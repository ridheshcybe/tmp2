// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — Mission Control
// ══════════════════════════════════════════════════════════════════════════════
//
// The panel that starts and stops the simulator, and steers it while it runs.
// Without it the cockpit only shows what the backend already happens to be
// doing — there is no way to begin a mission from the dashboard.
//
//   POST /api/missions/start | /api/missions/{id}/stop
//   GET  /api/simulation/status
//   POST /api/simulation/throttle | /api/simulation/altitude
// ══════════════════════════════════════════════════════════════════════════════

import { useCallback, useEffect, useRef, useState } from 'react';
import clsx from 'clsx';
import { Activity, Gauge, Play, Square, Thermometer, Wind } from 'lucide-react';

import api, { DEFAULT_ENGINE_ID } from '../../services/api';
import { describeApiError, useApiResource } from '../../hooks/useApiResource';
import { fmtClock } from '../../lib/adapters';
import { useToast } from '../ui/Toast';

interface MissionControlPanelProps {
  engineId?: string;
  className?: string;
  /** Called after a mission starts or stops, so views can refresh. */
  onMissionChanged?: (missionId: string | null) => void;
}

const DURATIONS = [
  { label: '2 min', value: 120 },
  { label: '5 min', value: 300 },
  { label: '10 min', value: 600 },
  { label: '30 min', value: 1800 },
];

export default function MissionControlPanel({
  engineId = DEFAULT_ENGINE_ID,
  className,
  onMissionChanged,
}: MissionControlPanelProps) {
  const { addToast } = useToast();

  const status = useApiResource(() => api.simulation.status(), { intervalMs: 2500 });

  const running = Boolean(status.data?.is_running);
  const missionId = status.data?.mission_id ?? null;

  // ── start form ────────────────────────────────────────────────────────────
  const [name, setName] = useState('Tapas-BH-201 sortie');
  const [duration, setDuration] = useState(300);
  const [ambient, setAmbient] = useState(0);
  const [busy, setBusy] = useState(false);

  const start = useCallback(async () => {
    setBusy(true);
    try {
      const result = await api.missions.start({
        engine_id: engineId,
        duration_s: duration,
        ambient_offset_c: ambient,
        name: name.trim() || null,
      });
      addToast(`Mission started (${result.mission_id.slice(0, 8)}…)`, 'success');
      await status.reload();
      onMissionChanged?.(result.mission_id);
    } catch (err) {
      addToast(`Could not start mission — ${describeApiError(err)}`, 'error');
    } finally {
      setBusy(false);
    }
  }, [addToast, ambient, duration, engineId, name, onMissionChanged, status]);

  const stop = useCallback(async () => {
    if (!missionId) return;
    setBusy(true);
    try {
      await api.missions.stop(missionId);
      addToast('Mission stopped — telemetry is stored and replayable', 'info');
      await status.reload();
      onMissionChanged?.(null);
    } catch (err) {
      addToast(`Could not stop mission — ${describeApiError(err)}`, 'error');
    } finally {
      setBusy(false);
    }
  }, [addToast, missionId, onMissionChanged, status]);

  // ── live controls ─────────────────────────────────────────────────────────
  const [throttle, setThrottle] = useState(0.4);
  const [altitude, setAltitude] = useState(10000);
  const commitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (commitTimer.current) clearTimeout(commitTimer.current);
  }, []);

  /*  Sliders fire on every pixel; push the value to the simulator once the
      pilot stops moving (300 ms) rather than once per render.  */
  const commitThrottle = useCallback(
    (value: number) => {
      if (commitTimer.current) clearTimeout(commitTimer.current);
      commitTimer.current = setTimeout(() => {
        api.simulation
          .throttle(value)
          .catch((err) => addToast(`Throttle rejected — ${describeApiError(err)}`, 'error'));
      }, 300);
    },
    [addToast]
  );

  const commitAltitude = useCallback(
    (value: number) => {
      if (commitTimer.current) clearTimeout(commitTimer.current);
      commitTimer.current = setTimeout(() => {
        api.simulation
          .altitude(value)
          .catch((err) => addToast(`Altitude rejected — ${describeApiError(err)}`, 'error'));
      }, 300);
    },
    [addToast]
  );

  return (
    <div className={clsx('hud-panel', className)}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyber-cyan" />
          <h3 className="text-sm font-medium text-cockpit-muted">Mission Control</h3>
        </div>
        <span
          className={clsx(
            'px-2 py-1 rounded text-xs font-medium',
            running
              ? 'bg-nominal-green/20 text-nominal-green'
              : 'bg-cockpit-surface text-cockpit-muted'
          )}
        >
          {running ? 'RUNNING' : 'IDLE'}
        </span>
      </div>

      {status.error && (
        <p className="mb-3 text-xs text-alert-red">
          Simulation status unavailable — {status.error}
        </p>
      )}

      {/* Live status */}
      <dl className="grid grid-cols-2 gap-3 mb-4 text-xs">
        <div className="p-2 rounded bg-cockpit-bg/50">
          <dt className="text-cockpit-muted">Mission</dt>
          <dd className="data-display text-white">
            {missionId ? `${missionId.slice(0, 8)}…` : '—'}
          </dd>
        </div>
        <div className="p-2 rounded bg-cockpit-bg/50">
          <dt className="text-cockpit-muted">Elapsed</dt>
          <dd className="data-display text-white">
            {status.data ? fmtClock(status.data.sim_time_s) : '--:--'}
          </dd>
        </div>
        <div className="p-2 rounded bg-cockpit-bg/50">
          <dt className="text-cockpit-muted">Frames</dt>
          <dd className="data-display text-white">{status.data?.frame_id ?? 0}</dd>
        </div>
        <div className="p-2 rounded bg-cockpit-bg/50">
          <dt className="text-cockpit-muted">Rate</dt>
          <dd className="data-display text-white">{status.data?.hz ?? 0} Hz</dd>
        </div>
      </dl>

      {(status.data?.active_faults?.length ?? 0) > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="text-xs text-cockpit-muted">Active faults:</span>
          {status.data?.active_faults.map((f) => (
            <span
              key={f}
              className="px-2 py-0.5 rounded text-xs bg-alert-red/20 text-alert-red border border-alert-red/40"
            >
              {f}
            </span>
          ))}
        </div>
      )}

      {running ? (
        <div className="space-y-4">
          {/* Throttle */}
          <label className="block">
            <span className="flex items-center justify-between text-xs text-cockpit-muted mb-1">
              <span className="flex items-center gap-1">
                <Gauge className="w-3 h-3" /> Throttle
              </span>
              <span className="data-display text-white">{(throttle * 100).toFixed(0)}%</span>
            </span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={throttle}
              onChange={(e) => {
                const v = Number(e.target.value);
                setThrottle(v);
                commitThrottle(v);
              }}
              className="w-full accent-cyber-cyan"
            />
          </label>

          {/* Altitude */}
          <label className="block">
            <span className="flex items-center justify-between text-xs text-cockpit-muted mb-1">
              <span className="flex items-center gap-1">
                <Wind className="w-3 h-3" /> Altitude
              </span>
              <span className="data-display text-white">
                {altitude.toLocaleString()} ft
              </span>
            </span>
            <input
              type="range"
              min="0"
              max="25000"
              step="500"
              value={altitude}
              onChange={(e) => {
                const v = Number(e.target.value);
                setAltitude(v);
                commitAltitude(v);
              }}
              className="w-full accent-cyber-cyan"
            />
          </label>

          <button
            onClick={stop}
            disabled={busy}
            className="w-full flex items-center justify-center gap-2 py-2 rounded-lg bg-alert-red/20 text-alert-red border border-alert-red/40 hover:bg-alert-red/30 transition-colors text-sm font-medium disabled:opacity-50"
          >
            <Square className="w-4 h-4" />
            Stop mission
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <label className="block">
            <span className="text-xs text-cockpit-muted">Mission name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-lg bg-cockpit-bg border border-cockpit-border text-sm text-white focus:border-cyber-cyan outline-none"
            />
          </label>

          <div>
            <span className="text-xs text-cockpit-muted">Duration</span>
            <div className="mt-1 grid grid-cols-4 gap-2">
              {DURATIONS.map((d) => (
                <button
                  key={d.value}
                  onClick={() => setDuration(d.value)}
                  className={clsx(
                    'py-1.5 rounded text-xs font-medium transition-colors',
                    duration === d.value
                      ? 'bg-cyber-cyan text-cockpit-bg'
                      : 'bg-cockpit-surface text-cockpit-muted hover:bg-cockpit-border'
                  )}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          <label className="block">
            <span className="flex items-center justify-between text-xs text-cockpit-muted mb-1">
              <span className="flex items-center gap-1">
                <Thermometer className="w-3 h-3" /> Ambient offset
              </span>
              <span className="data-display text-white">
                {ambient > 0 ? '+' : ''}
                {ambient} °C
              </span>
            </span>
            <input
              type="range"
              min="-20"
              max="30"
              step="5"
              value={ambient}
              onChange={(e) => setAmbient(Number(e.target.value))}
              className="w-full accent-hud-amber"
            />
            <span className="text-[10px] text-cockpit-muted">
              Hot-weather and cold-start scenarios
            </span>
          </label>

          <button
            onClick={start}
            disabled={busy || status.loading}
            className="w-full flex items-center justify-center gap-2 py-2 rounded-lg bg-cyber-cyan/20 text-cyber-cyan border border-cyber-cyan/40 hover:bg-cyber-cyan/30 transition-colors text-sm font-medium disabled:opacity-50"
          >
            <Play className="w-4 h-4" />
            {busy ? 'Starting…' : 'Start mission'}
          </button>

          <p className="text-[10px] text-cockpit-muted">
            Starting a mission clears any fault still injected from the previous
            one — the engine comes up healthy.
          </p>
        </div>
      )}
    </div>
  );
}
