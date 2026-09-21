#!/usr/bin/env python3
"""
Unit tests for fusion_ml.fusion_pipeline.EngineFusionPipeline

Run:
    pytest -v fusion_ml/tests/test_fusion_pipeline.py
"""

from __future__ import annotations

import statistics
import time

import numpy as np
import pytest

from fusion_ml.fusion_pipeline import EngineFusionPipeline
from fusion_ml.sensor_validator import ALL_CHANNELS, NUM_CHANNELS


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _nominal_frame(**overrides) -> dict:
    """Build a realistic nominal telemetry frame."""
    base = {
        "rpm": 2180.0, "map_kpa": 76.5, "fuel_flow_lph": 12.8,
        "equivalence_ratio": 0.84,
        "cht_c": [179.2, 177.8, 180.5, 176.3],
        "egt_c": [742.1, 739.8, 744.5, 737.2],
        "oil_pressure_kpa": 408.0, "oil_temp_c": 89.5,
        "vibration_rms_g": 1.48,
        "air_density_kg_m3": 0.98, "ambient_temp_c": -24.5,
        "ambient_pressure_kpa": 74.8,
    }
    base.update(overrides)
    return base


def _faulty_frame() -> dict:
    """Build a faulty telemetry frame (lean burn + piston wear)."""
    return {
        "rpm": 1700.0, "map_kpa": 60.0, "fuel_flow_lph": 7.5,
        "equivalence_ratio": 0.60,
        "cht_c": [245.0, 242.0, 250.0, 238.0],
        "egt_c": [895.0, 890.0, 905.0, 882.0],
        "oil_pressure_kpa": 220.0, "oil_temp_c": 128.0,
        "vibration_rms_g": 2.15,
        "air_density_kg_m3": 0.85, "ambient_temp_c": -25.0,
        "ambient_pressure_kpa": 70.0,
    }


# ══════════════════════════════════════════════════════════════════
#  1.  Pipeline initialization
# ══════════════════════════════════════════════════════════════════

class TestPipelineInit:
    """Verify pipeline initializes all components."""

    def test_creates_validator(self):
        pipeline = EngineFusionPipeline()
        assert pipeline.validator is not None

    def test_creates_fusion_net(self):
        pipeline = EngineFusionPipeline()
        assert pipeline.fusion_net is not None
        assert not pipeline.fusion_net.training  # eval mode

    def test_creates_health_calc(self):
        pipeline = EngineFusionPipeline()
        assert pipeline.health_calc is not None


# ══════════════════════════════════════════════════════════════════
#  2.  process_frame output structure
# ══════════════════════════════════════════════════════════════════

class TestProcessFrameOutput:
    """Verify enriched output has all required fields."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.pipeline = EngineFusionPipeline()
        self.result = self.pipeline.process_frame(_nominal_frame())

    def test_fused_vector_present(self):
        assert "fused_vector" in self.result
        assert len(self.result["fused_vector"]) == 32

    def test_health_index_present(self):
        assert "engine_health_index" in self.result
        assert 0.0 <= self.result["engine_health_index"] <= 100.0

    def test_combustion_efficiency_present(self):
        assert "combustion_efficiency" in self.result
        assert 0.0 <= self.result["combustion_efficiency"] <= 100.0

    def test_thermal_balance_present(self):
        assert "thermal_balance_spread" in self.result
        assert self.result["thermal_balance_spread"] >= 0.0

    def test_health_status_valid(self):
        assert self.result["health_status"] in {
            "NORMAL", "DEGRADED", "CRITICAL",
        }

    def test_isolation_flags_present(self):
        assert "sensor_isolation_flags" in self.result
        assert isinstance(self.result["sensor_isolation_flags"], list)

    def test_active_sensors_present(self):
        assert "active_sensors" in self.result
        assert len(self.result["active_sensors"]) == NUM_CHANNELS

    def test_original_frame_preserved(self):
        """Original telemetry keys should still be in the output."""
        assert "rpm" in self.result
        assert "cht_c" in self.result
        assert self.result["rpm"] == 2180.0

    def test_sub_indices_present(self):
        assert "thermal_strain_index" in self.result
        assert "mechanical_stress_index" in self.result
        assert "lubrication_health" in self.result
        assert "model_anomaly_residual" in self.result


# ══════════════════════════════════════════════════════════════════
#  3.  Normal vs faulty comparison
# ══════════════════════════════════════════════════════════════════

class TestNormalVsFaulty:
    """Faulty frames should produce lower health scores."""

    def test_faulty_ehi_lower(self):
        pipeline = EngineFusionPipeline()
        normal = pipeline.process_frame(_nominal_frame())
        faulty = pipeline.process_frame(_faulty_frame())
        assert faulty["engine_health_index"] < normal["engine_health_index"]

    def test_faulty_status_worse(self):
        pipeline = EngineFusionPipeline()
        normal = pipeline.process_frame(_nominal_frame())
        faulty = pipeline.process_frame(_faulty_frame())
        status_rank = {"NORMAL": 0, "DEGRADED": 1, "CRITICAL": 2}
        assert status_rank[faulty["health_status"]] >= status_rank[normal["health_status"]]

    def test_faulty_combustion_efficiency_lower(self):
        pipeline = EngineFusionPipeline()
        normal = pipeline.process_frame(_nominal_frame())
        faulty = pipeline.process_frame(_faulty_frame())
        assert faulty["combustion_efficiency"] < normal["combustion_efficiency"]


# ══════════════════════════════════════════════════════════════════
#  4.  Consistency (deterministic in eval mode)
# ══════════════════════════════════════════════════════════════════

class TestConsistency:
    """Same input should produce same output (eval mode)."""

    def test_reproducible_output(self):
        pipeline = EngineFusionPipeline()
        frame = _nominal_frame()
        r1 = pipeline.process_frame(frame)
        r2 = pipeline.process_frame(frame)
        assert r1["engine_health_index"] == r2["engine_health_index"]
        assert r1["fused_vector"] == r2["fused_vector"]


# ══════════════════════════════════════════════════════════════════
#  5.  Integration with FaultInjector
# ══════════════════════════════════════════════════════════════════

class TestFaultInjectorIntegration:
    """Feed real FaultInjector frames through the pipeline."""

    def test_lean_burn_drops_ehi(self):
        from simulator.fault_injector import FaultInjector
        pipeline = EngineFusionPipeline()
        inj = FaultInjector(dt=0.1, enable_noise=False)
        for _ in range(100):
            inj.step(0.7)
        inj.trigger_fault("LEAN_BURN_RUNAWAY", 0.8, 0.04)

        ehis = []
        for _ in range(300):
            frame = inj.step(0.7)
            result = pipeline.process_frame(frame)
            ehis.append(result["engine_health_index"])

        min_ehi = min(ehis)
        assert min_ehi < 70.0, (
            f"Pipeline lean burn min EHI = {min_ehi:.1f}, expected < 70"
        )

    def test_piston_ring_drops_ehi(self):
        from simulator.fault_injector import FaultInjector
        pipeline = EngineFusionPipeline()
        inj = FaultInjector(dt=0.1, enable_noise=False)
        for _ in range(100):
            inj.step(0.7)
        inj.trigger_fault("PISTON_RING_WEAR", 0.8, 0.03)

        ehis = []
        for _ in range(400):
            frame = inj.step(0.7)
            result = pipeline.process_frame(frame)
            ehis.append(result["engine_health_index"])

        min_ehi = min(ehis)
        assert min_ehi < 70.0, (
            f"Pipeline piston ring min EHI = {min_ehi:.1f}, expected < 70"
        )


# ══════════════════════════════════════════════════════════════════
#  6.  Latency benchmark
# ══════════════════════════════════════════════════════════════════

class TestLatencyBenchmark:
    """End-to-end pipeline must process 1000 frames with median < 25 ms."""

    def test_median_latency_under_25ms(self):
        pipeline = EngineFusionPipeline()
        stats = pipeline.benchmark(n_frames=1000, warmup=50)
        assert stats["median_ms"] < 25.0, (
            f"Median latency = {stats['median_ms']:.2f} ms, "
            f"target < 25 ms.\n"
            f"Full stats: mean={stats['mean_ms']:.2f}, "
            f"p95={stats['p95_ms']:.2f}, max={stats['max_ms']:.2f}"
        )

    def test_mean_latency_under_20ms(self):
        pipeline = EngineFusionPipeline()
        stats = pipeline.benchmark(n_frames=1000, warmup=50)
        assert stats["mean_ms"] < 20.0, (
            f"Mean latency = {stats['mean_ms']:.2f} ms, "
            f"target < 20 ms"
        )

    def test_p95_latency_under_30ms(self):
        pipeline = EngineFusionPipeline()
        stats = pipeline.benchmark(n_frames=1000, warmup=50)
        assert stats["p95_ms"] < 30.0, (
            f"P95 latency = {stats['p95_ms']:.2f} ms, "
            f"target < 30 ms"
        )


# ══════════════════════════════════════════════════════════════════
#  7.  Streaming simulation
# ══════════════════════════════════════════════════════════════════

class TestStreamingSimulation:
    """Simulate a continuous stream of 100 frames."""

    def test_streaming_produces_valid_results(self):
        pipeline = EngineFusionPipeline()
        rng = np.random.default_rng(0)
        results = []

        for i in range(100):
            frame = {
                "rpm": float(2200 + rng.normal(0, 30)),
                "map_kpa": float(78 + rng.normal(0, 1)),
                "fuel_flow_lph": float(13.0 + rng.normal(0, 0.3)),
                "equivalence_ratio": float(0.85 + rng.normal(0, 0.005)),
                "cht_c": [float(180 + rng.normal(0, 2)) for _ in range(4)],
                "egt_c": [float(740 + rng.normal(0, 3)) for _ in range(4)],
                "oil_pressure_kpa": float(410 + rng.normal(0, 3)),
                "oil_temp_c": float(89 + rng.normal(0, 1)),
                "vibration_rms_g": float(1.5 + rng.normal(0, 0.05)),
                "air_density_kg_m3": float(0.98 + rng.normal(0, 0.01)),
                "ambient_temp_c": float(-24.5 + rng.normal(0, 0.5)),
                "ambient_pressure_kpa": float(74.8 + rng.normal(0, 0.5)),
            }
            result = pipeline.process_frame(frame)
            results.append(result)

        # All results should be valid
        for r in results:
            assert 0.0 <= r["engine_health_index"] <= 100.0
            assert r["health_status"] in {"NORMAL", "DEGRADED", "CRITICAL"}
            assert len(r["fused_vector"]) == 32

        # Health should be mostly NORMAL for nominal data
        statuses = [r["health_status"] for r in results]
        assert statuses.count("NORMAL") > 80, (
            f"Only {statuses.count('NORMAL')}/100 frames NORMAL"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
