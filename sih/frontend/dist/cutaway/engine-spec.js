/*
    AeroTwin engine spec - the single source of truth for the engine's
    identity and its operating limits.

    Why this file exists: the UI test report found that different pages
    disagreed about the engine (the dashboard said V4 while the cutaway said
    V8) and that numbers, limits and warning labels could contradict each
    other.  Both problems come from the same cause - every page carried its
    own copy of the values.  Now they all read from here.

    The engine modelled by the digital twin is a 60 degree V4 turbo-prop:
    the backend's own telemetry model, the four CHT / four EGT channels and
    the (four cylinder) diagnostics page all match this.

    Note on the 3D cutaway: its STL casting has eight bores, because that is
    what the measured hardware model is.  That page labels the mesh as the
    bench model and takes the engine's *name* from here, so the app still
    reports one engine type throughout.

    Usage:
      <script src="engine-spec.js"></script>   before aerotwin-api.js

      Markup:  <span data-spec="shortName">V4</span>
               <div data-spec="engineType">...</div>
               <div data-spec="serial">...</div>
      Script:  window.AEROTWIN_SPEC.limits.chtCritC
*/
(function () {
    "use strict";

    const SPEC = {
        /* ---- identity (rendered into [data-spec] elements) ------------- */
        appName: "AeroTwin",
        shortName: "V4",
        model: "AeroTwin // V4",
        engineType: "60\u00B0 V4 Turbo-Prop",
        engineTypeCode: "60_DEG_V4_TURBOPROP",
        engineId: "TAPAS-BH-201-001",
        serial: "SN: V4-9982-B",
        cylinders: 4,
        firingOrder: "1-3-4-2",

        /* ---- operating limits ------------------------------------------ */
        /*  chtWarnC / chtCritC drive the CHT number, the "limit" caption and
            the warning badge, so all three can never disagree.  */
        limits: {
            chtWarnC: 215,
            chtCritC: 240,
            egtWarnC: 850,
            egtCritC: 950,
            oilPressureWarnKpa: 200,
            oilPressureCritKpa: 140,
            rpmMax: 6400,
            rpmCruise: 2400,
            rpmIdle: 1200,
            rpmTakeoff: 5800,
            vibrationWarnG: 0.45,
            vibrationCritG: 0.9,
            rulWarnMin: 30,
            rulCritMin: 10
        },

        /* ---- derived status bands -------------------------------------- */
        bands: {
            anomalyWarn: 0.35,
            anomalyCrit: 0.6,
            healthWarn: 70,
            healthCrit: 50,
            /*  longer than this since the last frame and the feed is OLD DATA */
            staleMs: 4000
        },

        /*  Classify a cylinder-head temperature into NOMINAL / WARN / CRIT. */
        chtStatus(c) {
            if (c == null || isNaN(c)) return "NODATA";
            if (c >= SPEC.limits.chtCritC) return "CRIT";
            if (c >= SPEC.limits.chtWarnC) return "WARN";
            return "NOMINAL";
        },

        /*  Classify an oil pressure (kPa). */
        oilStatus(kpa) {
            if (kpa == null || isNaN(kpa)) return "NODATA";
            if (kpa <= SPEC.limits.oilPressureCritKpa) return "CRIT";
            if (kpa <= SPEC.limits.oilPressureWarnKpa) return "LOW";
            return "NOMINAL";
        },

        /*  Classify an anomaly score into NORMAL / WARNING / CRITICAL. */
        anomalyBand(score) {
            if (score == null || isNaN(score)) return "NODATA";
            if (score >= SPEC.bands.anomalyCrit) return "CRITICAL";
            if (score >= SPEC.bands.anomalyWarn) return "WARNING";
            return "NORMAL";
        },

        /*  Classify an engine health index into a category band. */
        healthBand(ehi) {
            if (ehi == null || isNaN(ehi)) return "NODATA";
            if (ehi >= SPEC.bands.healthWarn) return "NORMAL";
            if (ehi >= SPEC.bands.healthCrit) return "WARNING";
            return "CRITICAL";
        }
    };

    /*  Fill every [data-spec="key"] element in the document with its value.
        Called on load, and again once the API module has had a chance to
        overwrite anything (it does not, but calling twice is harmless).  */
    function apply(root) {
        const scope = root || document;
        scope.querySelectorAll("[data-spec]").forEach(el => {
            const key = el.getAttribute("data-spec");
            if (SPEC[key] != null) el.textContent = SPEC[key];
        });
    }

    SPEC.apply = apply;

    window.AEROTWIN_SPEC = SPEC;
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => apply());
    } else {
        apply();
    }
})();
