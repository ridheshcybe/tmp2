"""Drive the AeroTwin dashboard in headless Chrome and report the whole chain.

Usage:  python _verify_cutaway.py [url] [seconds]

Checks that the live path actually works end to end, rather than that each
piece looks right on its own:

    backend -> WebSocket -> TelemetryContext -> React -> postMessage
            -> bridge -> cutaway viewer (RPM, CHT heatmap, cylinder indexing)

Needs the backend running (python -m uvicorn backend.main:app from sih/) with a
mission started, and the dashboard dev server on :3000.

Chrome is driven over the DevTools protocol rather than with a bare
--screenshot, because the check has to click into the Cutaway Twin view and
read the page's own state back out.
"""
import base64
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import numpy as np
from PIL import Image
from websockets.sync.client import connect

DEFAULT_URL = "http://localhost:3000"
PORT = 9222
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class DevTools:
    """A thin DevTools-protocol client: send one command, collect the events."""

    def __init__(self, url):
        self.ws = connect(url, max_size=None)
        self._id = 0
        self.events = []

    def send(self, method, **params):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self._id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})
            self.events.append(message)

    def collect(self, seconds):
        """Listen for `seconds`, absorbing any events that arrive."""
        end = time.time() + seconds
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                return
            try:
                self.events.append(json.loads(self.ws.recv(timeout=remaining)))
            except TimeoutError:
                return

    def evaluate(self, expression):
        result = self.send("Runtime.evaluate", expression=expression,
                           returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("text", "evaluate failed"))
        return result.get("result", {}).get("value")


def launch_chrome(url):
    """Start a debuggable headless Chrome and wait for its DevTools socket."""
    profile = tempfile.mkdtemp(prefix="chrome-verify-")
    browser = subprocess.Popen([
        CHROME, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--enable-unsafe-swiftshader", "--use-angle=swiftshader",
        "--hide-scrollbars", "--window-size=1600,1000",
        f"--remote-debugging-port={PORT}",
        "--user-data-dir=" + profile,
        url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=1) as r:
                targets = json.loads(r.read())
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                return pages[0]["webSocketDebuggerUrl"], profile, browser
        except Exception:
            pass
        time.sleep(0.5)

    browser.terminate()
    raise SystemExit("Chrome never opened a debugging port")


CLICK_CUTAWAY = """
(() => {
    const tab = [...document.querySelectorAll('nav button')]
        .find(b => b.textContent.includes('Cutaway Twin'));
    if (!tab) {
        return { clicked: false, tabs: [...document.querySelectorAll('nav button')].map(b => b.textContent.trim()) };
    }
    tab.click();
    return { clicked: true };
})()
"""

READ_STATE = """
(() => {
    const text = document.body.innerText;
    const out = {
        overlay: [...document.querySelectorAll('.data-display')].map(e => e.textContent.trim()),
        chips: [...document.querySelectorAll('.text-cockpit-muted')].map(e => e.textContent.trim()),
        faultChip: (text.match(/Injected fault[\\s\\S]{0,40}/) || [''])[0].replace(/\\s+/g, ' '),
        viewer: null,
    };

    const frame = document.querySelector('iframe');
    out.iframe = Boolean(frame);

    if (frame) {
        let doc = null;
        try { doc = frame.contentDocument; } catch (e) { doc = null; }

        /*
            engineBlock is a top-level `let` in the viewer, so it is a lexical
            global of that document, not a property of contentWindow - reading
            frame.contentWindow.engineBlock would prove nothing either way.
            The indexed-cylinder count in the cockpit is the real evidence
            that the viewer's model loaded.
        */
        out.viewer = {
            sameOrigin: Boolean(doc),
            bridgeLoaded: Boolean(frame.contentWindow && frame.contentWindow.__aerotwinBridge),
            speed: doc ? doc.getElementById('speed').value : null,
            speedMax: doc ? doc.getElementById('speed').max : null,
            hud: doc ? doc.getElementById('rpm').textContent.slice(0, 110) : null,
            tint: (frame.contentWindow && frame.contentWindow.__aerotwinTint)
                ? JSON.parse(JSON.stringify(frame.contentWindow.__aerotwinTint))
                : null,
        };
    }

    return out;
})()
"""

TOGGLE_HEATMAP = """
(() => {
    const label = [...document.querySelectorAll('label')]
        .find(l => l.textContent.includes('CHT heatmap'));
    if (!label) return { toggled: false };
    const box = label.querySelector('input[type=checkbox]');
    if (!box) return { toggled: false };
    box.click();
    return { toggled: true, checked: box.checked };
})()
"""


POST_HOT_FRAME = """
(() => {
    const frame = document.querySelector('iframe');
    if (!frame) return { posted: false };

    /*  A frame the live stream would never produce: every cylinder well past
        the tint's 150 C threshold, so the heatmap has something to show.  */
    frame.contentWindow.postMessage({
        type: 'AEROTWIN_TELEMETRY',
        payload: { rpm: 2400, cht: [232, 226, 236, 229], egt: [705, 690, 712, 700], injected_fault: null },
        options: { followRpm: true, heatmap: true },
    }, '*');

    return { posted: true };
})()
"""

BACKEND = "http://127.0.0.1:8081"


def _get(path):
    with urllib.request.urlopen(BACKEND + path, timeout=15) as response:
        return json.loads(response.read() or b"{}")


def _post(path, payload=None):
    body = json.dumps(payload or {}).encode()
    request = urllib.request.Request(BACKEND + path, data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read() or b"{}")


def start_mission(duration_s=600):
    return _post("/api/missions/start", {"duration_s": duration_s})


def stop_mission():
    """Stop the running mission, if any, so no frames are being broadcast."""
    listing = _get("/api/missions")
    missions = listing.get("missions") if isinstance(listing, dict) else listing
    for mission in missions or []:
        if str(mission.get("status")) == "RUNNING":
            return _post(f"/api/missions/{mission['mission_id']}/stop")
    return {"status": "nothing running"}


def inject_fault(fault_type="OVERHEATING", severity=0.9):
    """Ask the backend to inject a fault, the same call the demo panel makes."""
    return _post("/api/faults/inject", {"fault_type": fault_type, "severity": severity})


def shoot(devtools, name):
    shot = devtools.send("Page.captureScreenshot", format="png")
    path = os.path.abspath(name)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(shot["data"]))
    return path


def viewer_region(path):
    """The left two thirds: the cutaway panel, not the sidebar widgets."""
    image = np.asarray(Image.open(path).convert("RGB")).astype(float)
    return image[:, : int(image.shape[1] * 0.66), :]


def compare(path_a, path_b):
    """How much two frames of the viewer differ, and how amber each is."""
    a, b = viewer_region(path_a), viewer_region(path_b)
    if a.shape != b.shape:
        return {"error": f"shape mismatch {a.shape} vs {b.shape}"}
    amber = ((a[:, :, 0] - a[:, :, 2] > 40) & (a[:, :, 0] > 90)).mean()
    return {
        "mean_abs_diff": round(float(np.abs(a - b).mean()), 2),
        "changed_pct": round(float((np.abs(a - b).max(2) > 12).mean() * 100), 2),
        "amber_fraction": round(float(amber), 4),
        "brightness": round(float(a.mean()), 1),
    }


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    settle = float(sys.argv[2]) if len(sys.argv) > 2 else 14.0

    if not os.path.exists(CHROME):
        raise SystemExit("no Chrome at " + CHROME)

    print(f"Driving {url} ...")

    devtools_url, profile, browser = launch_chrome(url)

    try:
        devtools = DevTools(devtools_url)
        devtools.send("Page.enable")
        devtools.send("Runtime.enable")

        # Let the app boot, connect its socket and render the cockpit.
        devtools.collect(6)

        print("  clicking into the Cutaway Twin view ->", devtools.evaluate(CLICK_CUTAWAY))

        # The viewer loads two STLs, the bridge is injected on load, and the
        # bridge indexes the cylinders once the block has parsed.
        devtools.collect(settle)

        state = devtools.evaluate(READ_STATE)

        print("\n  page state")
        print("    iframe           :", state.get("iframe"))
        print("    overlay readouts :", state.get("overlay"))
        print("    fault chip       :", state.get("faultChip") or "(none)")
        print("    chips            :", [c for c in state.get("chips", []) if c])
        print("    viewer           :", json.dumps(state.get("viewer"), indent=6)[6:])

        live = shoot(devtools, "_cutaway_live.png")
        print(f"\n  screenshot -> {live}")

        # ── Does the CHT heatmap actually change the render? ─────────────
        #
        #  The cockpit pushes a frame every 100 ms, so a synthetic frame is
        #  overwritten almost immediately.  Stopping the mission first is what
        #  makes the tint observable at all.

        print("\n  stopping the mission so the stream goes quiet:", stop_mission())
        devtools.collect(2)

        print("  posting a synthetic 230 C frame ->", devtools.evaluate(POST_HOT_FRAME))
        devtools.collect(1)
        hot = shoot(devtools, "_cutaway_hot.png")

        #  The bridge's own tint state is the verdict here: a pixel diff would
        #  be confounded by the crank still turning and the flames jittering.
        tinted = devtools.evaluate(READ_STATE).get("viewer") or {}
        print("    bridge tint state :", tinted.get("tint"))

        print("  toggling the CHT heatmap off ->", devtools.evaluate(TOGGLE_HEATMAP))
        devtools.collect(2)
        hot_off = shoot(devtools, "_cutaway_hot_off.png")

        cleared = devtools.evaluate(READ_STATE).get("viewer") or {}
        print("    tint after off    :", cleared.get("tint"))
        print("    pixels on vs off  :", compare(hot, hot_off))

        # ── And the real path: a fault through the API to the cockpit ─────

        print("\n  restarting a mission ->", start_mission())
        print("  injecting OVERHEATING ->", inject_fault())
        devtools.collect(9)

        after = devtools.evaluate(READ_STATE)
        print("    overlay readouts :", after.get("overlay"))
        print("    fault chip       :", after.get("faultChip") or "(none)")
        print("    viewer hud       :", (after.get("viewer") or {}).get("hud"))

        errors = []
        console = []

        for event in devtools.events:
            method = event.get("method")
            params = event.get("params", {})

            if method == "Runtime.consoleAPICalled":
                text = " ".join(str(a.get("value", "")) for a in params.get("args", []))
                if text.strip():
                    console.append(f"{params.get('type')}: {text[:160]}")
            elif method == "Runtime.exceptionThrown":
                details = params.get("exceptionDetails", {})
                errors.append(details.get("exception", {}).get("description")
                              or details.get("text", "unknown"))

        print("\n  console (last 12)")
        for line in console[-12:]:
            print("   ", line)

        if errors:
            print("\n  EXCEPTIONS")
            for line in errors[:6]:
                print("   ", (line or "").splitlines()[0][:200])
        else:
            print("\n  no exceptions")
    finally:
        browser.terminate()
        with contextlib.suppress(Exception):
            browser.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
