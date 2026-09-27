// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — Mission Browser
// ══════════════════════════════════════════════════════════════════════════════
//
// Every mission the backend has stored, with the statistics the twin recorded
// for it (GET /api/missions, /api/missions/{id} → { mission, stats }). From here
// a past sortie can be replayed in the cockpit or turned into a report.
// ══════════════════════════════════════════════════════════════════════════════

import { useCallback, useState } from 'react';
import clsx from 'clsx';
import { Clock, Download, FileText, History, Play, RefreshCw } from 'lucide-react';

import api from '../../services/api';
import { useApiResource } from '../../hooks/useApiResource';
import { fmtDuration } from '../../lib/adapters';

interface MissionBrowserProps {
  className?: string;
  /** Mission to expand, usually the one currently running. */
  currentMissionId?: string | null;
  onReplay?: (missionId: string) => void;
  onOpenReport?: (missionId: string) => void;
}

interface MissionStats {
  frame_count?: number;
  max_anomaly?: number;
  min_health?: number;
  avg_health?: number;
  avg_rul?: number;
  min_rul?: number;
  anomaly_count?: number;
  fault_distribution?: Record<string, number>;
}

export default function MissionBrowser({
  className,
  currentMissionId,
  onReplay,
  onOpenReport,
}: MissionBrowserProps) {
  const [selected, setSelected] = useState<string | null>(null);

  const missions = useApiResource(() => api.missions.list(50), { intervalMs: 10_000 });
  const rows = missions.data?.missions ?? [];

  const effective = selected ?? currentMissionId ?? null;

  const detail = useApiResource(
    () => api.missions.get(effective as string),
    { enabled: Boolean(effective), deps: [effective] }
  );

  const stats = (detail.data?.stats ?? {}) as MissionStats;

  const select = useCallback((id: string) => setSelected(id), []);

  return (
    <div className={clsx('hud-panel flex flex-col', className)}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-cyber-cyan" />
          <h3 className="text-sm font-medium text-cockpit-muted">Missions</h3>
        </div>
        <button
          onClick={() => void missions.reload()}
          className="p-1.5 rounded bg-cockpit-surface hover:bg-cockpit-border transition-colors"
          title="Refresh"
        >
          <RefreshCw className={clsx('w-3.5 h-3.5 text-cockpit-muted', missions.loading && 'animate-spin')} />
        </button>
      </div>

      {missions.error && (
        <p className="mb-3 text-xs text-alert-red">Mission list unavailable — {missions.error}</p>
      )}

      {rows.length === 0 ? (
        <p className="text-xs text-cockpit-muted py-6 text-center">
          No missions stored yet. Start one from Mission Control.
        </p>
      ) : (
        <div className="max-h-64 overflow-auto -mx-1 px-1 mb-4">
          <ul className="space-y-1">
            {rows.map((m) => {
              const live = m.status === 'RUNNING';
              return (
                <li key={m.mission_id}>
                  <button
                    onClick={() => select(m.mission_id)}
                    className={clsx(
                      'w-full flex items-center justify-between gap-3 px-3 py-2 rounded-lg text-left transition-colors',
                      effective === m.mission_id
                        ? 'bg-cyber-cyan/15 border border-cyber-cyan/40'
                        : 'bg-cockpit-bg/50 border border-transparent hover:bg-cockpit-surface'
                    )}
                  >
                    <span className="min-w-0">
                      <span className="block text-xs text-white truncate">
                        {m.name || `Mission ${m.mission_id.slice(0, 8)}`}
                      </span>
                      <span className="block text-[10px] text-cockpit-muted font-mono">
                        {m.mission_id.slice(0, 8)}… · {m.frame_count} frames ·{' '}
                        {fmtDuration(m.duration_s)}
                      </span>
                    </span>
                    <span
                      className={clsx(
                        'shrink-0 px-2 py-0.5 rounded text-[10px] font-medium',
                        live
                          ? 'bg-nominal-green/20 text-nominal-green'
                          : 'bg-cockpit-surface text-cockpit-muted'
                      )}
                    >
                      {m.status}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Selected mission detail */}
      {effective && (
        <div className="mt-2 pt-4 border-t border-cockpit-border">
          <p className="text-xs text-cockpit-muted mb-3 flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {detail.data?.name || `Mission ${effective.slice(0, 8)}`}
          </p>

          {detail.error ? (
            <p className="text-xs text-alert-red">{detail.error}</p>
          ) : (
            <dl className="grid grid-cols-3 gap-2 text-xs mb-4">
              <div className="p-2 rounded bg-cockpit-bg/50">
                <dt className="text-cockpit-muted">Frames</dt>
                <dd className="data-display text-white">
                  {stats.frame_count ?? detail.data?.frame_count ?? 0}
                </dd>
              </div>
              <div className="p-2 rounded bg-cockpit-bg/50">
                <dt className="text-cockpit-muted">Min EHI</dt>
                <dd className="data-display text-hud-amber">
                  {stats.min_health !== undefined ? stats.min_health.toFixed(1) : '—'}
                </dd>
              </div>
              <div className="p-2 rounded bg-cockpit-bg/50">
                <dt className="text-cockpit-muted">Avg EHI</dt>
                <dd className="data-display text-white">
                  {stats.avg_health !== undefined ? stats.avg_health.toFixed(1) : '—'}
                </dd>
              </div>
              <div className="p-2 rounded bg-cockpit-bg/50">
                <dt className="text-cockpit-muted">Peak anomaly</dt>
                <dd className="data-display text-alert-red">
                  {stats.max_anomaly !== undefined ? stats.max_anomaly.toFixed(0) : '—'}
                </dd>
              </div>
              <div className="p-2 rounded bg-cockpit-bg/50">
                <dt className="text-cockpit-muted">Anomalies</dt>
                <dd className="data-display text-white">{stats.anomaly_count ?? 0}</dd>
              </div>
              <div className="p-2 rounded bg-cockpit-bg/50">
                <dt className="text-cockpit-muted">Min RUL</dt>
                <dd className="data-display text-white">
                  {stats.min_rul !== undefined && stats.min_rul !== null
                    ? `${stats.min_rul.toFixed(0)}m`
                    : '—'}
                </dd>
              </div>
            </dl>
          )}

          {stats.fault_distribution && Object.keys(stats.fault_distribution).length > 0 && (
            <div className="mb-4">
              <p className="text-xs text-cockpit-muted mb-1">Faults classified</p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(stats.fault_distribution).map(([cls, count]) => (
                  <span
                    key={cls}
                    className="px-2 py-0.5 rounded text-[10px] bg-alert-red/15 text-alert-red border border-alert-red/30"
                  >
                    {cls} × {count}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2">
            <button
              onClick={() => onReplay?.(effective)}
              className="flex items-center justify-center gap-1 py-2 rounded-lg bg-cyber-cyan/20 text-cyber-cyan border border-cyber-cyan/40 hover:bg-cyber-cyan/30 transition-colors text-xs font-medium"
            >
              <Play className="w-3.5 h-3.5" /> Replay
            </button>
            <button
              onClick={() => onOpenReport?.(effective)}
              className="flex items-center justify-center gap-1 py-2 rounded-lg bg-hud-amber/20 text-hud-amber border border-hud-amber/40 hover:bg-hud-amber/30 transition-colors text-xs font-medium"
            >
              <FileText className="w-3.5 h-3.5" /> Report
            </button>
            <a
              href={api.reports.downloadUrl(effective)}
              className="flex items-center justify-center gap-1 py-2 rounded-lg bg-cockpit-surface text-cockpit-muted hover:bg-cockpit-border transition-colors text-xs font-medium"
            >
              <Download className="w-3.5 h-3.5" /> JSON
            </a>
          </div>

          {detail.data?.started_at && (
            <p className="mt-3 text-[10px] text-cockpit-muted">
              Started {new Date(detail.data.started_at).toLocaleString()} ·{' '}
              {detail.data.ended_at
                ? `ended ${new Date(detail.data.ended_at).toLocaleTimeString()}`
                : 'in progress'}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
