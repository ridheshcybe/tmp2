// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — Shared Domain Types
// ══════════════════════════════════════════════════════════════════════════════
// Mirror of the backend Pydantic schemas (backend/models.py).
// The frontend consumes these shapes from three interchangeable sources:
//   - live WebSocket frames (backend broadcasts EngineState)
//   - REST API responses (engine / missions / reports / replay)
//   - deterministic local mock generators (src/services/mockData.ts)
// ══════════════════════════════════════════════════════════════════════════════

// ─── Enums ─────────────────────────────────────────────────────────────────────

export type MissionPhase =
  | 'STARTUP'
  | 'TAKEOFF'
  | 'CLIMB'
  | 'CRUISE'
  | 'ENDURANCE'
  | 'DESCENT'
  | 'LANDING';

export type HealthCategory =
  | 'NORMAL'
  | 'WATCH'
  | 'WARNING'
  | 'CRITICAL'
  | 'EMERGENCY';

export type FaultType =
  | 'HEALTHY'
  | 'INJECTOR_DEGRADATION'
  | 'MISFIRE'
  | 'LUBRICATION_FAILURE'
  | 'OVERHEATING'
  | 'SENSOR_DRIFT'
  | 'SENSOR_DROPOUT'
  | 'ABNORMAL_VIBRATION'
  | 'ALTERNATOR_DEGRADATION';

export type RtbAlert = 'NONE' | 'RTB_ADVISORY' | 'RTB_CRITICAL';

export type MissionStatus = 'IDLE' | 'RUNNING' | 'PAUSED' | 'COMPLETED' | 'FAULT_INJECTED';

export type DataSource = 'mock' | 'live';

// ─── Telemetry ─────────────────────────────────────────────────────────────────

/** One raw tick of engine telemetry — the fundamental data unit. */
export interface TelemetryFrameData {
  frame_id: number;
  timestamp: string;
  engine_id: string;
  mission_id?: string | null;
  /** Mission phase (STARTUP → TAKEOFF → CLIMB → CRUISE → ENDURANCE → …) */
  phase: MissionPhase;
  /** Throttle 0..1 */
  throttle: number;
  altitude_ft: number;
  ambient_temp_c: number;
  /** Engine speed (RPM) */
  rpm: number;
  /** Manifold absolute pressure (kPa) */
  map_kpa?: number;
  fuel_flow_lph: number;
  /** Cylinder head temperatures, per cylinder (°C) */
  cht: number[];
  /** Exhaust gas temperatures, per cylinder (°C) */
  egt: number[];
  oil_pressure_kpa: number;
  oil_temp_c: number;
  /** Vibration RMS (g) */
  vibration_rms: number;
  /** Alias used by some ML rows */
  vibration_rms_g?: number;
  battery_voltage: number;
  alternator_current: number;
  /** Injection timing (deg BTDC) */
  injection_timing: number;
  /** Ground-truth injected fault (demo) */
  injected_fault?: string | null;
  fault_severity?: number;
  sim_time_s?: number;
}

/** Observed vs physics-expected residual for one sensor channel. */
export interface SensorResidual {
  channel: string;
  observed: number;
  expected: number;
  residual: number;
  z_score: number;
  unit: string;
}

/** A single engine alert (from the digital twin service). */
export interface EngineAlert {
  level: 'NONE' | 'WATCH' | 'ADVISORY' | 'CRITICAL' | string;
  message: string;
  type: 'HEALTH' | 'FAULT' | 'RTB' | 'SENSOR' | string;
}

/**
 * Complete digital twin state — the payload of WS TELEMETRY messages
 * and GET /api/engine/{id}/state. This is the shape every page consumes.
 */
export interface EngineState {
  engine_id: string;
  mission_id?: string | null;
  timestamp: string;
  frame_id: number;

  /** Observed telemetry */
  observed: TelemetryFrameData;

  /** Physics-expected values (keyed by channel, from ml/physics_baseline) */
  expected: Record<string, number>;
  residuals: SensorResidual[];

  // ── Health ───────────────────────────────────────────────────────────
  health_index: number;
  health_category: HealthCategory;
  health_trend: 'stable' | 'declining' | 'improving' | string;
  health_delta_5min: number;
  health_confidence: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  health_explanation: string[];
  health_contributors: HealthContributor[];

  // ── Anomaly ──────────────────────────────────────────────────────────
  anomaly_score: number;
  is_anomaly: boolean;
  anomaly_contributors?: string[];

  // ── Fault ────────────────────────────────────────────────────────────
  fault_class: FaultType | string;
  fault_confidence: number;
  fault_severity: number;
  fault_criticality: number;
  fault_action: string;

  // ── RUL / RTB ────────────────────────────────────────────────────────
  rul_minutes?: number | null;
  rul_lo?: number | null;
  rul_hi?: number | null;
  rul_confidence: string;
  rul_trend: string;
  rtb_alert: RtbAlert;
  rtb_window_active: boolean;
  progress_pct: number;

  // ── Sensor health ────────────────────────────────────────────────────
  sensor_status: Record<string, boolean>;
  isolated_sensors: string[];

  alerts: EngineAlert[];
  processing_time_ms?: number;
}

/** One named contributor to the health-index score, with its penalty. */
export interface HealthContributor {
  label?: string;
  channel?: string;
  penalty: number;
  weight?: number;
  value?: string;
  severity?: string;
  [key: string]: unknown;
}

// ─── Missions ─────────────────────────────────────────────────────────────────

export interface MissionInfo {
  mission_id: string;
  engine_id: string;
  name?: string | null;
  status: MissionStatus | string;
  started_at: string;
  ended_at?: string | null;
  duration_s: number;
  frame_count: number;
  max_anomaly_score: number;
  min_health_index: number;
  faults_observed: string[];
}

export interface MissionSummary {
  mission: MissionInfo;
  health_stats: Record<string, unknown>;
  anomaly_stats: Record<string, unknown>;
  fault_stats: Record<string, unknown>;
  rul_stats: Record<string, unknown>;
  timeline: Array<Record<string, unknown>>;
  recommendations: string[];
}

// ─── Faults ───────────────────────────────────────────────────────────────────

export interface FaultInjectionRequest {
  fault_type: FaultType;
  severity?: number;
  target_sensor?: string | null;
}

export interface FaultInjectionResponse {
  fault_type: string;
  severity: number;
  injected_at: string;
  mission_id: string;
}

export interface FaultTypeInfo {
  fault_type: string;
  label?: string;
  description?: string;
  severity?: number;
  criticality?: number;
  [key: string]: unknown;
}

// ─── Replay ───────────────────────────────────────────────────────────────────

export interface ReplayRequest {
  mission_id: string;
  speed?: number;
  start_s?: number | null;
  end_s?: number | null;
}

// ─── Reports & Maintenance ────────────────────────────────────────────────────

export interface MaintenanceAdvisory {
  id?: string;
  severity: 'INFO' | 'WARNING' | 'CRITICAL' | string;
  subsystem: string;
  title: string;
  action: string;
  due_hours?: number | null;
  priority?: number;
  evidence?: string[];
  [key: string]: unknown;
}

export interface MissionReport {
  mission: MissionInfo;
  executive_summary: string;
  health_timeline: Array<Record<string, unknown>>;
  anomaly_events: Array<Record<string, unknown>>;
  fault_predictions: Array<Record<string, unknown>>;
  rul_timeline: Array<Record<string, unknown>>;
  maintenance_advisories: MaintenanceAdvisory[];
  sensor_summary: Record<string, unknown>;
  environmental_summary: Record<string, unknown>;
  generated_at: string;
}

// ─── Simulation ───────────────────────────────────────────────────────────────

export interface SimulationStatus {
  is_running: boolean;
  mission_id?: string | null;
  frame_id: number;
  sim_time_s: number;
  hz: number;
  active_faults: string[];
}

// ─── Replay frames (HTTP fallback) ────────────────────────────────────────────

export interface ReplayFramesResponse {
  mission_id: string;
  count: number;
  data: TelemetryFrameData[];
}

// ─── Health timeline (charting) ───────────────────────────────────────────────

export interface HealthTimelineResponse {
  mission_id: string;
  count: number;
  data: Array<Record<string, unknown>>;
}