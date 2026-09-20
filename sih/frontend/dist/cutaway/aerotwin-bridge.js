/*  ═════════════════════════════════════════════════════════════════════════
    AeroTwin <-> cutaway viewer bridge
    ═════════════════════════════════════════════════════════════════════════

    The cutaway viewer (index.html beside this file) is a self-contained
    Three.js page.  Rather than rewrite it as a React component, the dashboard
    hosts it and talks to it through this file, which CutawayTwinView.tsx
    injects into the viewer's own document.

    It has to be injected rather than driven from the parent because the
    viewer's state (`TUNE`, `SYSTEMS`, `scene`, `applySystemCut`, `pickAt`) is
    declared with top-level `const`/`let`.  Those are lexical globals of that
    document: another script in the same page can read them, but they are not
    properties of `iframe.contentWindow`, so React cannot reach them.

    Protocol, all over postMessage:

      parent -> viewer   { type: "AEROTWIN_TELEMETRY", payload: frame,
                           options: { followRpm, heatmap } }

      viewer -> parent   { type: "AEROTWIN_READY", payload: { cylinders, ready } }
      viewer -> parent   { type: "AEROTWIN_PICK",  payload: { system, cyl } | null }

    `frame` is the dashboard's flat telemetry frame (see lib/adapters.ts).
    ═══════════════════════════════════════════════════════════════════════ */

(function () {
    "use strict";

    if (window.__aerotwinBridge) return;
    window.__aerotwinBridge = true;

    /*  The viewer's Speed control is quoted in RPM: its own HUD prints
        `value * 3600` and its animation runs at `value * 60` rad/s.  Driving
        `value = rpm / 3600` therefore keeps the viewer's own readout equal to
        the live telemetry, instead of showing a second, contradictory number.
        Its slider only reaches 0.15 (about 540 RPM), so the range is widened
        to cover a real engine; the rotation stays ~6x slower than a real
        crank, which is the viewer's own deliberate choice and keeps the
        pistons watchable.  */
    const RPM_PER_SLIDER_UNIT = 3600;
    const SLIDER_MAX = 1.2;

    /*  Cylinder-head temperature ramp, matched to the dashboard legend:
        nominal below 150 C, amber by 190 C, red at 240 C.  */
    const CHT_NOMINAL_C = 150;
    const CHT_CRITICAL_C = 240;

    /*  Exhaust gas runs far hotter, so it gets its own ramp.
        "EGT spike > 850 C" is the number the cockpit copy uses for a fault.  */
    const EGT_NOMINAL_C = 700;
    const EGT_CRITICAL_C = 850;

    /*
        The per-cylinder groups are the reciprocating assembly - pistons, rods,
        rings - which sits *inside* the block, so tinting only those leaves the
        heatmap all but invisible on an assembled engine.  The viewer also tags
        hardware by system name, and these are the parts you can actually see,
        so the hottest cylinder drives them too.
    */
    const HEAT_SYSTEMS_CHT = ["valvesA", "valvesB", "camsA", "camsB", "plugs"];
    const HEAT_SYSTEMS_EGT = ["exhaust"];

    const speedEl = document.getElementById("speed");

    /*  One entry per cylinder; the viewer tags each cylinder group with
        userData.cyl = 1..8.  */
    let cylinderSlots = [];

    /*  [{ materials, nominal, critical, celsius }] for the visible systems.  */
    let systemSlots = [];

    let cylindersReady = false;

    /*
        Diagnostics for the dashboard's end-to-end check.  Exposed as a window
        property on purpose: the viewer's own globals are lexical and cannot be
        read from the parent, but this can.
    */
    window.__aerotwinTint = { cylinders: 0, systems: 0, maxK: 0, celsius: 0, applied: 0 };

    /*  ---------------------------------------------------------------------
        Finding the cylinders

        The groups are nested, so only the outermost tagged node of each
        cylinder is kept: otherwise a cylinder's materials would be indexed
        twice and the two copies would fight over the tint.
        --------------------------------------------------------------------- */
    function findCylinders() {

        const tagged = [];

        scene.traverse((node) => {
            if (node.userData && node.userData.cyl) tagged.push(node);
        });

        return tagged.filter((node) => {
            for (let parent = node.parent; parent; parent = parent.parent) {
                if (parent.userData && parent.userData.cyl) return false;
            }
            return true;
        });
    }

    /*
        Materials are shared between cylinders (there is one pistonMaterial for
        all eight), so tinting one hot cylinder would light up the rest.  Each
        cylinder gets private clones of its own materials once, at load, and
        the originals are remembered so the tint can be taken back off.
    */
    /*  Meshes already given private materials, so a part that appears in both
        a cylinder group and a named system is not cloned twice - two clones
        would fight over the same mesh and the per-cylinder tint would lose.  */
    const claimed = new WeakSet();

    function ownMaterials(root, stopAtCylinder) {

        const owned = [];

        const walk = (node) => {

            /*  A nested tagged node is the next cylinder along, not ours.  */
            if (stopAtCylinder && node !== root && node.userData && node.userData.cyl) return;

            if (node.material && !claimed.has(node)) {

                const isArray = Array.isArray(node.material);
                const mats = isArray ? node.material : [node.material];

                let touched = false;

                mats.forEach((mat, i) => {

                    if (!mat || !mat.emissive) return;

                    const clone = mat.clone();

                    if (isArray) node.material[i] = clone;
                    else node.material = clone;

                    touched = true;

                    owned.push({
                        material: clone,
                        baseEmissive: clone.emissive.getHex(),
                        baseIntensity: clone.emissiveIntensity
                    });
                });

                if (touched) claimed.add(node);
            }

            node.children.forEach(walk);
        };

        walk(root);
        return owned;
    }

    function indexCylinders() {

        cylinderSlots = findCylinders().map((group) => ({
            cyl: group.userData.cyl,
            materials: ownMaterials(group, true)
        }));

        /*  Visible systems, tinted from the hottest cylinder rather than one
            each - a temperature is per cylinder, the hardware is shared.  */
        systemSlots = [];

        const add = (names, nominal, critical, pick) => {

            if (typeof SYSTEMS === "undefined") return;

            for (const name of names) {

                const objects = SYSTEMS[name] || [];
                const materials = [];

                for (const object of objects) {
                    if (object && object.traverse) {
                        materials.push(...ownMaterials(object, false));
                    }
                }

                if (materials.length) systemSlots.push({ materials, nominal, critical, pick });
            }
        };

        const hottest = (values) => (values && values.length ? Math.max(...values) : 0);

        add(HEAT_SYSTEMS_CHT, CHT_NOMINAL_C, CHT_CRITICAL_C, (cht) => hottest(cht));
        add(HEAT_SYSTEMS_EGT, EGT_NOMINAL_C, EGT_CRITICAL_C, (cht, egt) => hottest(egt));

        window.__aerotwinTint.cylinders = cylinderSlots.length;
        window.__aerotwinTint.systems = systemSlots.length;

        return cylinderSlots.length;
    }

    /*  ---------------------------------------------------------------------
        Telemetry -> viewer
        --------------------------------------------------------------------- */

    function setRpm(rpm) {

        if (!speedEl) return;

        speedEl.max = String(SLIDER_MAX);

        const want = Math.max(0, Math.min(SLIDER_MAX, Number(rpm) / RPM_PER_SLIDER_UNIT));

        if (Math.abs(Number(speedEl.value) - want) < 0.0005) return;

        speedEl.value = String(want);

        /*  Drive the viewer's own control path, so the crank, the pistons,
            the flame and its HUD all stay consistent with each other.  */
        speedEl.dispatchEvent(new Event("input", { bubbles: true }));
    }

    function lerpHex(from, to, t) {

        const a = new THREE.Color(from);
        const b = new THREE.Color(to);

        return a.lerp(b, Math.max(0, Math.min(1, t))).getHex();
    }

    function applyTint(materials, temp, nominal, critical) {

        const k = Math.max(0, Math.min(1, (temp - nominal) / (critical - nominal)));

        for (const entry of materials) {

            if (k <= 0.01) {
                entry.material.emissive.setHex(entry.baseEmissive);
                entry.material.emissiveIntensity = entry.baseIntensity;
                continue;
            }

            /*  Amber at the first sign of heat, red approaching the critical
                band.  */
            const hex = k < 0.5
                ? lerpHex(0x3a1c00, 0xff8c1a, k * 2)
                : lerpHex(0xff8c1a, 0xff2a10, (k - 0.5) * 2);

            entry.material.emissive.setHex(hex);
            entry.material.emissiveIntensity = 0.35 + 0.65 * k;
        }
    }

    function setHeat(cht, egt) {

        if (!cht || cht.length === 0) return;

        let hottest = 0;

        const mark = (materials, temp, nominal, critical) => {
            applyTint(materials, temp, nominal, critical);
            hottest = Math.max(hottest, (temp - nominal) / (critical - nominal));
        };

        /*  The twin reports four cylinders and the model has eight in two
            banks of four, so 1-4 drive bank A (1-4) and bank B (5-8).  */
        for (const slot of cylinderSlots) {
            mark(slot.materials, Number(cht[(slot.cyl - 1) % cht.length]) || 0,
                 CHT_NOMINAL_C, CHT_CRITICAL_C);
        }

        for (const slot of systemSlots) {
            mark(slot.materials, slot.pick(cht, egt), slot.nominal, slot.critical);
        }

        window.__aerotwinTint.maxK = Math.max(0, Math.min(1, hottest));
        window.__aerotwinTint.celsius = Math.max(...cht);
        window.__aerotwinTint.applied++;
    }

    /*
        Turning the heatmap off has to take the tint back off, not just stop
        updating it - otherwise the last frame's glow stays on the engine.
    */
    function clearHeat() {

        for (const slot of cylinderSlots.concat(systemSlots)) {
            for (const entry of slot.materials) {
                entry.material.emissive.setHex(entry.baseEmissive);
                entry.material.emissiveIntensity = entry.baseIntensity;
            }
        }

        window.__aerotwinTint.maxK = 0;
        window.__aerotwinTint.celsius = 0;
        window.__aerotwinTint.applied++;
    }

    /*
        An injected fault raises the bloom slightly, so a failure reads on the
        engine itself and not only in the charts.  `bloomDefault` is the
        viewer's own constant; this only scales it.
    */
    function setFault(severity) {

        if (typeof bloomPass === "undefined") return;
        if (typeof bloomDefault === "undefined") return;

        const s = Math.max(0, Math.min(1, Number(severity) || 0));

        bloomPass.strength = s > 0.01 ? bloomDefault * (1 + 0.45 * s) : bloomDefault;
    }

    window.addEventListener("message", (event) => {

        const msg = event.data;

        if (!msg || msg.type !== "AEROTWIN_TELEMETRY") return;

        const frame = msg.payload || {};
        const options = msg.options || {};

        if (options.followRpm !== false) setRpm(frame.rpm);

        if (cylindersReady) {
            if (options.heatmap === false) clearHeat();
            else setHeat(frame.cht, frame.egt);
        }

        /*  The flat frame carries the ground-truth fault the demo injected.  */
        setFault(frame.injected_fault ? 1 : 0);
    });

    /*  ---------------------------------------------------------------------
        Viewer -> dashboard: report what the user clicks, so the cockpit can
        show the same selection.  The viewer handles its own clicks too, and
        pickAt is a pure raycast, so both listeners can share it.
        --------------------------------------------------------------------- */

    renderer.domElement.addEventListener("click", (e) => {

        let hit = null;

        try {
            hit = pickAt(e.clientX, e.clientY);
        } catch (err) {
            hit = null;
        }

        parent.postMessage({
            type: "AEROTWIN_PICK",
            payload: hit ? { system: hit.system, cyl: hit.cyl || null } : null
        }, "*");
    });

    /*  ---------------------------------------------------------------------
        The model arrives asynchronously (an STL load), so the cylinders are
        indexed once the block is on screen and the parent is then told the
        viewer is live.
        --------------------------------------------------------------------- */

    let attempts = 0;

    const waiter = setInterval(() => {

        attempts++;

        /*  engineBlock is set by the viewer once engine_block.stl has parsed.  */
        const loaded = typeof engineBlock !== "undefined" && engineBlock !== null;
        const count = loaded ? indexCylinders() : 0;

        if (count > 0 || attempts > 60) {

            clearInterval(waiter);
            cylindersReady = count > 0;

            parent.postMessage({
                type: "AEROTWIN_READY",
                payload: {
                    cylinders: count,
                    systems: systemSlots.length,
                    ready: cylindersReady,
                    attempts: attempts
                }
            }, "*");
        }
    }, 250);
})();
