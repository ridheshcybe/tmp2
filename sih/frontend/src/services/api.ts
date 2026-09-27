// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — API Client
// ══════════════════════════════════════════════════════════════════════════════
//
// Typed wrapper around the FastAPI backend. Uses relative `/api` paths so the
// Vite dev proxy (frontend/vite.config.ts) and the nginx production proxy
// (frontend/nginx.conf) route to the backend automatically.
//
// Every loader in this file is paired with a mock fallback in
// `src/services/mockData.ts` — see `src/hooks/useApiData.ts` for how pages
// gracefully degrade to mock data when the backend is unreachable.
// ══════════════════════════════════════════════════════════════════════════════

import type {
  EngineState,
  FaultInjectionRequest,
  FaultInjectionResponse,
  FaultTypeInfo,
  HealthTimelineResponse,
  MissionInfo,
  MissionReport,
  MissionSummary,
  ReplayFramesResponse,
  ReplayRequest,
  SimulationStatus,
  TelemetryFrameData,
} from '../types';

// ─── Configuration ─────────────────────────────────────────────────────────────

const ENV_API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '';

/** Base for REST calls. Relative by default (dev proxy / nginx). */
export const API_BASE = ENV_API_URL.replace(/\/+$/, '');

export const DEFAULT_ENGINE_ID = 'TAPAS-BH-201-001';

// ─── Errors ────────────────────────────────────────────────────────────────────

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: string;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

// ─── Low-level fetch ───────────────────────────────────────────────────────────

interface ApiFetchOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  timeoutMs?: number;
  /** Do not throw on non-2xx (caller handles 404/503 etc.) */
  swallowErrors?: boolean;
}

async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const {
    method = 'GET',
    body,
    timeoutMs = 8000,
    swallowErrors = false,
  } = options;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail: string | undefined;
      try {
        const payload = (await response.json()) as { detail?: string; error?: string };
        detail = payload.detail ?? payload.error;
      } catch {
        /* non-JSON error body */
      }
      if (swallowErrors) {
        throw new ApiError(response.status, `Request failed (${response.status})`, detail);
      }
      throw new ApiError(response.status, `Request failed (${response.status})`, detail);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, 'Request timed out');
    }
    throw new ApiError(0, `Network error: ${err instanceof Error ? err.message : 'unknown'}`);
  } finally {
    clearTimeout(timer);
  }
}

// ─── Health probe ──────────────────────────────────────────────────────────────

/** Lightweight backend reachability probe. Returns true when /health responds ok. */
export async function probeHealth(timeoutMs = 2500): Promise<boolean> {
  try {
    const health = await apiFetch<{ status: string }>('/health', { timeoutMs });
    return health?.status === 'ok';
  } catch {
    return false;
  }
}

// ─── Engine ────────────────────────────────────────────────────────────────────

export interface EngineHealthResponse {
  engine_id: string;
  health_index: number;
  category: string;
  trend: string;
  delta_5min: number;
  confidence: string;
  contributors: Array<Record<string, unknown>>;
  explanation: string[];
}

export interface EngineFaultsResponse {
  engine_id: string;
  fault_class: string;
  confidence: number;
  severity: number;
  criticality: number;
  action: string;
  anomaly_score: number;
  is_anomaly: boolean;
}

export interface EngineRulResponse {
  engine_id: string;
  rul_minutes: number | null;
  rul_lo: number | null;
  rul_hi: number | null;
  confidence: string;
  trend: string;
  rtb_alert: string;
  rtb_window_active: boolean;
  progress_pct: number;
}

export interface TelemetryHistoryResponse {
  engine_id: string;
  frames: TelemetryFrameData[];
  count: number;
}

const engine = {
  state: (engineId: string = DEFAULT_ENGINE_ID) =>
    apiFetch<EngineState>(`/api/engine/${engineId}/state`, { timeoutMs: 4000 }),
  telemetry: (engineId: string = DEFAULT_ENGINE_ID, limit = 200) =>
    apiFetch<TelemetryHistoryResponse>(`/api/engine/${engineId}/telemetry?limit=${limit}`, { timeoutMs: 4000 }),
  health: (engineId: string = DEFAULT_ENGINE_ID) =>
    apiFetch<EngineHealthResponse>(`/api/engine/${engineId}/health`, { timeoutMs: 4000 }),
  faults: (engineId: string = DEFAULT_ENGINE_ID) =>
    apiFetch<EngineFaultsResponse>(`/api/engine/${engineId}/faults`, { timeoutMs: 4000 }),
  rul: (engineId: string = DEFAULT_ENGINE_ID) =>
    apiFetch<EngineRulResponse>(`/api/engine/${engineId}/rul`, { timeoutMs: 4000 }),
};

// ─── Missions ──────────────────────────────────────────────────────────────────

export interface StartMissionRequest {
  engine_id?: string;
  duration_s?: number;
  ambient_offset_c?: number;
  name?: string | null;
}

const missions = {
  start: (body: StartMissionRequest) =>
    apiFetch<{ mission_id: string; engine_id: string; status: string; duration_s: number; started_at: string }>(
      '/api/missions/start',
      { method: 'POST', body, timeoutMs: 6000 }
    ),
  stop: (missionId: string) =>
    apiFetch<{ mission_id: string; status: string }>(`/api/missions/${missionId}/stop`, { method: 'POST' }),
  list: (limit = 50) =>
    apiFetch<{ missions: MissionInfo[]; count: number }>(`/api/missions?limit=${limit}`),
  get: (missionId: string) =>
    apiFetch<MissionInfo & { stats: Record<string, unknown> }>(`/api/missions/${missionId}`),
  summary: (missionId: string) =>
    apiFetch<MissionSummary>(`/api/missions/${missionId}/summary`),
};

// ─── Faults ────────────────────────────────────────────────────────────────────

const faults = {
  inject: (body: FaultInjectionRequest) =>
    apiFetch<FaultInjectionResponse>('/api/faults/inject', { method: 'POST', body }),
  clear: () => apiFetch<{ status: string; mission_id: string }>('/api/faults/clear', { method: 'POST' }),
  types: () => apiFetch<{ fault_types: FaultTypeInfo[] }>('/api/faults/types'),
};

// ─── Replay ────────────────────────────────────────────────────────────────────

const replay = {
  start: (body: ReplayRequest) =>
    apiFetch<{ mission_id: string; frame_count: number; speed: number; status: string; message: string }>(
      '/api/replay/start',
      { method: 'POST', body }
    ),
  frames: (missionId: string, limit = 5000) =>
    apiFetch<ReplayFramesResponse>(`/api/replay/frames/${missionId}?limit=${limit}`, { timeoutMs: 12000 }),
  status: () =>
    apiFetch<{ is_running: boolean; mission_id: string | null; speed: number }>('/api/replay/status'),
};

// ─── Reports ───────────────────────────────────────────────────────────────────

const reports = {
  get: (missionId: string) =>
    apiFetch<MissionReport>(`/api/reports/${missionId}`, { timeoutMs: 15000 }),
  healthTimeline: (missionId: string) =>
    apiFetch<HealthTimelineResponse>(`/api/reports/${missionId}/health-timeline`, { timeoutMs: 8000 }),
  downloadUrl: (missionId: string) => `${API_BASE}/api/reports/${missionId}/download`,
};

// ─── Simulation ────────────────────────────────────────────────────────────────

const simulation = {
  status: () => apiFetch<SimulationStatus>('/api/simulation/status', { timeoutMs: 3000 }),
  throttle: (throttle: number) =>
    apiFetch<{ throttle: number; status: string }>('/api/simulation/throttle', {
      method: 'POST',
      body: { throttle },
    }),
  altitude: (altitudeFt: number) =>
    apiFetch<{ altitude_ft: number; status: string }>('/api/simulation/altitude', {
      method: 'POST',
      body: { altitude_ft: altitudeFt },
    }),
};

// ─── Public surface ────────────────────────────────────────────────────────────

export const api = {
  probeHealth,
  engine,
  missions,
  faults,
  replay,
  reports,
  simulation,
};

export type Api = typeof api;
export default api;