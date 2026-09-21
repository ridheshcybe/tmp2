/*
    Shared harness JavaScript for the headless test drivers in this directory.

    This file is NOT part of the page.  _hand.py, _probe.py and _scan.py read
    it, splice it into a copy of index.html and point headless Chrome at the
    result, so the instrumentation the tests rely on lives in one real .js
    file that can be edited and linted as JavaScript, instead of being
    copy-pasted around as Python string literals.

    It is spliced into index.html's own <script>, so it shares that script's
    scope: the page's globals (SYSTEM_ORDER, TUNE, scene, renderer, pickAt,
    countFingers, applyHandCount, stopHand, HAND, SYSTEMS, bloomPass,
    clipPlane, engineBlock) are all in scope here, and none of them may be
    redeclared - the page would stop loading.  Hence the single HARNESS
    namespace.

    The build is static: index.html runs straight off the file system with no
    modules and no bundler, so everything here is plain page-scope code.
*/

const HARNESS = {

    /*  -----------------------------------------------------------------
        Deterministic Math.random

        The flames are jittered from Math.random, so two otherwise identical
        probe runs differ by that jitter alone.  Replacing it with a seeded
        LCG puts every run on the same footing, which is what makes an A/B
        screenshot diff mean anything.
        ----------------------------------------------------------------- */
    seed: 12345,

    /*
        Build a synthetic hand for the finger counter: a wrist, four finger
        chains and a thumb, with the named fingers extended and the rest
        curled into the palm.  Returns 21 landmarks in the MediaPipe order
        countFingers() expects, so it can stand in for a real camera.
    */
    makeHand(extended) {

        const lm = [];
        for (let i = 0; i < 21; i++) lm.push({ x: 0.5, y: 0.5, z: 0 });

        lm[0] = { x: 0.50, y: 0.85, z: 0 };                       /* wrist */

        const chains = [
            { finger: "index",  mcp: 5,  x: 0.42 },
            { finger: "middle", mcp: 9,  x: 0.50 },
            { finger: "ring",   mcp: 13, x: 0.58 },
            { finger: "pinky",  mcp: 17, x: 0.65 }
        ];

        for (const c of chains) {

            const open = extended.indexOf(c.finger) >= 0;

            /*  Extended: the pip sits half way up and the tip near the top
                of the frame.  Curled: the tip folds back down to the
                knuckle line.  */
            lm[c.mcp]     = { x: c.x, y: 0.62, z: 0 };
            lm[c.mcp + 1] = { x: c.x, y: open ? 0.46 : 0.54, z: 0 };
            lm[c.mcp + 2] = { x: c.x, y: open ? 0.42 : 0.56, z: 0 };
            lm[c.mcp + 3] = { x: c.x, y: open ? 0.36 : 0.62, z: 0 };
        }

        /*  Thumb: out to the side when open, wrapped across the palm when
            not.  */
        const tOpen = extended.indexOf("thumb") >= 0;
        lm[1] = { x: 0.40, y: 0.78, z: 0 };
        lm[2] = { x: 0.34, y: 0.72, z: 0 };
        lm[3] = { x: tOpen ? 0.30 : 0.44, y: tOpen ? 0.66 : 0.68, z: 0 };
        lm[4] = { x: tOpen ? 0.26 : 0.55, y: tOpen ? 0.60 : 0.62, z: 0 };

        return lm;
    },

    /*
        Report the state of the scene graph: how many drawable parts there
        are, how much geometry they carry, what the System Cut has hidden and
        which materials are not clipped by the section plane.

        Note: Layers.set() does not return this in r128, so it cannot be
        chained - doing that passes undefined into test() and throws.
    */
    DIAG() {

        const L0 = new THREE.Layers();
        L0.set(0);

        let n = 0, off = 0, tris = 0;
        const un = [];

        scene.traverse(o => {

            if (!o.isMesh && !o.isPoints) return;
            n++;

            /*  Indexed geometry counts its index, a non-indexed one has one
                triangle per three vertices.  */
            if (o.isMesh && o.geometry) {
                if (o.geometry.index) tris += o.geometry.index.count / 3;
                else if (o.geometry.attributes.position)
                    tris += o.geometry.attributes.position.count / 3;
            }

            if (!o.layers.test(L0)) off++;

            const mats = Array.isArray(o.material) ? o.material : [o.material];
            for (const m of mats) {
                if (m && (!m.clippingPlanes || m.clippingPlanes.length === 0)) {
                    un.push(o.type + "/" + (m.type || "array") + "/" +
                            (o.geometry ? o.geometry.attributes.position.count : -1) + "v");
                    break;
                }
            }
        });

        console.log("DIAG " + JSON.stringify({
            parts: n,
            tris: Math.round(tris),
            onHiddenLayer: off,
            unclipped: un,
            bloom: bloomPass.strength,
            blockMask: engineBlock ? engineBlock.layers.mask : -1,
            clip: clipPlane.constant,
            systems: Object.keys(SYSTEMS).map(k => k + ":" + SYSTEMS[k].length)
        }));
    },

    /*  Report the scene graph once the build has settled: the STL parts are
        hung on the model over the first second or so, so a report taken
        immediately after animate() shows a half-built engine.  */
    diagAfter(ms) {
        setTimeout(() => HARNESS.DIAG(), ms);
    },

    /*  One JSON line for the Python driver, which scrapes it back out of
        Chrome's stderr.  */
    report(log) {
        console.log("TEST " + JSON.stringify(log));
    }
};

/*
    Seeding has to be a side effect, not an explicit call: the page draws
    from Math.random on its very first frame.
*/
Math.random = function () {
    HARNESS.seed = (HARNESS.seed * 1103515245 + 12345) & 0x7fffffff;
    return HARNESS.seed / 0x7fffffff;
};
