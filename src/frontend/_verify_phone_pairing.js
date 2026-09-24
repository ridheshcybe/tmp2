/*
    E2E verification of the phone-pairing flow, the sibling of
    src/backend/_verify_cutaway.py.

    Two headless Chrome instances on this machine:

        desktop  opens  http://localhost:8000/cutaway.html  and calls
                 startPhonePair()  ->  parks its offer on serve.py
        phone    opens  the tunnel QR link  .../phone.html?key=...#p=<token>
                 and runs its real autoPair(): fetch offer, fake camera,
                 post answer back through the tunnel

    What is proven end to end:

        1. offer parking + token through ngrok (keyed relays)
        2. phone fetches the offer through the tunnel and answers
        3. desktop's poll picks the answer up, WebRTC connects
        4. the "ctl" data channel opens both ways
        5. a PHONE_CMD from the phone lands on the desktop
        6. a PHONE_STATE echo from the desktop lands on the phone
        7. the /__ctl REST fallback queues a command

    Usage:  node _verify_phone_pairing.js
    Needs:  serve.py on :8000 (with AEROTWIN_KEY), the ngrok tunnel up,
            backend on :8081, Google Chrome installed.
*/
const fs = require("fs");
const { spawn } = require("child_process");

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const KEY_FILE = "/tmp/aerotwin_key.txt";
const NGROK_API = "http://127.0.0.1:4040/api/tunnels";

/*
    Local mode (default): desktop on serve.py :8000, phone through the
    ngrok tunnel discovered on :4040.
    Prod mode:  PAIR_E2E_URL=https://aerotwin-up6k.onrender.com node _verify_phone_pairing.js
    -> both pages run against that origin (the FastAPI backend relay),
    AEROTWIN_KEY / AEROTWIN_API_KEY picked up from the environment when set.
*/
const ORIGIN = (process.env.PAIR_E2E_URL || "").replace(/\/$/, "");
const DESKTOP_URL = ORIGIN ? ORIGIN + "/cutaway.html"
                           : "http://localhost:8000/cutaway.html";
const PHONE_UA = "AeroTwinPairTest/1.0";   // non-browser UA: skips ngrok's interstitial

const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ---- tiny CDP client over the page's WebSocket ------------------------ */

class Page {
    constructor(wsUrl) {
        this.ws = new WebSocket(wsUrl);
        this._id = 0;
        this._pending = new Map();
        this.events = [];
        this.ws.addEventListener("message", ev => {
            const msg = JSON.parse(ev.data);
            if (msg.id && this._pending.has(msg.id)) {
                const { resolve, reject } = this._pending.get(msg.id);
                this._pending.delete(msg.id);
                if (msg.error) reject(new Error(msg.error.message));
                else resolve(msg.result || {});
            } else {
                this.events.push(msg);
            }
        });
    }
    get ready() { return this.ws.readyState === 1; }
    send(method, params = {}) {
        return new Promise((resolve, reject) => {
            const id = ++this._id;
            this._pending.set(id, { resolve, reject });
            this.ws.send(JSON.stringify({ id, method, params }));
        });
    }
    async evaluate(expression) {
        const r = await this.send("Runtime.evaluate", {
            expression, returnByValue: true, awaitPromise: true,
        });
        if (r.exceptionDetails) {
            throw new Error("evaluate: " +
                (r.exceptionDetails.exception?.description ||
                 r.exceptionDetails.text));
        }
        return r.result?.value;
    }
    errors() {
        return this.events
            .filter(e => e.method === "Runtime.exceptionThrown")
            .map(e => e.params.exceptionDetails.exception?.description ||
                      e.params.exceptionDetails.text || "unknown")
            .slice(0, 5);
    }
}

async function launchChrome(port, label, flags, url) {
    const profile = fs.mkdtempSync(`/tmp/chrome-${label}-`);
    const child = spawn(CHROME, [
        "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--enable-unsafe-swiftshader", "--use-angle=swiftshader",
        "--hide-scrollbars", "--window-size=1280,900",
        `--remote-debugging-port=${port}`,
        `--user-data-dir=${profile}`,
        ...flags, url,
    ], { stdio: "ignore" });

    for (let i = 0; i < 60; i++) {
        try {
            const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
            const page = list.find(t => t.type === "page");
            if (page) {
                const p = new Page(page.webSocketDebuggerUrl);
                for (let j = 0; j < 40 && !p.ready; j++) await sleep(100);
                await p.send("Page.enable");
                await p.send("Runtime.enable");
                return { child, profile, page: p };
            }
        } catch (e) { /* chrome not up yet */ }
        await sleep(500);
    }
    child.kill();
    throw new Error(`${label} chrome never opened its debugging port`);
}

async function tunnelUrl() {
    if (ORIGIN) return ORIGIN;              // prod mode: same origin for both peers
    const data = await (await fetch(NGROK_API)).json();
    const tun = (data.tunnels || []).find(t => (t.public_url || "").startsWith("https://"));
    if (!tun) throw new Error("ngrok tunnel is not up");
    return tun.public_url.replace(/\/$/, "");
}

const results = [];
const check = (name, ok, detail = "") => {
    results.push({ name, ok, detail });
    console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  -  " + detail : ""}`);
};

(async () => {
    const KEY = process.env.AEROTWIN_KEY ||
        ((fs.readFileSync(KEY_FILE, "utf8").match(/AEROTWIN_KEY=(\S+)/) || [])[1] || "");
    const TUNNEL = await tunnelUrl();
    console.log(`mode   : ${ORIGIN ? "prod (FastAPI relay)" : "local (serve.py + ngrok)"}`);
    console.log(`origin : ${TUNNEL}\n`);

    const desk = await launchChrome(9222, "desk",
        [], DESKTOP_URL);
    const phone = await launchChrome(9223, "phone",
        ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
        "about:blank");

    try {
        // The cutaway scene (three.js + STLs) needs a moment to boot.
        await sleep(7000);

        /* 1 ── desktop parks its offer ---------------------------------- */
        console.log("[desktop] startPhonePair()");
        await desk.page.evaluate("startPhonePair()");
        const token = await desk.page.evaluate("PHONE.token");
        const deskStatus = await desk.page.evaluate(
            "document.getElementById('pairState').textContent");
        check("offer parked under a token", !!token,
            `token=${token || "(none)"}  desktop="${deskStatus}"`);

        /* 2 ── phone opens the QR link through the tunnel ---------------- */
        const qrLink = `${TUNNEL}/phone.html` +
            (KEY ? `?key=${encodeURIComponent(KEY)}` : "") + `#p=${token}`;
        console.log("[phone] opening QR link through the tunnel ...");
        await phone.page.send("Emulation.setUserAgentOverride",
            { userAgent: PHONE_UA });
        await phone.page.send("Page.navigate", { url: qrLink });
        await sleep(3000);

        let phoneStatus = "", phoneDetail = "";
        for (let i = 0; i < 15; i++) {
            phoneStatus = await phone.page.evaluate(
                "document.getElementById('status').textContent");
            phoneDetail = await phone.page.evaluate(
                "document.getElementById('detail').textContent");
            if (/camera live|paired/i.test(phoneStatus) ||
                /paired/i.test(phoneDetail)) break;
            await sleep(1000);
        }
        check("phone fetched the offer + posted its answer (through ngrok, keyed)",
            /camera live|paired/.test(phoneStatus) || /paired/.test(phoneDetail),
            `status="${phoneStatus}"  detail="${phoneDetail}"`);

        /* 3 ── WebRTC connect -------------------------------------------- */
        let deskConn = "", phoneConn = "";
        for (let i = 0; i < 25; i++) {
            deskConn = await desk.page.evaluate(
                "PHONE.pc ? PHONE.pc.connectionState : 'none'");
            phoneConn = await phone.page.evaluate(
                "pc ? pc.connectionState : 'none'");
            if (deskConn === "connected" && phoneConn === "connected") break;
            await sleep(1000);
        }
        check("WebRTC peer connection established", deskConn === "connected" &&
            phoneConn === "connected", `desktop=${deskConn} phone=${phoneConn}`);

        let deskFinal = "";
        for (let i = 0; i < 15; i++) {
            deskFinal = await desk.page.evaluate(
                "document.getElementById('pairState').textContent");
            if (/phone camera live/.test(deskFinal)) break;
            await sleep(1000);
        }
        check("desktop reached 'phone camera live'",
            /phone camera live/.test(deskFinal), `pairState="${deskFinal}"`);

        /* 4 ── data channel both ways ------------------------------------- */
        const dcState = await desk.page.evaluate(
            "PHONE.channel ? PHONE.channel.readyState : 'none'");
        check("desktop ctl data channel open", dcState === "open",
            `readyState=${dcState}`);

        await desk.page.evaluate(
            "window.__lastCmd = null; " +
            "PHONE.channel.addEventListener('message', e => { window.__lastCmd = e.data; });");
        await phone.page.evaluate("sendCmd('throttle', 0.72)");
        await sleep(1500);
        const got = await desk.page.evaluate("window.__lastCmd");
        let cmdOk = false, cmdParsed = null;
        try { cmdParsed = JSON.parse(got); cmdOk =
            cmdParsed.type === "PHONE_CMD" && cmdParsed.cmd === "throttle" &&
            Math.abs(cmdParsed.value - 0.72) < 1e-9; } catch (e) {}
        check("PHONE_CMD phone -> desktop over the data channel", cmdOk,
            `received=${got || "(nothing)"}`);

        await desk.page.evaluate(
            "PHONE.channel.send(JSON.stringify({type:'PHONE_STATE'," +
            "phase:'MANUAL', rpm:1234, throttle:0.72}))");
        await sleep(1000);
        const rpm = await phone.page.evaluate(
            "document.getElementById('phRpm').textContent");
        const lever = await phone.page.evaluate(
            "document.getElementById('lever').value");
        check("PHONE_STATE desktop -> phone updates the controller UI",
            rpm === "1,234" && lever === "72",
            `phRpm="${rpm}"  lever="${lever}"`);

        /* 5 ── video track arriving on the desktop ------------------------ */
        const video = await desk.page.evaluate(
            "(() => { const v = document.getElementById('handVideo');" +
            "return { src: !!v.srcObject," +
            "tracks: PHONE.pc.getReceivers().map(r => r.track.kind + ':' + r.track.readyState) }; })()");
        check("phone camera video reached the desktop",
            video.src && video.tracks.includes("video:live"),
            JSON.stringify(video));

        /* 6 ── REST fallback through the tunnel --------------------------- */
        const postStatus = await phone.page.evaluate(
            "fetch('/__ctl' + (KEY ? '?key=' + encodeURIComponent(KEY) : ''), " +
            "{ method: 'POST', headers: Object.assign({'Content-Type': 'application/json'}," +
            " KEY ? { 'x-aerotwin-key': KEY } : {})," +
            "body: JSON.stringify({ cmd: 'preset', value: 'cruise' }) })" +
            ".then(r => r.status)");
        await sleep(500);
        const queue = await (await fetch(
            `http://localhost:8000/__ctl?since=0`)).json();
        const queued = queue.commands.some(c => c.cmd === "preset" &&
            c.value === "cruise");
        check("__ctl REST fallback queues a command (keyed, via tunnel)",
            postStatus === 200 && queued,
            `POST=${postStatus}  queued=${queued}  queue=${JSON.stringify(queue.commands)}`);

        /* ── console errors on either side -------------------------------- */
        const deskErrs = desk.page.errors(), phoneErrs = phone.page.errors();
        check("no page exceptions", deskErrs.length === 0 && phoneErrs.length === 0,
            [...deskErrs, ...phoneErrs].join(" | ").slice(0, 300));

    } finally {
        console.log("");
        const failed = results.filter(r => !r.ok).length;
        console.log(failed === 0
            ? `[SUCCESS] pairing E2E: ${results.length}/${results.length} checks passed`
            : `[FAILED] ${failed}/${results.length} checks failed`);
        for (const p of [desk, phone]) {
            try { await p.page.send("Page.close"); } catch (e) {}
            p.child.kill();
        }
        process.exit(failed === 0 ? 0 : 1);
    }
})().catch(e => { console.error("[ERROR]", e.message); process.exit(2); });
