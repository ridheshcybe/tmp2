#!/usr/bin/env python3
"""
Cross-Modal Sensor Fusion Network
==================================
PyTorch neural architecture for fusing heterogeneous aero-engine
sensor modalities (thermal, mechanical, fluid) into a compact latent
representation.

Architecture
------------
1. Three modality-specific embedding projections (→ d_model = 64).
2. Multi-Head Cross-Attention (4 heads): Thermal modality attends to
   Mechanical and Fluid contexts.
3. Gated residual connections preserve individual sensor fidelity.
4. Sensor-mask support: isolated channels are zeroed in attention.
5. Physics-Informed Loss penalises thermodynamic inconsistencies.

Output
------
* ``fused_state_vector``: 32-dim latent for downstream anomaly/RUL models.
* ``attention_weights``: dict of attention maps for explainability.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


# ══════════════════════════════════════════════════════════════════
#  Modality definitions
# ══════════════════════════════════════════════════════════════════

# Sensor channel names mapped to ALL_CHANNELS indices (from sensor_validator)
# ALL_CHANNELS = [
#   0  rpm,  1  map_kpa,  2  fuel_flow_lph,  3  equivalence_ratio,
#   4  cht_1_c,  5  cht_2_c,  6  cht_3_c,  7  cht_4_c,
#   8  egt_1_c,  9  egt_2_c, 10  egt_3_c, 11  egt_4_c,
#  12  oil_pressure_kpa, 13  oil_temp_c, 14  vibration_rms_g,
#  15  air_density_kg_m3, 16  ambient_temp_c, 17  ambient_pressure_kpa,
# ]

MODALITY_THERMAL_INDICES = [4, 5, 6, 7, 8, 9, 10, 11, 16]  # CHT×4, EGT×4, Ambient_Temp
MODALITY_MECHANICAL_INDICES = [0, 1, 14]                     # RPM, MAP, Vibration_RMS
MODALITY_FLUID_INDICES = [2, 12, 13]                         # Fuel_Flow, Oil_Pressure, Oil_Temp

MODALITY_DIMS = {
    "thermal":    len(MODALITY_THERMAL_INDICES),    # 9
    "mechanical": len(MODALITY_MECHANICAL_INDICES),  # 3
    "fluid":      len(MODALITY_FLUID_INDICES),      # 3
}

# Total input features across all three modalities
TOTAL_INPUT_DIM = sum(MODALITY_DIMS.values())  # 15


# ══════════════════════════════════════════════════════════════════
#  Network hyperparameters
# ══════════════════════════════════════════════════════════════════

D_MODEL = 64        # shared embedding dimension
N_HEADS = 4         # cross-attention heads
D_FFN = 128         # feed-forward hidden dim
FUSED_DIM = 32      # final output latent dimension
DROPOUT = 0.1


# ══════════════════════════════════════════════════════════════════
#  Sub-modules
# ══════════════════════════════════════════════════════════════════

class ModalityEmbedding(nn.Module):
    """
    Linear projection from raw sensor space → d_model.

    Applies LayerNorm + dropout after projection for training stability.
    """

    def __init__(self, in_dim: int, d_model: int = D_MODEL) -> None:
        super().__init__()
        self.proj = nn.Linear(in_dim, d_model)
        self.norm = nn.LayerNorm(d_model)
        self.drop = nn.Dropout(DROPOUT)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Parameters
        ----------
        x : (B, in_dim)

        Returns
        -------
        (B, d_model)
        """
        return self.drop(self.norm(self.proj(x)))


class GatedResidualBlock(nn.Module):
    """
    Gated residual connection: output = gate ⊙ (x + sublayer(x)) + (1 − gate) ⊙ x.

    The gate is a learned sigmoid that controls how much of the
    sublayer's contribution is mixed in — preserving original sensor
    fidelity when the sublayer output is not helpful.
    """

    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.norm = nn.LayerNorm(d_model)
        self.gate_proj = nn.Linear(d_model * 2, d_model)

    def forward(
        self,
        x: torch.Tensor,
        sublayer_out: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Parameters
        ----------
        x : (B, d_model) — residual input
        sublayer_out : (B, d_model) — output of the sublayer (e.g. attention)

        Returns
        -------
        output : (B, d_model)
        gate_values : (B, d_model) — for interpretability
        """
        combined = torch.cat([x, sublayer_out], dim=-1)       # (B, 2*d_model)
        gate = torch.sigmoid(self.gate_proj(combined))        # (B, d_model)
        output = gate * (x + sublayer_out) + (1.0 - gate) * x
        output = self.norm(output)
        return output, gate


class CrossModalAttention(nn.Module):
    """
    Multi-Head Cross-Attention where the query comes from one
    modality and keys/values come from other modalities.

    Supports sensor masking: isolated sensors have their
    corresponding key/value positions zeroed and attention weights
    set to −∞ (masked out).
    """

    def __init__(
        self,
        d_model: int = D_MODEL,
        n_heads: int = N_HEADS,
        dropout: float = DROPOUT,
    ) -> None:
        super().__init__()
        assert d_model % n_heads == 0, "d_model must be divisible by n_heads"
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_k = d_model // n_heads

        self.W_q = nn.Linear(d_model, d_model)
        self.W_k = nn.Linear(d_model, d_model)
        self.W_v = nn.Linear(d_model, d_model)
        self.W_o = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)
        self.scale = math.sqrt(self.d_k)

    def forward(
        self,
        query: torch.Tensor,
        kv_context: torch.Tensor,
        mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Parameters
        ----------
        query : (B, T_q, d_model)  — e.g. thermal tokens
        kv_context : (B, T_kv, d_model) — e.g. mechanical + fluid tokens
        mask : (B, T_kv) — True = valid, False = masked out

        Returns
        -------
        output : (B, T_q, d_model)
        attn_weights : (B, n_heads, T_q, T_kv)
        """
        B = query.shape[0]
        T_q = query.shape[1]
        T_kv = kv_context.shape[1]

        Q = self.W_q(query).view(B, T_q, self.n_heads, self.d_k).transpose(1, 2)
        K = self.W_k(kv_context).view(B, T_kv, self.n_heads, self.d_k).transpose(1, 2)
        V = self.W_v(kv_context).view(B, T_kv, self.n_heads, self.d_k).transpose(1, 2)

        # Scaled dot-product attention
        scores = torch.matmul(Q, K.transpose(-2, -1)) / self.scale  # (B, H, T_q, T_kv)

        # Apply mask: broadcast over heads and query positions
        if mask is not None:
            # mask: (B, T_kv) → (B, 1, 1, T_kv)
            mask_expanded = mask.unsqueeze(1).unsqueeze(2)
            scores = scores.masked_fill(~mask_expanded, float("-inf"))

        attn_weights = F.softmax(scores, dim=-1)
        # Replace NaN from all-masked rows with 0
        attn_weights = attn_weights.nan_to_num(0.0)

        attn_weights = self.dropout(attn_weights)
        context = torch.matmul(attn_weights, V)  # (B, H, T_q, d_k)
        context = context.transpose(1, 2).contiguous().view(B, T_q, self.d_model)
        output = self.W_o(context)

        return output, attn_weights


class FFN(nn.Module):
    """Position-wise feed-forward network."""

    def __init__(self, d_model: int = D_MODEL, d_ff: int = D_FFN) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),
            nn.Dropout(DROPOUT),
            nn.Linear(d_ff, d_model),
            nn.Dropout(DROPOUT),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ══════════════════════════════════════════════════════════════════
#  Output dataclass
# ══════════════════════════════════════════════════════════════════

@dataclass
class FusionOutput:
    """
    Output of :meth:`CrossModalFusionNet.forward`.

    Attributes
    ----------
    fused_state_vector : torch.Tensor
        (B, 32) — fused latent representation for downstream models.
    attention_weights : dict
        ``{"cross_modal": (B, H, T_q, T_kv), ...}`` for explainability.
    modality_embeddings : dict
        Pre-attention embeddings per modality.
    gate_values : dict
        Gated residual gate activations per fusion stage.
    """

    fused_state_vector: torch.Tensor
    attention_weights: Dict[str, torch.Tensor] = field(default_factory=dict)
    modality_embeddings: Dict[str, torch.Tensor] = field(default_factory=dict)
    gate_values: Dict[str, torch.Tensor] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════
#  Main Network
# ══════════════════════════════════════════════════════════════════

class CrossModalFusionNet(nn.Module):
    """
    Cross-Modal Sensor Fusion Network for Aero Engine Telemetry.

    Fuses three sensor modalities (Thermal, Mechanical, Fluid) via
    cross-attention and gated residuals into a 32-dimensional latent
    vector for anomaly detection and RUL prediction.

    Parameters
    ----------
    d_model : int
        Shared embedding dimension (default 64).
    n_heads : int
        Number of attention heads (default 4).
    fused_dim : int
        Output latent dimension (default 32).
    dropout : float
        Dropout rate (default 0.1).
    """

    def __init__(
        self,
        d_model: int = D_MODEL,
        n_heads: int = N_HEADS,
        fused_dim: int = FUSED_DIM,
        dropout: float = DROPOUT,
    ) -> None:
        super().__init__()
        self.d_model = d_model
        self.fused_dim = fused_dim

        # ── Modality embeddings ──
        self.thermal_embed = ModalityEmbedding(MODALITY_DIMS["thermal"], d_model)
        self.mechanical_embed = ModalityEmbedding(MODALITY_DIMS["mechanical"], d_model)
        self.fluid_embed = ModalityEmbedding(MODALITY_DIMS["fluid"], d_model)

        # ── Cross-attention: Thermal attends to Mechanical + Fluid ──
        self.cross_attn = CrossModalAttention(d_model, n_heads, dropout)
        self.cross_attn_gate = GatedResidualBlock(d_model)

        # ── Self-attention on concatenated context (Mech + Fluid) ──
        # Uses standard nn.MultiheadAttention for efficiency
        self.context_self_attn = nn.MultiheadAttention(
            embed_dim=d_model, num_heads=n_heads,
            dropout=dropout, batch_first=True,
        )
        self.context_norm = nn.LayerNorm(d_model)

        # ── Feed-forward after cross-attention ──
        self.ffn = FFN(d_model, d_model * 2)
        self.ffn_gate = GatedResidualBlock(d_model)

        # ── Fusion head: project concatenated tokens → fused_dim ──
        # We concatenate [thermal_out, mech_out, fluid_out] (3 × d_model)
        # and project down to fused_dim.
        self.fusion_proj = nn.Sequential(
            nn.Linear(d_model * 3, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, fused_dim),
        )

        # ── Layer norms for final output ──
        self.output_norm = nn.LayerNorm(fused_dim)

    def forward(
        self,
        x: torch.Tensor,
        sensor_mask: Optional[torch.Tensor] = None,
    ) -> FusionOutput:
        """
        Forward pass.

        Parameters
        ----------
        x : torch.Tensor
            (B, 15) — raw sensor features concatenated in ALL_CHANNELS
            order, subset to the 15 modality features.

            Feature order: [
              CHT_1..4, EGT_1..4, Ambient_Temp,    (9 thermal)
              RPM, MAP, Vibration_RMS,               (3 mechanical)
              Fuel_Flow, Oil_Pressure, Oil_Temp       (3 fluid)
            ]

            Or use :meth:`from_full_frame` to extract from a 18-channel
            ALL_CHANNELS tensor.

        sensor_mask : torch.Tensor | None
            (B, 15) — True = valid, False = isolated.  Isolated
            features are zeroed before embedding.  If *None*, all
            sensors are assumed valid.

        Returns
        -------
        FusionOutput
        """
        B = x.shape[0]

        # ── Zero out isolated sensors ──
        if sensor_mask is not None:
            x = x.clone()
            x[~sensor_mask] = 0.0

        # ── Split into modalities ──
        x_thermal = x[:, :9]        # (B, 9)
        x_mech = x[:, 9:12]         # (B, 3)
        x_fluid = x[:, 12:15]       # (B, 3)

        # ── Embed each modality → (B, 1, d_model) tokens ──
        e_thermal = self.thermal_embed(x_thermal).unsqueeze(1)    # (B, 1, d_model)
        e_mech = self.mechanical_embed(x_mech).unsqueeze(1)       # (B, 1, d_model)
        e_fluid = self.fluid_embed(x_fluid).unsqueeze(1)          # (B, 1, d_model)

        modality_embs = {
            "thermal": e_thermal.squeeze(1),
            "mechanical": e_mech.squeeze(1),
            "fluid": e_fluid.squeeze(1),
        }

        # ── Context: self-attention on Mechanical + Fluid ──
        context = torch.cat([e_mech, e_fluid], dim=1)  # (B, 2, d_model)

        # Build mask for context: if sensor_mask provided, mask out
        # isolated mechanical/fluid sensors (indices 9-14 in full frame)
        ctx_mask = None
        if sensor_mask is not None:
            # sensor_mask[:, 9:12] = mechanical, sensor_mask[:, 12:15] = fluid
            mech_valid = sensor_mask[:, 9:12]   # (B, 3)
            fluid_valid = sensor_mask[:, 12:15]  # (B, 3)
            # We have 2 context tokens (mech, fluid), but each token
            # represents its whole modality.  Mask a token only if ALL
            # its sensors are invalid.
            mech_token_valid = mech_valid.any(dim=-1, keepdim=True)   # (B, 1)
            fluid_token_valid = fluid_valid.any(dim=-1, keepdim=True) # (B, 1)
            ctx_mask = torch.cat([mech_token_valid, fluid_token_valid], dim=-1)  # (B, 2)

            # Zero out isolated context features
            context = context.clone()
            for b in range(B):
                if not mech_token_valid[b]:
                    context[b, 0, :] = 0.0
                if not fluid_token_valid[b]:
                    context[b, 1, :] = 0.0

        context_out, _ = self.context_self_attn(context, context, context)
        context_out = self.context_norm(context_out + context)  # residual

        # ── Cross-attention: Thermal attends to context ──
        # Build key/value mask: True = valid token
        kv_mask = ctx_mask  # (B, 2) or None

        attn_out, attn_weights = self.cross_attn(
            query=e_thermal,
            kv_context=context_out,
            mask=kv_mask,
        )

        # ── Gated residual on cross-attention ──
        thermal_out, gate_attn = self.cross_attn_gate(e_thermal, attn_out)

        # ── Feed-forward with gated residual ──
        ffn_out = self.ffn(thermal_out)
        thermal_out, gate_ffn = self.ffn_gate(thermal_out, ffn_out)

        # ── Project fused representation ──
        # Flatten all three modality outputs
        mech_out = e_mech  # context didn't change mech embedding shape
        fluid_out = e_fluid
        fused_input = torch.cat([thermal_out, mech_out, fluid_out], dim=-1)  # (B, 3*d_model)
        fused = self.fusion_proj(fused_input)   # (B, fused_dim)
        fused = self.output_norm(fused)

        return FusionOutput(
            fused_state_vector=fused,
            attention_weights={
                "cross_modal": attn_weights,     # (B, H, 1, 2)
            },
            modality_embeddings=modality_embs,
            gate_values={
                "cross_attn_gate": gate_attn.squeeze(1),  # (B, d_model)
                "ffn_gate": gate_ffn.squeeze(1),          # (B, d_model)
            },
        )

    @classmethod
    def from_full_frame(
        cls,
        frame: torch.Tensor,
        sensor_indices: Optional[List[int]] = None,
        **kwargs,
    ) -> "CrossModalFusionNet":
        """
        Convenience: extract the 15 modality features from an
        18-channel ALL_CHANNELS tensor.

        Parameters
        ----------
        frame : (B, 18) — full ALL_CHANNELS tensor
        sensor_indices : list of 15 indices into the 18-dim vector
        """
        # Default: select the 15 modality features from ALL_CHANNELS
        if sensor_indices is None:
            sensor_indices = (
                MODALITY_THERMAL_INDICES
                + MODALITY_MECHANICAL_INDICES
                + MODALITY_FLUID_INDICES
            )
        subset = frame[:, sensor_indices]
        net = cls(**kwargs)
        return net, subset


# ══════════════════════════════════════════════════════════════════
#  Physics-Constrained Loss
# ══════════════════════════════════════════════════════════════════

class PhysicsConstrainedLoss(nn.Module):
    """
    Combined loss for the cross-modal fusion network.

    Components
    ----------
    1. **Base task loss**: MSE or Cosine similarity between predicted
       and target fused_state_vector.
    2. **Thermodynamic consistency penalty**: If Fuel_Flow increases
       but neither RPM nor EGT/CHT increase, a penalty is added.
       This encodes the physical law that fuel energy must appear as
       mechanical work (RPM) or heat (EGT/CHT).

    Parameters
    ----------
    base_loss_type : str
        ``"mse"`` or ``"cosine"`` (default ``"mse"``).
    physics_weight : float
        Weight of the thermodynamic penalty term (default 0.1).
    """

    def __init__(
        self,
        base_loss_type: str = "mse",
        physics_weight: float = 0.1,
    ) -> None:
        super().__init__()
        self.base_loss_type = base_loss_type
        self.physics_weight = physics_weight

    def forward(
        self,
        predicted: torch.Tensor,
        target: torch.Tensor,
        raw_inputs: Optional[torch.Tensor] = None,
        sensor_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """
        Parameters
        ----------
        predicted : (B, 32) — network output
        target : (B, 32) — target fused state
        raw_inputs : (B, 15) — raw sensor features (for physics penalty)
        sensor_mask : (B, 15) — True = valid

        Returns
        -------
        total_loss : scalar
        loss_components : dict of scalar loss values
        """
        # ── Base task loss ──
        if self.base_loss_type == "cosine":
            base_loss = 1.0 - F.cosine_similarity(predicted, target, dim=-1).mean()
        else:
            base_loss = F.mse_loss(predicted, target)

        components = {"base_loss": base_loss.item()}

        # ── Physics constraint penalty ──
        physics_penalty = torch.tensor(0.0, device=predicted.device)
        if raw_inputs is not None:
            physics_penalty = self._thermodynamic_penalty(raw_inputs, sensor_mask)
            components["physics_penalty"] = physics_penalty.item()

        total = base_loss + self.physics_weight * physics_penalty
        components["total_loss"] = total.item()

        return total, components

    def _thermodynamic_penalty(
        self,
        x: torch.Tensor,
        sensor_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        Penalise thermodynamic inconsistency:
        Fuel_Flow ↑ without RPM ↑ or EGT/CHT ↑ = violation.

        Feature layout in x (15-dim):
          [0-8: thermal (CHT×4, EGT×4, Ambient_Temp)]
          [9-11: mechanical (RPM, MAP, Vibration)]
          [12-14: fluid (Fuel_Flow, Oil_Pressure, Oil_Temp)]

        We compute a delta-based penalty using a simple heuristic:
        For each sample, normalise features and check if
        fuel_flow_delta > 0 AND (rpm_delta < 0 AND egt_delta < 0).
        """
        B = x.shape[0]

        # Extract relevant channels
        fuel_flow = x[:, 0]     # Will remap below
        # Actually, x is in modality order: [thermal(9), mech(3), fluid(3)]
        # fluid: x[:, 12] = fuel_flow, x[:, 9] = RPM
        # thermal: x[:, 4:8] = EGT, x[:, 0:4] = CHT

        fuel = x[:, 12]   # Fuel_Flow
        rpm = x[:, 9]     # RPM
        egt = x[:, 4:8].mean(dim=-1)  # average EGT across cylinders
        cht = x[:, 0:4].mean(dim=-1)  # average CHT across cylinders

        # Normalise to [0, 1] range (approximate, using typical bounds)
        fuel_n = fuel / 60.0
        rpm_n = rpm / 6000.0
        egt_n = egt / 1100.0
        cht_n = cht / 350.0

        # Delta from nominal (use batch mean as proxy for nominal)
        fuel_delta = fuel_n - fuel_n.mean()
        rpm_delta = rpm_n - rpm_n.mean()
        egt_delta = egt_n - egt_n.mean()
        cht_delta = cht_n - cht_n.mean()

        # Combined thermal delta
        thermal_delta = torch.max(egt_delta, cht_delta)

        # Violation: fuel increases but neither RPM nor thermal increases
        # Use smooth approximation: ReLU(fuel_delta) × ReLU(-rpm_delta) × ReLU(-thermal_delta)
        violation = (
            F.relu(fuel_delta)
            * F.relu(-rpm_delta)
            * F.relu(-thermal_delta)
        )

        # If mask provided, zero out penalty for isolated sensors
        if sensor_mask is not None:
            # If fuel flow sensor is isolated, skip penalty
            fuel_valid = sensor_mask[:, 12].float()
            violation = violation * fuel_valid

        return violation.mean()


# ══════════════════════════════════════════════════════════════════
#  Latency benchmark
# ══════════════════════════════════════════════════════════════════

def benchmark_latency(n_runs: int = 200) -> Dict[str, float]:
    """
    Measure forward-pass latency on CPU for batch_size = 1.

    Returns
    -------
    dict with ``mean_ms``, ``std_ms``, ``max_ms``, ``p95_ms``.
    """
    net = CrossModalFusionNet()
    net.eval()

    x = torch.randn(1, 15)  # single sample

    # Warm up
    with torch.no_grad():
        for _ in range(50):
            net(x)

    # Timed runs
    times = []
    with torch.no_grad():
        for _ in range(n_runs):
            t0 = time.perf_counter()
            net(x)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000)  # ms

    times_arr = torch.tensor(times)
    return {
        "mean_ms": times_arr.mean().item(),
        "std_ms": times_arr.std().item(),
        "max_ms": times_arr.max().item(),
        "p95_ms": times_arr.quantile(0.95).item(),
    }


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n  Cross-Modal Fusion Network — Summary")
    print("  " + "=" * 50)

    net = CrossModalFusionNet()
    n_params = sum(p.numel() for p in net.parameters())
    print(f"  Parameters:     {n_params:,}")
    print(f"  d_model:        {D_MODEL}")
    print(f"  n_heads:        {N_HEADS}")
    print(f"  fused_dim:      {FUSED_DIM}")
    print(f"  Input modalities:")
    for name, dim in MODALITY_DIMS.items():
        print(f"    {name:<12s}  {dim} features → d_model={D_MODEL}")

    # Forward pass demo
    x = torch.randn(1, 15)
    mask = torch.ones(1, 15, dtype=torch.bool)
    mask[0, 5] = False  # isolate CHT_2

    out = net(x, sensor_mask=mask)
    print(f"\n  Output shape:   {out.fused_state_vector.shape}")
    print(f"  Attn map shape: {out.attention_weights['cross_modal'].shape}")

    # Loss demo
    criterion = PhysicsConstrainedLoss()
    target = torch.randn(1, 32)
    loss, comps = criterion(out.fused_state_vector, target, raw_inputs=x)
    print(f"\n  Loss demo:")
    for k, v in comps.items():
        print(f"    {k:<20s}  {v:.6f}")

    # Latency benchmark
    print("\n  Running latency benchmark (CPU, batch=1)…")
    stats = benchmark_latency()
    print(f"    Mean:  {stats['mean_ms']:.2f} ms")
    print(f"    Std:   {stats['std_ms']:.2f} ms")
    print(f"    Max:   {stats['max_ms']:.2f} ms")
    print(f"    P95:   {stats['p95_ms']:.2f} ms")
    if stats["p95_ms"] < 15.0:
        print("    ✓  Latency target met (< 15 ms)")
    else:
        print("    ✗  Latency target NOT met (≥ 15 ms)")
    print()
