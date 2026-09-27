#!/usr/bin/env python3
"""
Variational Autoencoder — Anomaly Detection
=============================================
beta-VAE trained on nominal fused vectors from the cross-modal fusion
pipeline.  Detects anomalous engine states by reconstruction error.

Architecture
------------
* Encoder: 32 → 64 → BN → LeakyReLU → 32 → (mu: 16, logvar: 16)
* Reparameterization: z = mu + eps · exp(0.5 · logvar)
* Decoder: 16 → 32 → BN → LeakyReLU → 32 → 64 → 32

Loss: MSE reconstruction + β · KL divergence  (β = 0.01)

Usage
-----
    # Training
    python -m fusion_ml.anomaly_vae train

    # Inference
    python -m fusion_ml.anomaly_vae predict --vector "0.1,0.2,..."

    # In Python
    from fusion_ml.anomaly_vae import AnomalyVAE
    vae = AnomalyVAE.load("fusion_ml/models/vae_nominal.pt")
    result = vae.predict_anomaly(fused_vector_tensor)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset


# ══════════════════════════════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════════════════════════════

FUSED_DIM = 32        # input/output dimension
LATENT_DIM = 16       # latent space dimension
HIDDEN_DIM = 64       # encoder/decoder hidden dimension
BETA = 0.01           # KL divergence weight (beta-VAE)
LEARNING_RATE = 1e-3
BATCH_SIZE = 64
EPOCHS = 25
ALPHA = 0.99          # reconstruction error threshold percentile

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "vae_nominal.pt"
NOMINAL_CSV = Path(__file__).resolve().parent.parent / "data" / "flight_dataset_nominal.csv"


# ══════════════════════════════════════════════════════════════════
#  VAE Architecture
# ══════════════════════════════════════════════════════════════════

class SingletonSafeBatchNorm1d(nn.BatchNorm1d):
    """
    ``BatchNorm1d`` that tolerates a batch of one sample.

    In training mode BatchNorm derives its statistics from the batch,
    which is impossible for a single sample — PyTorch raises
    ``Expected more than 1 value per channel when training``.  Real-time
    paths such as ``online_adapter._adapt_decoder`` forward one fused
    vector at a time with the module in train mode, so for that case we
    fall back to the accumulated running statistics instead.

    Weights and buffers are identical to ``nn.BatchNorm1d``, so existing
    checkpoints remain loadable and behaviour is unchanged for batches
    of two or more (and for any batch in eval mode).

    Assumes ``track_running_stats=True`` (the default used by this VAE).
    The parent's implementation is re-stated explicitly because
    TorchScript cannot resolve ``super().forward(...)`` inside a subclass.
    """

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.training and self.track_running_stats:
            if self.num_batches_tracked is not None:
                self.num_batches_tracked.add_(1)

        if self.momentum is None:
            # Cumulative moving average
            if self.num_batches_tracked is not None:
                momentum = 1.0 / float(self.num_batches_tracked.item())
            else:
                momentum = 0.0
        else:
            momentum = self.momentum

        # A singleton batch cannot provide batch statistics — reuse the
        # running statistics for that step instead of raising.
        singleton = self.training and x.dim() == 2 and x.size(0) == 1
        use_batch_stats = self.training and not singleton

        return F.batch_norm(
            x,
            self.running_mean,
            self.running_var,
            self.weight,
            self.bias,
            use_batch_stats,
            momentum,
            self.eps,
        )


class VAEEncoder(nn.Module):
    """
    Encoder: Linear(32→64) → BatchNorm → LeakyReLU → Linear(64→32)
    → split into mu(16) and logvar(16).
    """

    def __init__(
        self,
        input_dim: int = FUSED_DIM,
        hidden_dim: int = HIDDEN_DIM,
        latent_dim: int = LATENT_DIM,
    ) -> None:
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            SingletonSafeBatchNorm1d(hidden_dim),
            nn.LeakyReLU(0.2),
            nn.Linear(hidden_dim, input_dim),
        )
        self.mu_proj = nn.Linear(input_dim, latent_dim)
        self.logvar_proj = nn.Linear(input_dim, latent_dim)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        h = self.shared(x)
        mu = self.mu_proj(h)
        logvar = self.logvar_proj(h)
        return mu, logvar


class VAEDecoder(nn.Module):
    """
    Decoder: Linear(16→32) → BatchNorm → LeakyReLU → Linear(32→64)
    → Linear(64→32).
    """

    def __init__(
        self,
        latent_dim: int = LATENT_DIM,
        hidden_dim: int = HIDDEN_DIM,
        output_dim: int = FUSED_DIM,
    ) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(latent_dim, output_dim),
            SingletonSafeBatchNorm1d(output_dim),
            nn.LeakyReLU(0.2),
            nn.Linear(output_dim, hidden_dim),
            nn.Linear(hidden_dim, output_dim),
        )

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.net(z)


class AnomalyVAE(nn.Module):
    """
    Variational Autoencoder for engine anomaly detection.

    Parameters
    ----------
    input_dim : int
        Dimension of fused_state_vector (default 32).
    latent_dim : int
        Latent space dimension (default 16).
    hidden_dim : int
        Encoder/decoder hidden dimension (default 64).
    beta : float
        KL divergence weight (default 0.01).
    alpha : float
        Reconstruction error threshold percentile (default 0.99).
    """

    def __init__(
        self,
        input_dim: int = FUSED_DIM,
        latent_dim: int = LATENT_DIM,
        hidden_dim: int = HIDDEN_DIM,
        beta: float = BETA,
        alpha: float = ALPHA,
    ) -> None:
        super().__init__()
        self.input_dim = input_dim
        self.latent_dim = latent_dim
        self.beta = beta
        self.alpha = alpha

        self.encoder = VAEEncoder(input_dim, hidden_dim, latent_dim)
        self.decoder = VAEDecoder(latent_dim, hidden_dim, input_dim)

        # Threshold (set during training)
        self.register_buffer(
            "recon_threshold",
            torch.tensor(0.0),
        )

    # ── Reparameterization trick ──

    @staticmethod
    def reparameterize(mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        """
        z = mu + eps · exp(0.5 · logvar)
        """
        if mu.requires_grad or logvar.requires_grad:
            eps = torch.randn_like(mu)
        else:
            eps = torch.randn_like(mu)
        return mu + eps * torch.exp(0.5 * logvar)

    # ── Forward pass ──

    def forward(
        self, x: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Returns
        -------
        x_recon : (B, input_dim) — reconstructed input
        mu : (B, latent_dim)
        logvar : (B, latent_dim)
        """
        mu, logvar = self.encoder(x)
        z = self.reparameterize(mu, logvar)
        x_recon = self.decoder(z)
        return x_recon, mu, logvar

    # ── Loss ──

    def vae_loss(
        self, x_recon: torch.Tensor, x: torch.Tensor,
        mu: torch.Tensor, logvar: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """
        beta-VAE loss: MSE reconstruction + β · KL divergence.
        """
        # MSE reconstruction loss (per-sample, then mean)
        recon_loss = F.mse_loss(x_recon, x, reduction="none").sum(dim=-1).mean()

        # KL divergence: -0.5 * Σ(1 + log(σ²) - μ² - σ²)
        kl_loss = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp(), dim=-1).mean()

        total = recon_loss + self.beta * kl_loss

        return total, {
            "recon_loss": recon_loss.item(),
            "kl_loss": kl_loss.item(),
            "total_loss": total.item(),
        }

    # ── Anomaly inference ──

    def predict_anomaly(
        self,
        fused_vector: torch.Tensor,
    ) -> Dict[str, Any]:
        """
        Predict whether a fused vector is anomalous.

        Parameters
        ----------
        fused_vector : torch.Tensor
            (B, 32) or (32,) — fused latent from CrossModalFusionNet.

        Returns
        -------
        dict with keys:
            ``reconstruction_loss``: float
            ``anomaly_score``: float (0–100)
            ``is_anomaly``: bool
        """
        self.eval()
        with torch.no_grad():
            if fused_vector.dim() == 1:
                fused_vector = fused_vector.unsqueeze(0)

            x_recon, mu, logvar = self.forward(fused_vector)

            # Per-sample reconstruction loss
            recon_loss = F.mse_loss(x_recon, fused_vector, reduction="none").sum(dim=-1)

            loss_val = recon_loss.item() if recon_loss.numel() == 1 else recon_loss.mean().item()

            # Anomaly score: how far above threshold (0 = normal, 100 = extreme)
            threshold = self.recon_threshold.item()
            if threshold > 0:
                score = min(100.0, max(0.0, (loss_val / threshold - 1.0) * 100.0))
            else:
                score = 0.0

            is_anomaly = loss_val > threshold

            return {
                "reconstruction_loss": round(loss_val, 6),
                "anomaly_score": round(score, 2),
                "is_anomaly": bool(is_anomaly),
            }

    # ── Save / Load ──

    def save(self, path: Optional[str | Path] = None) -> Path:
        """Save model weights and metadata."""
        path = Path(path) if path else MODEL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "model_state": self.state_dict(),
            "input_dim": self.input_dim,
            "latent_dim": self.latent_dim,
            "beta": self.beta,
            "alpha": self.alpha,
            "recon_threshold": self.recon_threshold.item(),
        }, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> "AnomalyVAE":
        """Load model from checkpoint."""
        path = Path(path)
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        model = cls(
            input_dim=checkpoint["input_dim"],
            latent_dim=checkpoint["latent_dim"],
            beta=checkpoint["beta"],
            alpha=checkpoint["alpha"],
        )
        model.load_state_dict(checkpoint["model_state"])
        model.recon_threshold.fill_(checkpoint["recon_threshold"])
        model.eval()
        return model


# ══════════════════════════════════════════════════════════════════
#  Data loading
# ══════════════════════════════════════════════════════════════════

def _load_nominal_fused_vectors(
    max_samples: int = 10_000,
) -> torch.Tensor:
    """
    Load nominal CSV and generate fused vectors using the pipeline.

    Returns
    -------
    torch.Tensor of shape (N, 32)
    """
    from fusion_ml.fusion_pipeline import EngineFusionPipeline

    if not NOMINAL_CSV.exists():
        raise FileNotFoundError(
            f"Nominal dataset not found: {NOMINAL_CSV}\n"
            "  Generate with: python -m simulator.generate_datasets"
        )

    print(f"  Loading nominal data from {NOMINAL_CSV}…")
    df = pd.read_csv(NOMINAL_CSV)
    print(f"  Loaded {len(df):,} rows")

    pipeline = EngineFusionPipeline()
    fused_vectors: List[np.ndarray] = []

    # Sample evenly if too many rows
    if len(df) > max_samples:
        indices = np.linspace(0, len(df) - 1, max_samples, dtype=int)
    else:
        indices = np.arange(len(df))

    print(f"  Generating fused vectors for {len(indices):,} samples…")
    for i, idx in enumerate(indices):
        row = df.iloc[idx]
        frame = _row_to_frame(row)
        result = pipeline.process_frame(frame)
        fused_vectors.append(np.array(result["fused_vector"], dtype=np.float32))

        if (i + 1) % 1000 == 0:
            print(f"    {i + 1}/{len(indices)}")

    vectors = np.stack(fused_vectors)
    print(f"  Fused vectors shape: {vectors.shape}")
    return torch.from_numpy(vectors)


def _row_to_frame(row: pd.Series) -> Dict[str, Any]:
    """Convert a DataFrame row to a telemetry frame dict."""
    return {
        "rpm": float(row["rpm"]),
        "map_kpa": float(row["map_kpa"]),
        "fuel_flow_lph": float(row["fuel_flow_lph"]),
        "equivalence_ratio": float(row["equivalence_ratio"]),
        "cht_c": [
            float(row["cht_1_c"]), float(row["cht_2_c"]),
            float(row["cht_3_c"]), float(row["cht_4_c"]),
        ],
        "egt_c": [
            float(row["egt_1_c"]), float(row["egt_2_c"]),
            float(row["egt_3_c"]), float(row["egt_4_c"]),
        ],
        "oil_pressure_kpa": float(row["oil_pressure_kpa"]),
        "oil_temp_c": float(row["oil_temp_c"]),
        "vibration_rms_g": float(row["vibration_rms_g"]),
    }


# ══════════════════════════════════════════════════════════════════
#  Training
# ══════════════════════════════════════════════════════════════════

def train(
    epochs: int = EPOCHS,
    lr: float = LEARNING_RATE,
    batch_size: int = BATCH_SIZE,
    device: str = "cpu",
    max_samples: int = 10_000,
) -> AnomalyVAE:
    """
    Train the VAE on nominal fused vectors.

    Steps:
    1. Load nominal CSV → generate fused vectors via pipeline.
    2. Train VAE for N epochs.
    3. Compute reconstruction error threshold at alpha percentile.
    4. Save model weights.
    """
    dev = torch.device(device)

    # ── Load data ──
    data = _load_nominal_fused_vectors(max_samples)
    dataset = TensorDataset(data)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # ── Initialize model ──
    model = AnomalyVAE().to(dev)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    n_params = sum(p.numel() for p in model.parameters())
    print(f"\n  VAE Training — {n_params:,} parameters")
    print(f"  Epochs: {epochs}, Batch size: {batch_size}, β: {BETA}")
    print("  " + "─" * 50)

    # ── Training loop ──
    model.train()
    for epoch in range(epochs):
        epoch_loss = 0.0
        epoch_recon = 0.0
        epoch_kl = 0.0
        n_batches = 0

        t0 = time.time()
        for (batch,) in loader:
            batch = batch.to(dev)

            x_recon, mu, logvar = model(batch)
            loss, comps = model.vae_loss(x_recon, batch, mu, logvar)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            epoch_loss += comps["total_loss"]
            epoch_recon += comps["recon_loss"]
            epoch_kl += comps["kl_loss"]
            n_batches += 1

        elapsed = time.time() - t0
        avg_loss = epoch_loss / n_batches
        avg_recon = epoch_recon / n_batches
        avg_kl = epoch_kl / n_batches

        print(
            f"  Epoch {epoch + 1:>3}/{epochs}  "
            f"loss={avg_loss:.4f}  "
            f"recon={avg_recon:.4f}  "
            f"kl={avg_kl:.4f}  "
            f"({elapsed:.1f}s)"
        )

    # ── Compute threshold ──
    print("\n  Computing reconstruction error threshold…")
    model.eval()
    with torch.no_grad():
        all_recon_errors = []
        for (batch,) in loader:
            batch = batch.to(dev)
            x_recon, _, _ = model(batch)
            per_sample = F.mse_loss(x_recon, batch, reduction="none").sum(dim=-1)
            all_recon_errors.extend(per_sample.cpu().numpy().tolist())

        errors = np.array(all_recon_errors)
        threshold = float(np.percentile(errors, model.alpha * 100))
        model.recon_threshold.fill_(threshold)

        print(f"  Reconstruction error stats:")
        print(f"    Mean:  {errors.mean():.4f}")
        print(f"    Std:   {errors.std():.4f}")
        print(f"    Min:   {errors.min():.4f}")
        print(f"    Max:   {errors.max():.4f}")
        print(f"    P{int(model.alpha * 100):>2d}:   {threshold:.4f}")

    # ── Save model ──
    path = model.save()
    print(f"\n  Model saved: {path}")
    print("  Training complete.\n")

    return model


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def _force_utf8_stdout() -> None:
    """
    Make CLI output UTF-8 safe.

    When stdout is a pipe or a file, Python encodes with the locale codec
    (cp1252 on Windows) and printing the progress banner — which contains
    ``β`` and box-drawing glyphs — raises ``UnicodeEncodeError``.  That
    breaks ``train.bat > log.txt`` style redirection.

    Only non-console streams are reconfigured; an interactive console
    keeps its own encoding (Python already writes Unicode to the Windows
    console through the wide-character API).
    """
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    isatty = getattr(stream, "isatty", None)
    if reconfigure is None or isatty is None or isatty():
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):  # pragma: no cover - exotic streams
        pass


def main() -> None:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description="Anomaly VAE")
    sub = parser.add_subparsers(dest="command")

    # Train subcommand
    train_p = sub.add_parser("train", help="Train VAE on nominal data")
    train_p.add_argument("--epochs", type=int, default=EPOCHS)
    train_p.add_argument("--lr", type=float, default=LEARNING_RATE)
    train_p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    train_p.add_argument("--max-samples", type=int, default=10_000)
    train_p.add_argument("--device", type=str, default="cpu")

    # Predict subcommand
    pred_p = sub.add_parser("predict", help="Predict anomaly for a vector")
    pred_p.add_argument("--vector", type=str, required=True,
                        help="Comma-separated 32-dim vector")
    pred_p.add_argument("--model", type=str, default=str(MODEL_PATH))

    # Info subcommand
    sub.add_parser("info", help="Show model info")

    args = parser.parse_args()

    if args.command == "train":
        train(
            epochs=args.epochs,
            lr=args.lr,
            batch_size=args.batch_size,
            max_samples=args.max_samples,
            device=args.device,
        )

    elif args.command == "predict":
        vec = torch.tensor(
            [float(x) for x in args.vector.split(",")],
            dtype=torch.float32,
        ).reshape(1, -1)
        model = AnomalyVAE.load(args.model)
        result = model.predict_anomaly(vec)
        print(json.dumps(result, indent=2))

    elif args.command == "info":
        if MODEL_PATH.exists():
            model = AnomalyVAE.load(MODEL_PATH)
            n_params = sum(p.numel() for p in model.parameters())
            print(f"\n  Anomaly VAE Info")
            print(f"  {'=' * 40}")
            print(f"  Input dim:     {model.input_dim}")
            print(f"  Latent dim:    {model.latent_dim}")
            print(f"  Parameters:    {n_params:,}")
            print(f"  Beta:          {model.beta}")
            print(f"  Alpha:         {model.alpha}")
            print(f"  Threshold:     {model.recon_threshold.item():.4f}")
            print(f"  Path:          {MODEL_PATH}\n")
        else:
            print(f"\n  No trained model found at {MODEL_PATH}")
            print("  Run: python -m fusion_ml.anomaly_vae train\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
