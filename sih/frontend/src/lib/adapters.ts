// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — Adapters & Shared Display Helpers
// ══════════════════════════════════════════════════════════════════════════════
//
// The backend broadcasts the rich `EngineState` shape over WebSocket. The
// cockpit widgets built earlier (MasterHealthGauge, TelemetryStripCharts,
// ReturnToBaseHUD, SensorHealthStatus) consume a flatter legacy frame shape.
// `toLegacyFrame()` bridges the two so both generations of components can
// coexist on the same live stream.
// ══════════════════════════════════════════════════════════════════════════════

import type { EngineState, HealthCategory, FaultType } from '../types';

// ─── Legacy flat frame (consumed by Phase-5 cockpit widgets) ─────────────────

export interface LegacyTelemetryFrame {
  timestamp: string;
  frame_id: number;
  altitude_ft: number;
  throttle: number;
  rpm: number;
  map_kpa: number;
  fuel_flow_lph: number;
  cht: number[];
  egt: number[];
  oil_pressure_kpa: number;
  oil_temp_c: number;
  vibration_rms: number;
  ambient_temp_c: number;
  injected_fault: string | null;
  health?: {
    ehi: number;
    combustion_efficiency: number;
    thermal_balance_spread: number;
    status: string;
  };
  anomaly?: {
    score: number;
    is_detected: boolean;
    top_contributing_sensors: string[];
  };
  prognostics?: {
    predicted_rul_min: number;
    rtb_alert_level: 'NONE' | 'RTB_ADVISORY' | 'RTB_CRITICAL';
    rtb_window_active: boolean;
  };
  sensor_status?: {
    isolated_sensors: string[];
    active_sensors: Record<string, boolean>;
  };
}

/** Map the backend EngineState onto the legacy flat telemetry frame shape. */
export function toLegacyFrame(state: EngineState): LegacyTelemetryFrame {
  const obs = state.observed ?? ({} as EngineState['observed']);

  return {
    timestamp: state.timestamp ?? obs.timestamp ?? new Date().toISOString(),
    frame_id: state.frame_id ?? obs.frame_id ?? 0,
    altitude_ft: obs.altitude_ft ?? 0,
    throttle: obs.throttle ?? 0,
    rpm: obs.rpm ?? 0,
    map_kpa: obs.map_kpa ?? 0,
    fuel_flow_lph: obs.fuel_flow_lph ?? 0,
    cht: obs.cht ?? [0, 0, 0, 0],
    egt: obs.egt ?? [0, 0, 0, 0],
    oil_pressure_kpa: obs.oil_pressure_kpa ?? 0,
    oil_temp_c: obs.oil_temp_c ?? 0,
    vibration_rms: obs.vibration_rms ?? obs.vibration_rms_g ?? 0,
    ambient_temp_c: obs.ambient_temp_c ?? 0,
    injected_fault: obs.injected_fault ?? null,
    health: {
      ehi: state.health_index ?? 100,
      combustion_efficiency: combustionEfficiency(state),
      thermal_balance_spread: thermalSpread(state),
      status: state.health_category ?? 'NORMAL',
    },
    anomaly: {
      score: state.anomaly_score ?? 0,
      is_detected: state.is_anomaly ?? false,
      top_contributing_sensors: (state.anomaly_contributors as string[] | undefined) ?? [],
    },
    prognostics: {
      predicted_rul_min: state.rul_minutes ?? 180,
      rtb_alert_level: state.rtb_alert ?? 'NONE',
      rtb_window_active: state.rtb_window_active ?? false,
    },
    sensor_status: {
      isolated_sensors: state.isolated_sensors ?? [],
      active_sensors: state.sensor_status ?? {},
    },
  };
}

/** Best-effort combustion efficiency estimate from contributors (0–100). */
export function combustionEfficiency(state: EngineState): number {
  const eff = state.health_contributors?.find(
    (c) => typeof c.label === 'string' && /combustion/i.test(c.label)
  );
  if (eff && typeof eff.value === 'number') return eff.value;
  // Fallback: degrade with fault severity / health
  return Math.max(40, 97 - (100 - state.health_index) * 0.6);
}

/** Thermal balance spread across cylinders (°C) — EGT max−min if available. */
export function thermalSpread(state: EngineState): number {
  const egt = state.observed?.egt;
  if (egt && egt.length > 0) {
    return Math.max(0, Math.max(...egt) - Math.min(...egt));
  }
  const spread = state.health_contributors?.find(
    (c) => typeof c.label === 'string' && /spread/i.test(c.label)
  );
  return typeof spread?.value === 'number' ? spread.value : 0;
}

// ─── Display helpers ──────────────────────────────────────────────────────────

export const HEALTH_CATEGORY_STYLES: Record<
  HealthCategory | string,
  { text: string; badge: string; bar: string }
> = {
  NORMAL: { text: 'text-nominal-green', badge: 'bg-nominal-green/15 border-nominal-green/40', bar: 'bg-nominal-green' },
  WATCH: { text: 'text-hud-amber', badge: 'bg-hud-amber/15 border-hud-amber/40', bar: 'bg-hud-amber' },
  WARNING: { text: 'text-hud-amber', badge: 'bg-hud-amber/15 border-hud-amber/40', bar: 'bg-hud-amber' },
  CRITICAL: { text: 'text-alert-red', badge: 'bg-alert-red/15 border-alert-red/40', bar: 'bg-alert-red' },
  EMERGENCY: { text: 'text-alert-red', badge: 'bg-alert-red/25 border-alert-red/60', bar: 'bg-alert-red animate-pulse' },
};

export const FAULT_LABELS: Record<FaultType | string, string> = {
  HEALTHY: 'Healthy',
  INJECTOR_DEGRADATION: 'Injector Degradation',
  MISFIRE: 'Misfire',
  LUBRICATION_FAILURE: 'Lubrication Failure',
  OVERHEATING: 'Overheating',
  SENSOR_DRIFT: 'Sensor Drift',
  SENSOR_DROPOUT: 'Sensor Dropout',
  ABNORMAL_VIBRATION: 'Abnormal Vibration',
  ALTERNATOR_DEGRADATION: 'Alternator Degradation',
};

export const MISSION_PHASE_LABELS: Record<string, string> = {
  STARTUP: 'Startup',
  TAKEOFF: 'Takeoff',
  CLIMB: 'Climb',
  CRUISE: 'Cruise',
  ENDURANCE: 'Endurance',
  DESCENT: 'Descent',
  LANDING: 'Landing',
};

export function faultLabel(fault: string | null | undefined): string {
  if (!fault || fault === 'HEALTHY') return 'Healthy';
  return FAULT_LABELS[fault] ?? fault.replace(/_/g, ' ');
}

export function phaseLabel(phase: string | null | undefined): string {
  if (!phase) return '—';
  return MISSION_PHASE_LABELS[phase] ?? phase;
}

/** mm:ss from seconds */
export function fmtClock(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m.toString().padStart(2, '0')}:${r.toString().padStart(2, '0')}`;
}

/** Human duration like "2h 05m" or "3m 12s" */
export function fmtDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, '0')}m`;
}