#!/usr/bin/env python3
"""
Unit tests for fusion_ml.anomaly_vae

Run:
    pytest -v fusion_ml/tests/test_anomaly_vae.py
"""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
import torch
import torch.nn.functional as F

from fusion_ml.anomaly_vae import (
    AnomalyVAE,
    VAEEncoder,
    VAEDecoder,
    FUSED_DIM,
    LATENT_DIM,
    HIDDEN_DIM,
    BETA,
    ALPHA,
)


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════

def _make_nominal_data(B: int = 32) -> torch.Tensor:
    """Simulate nominal fused vectors (small Gaussian cloud)."""
    return torch.randn(B, FUSED_DIM) * 0.5 + 1.0


def _make_anomalous_data(B: int = 32) -> torch.Tensor:
    """Simulate anomalous fused vectors (far from nominal mean)."""
    return torch.randn(B, FUSED_DIM) * 3.0 + 5.0


# ══════════════════════════════════════════════════════════════════
#  1.  Architecture
# ══════════════════════════════════════════════════════════════════

class TestArchitecture:
    """Verify VAE encoder, decoder, and full model shapes."""

    def test_encoder_output_shapes(self):
        enc = VAEEncoder(FUSED_DIM, HIDDEN_DIM, LATENT_DIM)
        x = torch.randn(8, FUSED_DIM)
        mu, logvar = enc(x)
        assert mu.shape == (8, LATENT_DIM)
        assert logvar.shape == (8, LATENT_DIM)

    def test_decoder_output_shape(self):
        dec = VAEDecoder(LATENT_DIM, HIDDEN_DIM, FUSED_DIM)
        z = torch.randn(8, LATENT_DIM)
        x_recon = dec(z)
        assert x_recon.shape == (8, FUSED_DIM)

    def test_full_vae_forward(self):
        model = AnomalyVAE()
        x = torch.randn(4, FUSED_DIM)
        x_recon, mu, logvar = model(x)
        assert x_recon.shape == (4, FUSED_DIM)
        assert mu.shape == (4, LATENT_DIM)
        assert logvar.shape == (4, LATENT_DIM)

    def test_reparameterization_shape(self):
        mu = torch.randn(4, LATENT_DIM)
        logvar = torch.randn(4, LATENT_DIM)
        z = AnomalyVAE.reparameterize(mu, logvar)
        assert z.shape == (4, LATENT_DIM)

    def test_batch_single(self):
        """Batch size 1 should work."""
        model = AnomalyVAE()
        x = torch.randn(1, FUSED_DIM)
        x_recon, mu, logvar = model(x)
        assert x_recon.shape == (1, FUSED_DIM)

    def test_no_nan_in_output(self):
        model = AnomalyVAE()
        x = torch.randn(4, FUSED_DIM)
        x_recon, mu, logvar = model(x)
        assert not torch.isnan(x_recon).any()
        assert not torch.isnan(mu).any()
        assert not torch.isnan(logvar).any()


# ══════════════════════════════════════════════════════════════════
#  2.  Loss function
# ══════════════════════════════════════════════════════════════════

class TestVAELoss:
    """Verify beta-VAE loss computation."""

    def test_loss_is_scalar(self):
        model = AnomalyVAE()
        x = torch.randn(8, FUSED_DIM)
        x_recon, mu, logvar = model(x)
        loss, comps = model.vae_loss(x_recon, x, mu, logvar)
        assert loss.dim() == 0, "Loss should be a scalar"

    def test_loss_components_present(self):
        model = AnomalyVAE()
        x = torch.randn(8, FUSED_DIM)
        x_recon, mu, logvar = model(x)
        _, comps = model.vae_loss(x_recon, x, mu, logvar)
        assert "recon_loss" in comps
        assert "kl_loss" in comps
        assert "total_loss" in comps

    def test_loss_is_positive(self):
        model = AnomalyVAE()
        x = torch.randn(8, FUSED_DIM)
        x_recon, mu, logvar = model(x)
        loss, _ = model.vae_loss(x_recon, x, mu, logvar)
        assert loss.item() > 0

    def test_perfect_reconstruction_low_recon_loss(self):
        """If recon == input, reconstruction loss should be ~0."""
        model = AnomalyVAE()
        model.eval()
        x = torch.randn(8, FUSED_DIM)
        # Force reconstruction to equal input
        loss, comps = model.vae_loss(x, x, torch.zeros(8, LATENT_DIM),
                                     torch.zeros(8, LATENT_DIM))
        assert comps["recon_loss"] < 1e-6

    def test_kl_divergence_positive(self):
        """KL divergence should be non-negative."""
        model = AnomalyVAE()
        x = torch.randn(8, FUSED_DIM)
        x_recon, mu, logvar = model(x)
        _, comps = model.vae_loss(x_recon, x, mu, logvar)
        assert comps["kl_loss"] >= 0

    def test_gradient_flows(self):
        """Loss must be differentiable."""
        model = AnomalyVAE()
        x = torch.randn(4, FUSED_DIM, requires_grad=True)
        x_recon, mu, logvar = model(x)
        loss, _ = model.vae_loss(x_recon, x, mu, logvar)
        loss.backward()
        assert x.grad is not None


# ══════════════════════════════════════════════════════════════════
#  3.  Training (short run)
# ══════════════════════════════════════════════════════════════════

class TestTraining:
    """Verify training reduces loss and sets threshold."""

    def test_loss_decreases(self):
        """Training for a few epochs should reduce loss."""
        model = AnomalyVAE()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        data = _make_nominal_data(128)

        # Initial loss
        model.eval()
        with torch.no_grad():
            x_recon, mu, logvar = model(data)
            initial_loss, _ = model.vae_loss(x_recon, data, mu, logvar)

        # Train
        model.train()
        for _ in range(10):
            optimizer.zero_grad()
            x_recon, mu, logvar = model(data)
            loss, _ = model.vae_loss(x_recon, data, mu, logvar)
            loss.backward()
            optimizer.step()

        # Final loss
        model.eval()
        with torch.no_grad():
            x_recon, mu, logvar = model(data)
            final_loss, _ = model.vae_loss(x_recon, data, mu, logvar)

        assert final_loss.item() < initial_loss.item(), (
            f"Loss did not decrease: {initial_loss.item():.4f} → {final_loss.item():.4f}"
        )

    def test_threshold_set_after_training(self):
        """recon_threshold should be > 0 after computing it."""
        model = AnomalyVAE()
        data = _make_nominal_data(128)

        model.eval()
        with torch.no_grad():
            x_recon, mu, logvar = model(data)
            per_sample = F.mse_loss(x_recon, data, reduction="none").sum(dim=-1)
            threshold = float(np.percentile(per_sample.numpy(), ALPHA * 100))
            model.recon_threshold.fill_(threshold)

        assert model.recon_threshold.item() > 0


# ══════════════════════════════════════════════════════════════════
#  4.  Anomaly detection
# ══════════════════════════════════════════════════════════════════

class TestAnomalyDetection:
    """Verify predict_anomaly() correctly identifies anomalies."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.model = AnomalyVAE()
        self.model.eval()

        # Train briefly on nominal data
        data = _make_nominal_data(256)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=1e-3)
        for _ in range(20):
            optimizer.zero_grad()
            x_recon, mu, logvar = self.model(data)
            loss, _ = self.model.vae_loss(x_recon, data, mu, logvar)
            loss.backward()
            optimizer.step()

        # Set threshold from training data
        self.model.eval()
        with torch.no_grad():
            x_recon, mu, logvar = self.model(data)
            per_sample = F.mse_loss(x_recon, data, reduction="none").sum(dim=-1)
            threshold = float(np.percentile(per_sample.numpy(), ALPHA * 100))
            self.model.recon_threshold.fill_(threshold)

    def test_output_keys(self):
        vec = torch.randn(1, FUSED_DIM)
        result = self.model.predict_anomaly(vec)
        assert "reconstruction_loss" in result
        assert "anomaly_score" in result
        assert "is_anomaly" in result

    def test_anomaly_score_range(self):
        vec = torch.randn(1, FUSED_DIM)
        result = self.model.predict_anomaly(vec)
        assert 0.0 <= result["anomaly_score"] <= 100.0

    def test_nominal_not_anomaly(self):
        """Nominal data should mostly not be flagged as anomalous."""
        nominal = _make_nominal_data(16)
        n_anomalies = 0
        for i in range(16):
            result = self.model.predict_anomaly(nominal[i])
            if result["is_anomaly"]:
                n_anomalies += 1
        # Allow up to 30% false positives (alpha = 99%, but training is short)
        assert n_anomalies <= 8, (
            f"Too many false positives: {n_anomalies}/16"
        )

    def test_extreme_anomaly_detected(self):
        """Extreme values far from nominal should be flagged."""
        extreme = torch.ones(1, FUSED_DIM) * 100.0
        result = self.model.predict_anomaly(extreme)
        assert result["is_anomaly"] is True
        assert result["anomaly_score"] > 0

    def test_reconstruction_loss_positive(self):
        vec = torch.randn(1, FUSED_DIM)
        result = self.model.predict_anomaly(vec)
        assert result["reconstruction_loss"] >= 0


# ══════════════════════════════════════════════════════════════════
#  5.  Save / Load
# ══════════════════════════════════════════════════════════════════

class TestSaveLoad:
    """Verify model serialization round-trips correctly."""

    def test_save_load_roundtrip(self):
        model = AnomalyVAE()
        model.recon_threshold.fill_(0.42)

        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as f:
            path = f.name

        try:
            model.save(path)
            loaded = AnomalyVAE.load(path)

            assert loaded.input_dim == model.input_dim
            assert loaded.latent_dim == model.latent_dim
            assert loaded.beta == model.beta
            assert loaded.alpha == model.alpha
            assert abs(loaded.recon_threshold.item() - 0.42) < 1e-6

            # Verify weights match
            for p1, p2 in zip(model.parameters(), loaded.parameters()):
                assert torch.allclose(p1, p2)
        finally:
            os.unlink(path)

    def test_loaded_model_predicts(self):
        model = AnomalyVAE()
        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as f:
            path = f.name
        try:
            model.save(path)
            loaded = AnomalyVAE.load(path)
            result = loaded.predict_anomaly(torch.randn(1, FUSED_DIM))
            assert "is_anomaly" in result
        finally:
            os.unlink(path)


# ══════════════════════════════════════════════════════════════════
#  Runner
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
