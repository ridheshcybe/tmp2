/*
    Hand control and tooltip coverage, without a camera.

    Spliced into a copy of index.html by _hand.py alongside core.js, so the
    page's own functions (countFingers, applyHandCount, stopHand, HAND,
    pickAt) and the HARNESS helpers are both in scope.

    Every branch below has to stay honest: the camera is driven to failure on
    purpose, and the page must survive it with its UI intact.
*/

setTimeout(async () => {

    const log = [];

    /*  -----------------------------------------------------------------
        Finger counting, pose by pose.  One finger is one system, so this
        has to be right before the rest is worth checking.
        ----------------------------------------------------------------- */
    const poses = {
        "open hand (all five)": ["thumb", "index", "middle", "ring", "pinky"],
        "fist": [],
        "one finger": ["index"],
        "two fingers": ["index", "middle"],
        "three fingers": ["index", "middle", "ring"],
        "four fingers": ["index", "middle", "ring", "pinky"]
    };

    for (const name of Object.keys(poses)) {
        log.push("countFingers " + name + " = " +
                 countFingers(HARNESS.makeHand(poses[name])));
    }
    log.push("countFingers empty landmarks = " + countFingers(null));

    /*  -----------------------------------------------------------------
        ... and the count has to peel that many systems off the engine.
        ----------------------------------------------------------------- */
    const stages = SYSTEM_ORDER.length;
    const slider = document.getElementById("cutSystems");
    const hud = document.getElementById("syscut");

    for (const fingers of [0, 1, 3, 5]) {

        applyHandCount(fingers);

        const removed = Math.round(Number(slider.value) / 100 * stages);

        log.push("hand " + fingers + " -> slider " + slider.value +
                 " removed " + removed + " systems, hud: " +
                 hud.textContent.replace("System cut: ", ""));
    }

    /*  -----------------------------------------------------------------
        Panel statements carry tooltips too - they live outside #ui, and the
        tip host has to follow the pointer there as well.
        ----------------------------------------------------------------- */
    renderer.domElement.dispatchEvent(new PointerEvent("pointerdown",
        { clientX: 671, clientY: 187, bubbles: true }));
    renderer.domElement.dispatchEvent(new MouseEvent("click",
        { clientX: 671, clientY: 187, bubbles: true }));

    const panelTips = document.querySelectorAll("#partPanel [data-tip]");
    const panelStatements = document.querySelectorAll(
        "#partPanel label, #partPanel button, #partPanel h3, " +
        "#partPanel .desc, #partPanel .readout, #partPanel .close");

    log.push("part panel elements with tips = " + panelTips.length +
             " / " + panelStatements.length);

    const firstLabel = document.querySelector("#partControls label");

    if (firstLabel) {
        firstLabel.dispatchEvent(new PointerEvent("pointerover",
            { clientX: 200, clientY: 200, bubbles: true }));
        /*  Inline style, not computed: the fade is a CSS transition and has
            not finished at the moment of the read.  */
        log.push("panel label tip inline opacity=" +
                 document.getElementById("tip").style.opacity +
                 " text=" + document.getElementById("tip").textContent.slice(0, 48));
    }

    log.push("all data-tip elements = " + document.querySelectorAll("[data-tip]").length);

    /*  -----------------------------------------------------------------
        Camera refused.  Headless Chrome never settles a real camera prompt,
        so drive the failure directly - and it has to be graceful.
        ----------------------------------------------------------------- */
    let threw = null;
    window.addEventListener("error", e => { threw = e.message; });

    navigator.mediaDevices.getUserMedia = () =>
        Promise.reject(new Error("Requested device not found"));

    document.getElementById("handToggle").click();
    await new Promise(r => setTimeout(r, 800));

    log.push("camera refused: button=\"" +
             document.getElementById("handToggle").textContent + "\" state=\"" +
             document.getElementById("handState").textContent.slice(0, 70) +
             "\" tracking on=" + HAND.on + " threw=" + threw);

    /*  And stopping hands the camera back.  */
    let released = false;

    HAND.stream = { getTracks: () => [{ stop: () => { released = true; } }] };
    HAND.on = true;
    stopHand();

    log.push("stopHand released camera tracks=" + released +
             ", tracking on=" + HAND.on +
             ", box hidden=" + (document.getElementById("handBox").style.display === "none"));

    HARNESS.report(log);
}, 2200);
