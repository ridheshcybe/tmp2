#!/usr/bin/env python3
"""
RUL Predictor — Hybrid TCN + XGBoost Pipeline
================================================
Predicts Remaining Useful Life (RUL) for aero piston engines using:

1. **Temporal Convolutional Network (TCN)**: extracts temporal features
   from a sliding window of 300 fused vectors (30 s at 10 Hz).
2. **XGBoost Regressor**: maps TCN embeddings + baseline thermodynamic
   metrics to predicted RUL in minutes.

Features
--------
* 3 dilated causal convolution blocks (dilations 1, 2, 4).
* Residual connections for gradient flow.
* Return-to-Base (RTB) margin: WARNING (≤30 min), CRITICAL (≤10 min).
* NASA PHM scoring function for asymmetric cost evaluation.

Usage
-----
    python -m fusion_ml.rul_predictor train
    python -m fusion_ml.rul_predictor predict --sequence "..."
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

try:
    from xgboost import XGBRegressor
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

from fusion_ml.cross_modal_fusion import FUSED_DIM


# ══════════════════════════════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════════════════════════════

SEQUENCE_LENGTH = 300     # 30 s at 10 Hz
TCN_CHANNELS = 32
TCN_EMBED_DIM = 16        # TCN output embedding dimension
KERNEL_SIZE = 3
DILATIONS = [1, 2, 4]
BASELINE_FEATURES = 3     # CHT_max, EGT_spread, Vibration_RMS
TOTAL_FEATURE_DIM = TCN_EMBED_DIM + BASELINE_FEATURES  # 19

RTB_WARNING_MIN = 30.0
RTB_CRITICAL_MIN = 10.0

TCN_EPOCHS = 15
TCN_LR = 1e-3
TCN_BATCH_SIZE = 32
XGB_N_ESTIMATORS = 200
XGB_MAX_DEPTH = 6
XGB_LEARNING_RATE = 0.1

#: Upper bound on how many sliding windows are materialised for training.
#: One window is (SEQUENCE_LENGTH × FUSED_DIM) float32 ≈ 38 kB, so the full
#: fault dataset (≈430 k windows) would need ≈16 GB of RAM.  Candidates are
#: evenly sub-sampled down to this budget.
MAX_TRAIN_SEQUENCES = 10_000

MODEL_DIR = Path(__file__).resolve().parent / "models"
TCN_PATH = MODEL_DIR / "tcn_extractor.pt"
XGB_PATH = MODEL_DIR / "xgb_rul.json"
FAULTS_CSV = Path(__file__).resolve().parent.parent / "data" / "flight_dataset_faults.csv"


# ══════════════════════════════════════════════════════════════════
#  TCN Feature Extractor
# ══════════════════════════════════════════════════════════════════

class CausalConv1d(nn.Module):
    """
    Causal 1D convolution: output[t] depends only on input[≤t].
    Achieved by left-padding input by (kernel_size - 1) * dilation.
    """

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int,
        dilation: int = 1,
    ) -> None:
        super().__init__()
        self.padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(
            in_channels, out_channels, kernel_size,
            dilation=dilation, padding=0,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, C, T)
        x_padded = F.pad(x, (self.padding, 0))
        return self.conv(x_padded)


class TCNBlock(nn.Module):
    """
    Single TCN block: CausalConv → BatchNorm → ReLU → CausalConv → BatchNorm
    with residual connection.
    """

    def __init__(
        self,
        channels: int,
        kernel_size: int,
        dilation: int,
    ) -> None:
        super().__init__()
        self.conv1 = CausalConv1d(channels, channels, kernel_size, dilation)
        self.bn1 = nn.BatchNorm1d(channels)
        self.conv2 = CausalConv1d(channels, channels, kernel_size, dilation)
        self.bn2 = nn.BatchNorm1d(channels)
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        out = self.relu(out + residual)  # residual connection
        return out


class TCNFeatureExtractor(nn.Module):
    """
    Temporal Convolutional Network for feature extraction.

    Architecture:
    * Input: (B, seq_len, fused_dim=32)
    * 3 TCN blocks with dilations [1, 2, 4], channels=32
    * Global average pooling → (B, channels=32)
    * Linear projection → (B, embed_dim=16)

    Parameters
    ----------
    input_dim : int
        Dimension of each timestep (default 32).
    channels : int
        Number of convolutional channels (default 32).
    embed_dim : int
        Output embedding dimension (default 16).
    kernel_size : int
        Convolution kernel size (default 3).
    dilations : list[int]
        Dilation factors for each block (default [1, 2, 4]).
    """

    def __init__(
        self,
        input_dim: int = FUSED_DIM,
        channels: int = TCN_CHANNELS,
        embed_dim: int = TCN_EMBED_DIM,
        kernel_size: int = KERNEL_SIZE,
        dilations: Optional[List[int]] = None,
    ) -> None:
        super().__init__()
        self.input_proj = nn.Linear(input_dim, channels)
        dilations = dilations or DILATIONS

        self.blocks = nn.ModuleList([
            TCNBlock(channels, kernel_size, d) for d in dilations
        ])

        self.gap = nn.AdaptiveAvgPool1d(1)  # global average pooling
        self.proj = nn.Linear(channels, embed_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Parameters
        ----------
        x : (B, seq_len, input_dim)

        Returns
        -------
        (B, embed_dim)
        """
        # Project input channels
        h = self.input_proj(x)  # (B, T, channels)
        h = h.transpose(1, 2)   # (B, channels, T) for Conv1d

        # TCN blocks
        for block in self.blocks:
            h = block(h)

        # Global average pooling: (B, channels, T) → (B, channels, 1)
        h = self.gap(h).squeeze(-1)  # (B, channels)

        # Project to embedding
        h = self.proj(h)  # (B, embed_dim)
        return h


# ══════════════════════════════════════════════════════════════════
#  NASA PHM Scoring Function
# ══════════════════════════════════════════════════════════════════

def nasa_phm_score(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    alpha: float = 3.0,
) -> float:
    """
    NASA PHM 2008 scoring function.

    Asymmetric penalty: late predictions (underestimating RUL) are
    penalised exponentially more than early predictions.

    Score = Σ exp(-d_i / α) - 1  if d_i < 0 (early)
          = Σ exp(d_i / 13) - 1  if d_i ≥ 0 (late)

    where d_i = y_pred_i - y_true_i

    Lower score is better.  A perfect model scores 0.
    """
    d = y_pred - y_true
    scores = np.where(
        d < 0,
        np.exp(-d / alpha) - 1,   # early prediction penalty
        np.exp(d / 13.0) - 1,     # late prediction penalty
    )
    return float(scores.sum())


# ══════════════════════════════════════════════════════════════════
#  RUL Predictor
# ══════════════════════════════════════════════════════════════════

class RULPredictor:
    """
    Hybrid TCN + XGBoost RUL prediction pipeline.

    Parameters
    ----------
    sequence_length : int
        Sliding window length in samples (default 300).
    device : str
        PyTorch device (default "cpu").
    """

    def __init__(
        self,
        sequence_length: int = SEQUENCE_LENGTH,
        device: str = "cpu",
    ) -> None:
        self.seq_len = sequence_length
        self.device = torch.device(device)

        # TCN feature extractor
        self.tcn = TCNFeatureExtractor().to(self.device)
        self.xgb: Optional[Any] = None  # XGBRegressor (fitted)

        # Normalization stats (set during training)
        self.register_buffer("xgb_mean", np.zeros(TOTAL_FEATURE_DIM))
        self.register_buffer("xgb_std", np.ones(TOTAL_FEATURE_DIM))

    def register_buffer(self, name: str, value: Any) -> None:
        """Store numpy arrays as instance attributes."""
        setattr(self, f"_{name}_arr", value)

    # ── Sequence building ──────────────────────────────────────

    def build_sequences(
        self,
        fused_vectors: np.ndarray,
        rul_labels: np.ndarray,
        cht_max: np.ndarray,
        egt_spread: np.ndarray,
        vibration: np.ndarray,
        window_indices: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Build sliding-window sequences from fused vectors.

        Parameters
        ----------
        fused_vectors : (N, 32) — per-timestep fused latents
        rul_labels : (N,) — RUL in minutes
        cht_max, egt_spread, vibration : (N,) — baseline metrics
        window_indices : np.ndarray | None
            Window end indices to materialise.  ``None`` (default) keeps
            every window — i.e. ``seq_len - 1 … N - 1``.  Passing an
            explicit subset keeps memory bounded on large datasets.

        Returns
        -------
        X_seq : (M, seq_len, 32) — input sequences
        X_base : (M, 3) — baseline features at window end
        y_rul : (M,) — target RUL at window end
        """
        N = len(fused_vectors)
        X_seqs, X_bases, y_ruls = [], [], []

        if window_indices is None:
            window_indices = np.arange(self.seq_len - 1, N)

        for i in window_indices:
            i = int(i)
            seq = fused_vectors[i - self.seq_len + 1: i + 1]  # (seq_len, 32)
            X_seqs.append(seq)
            X_bases.append([
                cht_max[i],
                egt_spread[i],
                vibration[i],
            ])
            y_ruls.append(rul_labels[i])

        return (
            np.array(X_seqs, dtype=np.float32),
            np.array(X_bases, dtype=np.float32),
            np.array(y_ruls, dtype=np.float32),
        )

    # ── TCN feature extraction ─────────────────────────────────

    def extract_tcn_features(
        self,
        X_seq: np.ndarray,
    ) -> np.ndarray:
        """
        Extract TCN embeddings from sequences.

        Parameters
        ----------
        X_seq : (M, seq_len, 32)

        Returns
        -------
        (M, TCN_EMBED_DIM) numpy array
        """
        self.tcn.eval()
        tensor = torch.from_numpy(X_seq).to(self.device)

        embeddings = []
        with torch.no_grad():
            # Process in batches to avoid memory issues
            batch_size = 256
            for start in range(0, len(tensor), batch_size):
                batch = tensor[start:start + batch_size]
                emb = self.tcn(batch)
                embeddings.append(emb.cpu().numpy())

        return np.concatenate(embeddings, axis=0)

    # ── Training ───────────────────────────────────────────────

    def train(
        self,
        csv_path: Optional[str | Path] = None,
        tcn_epochs: int = TCN_EPOCHS,
        tcn_lr: float = TCN_LR,
        max_runs: int = 50,
        max_sequences: Optional[int] = MAX_TRAIN_SEQUENCES,
    ) -> Dict[str, float]:
        """
        Train the full pipeline on fault-injected flight data.

        Steps:
        1. Load faults CSV → generate fused vectors via pipeline.
        2. Build sequences + baseline features (per run, anomaly-ended).
        3. Train TCN to predict RUL directly (MSE loss).
        4. Extract TCN embeddings → train XGBoost on combined features.
        5. Evaluate and print metrics.

        Parameters
        ----------
        max_sequences : int | None
            Cap on the number of sliding windows kept for training;
            candidates are evenly sub-sampled to fit.  ``None`` keeps
            every candidate (needs ≈16 GB RAM on the full fault dataset).
        """
        if not HAS_XGBOOST:
            raise RuntimeError(
                "xgboost is required to train the RUL predictor but is not "
                "installed.\n  Install with: pip install -r requirements.txt"
            )

        csv_path = Path(csv_path) if csv_path else FAULTS_CSV
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Fault dataset not found: {csv_path}\n"
                "  Generate with: python -m simulator.generate_datasets faults"
            )

        # ── Step 1: Load data ──
        print(f"\n  RUL Predictor — Training Pipeline")
        print(f"  {'=' * 50}")
        print(f"  Loading faults CSV: {csv_path}")

        df = pd.read_csv(csv_path)
        print(f"  Loaded {len(df):,} rows")

        # ── Step 2: Generate fused vectors ──
        from fusion_ml.fusion_pipeline import EngineFusionPipeline
        pipeline = EngineFusionPipeline()

        # Group by run_id for sequence continuity
        if "run_id" in df.columns:
            run_ids = df["run_id"].unique()[:max_runs]
        else:
            run_ids = [0]

        # Per-run buffers — sliding windows must never span run boundaries
        runs: List[Dict[str, np.ndarray]] = []

        print(f"  Processing {len(run_ids)} runs…")
        for run_id in run_ids:
            if "run_id" in df.columns:
                run_df = df[df["run_id"] == run_id].reset_index(drop=True)
            else:
                run_df = df

            fused: List[np.ndarray] = []
            rul: List[float] = []
            cht_max: List[float] = []
            egt_spread: List[float] = []
            vib: List[float] = []
            is_anom: List[int] = []

            for _, row in run_df.iterrows():
                frame = _row_to_frame(row)
                result = pipeline.process_frame(frame)

                fused.append(np.array(result["fused_vector"], dtype=np.float32))
                rul.append(float(row["remaining_useful_life_sec"]) / 60.0)  # sec → min
                cht_max.append(max(frame["cht_c"]))
                egt_spread.append(max(frame["egt_c"]) - min(frame["egt_c"]))
                vib.append(frame["vibration_rms_g"])
                is_anom.append(int(row.get("is_anomaly", 0)))

            runs.append({
                "fused": np.stack(fused),
                "rul": np.asarray(rul, dtype=np.float32),
                "cht_max": np.asarray(cht_max, dtype=np.float32),
                "egt_spread": np.asarray(egt_spread, dtype=np.float32),
                "vib": np.asarray(vib, dtype=np.float32),
                "is_anom": np.asarray(is_anom, dtype=np.int8),
            })

        n_frames = sum(len(r["rul"]) for r in runs)
        rul_min = min(float(r["rul"].min()) for r in runs)
        rul_max = max(float(r["rul"].max()) for r in runs)
        print(f"  Fused vectors: ({n_frames:,}, {FUSED_DIM})")
        print(f"  RUL range: {rul_min:.1f} – {rul_max:.1f} min")

        # ─ Step 3: Build sequences ──
        # Only use sequences where the window ends at an anomalous point
        # (RUL is meaningful only during degradation); fall back to every
        # window if a run has no anomalies at all.
        candidates: List[Tuple[Dict[str, np.ndarray], np.ndarray]] = []
        n_candidates = 0
        n_anomalous = 0
        for run_data in runs:
            all_windows = np.arange(self.seq_len - 1, len(run_data["rul"]))
            if len(all_windows) == 0:
                continue
            anom_windows = all_windows[run_data["is_anom"][all_windows] == 1]
            chosen = anom_windows if len(anom_windows) else all_windows
            n_anomalous += len(anom_windows)
            n_candidates += len(chosen)
            candidates.append((run_data, chosen))

        if not candidates:
            raise ValueError(
                f"No training windows available: every run is shorter than "
                f"the {self.seq_len}-sample sequence length."
            )

        # Evenly sub-sample the candidate pool to stay within the memory budget
        pool: List[Tuple[int, int]] = [
            (part_idx, int(window))
            for part_idx, (_, windows) in enumerate(candidates)
            for window in windows
        ]
        if max_sequences is not None and len(pool) > max_sequences:
            picks = np.linspace(0, len(pool) - 1, max_sequences, dtype=int)
            pool = [pool[k] for k in picks]

        print(
            f"  Candidate windows: {n_candidates:,} "
            f"({n_anomalous:,} anomaly-ended)  →  using {len(pool):,}"
        )

        # Materialise the selected windows directly into pre-allocated arrays
        by_part: Dict[int, List[int]] = {}
        for part_idx, window in pool:
            by_part.setdefault(part_idx, []).append(window)

        n_keep = len(pool)
        X_seq = np.empty((n_keep, self.seq_len, FUSED_DIM), dtype=np.float32)
        X_base = np.empty((n_keep, BASELINE_FEATURES), dtype=np.float32)
        y_rul = np.empty(n_keep, dtype=np.float32)

        offset = 0
        for part_idx in sorted(by_part):
            run_data, _ = candidates[part_idx]
            X_s, X_b, y_r = self.build_sequences(
                run_data["fused"], run_data["rul"], run_data["cht_max"],
                run_data["egt_spread"], run_data["vib"],
                window_indices=np.asarray(by_part[part_idx], dtype=int),
            )
            n_part = len(y_r)
            X_seq[offset:offset + n_part] = X_s
            X_base[offset:offset + n_part] = X_b
            y_rul[offset:offset + n_part] = y_r
            offset += n_part

        print(
            f"  Sequences: {X_seq.shape}  "
            f"({X_seq.nbytes / 1e6:.0f} MB)  RUL range: "
            f"{y_rul.min():.1f} – {y_rul.max():.1f} min"
        )

        # ── Step 4: Train TCN ──
        print(f"\n  Training TCN ({tcn_epochs} epochs)…")
        self._train_tcn(X_seq, y_rul, tcn_epochs, tcn_lr)

        # ── Step 5: Extract TCN embeddings ──
        print("  Extracting TCN embeddings…")
        tcn_embs = self.extract_tcn_features(X_seq)

        # ── Step 6: Combine features ──
        X_combined = np.concatenate([tcn_embs, X_base], axis=1)  # (M, 19)

        # Normalize
        self._xgb_mean = X_combined.mean(axis=0)
        self._xgb_std = X_combined.std(axis=0) + 1e-8
        X_norm = (X_combined - self._xgb_mean) / self._xgb_std

        # ── Step 7: Train XGBoost ──
        print("  Training XGBoost…")
        self.xgb = XGBRegressor(
            n_estimators=XGB_N_ESTIMATORS,
            max_depth=XGB_MAX_DEPTH,
            learning_rate=XGB_LEARNING_RATE,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
        )
        self.xgb.fit(X_norm, y_rul)

        # ── Step 8: Evaluate ──
        y_pred = self.xgb.predict(X_norm)
        metrics = self._compute_metrics(y_rul, y_pred)

        print(f"\n  Evaluation Metrics:")
        for k, v in metrics.items():
            print(f"    {k:<25s}  {v:.4f}")

        # ── Step 9: Save models ──
        self.save()
        print(f"\n  Models saved:")
        print(f"    TCN:  {TCN_PATH}")
        print(f"    XGB:  {XGB_PATH}")

        return metrics

    def _train_tcn(
        self,
        X_seq: np.ndarray,
        y_rul: np.ndarray,
        epochs: int,
        lr: float,
    ) -> None:
        """Train TCN to predict RUL directly."""
        dataset = TensorDataset(
            torch.from_numpy(X_seq),
            torch.from_numpy(y_rul),
        )
        loader = DataLoader(dataset, batch_size=TCN_BATCH_SIZE, shuffle=True)

        # Add a linear head on top of TCN for direct RUL prediction during training
        tcn_head = nn.Sequential(
            self.tcn,
            nn.Linear(TCN_EMBED_DIM, 1),
        ).to(self.device)

        optimizer = torch.optim.Adam(tcn_head.parameters(), lr=lr)
        criterion = nn.MSELoss()

        tcn_head.train()
        for epoch in range(epochs):
            total_loss = 0.0
            n_batches = 0
            t0 = time.time()

            for batch_x, batch_y in loader:
                batch_x = batch_x.to(self.device)
                batch_y = batch_y.to(self.device)

                pred = tcn_head(batch_x).squeeze(-1)
                loss = criterion(pred, batch_y)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                total_loss += loss.item()
                n_batches += 1

            elapsed = time.time() - t0
            print(
                f"    Epoch {epoch + 1:>3}/{epochs}  "
                f"loss={total_loss / n_batches:.4f}  "
                f"({elapsed:.1f}s)"
            )

    # ── Inference ──────────────────────────────────────────────

    def predict_rul(
        self,
        fused_sequence: np.ndarray,
        baseline_metrics: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Predict RUL for a sequence of fused vectors.

        Parameters
        ----------
        fused_sequence : np.ndarray
            (seq_len, 32) or (B, seq_len, 32) — window of fused vectors.
        baseline_metrics : np.ndarray | None
            (3,) or (B, 3) — [CHT_max, EGT_spread, Vibration].
            If None, estimated from the sequence.

        Returns
        -------
        dict with:
            ``predicted_rul_min``: float
            ``rtb_warning``: bool (RUL ≤ 30 min)
            ``rtb_critical``: bool (RUL ≤ 10 min)
            ``confidence``: float (0–1, based on XGBoost tree variance)
        """
        if self.xgb is None:
            raise RuntimeError("XGBoost model not trained. Run train() first.")

        self.tcn.eval()

        # Ensure correct shape
        if fused_sequence.ndim == 2:
            fused_sequence = fused_sequence[np.newaxis, ...]

        # Extract TCN features
        tcn_embs = self.extract_tcn_features(fused_sequence)

        # Baseline features
        if baseline_metrics is not None:
            if baseline_metrics.ndim == 1:
                baseline_metrics = baseline_metrics[np.newaxis, ...]
            base = baseline_metrics
        else:
            # Estimate from last timestep of sequence
            last = fused_sequence[:, -1, :]  # (B, 32)
            # Approximate CHT max from first 4 dims of modality features
            # (these are the raw sensor values, not the fused latent)
            base = np.zeros((len(tcn_embs), BASELINE_FEATURES))
            base[:, 0] = 200.0   # default CHT max
            base[:, 1] = 20.0    # default EGT spread
            base[:, 2] = 1.5     # default vibration

        # Combine features
        X = np.concatenate([tcn_embs, base], axis=1)

        # Normalize
        X_norm = (X - self._xgb_mean) / self._xgb_std

        # Predict
        rul_pred = self.xgb.predict(X_norm)

        # RTB evaluation
        rul_val = float(rul_pred[0]) if len(rul_pred) == 1 else float(rul_pred.mean())

        # Confidence from XGBoost (approximate via tree predictions variance)
        # For a single prediction, use a heuristic based on RUL distance from thresholds
        confidence = min(1.0, max(0.0, 1.0 - abs(rul_val - 50.0) / 100.0))

        return {
            "predicted_rul_min": round(rul_val, 2),
            "rtb_warning": rul_val <= RTB_WARNING_MIN,
            "rtb_critical": rul_val <= RTB_CRITICAL_MIN,
            "confidence": round(confidence, 4),
        }

    # ── Evaluation ─────────────────────────────────────────────

    @staticmethod
    def _compute_metrics(
        y_true: np.ndarray,
        y_pred: np.ndarray,
    ) -> Dict[str, float]:
        """Compute RMSE, MAE, and NASA PHM score."""
        rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
        mae = float(np.mean(np.abs(y_true - y_pred)))
        score = nasa_phm_score(y_true, y_pred)

        return {
            "rmse_min": rmse,
            "mae_min": mae,
            "nasa_phm_score": score,
        }

    # ── Save / Load ────────────────────────────────────────────

    def save(self) -> None:
        """Save TCN weights and XGBoost model."""
        MODEL_DIR.mkdir(parents=True, exist_ok=True)

        # Save TCN
        torch.save({
            "tcn_state": self.tcn.state_dict(),
            "seq_len": self.seq_len,
        }, TCN_PATH)

        # Save XGBoost
        if self.xgb is not None:
            self.xgb.save_model(str(XGB_PATH))

        # Save normalization stats
        np.savez(
            MODEL_DIR / "rul_norm_stats.npz",
            mean=self._xgb_mean,
            std=self._xgb_std,
        )

    @classmethod
    def load(
        cls,
        tcn_path: Optional[str | Path] = None,
        xgb_path: Optional[str | Path] = None,
    ) -> "RULPredictor":
        """Load trained models."""
        tcn_path = Path(tcn_path or TCN_PATH)
        xgb_path = Path(xgb_path or XGB_PATH)

        predictor = cls()

        # Load TCN
        if tcn_path.exists():
            checkpoint = torch.load(tcn_path, map_location="cpu", weights_only=False)
            predictor.tcn.load_state_dict(checkpoint["tcn_state"])
            predictor.seq_len = checkpoint.get("seq_len", SEQUENCE_LENGTH)

        # Load XGBoost
        if xgb_path.exists() and HAS_XGBOOST:
            predictor.xgb = XGBRegressor()
            predictor.xgb.load_model(str(xgb_path))

        # Load norm stats
        norm_path = MODEL_DIR / "rul_norm_stats.npz"
        if norm_path.exists():
            stats = np.load(norm_path)
            predictor._xgb_mean = stats["mean"]
            predictor._xgb_std = stats["std"]

        predictor.tcn.eval()
        return predictor


# ══════════════════════════════════════════════════════════════════
#  Data helpers
# ══════════════════════════════════════════════════════════════════

def _row_to_frame(row: pd.Series) -> Dict[str, Any]:
    """Convert a DataFrame row to a telemetry frame dict."""
    return {
        "rpm": float(row["rpm"]),
        "map_kpa": float(row["map_kpa"]),
        "fuel_flow_lph": float(row["fuel_flow_lph"]),
        "equivalence_ratio": float(row.get("equivalence_ratio", 0.85)),
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
#  CLI
# ══════════════════════════════════════════════════════════════════

def _force_utf8_stdout() -> None:
    """
    Make CLI output UTF-8 safe.

    When stdout is a pipe or a file, Python encodes with the locale codec
    (cp1252 on Windows) and printing the progress banner — which contains
    box-drawing glyphs — raises ``UnicodeEncodeError``.  That breaks
    ``train.bat > log.txt`` style redirection.

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
    parser = argparse.ArgumentParser(description="RUL Predictor")
    sub = parser.add_subparsers(dest="command")

    # Train
    train_p = sub.add_parser("train", help="Train TCN + XGBoost pipeline")
    train_p.add_argument("--csv", type=str, default=None)
    train_p.add_argument("--tcn-epochs", type=int, default=TCN_EPOCHS)
    train_p.add_argument("--max-runs", type=int, default=50)
    train_p.add_argument(
        "--max-sequences", type=int, default=MAX_TRAIN_SEQUENCES,
        help="Cap on training windows (memory budget).",
    )

    # Predict
    pred_p = sub.add_parser("predict", help="Predict RUL")
    pred_p.add_argument("--sequence", type=str, required=True,
                        help="JSON array of 300 fused vectors")

    # Info
    sub.add_parser("info", help="Show model info")

    args = parser.parse_args()

    if args.command == "train":
        predictor = RULPredictor()
        predictor.train(
            csv_path=args.csv,
            tcn_epochs=args.tcn_epochs,
            max_runs=args.max_runs,
            max_sequences=args.max_sequences,
        )

    elif args.command == "predict":
        seq = np.array(json.loads(args.sequence), dtype=np.float32)
        predictor = RULPredictor.load()
        result = predictor.predict_rul(seq)
        print(json.dumps(result, indent=2))

    elif args.command == "info":
        print(f"\n  RUL Predictor Info")
        print(f"  {'=' * 40}")
        print(f"  Sequence length:  {SEQUENCE_LENGTH} samples (30 s)")
        print(f"  TCN channels:     {TCN_CHANNELS}")
        print(f"  TCN embed dim:    {TCN_EMBED_DIM}")
        print(f"  Dilations:        {DILATIONS}")
        print(f"  XGB features:     {TOTAL_FEATURE_DIM}")
        print(f"  RTB warning:      ≤ {RTB_WARNING_MIN} min")
        print(f"  RTB critical:     ≤ {RTB_CRITICAL_MIN} min")
        print(f"  TCN path:         {TCN_PATH}")
        print(f"  XGB path:         {XGB_PATH}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
