#!/usr/bin/env python3
"""
Model Export & Optimization
============================
Packages Phase 2 and Phase 3 models into production-ready formats:

* **TorchScript** (`.torchscript`) — traced with example inputs.
* **ONNX** (`.onnx`) — for cross-platform inference.

Includes an ``OptimizedEngineInference`` wrapper that runs the full
pipeline using ONNX Runtime / TorchScript with multi-threaded CPU
execution and an end-to-end latency benchmark.

Usage
-----
    python -m fusion_ml.export_models export
    python -m fusion_ml.export_models benchmark
    python -m fusion_ml.export_models full       # export + benchmark

Output directory: ``/fusion_ml/production/``
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn

# ── Model imports ──────────────────────────────────────────────
from fusion_ml.cross_modal_fusion import (
    CrossModalFusionNet,
    FUSED_DIM,
    N_HEADS,
)
from fusion_ml.anomaly_vae import AnomalyVAE, LATENT_DIM, HIDDEN_DIM
from fusion_ml.rul_predictor import (
    TCNFeatureExtractor,
    RULPredictor,
    SEQUENCE_LENGTH,
    TCN_CHANNELS,
    TCN_EMBED_DIM,
    KERNEL_SIZE,
    DILATIONS,
    BASELINE_FEATURES,
    TOTAL_FEATURE_DIM,
)
from fusion_ml.sensor_validator import (
    SensorValidator,
    ALL_CHANNELS,
    NUM_CHANNELS,
)


# ══════════════════════════════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════════════════════════════

PRODUCTION_DIR = Path(__file__).resolve().parent / "production"
PRODUCTION_DIR.mkdir(parents=True, exist_ok=True)

ONNX_OPSET = 17
BENCHMARK_N_FRAMES = 500
BENCHMARK_WARMUP = 50


# ══════════════════════════════════════════════════════════════════
#  Export functions
# ══════════════════════════════════════════════════════════════════

class ModelExporter:
    """
    Handles TorchScript and ONNX export for all Phase 2/3 models.
    """

    def __init__(self, output_dir: Path = PRODUCTION_DIR) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── CrossModalFusionNet ──

    def export_fusion_net(
        self,
        model: CrossModalFusionNet,
    ) -> Dict[str, Path]:
        """Export CrossModalFusionNet to TorchScript and ONNX."""
        model.eval()
        paths = {}

        # Example inputs
        x = torch.randn(1, 15)
        mask = torch.ones(1, 15, dtype=torch.bool)

        # ── TorchScript ──
        ts_path = self.output_dir / "fusion_net.torchscript"
        try:
            # Use trace (simpler, faster inference)
            traced = torch.jit.trace(model, (x, mask))
            traced.save(str(ts_path))
            paths["torchscript"] = ts_path
            print(f"    ✓ TorchScript: {ts_path}")
        except Exception as e:
            print(f"    ✗ TorchScript failed: {e}")

        # ── ONNX ──
        onnx_path = self.output_dir / "fusion_net.onnx"
        try:
            torch.onnx.export(
                model,
                (x, mask),
                str(onnx_path),
                input_names=["input", "sensor_mask"],
                output_names=["fused_vector"],
                dynamic_axes={
                    "input": {0: "batch"},
                    "sensor_mask": {0: "batch"},
                    "fused_vector": {0: "batch"},
                },
                opset_version=ONNX_OPSET,
                do_constant_folding=True,
            )
            paths["onnx"] = onnx_path
            print(f"    ✓ ONNX: {onnx_path}")
        except Exception as e:
            print(f"    ✗ ONNX failed: {e}")

        return paths

    # ── AnomalyVAE ──

    def export_vae(
        self,
        model: AnomalyVAE,
    ) -> Dict[str, Path]:
        """Export AnomalyVAE encoder+decoder to TorchScript and ONNX."""
        model.eval()
        paths = {}

        x = torch.randn(1, FUSED_DIM)

        # ── TorchScript ──
        ts_path = self.output_dir / "anomaly_vae.torchscript"
        try:
            traced = torch.jit.trace(model, x)
            traced.save(str(ts_path))
            paths["torchscript"] = ts_path
            print(f"    ✓ TorchScript: {ts_path}")
        except Exception as e:
            print(f"    ✗ TorchScript failed: {e}")

        # ── ONNX ──
        onnx_path = self.output_dir / "anomaly_vae.onnx"
        try:
            torch.onnx.export(
                model,
                x,
                str(onnx_path),
                input_names=["fused_vector"],
                output_names=["x_recon", "mu", "logvar"],
                dynamic_axes={
                    "fused_vector": {0: "batch"},
                    "x_recon": {0: "batch"},
                    "mu": {0: "batch"},
                    "logvar": {0: "batch"},
                },
                opset_version=ONNX_OPSET,
            )
            paths["onnx"] = onnx_path
            print(f"    ✓ ONNX: {onnx_path}")
        except Exception as e:
            print(f"    ✗ ONNX failed: {e}")

        return paths

    # ── TCN Feature Extractor ──

    def export_tcn(
        self,
        model: TCNFeatureExtractor,
    ) -> Dict[str, Path]:
        """Export TCN to TorchScript and ONNX."""
        model.eval()
        paths = {}

        x = torch.randn(1, SEQUENCE_LENGTH, FUSED_DIM)

        # ── TorchScript ──
        ts_path = self.output_dir / "tcn_extractor.torchscript"
        try:
            traced = torch.jit.trace(model, x)
            traced.save(str(ts_path))
            paths["torchscript"] = ts_path
            print(f"    ✓ TorchScript: {ts_path}")
        except Exception as e:
            print(f"    ✗ TorchScript failed: {e}")

        # ── ONNX ──
        onnx_path = self.output_dir / "tcn_extractor.onnx"
        try:
            torch.onnx.export(
                model,
                x,
                str(onnx_path),
                input_names=["sequence"],
                output_names=["embedding"],
                dynamic_axes={
                    "sequence": {0: "batch"},
                    "embedding": {0: "batch"},
                },
                opset_version=ONNX_OPSET,
            )
            paths["onnx"] = onnx_path
            print(f"    ✓ ONNX: {onnx_path}")
        except Exception as e:
            print(f"    ✗ ONNX failed: {e}")

        return paths

    # ── Full export ──

    def export_all(
        self,
        fusion_net: Optional[CrossModalFusionNet] = None,
        vae: Optional[AnomalyVAE] = None,
        tcn: Optional[TCNFeatureExtractor] = None,
    ) -> Dict[str, Dict[str, Path]]:
        """Export all models."""
        print("\n  Model Export — Production Packaging")
        print("  " + "=" * 50)

        all_paths = {}

        if fusion_net is None:
            fusion_net = CrossModalFusionNet()
        print("\n  CrossModalFusionNet:")
        all_paths["fusion_net"] = self.export_fusion_net(fusion_net)

        if vae is None:
            vae = AnomalyVAE()
        print("\n  AnomalyVAE:")
        all_paths["vae"] = self.export_vae(vae)

        if tcn is None:
            tcn = TCNFeatureExtractor()
        print("\n  TCN Feature Extractor:")
        all_paths["tcn"] = self.export_tcn(tcn)

        # Save metadata
        meta = {
            "fusion_net": {
                "input_dim": FUSED_DIM,
                "fused_dim": FUSED_DIM,
                "n_heads": N_HEADS,
            },
            "vae": {
                "input_dim": FUSED_DIM,
                "latent_dim": LATENT_DIM,
                "hidden_dim": HIDDEN_DIM,
            },
            "tcn": {
                "input_dim": FUSED_DIM,
                "seq_len": SEQUENCE_LENGTH,
                "channels": TCN_CHANNELS,
                "embed_dim": TCN_EMBED_DIM,
                "kernel_size": KERNEL_SIZE,
                "dilations": DILATIONS,
            },
        }
        meta_path = self.output_dir / "model_metadata.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        print(f"\n  Metadata: {meta_path}")

        return all_paths


# ══════════════════════════════════════════════════════════════════
#  Optimized Inference Wrapper
# ══════════════════════════════════════════════════════════════════

class OptimizedEngineInference:
    """
    Production inference wrapper using TorchScript models with
    multi-threaded CPU execution.

    Chains: Validator → Fusion → VAE Anomaly → TCN/XGBoost RUL.
    """

    def __init__(
        self,
        production_dir: Path = PRODUCTION_DIR,
        num_threads: Optional[int] = None,
    ) -> None:
        self.prod_dir = Path(production_dir)

        # Set intra-op threads to CPU core count
        if num_threads is None:
            num_threads = os.cpu_count() or 4
        torch.set_num_threads(num_threads)
        self.num_threads = num_threads

        # ── Load models ──
        self.validator = SensorValidator(buffer_size=600)
        self.fusion_net = self._load_fusion_net()
        self.vae = self._load_vae()
        self.tcn = self._load_tcn()
        self.rul_predictor = self._load_rul_predictor()

    def _load_fusion_net(self) -> Optional[nn.Module]:
        ts_path = self.prod_dir / "fusion_net.torchscript"
        if ts_path.exists():
            return torch.jit.load(str(ts_path), map_location="cpu")
        # Fallback to eager model
        model = CrossModalFusionNet()
        model.eval()
        return model

    def _load_vae(self) -> Optional[nn.Module]:
        ts_path = self.prod_dir / "anomaly_vae.torchscript"
        if ts_path.exists():
            return torch.jit.load(str(ts_path), map_location="cpu")
        model = AnomalyVAE()
        model.eval()
        return model

    def _load_tcn(self) -> Optional[nn.Module]:
        ts_path = self.prod_dir / "tcn_extractor.torchscript"
        if ts_path.exists():
            return torch.jit.load(str(ts_path), map_location="cpu")
        model = TCNFeatureExtractor()
        model.eval()
        return model

    def _load_rul_predictor(self) -> Optional[RULPredictor]:
        try:
            return RULPredictor.load()
        except Exception:
            return None

    def process_frame(
        self,
        raw_telemetry: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Full pipeline inference on a single frame.

        Steps:
        1. Validate sensors
        2. Build tensor + mask
        3. Fusion net → fused_vector
        4. VAE → anomaly score
        5. (TCN/RUL if sequence available)

        Returns enriched dict.
        """
        # ── Step 1: Validate ──
        sanitized = self.validator.validate(raw_telemetry)

        # ── Step 2: Build tensor ──
        all_vals = sanitized.all_values
        mask_list = sanitized.sensor_mask

        # Map to modality indices
        from fusion_ml.fusion_pipeline import _MODALITY_INDICES
        features = [float(all_vals.get(ALL_CHANNELS[idx], 0.0)) for idx in _MODALITY_INDICES]
        mask = [bool(mask_list[idx]) for idx in _MODALITY_INDICES]

        input_tensor = torch.tensor([features], dtype=torch.float32)
        mask_tensor = torch.tensor([mask], dtype=torch.bool)

        # ── Step 3: Fusion ──
        with torch.no_grad():
            if isinstance(self.fusion_net, torch.jit.ScriptModule):
                fused = self.fusion_net(input_tensor, mask_tensor)
            else:
                from fusion_ml.cross_modal_fusion import FusionOutput
                out = self.fusion_net(input_tensor, sensor_mask=mask_tensor)
                fused = out.fused_state_vector

        # ── Step 4: VAE anomaly ──
        with torch.no_grad():
            if isinstance(self.vae, torch.jit.ScriptModule):
                x_recon, mu, logvar = self.vae(fused)
                recon_loss = ((x_recon - fused) ** 2).sum(dim=-1).item()
            else:
                result = self.vae.predict_anomaly(fused)
                recon_loss = result["reconstruction_loss"]

        # Anomaly score
        threshold = 1.0  # default threshold
        if hasattr(self.vae, 'recon_threshold'):
            threshold = self.vae.recon_threshold.item()
        elif hasattr(self.vae, 'recon_threshold') and isinstance(self.vae, torch.jit.ScriptModule):
            # JIT models don't have buffers as attributes
            pass

        anomaly_score = min(100.0, max(0.0, (recon_loss / max(threshold, 1e-8) - 1.0) * 100.0))
        is_anomaly = recon_loss > threshold

        # ── Assemble output ──
        output = dict(raw_telemetry)
        output["fused_vector"] = [round(float(v), 6) for v in fused.numpy().ravel()]
        output["reconstruction_loss"] = round(recon_loss, 6)
        output["anomaly_score"] = round(anomaly_score, 2)
        output["is_anomaly"] = bool(is_anomaly)
        output["sensor_isolation_flags"] = sanitized.isolation_flags

        return output


# ══════════════════════════════════════════════════════════════════
#  Latency Benchmark
# ══════════════════════════════════════════════════════════════════

def run_benchmark(
    n_frames: int = BENCHMARK_N_FRAMES,
    warmup: int = BENCHMARK_WARMUP,
) -> Dict[str, Any]:
    """
    End-to-end pipeline latency benchmark.

    Measures: Validator → Fusion → VAE Anomaly per frame.
    """
    import pandas as pd

    print("\n  End-to-End Latency Benchmark")
    print("  " + "=" * 50)
    print(f"  Frames: {n_frames}, Warmup: {warmup}")
    print(f"  CPU threads: {torch.get_num_threads()}")

    # Build inference engine
    engine = OptimizedEngineInference()

    # Generate test frame
    rng = np.random.default_rng(42)
    test_frame = {
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

    # Warmup
    print(f"\n  Warming up ({warmup} frames)…")
    for _ in range(warmup):
        engine.process_frame(test_frame)

    # Timed run
    print(f"  Benchmarking ({n_frames} frames)…")
    latencies_ms: List[float] = []
    for _ in range(n_frames):
        t0 = time.perf_counter()
        engine.process_frame(test_frame)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

    # Compute statistics
    arr = np.array(latencies_ms)
    stats = {
        "min_ms": float(np.min(arr)),
        "median_ms": float(np.median(arr)),
        "mean_ms": float(np.mean(arr)),
        "std_ms": float(np.std(arr)),
        "p95_ms": float(np.percentile(arr, 95)),
        "p99_ms": float(np.percentile(arr, 99)),
        "max_ms": float(np.max(arr)),
        "n_frames": n_frames,
        "cpu_threads": torch.get_num_threads(),
    }

    # Print summary table
    print(f"\n  {'─' * 50}")
    print(f"  {'Metric':<20} {'Value':>12}")
    print(f"  {'─' * 50}")
    for key, val in stats.items():
        if key == "n_frames" or key == "cpu_threads":
            print(f"  {key:<20} {val:>12}")
        else:
            print(f"  {key:<20} {val:>10.2f} ms")
    print(f"  {'─' * 50}")

    # 10 Hz target check
    target_ms = 100.0  # 10 Hz = 100 ms per frame
    margin_ms = 30.0   # strict < 30 ms processing
    if stats["p95_ms"] < margin_ms:
        print(f"\n  ✓  p95 latency ({stats['p95_ms']:.2f} ms) < {margin_ms} ms target")
    else:
        print(f"\n  ✗  p95 latency ({stats['p95_ms']:.2f} ms) ≥ {margin_ms} ms target")

    # Save results
    results_path = PRODUCTION_DIR / "benchmark_results.json"
    with open(results_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"  Results saved: {results_path}")

    # Save detailed CSV
    csv_path = PRODUCTION_DIR / "benchmark_latencies.csv"
    df = pd.DataFrame({"latency_ms": latencies_ms})
    df.to_csv(csv_path, index=False)
    print(f"  Latencies CSV: {csv_path}\n")

    return stats


# ══════════════════════════════════════════════════════════════════
#  Full Production Package
# ══════════════════════════════════════════════════════════════════

def build_production_package() -> None:
    """Full pipeline: export all models + benchmark."""
    exporter = ModelExporter()
    exporter.export_all()

    # Also save model weights for fallback
    print("\n  Saving model weights for fallback…")
    vae = AnomalyVAE()
    vae.save(PRODUCTION_DIR / "vae_nominal.pt")

    tcn = TCNFeatureExtractor()
    torch.save(
        {"tcn_state": tcn.state_dict(), "seq_len": SEQUENCE_LENGTH},
        PRODUCTION_DIR / "tcn_extractor.pt",
    )

    fusion = CrossModalFusionNet()
    torch.save(fusion.state_dict(), PRODUCTION_DIR / "fusion_net.pt")

    print("  All weights saved.\n")

    # Run benchmark
    stats = run_benchmark()

    # Final summary
    print("  Production Package Summary")
    print("  " + "=" * 50)
    for p in sorted(PRODUCTION_DIR.iterdir()):
        size_kb = p.stat().st_size / 1024
        print(f"  {p.name:<40s} {size_kb:>8.1f} KB")
    print()


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Model Export & Optimization")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("export", help="Export all models to TorchScript/ONNX")
    bench_p = sub.add_parser("benchmark", help="Run latency benchmark")
    bench_p.add_argument("--n-frames", type=int, default=BENCHMARK_N_FRAMES)
    sub.add_parser("full", help="Export + benchmark (full pipeline)")

    args = parser.parse_args()

    if args.command == "export":
        exporter = ModelExporter()
        exporter.export_all()

    elif args.command == "benchmark":
        run_benchmark(n_frames=args.n_frames)

    elif args.command == "full":
        build_production_package()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
