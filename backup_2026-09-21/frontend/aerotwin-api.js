/*
    AeroTwin API client - shared by every standalone page.

    Talks to the sih FastAPI backend:

        REST   /api/engine/{id}/state, /api/faults/*, /api/missions/*,
               /api/simulation/*, /health          (proxied same-origin
               by serve.py to http://127.0.0.1:8081, so CORS never matters)
        WS     ws://<backend-host>:8081/ws/telemetry/{id}
               (direct - the browser opens it itself)

    Frames arrive as the rich EngineState (see sih/backend/models/schemas.py
    and sih/frontend/src/lib/adapters.ts).  flatten() maps that onto the flat
    frame the pages want.

    Connection states reported to pages:  live | polling | offline
      live     - websocket open, frames streaming
      polling  - WS refused, REST works (poll every 2 s)
      offline  - nothing reachable; demo generator feeds clearly-labelled
                 placeholder frames so the pages stay alive in a pitch
*/
(function () {
    "use strict";

    const ENGINE_ID = "TAPAS-BH-201-001";
    const BACKEND_HTTP = "";                     // same-origin, via serve.py proxy
    const BACKEND_WS_PORT = 8081;

    /* ------------------------------------------------------------------ */
    /*  flatten: EngineState -> flat frame                                 */
    /* ------------------------------------------------------------------ */

    function flatten(state) {
        const obs = state.observed || {};
        return {
            timestamp: state.timestamp || obs.timestamp || new Date().toISOString(),
            frame_id: state.frame_id != null ? state.frame_id : (obs.frame_id || 0),
            sim_time_s: obs.sim_time_s || 0,
            altitude_ft: obs.altitude_ft || 0,
            throttle: obs.throttle || 0,
            rpm: obs.rpm || 0,
            map_kpa: obs.map_kpa || 0,
            fuel_flow_lph: obs.fuel_flow_lph || 0,
            cht: obs.cht || [0, 0, 0, 0],
            egt: obs.egt || [0, 0, 0, 0],
            oil_pressure_kpa: obs.oil_pressure_kpa || 0,
            oil_temp_c: obs.oil_temp_c || 0,
            vibration_rms: obs.vibration_rms || obs.vibration_rms_g || 0,
            ambient_temp_c: obs.ambient_temp_c || 0,
            injected_fault: obs.injected_fault || null,
            health_index: state.health_index,
            health_category: state.health_category || "NORMAL",
            anomaly_score: state.anomaly_score || 0,
            is_anomaly: !!state.is_anomaly,
            anomaly_contributors: state.anomaly_contributors || [],
            fault_class: state.fault_class || null,
            fault_confidence: state.fault_confidence,
            fault_severity: state.fault_severity,
            rul_minutes: state.rul_minutes,
            rtb_alert: state.rtb_alert || "NONE",
            isolated_sensors: state.isolated_sensors || [],
            sensor_status: state.sensor_status || {},
            residuals: state.residuals || null,
            physics_expected: state.physics_expected || null,
            raw: state
        };
    }

    /* ------------------------------------------------------------------ */
    /*  demo generator (offline mode, honestly labelled)                   */
    /* ------------------------------------------------------------------ */

    let demoFault = null;                        // {type, severity}
    let demoPhase = 0;

    function demoFrame() {
        demoPhase += 0.05;
        const wobble = Math.sin(demoPhase) * 40;
        const sev = demoFault ? demoFault.severity : 0;
        const hot = demoFault && /OVERHEAT|THERMAL/i.test(demoFault.type) ? sev : 0;
        const vib = demoFault && /VIBRATION/i.test(demoFault.type) ? sev : 0;
        const oil = demoFault && /LUBRICATION|OIL/i.test(demoFault.type) ? sev : 0;

        const base = 2400 + wobble * 3;
        return flatten({
            observed: {
                timestamp: new Date().toISOString(),
                frame_id: Math.floor(demoPhase * 10),
                sim_time_s: demoPhase * 2,
                altitude_ft: 15000 + wobble * 8,
                throttle: 0.65 + Math.sin(demoPhase / 3) * 0.05,
                rpm: base - hot * 120 + vib * 60,
                map_kpa: 88 + wobble * 0.5,
                fuel_flow_lph: 38 + wobble * 0.4,
                cht: [95, 97, 96 + hot * 90, 96].map(v => +(v + wobble * 0.1).toFixed(1)),
                egt: [680, 690, 685 + hot * 220, 688].map(v => Math.round(v)),
                oil_pressure_kpa: +(310 - oil * 160 - wobble * 0.6).toFixed(1),
                oil_temp_c: +(88 + hot * 25 + wobble * 0.2).toFixed(1),
                vibration_rms: +(0.18 + vib * 1.4 + Math.abs(wobble) * 0.002).toFixed(3),
                ambient_temp_c: 12,
                injected_fault: demoFault ? demoFault.type : null
            },
            health_index: +Math.max(18, 100 - hot * 45 - vib * 25 - oil * 35).toFixed(1),
            health_category: hot + vib + oil > 0.6 ? "CRITICAL" :
                hot + vib + oil > 0.25 ? "WARNING" : "NORMAL",
            anomaly_score: +Math.min(1, hot * 0.9 + vib * 0.7 + oil * 0.8).toFixed(3),
            is_anomaly: (hot + vib + oil) > 0.2,
            rul_minutes: Math.max(15, Math.round(180 - (hot + vib + oil) * 140)),
            rtb_alert: hot + vib + oil > 0.55 ? "RTB_CRITICAL" :
                hot + vib + oil > 0.2 ? "RTB_ADVISORY" : "NONE"
        });
    }

    /* ------------------------------------------------------------------ */
    /*  transport                                                          */
    /* ------------------------------------------------------------------ */

    const listeners = { frame: [], status: [] };
    let currentFrame = null;
    const history = [];                          // ring of flat frames
    const HISTORY_MAX = 240;
    let status = "offline";
    let ws = null, pollTimer = null, demoTimer = null, reconnectTimer = null;
    let wsAlive = false;

    function setStatus(next) {
        if (status === next) return;
        status = next;
        listeners.status.forEach(fn => { try { fn(status); } catch (e) {} });
    }

    function emit(frame) {
        currentFrame = frame;
        history.push(frame);
        if (history.length > HISTORY_MAX) history.shift();
        listeners.frame.forEach(fn => { try { fn(frame); } catch (e) {} });
    }

    function wsUrl() {
        const host = location.hostname || "127.0.0.1";
        return "ws://" + host + ":" + BACKEND_WS_PORT + "/ws/telemetry/" + ENGINE_ID;
    }

    function connectWs() {
        let opened = false;
        try {
            ws = new WebSocket(wsUrl());
        } catch (e) {
            startPolling();
            return;
        }

        ws.onopen = () => {
            opened = true;
            wsAlive = true;
            stopPolling();
            stopDemo();
            setStatus("live");
        };

        ws.onmessage = (ev) => {
            try {
                const msg = JSON.parse(ev.data);
                const state = msg.payload || msg;
                if (state && (state.observed || state.health_index !== undefined)) {
                    emit(flatten(state));
                }
            } catch (e) { /* keep-alives etc. */ }
        };

        ws.onclose = () => {
            wsAlive = false;
            if (!opened) { startPolling(); return; }
            setStatus("polling");
            pollOnce().then(ok => ok ? startPolling() : startDemo());
            clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(connectWs, 5000);
        };

        ws.onerror = () => { try { ws.close(); } catch (e) {} };
    }

    async function pollOnce() {
        try {
            const r = await fetch(BACKEND_HTTP + "/api/engine/" + ENGINE_ID + "/state",
                { cache: "no-store" });
            if (!r.ok) return false;
            emit(flatten(await r.json()));
            return true;
        } catch (e) {
            return false;
        }
    }

    function startPolling() {
        if (pollTimer) return;
        setStatus("polling");
        pollTimer = setInterval(() => {
            pollOnce().then(ok => { if (!ok) { stopPolling(); startDemo(); } });
        }, 2000);
    }

    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    function startDemo() {
        if (demoTimer) return;
        setStatus("offline");
        demoTimer = setInterval(() => emit(demoFrame()), 500);
    }

    function stopDemo() {
        if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
    }

    /* ------------------------------------------------------------------ */
    /*  REST helpers                                                       */
    /* ------------------------------------------------------------------ */

    async function api(method, path, body) {
        const opts = { method, headers: { "Content-Type": "application/json" }, cache: "no-store" };
        if (body !== undefined) opts.body = JSON.stringify(body);
        const r = await fetch(BACKEND_HTTP + path, opts);
        if (!r.ok) {
            let detail = r.statusText;
            try { detail = (await r.json()).detail || detail; } catch (e) {}
            throw new Error(detail || ("HTTP " + r.status));
        }
        return r.json();
    }

    /* ------------------------------------------------------------------ */
    /*  public surface                                                     */
    /* ------------------------------------------------------------------ */

    const AEROTWIN = {
        ENGINE_ID,
        flatten,
        history,
        get frame() { return currentFrame; },
        get status() { return status; },

        onFrame(fn)  { listeners.frame.push(fn);  if (currentFrame) fn(currentFrame); },
        onStatus(fn) { listeners.status.push(fn); fn(status); },

        start() {
            if (ws || pollTimer || demoTimer) return;
            connectWs();
            /*  if the WS never opens, fall back after 3 s */
            setTimeout(() => {
                if (!wsAlive && !pollTimer && !demoTimer) {
                    pollOnce().then(ok => ok ? startPolling() : startDemo());
                }
            }, 3000);
        },

        injectFault(faultType, severity, targetSensor) {
            return api("POST", "/api/faults/inject",
                { fault_type: faultType, severity: severity, target_sensor: targetSensor || null });
        },
        clearFaults()      { return api("POST", "/api/faults/clear"); },
        faultTypes()       { return api("GET",  "/api/faults/types"); },
        simStatus()        { return api("GET",  "/api/simulation/status"); },
        setThrottle(v)     { return api("POST", "/api/simulation/throttle", { throttle: v }); },
        setAltitude(ft)    { return api("POST", "/api/simulation/altitude", { altitude_ft: ft }); },

        startMission(name, durationS) {
            return api("POST", "/api/missions/start",
                { engine_id: ENGINE_ID, name: name || null, duration_s: durationS || 600 });
        },
        stopMission(id)      { return api("POST", "/api/missions/" + id + "/stop"); },
        missions(limit)      { return api("GET", "/api/missions?limit=" + (limit || 50)); },
        mission(id)          { return api("GET", "/api/missions/" + id); },
        missionSummary(id)   { return api("GET", "/api/missions/" + id + "/summary"); },
        healthTimeline(id)   { return api("GET", "/api/reports/" + id + "/health-timeline"); },
        report(id)           { return api("GET", "/api/reports/" + id); },

        health()             { return api("GET", "/health"); },

        /*  demo-mode fault hook, so the fault lab still demonstrates something
            when the backend is down */
        setDemoFault(type, severity) {
            demoFault = type ? { type: type, severity: severity } : null;
        },
        isOffline() { return status === "offline"; }
    };

    window.AEROTWIN_API = AEROTWIN;
})();
