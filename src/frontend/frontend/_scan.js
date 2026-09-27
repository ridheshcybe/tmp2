/*
    Interaction test: does clicking and switching anything actually work?

    Spliced into a copy of index.html by _scan.py alongside core.js, then
    driven with real pointer events at the canvas - the same events the page
    listens for - so this exercises the real handlers rather than calling
    them directly.
*/

setTimeout(() => {

    const log = [];
    const cv = renderer.domElement;

    /*  -----------------------------------------------------------------
        Where is everything on screen?  Also proves every region either
        picks a system or is honestly empty.
        ----------------------------------------------------------------- */
    const seen = {};

    for (let x = 260; x <= 1120; x += 60) {
        for (let y = 160; y <= 760; y += 60) {
            const hit = pickAt(x, y);
            const key = hit ? hit.system + (hit.cyl ? "|cyl" + hit.cyl : "") : "-";
            (seen[key] = seen[key] || []).push(x + "," + y);
        }
    }

    for (const k of Object.keys(seen).sort()) {
        log.push(k + " x" + seen[k].length + " e.g. " + seen[k][0]);
    }

    /*  -----------------------------------------------------------------
        Cut a cylinder from the chip strip.
        ----------------------------------------------------------------- */
    const chips = document.querySelectorAll(".cyl");

    if (chips.length > 2) {
        chips[2].dispatchEvent(new MouseEvent("click", { bubbles: true }));
        log.push("chip click -> cut=[" + [...TUNE.cut].join(",") + "] class=" + chips[2].className);
    } else {
        log.push("chip strip has only " + chips.length + " chips - cannot test a cylinder cut");
    }

    /*  -----------------------------------------------------------------
        And through the panel, for a picked piston.
        ----------------------------------------------------------------- */
    let ps = null;

    for (const k of Object.keys(seen)) {
        if (k.indexOf("piston") === 0) { ps = seen[k][0].split(",").map(Number); break; }
    }

    if (ps) {

        cv.dispatchEvent(new PointerEvent("pointerdown",
            { clientX: ps[0], clientY: ps[1], bubbles: true }));
        cv.dispatchEvent(new MouseEvent("click",
            { clientX: ps[0], clientY: ps[1], bubbles: true }));

        log.push("piston panel: " + document.getElementById("partTitle").textContent);

        const b = [...document.querySelectorAll("#partControls button")];
        log.push("buttons " + b.length + " -> " + (b[0] ? b[0].textContent : "-"));

        if (b.length) {
            /*  First click restores cylinder 3 (cut above), second cuts.  */
            b[0].click();
            log.push("after button: cut=[" + [...TUNE.cut].join(",") + "]");
        }
    }

    /*  -----------------------------------------------------------------
        Air inflow from the intake panel, and check it reaches the streams.
        ----------------------------------------------------------------- */
    const air = seen["intake"] ? seen["intake"][0].split(",").map(Number) : null;

    if (air) {

        cv.dispatchEvent(new PointerEvent("pointerdown",
            { clientX: air[0], clientY: air[1], bubbles: true }));
        cv.dispatchEvent(new MouseEvent("click",
            { clientX: air[0], clientY: air[1], bubbles: true }));

        const ins = [...document.querySelectorAll("#partControls input")];

        log.push("intake panel inputs=" + ins.length +
                 " labels=" + [...document.querySelectorAll("#partControls label")]
                     .map(l => l.textContent).join("/"));

        if (ins.length) {
            ins[0].value = 0;
            ins[0].dispatchEvent(new Event("input"));
            log.push("air now " + TUNE.air);
        }
    }

    /*  -----------------------------------------------------------------
        Ignition advance from the plugs panel.
        ----------------------------------------------------------------- */
    const pl = seen["plugs"] ? seen["plugs"][0].split(",").map(Number) : null;

    if (pl) {

        cv.dispatchEvent(new PointerEvent("pointerdown",
            { clientX: pl[0], clientY: pl[1], bubbles: true }));
        cv.dispatchEvent(new MouseEvent("click",
            { clientX: pl[0], clientY: pl[1], bubbles: true }));

        const ins = [...document.querySelectorAll("#partControls input")];

        log.push("plugs panel inputs=" + ins.length);

        if (ins.length) {
            ins[ins.length - 1].value = 0;
            ins[ins.length - 1].dispatchEvent(new Event("input"));
            log.push("last control now " + TUNE.advance + " (advance) / air " + TUNE.air);
        }
    }

    log.push("data-tip elements=" + document.querySelectorAll("[data-tip]").length);
    log.push("cut stages=" + SYSTEM_ORDER.map(s => s.key).join(","));

    HARNESS.report(log);
}, 2200);
