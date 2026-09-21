// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — Mission Report
// ══════════════════════════════════════════════════════════════════════════════
//
// The post-flight artefact: the backend writes the executive summary, the
// anomaly events, the fault predictions, the RUL timeline and the maintenance
// advisories; this panel renders them and offers the JSON download.
//
//   GET /api/reports/{mission_id}
//   GET /api/reports/{mission_id}/health-timeline
//   GET /api/reports/{mission_id}/download
// ══════════════════════════════════════════════════════════════════════════════

import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { Download, FileText, RefreshCw, Wrench } from 'lucide-react';
import {
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
} from 'chart.js';
import { Line } from 'react-chartjs-2';

import api from '../../services/api';
import { describeApiError, useApiResource } from '../../hooks/useApiResource';
import type { MaintenanceAdvisory } from '../../types';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip, Legend);

interface MissionReportPanelProps {
  className?: string;
  /** Mission to report on; defaults to the newest mission with stored frames. */
  missionId?: string | null;
  onMissionChange?: (missionId: string) => void;
}

export default function MissionReportPanel({
  className,
  missionId,
  onMissionChange,
}: MissionReportPanelProps) {
  const [selected, setSelected] = useState<string | null>(missionId ?? null);

  useEffect(() => {
    if (missionId) setSelected(missionId);
  }, [missionId]);

  const missions = useApiResource(() => api.missions.list(50), { intervalMs: 30_000 });
  /*  A mission can be reported on once it has stored telemetry: either it is
      finished, or the backend has already counted its frames.  */
  const candidates = useMemo(
    () =>
      (missions.data?.missions ?? []).filter(
        (m) => (m.frame_count ?? 0) > 0 || m.status !== 'RUNNING'
      ),
    [missions.data]
  );

  // Default to the newest mission that actually has data.
  useEffect(() => {
    if (!selected && candidates.length > 0) setSelected(candidates[0].mission_id);
  }, [candidates, selected]);

  const report = useApiResource(() => api.reports.get(selected as string), {
    enabled: Boolean(selected),
    deps: [selected],
  });

  const timeline = useApiResource(() => api.reports.healthTimeline(selected as string), {
    enabled: Boolean(selected),
    deps: [selected],
  });

  const noReportYet =
    report.error !== null &&
    (/404/.test(report.error) || /not found/i.test(report.error));

  const advisories = (report.data?.maintenance_advisories ?? []) as MaintenanceAdvisory[];
  const points = (timeline.data?.data ?? []) as Array<Record<string, unknown>>;

  const chart = useMemo(() => {
    const labels = points.map((p) => Number(p.sim_time_s ?? 0).toFixed(0));
    return {
      labels,
      datasets: [
        {
          label: 'EHI',
          data: points.map((p) => Number(p.health_index ?? 0)),
          borderColor: '#06b6d4',
          backgroundColor: 'rgba(6, 182, 212, 0.15)',
          fill: true,
          tension: 0.25,
          pointRadius: 0,
          yAxisID: 'y',
        },
        {
          label: 'Anomaly',
          data: points.map((p) => Number(p.anomaly_score ?? 0)),
          borderColor: '#ef4444',
          borderDash: [4, 4],
          fill: false,
          tension: 0.25,
          pointRadius: 0,
          yAxisID: 'y',
        },
      ],
    };
  }, [points]);

  const pick = (id: string) => {
    setSelected(id);
    onMissionChange?.(id);
  };

  return (
    <div className={clsx('hud-panel flex flex-col', className)}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-hud-amber" />
          <h3 className="text-sm font-medium text-cockpit-muted">Mission Report</h3>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              void report.reload();
              void timeline.reload();
            }}
            className="p-1.5 rounded bg-cockpit-surface hover:bg-cockpit-border transition-colors"
            title="Regenerate"
          >
            <RefreshCw
              className={clsx('w-3.5 h-3.5 text-cockpit-muted', report.loading && 'animate-spin')}
            />
          </button>
          {selected && !noReportYet && (
            <a
              href={api.reports.downloadUrl(selected)}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-cyber-cyan/20 text-cyber-cyan hover:bg-cyber-cyan/30 transition-colors"
            >
              <Download className="w-3 h-3" /> JSON
            </a>
          )}
        </div>
      </div>

      <select
        value={selected ?? ''}
        onChange={(e) => pick(e.target.value)}
        className="w-full mb-4 px-2 py-2 rounded-lg bg-cockpit-bg border border-cockpit-border text-xs text-white focus:border-hud-amber outline-none"
      >
        {candidates.length === 0 && <option value="">No missions with stored telemetry</option>}
        {candidates.map((m) => (
          <option key={m.mission_id} value={m.mission_id}>
            {(m.name || `Mission ${m.mission_id.slice(0, 8)}`)} · {m.frame_count} frames
          </option>
        ))}
      </select>

      {noReportYet ? (
        <p className="text-xs text-cockpit-muted py-6 text-center">
          No report for this mission yet — a mission needs stored telemetry
          before the backend can summarise it.
        </p>
      ) : report.error ? (
        <p className="text-xs text-alert-red">{report.error}</p>
      ) : !report.data ? (
        <p className="text-xs text-cockpit-muted py-6 text-center">Loading report…</p>
      ) : (
        <div className="space-y-4">
          {/* Executive summary */}
          <div className="p-3 rounded-lg bg-cockpit-bg/60 border border-cockpit-border">
            <pre className="text-[11px] leading-relaxed text-white whitespace-pre-wrap font-mono">
              {report.data.executive_summary}
            </pre>
            <p className="mt-2 text-[10px] text-cockpit-muted">
              Generated {new Date(report.data.generated_at).toLocaleString()}
            </p>
          </div>

          {/* Health timeline */}
          {points.length > 0 && (
            <div>
              <p className="text-xs text-cockpit-muted mb-2">
                Health & anomaly timeline ({points.length} snapshots)
              </p>
              <div className="h-48">
                <Line
                  data={chart}
                  options={{
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: { legend: { labels: { color: '#9ca3af', boxWidth: 10 } } },
                    scales: {
                      x: {
                        ticks: { color: '#6b7280', maxTicksLimit: 8 },
                        grid: { color: 'rgba(31,41,55,0.6)' },
                        title: { display: true, text: 'sim time (s)', color: '#6b7280' },
                      },
                      y: {
                        min: 0,
                        max: 100,
                        ticks: { color: '#6b7280' },
                        grid: { color: 'rgba(31,41,55,0.6)' },
                      },
                    },
                  }}
                />
              </div>
            </div>
          )}

          {/* Event counts */}
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="p-2 rounded bg-cockpit-bg/50">
              <p className="text-cockpit-muted">Anomaly events</p>
              <p className="data-display text-alert-red">
                {report.data.anomaly_events?.length ?? 0}
              </p>
            </div>
            <div className="p-2 rounded bg-cockpit-bg/50">
              <p className="text-cockpit-muted">Fault predictions</p>
              <p className="data-display text-hud-amber">
                {report.data.fault_predictions?.length ?? 0}
              </p>
            </div>
            <div className="p-2 rounded bg-cockpit-bg/50">
              <p className="text-cockpit-muted">RUL points</p>
              <p className="data-display text-white">
                {report.data.rul_timeline?.length ?? 0}
              </p>
            </div>
          </div>

          {/* Maintenance advisories */}
          <div>
            <p className="text-xs text-cockpit-muted mb-2 flex items-center gap-1">
              <Wrench className="w-3 h-3" /> Maintenance advisories
            </p>
            {advisories.length === 0 ? (
              <p className="text-xs text-nominal-green">
                No maintenance action raised for this mission.
              </p>
            ) : (
              <ul className="space-y-2">
                {advisories.map((a, i) => (
                  <li
                    key={a.id ?? i}
                    className={clsx(
                      'p-2 rounded-lg border text-xs',
                      a.severity === 'CRITICAL'
                        ? 'bg-alert-red/10 border-alert-red/40'
                        : a.severity === 'WARNING'
                          ? 'bg-hud-amber/10 border-hud-amber/40'
                          : 'bg-cockpit-bg/50 border-cockpit-border'
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-white font-medium">{a.title ?? a.subsystem}</span>
                      <span
                        className={clsx(
                          'px-1.5 py-0.5 rounded text-[10px]',
                          a.severity === 'CRITICAL'
                            ? 'bg-alert-red/20 text-alert-red'
                            : a.severity === 'WARNING'
                              ? 'bg-hud-amber/20 text-hud-amber'
                              : 'bg-cockpit-surface text-cockpit-muted'
                        )}
                      >
                        {a.severity}
                      </span>
                    </div>
                    <p className="mt-1 text-cockpit-muted">{a.action}</p>
                    {a.evidence && a.evidence.length > 0 && (
                      <ul className="mt-1 list-disc list-inside text-[10px] text-cockpit-muted">
                        {a.evidence.slice(0, 3).map((e, j) => (
                          <li key={j}>{e}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {timeline.error && !noReportYet && (
        <p className="mt-3 text-[10px] text-cockpit-muted">
          Health timeline unavailable — {describeApiError(timeline.error)}
        </p>
      )}
    </div>
  );
}
