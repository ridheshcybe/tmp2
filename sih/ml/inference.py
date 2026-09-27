"""
Streaming inference — confidence, explainability, fallback.
===========================================================

:class:`InferencePipeline` streams telemetry rows through the trained bundle
(:mod:`ml.train` output) and returns, per row:

* anomaly score (0–100) + binary flag,
* fault class + probability (confidence),
* degradation severity + confidence,
* RUL (minutes) + 68 % interval, from tree variance,
* alert level (NONE / WATCH / ADVISORY / CRITICAL),
* explanations (human-readable).

:class:`FallbackAnalyzer` is the **model-unavailable fallback**: it never
raises, and produces a degraded-but-honest signal from physics residuals,
healthy residual statistics and trend rules — the dashboard keeps working
even if the model files are missing or corrupt.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Dict, List, Optional

import numpy as np

from ml.feature_engineering import FeatureExtractor, feature_names
from ml.physics_baseline import expected_sensors, residual_summary
from ml.labels import HEALTHY_LABEL

#: Rule-based recommended actions per fault class (demo-level guidance).
ACTIONS: Dict[str, str] = {
    "INJECTOR_DEGRADATION": "Inspect injector / fuel delivery on the affected cylinder; avoid high-throttle operation.",
    "MISFIRE": "Check spark plug, ignition lead and injector on the misfiring cylinder.",
    "LUBRICATION_FAILURE": "Inspect oil pump, filter and for leaks; monitor oil pressure — do not continue endurance ops.",
    "OVERHEATING": "Check cooling airflow, baffles and oil cooler; reduce power and descend if CHT keeps climbing.",
    "SENSOR_DRIFT": "Verify sensor calibration / wiring; treat readings as advisory until replaced.",
    "SENSOR_DROPOUT": "Sensor channel is frozen — replace sensor or check connector; health logic ignores the channel.",
    "ABNORMAL_VIBRATION": "Inspect engine mounts, propeller balance and accessories before next flight.",
    "ALTERNATOR_DEGRADATION": "Inspect alternator / regulator; battery is draining — plan early landing.",
}

#: Alert thresholds.
SEV_CRITICAL = 0.7
SEV_ADVISORY = 0.35
RUL_CRITICAL_MIN = 5.0
RUL_ADVISORY_MIN = 15.0
LOW_CONFIDENCE = 0.6


def _load_bundle(model_dir: str) -> Dict[str, object]:
    with open(f"{model_dir}/bundle.json", encoding="utf-8") as fh:
        return json.load(fh)


class InferencePipeline:
    """Streaming predictor wrapping the trained models."""

    def __init__(self, model_dir: str) -> None:
        import joblib

        self.model_dir = model_dir
        bundle = _load_bundle(model_dir)
        self.bundle = bundle
        self.feature_names = list(bundle["feature_names"])
        self.window_s = int(bundle.get("window_s", 60))
        self.trend_s = int(bundle.get("trend_s", 180))
        self.class_names = list(bundle["class_names"])
        self.anomaly_threshold = float(bundle["anomaly_threshold"])
        self.anomaly_scale = max(
            0.01, float(bundle.get("anomaly_val_decision_std", 0.05))
        )

        self._anomaly = joblib.load(f"{model_dir}/anomaly.joblib")
        self._scaler = joblib.load(f"{model_dir}/anomaly_scaler.joblib")
        self._clf = joblib.load(f"{model_dir}/classifier.joblib")
        self._deg = joblib.load(f"{model_dir}/degradation.joblib")
        self._rul = joblib.load(f"{model_dir}/rul.joblib")

        self._ext = FeatureExtractor(self.window_s, self.trend_s)

    # ── streaming ─────────────────────────────────────────────────────────

    def update(self, row: Dict[str, object]) -> Optional[Dict[str, object]]:
        """Ingest one row; returns a prediction once the window is warm."""
        self._ext.update(row)
        if not self._ext.warm:
            return None
        return self.predict(self._ext.features())

    def predict(self, features: Dict[str, float]) -> Dict[str, object]:
        """Predict on one feature vector (see :meth:`predict_row` for JSON-safe)."""
        X = np.asarray([[features[f] for f in self.feature_names]], dtype=float)

        # anomaly
        decision = float(self._anomaly.decision_function(self._scaler.transform(X))[0])
        anomaly_score = float(np.clip(100.0 * (self.anomaly_threshold - decision) / self.anomaly_scale, 0.0, 100.0))
        is_anomaly = bool(decision < self.anomaly_threshold)

        # classification
        proba = self._clf.predict_proba(X)[0]
        idx = int(np.argmax(proba))
        cls = self.class_names[idx]
        confidence = float(proba[idx])

        # degradation (tree variance → confidence)
        deg_preds = np.array([t.predict(X)[0] for t in self._deg.estimators_])
        severity = float(np.clip(np.mean(deg_preds), 0.0, 1.0))
        deg_conf = float(np.clip(1.0 - np.std(deg_preds) / 0.3, 0.0, 1.0))

        # RUL (log-scale trees → minutes + 68 % interval)
        rul_logs = np.array([t.predict(X)[0] for t in self._rul.estimators_])
        rul_mean = float(np.expm1(np.mean(rul_logs)))
        rul_std = float(np.std(rul_logs))
        rul_lo = max(0.0, float(np.expm1(np.mean(rul_logs) - rul_std)))
        rul_hi = float(np.expm1(np.mean(rul_logs) + rul_std))
        rul_conf = float(np.clip(1.0 - rul_std / 1.5, 0.0, 1.0))

        alert = _alert_level(
            is_anomaly, cls, severity, rul_mean, confidence
        )
        return {
            "anomaly_score": anomaly_score,
            "is_anomaly": is_anomaly,
            "fault_class": cls,
            "confidence": confidence,
            "low_confidence": bool(confidence < LOW_CONFIDENCE),
            "severity": severity,
            "severity_conf": deg_conf,
            "rul_min": rul_mean,
            "rul_lo": rul_lo,
            "rul_hi": rul_hi,
            "rul_conf": rul_conf,
            "alert_level": alert,
        }

    # ── explainability ────────────────────────────────────────────────────

    def explain(self, row: Dict[str, object], pred: Dict[str, object]) -> List[str]:
        """Human-readable explanation for one prediction."""
        exp = expected_sensors(row)
        res = residual_summary(row)
        lines: List[str] = []
        cls = pred["fault_class"]
        lines.append(f"prediction: {cls} (P={pred['confidence']:.2f}) "
                     f"| anomaly={pred['anomaly_score']:.0f}/100 "
                     f"| severity={pred['severity']:.2f} "
                     f"| RUL≈{pred['rul_min']:.0f} min [{pred['rul_lo']:.0f}–{pred['rul_hi']:.0f}] "
                     f"| alert={pred['alert_level']}")

        # top physics residuals (observed vs expected)
        channels = sorted(
            ((abs(v), k) for k, v in res.items() if k.startswith(("r_egt_", "r_cht_", "r_oil", "r_vib"))),
            reverse=True,
        )[:3]
        for _, key in channels:
            obs_key = key.replace("r_", "")
            if obs_key in exp:
                lines.append(
                    f"  residual {key}: {res[key]:+.0f} "
                    f"(observed {float(row.get(obs_key, 0)):.0f} vs expected {exp[obs_key]:.0f})"
                )

        # top feature impacts (global importance × z — approximation, no SHAP dep)
        imp = self._clf.feature_importances_
        imp_map = {n: float(w) for n, w in zip(self.feature_names, imp)}
        healthy = self.bundle.get("healthy_residual_stats", {})
        scored = []
        try:
            feats = self._ext.features()
        except Exception:
            feats = {}
        for n, w in imp_map.items():
            v = float(feats.get(n, 0.0))
            if n in healthy and healthy[n]["std"] > 1e-9:
                z = (v - healthy[n]["mean"]) / healthy[n]["std"]
            else:
                z = v
            scored.append((abs(w * z), n, z))
        for _, n, z in sorted(scored, reverse=True)[:3]:
            lines.append(f"  top feature {n}: z={z:+.2f}")

        if cls != HEALTHY_LABEL:
            lines.append(f"  recommended action: {ACTIONS.get(cls, 'Inspect engine before next flight.')}")
        if pred["low_confidence"]:
            lines.append("  ⚠ low classification confidence — treat as anomaly-watch, not diagnosis")
        return lines

    # ── JSON-safe helper ──────────────────────────────────────────────────

    def predict_row(self, row: Dict[str, object]) -> Dict[str, object]:
        """Update + predict, returning JSON-safe primitives with row meta."""
        out = self.update(row)
        if out is None:
            return {"sim_time_s": float(row.get("sim_time_s", 0.0)), "warmup": True}
        out = {k: float(v) if isinstance(v, (np.floating, float)) and k != "fault_class" else v
               for k, v in out.items()}
        out["sim_time_s"] = float(row.get("sim_time_s", 0.0))
        return out


class FallbackAnalyzer:
    """
    Rule-based fallback used when models are unavailable.

    Physics residuals are z-scored against the healthy statistics stored in
    the bundle (or a built-in default), then thresholded. It is deliberately
    conservative: class is often UNKNOWN, confidence is low.
    """

    DEFAULT_STATS = {
        "r_egt_avg": (0.0, 18.0), "r_egt_max": (12.0, 20.0),
        "r_cht_avg": (0.0, 6.0), "r_cht_max": (4.0, 7.0),
        "r_oil_p": (0.0, 8.0), "r_oil_t": (0.0, 1.5),
        "r_vib": (0.0, 0.06), "r_fuel": (0.0, 0.3),
        "r_batt": (0.0, 0.05), "r_alt": (0.0, 0.9),
    }

    def __init__(self, bundle: Optional[Dict[str, object]] = None) -> None:
        stats = (bundle or {}).get("healthy_residual_stats", {})
        self.stats = {
            k: {"mean": stats[k]["mean"], "std": max(1e-6, stats[k]["std"])}
            if k in stats else {"mean": m, "std": max(1e-6, s)}
            for k, (m, s) in self.DEFAULT_STATS.items()
        }
        self._last_sev: Optional[float] = None
        self._last_t: Optional[float] = None

    def predict(self, row: Dict[str, object]) -> Dict[str, object]:
        res = residual_summary(row)

        def z(key: str) -> float:
            st = self.stats.get(key, {"mean": 0.0, "std": 1.0})
            return (res.get(key, 0.0) - st["mean"]) / st["std"]

        zs = {k: z(k) for k in self.stats}
        max_z = max(abs(v) for v in zs.values())
        is_anomaly = bool(max_z > 4.0)
        anomaly_score = float(np.clip(100.0 * max_z / 8.0, 0.0, 100.0))

        cls = self._rule_class(zs)
        if not is_anomaly:
            cls = HEALTHY_LABEL
        severity = float(np.clip(max_z / 8.0, 0.0, 1.0))

        # crude RUL from severity slope (minutes)
        rul_min: Optional[float] = None
        t = float(row.get("sim_time_s", 0.0))
        if self._last_sev is not None and self._last_t is not None and t > self._last_t:
            rate = (severity - self._last_sev) / max(1e-6, (t - self._last_t) / 60.0)
            if rate > 1e-4:
                rul_min = float(max(0.0, (0.9 - severity) / rate))
        self._last_sev, self._last_t = severity, t

        pred = {
            "anomaly_score": anomaly_score,
            "is_anomaly": is_anomaly,
            "fault_class": cls,
            "confidence": 0.4 if cls != HEALTHY_LABEL else 0.6,
            "low_confidence": True,
            "severity": severity,
            "severity_conf": 0.3,
            "rul_min": rul_min,
            "rul_lo": None,
            "rul_hi": None,
            "rul_conf": 0.2,
            "alert_level": _alert_level(is_anomaly, cls, severity, rul_min or 999.0, 0.4),
            "fallback": True,
        }
        return pred

    @staticmethod
    def _rule_class(zs: Dict[str, float]) -> str:
        if zs["r_oil_p"] < -2.5:
            return "LUBRICATION_FAILURE"
        if zs["r_cht_avg"] > 2.5 or zs["r_cht_max"] > 3.0:
            return "OVERHEATING"
        if zs["r_egt_max"] > 3.0 and zs["r_egt_avg"] > 0.5:
            return "INJECTOR_DEGRADATION"
        if zs["r_egt_max"] < -2.5:
            return "MISFIRE"
        if zs["r_vib"] > 3.0:
            return "ABNORMAL_VIBRATION"
        if zs["r_batt"] < -3.0:
            return "ALTERNATOR_DEGRADATION"
        return "UNKNOWN"


def _alert_level(
    is_anomaly: bool,
    cls: str,
    severity: float,
    rul_min: float,
    confidence: float,
) -> str:
    critical = (
        severity > SEV_CRITICAL
        or rul_min < RUL_CRITICAL_MIN
        or (cls in ("LUBRICATION_FAILURE", "OVERHEATING") and severity > 0.5)
    )
    if critical:
        return "CRITICAL"
    advisory = (
        is_anomaly
        or (cls != HEALTHY_LABEL and severity > SEV_ADVISORY)
        or rul_min < RUL_ADVISORY_MIN
    )
    if advisory:
        return "ADVISORY"
    watch = cls != HEALTHY_LABEL and confidence < LOW_CONFIDENCE
    return "WATCH" if watch else "NONE"


def build_pipeline(model_dir: str):
    """InferencePipeline, or FallbackAnalyzer if models are unavailable."""
    try:
        return InferencePipeline(model_dir)
    except Exception as exc:  # pragma: no cover — defensive by design
        print(f"  ⚠ models unavailable ({exc}); using rule-based fallback")
        bundle = None
        try:
            bundle = _load_bundle(model_dir)
        except Exception:
            pass
        return FallbackAnalyzer(bundle)


# ──────────────────────────────────────────────────────────────────────────
#  CLI: stream a CSV through the pipeline
# ──────────────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ml.inference", description="stream a CSV through the trained pipeline")
    parser.add_argument("--model-dir", default="ml/models")
    parser.add_argument("--csv", required=True, help="telemetry CSV (telemetry_gen output)")
    parser.add_argument("--out", default=None, help="JSON output path for per-row predictions")
    parser.add_argument("--explain", action="store_true", help="print an explanation for the last window")
    args = parser.parse_args(argv)

    pipe = build_pipeline(args.model_dir)
    rows = []
    with open(args.csv, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            row = {k: (float(v) if v not in ("", "None") else 0.0) for k, v in raw.items()}
            pred = pipe.predict_row(row) if isinstance(pipe, InferencePipeline) else pipe.predict(row)
            pred["phase"] = row.get("phase", "")
            rows.append(pred)

    last_class = [r for r in rows if r.get("fault_class")]
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1)
        print(f"  predictions : {args.out} ({len(rows)} rows)")

    alerts: Dict[str, int] = {}
    for r in rows:
        alerts[r.get("alert_level", "NONE")] = alerts.get(r.get("alert_level", "NONE"), 0) + 1
    print(f"  alerts      : {alerts}")
    if last_class:
        last = last_class[-1]
        print(f"  final       : class={last.get('fault_class')} "
              f"conf={last.get('confidence', 0):.2f} "
              f"severity={last.get('severity', 0):.2f} "
              f"rul={last.get('rul_min')} "
              f"alert={last.get('alert_level')}")

    if args.explain and isinstance(pipe, InferencePipeline):
        # re-stream to fetch the final raw row for a richer explanation
        last_raw: Optional[Dict[str, object]] = None
        with open(args.csv, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                row = {k: (float(v) if v not in ("", "None") else 0.0) for k, v in raw.items()}
                last_raw = row
                pipe.update(row)
        final_pred = rows[-1]
        print("\n  explanation (final window):")
        for line in pipe.explain(last_raw, final_pred):
            print(f"    {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())