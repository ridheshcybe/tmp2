// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — Physics Residuals
// ══════════════════════════════════════════════════════════════════════════════
//
// The explainability panel: for each sensor channel, what the physics baseline
// expected, what the engine actually did, and how far apart they are in units
// and in sigmas of the healthy baseline.
//
// This is the evidence behind every health score — "EGT is +76 °C above the
// physics model" is a statement an engineer can act on, where "anomaly 71/100"
// is not. It reads the twin state straight off the WebSocket, which is why the
// context keeps the raw EngineState alongside the flattened frame.
// ══════════════════════════════════════════════════════════════════════════════

import clsx from 'clsx';
import { FlaskConical, Info } from 'lucide-react';

import { useTelemetry } from '../../context/TelemetryContext';
import { RESIDUAL_LABELS } from '../../lib/residuals';

interface PhysicsResidualsPanelProps {
  className?: string;
}

export default function PhysicsResidualsPanel({ className }: PhysicsResidualsPanelProps) {
  const { lastState, warmingUp, connectionStatus } = useTelemetry();
  const residuals = lastState?.residuals ?? [];

  const zStyle = (z: number) => {
    const a = Math.abs(z);
    if (a >= 4) return 'text-alert-red';
    if (a >= 2) return 'text-hud-amber';
    return 'text-nominal-green';
  };

  return (
    <div className={clsx('hud-panel flex flex-col', className)}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <FlaskConical className="w-4 h-4 text-cyber-cyan" />
          <h3 className="text-sm font-medium text-cockpit-muted">
            Physics Residuals — observed vs expected
          </h3>
        </div>
        {lastState && (
          <span className="text-xs text-cockpit-muted font-mono">
            frame {lastState.frame_id}
          </span>
        )}
      </div>

      {warmingUp && (
        <div className="mb-3 flex items-start gap-2 p-2 rounded-lg bg-hud-amber/10 border border-hud-amber/30">
          <Info className="w-3.5 h-3.5 text-hud-amber mt-0.5 shrink-0" />
          <p className="text-[11px] text-hud-amber leading-relaxed">
            Engine warming up — the baseline describes a warm engine, so these
            residuals are large by definition and the health index is held at
            WATCH until the heads reach operating temperature.
          </p>
        </div>
      )}

      {residuals.length === 0 ? (
        <p className="text-xs text-cockpit-muted py-6 text-center">
          {connectionStatus === 'CONNECTED'
            ? 'Waiting for the first frame of a mission.'
            : 'Not connected — start the backend and a mission to see residuals.'}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-cockpit-muted border-b border-cockpit-border">
                <th className="pb-2 font-medium">Channel</th>
                <th className="pb-2 font-medium text-right">Observed</th>
                <th className="pb-2 font-medium text-right">Expected</th>
                <th className="pb-2 font-medium text-right">Residual</th>
                <th className="pb-2 font-medium text-right">σ</th>
              </tr>
            </thead>
            <tbody>
              {residuals.map((r) => (
                <tr key={r.channel} className="border-b border-cockpit-border/40">
                  <td className="py-1.5 text-white">
                    {RESIDUAL_LABELS[r.channel] ?? r.channel}
                  </td>
                  <td className="py-1.5 text-right data-display text-white">
                    {fmt(r.observed)}
                    <span className="text-cockpit-muted"> {r.unit}</span>
                  </td>
                  <td className="py-1.5 text-right data-display text-cockpit-muted">
                    {fmt(r.expected)}
                  </td>
                  <td
                    className={clsx(
                      'py-1.5 text-right data-display',
                      Math.abs(r.z_score) >= 4
                        ? 'text-alert-red'
                        : Math.abs(r.z_score) >= 2
                          ? 'text-hud-amber'
                          : 'text-nominal-green'
                    )}
                  >
                    {r.residual > 0 ? '+' : ''}
                    {fmt(r.residual)}
                  </td>
                  <td className={clsx('py-1.5 text-right data-display', zStyle(r.z_score))}>
                    {r.z_score > 0 ? '+' : ''}
                    {r.z_score.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-3 text-[10px] text-cockpit-muted leading-relaxed">
        residual = observed − expected, from the analytic ISA + thermal baseline
        (ml/physics_baseline.py). σ is measured against the fitted healthy
        residual baseline, so ±2σ is normal operation.
      </p>
    </div>
  );
}

function fmt(value: number | undefined | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1000) return value.toFixed(0);
  if (abs >= 100) return value.toFixed(1);
  if (abs >= 1) return value.toFixed(2);
  return value.toFixed(3);
}
