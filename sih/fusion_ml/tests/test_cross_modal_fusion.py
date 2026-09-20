#!/usr/bin/env python3
"""
Unit tests for fusion_ml.cross_modal_fusion

Run:
    pytest -v fusion_ml/tests/test_cross_modal_fusion.py
"""

from __future__ import annotations

import time

import pytest
import torch

from fusion_ml.cross_modal_fusion import (
    CrossModalFusionNet,
    FusionOutput,
    PhysicsConstrainedLoss,
    ModalityEmbedding,
    GatedResidualBlock,
    CrossModalAttention,
    FFN,
    FusionOutput as _,
    MODALITY_DIMS,
    D_MODEL,
    FUSED_DIM,
    N_HEADS,
    benchmark_latency,
)


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _make_input(B: int = 1, isolated: list | None = None) -> tuple:
    """Create a random input tensor and optional sensor mask."""
    x = torch.randn(B, 15)
    mask = torch.ones(B, 15, dtype=torch.bool)
    if isolated:
        for idx in isolated:
            mask[:, idx] = False
    return x, mask


# ══════════════════════════════════════════════════════════════════
#  1.  Architecture shape tests
# ══════════════════════════════════════════════════════════════════

class TestArchitectureShapes:
    """Verify all tensor shapes through the network."""

    def test_output_is_fusion_output(self):
        net = CrossModalFusionNet()
        x, mask = _make_input()
        out = net(x, sensor_mask=mask)
        assert isinstance(out, FusionOutput)

    def test_fused_state_vector_shape(self):
        net = CrossModalFusionNet()
        x, mask = _make_input()
        out = net(x, sensor_mask=mask)
        assert out.fused_state_vector.shape == (1, FUSED_DIM)

    def test_batch_dimension_preserved(self):
        net = CrossModalFusionNet()
        x, mask = _make_input(B=8)
        out = net(x, sensor_mask=mask)
        assert out.fused_state_vector.shape == (8, FUSED_DIM)

    def test_attention_weights_shape(self):
        """Cross-attention map: (B, n_heads, 1 query, 2 kv tokens)."""
        net = CrossModalFusionNet()
        x, mask = _make_input()
        out = net(x, sensor_mask=mask)
        attn = out.attention_weights["cross_modal"]
        assert attn.shape == (1, N_HEADS, 1, 2)

    def test_attention_weights_sum_to_one(self):
        """Attention weights should sum to 1 over the kv dimension."""
        net = CrossModalFusionNet()
        x, mask = _make_input()
        out = net(x, sensor_mask=mask)
        attn = out.attention_weights["cross_modal"]
        attn_sum = attn.sum(dim=-1)
        assert torch.allclose(attn_sum, torch.ones_like(attn_sum), atol=1e-5)

    def test_modality_embeddings_present(self):
        net = CrossModalFusionNet()
        x, mask = _make_input()
        out = net(x, sensor_mask=mask)
        assert "thermal" in out.modality_embeddings
        assert "mechanical" in out.modality_embeddings
        assert "fluid" in out.modality_embeddings
        for key in ["thermal", "mechanical", "fluid"]:
            assert out.modality_embeddings[key].shape == (1, D_MODEL)

    def test_gate_values_present(self):
        net = CrossModalFusionNet()
        x, mask = _make_input()
        out = net(x, sensor_mask=mask)
        assert "cross_attn_gate" in out.gate_values
        assert "ffn_gate" in out.gate_values

    def test_no_mask_all_valid(self):
        """Without sensor_mask, all sensors should be treated as valid."""
        net = CrossModalFusionNet()
        x = torch.randn(1, 15)
        out = net(x)  # no mask
        assert out.fused_state_vector.shape == (1, FUSED_DIM)


# ══════════════════════════════════════════════════════════════════
#  2.  Sensor mask handling
# ══════════════════════════════════════════════════════════════════

class TestSensorMaskHandling:
    """Isolated sensors should be zeroed and attention adjusted."""

    def test_isolated_sensor_zeroed(self):
        """Isolated features should be zeroed before embedding."""
        net = CrossModalFusionNet()
        net.eval()
        x = torch.randn(1, 15)
        mask = torch.ones(1, 15, dtype=torch.bool)
        mask[0, 5] = False  # isolate CHT_2 (index 5 in modality order)

        with torch.no_grad():
            out = net(x, sensor_mask=mask)
        # Output should still be valid (not NaN)
        assert not torch.isnan(out.fused_state_vector).any()
        assert not torch.isinf(out.fused_state_vector).any()

    def test_all_isolated_produces_valid_output(self):
        """Even with all sensors isolated, network should not crash."""
        net = CrossModalFusionNet()
        x = torch.randn(1, 15)
        mask = torch.zeros(1, 15, dtype=torch.bool)  # all isolated

        with torch.no_grad():
            out = net(x, sensor_mask=mask)
        assert not torch.isnan(out.fused_state_vector).any()

    def test_mask_affects_output(self):
        """Different masks should produce different outputs."""
        net = CrossModalFusionNet()
        x = torch.randn(1, 15)
        mask_a = torch.ones(1, 15, dtype=torch.bool)
        mask_b = torch.ones(1, 15, dtype=torch.bool)
        mask_b[0, 9] = False  # isolate RPM

        with torch.no_grad():
            out_a = net(x, sensor_mask=mask_a)
            out_b = net(x, sensor_mask=mask_b)

        assert not torch.allclose(
            out_a.fused_state_vector, out_b.fused_state_vector
        ), "Mask should change output"


# ══════════════════════════════════════════════════════════════════
#  3.  Sub-module tests
# ══════════════════════════════════════════════════════════════════

class TestModalityEmbedding:
    def test_shape(self):
        emb = ModalityEmbedding(9, D_MODEL)
        x = torch.randn(4, 9)
        out = emb(x)
        assert out.shape == (4, D_MODEL)


class TestGatedResidualBlock:
    def test_gate_bounded(self):
        block = GatedResidualBlock(D_MODEL)
        x = torch.randn(2, D_MODEL)
        sub = torch.randn(2, D_MODEL)
        out, gate = block(x, sub)
        assert out.shape == (2, D_MODEL)
        assert gate.min() >= 0.0
        assert gate.max() <= 1.0


class TestCrossModalAttention:
    def test_output_shape(self):
        attn = CrossModalAttention(D_MODEL, N_HEADS)
        q = torch.randn(2, 1, D_MODEL)
        kv = torch.randn(2, 2, D_MODEL)
        out, weights = attn(q, kv)
        assert out.shape == (2, 1, D_MODEL)
        assert weights.shape == (2, N_HEADS, 1, 2)

    def test_masked_attention(self):
        """Masked kv token should get ~0 attention weight."""
        attn = CrossModalAttention(D_MODEL, N_HEADS)
        attn.eval()
        q = torch.randn(1, 1, D_MODEL)
        kv = torch.randn(1, 2, D_MODEL)
        mask = torch.tensor([[True, False]])  # mask out second token

        with torch.no_grad():
            _, weights = attn(q, kv, mask=mask)
        # Second kv token weight should be ~0
        assert weights[0, 0, 0, 1] < 0.01


class TestFFN:
    def test_shape(self):
        ffn = FFN(D_MODEL, 128)
        x = torch.randn(4, D_MODEL)
        out = ffn(x)
        assert out.shape == (4, D_MODEL)


# ══════════════════════════════════════════════════════════════════
#  4.  Physics-Constrained Loss
# ══════════════════════════════════════════════════════════════════

class TestPhysicsConstrainedLoss:
    """Validate loss function components and gradient flow."""

    def test_mse_loss_basic(self):
        criterion = PhysicsConstrainedLoss(base_loss_type="mse")
        pred = torch.randn(4, 32)
        target = torch.randn(4, 32)
        loss, comps = criterion(pred, target)
        assert loss.item() > 0
        assert "base_loss" in comps
        assert "total_loss" in comps

    def test_cosine_loss_basic(self):
        criterion = PhysicsConstrainedLoss(base_loss_type="cosine")
        pred = torch.randn(4, 32)
        target = torch.randn(4, 32)
        loss, comps = criterion(pred, target)
        assert 0.0 <= loss.item() <= 2.0

    def test_physics_penalty_active(self):
        """Penalty should increase when fuel flow rises without RPM/EGT rise."""
        criterion = PhysicsConstrainedLoss(physics_weight=1.0)
        pred = torch.randn(2, 32)
        target = torch.randn(2, 32)

        # Create inputs with high fuel flow, low RPM/EGT
        x_violating = torch.zeros(2, 15)
        x_violating[:, 12] = 50.0   # high fuel flow
        x_violating[:, 9] = 500.0   # low RPM
        x_violating[:, 4:8] = 200.0 # low EGT

        # Create normal inputs
        x_normal = torch.zeros(2, 15)
        x_normal[:, 12] = 15.0   # normal fuel flow
        x_normal[:, 9] = 2000.0  # normal RPM
        x_normal[:, 4:8] = 700.0 # normal EGT

        _, comps_v = criterion(pred, target, raw_inputs=x_violating)
        _, comps_n = criterion(pred, target, raw_inputs=x_normal)

        # Violating input should have higher physics penalty
        assert comps_v["physics_penalty"] >= comps_n["physics_penalty"]

    def test_physics_penalty_zero_when_no_violation(self):
        """No penalty when fuel flow and RPM/EGT are correlated."""
        criterion = PhysicsConstrainedLoss(physics_weight=1.0)
        pred = torch.randn(1, 32)
        target = torch.randn(1, 32)

        # All features at same relative level — no violation
        x = torch.ones(1, 15) * 0.5
        _, comps = criterion(pred, target, raw_inputs=x)
        assert comps["physics_penalty"] == pytest.approx(0.0, abs=1e-6)

    def test_gradient_flows(self):
        """Loss should be differentiable and gradients should propagate."""
        net = CrossModalFusionNet()
        criterion = PhysicsConstrainedLoss()
        x = torch.randn(2, 15, requires_grad=True)
        target = torch.randn(2, 32)

        out = net(x)
        loss, _ = criterion(out.fused_state_vector, target, raw_inputs=x)
        loss.backward()

        assert x.grad is not None
        assert not torch.isnan(x.grad).any()


# ══════════════════════════════════════════════════════════════════
#  5.  End-to-end training step
# ══════════════════════════════════════════════════════════════════

class TestEndToEnd:
    """Full forward + loss + backward cycle."""

    def test_training_step(self):
        net = CrossModalFusionNet()
        criterion = PhysicsConstrainedLoss()
        optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)

        x = torch.randn(8, 15)
        mask = torch.ones(8, 15, dtype=torch.bool)
        mask[0, 5] = False
        mask[3, 9] = False
        target = torch.randn(8, 32)

        # Forward
        out = net(x, sensor_mask=mask)
        loss, comps = criterion(out.fused_state_vector, target, raw_inputs=x)

        # Backward
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        assert not torch.isnan(loss)

    def test_loss_decreases(self):
        """Loss should decrease over a few gradient steps on fixed data."""
        torch.manual_seed(42)
        net = CrossModalFusionNet()
        criterion = PhysicsConstrainedLoss()
        optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)

        x = torch.randn(16, 15)
        target = torch.randn(16, 32)

        losses = []
        for _ in range(20):
            out = net(x)
            loss, _ = criterion(out.fused_state_vector, target, raw_inputs=x)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(loss.item())

        assert losses[-1] < losses[0], (
            f"Loss did not decrease: {losses[0]:.4f} → {losses[-1]:.4f}"
        )


# ══════════════════════════════════════════════════════════════════
#  6.  Latency
# ══════════════════════════════════════════════════════════════════

class TestLatency:
    """CPU forward-pass latency must be < 15 ms for batch_size = 1."""

    def test_latency_under_15ms(self):
        stats = benchmark_latency(n_runs=200)
        assert stats["p95_ms"] < 15.0, (
            f"P95 latency = {stats['p95_ms']:.2f} ms, "
            f"target < 15 ms.  Full stats: {stats}"
        )

    def test_mean_latency_under_10ms(self):
        stats = benchmark_latency(n_runs=200)
        assert stats["mean_ms"] < 10.0, (
            f"Mean latency = {stats['mean_ms']:.2f} ms, expected < 10 ms"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
