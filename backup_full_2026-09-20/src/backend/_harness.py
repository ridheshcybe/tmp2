"""Shared plumbing for the headless test drivers in this directory.

_hand.py, _probe.py and _scan.py each used to carry their own copy of the
same four steps: splice the test JavaScript into a copy of index.html, serve
that copy over HTTP, run headless Chrome against it, and read the JSON log
the page printed back out of Chrome's stderr.  All of that lives here once
now, and the JavaScript the drivers splice in lives in .js files next to them
(core.js, plus one per test) rather than in Python string literals.

So a driver is now just a call:

    import _harness as H
    H.run_test("scan", "_scan.js", budget=20000, shot="_i.png")

Everything is addressed relative to this file, so the drivers work no matter
which directory they are run from.
"""
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))

#: Splice points inside index.html's main script.
ANIMATE = "animate();"
SCENE = "const scene = new THREE.Scene();"
DELTA = "const delta = clock.getDelta();"

#: Chrome copies the page's console to stderr at these prefixes.
LOG_PREFIX = "TEST "

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


# ---------------------------------------------------------------- files ----

def path(name):
    return os.path.join(ROOT, name)


def index_html():
    """index.html: the page every driver here instruments and measures."""
    with open(path("index.html"), encoding="utf-8") as fh:
        return fh.read()


def js(name):
    """One of the harness JavaScript files, read fresh so edits take."""
    with open(path(name), encoding="utf-8") as fh:
        return fh.read()


def splice(html, marker, js_text, after=True):
    """Insert js_text at marker inside a copy of the page.

    The marker is asserted rather than replaced hopefully: if index.html is
    edited and the marker moves, the old code silently produced a page with
    no test in it, which looks exactly like a passing run.
    """
    if marker not in html:
        raise SystemExit(
            "cannot splice into index.html: %r is gone from the page.\n"
            "Update the marker in _harness.py to match." % marker)
    repl = marker + "\n" + js_text if after else js_text + "\n" + marker
    return html.replace(marker, repl, 1)


def instrumented(test_js, html=None):
    """index.html with core.js and a test script spliced in after animate()."""
    if html is None:
        html = index_html()
    return splice(html, ANIMATE, js("core.js") + "\n\n" + test_js)


# -------------------------------------------------------------- browser ----

def chrome():
    """Path to the browser binary, or a clear failure naming what was tried."""
    tried = [os.environ.get("CHROME")] + CHROME_CANDIDATES
    for candidate in tried:
        if candidate and os.path.exists(candidate):
            return candidate
    raise SystemExit("no Chrome found - set CHROME to the binary. Tried:\n  " +
                     "\n  ".join(c for c in tried if c))


def run_chrome(url, shot=None, budget=12000, size="1400,880"):
    """Run headless Chrome against url and return its stderr.

    stderr is how the page's console gets back out, so it is this function's
    return value rather than a debugging afterthought.  The profile is a
    fresh temp directory so that two drivers can run at once.

    --enable-unsafe-swiftshader plus --use-angle=swiftshader is what makes
    WebGL work at all once there is no GPU.
    """
    cmd = [chrome(), "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
           "--enable-unsafe-swiftshader", "--use-angle=swiftshader",
           "--hide-scrollbars", "--window-size=" + size,
           "--virtual-time-budget=" + str(budget),
           "--enable-logging=stderr", "--v=0"]

    if shot:
        cmd.append("--screenshot=" + os.path.abspath(shot))

    profile = tempfile.mkdtemp(prefix="chrome-probe-")
    cmd.append("--user-data-dir=" + profile)
    cmd.append(url)

    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              errors="replace").stderr
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def free_port():
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(url, tries=50, delay=0.1):
    """Block until the server answers, so Chrome never races its own start."""
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1).read(1)
            return
        except urllib.error.URLError:
            time.sleep(delay)
    raise SystemExit("static server never came up at " + url)


@contextlib.contextmanager
def serve(directory=ROOT):
    """Serve `directory` for the length of the with block.

    The port is picked per run, so two drivers can run at the same time; the
    fixed 8765 they used to share made that collide.
    """
    port = int(os.environ.get("PROBE_PORT") or 0) or free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=directory, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    base = "http://127.0.0.1:%d" % port

    try:
        wait_for(base)
        yield base
    finally:
        server.terminate()
        with contextlib.suppress(Exception):
            server.wait(timeout=10)


@contextlib.contextmanager
def serve_page(html, name):
    """Write html beside index.html, serve it, yield its URL, then tidy up.

    Index.html has to sit next to the scratch page - that is where the page
    fetches its STL files and textures from - so it cannot go in a temp
    directory.  Set PROBE_KEEP=1 to leave the scratch page behind for
    inspection.
    """
    page = "_probe_" + name + ".html"
    with open(path(page), "w", encoding="utf-8") as fh:
        fh.write(html)

    try:
        with serve() as base:
            yield base + "/" + page
    finally:
        if not os.environ.get("PROBE_KEEP"):
            with contextlib.suppress(OSError):
                os.remove(path(page))


# --------------------------------------------------------------- console ----

def console(stderr):
    """The page's console lines, as Chrome logged them."""
    out = []
    for line in stderr.splitlines():
        if "CONSOLE:" not in line and "Uncaught" not in line:
            continue
        text = line.split("CONSOLE:", 1)[-1].split(", source:", 1)[0].strip()
        out.append(text.strip('"').replace("\\n", " "))
    return out


def raw_lines(stderr, *needles):
    """Chrome stderr lines mentioning any needle, trimmed for printing."""
    return [line.split("] ", 1)[-1][:200]
            for line in stderr.splitlines() if any(n in line for n in needles)]


def test_log(stderr):
    """The `TEST <json array>` items a test reported, flattened.

    A page that threw, or that logged something the harness cannot parse,
    comes through verbatim: a broken test has to be visible in the output
    rather than silently missing from it.
    """
    items = []
    for text in console(stderr):
        if "Uncaught" in text:
            items.append("UNCAUGHT " + text)
        elif LOG_PREFIX in text:
            payload = text.split(LOG_PREFIX, 1)[-1]
            try:
                items.extend(json.loads(payload))
            except ValueError:
                items.append("RAW " + payload[:800])
    return items


# ---------------------------------------------------------------- driver ----

def run_test(name, script, budget=20000, shot=None):
    """Splice a test script into index.html, run it, print what it reported.

    `name` labels the scratch page, so the drivers stay out of each other's
    way.  A run that reports nothing at all is an error, not a pass.
    """
    html = instrumented(js(script))

    with serve_page(html, name) as url:
        stderr = run_chrome(url, shot=shot, budget=budget)

    items = test_log(stderr)

    if not items:
        tail = "\n".join(raw_lines(stderr, "Uncaught", "CONSOLE", "ERROR"))[-2000:]
        raise SystemExit("no " + LOG_PREFIX.strip() + " log came back from " +
                         script + " - the page threw before it could report:\n" + tail)

    for item in items:
        print("   " + str(item))
