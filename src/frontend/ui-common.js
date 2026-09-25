/*
    AeroTwin shared UI helpers - loaded by every standalone page, after
    engine-spec.js and aerotwin-api.js.

    Three jobs, all of them things the UI report flagged as per-page
    inconsistencies:

    1. RESPONSIVE NAV
       On a phone or a narrow window the 16rem sidebar used to sit in the
       flow and cover the main content.  Any <aside data-nav> now becomes
       an off-canvas drawer below 1024px, opened by a menu button that this
       file injects into the header, and closed by the backdrop, Esc or
       following a link.

    2. HONEST FEED STATE
       autoConn() renders ONE status vocabulary on every page - LIVE /
       POLLING / OLD DATA / OFFLINE - from the API client's own frame age,
       instead of each page hard-coding a green "LIVE" badge.

    3. SMALL SHARED BITS
       "Updated 2s ago" text, a copy-with-feedback helper, and a toast.

    Markup hooks:
      <aside data-nav>                     -> becomes the drawer
      #connBadge / #connDot / #connLabel   -> the status chip
      [data-conn-short]                    -> text set to LIVE / OLD DATA / ...
      [data-conn-dot]                      -> dot recoloured to match
      [data-updated]                       -> "Updated 2s ago"
      [data-demo-badge]                    -> shown only while source=demo
*/
(function () {
    "use strict";

    const CSS = `
        #navToggle { display: none; }

        @media (max-width: 1023px) {
            #navToggle {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 34px;
                height: 34px;
                flex: 0 0 auto;
                border-radius: 8px;
                border: 1px solid #e2ded6;
                background: #ffffff;
                color: #1a1a1a;
                cursor: pointer;
            }

            aside[data-nav] {
                position: fixed;
                top: 3.5rem;              /* clears the sticky header */
                bottom: 0;
                left: 0;
                width: 16rem;
                z-index: 60;
                transform: translateX(-102%);
                transition: transform 0.22s ease;
                box-shadow: 0 18px 40px rgba(0, 0, 0, 0.28);
            }

            aside[data-nav].drawer-open { transform: translateX(0); }

            #navBackdrop {
                display: block;
                position: fixed;
                inset: 3.5rem 0 0 0;
                background: rgba(20, 18, 15, 0.45);
                z-index: 55;
                opacity: 0;
                pointer-events: none;
                transition: opacity 0.22s ease;
            }

            #navBackdrop.open { opacity: 1; pointer-events: auto; }
        }

        [data-conn="live"]    { color: #047857; }
        [data-conn="polling"] { color: #b45309; }
        [data-conn="old"]     { color: #b45309; }
        [data-conn="offline"] { color: #78716c; }

        .aero-updated { font-variant-numeric: tabular-nums; }

        #toast {
            position: fixed;
            left: 50%;
            bottom: 20px;
            transform: translateX(-50%) translateY(8px);
            background: #1a1a1a;
            color: #ffffff;
            font: 600 12px/1 "Inter", sans-serif;
            padding: 9px 15px;
            border-radius: 9999px;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.18s, transform 0.18s;
            z-index: 300;
        }

        #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
    `;

    function injectCss() {
        if (document.getElementById("aero-ui-css")) return;
        const style = document.createElement("style");
        style.id = "aero-ui-css";
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    /* ------------------------------------------------------------------ */
    /*  1. responsive nav                                                  */
    /* ------------------------------------------------------------------ */

    function initNav() {
        const aside = document.querySelector("aside[data-nav]");
        const header = document.querySelector("header");
        if (!aside || !header) return;
        if (document.getElementById("navToggle")) return;

        const btn = document.createElement("button");
        btn.id = "navToggle";
        btn.type = "button";
        btn.setAttribute("aria-label", "Show navigation");
        btn.setAttribute("aria-expanded", "false");
        btn.innerHTML =
            '<span class="material-symbols-outlined text-[20px]">menu</span>';

        /*  Ride inside the header's first flex row so the existing gap
            spacing applies and the brand stays where it was.  */
        const row = header.firstElementChild;
        if (row) row.insertBefore(btn, row.firstChild);
        else header.insertBefore(btn, header.firstChild);

        const backdrop = document.createElement("div");
        backdrop.id = "navBackdrop";
        document.body.appendChild(backdrop);

        function setOpen(on) {
            aside.classList.toggle("drawer-open", on);
            backdrop.classList.toggle("open", on);
            btn.setAttribute("aria-expanded", on ? "true" : "false");
        }

        btn.addEventListener("click", () => {
            setOpen(!aside.classList.contains("drawer-open"));
        });
        backdrop.addEventListener("click", () => setOpen(false));
        document.addEventListener("keydown", e => {
            if (e.key === "Escape") setOpen(false);
        });
        aside.addEventListener("click", e => {
            if (e.target.closest("a")) setOpen(false);
        });
        window.addEventListener("resize", () => {
            if (window.innerWidth >= 1024) setOpen(false);
        });
    }

    /* ------------------------------------------------------------------ */
    /*  2. honest feed state                                               */
    /* ------------------------------------------------------------------ */

    const CONN = {
        live: {
            label: "STATUS: LIVE", short: "LIVE",
            dot: "bg-emerald-500",
            chip: "bg-emerald-50 text-emerald-700 border-emerald-200",
            pulse: true
        },
        polling: {
            label: "STATUS: POLLING", short: "POLLING",
            dot: "bg-amber-500",
            chip: "bg-amber-50 text-amber-700 border-amber-200",
            pulse: false
        },
        old: {
            label: "STATUS: OLD DATA", short: "OLD DATA",
            dot: "bg-amber-600",
            chip: "bg-amber-100 text-amber-800 border-amber-300",
            pulse: false
        },
        offline: {
            label: "STATUS: DEMO MODE", short: "OFFLINE",
            dot: "bg-stone-400",
            chip: "bg-stone-100 text-stone-600 border-stone-300",
            pulse: false
        }
    };

    function connInfo(state) { return CONN[state] || CONN.offline; }

    /*
        Render the feed state everywhere it appears, and keep re-rendering it
        once a second so a feed that goes quiet flips to OLD DATA on its own
        rather than sitting on a stale green "LIVE".
    */
    function autoConn(api, onChange) {
        const client = api || window.AEROTWIN_API;

        function apply() {
            const state = client && client.feedState ? client.feedState() : "offline";
            const info = connInfo(state);

            const badge = document.getElementById("connBadge");
            const dot = document.getElementById("connDot");
            const label = document.getElementById("connLabel");

            if (badge) {
                badge.className = "inline-flex items-center gap-1.5 px-2.5 py-0.5 " +
                    "rounded-full text-[11px] font-mono font-medium border " + info.chip;
            }
            if (dot) {
                dot.className = "w-1.5 h-1.5 rounded-full " + info.dot +
                    (info.pulse ? " animate-pulse" : "");
            }
            if (label) label.textContent = info.label;

            document.querySelectorAll("[data-conn-short]").forEach(el => {
                el.textContent = info.short;
                el.dataset.conn = state;
            });
            document.querySelectorAll("[data-conn-dot]").forEach(el => {
                el.className = "w-1.5 h-1.5 rounded-full " + info.dot +
                    (info.pulse ? " animate-pulse" : "");
            });

            if (onChange) onChange(state, info);

            return state;
        }

        apply();
        if (client && client.onStatus) client.onStatus(apply);
        setInterval(apply, 1000);

        return apply;
    }

    /* ------------------------------------------------------------------ */
    /*  3. shared bits                                                     */
    /* ------------------------------------------------------------------ */

    function ageText(ms) {
        if (ms == null || !isFinite(ms)) return "no data";
        const s = Math.max(0, Math.round(ms / 1000));
        if (s < 1) return "just now";
        if (s < 60) return s + "s ago";
        const m = Math.floor(s / 60);
        if (m < 60) return m + "m " + (s % 60) + "s ago";
        return Math.floor(m / 60) + "h ago";
    }

    /*  Fill every [data-updated] element with "Updated 2s ago".  */
    function tickUpdated(api) {
        const client = api || window.AEROTWIN_API;

        function apply() {
            const txt = client && client.ageMs != null
                ? "Updated " + ageText(client.ageMs)
                : "Updated --";
            document.querySelectorAll("[data-updated]").forEach(el => {
                el.textContent = txt;
            });
        }

        apply();
        setInterval(apply, 1000);
    }

    /*  Show [data-demo-badge] while the offline generator is feeding.  */
    function demoBadges(api) {
        const client = api || window.AEROTWIN_API;

        function apply() {
            const demo = !!(client && client.frame && client.frame.source === "demo");
            document.querySelectorAll("[data-demo-badge]").forEach(el => {
                el.classList.toggle("hidden", !demo);
            });
        }

        apply();
        if (client && client.onFrame) client.onFrame(apply);
    }

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    let toastTimer = null;

    function toast(message) {
        let el = document.getElementById("toast");
        if (!el) {
            el = document.createElement("div");
            el.id = "toast";
            document.body.appendChild(el);
        }
        el.textContent = message;
        el.classList.add("show");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => el.classList.remove("show"), 1700);
    }

    /*  Copy with visible confirmation - the report found the old copy button
        gave no feedback at all.  */
    async function copy(text, message) {
        const ok = "Copied";
        try {
            await navigator.clipboard.writeText(text);
            toast(message || ok);
            return true;
        } catch (e) {
            toast("Copy failed - select and copy manually");
            return false;
        }
    }

    function init() {
        injectCss();
        initNav();
        tickUpdated();
        demoBadges();
    }

    window.AeroUI = {
        connInfo: connInfo,
        autoConn: autoConn,
        tickUpdated: tickUpdated,
        demoBadges: demoBadges,
        ageText: ageText,
        toast: toast,
        copy: copy,
        esc: esc,
        CONN: CONN
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
