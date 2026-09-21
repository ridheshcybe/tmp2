
    /* ===== UI handlers ===== */
    function setPreset(name, rpm) {
      document.querySelectorAll('.preset-btn').forEach(btn => {
        btn.className = "preset-btn px-3 py-1 rounded text-xs font-headline font-semibold text-stone-300 hover:text-white transition-all";
      });
      const current = document.getElementById('preset-' + name);
      if (current) current.className = "preset-btn px-3 py-1 rounded text-xs font-headline font-bold bg-primary-container text-on-primary-container shadow transition-all";

      const rpmEl = document.getElementById('metric-rpm');
      if (rpmEl) rpmEl.innerHTML = rpm.toLocaleString() + ' <span class="text-xs font-mono font-normal text-on-surface-variant">RPM</span>';

      const cutFrame = document.getElementById('cutawayFrame');
      if (cutFrame && cutFrame.contentWindow) {
        cutFrame.contentWindow.postMessage({ type: 'CUTAWAY_SET_RPM', rpm }, '*');
      }
    }

    function triggerRunaway() {
      const tempEl = document.getElementById('metric-temp');
      if (tempEl) {
        tempEl.innerText = "188.4°C";
        tempEl.classList.add('animate-pulse');
      }
      setPreset('takeoff', 5800);
      const sev = document.getElementById('sev-thermal');
      if (sev) sev.innerText = "1.00";
    }

    function toggleJsonDrawer() {
      const drawer = document.getElementById('json-drawer');
      if (drawer) drawer.classList.toggle('translate-y-full');
    }

    function copyPayload() {
      const el = document.getElementById('json-preview');
      if (el && navigator.clipboard) {
        navigator.clipboard.writeText(el.innerText);
        alert("Payload copied to clipboard.");
      }
    }

    function dispatchWebhook() {
      alert("Telemetry snapshot synced with remote broker.");
    }

    /* =========================================================================
       CUTAWAY IFRAME (inline, not a pop-up)
       ========================================================================= */
    const cutawayFrame = document.getElementById('cutawayFrame');

    /*  The preset buttons are wired to the backend inside the API block
        below; before that block runs they must still exist, so a stub
        keeps the inline onclick from throwing on a slow API script.  */
    if (typeof window.setPreset !== 'function') {
      window.setPreset = function () {};
    }

    cutawayFrame.addEventListener('load', () => {
      const active = document.querySelector('.preset-btn.bg-primary-container');
      if (!active) return;
      const rpm = active.id === 'preset-idle' ? 1200
        : active.id === 'preset-takeoff' ? 5800
          : 2400;
      if (cutawayFrame.contentWindow) {
        cutawayFrame.contentWindow.postMessage({ type: 'CUTAWAY_SET_RPM', rpm }, '*');
      }
    });

    document.getElementById('reloadSimBtn').addEventListener('click', () => {
      cutawayFrame.src = 'cutaway.html';
    });

    /* Ask the simulator to produce a fresh QR. The simulator is expected to
       reply with a CUTAWAY_SHOW_QR message (see the message bridge below). */
    function askSimForQr() {
      lastQrDataUrl = null;
      lastQrCaption = null;
      qrPlaceholder.innerHTML =
        '<div class="spinner"></div><div>Waiting for QR from simulator&hellip;</div>';
      setQrStatus('');
      openQr();
      if (cutawayFrame.contentWindow) {
        cutawayFrame.contentWindow.postMessage({ type: 'CUTAWAY_REQUEST_QR' }, '*');
      }
    }

    /* =========================================================================
       QR POP-UP
       The QR carries a one-time pairing token, so scanning it is the whole
       handshake: the phone fetches the offer and posts its answer back over
       the local server, and this pop-up just watches for the connected
       state.  No code to copy, and no reply to paste back in.
       ========================================================================= */
    const qrPopup = document.getElementById('qrPopup');
    const qrImage = document.getElementById('qrImage');
    const qrPlaceholder = document.getElementById('qrPlaceholder');
    const qrCaption = document.getElementById('qrCaption');
    const qrStatus = document.getElementById('qrStatus');

    const DEFAULT_CAPTION =
      'Scan this code with your phone camera to pair.<br>Keep both devices on the same network.';

    let lastQrDataUrl = null;
    let lastQrCaption = null;

    function setQrStatus(text) {
      qrStatus.textContent = text || '';
    }

    function openQr() {
      if (lastQrDataUrl) {
        qrImage.src = lastQrDataUrl;
        qrImage.style.display = 'block';
        qrPlaceholder.style.display = 'none';
      } else {
        qrImage.style.display = 'none';
        qrPlaceholder.style.display = 'flex';
      }

      qrCaption.innerHTML = lastQrCaption || DEFAULT_CAPTION;
      qrPopup.classList.add('open');
    }

    function closeQr() {
      qrPopup.classList.remove('open');
    }

    document.getElementById('qrClose').addEventListener('click', closeQr);
    document.getElementById('qrDoneBtn').addEventListener('click', closeQr);

    qrPopup.addEventListener('click', e => {
      if (e.target === qrPopup) closeQr();
    });

    /* =========================================================================
       MESSAGE BRIDGE
       The simulator (cutaway.html) sends its QR image here. The engine itself
       never moves; only this pop-up appears on top.
       ========================================================================= */
    window.addEventListener('message', (ev) => {
      const data = ev.data;
      if (!data || typeof data !== 'object') return;

      if (data.type === 'CUTAWAY_SHOW_QR') {
        if (data.error) {
          lastQrDataUrl = null;
          lastQrCaption = 'Pairing failed: ' + data.error;
          qrPlaceholder.innerHTML =
            '<div style="color:#e63b2e;font-weight:600">Pairing failed</div>' +
            '<div>' + String(data.error).replace(/</g, '&lt;') + '</div>';
        } else {
          lastQrDataUrl = data.dataUrl || null;
          lastQrCaption = data.caption || null;
          qrPlaceholder.innerHTML =
            '<div class="spinner"></div><div>Waiting for QR from simulator&hellip;</div>';
        }
        openQr();
        return;
      }

      if (data.type === 'CUTAWAY_PAIR_STATE') {
        /*  The sim announces every pairing step, even when this pop-up is
            closed; a live connection closes whatever is open.  */
        if (data.connected) {
          closeQr();
        } else if (qrPopup.classList.contains('open')) {
          setQrStatus(data.message || '');
        }
        return;
      }

      if (data.type === 'CUTAWAY_QR_CLOSED' || data.type === 'PAIR_CLOSED') {
        closeQr();
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && qrPopup.classList.contains('open')) closeQr();
    });

    /* =========================================================================
       BACKEND WIRING
       ========================================================================= */
    const API = window.AEROTWIN_API;
    if (API) {
      API.start();

      /* ---- mission boot ------------------------------------------------
         Every KPI, fault and preset on this page is powered by the
         backend's mission simulator, so make sure one is running: ask
         politely, start one if nobody else has. ------------------------- */
      const DEFAULT_RPM = 2400;

      (async function ensureMission() {
        try {
          const st = await API.simStatus();
          if (!st.is_running) {
            /*  'manual' = the engine sits parked at ground idle until a
                preset, the slider or the phone commands it. */
            await API.startMission('Dashboard session', 3600, 'manual')
              .then(() => console.log('[mission] interactive session started'))
              .catch(err => console.warn('[mission] start failed:', err.message));
          }
        } catch (e) {
          console.warn('[mission] backend unreachable:', e.message);
        }
      })();

      /*  Publish the live engine state to the phone controller, via the
          sim iframe's data channel (and the /__ctl poll for REST). */
      let phoneStateTimer = null;

      function publishPhoneState(f) {
        const cutFrame = document.getElementById('cutawayFrame');
        if (cutFrame && cutFrame.contentWindow) {
          cutFrame.contentWindow.postMessage({
            type: 'PHONE_STATE',
            phase: f.phase || 'MANUAL',
            rpm: Math.round(f.rpm || 0),
            throttle: f.throttle || 0,
            flying: flying
          }, '*');
        }
      }

      /*  Backend throttle from the preset buttons: rpm/3600 is the scale
          the simulator's own model uses. Falls back to the sim iframe if
          the backend is down, so the visuals still follow the preset.  */
      function setPreset(name, rpm) {
        document.querySelectorAll('.preset-btn').forEach(btn => {
          btn.className = "preset-btn px-3 py-1 rounded text-xs font-headline font-semibold text-stone-300 hover:text-white transition-all";
        });
        const current = document.getElementById('preset-' + name);
        if (current) current.className = "preset-btn px-3 py-1 rounded text-xs font-headline font-bold bg-primary-container text-on-primary-container shadow transition-all";

        const rpmEl = document.getElementById('metric-rpm');
        if (rpmEl) rpmEl.innerHTML = rpm.toLocaleString() + ' <span class="text-xs font-mono font-normal text-on-surface-variant">RPM</span>';

        const throttle = Math.min(1, Math.max(THROTTLE_FLOOR, Math.round((rpm / 3600) * 100) / 100));
        if (throttleSlider && !manualMode) throttleSlider.value = String(Math.round(throttle * 100));
        API.setThrottle(throttle)
          .then(() => { syncThrottleUI(throttle); console.log('[sim] throttle ->', throttle); })
          .catch(() => commandSim(rpm / 3600));
      }
      window.setPreset = setPreset;

      const CONN_STYLES = {
        live: { label: "STATUS: LIVE", dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-700 border-emerald-200" },
        polling: { label: "STATUS: POLLING", dot: "bg-amber-500", chip: "bg-amber-50 text-amber-700 border-amber-200" },
        offline: { label: "STATUS: DEMO MODE", dot: "bg-stone-400", chip: "bg-stone-100 text-stone-600 border-stone-300" }
      };

      const connBadge = document.getElementById('connBadge');
      const connDot = document.getElementById('connDot');
      const connLabel = document.getElementById('connLabel');

      function renderStatus(st) {
        const s = CONN_STYLES[st] || CONN_STYLES.offline;

        connBadge.className = "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-medium border " + s.chip;
        connDot.className = "w-1.5 h-1.5 rounded-full " + s.dot + (st === 'live' ? " animate-pulse" : "");
        connLabel.textContent = s.label;

        document.getElementById('feedSource').textContent =
          st === 'live' ? "WS FEED" : st === 'polling' ? "REST POLL" : "DEMO FEED";
        document.querySelector('#feedBadge span').textContent =
          st === 'live' ? "10Hz" : st === 'polling' ? "0.5Hz" : "2Hz";
      }

      const fmt = (v, d) => (v == null || isNaN(v)) ? "--" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 1 : d });

      /*  KPI deltas. Each chip shows the change over the last ~1 s
          (not the previous 10 Hz frame) so the number is big enough to
          read: tens of RPM, tenths of a degree. The chip pops whenever
          its displayed value changes - every fluctuation is shown. */
      const KPI_WINDOW_MS = 1000;
      const kpiHistory = {};                 // id -> [{t, v}]

      function setKpiDelta(id, value, digits, unit) {
        const el = document.getElementById(id);
        if (!el || !isFinite(value)) return;
        const now = performance.now();
        const hist = kpiHistory[id] || (kpiHistory[id] = []);
        hist.push({ t: now, v: value });
        while (hist.length > 2 && now - hist[0].t > KPI_WINDOW_MS) hist.shift();
        const old = hist[0];
        if (hist.length < 2 || now - old.t < 250) {
          /*  not enough history in the window yet */
          return;
        }
        const diff = value - old.v;
        let txt, sign;
        if (Math.abs(diff) < Math.pow(10, -digits) / 2) {
          txt = '\u00B7 hold';
          sign = 'flat';
        } else {
          txt = (diff > 0 ? '\u25B2 ' : '\u25BC ') + Math.abs(diff).toFixed(digits) + unit;
          sign = diff > 0 ? 'up' : 'down';
        }
        if (el.textContent !== txt) {
          el.textContent = txt;
          el.dataset.sign = sign;
          /*  pop at most ~3x/s so a spooling engine does not strobe */
          if (now - (el._lastPop || 0) > 300) {
            el._lastPop = now;
            el.classList.remove('pop');
            void el.offsetWidth;             /* restart the pop animation */
            el.classList.add('pop');
          }
        }
      }

      /*  Live KPI trend lines: the last ~120 samples drawn as a sparkline
          so every fluctuation is visible as a moving line, not just a
          number. DPR-aware so the line stays crisp on HiDPI screens. */
      const SPARK_MAX = 120;
      const sparkData = {};                    // canvas id -> number[]
      const sparkCtx = {};

      function drawSpark(id, value) {
        if (!isFinite(value)) return;
        const hist = sparkData[id] || (sparkData[id] = []);
        hist.push(value);
        if (hist.length > SPARK_MAX) hist.shift();
        if (hist.length < 2) return;

        const canvas = document.getElementById(id);
        if (!canvas) return;
        if (!sparkCtx[id]) {
          const dpr = window.devicePixelRatio || 1;
          canvas.width = canvas.clientWidth * dpr;
          canvas.height = canvas.clientHeight * dpr;
          sparkCtx[id] = canvas.getContext('2d');
          sparkCtx[id].scale(dpr, dpr);
        }
        const ctx = sparkCtx[id];
        const w = canvas.clientWidth, h = canvas.clientHeight;
        ctx.clearRect(0, 0, w, h);

        let lo = Math.min(...hist), hi = Math.max(...hist);
        if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
        const pad = 3;
        const x = i => (i / (SPARK_MAX - 1)) * (w - 2) + 1;
        const y = v => h - pad - ((v - lo) / (hi - lo)) * (h - pad * 2);

        /*  fill under the curve, then the line itself; colour tracks
            direction: green when the latest sample is at/above where
            the window started, red when below. */
        const up = hist[hist.length - 1] >= hist[0];
        const stroke = up ? '#059669' : '#e11d48';

        ctx.beginPath();
        ctx.moveTo(x(0), y(hist[0]));
        for (let i = 1; i < hist.length; i++) ctx.lineTo(x(i), y(hist[i]));
        ctx.lineTo(x(hist.length - 1), h); ctx.lineTo(x(0), h); ctx.closePath();
        ctx.fillStyle = up ? 'rgba(5,150,105,0.10)' : 'rgba(225,29,72,0.10)';
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(x(0), y(hist[0]));
        for (let i = 1; i < hist.length; i++) ctx.lineTo(x(i), y(hist[i]));
        ctx.strokeStyle = stroke; ctx.lineWidth = 1.6; ctx.lineJoin = 'round';
        ctx.stroke();

        /*  live-end dot */
        ctx.beginPath();
        ctx.arc(x(hist.length - 1), y(hist[hist.length - 1]), 2.2, 0, Math.PI * 2);
        ctx.fillStyle = stroke;
        ctx.fill();
      }

      function renderFrame(f) {
        const hotCyl = (f.cht || []).indexOf(Math.max(...(f.cht || [0])));
        document.getElementById('metric-rpm').textContent = fmt(f.rpm, 0);
        document.getElementById('metric-temp').textContent = fmt(f.cht?.[hotCyl], 1);
        document.getElementById('metric-temp-sub').textContent = "Cyl " + (hotCyl + 1) + " \u00B7 limit 240\u00B0C";
        document.getElementById('metric-oil').textContent = fmt(f.oil_pressure_kpa * 0.145038, 1);
        setKpiDelta('delta-rpm', f.rpm, 0, '');
        setKpiDelta('delta-temp', f.cht?.[hotCyl], 1, '\u00B0');
        setKpiDelta('delta-oil', f.oil_pressure_kpa * 0.145038, 1, '');
        drawSpark('spark-rpm', f.rpm);
        drawSpark('spark-temp', f.cht?.[hotCyl]);
        drawSpark('spark-oil', f.oil_pressure_kpa * 0.145038);
        const oilOk = f.oil_pressure_kpa > 200;
        const oilEl = document.getElementById('metric-oil-status');
        oilEl.textContent = oilOk ? "Nominal" : "LOW";
        oilEl.className = "text-[11px] font-mono font-semibold " + (oilOk ? "text-emerald-700" : "text-rose-700");

        const isMisfire = f.injected_fault === 'MISFIRE' || /misfire/i.test(f.fault_class || '');
        document.getElementById('metric-misfire').textContent = isMisfire ? "Detected" : "0 Detected";

        /*  Flight phase + manual-throttle readout follow the live frame.  */
        if (f.phase && activeProfile !== 'manual') setPhaseChip(f.phase);
        syncThrottleUI(f.throttle);

        /*  Throttle the phone-state publish to ~2 Hz. */
        if (!phoneStateTimer) {
          phoneStateTimer = setTimeout(() => { phoneStateTimer = null; }, 500);
          publishPhoneState(f);
        }

        const json = {
          timestamp: f.timestamp,
          engine_id: API.ENGINE_ID,
          frame_id: f.frame_id,
          observed: {
            rpm: f.rpm, throttle: f.throttle, altitude_ft: f.altitude_ft,
            map_kpa: f.map_kpa, fuel_flow_lph: f.fuel_flow_lph,
            cht_c: f.cht, egt_c: f.egt,
            oil_pressure_kpa: f.oil_pressure_kpa, oil_temp_c: f.oil_temp_c,
            vibration_rms: f.vibration_rms, ambient_temp_c: f.ambient_temp_c
          },
          health: { index: f.health_index, category: f.health_category },
          anomaly: {
            score: f.anomaly_score, detected: f.is_anomaly,
            contributors: (f.anomaly_contributors || []).slice(0, 3)
          },
          prognostics: { rul_min: f.rul_minutes, rtb_alert: f.rtb_alert },
          injected_fault: f.injected_fault,
          source: f.injected_fault && f.source === 'offline' ? 'demo' : (f.source || undefined)
        };
        document.getElementById('json-preview').innerHTML = '<code>' +
          JSON.stringify(json, null, 2).replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</code>';
      }

      API.onFrame(renderFrame);
      API.onFrame(pushFrameToSim);
      API.onStatus(renderStatus);

      let injectTimer = null;
      window.injectFault = function (faultType, sliderVal) {
        const severity = Math.min(1, Math.max(0.05, sliderVal / 100));

        if (faultType === 'OVERHEATING') document.getElementById('sev-thermal').textContent = severity.toFixed(2);
        if (faultType === 'ABNORMAL_VIBRATION') document.getElementById('sev-vibration').textContent = severity.toFixed(2);

        if (API.isOffline()) { API.setDemoFault(faultType, severity); return; }

        clearTimeout(injectTimer);
        injectTimer = setTimeout(() => {
          API.injectFault(faultType, severity)
            .then(() => console.log('[fault] injected ' + faultType + ' @ ' + severity))
            .catch(err => {
              console.warn('[fault] ' + err.message);
              alert('Fault injection failed: ' + err.message);
            });
        }, 300);
      };

      window.clearAllFaults = function () {
        API.setDemoFault(null);
        if (API.isOffline()) return;
        API.clearFaults()
          .then(() => console.log('[fault] cleared'))
          .catch(err => alert('Clear faults failed: ' + err.message));
      };

      window.dispatchWebhook = function () {
        API.health()
          .then(h => alert('Backend live \u00B7 v' + (h.version || '?') + ' \u00B7 uptime ' + h.uptime_s + 's \u00B7 sim: ' + (h.components.simulator)))
          .catch(() => alert('Backend unreachable - page is running on demo data.'));
      };

      window.triggerRunaway = function () {
        const slider = document.querySelector('input[oninput*="OVERHEATING"]');
        if (slider) { slider.value = 100; }
        window.injectFault('OVERHEATING', 100);
        setPreset('takeoff', 5800);
        const sev = document.getElementById('sev-thermal');
        if (sev) sev.textContent = "1.00";
      };

      /*  Forward one frame into the cutaway iframe so the engine
          animation follows the backend, not a local slider.  Speed
          changes are throttle commands - the sim spools between them -
          and the health flags drive its burst watch.  */
      function pushFrameToSim(f) {
        const cutFrame = document.getElementById('cutawayFrame');
        if (cutFrame && cutFrame.contentWindow && f) {
          cutFrame.contentWindow.postMessage({
            type: 'CUTAWAY_ENGINE_STATE',
            rpm: Math.round(f.rpm),
            throttle: f.throttle || 0,
            tempC: Math.max(...(f.cht || [0])),
            oilPsi: (f.oil_pressure_kpa || 0) * 0.145038,
            phase: f.phase || '',
            aboutToBurst: f.anomaly_score >= 0.55,
            overLimit: Math.round(f.rpm) >= 6400 ||
                       (f.rtb_alert || '') === 'RTB_CRITICAL',
            detail: f.injected_fault ||
                    (f.rtb_alert && f.rtb_alert !== 'NONE'
                      ? f.rtb_alert : ''),
            health: f.health_category
          }, '*');
        }
      }

      /* =========================================================================
         BACKEND SYNC
         The dashboard does not just listen - it actively syncs from the
         backend and drives the sim with what it gets:

           1. every 5 s  GET /api/simulation/status - if the mission died
              (backend restart, timeout), start a new one;
           2. every 5 s  GET /api/engine/{id}/state - a REST snapshot that
              keeps the KPIs alive even when the websocket is down;
           3. the state is forwarded into the cutaway iframe
              (CUTAWAY_SET_RPM) and the RPM KPI, so the sim always mirrors
              the backend.
         ========================================================================= */
      const SYNC_INTERVAL_MS = 5000;

      async function syncFromBackend() {

        if (API.isOffline()) return;

        /*  1. mission keeper + flight-phase readout  */
        try {
          const st = await API.simStatus();
          renderFlightStatus(st);
          if (!st.is_running) {
            await API.startMission('Dashboard session', 3600, 'manual');
            console.log('[sync] interactive session restarted');
          }
        } catch (e) {
          console.warn('[sync] status failed:', e.message);
          return;
        }

        /*  2. REST state snapshot  */
        try {
          const r = await fetch('/api/engine/' + API.ENGINE_ID + '/state',
            { cache: 'no-store' });
          if (r.ok) {
            const state = await r.json();
            const frame = API.flatten(state);

            /*  3. push it at the UI and the sim  */
            renderFrame(frame);
            pushFrameToSim(frame);
          }
        } catch (e) {
          /*  the WS path already renders frames; silence is fine here  */
        }
      }

      /*  A user request for a burst test: drive the backend to the redline
          and let the sim's own protection pull it back.  */
      window.panicTest = function () {
        API.setThrottle(1.0)
          .then(() => console.log('[sync] throttle -> 1.0 (panic test)'))
          .catch(err => console.warn('[sync] throttle failed:', err.message));
      };

      /*  renderFlightStatus: the backend's own view of the session. The
          Test Flight button tracks the profile actually running; phase
          text comes from the live frames. */
      function renderFlightStatus(st) {
        if (!st) return;
        activeProfile = st.profile || null;
        const nowFlying = !!(st.is_running && st.profile === FLIGHT_PROFILE);
        setFlying(nowFlying);
      }

      /* =========================================================================
         FLIGHT CONTROL
         Three ways to drive the engine:

           Engine presets - Idle / Cruise / Takeoff: one click sets a
                            commanded throttle; the engine spools there.
           Test Flight    - starts the backend's compressed "test_flight"
                            profile (~2.5 min): idle, takeoff, climb,
                            cruise, descent, landing. The Abort button
                            stops the profile and spools back to idle.
           Throttle       - manual control: drag the slider (or use the
                            paired phone), the engine is commanded to
                            that throttle and visibly spools.
         ========================================================================= */
      const FLIGHT_PROFILE = 'test_flight';
      /*  Interactive floor: 5 % keeps the engine idling instead of dying
          to a stop when the stick is pulled all the way down. */
      const THROTTLE_FLOOR = 0.05;
      let ctlCursor = 0;                   // /__ctl REST fallback cursor
      let flying = false;
      let manualMode = false;              // slider has taken the stick
      let activeProfile = null;            // what the session is flying
      let demoFlightTimer = null;

      const phaseChip = document.getElementById('flightPhaseChip');
      const testFlightBtn = document.getElementById('testFlightBtn');
      const abortFlightBtn = document.getElementById('abortFlightBtn');
      const releaseToIdleBtn = document.getElementById('releaseToIdleBtn');
      const manualChip = document.getElementById('manualChip');
      const throttleSlider = document.getElementById('throttleSlider');
      const throttleReadout = document.getElementById('throttleReadout');
      const throttleBox = document.getElementById('manualThrottle');

      /*  The cutaway iframe also honours CUTAWAY_SET_THROTTLE; fall back
          to the RPM mapping for older copies of the simulator. */
      function commandSim(throttle) {
        const cutFrame = document.getElementById('cutawayFrame');
        if (cutFrame && cutFrame.contentWindow) {
          cutFrame.contentWindow.postMessage(
            { type: 'CUTAWAY_SET_THROTTLE', throttle: throttle }, '*');
          cutFrame.contentWindow.postMessage(
            { type: 'CUTAWAY_SET_RPM', rpm: Math.round(throttle * 3600) }, '*');
        }
      }

      function setPhaseChip(phase) {
        if (!phaseChip) return;
        phaseChip.textContent = 'PHASE: ' + String(phase).toUpperCase();
        phaseChip.classList.remove('hidden');
        const c = PHASE_STYLES[phase] || PHASE_STYLES["CRUISE"];
        phaseChip.className =
          'font-mono font-bold text-[10px] px-2 py-0.5 rounded border ' + c;
      }

      function hidePhaseChip() {
        if (!phaseChip) return;
        phaseChip.classList.add('hidden');
      }

      function setFlying(on) {
        flying = on;
        if (testFlightBtn) testFlightBtn.style.display = on ? 'none' : '';
        if (abortFlightBtn) abortFlightBtn.style.display = on ? '' : 'none';
      }

      function setManual(on) {
        manualMode = on;
        if (manualChip) manualChip.classList.toggle('hidden', !on);
        if (throttleBox) {
          throttleBox.classList.toggle('ring-1', on);
          throttleBox.classList.toggle('ring-emerald-400/60', on);
        }
      }

      const PHASE_STYLES = {
        STARTUP:  'bg-stone-800 text-stone-300 border-stone-600',
        TAKEOFF:  'bg-amber-500/20 text-amber-300 border-amber-500/40',
        CLIMB:    'bg-sky-500/20 text-sky-300 border-sky-500/40',
        CRUISE:   'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
        ENDURANCE:'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
        DESCENT:  'bg-indigo-500/20 text-indigo-300 border-indigo-500/40',
        LANDING:  'bg-rose-500/20 text-rose-300 border-rose-500/40'
      };

      /*  Manual throttle. Slider drags command the engine directly and
          suspend the flight profile; it resumes when Abort/Start is next
          used. Kept to one POST per frame - the 0.75 s debounce below -
          so dragging does not flood the backend.                       */
      let throttleDebounce = null;
      let lastSentThrottle = null;

      function syncThrottleUI(throttle) {
        /*  Follow the engine: slider + readout mirror the live frame so
            the profile moves the stick too, unless the user is on it. */
        if (throttle == null || isNaN(throttle)) return;
        if (throttleReadout) throttleReadout.textContent = Math.round(throttle * 100) + '%';
        if (throttleSlider && document.activeElement !== throttleSlider && !manualMode) {
          throttleSlider.value = String(Math.round(throttle * 100));
        }
      }

      function sendThrottle(v) {
        const throttle = Math.min(1, Math.max(THROTTLE_FLOOR, v));
        setManual(true);
        if (API.isOffline()) {
          API.setDemoThrottle(throttle);
          commandSim(throttle);
          return;
        }
        if (throttle === lastSentThrottle) return;
        lastSentThrottle = throttle;
        API.setThrottle(throttle)
          .then(() => commandSim(throttle))
          .catch(err => {
            console.warn('[throttle] failed:', err.message);
            lastSentThrottle = null;
            /*  Backend refused (no mission?): drive the sim iframe alone
                so the engine still reacts to the slider. */
            commandSim(throttle);
          });
      }

      if (throttleSlider) {
        const onSlider = () => {
          setManual(true);
          const v = Number(throttleSlider.value) / 100;
          if (throttleReadout) throttleReadout.textContent = Math.round(v * 100) + '%';
          clearTimeout(throttleDebounce);
          throttleDebounce = setTimeout(() => sendThrottle(v), 300);
        };
        throttleSlider.addEventListener('input', onSlider);
        throttleSlider.addEventListener('change', () => {
          /*  Final command on release - no debounce tail. */
          setManual(true);
          sendThrottle(Number(throttleSlider.value) / 100);
        });
      }

      /*  Hand the stick back to the engine: clear the manual override,
          spool down to ground idle. Works with the backend running and
          in demo mode. */
      async function releaseToIdle() {
        setManual(false);
        lastSentThrottle = null;
        if (API.isOffline()) {
          API.setDemoThrottle(null);
          commandSim(THROTTLE_FLOOR);
          if (throttleSlider) throttleSlider.value = String(Math.round(THROTTLE_FLOOR * 100));
          if (throttleReadout) throttleReadout.textContent = Math.round(THROTTLE_FLOOR * 100) + '%';
          return;
        }
        try {
          await API.releaseThrottle();
          if (throttleSlider) throttleSlider.value = String(Math.round(THROTTLE_FLOOR * 100));
          if (throttleReadout) throttleReadout.textContent = Math.round(THROTTLE_FLOOR * 100) + '%';
          console.log('[throttle] released to profile (idle-parked session)');
        } catch (e) {
          console.warn('[throttle] release failed:', e.message);
          /*  Fallback: command idle directly. */
          sendThrottle(THROTTLE_FLOOR);
        }
      }
      if (releaseToIdleBtn) releaseToIdleBtn.addEventListener('click', releaseToIdle);

      async function startTestFlight() {
        setFlying(true);
        setManual(false);
        activeProfile = FLIGHT_PROFILE;
        lastSentThrottle = null;
        try {
          /*  160 s: the ~142 s profile plus a short hold at idle after
              landing; the next backend sync then flips the UI back. */
          await API.startSimulation(FLIGHT_PROFILE, 'Test Flight', 160);
          console.log('[flight] test flight started (backend)');
        } catch (e) {
          console.warn('[flight] backend start failed, flying demo profile:', e.message);
          API.startDemoFlight();
          setPhaseChip('STARTUP');
          /*  The demo generator cannot tell us when the profile is over,
              so time it here: back to idle state once it has landed.  */
          clearTimeout(demoFlightTimer);
          demoFlightTimer = setTimeout(() => setFlying(false),
            (API.DEMO_FLIGHT_TOTAL_S + 5) * 1000);
        }
      }

      async function abortFlight() {
        setManual(false);
        activeProfile = null;
        clearTimeout(demoFlightTimer);
        try {
          await API.stopSimulation();
          console.log('[flight] aborted (backend)');
        } catch (e) {
          console.warn('[flight] backend stop failed:', e.message);
        }
        API.stopDemoFlight();
        setFlying(false);
        /*  Spool back down to ground idle instead of leaving the engine
            hanging at whatever throttle the profile was mid-flight at. */
        await releaseToIdle();
      }

      if (testFlightBtn) testFlightBtn.addEventListener('click', startTestFlight);
      if (abortFlightBtn) abortFlightBtn.addEventListener('click', abortFlight);

      /* =========================================================================
         PHONE CONTROLLER
         The paired phone is a live throttle lever for this dashboard.
         cutaway.html relays {type: PHONE_CMD, cmd, value} messages from
         the phone's WebRTC data channel; the same commands also arrive
         as HTTP (serve.py /__ctl) for the phone page's REST mode.
         ========================================================================= */
      const PHONE_CMDS = {
        throttle(v) { sendThrottle(Number(v)); },
        release()   { releaseToIdle(); },
        preset(name) {
          const rpm = { idle: 1200, cruise: 2400, takeoff: 5800 }[name];
          if (rpm) setPreset(name, rpm);
        },
        flight()    { flying ? abortFlight() : startTestFlight(); },
        abort()     { if (flying) abortFlight(); }
      };

      function runPhoneCmd(cmd, value) {
        const fn = PHONE_CMDS[cmd];
        if (fn) { try { fn(value); } catch (e) { console.warn('[phone] cmd failed:', e); } }
      }

      /*  The sim iframe relays data-channel commands from the phone. */
      window.addEventListener('message', (ev) => {
        const d = ev.data;
        if (!d || typeof d !== 'object') return;
        if (d.type === 'PHONE_CMD') runPhoneCmd(d.cmd, d.value);
      });

      /*  REST fallback: the phone page polls /__ctl for queued commands
          (works even without a WebRTC data channel). */
      setInterval(async () => {
        try {
          const r = await fetch('/__ctl?since=' + ctlCursor, { cache: 'no-store' });
          if (!r.ok) return;
          const data = await r.json();
          ctlCursor = data.cursor != null ? data.cursor : ctlCursor;
          (data.commands || []).forEach(c => runPhoneCmd(c.cmd, c.value));
        } catch (noCtl) { /* serve.py without the ctl relay - fine */ }
      }, 1200);

      setInterval(syncFromBackend, SYNC_INTERVAL_MS);

      /*  Manual "Sync" button: run one sync pass right now.  */
      const syncBtn = document.getElementById('syncSimBtn');
      if (syncBtn) {
        syncBtn.addEventListener('click', () => {
          syncFromBackend();
          pushFrameToSim(API.frame);
          const prev = syncBtn.title;
          syncBtn.title = 'Synced ' + new Date().toLocaleTimeString();
          setTimeout(() => { syncBtn.title = prev; }, 1500);
        });
      }
    } else {
      console.warn('AEROTWIN_API not found, UI will use static demo values.');
      document.getElementById('connLabel').textContent = "STATUS: DEMO (no API)";
    }
  