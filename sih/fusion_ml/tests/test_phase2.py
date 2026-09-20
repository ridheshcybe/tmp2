#!/usr/bin/env python3
"""
Phase 2 — Comprehensive Automated Test Suite
==============================================
Validates every Phase 2 component of the Aero Piston Engine Digital Twin:
sensor validation, cross-modal fusion, physics-constrained loss,
health indexing, and end-to-end pipeline latency.

    pytest -v fusion_ml/tests/test_phase2.py

Sections
--------
1. test_sensor_freeze_isolation      — SensorValidator freeze detection
2. test_cross_modal_attention_fwd    — CrossModalFusionNet forward pass
3. test_physics_constrained_loss     — PhysicsConstrainedLoss penalty
4. test_health_index_dynamics        — HealthIndexCalculator dynamics
5. test_pipeline_latency_benchmark   — End-to-end pipeline latency
"""

from __future__ import annotations

import time
from typing import Dict, List

import numpy as np
import pytest
import torch

# ── Imports under test ──────────────────────────────────────────
from fusion_ml.sensor_validator import (
    SensorValidator,
    SanitizedFrame,
    IsolationReason,
    ALL_CHANNELS,
    NUM_CHANNELS,
)
from fusion_ml.cross_modal_fusion import (
    CrossModalFusionNet,
    PhysicsConstrainedLoss,
    FusionOutput,
    FUSED_DIM,
    N_HEADS,
    MODALITY_THERMAL_INDICES,
    MODALITY_MECHANICAL_INDICES,
    MODALITY_FLUID_INDICES,
)
from fusion_ml.health_index_calculator import (
    HealthIndexCalculator,
    HealthStatus,
)
from fusion_ml.fusion_pipeline import EngineFusionPipeline


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _nominal_frame(**overrides) -> dict:
    """Build a healthy nominal telemetry frame."""
    base = {
        "rpm": 2200, "map_kpa": 78, "fuel_flow_lph": 13.0,
        "equivalence_ratio": 0.85,
        "cht_c": [178.0, 177.0, 179.0, 176.0],
        "egt_c": [740.0, 738.0, 742.0, 736.0],
        "oil_pressure_kpa": 410.0, "oil_temp_c": 88.0,
        "vibration_rms_g": 1.45,
    }
    base.update(overrides)
    return base


def _frozen_frame(cht2_val: float = 185.0) -> dict:
    """Build a frame with CHT_2 frozen to a static value."""
    return {
        "rpm": 2200 + np.random.normal(0, 50),
        "map_kpa": 78 + np.random.normal(0, 1),
        "fuel_flow_lph": 13.0 + np.random.normal(0, 0.3),
        "equivalence_ratio": 0.85,
        "cht_c": [178.0, cht2_val, 179.0, 176.0],
        "egt_c": [740.0, 738.0, 742.0, 736.0],
        "oil_pressure_kpa": 410.0, "oil_temp_c": 88.0,
        "vibration_rms_g": 1.5,
    }


# ══════════════════════════════════════════════════════════════════
#  1.  SENSOR FREEZE ISOLATION
# ══════════════════════════════════════════════════════════════════

class TestSensorFreezeIsolation:
    """
    Feed 600 consecutive identical frames for CHT_2.
    Assert CHT_2 is flagged ISOLATED_FROZEN on frame 601 while
    all other channels remain valid.
    """

    def test_cht2_frozen_after_600_frames(self):
        """
        600 identical CHT_2 values → freeze detected on frame 601.
        """
        v = SensorValidator(buffer_size=600)
        frozen_val = 185.0

        # Feed 600 identical frames (CHT_2 frozen, others vary slightly)
        for _ in range(600):
            frame = _frozen_frame(cht2_val=frozen_val)
            v.validate(frame)

        # Frame 601: should now trigger freeze detection
        result = v.validate(_frozen_frame(cht2_val=frozen_val))

        cht2_flags = [
            f for f in result.isolation_flags
            if f["channel"] == "cht_2_c"
            and f["reason"] == IsolationReason.FROZEN
        ]
        assert len(cht2_flags) > 0, (
            "CHT_2 not flagged as ISOLATED_FROZEN after 600 identical frames"
        )

    def test_other_channels_remain_valid(self):
        """
        All channels except CHT_2 should remain valid (mask=True).
        """
        v = SensorValidator(buffer_size=600)
        for _ in range(601):
            v.validate(_frozen_frame(cht2_val=185.0))

        result = v.validate(_frozen_frame(cht2_val=185.0))
        cht2_idx = ALL_CHANNELS.index("cht_2_c")

        # CHT_2 should be masked out
        assert not result.sensor_mask[cht2_idx], (
            f"CHT_2 mask should be False, got {result.sensor_mask[cht2_idx]}"
        )

        # Other channels should be valid
        for idx, ch in enumerate(ALL_CHANNELS):
            if idx == cht2_idx:
                continue
            assert result.sensor_mask[idx], (
                f"{ch} unexpectedly isolated (mask=False) at index {idx}"
            )

    def test_cht2_excluded_from_valid_sensors(self):
        """
        CHT_2 should not appear in valid_sensors dict.
        """
        v = SensorValidator(buffer_size=600)
        for _ in range(601):
            v.validate(_frozen_frame(cht2_val=185.0))

        result = v.validate(_frozen_frame(cht2_val=185.0))
        assert "cht_2_c" not in result.valid_sensors, (
            "CHT_2 still in valid_sensors after freeze detection"
        )

    def test_not_frozen_before_buffer_full(self):
        """
        Freeze should NOT trigger before buffer is full (frame < 600).
        """
        v = SensorValidator(buffer_size=600)
        for _ in range(599):
            result = v.validate(_frozen_frame(cht2_val=185.0))

        cht2_flags = [
            f for f in result.isolation_flags
            if f["channel"] == "cht_2_c"
            and f["reason"] == IsolationReason.FROZEN
        ]
        assert len(cht2_flags) == 0, (
            "Freeze detected before buffer was full"
        )


# ══════════════════════════════════════════════════════════════════
#  2.  CROSS-MODAL ATTENTION FORWARD PASS
# ══════════════════════════════════════════════════════════════════

class TestCrossModalAttentionForward:
    """
    Pass random synthetic tensors through CrossModalFusionNet
    with and without masked sensors.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.net = CrossModalFusionNet()
        self.net.eval()

    def test_output_shape_batch1(self):
        """Output fused_state_vector must be (1, 32)."""
        x = torch.randn(1, 15)
        out = self.net(x)
        assert out.fused_state_vector.shape == (1, FUSED_DIM), (
            f"Expected (1, {FUSED_DIM}), got {out.fused_state_vector.shape}"
        )

    def test_output_shape_batch8(self):
        """Output must preserve batch dimension."""
        B = 8
        x = torch.randn(B, 15)
        out = self.net(x)
        assert out.fused_state_vector.shape == (B, FUSED_DIM)

    def test_attention_weights_shape(self):
        """Cross-attention map: (B, n_heads, 1 query, 2 kv tokens)."""
        x = torch.randn(4, 15)
        out = self.net(x)
        attn = out.attention_weights["cross_modal"]
        assert attn.shape == (4, N_HEADS, 1, 2), (
            f"Expected (4, {N_HEADS}, 1, 2), got {attn.shape}"
        )

    def test_attention_weights_sum_to_one(self):
        """Attention weights must sum to 1.0 over the kv dimension."""
        x = torch.randn(4, 15)
        out = self.net(x)
        attn = out.attention_weights["cross_modal"]
        attn_sum = attn.sum(dim=-1)
        assert torch.allclose(attn_sum, torch.ones_like(attn_sum), atol=1e-5), (
            f"Attention weights don't sum to 1: {attn_sum}"
        )

    def test_masked_channel_zero_attention(self):
        """
        When mechanical sensors are fully masked, the mechanical
        context token should receive near-zero attention weight.
        """
        x = torch.randn(1, 15)
        mask = torch.ones(1, 15, dtype=torch.bool)
        # Mask ALL mechanical sensors (indices 9, 10, 11 in modality order)
        mask[0, 9] = False
        mask[0, 10] = False
        mask[0, 11] = False

        out = self.net(x, sensor_mask=mask)
        attn = out.attention_weights["cross_modal"]  # (1, H, 1, 2)

        # The first kv token is mechanical — its attention should be ~0
        mech_attn = attn[0, :, 0, 0]  # (H,) — all heads, mechanical token
        assert mech_attn.mean() < 0.05, (
            f"Mechanical token attention too high with full mask: "
            f"{mech_attn.mean():.4f}"
        )

    def test_no_nan_in_output(self):
        """No NaN or Inf in output tensors."""
        x = torch.randn(4, 15)
        out = self.net(x)
        assert not torch.isnan(out.fused_state_vector).any()
        assert not torch.isinf(out.fused_state_vector).any()

    def test_output_not_static(self):
        """Different inputs should produce different outputs."""
        x1 = torch.randn(1, 15)
        x2 = torch.randn(1, 15)
        out1 = self.net(x1)
        out2 = self.net(x2)
        assert not torch.allclose(out1.fused_state_vector, out2.fused_state_vector)


# ══════════════════════════════════════════════════════════════════
#  3.  PHYSICS-CONSTRAINED LOSS
# ══════════════════════════════════════════════════════════════════

class TestPhysicsConstrainedLoss:
    """
    Create two synthetic batches:
      - Batch A: thermodynamically consistent (fuel↑ with RPM↑)
      - Batch B: thermodynamically invalid (fuel↑ while RPM↓, EGT↓)
    Assert Loss(B) > Loss(A).
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        torch.manual_seed(42)
        self.criterion = PhysicsConstrainedLoss(physics_weight=1.0)
        self.pred = torch.randn(8, 32)
        self.target = torch.randn(8, 32)

    def test_violation_batch_higher_loss(self):
        """
        Batch B (fuel↑, RPM↓, EGT↓) must have higher loss
        than Batch A (fuel↑, RPM↑, EGT↑) due to physics penalty.
        """
        B = 8

        # ── Batch A: consistent ──
        # fuel_flow high, RPM high, EGT high (all correlated)
        batch_a = torch.zeros(B, 15)
        batch_a[:, :4] = 200.0     # CHT high
        batch_a[:, 4:8] = 800.0    # EGT high
        batch_a[:, 9] = 3000.0     # RPM high
        batch_a[:, 12] = 30.0      # Fuel flow high
        batch_a[:, 13] = 90.0      # Oil temp

        # ── Batch B: inconsistent ──
        # fuel_flow high, but RPM low and EGT low
        batch_b = torch.zeros(B, 15)
        batch_b[:, :4] = 150.0     # CHT low
        batch_b[:, 4:8] = 400.0    # EGT low
        batch_b[:, 9] = 800.0      # RPM low
        batch_b[:, 12] = 50.0      # Fuel flow HIGH (violation!)
        batch_b[:, 13] = 90.0      # Oil temp

        _, comps_a = self.criterion(self.pred, self.target, raw_inputs=batch_a)
        _, comps_b = self.criterion(self.pred, self.target, raw_inputs=batch_b)

        assert comps_b["physics_penalty"] > comps_a["physics_penalty"], (
            f"Batch B penalty ({comps_b['physics_penalty']:.6f}) "
            f"should exceed Batch A ({comps_a['physics_penalty']:.6f})"
        )

        assert comps_b["total_loss"] > comps_a["total_loss"], (
            f"Batch B total loss should exceed Batch A"
        )

    def test_consistent_batch_low_penalty(self):
        """
        When fuel flow, RPM, and EGT all increase together,
        the physics penalty should be near zero.
        """
        B = 8
        batch = torch.zeros(B, 15)
        batch[:, :4] = 200.0
        batch[:, 4:8] = 800.0
        batch[:, 9] = 3000.0   # RPM high
        batch[:, 12] = 30.0    # Fuel high
        batch[:, 13] = 90.0

        _, comps = self.criterion(self.pred, self.target, raw_inputs=batch)
        assert comps["physics_penalty"] == pytest.approx(0.0, abs=1e-6), (
            f"Consistent batch penalty should be ~0, got {comps['physics_penalty']}"
        )

    def test_gradient_flows(self):
        """Loss must be differentiable."""
        x = torch.randn(4, 15, requires_grad=True)
        target = torch.randn(4, 32)
        pred = torch.randn(4, 32, requires_grad=True)

        loss, _ = self.criterion(pred, target, raw_inputs=x)
        loss.backward()

        assert pred.grad is not None
        assert x.grad is not None
        assert not torch.isnan(loss)


# ══════════════════════════════════════════════════════════════════
#  4.  HEALTH INDEX DYNAMICS
# ══════════════════════════════════════════════════════════════════

class TestHealthIndexDynamics:
    """
    - Nominal data: EHI between 90% and 100%.
    - Severe thermal strain (EGT > 880°C): EHI < 50%, status = CRITICAL.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.calc = HealthIndexCalculator()

    def test_nominal_ehi_90_to_100(self):
        """
        Nominal engine frame should produce EHI between 90 and 100.
        """
        frame = _nominal_frame()
        result = self.calc.compute(raw_frame=frame)
        ehi = result["engine_health_index"]
        assert 90.0 <= ehi <= 100.0, (
            f"Nominal EHI = {ehi:.1f}, expected 90–100"
        )

    def test_nominal_status_normal(self):
        """Nominal frame should have NORMAL status."""
        result = self.calc.compute(raw_frame=_nominal_frame())
        assert result["health_status"] == HealthStatus.NORMAL

    def test_severe_thermal_ehi_below_50(self):
        """
        Inject severe thermal strain (EGT > 880°C across all cylinders).
        EHI must drop below 50%.
        """
        frame = _nominal_frame()
        frame["egt_c"] = [890.0, 885.0, 895.0, 888.0]  # all > 880
        frame["cht_c"] = [250.0, 248.0, 252.0, 246.0]  # high CHT
        result = self.calc.compute(raw_frame=frame)
        ehi = result["engine_health_index"]
        assert ehi < 50.0, (
            f"Severe thermal EHI = {ehi:.1f}, expected < 50"
        )

    def test_severe_thermal_status_critical(self):
        """
        Severe thermal strain must transition status to CRITICAL.
        """
        frame = _nominal_frame()
        frame["egt_c"] = [890.0, 885.0, 895.0, 888.0]
        frame["cht_c"] = [250.0, 248.0, 252.0, 246.0]
        result = self.calc.compute(raw_frame=frame)
        assert result["health_status"] == HealthStatus.CRITICAL, (
            f"Expected CRITICAL, got {result['health_status']}"
        )

    def test_progressive_thermal_degradation(self):
        """
        As EGT increases progressively, EHI must decrease monotonically.
        """
        ehis = []
        for egt_boost in [0, 20, 40, 60, 80, 100, 120, 140]:
            frame = _nominal_frame()
            base_egt = [740.0, 738.0, 742.0, 736.0]
            frame["egt_c"] = [e + egt_boost for e in base_egt]
            frame["cht_c"] = [c + egt_boost * 0.3 for c in frame["cht_c"]]
            result = self.calc.compute(raw_frame=frame)
            ehis.append(result["engine_health_index"])

        for i in range(len(ehis) - 1):
            assert ehis[i] >= ehis[i + 1], (
                f"EHI not monotonic: {ehis[i]:.1f} → {ehis[i+1]:.1f}"
            )

        # Final EHI should be well below 50
        assert ehis[-1] < 50.0, (
            f"Final progressive EHI = {ehis[-1]:.1f}, expected < 50"
        )

    def test_low_oil_pressure_drops_ehi(self):
        """Low oil pressure should reduce lubrication health and EHI."""
        normal = self.calc.compute(raw_frame=_nominal_frame())
        low_oil = self.calc.compute(raw_frame=_nominal_frame(
            oil_pressure_kpa=120.0,
        ))
        assert low_oil["engine_health_index"] < normal["engine_health_index"]
        assert low_oil["lubrication_health"] < normal["lubrication_health"]

    def test_high_vibration_drops_ehi(self):
        """High vibration should reduce mechanical stress index."""
        normal = self.calc.compute(raw_frame=_nominal_frame())
        high_vib = self.calc.compute(raw_frame=_nominal_frame(
            vibration_rms_g=2.5,
        ))
        assert high_vib["engine_health_index"] < normal["engine_health_index"]
        assert high_vib["mechanical_stress_index"] < normal["mechanical_stress_index"]


# ══════════════════════════════════════════════════════════════════
#  5.  PIPELINE LATENCY BENCHMARK
# ══════════════════════════════════════════════════════════════════

class TestPipelineLatencyBenchmark:
    """
    Stream 500 consecutive frames through
    EngineFusionPipeline.process_frame(). Measure per-frame latency.
    Assert p95 latency < 25 ms on CPU.
    """

    def test_p95_latency_under_25ms(self):
        """
        p95 of 500 frames must be < 25 ms.
        """
        pipeline = EngineFusionPipeline()
        frame = {
            "rpm": 2180.0, "map_kpa": 76.5, "fuel_flow_lph": 12.8,
            "equivalence_ratio": 0.84,
            "cht_c": [179.2, 177.8, 180.5, 176.3],
            "egt_c": [742.1, 739.8, 744.5, 737.2],
            "oil_pressure_kpa": 408.0, "oil_temp_c": 89.5,
            "vibration_rms_g": 1.48,
        }

        # Warmup
        for _ in range(30):
            pipeline.process_frame(frame)

        # Timed run
        times_ms: List[float] = []
        for _ in range(500):
            t0 = time.perf_counter()
            pipeline.process_frame(frame)
            t1 = time.perf_counter()
            times_ms.append((t1 - t0) * 1000.0)

        times_sorted = sorted(times_ms)
        p95 = times_sorted[int(0.95 * len(times_sorted))]
        median = times_sorted[len(times_sorted) // 2]
        mean = sum(times_ms) / len(times_ms)

        assert p95 < 25.0, (
            f"p95 latency = {p95:.2f} ms, target < 25 ms\n"
            f"(median={median:.2f}, mean={mean:.2f}, "
            f"max={max(times_ms):.2f})"
        )

    def test_median_latency_under_20ms(self):
        """Median must be < 20 ms."""
        pipeline = EngineFusionPipeline()
        stats = pipeline.benchmark(n_frames=500, warmup=30)
        assert stats["median_ms"] < 20.0, (
            f"Median = {stats['median_ms']:.2f} ms, target < 20 ms"
        )

    def test_mean_latency_under_15ms(self):
        """Mean must be < 15 ms."""
        pipeline = EngineFusionPipeline()
        stats = pipeline.benchmark(n_frames=500, warmup=30)
        assert stats["mean_ms"] < 15.0, (
            f"Mean = {stats['mean_ms']:.2f} ms, target < 15 ms"
        )


# ══════════════════════════════════════════════════════════════════
#  Runner
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
