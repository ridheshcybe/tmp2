#!/usr/bin/env python3
"""
Unit tests for fusion_ml.export_models

Run:
    pytest -v fusion_ml/tests/test_export_models.py
"""

from __future__ import annotations

import json
import tempfile
import os
from pathlib import Path

import numpy as np
import pytest
import torch

from fusion_ml.cross_modal_fusion import CrossModalFusionNet, FUSED_DIM
from fusion_ml.anomaly_vae import AnomalyVAE
from fusion_ml.rul_predictor import TCNFeatureExtractor, SEQUENCE_LENGTH
from fusion_ml.export_models import (
    ModelExporter,
    OptimizedEngineInference,
    run_benchmark,
    PRODUCTION_DIR,
)


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _make_test_frame() -> dict:
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
    }


# ══════════════════════════════════════════════════════════════════
#  1.  TorchScript Export
# ══════════════════════════════════════════════════════════════════

class TestTorchScriptExport:
    """Verify TorchScript tracing and loading for all models."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.mkdtemp()
        self.exporter = ModelExporter(Path(self.tmpdir))

    def test_fusion_net_torchscript(self):
        model = CrossModalFusionNet()
        paths = self.exporter.export_fusion_net(model)
        assert "torchscript" in paths
        assert paths["torchscript"].exists()

        # Load and verify
        loaded = torch.jit.load(str(paths["torchscript"]))
        x = torch.randn(1, 15)
        mask = torch.ones(1, 15, dtype=torch.bool)
        out = loaded(x, mask)
        assert out.shape == (1, FUSED_DIM)

    def test_vae_torchscript(self):
        model = AnomalyVAE()
        paths = self.exporter.export_vae(model)
        assert "torchscript" in paths
        assert paths["torchscript"].exists()

        loaded = torch.jit.load(str(paths["torchscript"]))
        x = torch.randn(1, FUSED_DIM)
        out = loaded(x)
        assert len(out) == 3  # x_recon, mu, logvar
        assert out[0].shape == (1, FUSED_DIM)

    def test_tcn_torchscript(self):
        model = TCNFeatureExtractor()
        paths = self.exporter.export_tcn(model)
        assert "torchscript" in paths
        assert paths["torchscript"].exists()

        loaded = torch.jit.load(str(paths["torchscript"]))
        x = torch.randn(1, SEQUENCE_LENGTH, FUSED_DIM)
        out = loaded(x)
        assert out.shape[0] == 1
        assert out.shape[1] == 16  # TCN_EMBED_DIM

    def test_torchscript_deterministic(self):
        """TorchScript output should match eager output."""
        model = CrossModalFusionNet()
        model.eval()
        paths = self.exporter.export_fusion_net(model)

        loaded = torch.jit.load(str(paths["torchscript"]))
        x = torch.randn(2, 15)
        mask = torch.ones(2, 15, dtype=torch.bool)

        with torch.no_grad():
            eager_out = model(x, mask).fused_vector
            ts_out = loaded(x, mask)

        assert torch.allclose(eager_out, ts_out, atol=1e-5)


# ══════════════════════════════════════════════════════════════════
#  2.  ONNX Export
# ══════════════════════════════════════════════════════════════════

class TestONNXExport:
    """Verify ONNX export for all models."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.mkdtemp()
        self.exporter = ModelExporter(Path(self.tmpdir))

    def test_fusion_net_onnx(self):
        model = CrossModalFusionNet()
        paths = self.exporter.export_fusion_net(model)
        assert "onnx" in paths
        assert paths["onnx"].exists()
        assert paths["onnx"].stat().st_size > 0

    def test_vae_onnx(self):
        model = AnomalyVAE()
        paths = self.exporter.export_vae(model)
        assert "onnx" in paths
        assert paths["onnx"].exists()

    def test_tcn_onnx(self):
        model = TCNFeatureExtractor()
        paths = self.exporter.export_tcn(model)
        assert "onnx" in paths
        assert paths["onnx"].exists()


# ══════════════════════════════════════════════════════════════════
#  3.  Metadata
# ══════════════════════════════════════════════════════════════════

class TestMetadata:
    """Verify model metadata JSON is generated."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.mkdtemp()
        self.exporter = ModelExporter(Path(self.tmpdir))

    def test_metadata_created(self):
        self.exporter.export_all()
        meta_path = Path(self.tmpdir) / "model_metadata.json"
        assert meta_path.exists()

        with open(meta_path) as f:
            meta = json.load(f)
        assert "fusion_net" in meta
        assert "vae" in meta
        assert "tcn" in meta

    def test_metadata_correct_dims(self):
        self.exporter.export_all()
        meta_path = Path(self.tmpdir) / "model_metadata.json"
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["fusion_net"]["input_dim"] == FUSED_DIM
        assert meta["vae"]["latent_dim"] == 16
        assert meta["tcn"]["seq_len"] == SEQUENCE_LENGTH


# ══════════════════════════════════════════════════════════════════
#  4.  OptimizedEngineInference
# ══════════════════════════════════════════════════════════════════

class TestOptimizedInference:
    """Verify OptimizedEngineInference processes frames correctly."""

    def test_returns_enriched_dict(self):
        engine = OptimizedEngineInference()
        result = engine.process_frame(_make_test_frame())
        assert isinstance(result, dict)
        assert "fused_vector" in result
        assert "anomaly_score" in result
        assert "is_anomaly" in result

    def test_fused_vector_length(self):
        engine = OptimizedEngineInference()
        result = engine.process_frame(_make_test_frame())
        assert len(result["fused_vector"]) == FUSED_DIM

    def test_anomaly_score_range(self):
        engine = OptimizedEngineInference()
        result = engine.process_frame(_make_test_frame())
        assert 0.0 <= result["anomaly_score"] <= 100.0

    def test_isolation_flags_present(self):
        engine = OptimizedEngineInference()
        result = engine.process_frame(_make_test_frame())
        assert "sensor_isolation_flags" in result
        assert isinstance(result["sensor_isolation_flags"], list)

    def test_original_frame_preserved(self):
        engine = OptimizedEngineInference()
        frame = _make_test_frame()
        result = engine.process_frame(frame)
        assert "rpm" in result
        assert result["rpm"] == frame["rpm"]

    def test_multiple_frames(self):
        engine = OptimizedEngineInference()
        for _ in range(10):
            result = engine.process_frame(_make_test_frame())
            assert "fused_vector" in result


# ══════════════════════════════════════════════════════════════════
#  5.  Latency Benchmark
# ══════════════════════════════════════════════════════════════════

class TestLatencyBenchmark:
    """Verify benchmark produces valid results."""

    def test_benchmark_returns_stats(self):
        stats = run_benchmark(n_frames=50, warmup=10)
        assert "min_ms" in stats
        assert "median_ms" in stats
        assert "p95_ms" in stats
        assert "p99_ms" in stats

    def test_benchmark_p95_under_30ms(self):
        """End-to-end p95 must be < 30 ms."""
        stats = run_benchmark(n_frames=200, warmup=20)
        assert stats["p95_ms"] < 30.0, (
            f"p95 latency = {stats['p95_ms']:.2f} ms, target < 30 ms"
        )


# ══════════════════════════════════════════════════════════════════
#  Runner
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
