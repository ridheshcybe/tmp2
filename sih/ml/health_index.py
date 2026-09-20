"""
Transparent 0–100 Engine Health Index (EHI).
============================================

A single, explainable number for the operator: **100 = brand new, 0 = don't
fly**. The index is a weighted sum of five independently measurable penalty
terms, so every point deducted can be traced to a physical observation:

    EHI = 100 × (1 − Σ w_i × penalty_i)

    penalty_residual     : worst |z|-score of the physics residuals
                           (observed vs expected sensor value)
    penalty_anomaly      : anomaly score / 100  (Isolation-Forest margin)
    penalty_fault        : max fault probability × fault criticality
    penalty_degradation  : degradation severity (0–1)
    penalty_sensor       : fraction of sensors missing / frozen / isolated

Weights (sum = 1.0, see :data:`DEFAULT_WEIGHTS`): residuals 0.25, fault 0.25,
anomaly 0.20, degradation 0.20, sensor quality 0.10.

Design rules
------------
* **Transparent** — every component is a documented, monotonic function of a
  physical quantity; no black-box blending.
* **Smooth** — exponential moving average (τ ≈ 60 s) + a hard rate limit
  (±15 points per second of engine time) so the needle never jumps
  unrealistically. The time constant is *cadence-adaptive*: it is computed
  from the measured Δt between updates, so a 10 Hz live stream and a 1 Hz
  CSV replay produce the same physical response.
* **Honest under missing data** — lost/frozen sensors are *penalised* (they
  reduce confidence and cap the index at 50 when > 40 % are gone), and the
  weights of unavailable model outputs are redistributed to the remaining
  components rather than silently ignored.
* **Readable** — ``explanation`` is written for a maintenance engineer:
  "EGT residual +76 °C (4.2σ above healthy)", not "feature_17 = 0.83".

Categories: NORMAL ≥ 85 · WATCH 70–84 · WARNING 50–69 · CRITICAL 30–49 ·
EMERGENCY < 30.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from ml.physics_baseline import residual_summary

# ──────────────────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────────────────

#: Mission-safety criticality per fault class (0 = harmless … 1 = loss-of-engine).
CRITICALITY: Dict[str, float] = {
    "HEALTHY": 0.0,
    "LUBRICATION_FAILURE": 1.0,
    "OVERHEATING": 0.90,
    "MISFIRE": 0.75,
    "ABNORMAL_VIBRATION": 0.70,
    "INJECTOR_DEGRADATION": 0.65,
    "ALTERNATOR_DEGRADATION": 0.50,
    "SENSOR_DRIFT": 0.35,
    "SENSOR_DROPOUT": 0.30,
    "UNKNOWN": 0.50,
}

#: Component weights (sum = 1.0). Residuals + fault carry the most evidence;
#: sensor quality is deliberately small but never zero (quality gate).
DEFAULT_WEIGHTS: Dict[str, float] = {
    "residual": 0.25,
    "anomaly": 0.20,
    "fault": 0.25,
    "degradation": 0.20,
    "sensor": 0.10,
}

#: (lower_bound_inclusive, label) — evaluated highest-first.
CATEGORY_RANGES: List[Tuple[float, str]] = [
    (85.0, "NORMAL"),
    (70.0, "WATCH"),
    (50.0, "WARNING"),
    (30.0, "CRITICAL"),
    (0.0, "EMERGENCY"),
]

#: A residual z of 8.0 ⇒ full penalty (≈ 6-sigma event, never healthy).
Z_MAX = 8.0

#: Channels scored by the residual penalty. ``r_oil_t`` is deliberately
#: excluded: oil temperature lags operating-point changes by minutes
#: (thermal mass), so healthy transients produce large steady-state
#: residuals — oil temperature is monitored for *trends*, not instant score.
PENALTY_CHANNELS: List[str] = [
    "r_cht_avg", "r_cht_max",
    "r_egt_avg", "r_egt_max",
    "r_fuel", "r_oil_p",
    "r_vib", "r_batt", "r_alt",
]

#: Empirically fitted healthy residual (mean, std) from a full healthy mission
#: of the telemetry generator — the default baseline when no trained bundle
#: is available. A trained bundle's ``healthy_residual_stats`` overrides this.
HEALTHY_RESIDUAL_STATS: Dict[str, Tuple[float, float]] = {
    "r_cht_avg": (-1.71, 20.51),
    "r_cht_max": (12.08, 18.46),
    "r_egt_avg": (-1.15, 3.76),
    "r_egt_max": (14.07, 4.93),
    "r_fuel": (0.00, 0.12),
    "r_oil_p": (0.00, 3.55),
    "r_oil_t": (-16.76, 21.69),
    "r_vib": (0.00, 0.04),
    "r_batt": (0.00, 0.04),
    "r_alt": (0.00, 0.73),
}

#: Physical units per residual channel (for human-readable labels).
RESIDUAL_UNITS: Dict[str, str] = {
    "r_cht_avg": "°C", "r_cht_max": "°C",
    "r_egt_avg": "°C", "r_egt_max": "°C",
    "r_fuel": "l/h", "r_oil_p": "kPa", "r_oil_t": "°C",
    "r_vib": "g", "r_batt": "V", "r_alt": "A",
}

#: Friendly names per residual channel.
RESIDUAL_NAMES: Dict[str, str] = {
    "r_cht_avg": "CHT residual (avg)", "r_cht_max": "CHT residual (max cyl)",
    "r_egt_avg": "EGT residual (avg)", "r_egt_max": "EGT residual (max cyl)",
    "r_fuel": "Fuel-flow residual", "r_oil_p": "Oil-pressure residual",
    "r_oil_t": "Oil-temperature residual", "r_vib": "Vibration residual",
    "r_batt": "Battery-voltage residual", "r_alt": "Alternator-current residual",
}

#: Below this fraction of healthy sensors the index is marked STALE and capped.
MIN_SENSOR_FRACTION = 0.60

#: Telemetry sensor channels the calculator expects (for data-quality ratio).
SENSOR_CHANNELS: List[str] = [
    "rpm", "fuel_flow_lph",
    "cht_c1", "cht_c2", "cht_c3", "cht_c4",
    "egt_c1", "egt_c2", "egt_c3", "egt_c4",
    "oil_pressure_kpa", "oil_temp_c", "vibration_rms_g",
    "battery_v", "alternator_a", "injection_timing_deg",
]

# ──────────────────────────────────────────────────────────────────────────
#  Pure functions
# ──────────────────────────────────────────────────────────────────────────


def compute_ehi(penalties: Dict[str, float], weights: Dict[str, float]) -> float:
    """
    EHI = 100 × (1 − Σ w_i·p_i), clamped to [0, 100].

    ``penalties`` may omit components (they contribute 0) — weights are NOT
    renormalised here; use :meth:`HealthIndexCalculator.update` for proper
    weight redistribution on missing data.
    """
    total = sum(weights.get(k, 0.0) * min(1.0, max(0.0, p)) for k, p in penalties.items())
    return float(np.clip(100.0 * (1.0 - total), 0.0, 100.0))


def category(ehi: float) -> str:
    """Health category label for a score."""
    for lo, label in CATEGORY_RANGES:
        if ehi >= lo:
            return label
    return "EMERGENCY"


def alert_level(ehi: float, penalties: Dict[str, float], cls: str) -> str:
    """Operational alert for the index (NONE / WATCH / ADVISORY / CRITICAL)."""
    if (
        ehi < 50.0
        or penalties.get("degradation", 0.0) > 0.7
        or (penalties.get("fault", 0.0) > 0.5 and CRITICALITY.get(cls, 0.0) >= 0.75)
    ):
        return "CRITICAL"
    if (
        ehi < 70.0
        or penalties.get("anomaly", 0.0) > 0.35
        or penalties.get("degradation", 0.0) > 0.35
    ):
        return "ADVISORY"
    if ehi < 85.0:
        return "WATCH"
    return "NONE"


# ──────────────────────────────────────────────────────────────────────────
#  Calculator
# ──────────────────────────────────────────────────────────────────────────


class HealthIndexCalculator:
    """
    Streaming EHI calculator.

    Usage::

        calc = HealthIndexCalculator(healthy_stats=bundle["healthy_residual_stats"])
        result = calc.update(row, pred, sensor_valid=None)

    ``row``  — one telemetry row (CSV-keyed, as generated by the simulator).
    ``pred`` — the inference prediction dict from ``ml.inference``
               (fault_class, confidence, anomaly_score, severity, …).
    """

    def __init__(
        self,
        healthy_stats: Optional[Dict[str, Dict[str, float]]] = None,
        weights: Optional[Dict[str, float]] = None,
        tau_s: float = 60.0,
        max_step: float = 15.0,
        dt_s: float = 1.0,
    ) -> None:
        defaults = {
            k: {"mean": m, "std": max(1e-6, s)}
            for k, (m, s) in HEALTHY_RESIDUAL_STATS.items()
        }
        if healthy_stats:
            defaults.update(
                {k: {"mean": v["mean"], "std": max(1e-6, v["std"])}
                 for k, v in healthy_stats.items()}
            )
        self.stats = defaults
        self.weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
        self.tau_s = float(tau_s)
        self.alpha = 1.0 - math.exp(-dt_s / max(1.0, self.tau_s))  # 1 Hz default
        self.max_step = max_step
        self.dt_s = dt_s

        self._ehi: Optional[float] = None
        self._history: Deque[Tuple[float, float]] = deque(maxlen=600)
        self._t = 0.0
        self._last_t: Optional[float] = None

    # ── public ────────────────────────────────────────────────────────────

    def update(
        self,
        row: Dict[str, object],
        pred: Dict[str, object],
        sensor_valid: Optional[Dict[str, bool]] = None,
        t: Optional[float] = None,
    ) -> Dict[str, object]:
        """Compute the smoothed EHI for one tick and return the full result."""
        self._t = float(t if t is not None else row.get("sim_time_s", self._t + self.dt_s))
        dt_eff = self._dt_effective()
        self._last_t = self._t

        # ── 1. component penalties ──
        p_res = self._residual_penalty(row)
        p_anom = float(np.clip(float(pred.get("anomaly_score", 0.0)) / 100.0, 0.0, 1.0))
        cls = str(pred.get("fault_class", "HEALTHY"))
        conf = float(pred.get("confidence", 0.0))
        p_fault = (
            float(np.clip(conf * CRITICALITY.get(cls, 0.5), 0.0, 1.0))
            if cls != "HEALTHY"
            else 0.0
        )
        p_deg = float(np.clip(float(pred.get("severity", 0.0)), 0.0, 1.0))
        fraction, bad_channels = self._sensor_fraction(row, sensor_valid)
        p_sens = float(np.clip(1.0 - fraction, 0.0, 1.0))

        penalties = {
            "residual": p_res,
            "anomaly": p_anom,
            "fault": p_fault,
            "degradation": p_deg,
            "sensor": p_sens,
        }

        # ── 2. availability → weight redistribution ──
        available = {
            "residual": True,
            "anomaly": "anomaly_score" in pred,
            "fault": "fault_class" in pred and "confidence" in pred,
            "degradation": "severity" in pred,
            "sensor": True,
        }
        w_sum = sum(w for k, w in self.weights.items() if available[k])
        weights_used = {
            k: (self.weights[k] / w_sum if available[k] else 0.0)
            for k in self.weights
        }
        missing = [k for k in self.weights if not available[k]]

        # ── 3. raw score, smoothing with rate limit ──
        raw = compute_ehi({k: v for k, v in penalties.items() if available[k]}, weights_used)
        if self._ehi is None:
            smoothed = raw
        else:
            alpha = 1.0 - math.exp(-dt_eff / max(1.0, self.tau_s))
            ema = self._ehi + alpha * (raw - self._ehi)
            # rate limit scaled to the elapsed time — per *second* of engine
            # time, never more than max_step for a single update
            step_cap = self.max_step * dt_eff / max(1e-6, self.dt_s)
            delta = float(np.clip(ema - self._ehi, -step_cap, step_cap))
            smoothed = self._ehi + delta
        self._ehi = float(np.clip(smoothed, 0.0, 100.0))
        self._history.append((self._t, self._ehi))

        # ── 4. data-quality gate ──
        stale = fraction < MIN_SENSOR_FRACTION
        ehi = min(self._ehi, 50.0) if stale else self._ehi

        # ── 5. trend / confidence / explanation ──
        trend, delta_5 = self._trend()
        contributors = self._contributors(penalties, row, pred, cls, conf, bad_channels)
        confidence = self._confidence(fraction, bool(missing), stale)
        explanation = self._explanation(
            ehi, penalties, contributors, pred, cls, trend, stale, missing
        )

        return {
            "ehi": round(ehi, 1),
            "raw": round(raw, 1),
            "category": category(ehi),
            "alert_level": alert_level(ehi, penalties, cls),
            "trend": trend,
            "delta_5min": round(delta_5, 1),
            "penalties": {k: round(v, 3) for k, v in penalties.items()},
            "weights_used": {k: round(v, 3) for k, v in weights_used.items()},
            "data_quality": {
                "fraction_valid": round(fraction, 2),
                "stale": stale,
                "bad_channels": sorted(bad_channels),
            },
            "confidence": confidence,
            "contributors": contributors,
            "explanation": explanation,
        }

    # ── internals ─────────────────────────────────────────────────────────

    def _dt_effective(self) -> float:
        """
        Simulated time elapsed since the previous update, clamped to one
        nominal step (``dt_s``).

        The live API streams at 10 Hz (Δt = 0.1 s) while CSV replay advances
        1 s per row. Using the *measured* Δt in the EMA and the rate limit
        makes the index cadence-independent: τ ≈ 60 s and ±15 points/s of
        engine time whether frames arrive at 1 Hz or 10 Hz. Clamping to
        ``dt_s`` keeps the original behaviour for slow/gappy streams (one
        update may move at most ``max_step`` points, even across a data gap).
        """
        if self._last_t is None or self._t <= self._last_t:
            return self.dt_s
        return float(min(self.dt_s, max(1e-3, self._t - self._last_t)))

    def reset(self) -> None:
        """Clear all history so the next tick restarts from a neutral score.

        Called at mission start: the prototype injects no faults on a fresh
        mission, so a healthy restart must not inherit the previous
        mission's degraded EMA value.
        """
        self._ehi = None
        self._history.clear()
        self._last_t = None

    def _residual_penalty(self, row: Dict[str, object]) -> float:
        try:
            res = residual_summary(row)
        except Exception:
            return 0.0
        zs: List[float] = []
        for ch in PENALTY_CHANNELS:
            val = res.get(ch)
            st = self.stats.get(ch)
            if val is None or st is None or st["std"] < 1e-9:
                continue
            zs.append(abs(float(val) - st["mean"]) / st["std"])
        if not zs:
            return 0.0
        return float(np.clip(max(zs) / Z_MAX, 0.0, 1.0))

    def _sensor_fraction(
        self,
        row: Dict[str, object],
        sensor_valid: Optional[Dict[str, bool]],
    ) -> Tuple[float, List[str]]:
        bad: List[str] = []
        for ch in SENSOR_CHANNELS:
            ok = ch in row and row[ch] is not None and str(row[ch]) not in ("", "nan")
            if sensor_valid is not None and ch in sensor_valid:
                ok = ok and bool(sensor_valid[ch])
            if not ok:
                bad.append(ch)
        fraction = 1.0 - len(bad) / max(1, len(SENSOR_CHANNELS))
        return fraction, bad

    def _trend(self) -> Tuple[str, float]:
        if len(self._history) < 2:
            return "stable", 0.0
        t_now, ehi_now = self._history[-1]
        past = [e for t, e in self._history if t_now - t <= 300.0]
        if len(past) < 2:
            return "stable", 0.0
        delta = ehi_now - past[0]
        if delta < -2.0:
            return "declining", delta
        if delta > 2.0:
            return "improving", delta
        return "stable", delta

    def _contributors(
        self,
        penalties: Dict[str, float],
        row: Dict[str, object],
        pred: Dict[str, object],
        cls: str,
        conf: float,
        bad_channels: List[str],
    ) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []

        if penalties["residual"] > 0.05:
            out.append({
                "component": "residual",
                "penalty": round(penalties["residual"], 3),
                "label": self._top_residual_label(row),
            })
        if penalties["anomaly"] > 0.05:
            out.append({
                "component": "anomaly",
                "penalty": round(penalties["anomaly"], 3),
                "label": f"Anomaly score {pred.get('anomaly_score', 0):.0f}/100",
            })
        if penalties["fault"] > 0.05:
            out.append({
                "component": "fault",
                "penalty": round(penalties["fault"], 3),
                "label": f"{cls} probability {conf:.2f} "
                         f"(criticality {CRITICALITY.get(cls, 0.5):.2f})",
            })
        if penalties["degradation"] > 0.05:
            out.append({
                "component": "degradation",
                "penalty": round(penalties["degradation"], 3),
                "label": f"Degradation score {pred.get('severity', 0):.2f}",
            })
        if penalties["sensor"] > 0.05 and bad_channels:
            out.append({
                "component": "sensor",
                "penalty": round(penalties["sensor"], 3),
                "label": f"{len(bad_channels)} sensors degraded "
                         f"({', '.join(bad_channels[:4])})",
            })
        return sorted(out, key=lambda c: c["penalty"], reverse=True)

    def _top_residual_label(self, row: Dict[str, object]) -> str:
        res = residual_summary(row)
        best, best_z = "", 0.0
        for ch, val in res.items():
            st = self.stats.get(ch)
            if st is None or st["std"] < 1e-9:
                continue
            z = abs(float(val) - st["mean"]) / st["std"]
            if z > best_z:
                best, best_z = ch, z
        if not best:
            return "Residuals within healthy band"
        sign = "+" if res[best] >= 0 else ""
        unit = RESIDUAL_UNITS.get(best, "")
        name = RESIDUAL_NAMES.get(best, best.replace("r_", ""))
        return (
            f"{name} {sign}{res[best]:.0f}{unit} "
            f"({best_z:.1f}σ above healthy baseline)"
        )

    def _confidence(self, fraction: float, missing_model: bool, stale: bool) -> str:
        if stale or fraction < 0.8:
            return "LOW"
        if fraction < 0.95 or missing_model:
            return "MEDIUM"
        return "HIGH"

    def _explanation(
        self,
        ehi: float,
        penalties: Dict[str, float],
        contributors: List[Dict[str, object]],
        pred: Dict[str, object],
        cls: str,
        trend: str,
        stale: bool,
        missing: List[str],
    ) -> List[str]:
        lines = [f"Health Index: {ehi:.0f}/100 · {category(ehi)} · trend {trend}"]
        if contributors:
            lines.append("Main contributors:")
            for c in contributors[:4]:
                lines.append(f"  – {c['label']}")
        else:
            lines.append("  – all monitored channels within healthy limits")
        if cls not in ("HEALTHY", "UNKNOWN"):
            from ml.inference import ACTIONS

            lines.append(f"Recommended action: {ACTIONS.get(cls, 'Inspect before next flight.')}")
        if stale:
            lines.append("Data quality POOR — more than 40% of sensors unavailable; "
                         "index capped at 50.")
        if missing:
            lines.append(f"Models unavailable ({', '.join(missing)}); "
                         "weights redistributed to remaining evidence.")
        return lines


def explain_text(result: Dict[str, object]) -> str:
    """Pretty-print a calculator result (dashboard / report friendly)."""
    return "\n".join(result["explanation"])