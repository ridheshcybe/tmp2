#!/usr/bin/env python3
"""
AI Inference Service
====================
Master inference server that:

1. **Consumes** the 10 Hz WebSocket telemetry stream from
   ``simulator/telemetry_streamer.py``.
2. **Processes** each frame through the full AI pipeline:
   SensorValidator → CrossModalFusionNet → AnomalyVAE → RUL Predictor.
3. **Broadcasts** enriched JSON packets on port 8766 for downstream
   Phase 4 Node.js ingestion.

Output Payload
--------------
.. code-block:: json

    {
      "timestamp": "ISO8601",
      "frame_id": int,
      "telemetry": { ... },
      "health": { "ehi": float, "combustion_efficiency": float, "status": str },
      "anomaly": { "score": float, "is_detected": bool, "top_contributing_sensors": [...] },
      "prognostics": { "predicted_rul_min": float, "rtb_alert_level": str, "rtb_window_active": bool },
      "sensor_status": { "isolated_sensors": [...] }
    }

Usage
-----
    # Terminal 1: start the simulation streamer
    python -m simulator.telemetry_streamer

    # Terminal 2: start the AI service
    python -m fusion_ml.ai_service

    # Terminal 3: connect to enriched output
    python -m fusion_ml.ai_service --port 8766
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set

import numpy as np
import torch

try:
    import websockets
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve, ServerConnection
except ImportError:
    print("  Install websockets:  pip install websockets>=12.0", file=sys.stderr)
    sys.exit(1)

from fusion_ml.fusion_pipeline import EngineFusionPipeline
from fusion_ml.anomaly_vae import AnomalyVAE
from fusion_ml.rul_predictor import RULPredictor, SEQUENCE_LENGTH
from fusion_ml.sensor_validator import ALL_CHANNELS, NUM_CHANNELS


# ══════════════════════════════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════════════════════════════

STREAMER_URL = "ws://localhost:8765"
BROADCAST_PORT = 8766
SEQUENCE_BUFFER_LEN = 300  # 30 s at 10 Hz
RTB_WARNING_MIN = 30.0
RTB_CRITICAL_MIN = 10.0

LOG_FMT = "%(asctime)s  %(levelname)-7s  %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FMT)
log = logging.getLogger("ai_service")


# ══════════════════════════════════════════════════════════════════
#  Sequence Buffer
# ══════════════════════════════════════════════════════════════════

class SequenceBuffer:
    """
    Rolling buffer of fused vectors for temporal models.

    Maintains a deque of length ``maxlen`` (default 300 = 30 s at 10 Hz).
    """

    def __init__(self, maxlen: int = SEQUENCE_BUFFER_LEN) -> None:
        self.buffer: Deque[np.ndarray] = deque(maxlen=maxlen)
        self.maxlen = maxlen

    def append(self, fused_vector: np.ndarray) -> None:
        self.buffer.append(fused_vector.copy())

    def get_sequence(self) -> Optional[np.ndarray]:
        """
        Return the current buffer as a (seq_len, 32) numpy array,
        or None if buffer is not yet full.
        """
        if len(self.buffer) < self.maxlen:
            return None
        return np.stack(list(self.buffer))

    @property
    def length(self) -> int:
        return len(self.buffer)

    def clear(self) -> None:
        self.buffer.clear()


# ══════════════════════════════════════════════════════════════════
#  AI Inference Service
# ══════════════════════════════════════════════════════════════════

class AIService:
    """
    Master AI inference server.

    Connects to the telemetry streamer, processes each frame through
    the full pipeline, and broadcasts enriched packets.

    Parameters
    ----------
    streamer_url : str
        WebSocket URL of the telemetry streamer.
    broadcast_port : int
        Port for broadcasting enriched packets.
    """

    def __init__(
        self,
        streamer_url: str = STREAMER_URL,
        broadcast_port: int = BROADCAST_PORT,
    ) -> None:
        self.streamer_url = streamer_url
        self.broadcast_port = broadcast_port

        # ── Pipeline components ──
        log.info("Loading AI pipeline components…")
        self.pipeline = EngineFusionPipeline()

        # Load VAE if available
        vae_path = Path(__file__).resolve().parent / "models" / "vae_nominal.pt"
        if vae_path.exists():
            self.vae = AnomalyVAE.load(vae_path)
            log.info("  VAE loaded from %s", vae_path)
        else:
            self.vae = AnomalyVAE()
            log.warning("  VAE not found at %s — using untrained model", vae_path)

        # Load RUL predictor if available
        try:
            self.rul_predictor = RULPredictor.load()
            log.info("  RUL predictor loaded")
        except Exception:
            self.rul_predictor = None
            log.warning("  RUL predictor not found — RUL disabled")

        # ── Sequence buffer ──
        self.seq_buffer = SequenceBuffer(maxlen=SEQUENCE_BUFFER_LEN)

        # ── Broadcast clients ──
        self._broadcast_clients: Set[ServerConnection] = set()

        # ── Frame counter ──
        self._frame_id = 0

        # ── Anomaly top-contributor tracking ──
        self._prev_fused: Optional[np.ndarray] = None

    # ── Frame processing ───────────────────────────────────────

    def process_frame(self, raw_frame: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single telemetry frame through the full AI pipeline.

        Returns the enriched output payload.
        """
        self._frame_id += 1

        # ── Step 1: Fusion pipeline (Validator → Fusion → Health) ──
        enriched = self.pipeline.process_frame(raw_frame)
        fused_vec = np.array(enriched["fused_vector"], dtype=np.float32)

        # ── Step 2: VAE anomaly detection ──
        fused_tensor = torch.from_numpy(fused_vec).unsqueeze(0)
        anomaly_result = self.vae.predict_anomaly(fused_tensor)

        # ── Step 3: Top contributing sensors ──
        top_sensors = self._identify_top_contributors(fused_vec, raw_frame)

        # ── Step 4: Sequence buffer + RUL ──
        self.seq_buffer.append(fused_vec)
        prognostics = self._compute_prognostics()

        # ── Step 5: Health status override ──
        health_status = enriched.get("health_status", "NORMAL")
        if health_status == "NORMAL" and anomaly_result["is_anomaly"]:
            health_status = "WARNING"
        if prognostics["rtb_alert_level"] == "RTB_CRITICAL":
            health_status = "CRITICAL"

        # ── Step 6: Assemble payload ──
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "frame_id": self._frame_id,
            "telemetry": {
                "rpm": raw_frame.get("rpm"),
                "map_kpa": raw_frame.get("map_kpa"),
                "fuel_flow_lph": raw_frame.get("fuel_flow_lph"),
                "cht_c": raw_frame.get("cht_c", raw_frame.get("cht")),
                "egt_c": raw_frame.get("egt_c", raw_frame.get("egt")),
                "oil_pressure_kpa": raw_frame.get("oil_pressure_kpa"),
                "oil_temp_c": raw_frame.get("oil_temp_c"),
                "vibration_rms_g": raw_frame.get("vibration_rms_g"),
            },
            "health": {
                "ehi": enriched.get("engine_health_index", 0.0),
                "combustion_efficiency": enriched.get("combustion_efficiency", 0.0),
                "status": health_status,
            },
            "anomaly": {
                "score": anomaly_result["anomaly_score"],
                "is_detected": anomaly_result["is_anomaly"],
                "top_contributing_sensors": top_sensors,
            },
            "prognostics": prognostics,
            "sensor_status": {
                "isolated_sensors": [
                    f["channel"] for f in enriched.get("sensor_isolation_flags", [])
                ],
            },
        }

        self._prev_fused = fused_vec.copy()
        return payload

    # ── Prognostics ────────────────────────────────────────────

    def _compute_prognostics(self) -> Dict[str, Any]:
        """Compute RUL and RTB alerts from sequence buffer."""
        result: Dict[str, Any] = {
            "predicted_rul_min": None,
            "rtb_alert_level": "NONE",
            "rtb_window_active": False,
        }

        seq = self.seq_buffer.get_sequence()
        if seq is None or self.rul_predictor is None:
            return result

        try:
            rul_result = self.rul_predictor.predict_rul(seq)
            rul_min = rul_result["predicted_rul_min"]
            result["predicted_rul_min"] = round(rul_min, 2)

            # RTB classification
            if rul_min <= RTB_CRITICAL_MIN:
                result["rtb_alert_level"] = "RTB_CRITICAL"
                result["rtb_window_active"] = True
            elif rul_min <= RTB_WARNING_MIN:
                result["rtb_alert_level"] = "RTB_ADVISORY"
                result["rtb_window_active"] = True
            else:
                result["rtb_alert_level"] = "NONE"
                result["rtb_window_active"] = False

        except Exception as e:
            log.warning("RUL prediction failed: %s", e)

        return result

    # ── Top contributing sensors ────────────────────────────────

    def _identify_top_contributors(
        self,
        fused_vec: np.ndarray,
        raw_frame: Dict[str, Any],
    ) -> List[str]:
        """
        Identify which sensors contributed most to the current state.
        Simple heuristic: compare fused vector deviation from nominal.
        """
        # Use sensor values that deviate most from typical ranges
        contributors = []
        sensor_checks = [
            ("CHT_1", raw_frame.get("cht_c", [0]*4)[0] if isinstance(raw_frame.get("cht_c"), list) else 0, 180, 40),
            ("CHT_2", raw_frame.get("cht_c", [0]*4)[1] if isinstance(raw_frame.get("cht_c"), list) and len(raw_frame.get("cht_c", [])) > 1 else 0, 180, 40),
            ("CHT_3", raw_frame.get("cht_c", [0]*4)[2] if isinstance(raw_frame.get("cht_c"), list) and len(raw_frame.get("cht_c", [])) > 2 else 0, 180, 40),
            ("CHT_4", raw_frame.get("cht_c", [0]*4)[3] if isinstance(raw_frame.get("cht_c"), list) and len(raw_frame.get("cht_c", [])) > 3 else 0, 180, 40),
            ("EGT_1", raw_frame.get("egt_c", [0]*4)[0] if isinstance(raw_frame.get("egt_c"), list) else 0, 740, 60),
            ("EGT_2", raw_frame.get("egt_c", [0]*4)[1] if isinstance(raw_frame.get("egt_c"), list) and len(raw_frame.get("egt_c", [])) > 1 else 0, 740, 60),
            ("RPM", raw_frame.get("rpm", 0), 2200, 200),
            ("OIL_PRESSURE", raw_frame.get("oil_pressure_kpa", 0), 400, 100),
            ("VIBRATION", raw_frame.get("vibration_rms_g", 0), 1.5, 0.5),
        ]

        deviations = []
        for name, value, nominal, scale in sensor_checks:
            dev = abs(value - nominal) / scale
            deviations.append((name, dev))

        # Sort by deviation, take top 3
        deviations.sort(key=lambda x: x[1], reverse=True)
        contributors = [name for name, dev in deviations[:3] if dev > 0.1]

        return contributors

    # ── Broadcast server ────────────────────────────────────────

    async def _broadcast_handler(self, ws: ServerConnection) -> None:
        """Handle incoming broadcast subscriber connections."""
        self._broadcast_clients.add(ws)
        remote = ws.remote_address
        log.info("Broadcast client connected: %s", remote)
        try:
            async for _ in ws:
                pass  # Client is read-only (subscribes to broadcasts)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._broadcast_clients.discard(ws)
            log.info("Broadcast client disconnected: %s", remote)

    async def _broadcast(self, payload: Dict[str, Any]) -> None:
        """Broadcast enriched payload to all connected subscribers."""
        if not self._broadcast_clients:
            return
        data = json.dumps(payload)
        stale: list[ServerConnection] = []
        for ws in list(self._broadcast_clients):
            try:
                await ws.send(data)
            except websockets.ConnectionClosed:
                stale.append(ws)
        for ws in stale:
            self._broadcast_clients.discard(ws)

    # ── Main loop ───────────────────────────────────────────────

    async def run(self) -> None:
        """Main event loop: consume stream → process → broadcast."""
        log.info("AI Service starting…")
        log.info("  Streamer:  %s", self.streamer_url)
        log.info("  Broadcast: ws://localhost:%d", self.broadcast_port)

        # Start broadcast server
        broadcast_server = await serve(
            self._broadcast_handler, "localhost", self.broadcast_port,
        )
        log.info("  Broadcast server listening on port %d", self.broadcast_port)

        # Connect to telemetry streamer
        retries = 0
        max_retries = 30
        while retries < max_retries:
            try:
                async with connect(self.streamer_url) as ws:
                    log.info("  Connected to streamer at %s", self.streamer_url)
                    retries = 0

                    async for raw_msg in ws:
                        try:
                            pkt = json.loads(raw_msg)
                            payload = self.process_frame(pkt)
                            await self._broadcast(payload)
                        except json.JSONDecodeError:
                            log.warning("Invalid JSON from streamer")
                        except Exception as e:
                            log.error("Processing error: %s", e, exc_info=True)

            except (ConnectionRefusedError, OSError) as e:
                retries += 1
                wait = min(2.0 * retries, 10.0)
                log.warning(
                    "Streamer not available (attempt %d/%d): %s — retrying in %.1fs",
                    retries, max_retries, e, wait,
                )
                await asyncio.sleep(wait)

        log.info("AI Service shutting down.")
        broadcast_server.close()
        await broadcast_server.wait_closed()


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="AI Inference Service")
    parser.add_argument(
        "--streamer", type=str, default=STREAMER_URL,
        help=f"Telemetry streamer URL (default: {STREAMER_URL})",
    )
    parser.add_argument(
        "--port", type=int, default=BROADCAST_PORT,
        help=f"Broadcast port (default: {BROADCAST_PORT})",
    )
    args = parser.parse_args()

    service = AIService(
        streamer_url=args.streamer,
        broadcast_port=args.port,
    )
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        log.info("Service interrupted.")


if __name__ == "__main__":
    main()
