#!/usr/bin/env python3
"""
Engine Fusion Pipeline
======================
End-to-end wrapper that chains:

1. **SensorValidator** — sanitises raw 10 Hz telemetry.
2. **CrossModalFusionNet** — fuses modalities into a 32-dim latent.
3. **HealthIndexCalculator** — derives EHI, CDM, and thermal balance.

Usage
-----
    from fusion_ml.fusion_pipeline import EngineFusionPipeline

    pipeline = EngineFusionPipeline()
    enriched = pipeline.process_frame(raw_telemetry_frame)
    print(enriched["engine_health_index"])
"""

from __future__ import annotations

import statistics
import time
from typing import Any, Dict, List, Optional

import numpy as np
import torch

from fusion_ml.sensor_validator import (
    SensorValidator,
    SanitizedFrame,
    ALL_CHANNELS,
    NUM_CHANNELS,
)
from fusion_ml.cross_modal_fusion import (
    CrossModalFusionNet,
    FusionOutput,
    MODALITY_THERMAL_INDICES,
    MODALITY_MECHANICAL_INDICES,
    MODALITY_FLUID_INDICES,
    FUSED_DIM,
)
from fusion_ml.health_index_calculator import (
    HealthIndexCalculator,
    HealthStatus,
)


# ══════════════════════════════════════════════════════════════════
#  Modality feature extraction order
# ══════════════════════════════════════════════════════════════════

# The 15 features expected by CrossModalFusionNet, in order:
# [CHT×4, EGT×4, Ambient_Temp, RPM, MAP, Vibration, Fuel_Flow, Oil_P, Oil_T]
_MODALITY_INDICES = (
    MODALITY_THERMAL_INDICES      # [4, 5, 6, 7, 8, 9, 10, 11, 16]  → 9 features
    + MODALITY_MECHANICAL_INDICES  # [0, 1, 14]                       → 3 features
    + MODALITY_FLUID_INDICES       # [2, 12, 13]                      → 3 features
)


# ══════════════════════════════════════════════════════════════════
#  Pipeline
# ══════════════════════════════════════════════════════════════════

class EngineFusionPipeline:
    """
    End-to-end telemetry processing pipeline.

    Chains sensor validation → neural fusion → health indexing into a
    single ``process_frame()`` call.

    Parameters
    ----------
    device : str
        PyTorch device (``"cpu"`` default).
    validator_buffer_size : int
        FIFO buffer length for :class:`SensorValidator`.
    health_weights : dict | None
        Custom EHI weights for :class:`HealthIndexCalculator`.
    """

    def __init__(
        self,
        device: str = "cpu",
        validator_buffer_size: int = 600,
        health_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self.device = torch.device(device)

        # ── Step 1: Sensor Validator ──
        self.validator = SensorValidator(buffer_size=validator_buffer_size)

        # ── Step 2 & 3: Cross-Modal Fusion Network ──
        self.fusion_net = CrossModalFusionNet()
        self.fusion_net.to(self.device)
        self.fusion_net.eval()

        # ── Step 4: Health Index Calculator ──
        self.health_calc = HealthIndexCalculator(ehi_weights=health_weights)

        # NOTE: the (1, 15) input/mask tensors are built per frame in
        # ``_build_tensors`` — they must stay aligned with
        # ``_MODALITY_INDICES`` and are *not* the same shape as the
        # 18-entry ``ALL_CHANNELS`` validator mask.

    # ── Public API ─────────────────────────────────────────────

    def process_frame(
        self,
        raw_telemetry: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process a single telemetry frame through the full pipeline.

        Parameters
        ----------
        raw_telemetry : dict
            Raw telemetry frame (as produced by ``FaultInjector.step()``
            or the WebSocket streamer).

        Returns
        -------
        dict
            Enriched dictionary containing:

            * All original telemetry fields
            * ``fused_vector``: list[float] — 32-dim latent
            * ``engine_health_index``: float (0–100)
            * ``combustion_efficiency``: float (0–100)
            * ``thermal_balance_spread``: float
            * ``health_status``: str
            * ``sensor_isolation_flags``: list[dict]
            * ``active_sensors``: dict[str, bool]
        """
        # ── Step 1: Validate sensors ──
        sanitized = self.validator.validate(raw_telemetry)

        # ── Step 2: Build tensor + mask ──
        input_tensor, mask_tensor = self._build_tensors(sanitized)

        # ── Step 3: Forward pass through fusion net ──
        with torch.no_grad():
            fusion_out = self.fusion_net(input_tensor, sensor_mask=mask_tensor)

        fused_vector = fusion_out.fused_state_vector.cpu().numpy().ravel()

        # ── Step 4: Compute health indices ──
        health = self.health_calc.compute(
            fused_vector=fused_vector,
            raw_frame=raw_telemetry,
        )

        # ── Step 5: Assemble enriched output ──
        output = dict(raw_telemetry)  # shallow copy

        # Fused latent
        output["fused_vector"] = [round(float(v), 6) for v in fused_vector]

        # Health scores
        output["engine_health_index"] = health["engine_health_index"]
        output["combustion_efficiency"] = health["combustion_efficiency"]
        output["thermal_balance_spread"] = health["thermal_balance_spread"]
        output["health_status"] = health["health_status"]

        # Sub-indices
        output["thermal_strain_index"] = health["thermal_strain_index"]
        output["mechanical_stress_index"] = health["mechanical_stress_index"]
        output["lubrication_health"] = health["lubrication_health"]
        output["model_anomaly_residual"] = health["model_anomaly_residual"]

        # Sensor isolation
        output["sensor_isolation_flags"] = sanitized.isolation_flags

        # ``mask_tensor`` only carries the 15 modality-ordered features that
        # the fusion net consumes, whereas ``active_sensors`` reports every
        # monitored channel — so read the full-length mask from the
        # sanitised frame instead of the reduced fusion tensor.
        active = sanitized.sensor_mask
        if len(active) != NUM_CHANNELS:  # defensive: never short-index
            active = (list(active) + [True] * NUM_CHANNELS)[:NUM_CHANNELS]
        output["active_sensors"] = {
            ch: bool(active[i]) for i, ch in enumerate(ALL_CHANNELS)
        }

        return output

    # ── Tensor construction ────────────────────────────────────

    def _build_tensors(
        self,
        sanitized: SanitizedFrame,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Convert sanitized frame into a (1, 15) input tensor and
        a (1, 15) boolean mask for the fusion network.

        The 15 features are in modality order:
        [thermal(9), mechanical(3), fluid(3)]
        """
        all_vals = sanitized.all_values
        mask_list = sanitized.sensor_mask

        # Build the 15-feature vector from ALL_CHANNELS values
        features = [float(all_vals.get(ALL_CHANNELS[idx], 0.0)) for idx in _MODALITY_INDICES]

        # Build the 15-feature mask
        mask = [bool(mask_list[idx]) for idx in _MODALITY_INDICES]

        input_tensor = torch.tensor([features], dtype=torch.float32, device=self.device)
        mask_tensor = torch.tensor([mask], dtype=torch.bool, device=self.device)

        return input_tensor, mask_tensor

    # ── Benchmarking ───────────────────────────────────────────

    def benchmark(
        self,
        n_frames: int = 1000,
        warmup: int = 50,
    ) -> Dict[str, float]:
        """
        Measure end-to-end pipeline latency.

        Parameters
        ----------
        n_frames : int
            Number of frames to measure.
        warmup : int
            Warmup frames (not timed).

        Returns
        -------
        dict
            ``mean_ms``, ``median_ms``, ``std_ms``, ``p95_ms``, ``max_ms``.
        """
        # Generate a realistic test frame
        test_frame = self._make_test_frame()

        # Warmup
        for _ in range(warmup):
            self.process_frame(test_frame)

        # Timed runs
        times_ms: List[float] = []
        for _ in range(n_frames):
            t0 = time.perf_counter()
            self.process_frame(test_frame)
            t1 = time.perf_counter()
            times_ms.append((t1 - t0) * 1000.0)

        return {
            "mean_ms": statistics.mean(times_ms),
            "median_ms": statistics.median(times_ms),
            "std_ms": statistics.stdev(times_ms),
            "p95_ms": sorted(times_ms)[int(0.95 * n_frames)],
            "max_ms": max(times_ms),
            "min_ms": min(times_ms),
            "n_frames": n_frames,
        }

    @staticmethod
    def _make_test_frame() -> Dict[str, Any]:
        """Build a realistic test frame for benchmarking."""
        rng = np.random.default_rng(42)
        return {
            "rpm": float(2200 + rng.normal(0, 50)),
            "map_kpa": float(78 + rng.normal(0, 2)),
            "fuel_flow_lph": float(13.0 + rng.normal(0, 0.5)),
            "equivalence_ratio": float(0.85 + rng.normal(0, 0.01)),
            "cht_c": [float(180 + rng.normal(0, 3)) for _ in range(4)],
            "egt_c": [float(740 + rng.normal(0, 5)) for _ in range(4)],
            "oil_pressure_kpa": float(410 + rng.normal(0, 5)),
            "oil_temp_c": float(88 + rng.normal(0, 2)),
            "vibration_rms_g": float(1.5 + rng.normal(0, 0.1)),
            "air_density_kg_m3": float(1.0 + rng.normal(0, 0.02)),
            "ambient_temp_c": float(-24 + rng.normal(0, 1)),
            "ambient_pressure_kpa": float(75 + rng.normal(0, 1)),
        }


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def _demo() -> None:
    """Run the pipeline on a sample frame and display results."""
    print("\n  Engine Fusion Pipeline — Demo")
    print("  " + "=" * 55)

    pipeline = EngineFusionPipeline()

    # Sample frame
    frame = {
        "rpm": 2180.0, "map_kpa": 76.5, "fuel_flow_lph": 12.8,
        "equivalence_ratio": 0.84,
        "cht_c": [179.2, 177.8, 180.5, 176.3],
        "egt_c": [742.1, 739.8, 744.5, 737.2],
        "oil_pressure_kpa": 408.0, "oil_temp_c": 89.5,
        "vibration_rms_g": 1.48,
        "air_density_kg_m3": 0.98, "ambient_temp_c": -24.5,
        "ambient_pressure_kpa": 74.8,
    }

    result = pipeline.process_frame(frame)

    # Print key results
    for key in [
        "engine_health_index", "combustion_efficiency",
        "thermal_balance_spread", "health_status",
        "thermal_strain_index", "mechanical_stress_index",
        "lubrication_health", "model_anomaly_residual",
    ]:
        print(f"  {key:<30s}  {result[key]}")

    n_active = sum(1 for v in result["active_sensors"].values() if v)
    print(f"  {'active_sensors':<30s}  {n_active}/{len(result['active_sensors'])}")
    print(f"  {'fused_vector dims':<30s}  {len(result['fused_vector'])}")
    print(f"  {'isolation_flags':<30s}  {len(result['sensor_isolation_flags'])}")

    # Benchmark
    print("\n  Running benchmark (1000 frames)…")
    stats = pipeline.benchmark(n_frames=1000)
    print(f"    Mean:    {stats['mean_ms']:.2f} ms")
    print(f"    Median:  {stats['median_ms']:.2f} ms")
    print(f"    P95:     {stats['p95_ms']:.2f} ms")
    print(f"    Max:     {stats['max_ms']:.2f} ms")
    if stats["median_ms"] < 25.0:
        print("    ✓  Latency target met (median < 25 ms)")
    else:
        print("    ✗  Latency target NOT met (median ≥ 25 ms)")
    print()


if __name__ == "__main__":
    _demo()
