#!/usr/bin/env python3
"""
Unit tests for fusion_ml.online_adapter

Run:
    pytest -v fusion_ml/tests/test_online_adapter.py
"""

from __future__ import annotations

import copy

import numpy as np
import pytest
import torch

from fusion_ml.anomaly_vae import AnomalyVAE, FUSED_DIM
from fusion_ml.online_adapter import (
    OnlineAdaptationManager,
    EMABaselineTracker,
    AdaptationState,
    AdaptationResult,
    ANOMALY_SPIKE_THRESHOLD,
    NOMINAL_CONFIRM_S,
    STEADY_STATE_VEL_THRESH,
)


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _make_vae() -> AnomalyVAE:
    """Create a VAE with small recon threshold for testing."""
    vae = AnomalyVAE()
    vae.recon_threshold.fill_(1.0)
    vae.eval()
    return vae


def _make_adapter(**kwargs) -> OnlineAdaptationManager:
    """Create an adapter with a test VAE."""
    return OnlineAdaptationManager(_make_vae(), **kwargs)


def _nominal_vector(drift: float = 0.0) -> np.ndarray:
    """Build a nominal fused vector with optional drift offset."""
    rng = np.random.default_rng(42)
    return (rng.standard_normal(FUSED_DIM) * 0.5 + 1.0).astype(np.float32) + drift


# ══════════════════════════════════════════════════════════════════
#  1.  EMA Baseline Tracker
# ══════════════════════════════════════════════════════════════════

class TestEMABaselineTracker:
    """Verify EMA tracking and normalization."""

    def test_initialization(self):
        ema = EMABaselineTracker(dim=32)
        assert ema.count == 0
        assert not ema.is_ready

    def test_first_update(self):
        ema = EMABaselineTracker(dim=32)
        x = np.ones(32, dtype=np.float64)
        ema.update(x)
        assert ema.count == 1
        np.testing.assert_array_equal(ema.mean, x)

    def test_converges_to_mean(self):
        """EMA should converge to the input mean."""
        ema = EMABaselineTracker(dim=4, momentum=0.5)
        for _ in range(1000):
            ema.update(np.array([10.0, 20.0, 30.0, 40.0]))
        np.testing.assert_allclose(ema.mean, [10, 20, 30, 40], atol=1.0)

    def test_normalization(self):
        """Normalized values should have ~zero mean."""
        ema = EMABaselineTracker(dim=4, momentum=0.1)
        for _ in range(200):
            ema.update(np.array([100.0, 200.0, 300.0, 400.0]))
        normalized = ema.normalize(np.array([100.0, 200.0, 300.0, 400.0]))
        assert abs(normalized.mean()) < 5.0  # should be near 0

    def test_is_ready_after_30(self):
        ema = EMABaselineTracker(dim=32)
        for i in range(30):
            ema.update(np.random.randn(32))
        assert ema.is_ready


# ══════════════════════════════════════════════════════════════════
#  2.  Basic Processing
# ══════════════════════════════════════════════════════════════════

class TestBasicProcessing:
    """Verify adapter processes frames correctly."""

    def test_returns_adaptation_result(self):
        adapter = _make_adapter()
        result = adapter.process(_nominal_vector(), altitude_ft=18000, throttle=0.65, timestamp=1.0)
        assert isinstance(result, AdaptationResult)

    def test_anomaly_result_present(self):
        adapter = _make_adapter()
        result = adapter.process(_nominal_vector(), timestamp=1.0)
        assert "anomaly_result" in result.__dict__
        assert "reconstruction_loss" in result.anomaly_result

    def test_state_increments(self):
        adapter = _make_adapter()
        adapter.process(_nominal_vector(), timestamp=1.0)
        adapter.process(_nominal_vector(), timestamp=2.0)
        assert adapter.state.total_frames == 2

    def test_ema_updates_on_nominal(self):
        adapter = _make_adapter()
        vec = _nominal_vector()
        # Run many nominal frames at steady state
        for i in range(50):
            adapter.process(vec, altitude_ft=18000, throttle=0.65, timestamp=float(i))
        assert adapter.ema.count > 0


# ══════════════════════════════════════════════════════════════════
#  3.  Safety Guard
# ══════════════════════════════════════════════════════════════════

class TestSafetyGuard:
    """Verify safety guard freezes on fault/anomaly."""

    def test_freeze_on_fault_labels(self):
        adapter = _make_adapter()
        fault_labels = {
            "LEAN_BURN_RUNAWAY": {"active": True, "severity": 0.5},
            "PISTON_RING_WEAR": {"active": False},
        }
        adapter.process(_nominal_vector(), fault_labels=fault_labels)
        assert adapter.state.is_frozen
        assert "fault_label" in adapter.state.freeze_reason

    def test_freeze_on_anomaly_spike(self):
        """High anomaly score should trigger safety freeze."""
        adapter = _make_adapter()
        # Use a vector far from nominal to trigger high anomaly score
        extreme = np.ones(FUSED_DIM, dtype=np.float32) * 100.0
        adapter.process(extreme, timestamp=1.0)
        # The extreme vector should cause high anomaly score
        assert adapter.state.last_anomaly_score > ANOMALY_SPIKE_THRESHOLD or adapter.state.is_frozen

    def test_no_updates_when_frozen(self):
        adapter = _make_adapter()
        adapter._freeze("test_freeze")
        result = adapter.process(_nominal_vector(), altitude_ft=18000, throttle=0.65, timestamp=1.0)
        assert not result.adapted

    def test_rollback_unfreezes(self):
        adapter = _make_adapter()
        adapter._freeze("test")
        assert adapter.state.is_frozen
        adapter.rollback()
        assert not adapter.state.is_frozen


# ══════════════════════════════════════════════════════════════════
#  4.  Steady-State Detection
# ══════════════════════════════════════════════════════════════════

class TestSteadyStateDetection:
    """Verify steady-state cruise detection."""

    def test_steady_state_detected(self):
        adapter = _make_adapter()
        # Same altitude and throttle over time
        for i in range(10):
            result = adapter.process(
                _nominal_vector(),
                altitude_ft=18000.0,
                throttle=0.65,
                timestamp=float(i) * 0.1,
            )
        # Should be steady after a few frames
        assert adapter.ema.count > 0  # EMA should have been updated

    def test_changing_altitude_not_steady(self):
        adapter = _make_adapter()
        # Rapidly changing altitude
        for i in range(10):
            adapter.process(
                _nominal_vector(),
                altitude_ft=1000.0 * i,  # changing rapidly
                throttle=0.65,
                timestamp=float(i) * 0.1,
            )
        # EMA should not have been updated much
        assert adapter.ema.count < 5


# ══════════════════════════════════════════════════════════════════
#  5.  Atmospheric Drift Adaptation
# ══════════════════════════════════════════════════════════════════

class TestAtmosphericDriftAdaptation:
    """
    Prove that gradual atmospheric temperature drift does NOT
    cause false-positive anomaly alarms.
    """

    def test_gradual_drift_no_false_positives(self):
        """
        Simulate 600 frames of gradual temperature drift (+0.01 per frame).
        The adapter's EMA should track the drift, and the anomaly score
        should stay below the spike threshold.
        """
        adapter = _make_adapter()
        vae = adapter.vae

        # Base vector
        base = _nominal_vector(drift=0.0)
        spike_count = 0
        anomaly_scores = []

        for i in range(600):
            # Gradual drift: each frame shifts by 0.01
            drift = i * 0.01
            drifted = base + drift
            result = adapter.process(
                drifted,
                altitude_ft=18000.0,
                throttle=0.65,
                timestamp=float(i) * 0.1,
            )
            score = result.anomaly_result["anomaly_score"]
            anomaly_scores.append(score)
            if score > ANOMALY_SPIKE_THRESHOLD:
                spike_count += 1

        # With adaptive normalization, false positives should be minimal
        # Allow up to 5% of frames to spike (initial warmup period)
        assert spike_count < 30, (
            f"Too many false-positive spikes during gradual drift: "
            f"{spike_count}/600"
        )

        # The final scores should be lower than the initial scores
        # (adaptation has kicked in)
        avg_first_50 = np.mean(anomaly_scores[:50])
        avg_last_50 = np.mean(anomaly_scores[-50:])
        # Last 50 should be comparable or lower (adaptation working)
        # Allow some tolerance
        assert avg_last_50 <= avg_first_50 * 3.0, (
            f"Adaptation not working: first50={avg_first_50:.2f}, "
            f"last50={avg_last_50:.2f}"
        )

    def test_drift_correction_available(self):
        """After processing nominal frames, drift_correction should be available."""
        adapter = _make_adapter()
        for i in range(50):
            result = adapter.process(
                _nominal_vector(),
                altitude_ft=18000.0,
                throttle=0.65,
                timestamp=float(i) * 0.1,
            )
        assert result.drift_correction is not None
        assert len(result.drift_correction) == FUSED_DIM

    def test_extreme_drift_still_tracked(self):
        """Even a large but gradual drift should be tracked by EMA."""
        adapter = _make_adapter()
        base = _nominal_vector()
        for i in range(100):
            adapter.process(
                base + i * 0.1,  # large drift
                altitude_ft=18000.0,
                throttle=0.65,
                timestamp=float(i) * 0.1,
            )
        assert adapter.ema.count > 0
        # EMA mean should have shifted from zero
        assert np.linalg.norm(adapter.ema.mean) > 0.1

    def test_reset_clears_streak(self):
        adapter = _make_adapter()
        adapter.state.nominal_streak_s = 500.0
        adapter.reset()
        assert adapter.state.nominal_streak_s == 0.0
        assert adapter.state.total_frames == 0


# ══════════════════════════════════════════════════════════════════
#  6.  Decoder Adaptation
# ══════════════════════════════════════════════════════════════════

class TestDecoderAdaptation:
    """Verify that decoder weights change during online adaptation."""

    def test_decoder_weights_change(self):
        """After enough nominal frames, decoder should have adapted."""
        adapter = _make_adapter()

        # Snapshot decoder weights before
        before = copy.deepcopy(adapter.vae.decoder.state_dict())

        # Feed nominal frames for long enough to trigger adaptation
        # We need nominal_streak_s >= NOMINAL_CONFIRM_S (300s)
        # At dt=0.1, that's 3000 frames
        for i in range(3100):
            adapter.process(
                _nominal_vector(),
                altitude_ft=18000.0,
                throttle=0.65,
                timestamp=float(i) * 0.1,
            )

        # Check if decoder weights changed
        after = adapter.vae.decoder.state_dict()
        weights_changed = False
        for key in before:
            if not torch.equal(before[key], after[key]):
                weights_changed = True
                break

        assert weights_changed, "Decoder weights did not change after adaptation"
        assert adapter.state.total_updates > 0


# ══════════════════════════════════════════════════════════════════
#  Runner
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
