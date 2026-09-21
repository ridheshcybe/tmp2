// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — WebSocket wire format
// ══════════════════════════════════════════════════════════════════════════════
//
// Two backends can feed this cockpit and they do not speak the same shape:
//
//   FastAPI backend (backend/main.py, :8081)
//       { "type": "TELEMETRY", "payload": EngineState }
//       with the sensors inside payload.observed, and health/anomaly/RUL as
//       siblings of `observed` on the same payload.
//
//   Node gateway (backend/src/server.ts, :8080) and the replay/mock sources
//       a flat frame with rpm/cht/egt at the top level.
//
// `parseTelemetryMessage` normalises both into the flat frame the cockpit
// widgets consume, and returns null for anything that is not a frame, so the
// context can ignore WELCOME / STATS / FAULT_INJECTED chatter.
// ══════════════════════════════════════════════════════════════════════════════

import { toLegacyFrame, type LegacyTelemetryFrame } from './adapters';
import type { EngineState } from '../types';

/** Message types that carry a frame; everything else on this socket is control chatter. */
const FRAME_TYPE = 'TELEMETRY';

/**
 * The raw twin state, when the message carries one.
 *
 * `parseTelemetryMessage` flattens EngineState into the frame the cockpit
 * widgets consume, which loses the parts only the twin has: the physics
 * expected values, the per-channel residuals and the warm-up flag. Panels that
 * explain *why* a score moved need those, so they read the state directly.
 */
export function parseTwinState(raw: unknown): EngineState | null {

  if (!raw) return null;

  let message: Record<string, unknown>;

  try {
    message = typeof raw === 'string'
      ? (JSON.parse(raw) as Record<string, unknown>)
      : (raw as Record<string, unknown>);
  } catch {
    return null;
  }

  if (!message || typeof message !== 'object') return null;
  if (message.type !== FRAME_TYPE) return null;

  const payload = message.payload as Record<string, unknown> | undefined;
  if (!payload || typeof payload !== 'object') return null;

  return payload.observed && typeof payload.observed === 'object'
    ? (payload as unknown as EngineState)
    : null;
}

export function parseTelemetryMessage(raw: unknown): LegacyTelemetryFrame | null {

  if (!raw) return null;

  let message: Record<string, unknown>;

  try {
    message = typeof raw === 'string'
      ? (JSON.parse(raw) as Record<string, unknown>)
      : (raw as Record<string, unknown>);
  } catch {
    return null;
  }

  if (!message || typeof message !== 'object') return null;

  /*  ── Envelope: { type, payload } ────────────────────────────────────── */

  if (typeof message.type === 'string' && message.payload && typeof message.payload === 'object') {

    if (message.type !== FRAME_TYPE) return null;

    const payload = message.payload as Record<string, unknown>;

    /*  The real shape: sensors under `observed`, twin state around it.  */
    if (payload.observed && typeof payload.observed === 'object') {
      return toLegacyFrame(payload as unknown as EngineState);
    }

    /*  Some builds put the flat frame straight into the payload.  */
    return typeof payload.rpm === 'number'
      ? (payload as unknown as LegacyTelemetryFrame)
      : null;
  }

  /*  ── Flat frame: gateway, replay playback, mock generators ──────────── */

  if (typeof message.rpm === 'number' || typeof message.frame_id === 'number') {
    return message as unknown as LegacyTelemetryFrame;
  }

  return null;
}
