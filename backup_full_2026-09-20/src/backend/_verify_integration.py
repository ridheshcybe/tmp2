"""Drive the cockpit in headless Chrome and verify the new integration end to end.

Usage:  python _verify_integration.py [url]

Assumes the backend is on :8081 and the dashboard dev server on :3000. Exercises
the panels the way a demonstrator would: start a mission, inject a fault, read
the report, replay a stored mission — reading the resulting DOM, not just the
network.

    python _verify_integration.py
"""
from __future__ import annotations

import contextlib
import json
import shutil
import sys
import time
import urllib.error
import urllib.request

from _verify_cutaway import DevTools, launch_chrome

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
BACKEND = "http://127.0.0.1:8081"
ENGINE = "TAPAS-BH-201-001"

problems: list[str] = []
notes: list[str] = []


def backend(method: str, path: str, body=None):
    req = urllib.request.Request(BACKEND + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data, timeout=20) as r:
        return json.loads(r.read().decode())


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        problems.append(label)
    return ok


# ── page helpers ─────────────────────────────────────────────────────────────

CLICK_TAB = """
(() => {
    const label = %s;
    const tabs = [...document.querySelectorAll('nav button')];
    const tab = tabs.find(b => b.textContent.trim().toLowerCase().includes(label.toLowerCase()));
    if (!tab) return { clicked: false, tabs: tabs.map(b => b.textContent.trim()) };
    tab.click();
    return { clicked: true, tabs: tabs.map(b => b.textContent.trim()) };
})()
"""

CLICK_TEXT = """
(() => {
    const wanted = %s;
    const nodes = [...document.querySelectorAll('button, a')];
    const el = nodes.find(n => n.textContent.trim().toLowerCase() === wanted.toLowerCase())
            || nodes.find(n => n.textContent.trim().toLowerCase().includes(wanted.toLowerCase()));
    if (!el) return { clicked: false, available: nodes.map(n => n.textContent.trim()).filter(Boolean).slice(0, 40) };
    el.click();
    return { clicked: true, text: el.textContent.trim() };
})()
"""

READ = """
(() => {
    const text = document.body.innerText;
    const btn = [...document.querySelectorAll('button')].map(b => b.textContent.trim());
    const selects = [...document.querySelectorAll('select')].map(s => ({
        value: s.value,
        options: [...s.options].map(o => o.textContent.trim()),
    }));
    return {
        text,
        buttons: btn,
        selects,
        nav: [...document.querySelectorAll('nav button')].map(b => b.textContent.trim()),
        selects_count: selects.length,
    };
})()
"""


def main() -> None:
    print(f"driving {URL}\n")

    with contextlib.suppress(Exception):
        backend("POST", "/api/faults/clear")
        backend("POST", "/api/simulation/throttle", {"throttle": 0.5})

    socket, profile, browser = launch_chrome(URL)
    try:
        devtools = DevTools(socket)
        devtools.send("Runtime.enable")
        devtools.send("Log.enable")
        devtools.collect(9)

        state = devtools.evaluate(READ)
        if not check("app rendered", "AeroTwin" in state["text"]):
            print(json.dumps(state, indent=2)[:1500])
            return

        check(
            "nav exposes the new views",
            all(any(v in tab for tab in state["nav"]) for v in ("Mission", "Diagnostics", "Reports")),
            " / ".join(state["nav"]),
        )

        # ── 1. mission control ───────────────────────────────────────────────
        print("\n1. Mission Control — start a mission from the UI")
        devtools.evaluate(CLICK_TAB % json.dumps("Mission"))
        devtools.collect(3)
        clicked = devtools.evaluate(CLICK_TEXT % json.dumps("Start mission"))
        check("start button present and clicked", clicked.get("clicked"), str(clicked.get("available", ""))[:160])
        devtools.collect(8)

        state = devtools.evaluate(READ)
        check("panel reports RUNNING", "RUNNING" in state["text"])
        status = backend("GET", "/api/simulation/status")
        check("backend confirms a running simulator", bool(status.get("is_running")), f"mission {str(status.get('mission_id'))[:8]}")
        running_mission = status.get("mission_id")

        # ── 2. telemetry reaching the cockpit ────────────────────────────────
        print("\n2. Telemetry — frames arriving over the WebSocket")
        frames_before = status.get("frame_id") or 0
        time.sleep(6)
        after = backend("GET", "/api/simulation/status")
        check("backend frame counter advanced", (after.get("frame_id") or 0) > frames_before,
              f"{frames_before} -> {after.get('frame_id')}")
        check("header shows a live frame count", "Frames" in devtools.evaluate(READ)["text"])

        # ── 3. physics residuals ─────────────────────────────────────────────
        print("\n3. Physics residuals — observed vs expected")
        devtools.evaluate(CLICK_TAB % json.dumps("Cockpit"))
        devtools.collect(4)
        text = devtools.evaluate(READ)["text"]
        check("residual panel has channel rows", "CHT residual" in text, "")
        check("residual table shows sigma column", "σ" in text)

        # ── 4. fault console ─────────────────────────────────────────────────
        print("\n4. Fault console — inject through the UI")
        devtools.evaluate(CLICK_TAB % json.dumps("Mission"))
        devtools.collect(3)
        state = devtools.evaluate(READ)
        backend_types = {t["type"] for t in backend("GET", "/api/faults/types")["fault_types"]}
        shown = {t for t in backend_types if any(t.replace("_", " ").lower() in b.lower() for b in state["buttons"])}
        check("console offers the backend's fault types", len(shown) >= 4,
              f"{len(shown)}/{len(backend_types)}: {sorted(shown)[:4]}")

        before = len(backend("GET", "/api/faults/history")["faults"])
        clicked = devtools.evaluate(CLICK_TEXT % json.dumps("Misfire"))
        check("inject button clicked", clicked.get("clicked"), str(clicked)[:120])
        devtools.collect(6)
        rows = backend("GET", "/api/faults/history")["faults"]
        new_rows = [r for r in rows if r["fault_type"] == "MISFIRE"]
        check("injection reached the backend", len(rows) > before and bool(new_rows),
              f"{before} -> {len(rows)} rows")
        check("incident log shows the fault in the UI", "Misfire" in devtools.evaluate(READ)["text"])

        # ── 5. escalation + report ───────────────────────────────────────────
        print("\n5. Escalation — the twin reacts, then the report summarises it")
        deadline = time.time() + 55
        peak = 0.0
        while time.time() < deadline:
            st = backend("GET", f"/api/engine/{ENGINE}/state")
            peak = max(peak, float(st.get("anomaly_score") or 0))
            if peak >= 80:
                break
            time.sleep(5)
        check("anomaly score escalates after injection", peak >= 60, f"peak anomaly {peak:.0f}")

        backend("POST", f"/api/missions/{running_mission}/stop")
        time.sleep(2)
        devtools.evaluate(CLICK_TAB % json.dumps("Reports"))
        devtools.collect(9)
        text = devtools.evaluate(READ)["text"]
        # The report body itself, not just the panel title.
        check("report renders the executive summary body", "Total telemetry frames" in text)
        check("report renders maintenance advisories", "Maintenance advisories" in text)
        check("report chart has timeline data", "Health & anomaly timeline" in text)

        # ── 6. replay ────────────────────────────────────────────────────────
        print("\n6. Replay — play a stored mission back")
        devtools.evaluate(CLICK_TAB % json.dumps("Diagnostics"))
        devtools.collect(4)
        state = devtools.evaluate(READ)
        picker = next((s for s in state["selects"] if any("frames" in o for o in s["options"])), None)
        check("replay offers stored missions", picker is not None,
              str([o for o in (picker or {}).get("options", [])][:2]))

        clicked = devtools.evaluate(CLICK_TEXT % json.dumps("Load Mission Data"))
        check("load button clicked", clicked.get("clicked"), str(clicked)[:120])
        devtools.collect(12)
        text = devtools.evaluate(READ)["text"]
        check("replay mode engaged", "REPLAY" in text)
        check("replay shows a frame position", "frame" in text.lower())

        # ── console health ───────────────────────────────────────────────────
        errors, warnings = [], []
        for event in devtools.events:
            if event.get("method") == "Runtime.exceptionThrown":
                details = event["params"].get("exceptionDetails", {})
                errors.append((details.get("exception", {}).get("description") or details.get("text", ""))[:200])
            elif event.get("method") == "Log.entryAdded":
                entry = event["params"]["entry"]
                if entry.get("level") == "error":
                    errors.append(entry.get("text", "")[:200])
                elif entry.get("level") == "warning":
                    warnings.append(entry.get("text", "")[:120])

        print(f"\nconsole: {len(errors)} errors, {len(warnings)} warnings")
        for line in errors[:8]:
            print("  error:", line.splitlines()[0])
        for line in warnings[:4]:
            print("  warn :", line)

        check("no uncaught exceptions or console errors", not errors,
              f"{len(errors)} seen" if errors else "")

        print(f"\n{'ALL CHECKS PASSED' if not problems else 'FAILURES: ' + '; '.join(problems)}")
    finally:
        with contextlib.suppress(Exception):
            browser.terminate()
            browser.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
