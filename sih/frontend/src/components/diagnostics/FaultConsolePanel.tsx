// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — Fault Injection Console
// ══════════════════════════════════════════════════════════════════════════════
//
// Drives the demo: pick a real fault from the backend's own enum, set its
// severity and (for the sensor faults) which channel it hits, inject it, and
// watch the twin respond. Every injection is listed from the audit trail.
//
//   GET  /api/faults/types    — the fault catalogue + recommended action
//   POST /api/faults/inject   — { fault_type, severity, target_sensor }
//   POST /api/faults/clear
//   GET  /api/faults/history  — what has been injected, newest first
//
// The fault names come from the backend, not from a hardcoded list here: a
// name the backend does not recognise used to be swallowed silently, so a
// button could look like it worked and do nothing.
// ══════════════════════════════════════════════════════════════════════════════

import { useCallback, useState } from 'react';
import clsx from 'clsx';
import { AlertTriangle, RotateCcw, Snowflake, Trash2, Zap } from 'lucide-react';

import api from '../../services/api';
import { describeApiError, useApiResource } from '../../hooks/useApiResource';
import { faultLabel } from '../../lib/adapters';
import { useToast } from '../ui/Toast';

interface FaultConsolePanelProps {
  className?: string;
  /** Only show history for this mission. */
  missionId?: string | null;
}

/** Channels the sensor faults can target, named as the generator names them. */
const SENSOR_CHANNELS = [
  'cht_c1', 'cht_c2', 'cht_c3', 'cht_c4',
  'egt_c1', 'egt_c2', 'egt_c3', 'egt_c4',
  'oil_pressure_kpa', 'oil_temp_c', 'vibration_rms_g',
  'battery_v', 'alternator_a', 'rpm', 'fuel_flow_lph',
];

const SENSOR_FAULTS = ['SENSOR_DRIFT', 'SENSOR_DROPOUT'];

export default function FaultConsolePanel({ className, missionId }: FaultConsolePanelProps) {
  const { addToast } = useToast();

  const catalogue = useApiResource(() => api.faults.types(), { intervalMs: 60_000 });
  const history = useApiResource(() => api.faults.history(missionId ?? undefined, 50), {
    intervalMs: 5000,
    deps: [missionId],
  });

  const [severity, setSeverity] = useState(0.7);
  const [channel, setChannel] = useState('cht_c2');
  const [busy, setBusy] = useState<string | null>(null);

  const inject = useCallback(
    async (faultType: string) => {
      setBusy(faultType);
      try {
        const needsChannel = SENSOR_FAULTS.includes(faultType);
        await api.faults.inject({
          fault_type: faultType as never,
          severity,
          target_sensor: needsChannel ? channel : null,
        });
        addToast(
          `${faultLabel(faultType)} injected at severity ${severity.toFixed(2)}` +
            (needsChannel ? ` on ${channel}` : ''),
          'warning'
        );
        await history.reload();
      } catch (err) {
        addToast(`Injection rejected — ${describeApiError(err)}`, 'error');
      } finally {
        setBusy(null);
      }
    },
    [addToast, channel, history, severity]
  );

  const clearAll = useCallback(async () => {
    setBusy('__clear__');
    try {
      await api.faults.clear();
      addToast('All faults cleared — engine back to nominal', 'success');
      await history.reload();
    } catch (err) {
      addToast(`Clear failed — ${describeApiError(err)}`, 'error');
    } finally {
      setBusy(null);
    }
  }, [addToast, history]);

  const faultTypes = catalogue.data?.fault_types ?? [];
  const rows = history.data?.faults ?? [];

  return (
    <div className={clsx('hud-panel flex flex-col', className)}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-hud-amber" />
          <h3 className="text-sm font-medium text-cockpit-muted">Fault Injection</h3>
        </div>
        <button
          onClick={clearAll}
          disabled={busy !== null}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-nominal-green/20 text-nominal-green hover:bg-nominal-green/30 transition-colors disabled:opacity-50"
        >
          <RotateCcw className="w-3 h-3" />
          Clear all
        </button>
      </div>

      {catalogue.error && (
        <p className="mb-3 text-xs text-alert-red">
          Fault catalogue unavailable — {catalogue.error}
        </p>
      )}

      {/* Severity + target channel */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
        <label className="block">
          <span className="flex items-center justify-between text-xs text-cockpit-muted mb-1">
            <span>Severity</span>
            <span className="data-display text-white">{severity.toFixed(2)}</span>
          </span>
          <input
            type="range"
            min="0.1"
            max="1"
            step="0.05"
            value={severity}
            onChange={(e) => setSeverity(Number(e.target.value))}
            className="w-full accent-hud-amber"
          />
        </label>

        <label className="block">
          <span className="flex items-center gap-1 text-xs text-cockpit-muted mb-1">
            <Snowflake className="w-3 h-3" /> Sensor-drift/dropout channel
          </span>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            className="w-full px-2 py-1.5 rounded-lg bg-cockpit-bg border border-cockpit-border text-xs text-white focus:border-hud-amber outline-none"
          >
            {SENSOR_CHANNELS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* The catalogue */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-4">
        {faultTypes.length === 0 && !catalogue.loading && (
          <p className="text-xs text-cockpit-muted">No fault types reported by the backend.</p>
        )}
        {faultTypes.map((f) => {
          const critical = (f.criticality ?? 0) >= 0.75;
          return (
            <button
              key={f.type}
              onClick={() => inject(f.type)}
              disabled={busy !== null}
              title={(f.action as string | undefined) ?? undefined}
              className={clsx(
                'flex flex-col items-start gap-0.5 px-3 py-2 rounded-lg border text-left transition-all disabled:opacity-50',
                critical
                  ? 'bg-alert-red/15 border-alert-red/40 hover:bg-alert-red/25'
                  : 'bg-hud-amber/15 border-hud-amber/40 hover:bg-hud-amber/25'
              )}
            >
              <span
                className={clsx(
                  'text-xs font-medium',
                  critical ? 'text-alert-red' : 'text-hud-amber'
                )}
              >
                {faultLabel(f.type)}
                {busy === f.type && ' …'}
              </span>
              <span className="text-[10px] text-cockpit-muted">
                criticality {((f.criticality ?? 0) * 100).toFixed(0)}%
              </span>
            </button>
          );
        })}
      </div>

      {faultTypes.length > 0 && (
        <p className="mb-4 text-[10px] text-cockpit-muted leading-relaxed">
          Faults ramp in over ~60 s, which is why the anomaly score climbs rather
          than jumping. Every injection is logged below.
        </p>
      )}

      {/* Audit trail */}
      <div className="flex items-center justify-between mb-2">
        <span className="flex items-center gap-1 text-xs text-cockpit-muted">
          <AlertTriangle className="w-3 h-3" /> Incident log
        </span>
        <span className="text-xs text-cockpit-muted">
          {rows.length} {rows.length === 1 ? 'entry' : 'entries'}
        </span>
      </div>

      {history.error ? (
        <p className="text-xs text-alert-red">{history.error}</p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-cockpit-muted py-4 text-center">
          Nothing injected yet — no incident to report.
        </p>
      ) : (
        <div className="max-h-56 overflow-auto -mx-1 px-1">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-cockpit-surface">
              <tr className="text-left text-cockpit-muted border-b border-cockpit-border">
                <th className="pb-1 font-medium">Time</th>
                <th className="pb-1 font-medium">Fault</th>
                <th className="pb-1 font-medium">Sev</th>
                <th className="pb-1 font-medium">Channel</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-cockpit-border/40">
                  <td className="py-1 font-mono text-cockpit-muted">
                    {r.injected_at
                      ? new Date(r.injected_at).toLocaleTimeString()
                      : '—'}
                  </td>
                  <td className="py-1 text-white">{faultLabel(r.fault_type)}</td>
                  <td className="py-1 data-display text-hud-amber">
                    {Number(r.severity).toFixed(2)}
                  </td>
                  <td className="py-1 font-mono text-cockpit-muted">
                    {r.target_sensor ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Small helper so the modal in App.tsx can reuse the same rendering. */
export function FaultHistoryTable({ missionId }: { missionId?: string | null }) {
  const history = useApiResource(() => api.faults.history(missionId ?? undefined, 200), {
    intervalMs: 5000,
    deps: [missionId],
  });
  const rows = history.data?.faults ?? [];

  if (history.error) return <p className="text-xs text-alert-red">{history.error}</p>;
  if (rows.length === 0) {
    return <p className="text-xs text-cockpit-muted py-6 text-center">No incidents logged.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-cockpit-muted border-b border-cockpit-border">
            <th className="pb-2 font-medium">Time</th>
            <th className="pb-2 font-medium">Mission</th>
            <th className="pb-2 font-medium">Fault</th>
            <th className="pb-2 font-medium">Severity</th>
            <th className="pb-2 font-medium">Channel</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b border-cockpit-border/40">
              <td className="py-2 font-mono text-xs text-cockpit-muted">
                {r.injected_at ? new Date(r.injected_at).toLocaleString() : '—'}
              </td>
              <td className="py-2 font-mono text-xs">{r.mission_id.slice(0, 8)}…</td>
              <td className="py-2">{faultLabel(r.fault_type)}</td>
              <td className="py-2 data-display text-hud-amber">
                {Number(r.severity).toFixed(2)}
              </td>
              <td className="py-2 font-mono text-xs text-cockpit-muted">
                {r.target_sensor ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-cockpit-muted flex items-center gap-1">
        <Trash2 className="w-3 h-3" /> Source: GET /api/faults/history
      </p>
    </div>
  );
}
