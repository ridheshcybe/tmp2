#!/usr/bin/env python3
"""
Unit tests for fusion_ml.rul_predictor

Run:
    pytest -v fusion_ml/tests/test_rul_predictor.py
"""

from __future__ import annotations

import tempfile
import os

import numpy as np
import pytest
import torch

from fusion_ml.rul_predictor import (
    RULPredictor,
    CausalConv1d,
    TCNBlock,
    TCNFeatureExtractor,
    nasa_phm_score,
    SEQUENCE_LENGTH,
    TCN_EMBED_DIM,
    RTB_WARNING_MIN,
    RTB_CRITICAL_MIN,
    FUSED_DIM,
)

try:
    from xgboost import XGBRegressor
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _make_sequence(B: int = 4, T: int = 300, D: int = 32) -> np.ndarray:
    """Build a random sequence of fused vectors."""
    return np.random.randn(B, T, D).astype(np.float32)


def _make_single_sequence(T: int = 300, D: int = 32) -> np.ndarray:
    """Build a single (T, D) sequence."""
    return np.random.randn(T, D).astype(np.float32)


# ══════════════════════════════════════════════════════════════════
#  1.  TCN Architecture
# ══════════════════════════════════════════════════════════════════

class TestTCNArchitecture:
    """Verify TCN blocks and feature extractor shapes."""

    def test_causal_conv_output_length(self):
        """Causal conv must not change temporal length."""
        conv = CausalConv1d(32, 32, kernel_size=3, dilation=1)
        x = torch.randn(2, 32, 300)
        out = conv(x)
        assert out.shape == (2, 32, 300)

    def test_causal_conv_preserves_length_dilated(self):
        """Dilated causal conv must also preserve length."""
        conv = CausalConv1d(32, 32, kernel_size=3, dilation=4)
        x = torch.randn(2, 32, 300)
        out = conv(x)
        assert out.shape == (2, 32, 300)

    def test_tcn_block_output_shape(self):
        block = TCNBlock(32, kernel_size=3, dilation=1)
        x = torch.randn(2, 32, 300)
        out = block(x)
        assert out.shape == (2, 32, 300)

    def test_tcn_block_residual(self):
        """Output should differ from input (not identity)."""
        block = TCNBlock(32, kernel_size=3, dilation=1)
        x = torch.randn(2, 32, 300)
        out = block(x)
        assert not torch.allclose(x, out)

    def test_tcn_extractor_output_shape(self):
        tcn = TCNFeatureExtractor()
        x = torch.randn(4, 300, FUSED_DIM)
        out = tcn(x)
        assert out.shape == (4, TCN_EMBED_DIM)

    def test_tcn_extractor_batch1(self):
        tcn = TCNFeatureExtractor()
        x = torch.randn(1, 300, FUSED_DIM)
        out = tcn(x)
        assert out.shape == (1, TCN_EMBED_DIM)

    def test_tcn_no_nan(self):
        tcn = TCNFeatureExtractor()
        x = torch.randn(4, 300, FUSED_DIM)
        out = tcn(x)
        assert not torch.isnan(out).any()

    def test_tcn_gradient_flows(self):
        tcn = TCNFeatureExtractor()
        x = torch.randn(2, 300, FUSED_DIM, requires_grad=True)
        out = tcn(x)
        loss = out.sum()
        loss.backward()
        assert x.grad is not None


# ══════════════════════════════════════════════════════════════════
#  2.  Sequence Building
# ══════════════════════════════════════════════════════════════════

class TestSequenceBuilding:
    """Verify sliding window sequence construction."""

    def test_output_shapes(self):
        pred = RULPredictor(sequence_length=300)
        N = 500
        fused = np.random.randn(N, 32).astype(np.float32)
        rul = np.random.uniform(0, 60, N).astype(np.float32)
        cht = np.random.uniform(150, 250, N).astype(np.float32)
        egt = np.random.uniform(10, 50, N).astype(np.float32)
        vib = np.random.uniform(1.0, 2.0, N).astype(np.float32)

        X_seq, X_base, y_rul = pred.build_sequences(fused, rul, cht, egt, vib)

        expected_M = N - 299  # 500 - (300 - 1) = 201
        assert X_seq.shape == (expected_M, 300, 32)
        assert X_base.shape == (expected_M, 3)
        assert y_rul.shape == (expected_M,)

    def test_sequence_window_integrity(self):
        """The last timestep of each window should match the label."""
        pred = RULPredictor(sequence_length=10)
        # 50 timesteps → 50 − 10 + 1 = 41 windows of length 10.
        fused = np.arange(500).reshape(50, 10).astype(np.float32)
        rul = np.arange(50).astype(np.float32)
        cht = np.ones(50) * 180.0
        egt = np.ones(50) * 20.0
        vib = np.ones(50) * 1.5

        X_seq, X_base, y_rul = pred.build_sequences(fused, rul, cht, egt, vib)
        # Last window: indices [40..49], so y should be rul[49] = 49
        assert y_rul.shape == (41,)
        assert y_rul[-1] == 49.0
        # The window must end at the labelled timestep
        np.testing.assert_array_equal(X_seq[-1], fused[40:50])
        # baseline features at the window end: [cht_max, egt_spread, vib]
        np.testing.assert_array_equal(X_base[-1], [180.0, 20.0, 1.5])


# ══════════════════════════════════════════════════════════════════
#  3.  TCN Feature Extraction
# ══════════════════════════════════════════════════════════════════

class TestTCNFeatureExtraction:
    """Verify TCN embedding extraction from sequences."""

    def test_extraction_shape(self):
        pred = RULPredictor()
        seq = _make_sequence(B=8, T=300, D=32)
        embs = pred.extract_tcn_features(seq)
        assert embs.shape == (8, TCN_EMBED_DIM)

    def test_extraction_deterministic(self):
        """Same input should produce same embedding (eval mode)."""
        pred = RULPredictor()
        seq = _make_sequence(B=4, T=300, D=32)
        emb1 = pred.extract_tcn_features(seq)
        emb2 = pred.extract_tcn_features(seq)
        np.testing.assert_array_equal(emb1, emb2)

    def test_different_inputs_different_embeddings(self):
        pred = RULPredictor()
        seq1 = _make_sequence(B=2, T=300, D=32)
        seq2 = _make_sequence(B=2, T=300, D=32)
        emb1 = pred.extract_tcn_features(seq1)
        emb2 = pred.extract_tcn_features(seq2)
        assert not np.allclose(emb1, emb2)


# ══════════════════════════════════════════════════════════════════
#  4.  NASA PHM Scoring Function
# ══════════════════════════════════════════════════════════════════

class TestNASAPHMScore:
    """Verify the NASA PHM scoring function."""

    def test_perfect_prediction(self):
        """Perfect predictions should score 0."""
        y = np.array([10.0, 20.0, 30.0])
        score = nasa_phm_score(y, y)
        assert abs(score) < 1e-6

    def test_late_prediction_penalized(self):
        """Late prediction (overestimating RUL) should have higher score."""
        y_true = np.array([20.0, 30.0])
        y_early = np.array([18.0, 28.0])   # early by 2
        y_late = np.array([22.0, 32.0])    # late by 2
        score_early = nasa_phm_score(y_true, y_early)
        score_late = nasa_phm_score(y_true, y_late)
        assert score_late > score_early

    def test_score_non_negative(self):
        """Score should be non-negative."""
        y_true = np.array([10.0, 20.0, 30.0])
        y_pred = np.array([15.0, 25.0, 35.0])
        score = nasa_phm_score(y_true, y_pred)
        assert score >= 0


# ══════════════════════════════════════════════════════════════════
#  5.  RTB Margin Evaluation
# ══════════════════════════════════════════════════════════════════

class TestRTBMargin:
    """Verify Return-to-Base warning and critical triggers."""

    def test_rtb_warning_at_30min(self):
        """RUL ≤ 30 min should trigger RTB_WARNING."""
        pred = RULPredictor()
        # Mock the XGBoost model
        pred.xgb = type("MockXGB", (), {
            "predict": lambda self, X: np.array([25.0]),
        })()
        pred._xgb_mean = np.zeros(19)
        pred._xgb_std = np.ones(19)

        seq = _make_single_sequence(300, 32)
        result = pred.predict_rul(seq)
        assert result["rtb_warning"] is True

    def test_rtb_critical_at_10min(self):
        """RUL ≤ 10 min should trigger RTB_CRITICAL."""
        pred = RULPredictor()
        pred.xgb = type("MockXGB", (), {
            "predict": lambda self, X: np.array([8.0]),
        })()
        pred._xgb_mean = np.zeros(19)
        pred._xgb_std = np.ones(19)

        seq = _make_single_sequence(300, 32)
        result = pred.predict_rul(seq)
        assert result["rtb_critical"] is True
        assert result["rtb_warning"] is True

    def test_no_rtb_above_30min(self):
        """RUL > 30 min should not trigger either warning."""
        pred = RULPredictor()
        pred.xgb = type("MockXGB", (), {
            "predict": lambda self, X: np.array([45.0]),
        })()
        pred._xgb_mean = np.zeros(19)
        pred._xgb_std = np.ones(19)

        seq = _make_single_sequence(300, 32)
        result = pred.predict_rul(seq)
        assert result["rtb_warning"] is False
        assert result["rtb_critical"] is False


# ══════════════════════════════════════════════════════════════════
#  6.  XGBoost Integration
# ══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_XGBOOST, reason="xgboost not installed")
class TestXGBoostIntegration:
    """Verify XGBoost training and prediction."""

    def test_xgb_can_fit(self):
        """XGBoost should fit on synthetic data."""
        X = np.random.randn(100, 19).astype(np.float32)
        y = np.random.uniform(0, 60, 100).astype(np.float32)

        model = XGBRegressor(n_estimators=10, max_depth=3, verbosity=0)
        model.fit(X, y)
        preds = model.predict(X)
        assert preds.shape == (100,)

    def test_xgb_save_load(self):
        """XGBoost model should save and load correctly."""
        X = np.random.randn(50, 19).astype(np.float32)
        y = np.random.uniform(0, 60, 50).astype(np.float32)

        model = XGBRegressor(n_estimators=10, max_depth=3, verbosity=0)
        model.fit(X, y)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            model.save_model(path)
            loaded = XGBRegressor()
            loaded.load_model(path)
            preds = loaded.predict(X[:5])
            assert preds.shape == (5,)
        finally:
            os.unlink(path)


# ══════════════════════════════════════════════════════════════════
#  7.  Save / Load
# ══════════════════════════════════════════════════════════════════

class TestSaveLoad:
    """Verify RULPredictor serialization."""

    def test_tcn_save_load(self):
        """TCN weights should round-trip through save/load."""
        pred = RULPredictor()

        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as f:
            tcn_path = f.name

        try:
            # Save just TCN
            torch.save({"tcn_state": pred.tcn.state_dict(), "seq_len": 300}, tcn_path)

            # Load into fresh predictor
            pred2 = RULPredictor()
            ckpt = torch.load(tcn_path, map_location="cpu", weights_only=False)
            pred2.tcn.load_state_dict(ckpt["tcn_state"])

            # Verify weights match
            for p1, p2 in zip(pred.tcn.parameters(), pred2.tcn.parameters()):
                assert torch.allclose(p1, p2)
        finally:
            os.unlink(tcn_path)


# ══════════════════════════════════════════════════════════════════
#  Runner
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
