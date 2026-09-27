#!/usr/bin/env python3
"""
Online Adaptation Manager
=========================
Adapts the anomaly-detection VAE to gradual environmental drifts
(e.g. atmospheric temperature changes) without triggering false
positives.

Features
--------
* **EMA Baseline Tracker**: exponential moving average of nominal
  features during steady-state cruise.
* **Incremental VAE Decoder Updates**: low-learning-rate gradient
  steps on the decoder only when data is verified nominal for > 5 min.
* **Safety Guard**: freezes all online updates on fault detection or
  anomaly score spike (> 25%).
* **Adaptive Normalization**: recenters and rescales inputs to
  compensate for slow environmental drift.

Usage
-----
    from fusion_ml.online_adapter import OnlineAdaptationManager

    adapter = OnlineAdaptationManager(vae_model)
    for frame in stream:
        result = adapter.process(frame)
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


# ══════════════════════════════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════════════════════════════

EMA_MOMENTUM = 0.001          # EMA decay (slow tracking)
ADAPTIVE_LR = 1e-5            # Very low LR for online decoder updates
NOMINAL_CONFIRM_S = 300.0     # 5 minutes of nominal data before update
ANOMALY_SPIKE_THRESHOLD = 25.0  # Anomaly score that triggers safety freeze
STEADY_STATE_VEL_THRESH = 0.01  # Threshold for altitude/throttle derivative
STALE_BUFFER_SIZE = 600       # Rolling buffer for drift detection


# ══════════════════════════════════════════════════════════════════
#  Data structures
# ══════════════════════════════════════════════════════════════════

@dataclass
class AdaptationState:
    """Tracks the online adaptation lifecycle."""
    is_frozen: bool = False
    freeze_reason: str = ""
    nominal_streak_s: float = 0.0
    last_anomaly_score: float = 0.0
    total_updates: int = 0
    total_frames: int = 0
    drift_magnitude: float = 0.0


@dataclass
class AdaptationResult:
    """Output of :meth:`OnlineAdaptationManager.process`."""
    anomaly_result: Dict[str, Any]
    adapted: bool
    state: AdaptationState
    ema_baseline: Optional[np.ndarray]
    drift_correction: Optional[np.ndarray]


# ══════════════════════════════════════════════════════════════════
#  EMA Baseline Tracker
# ══════════════════════════════════════════════════════════════════

class EMABaselineTracker:
    """
    Exponential Moving Average tracker for nominal baseline features.

    Maintains running mean and variance of fused vectors seen during
    nominal (steady-state cruise) operation.  Used for adaptive
    normalization to compensate for atmospheric drift.
    """

    def __init__(
        self,
        dim: int = 32,
        momentum: float = EMA_MOMENTUM,
    ) -> None:
        self.dim = dim
        self.momentum = momentum
        self.mean = np.zeros(dim, dtype=np.float64)
        self.var = np.ones(dim, dtype=np.float64)
        self.count = 0
        self.initialized = False

    def update(self, x: np.ndarray) -> None:
        """
        Update EMA with a new sample.

        Parameters
        ----------
        x : (dim,) — single fused vector
        """
        x = np.asarray(x, dtype=np.float64)
        if not self.initialized:
            self.mean = x.copy()
            self.var = np.zeros_like(x)
            self.count = 1
            self.initialized = True
            return

        self.count += 1
        alpha = self.momentum

        # EMA mean
        old_mean = self.mean.copy()
        self.mean = (1 - alpha) * self.mean + alpha * x

        # EMA variance (Welford-like)
        delta = x - old_mean
        delta2 = x - self.mean
        self.var = (1 - alpha) * self.var + alpha * delta * delta2

    def get_normalization(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Returns (mean, std) for adaptive normalization.
        """
        std = np.sqrt(np.maximum(self.var, 1e-8))
        return self.mean.copy(), std.copy()

    def normalize(self, x: np.ndarray) -> np.ndarray:
        """Normalize x using current EMA statistics."""
        mean, std = self.get_normalization()
        return (x - mean) / std

    def denormalize(self, x_norm: np.ndarray) -> np.ndarray:
        """Reverse normalization."""
        mean, std = self.get_normalization()
        return x_norm * std + mean

    @property
    def is_ready(self) -> bool:
        """True if enough samples have been seen."""
        return self.count >= 30  # need at least 30 samples


# ══════════════════════════════════════════════════════════════════
#  Online Adaptation Manager
# ══════════════════════════════════════════════════════════════════

class OnlineAdaptationManager:
    """
    Manages online adaptation of the anomaly-detection VAE.

    Responsibilities:
    1. Track nominal baselines via EMA during steady-state cruise.
    2. Apply adaptive normalization to compensate for drift.
    3. Incrementally update VAE decoder when verified nominal > 5 min.
    4. Freeze all updates on fault detection or anomaly spike.

    Parameters
    ----------
    vae_model : AnomalyVAE
        Pre-trained VAE model.
    dt : float
        Time step between frames [s] (default 0.1 for 10 Hz).
    device : str
        PyTorch device (default "cpu").
    """

    def __init__(
        self,
        vae_model: nn.Module,
        dt: float = 0.1,
        device: str = "cpu",
    ) -> None:
        self.vae = vae_model
        self.vae.eval()
        self.dt = dt
        self.device = torch.device(device)

        # ── EMA baseline tracker ──
        self.ema = EMABaselineTracker(dim=32, momentum=EMA_MOMENTUM)

        # ── State ──
        self.state = AdaptationState()

        # ── Snapshot of pre-adaptation weights ──
        self._baseline_state = copy.deepcopy(vae_model.state_dict())

        # ── Optimizer (only decoder params) ──
        self._decoder_params = list(self.vae.decoder.parameters())
        self._optimizer = torch.optim.Adam(
            self._decoder_params, lr=ADAPTIVE_LR,
        )

        # ── Previous frame for derivative computation ──
        self._prev_altitude = None
        self._prev_throttle = None
        self._prev_time = None

    # ── Public API ─────────────────────────────────────────────

    def process(
        self,
        fused_vector: np.ndarray,
        altitude_ft: float = 0.0,
        throttle: float = 0.0,
        timestamp: Optional[float] = None,
        fault_labels: Optional[Dict[str, Any]] = None,
    ) -> AdaptationResult:
        """
        Process a single frame through the adaptation manager.

        Parameters
        ----------
        fused_vector : np.ndarray
            (32,) — fused latent from the fusion pipeline.
        altitude_ft : float
            Current altitude [ft].
        throttle : float
            Current throttle position (0–1).
        timestamp : float | None
            Current timestamp [s].
        fault_labels : dict | None
            Fault labels from FaultInjector (if available).

        Returns
        -------
        AdaptationResult
        """
        self.state.total_frames += 1
        fused = np.asarray(fused_vector, dtype=np.float32)

        # ── Step 1: Safety guard check ──
        self._check_safety(fault_labels)

        # ── Step 2: Compute anomaly score ──
        fused_tensor = torch.from_numpy(fused).unsqueeze(0).to(self.device)
        anomaly_result = self.vae.predict_anomaly(fused_tensor)
        anomaly_score = anomaly_result["anomaly_score"]
        self.state.last_anomaly_score = anomaly_score

        # ── Step 3: Safety guard on anomaly spike ──
        if anomaly_score > ANOMALY_SPIKE_THRESHOLD:
            self._freeze(f"anomaly_spike ({anomaly_score:.1f}%)")
            adapted = False
        elif self.state.is_frozen:
            adapted = False
        else:
            # ── Step 4: Detect steady-state cruise ──
            is_steady = self._is_steady_state(altitude_ft, throttle, timestamp)

            # ── Step 5: Update EMA if nominal ──
            if anomaly_result["is_anomaly"] is False and is_steady:
                self.ema.update(fused)
                self.state.nominal_streak_s += self.dt
                adapted = self._try_adapt(fused)
            else:
                # Reset nominal streak
                if anomaly_result["is_anomaly"]:
                    self.state.nominal_streak_s = 0.0
                adapted = False

        # ── Step 6: Adaptive normalization ──
        drift_correction = None
        if self.ema.is_ready:
            drift_correction = self.ema.normalize(fused)
            self.state.drift_magnitude = float(np.linalg.norm(
                self.ema.mean - np.zeros(32)
            ))

        # Build output
        ema_baseline = self.ema.mean.copy() if self.ema.initialized else None

        return AdaptationResult(
            anomaly_result=anomaly_result,
            adapted=adapted,
            state=copy.deepcopy(self.state),
            ema_baseline=ema_baseline,
            drift_correction=drift_correction,
        )

    def reset(self) -> None:
        """Reset adaptation state but keep learned drift correction."""
        self.state = AdaptationState()
        self.ema = EMABaselineTracker(dim=32, momentum=EMA_MOMENTUM)

    def rollback(self) -> None:
        """Rollback VAE weights to pre-adaptation baseline."""
        self.vae.load_state_dict(self._baseline_state)
        self.state.is_frozen = False
        self.state.freeze_reason = ""
        self.state.total_updates = 0

    # ── Internal: Safety guard ─────────────────────────────────

    def _check_safety(self, fault_labels: Optional[Dict[str, Any]]) -> None:
        """Check for fault conditions and freeze if detected."""
        if fault_labels is None:
            return

        # Check faults_active
        faults_active = fault_labels.get("faults_active", [])
        if faults_active:
            self._freeze(f"fault_detected: {faults_active}")
            return

        # Check individual fault labels
        for ft_name, ft_info in fault_labels.items():
            if isinstance(ft_info, dict) and ft_info.get("active", False):
                self._freeze(f"fault_label: {ft_name}")
                return

    def _freeze(self, reason: str) -> None:
        """Freeze all online updates."""
        if not self.state.is_frozen:
            self.state.is_frozen = True
            self.state.freeze_reason = reason
            self.state.nominal_streak_s = 0.0

    # ── Internal: Steady-state detection ───────────────────────

    def _is_steady_state(
        self,
        altitude_ft: float,
        throttle: float,
        timestamp: Optional[float],
    ) -> bool:
        """
        Detect steady-state cruise: altitude and throttle derivatives
        are near zero.
        """
        if self._prev_altitude is None or timestamp is None:
            self._prev_altitude = altitude_ft
            self._prev_throttle = throttle
            self._prev_time = timestamp
            return False

        dt = timestamp - self._prev_time
        if dt <= 0:
            return False

        d_alt = abs(altitude_ft - self._prev_altitude) / dt
        d_thr = abs(throttle - self._prev_throttle) / dt

        self._prev_altitude = altitude_ft
        self._prev_throttle = throttle
        self._prev_time = timestamp

        # Steady state: small derivatives
        return (
            d_alt < STEADY_STATE_VEL_THRESH * 1000  # < 10 ft/s
            and d_thr < STEADY_STATE_VEL_THRESH      # < 0.01/s
        )

    # ── Internal: VAE decoder adaptation ───────────────────────

    def _try_adapt(self, fused: np.ndarray) -> bool:
        """
        If nominal streak is long enough, perform a decoder update step.

        Returns True if an update was performed.
        """
        if self.state.nominal_streak_s < NOMINAL_CONFIRM_S:
            return False

        if self.state.is_frozen:
            return False

        # Perform one gradient step on decoder
        self.vae.train()
        # Only decoder is trainable; encoder is frozen
        for p in self.vae.encoder.parameters():
            p.requires_grad = False

        x = torch.from_numpy(fused).unsqueeze(0).to(self.device)

        # Forward (encoder is frozen, only decoder adapts)
        with torch.no_grad():
            mu, logvar = self.vae.encoder(x)

        # Re-encode with grad for the decoder path
        z = self.vae.reparameterize(mu, logvar)
        x_recon = self.vae.decoder(z)

        # Reconstruction loss only (no KL — we're adapting to distribution shift)
        loss = F.mse_loss(x_recon, x)

        self._optimizer.zero_grad()
        loss.backward()
        self._optimizer.step()

        # Restore encoder
        for p in self.vae.encoder.parameters():
            p.requires_grad = True

        self.vae.eval()
        self.state.total_updates += 1
        self.state.nominal_streak_s = 0.0  # reset streak after update

        return True

    # ── Properties ─────────────────────────────────────────────

    @property
    def is_adapted(self) -> bool:
        """True if any online updates have been performed."""
        return self.state.total_updates > 0

    @property
    def is_frozen(self) -> bool:
        return self.state.is_frozen

    @property
    def nominal_streak(self) -> float:
        return self.state.nominal_streak_s
