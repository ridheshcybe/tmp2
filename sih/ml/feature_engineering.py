"""
Streaming feature extraction.
=============================

One :class:`FeatureExtractor` instance turns a stream of telemetry rows into
a fixed-size feature vector per row, combining the four design pillars:

1. **Physics residuals** — ``observed − physics_expected`` per channel and
   aggregated per-cylinder statistics (from :mod:`ml.physics_baseline`).
2. **Rolling statistics** — trailing-window mean / std and *trend slopes*
   of the key residual series (faults are trends, not jumps).
3. **Sensor correlations** — trailing-window Pearson correlations of
   physically coupled pairs (EGT↔CHT, oil pressure↔RPM, fuel↔RPM,
   vibration↔RPM). Couplings break characteristically under faults.
4. **Operating-condition normalization** — the conditions (throttle,
   altitude, ambient, RPM, mission phase) are included *and* residuals are
   computed condition-relative, so models do not confuse "cruising at
   altitude" with "fault".

All windows are strictly **causal** (trailing only), so features at time ``t``
never use information from ``t' > t`` — required for leakage-free evaluation
and for live streaming.

The extractor is symmetric: used in batch for training and online for
inference.
"""

from __future__ import annotations

import math
from collections import OrderedDict, deque
from typing import Deque, Dict, List

import numpy as np

from ml.physics_baseline import residual_summary
from simulator.telemetry_gen.telemetry_schema import PHASE_ORDER

#: Column used for trends (seconds per sample; 1 Hz default).
DT_S = 1.0

# ──────────────────────────────────────────────────────────────────────────
#  Feature catalogue
# ──────────────────────────────────────────────────────────────────────────


def feature_names(window_s: int = 60, trend_s: int = 180) -> List[str]:
    """Names of the features produced by a freshly-warmed extractor."""
    names: List[str] = []
    names += ["throttle", "altitude_ft", "ambient_temp_c", "rpm"]
    names += [f"phase_{p}" for p in PHASE_ORDER]
    names += [
        "fuel_flow_lph", "oil_temp_c", "battery_v", "alternator_a",
        "injection_timing_deg",
    ]
    names += ["cht_spread", "egt_spread"]
    names += [
        "r_cht_avg", "r_cht_max", "r_egt_avg", "r_egt_max",
        "r_fuel", "r_oil_p", "r_oil_t", "r_vib", "r_batt", "r_alt",
    ]
    names += [
        f"roll_mean_r_egt_{window_s}s",
        f"roll_std_r_egt_{window_s}s",
        f"roll_mean_r_cht_{window_s}s",
        f"roll_mean_r_vib_{window_s}s",
        f"roll_std_r_vib_{window_s}s",
        f"roll_mean_r_oilp_{window_s}s",
        f"trend_r_egt_{trend_s}s",
        f"trend_r_vib_{trend_s}s",
        f"trend_r_oilp_{trend_s}s",
    ]
    names += [
        "corr_egt_cht",
        "corr_oilp_rpm",
        "corr_fuel_rpm",
        "corr_vib_rpm",
    ]
    return names


def _safe_corr(a: Deque[float], b: Deque[float]) -> float:
    n = min(len(a), len(b))
    if n < 5:
        return 0.0
    x = np.asarray(list(a)[-n:], dtype=float)
    y = np.asarray(list(b)[-n:], dtype=float)
    if np.std(x) < 1e-9 or np.std(y) < 1e-9:
        return 0.0
    c = float(np.corrcoef(x, y)[0, 1])
    return c if math.isfinite(c) else 0.0


def _safe_slope(y: Deque[float], dt: float = DT_S) -> float:
    n = len(y)
    if n < 5:
        return 0.0
    x = np.arange(n, dtype=float) * dt
    vals = np.asarray(list(y), dtype=float)
    slope = float(np.polyfit(x, vals, 1)[0])
    return slope if math.isfinite(slope) else 0.0


# ──────────────────────────────────────────────────────────────────────────
#  Extractor
# ──────────────────────────────────────────────────────────────────────────


class FeatureExtractor:
    """Streaming feature extractor (batch + live use)."""

    def __init__(self, window_s: int = 60, trend_s: int = 180) -> None:
        self.window_s = window_s
        self.trend_s = trend_s
        w = window_s          # 1 Hz samples
        tr = trend_s
        # residual series (rolling windows)
        self._r_egt: Deque[float] = deque(maxlen=w)
        self._r_cht: Deque[float] = deque(maxlen=w)
        self._r_vib: Deque[float] = deque(maxlen=w)
        self._r_oilp: Deque[float] = deque(maxlen=w)
        # raw series for correlations
        self._egt: Deque[float] = deque(maxlen=w)
        self._cht: Deque[float] = deque(maxlen=w)
        self._oilp: Deque[float] = deque(maxlen=w)
        self._rpm: Deque[float] = deque(maxlen=w)
        self._fuel: Deque[float] = deque(maxlen=w)
        self._vib: Deque[float] = deque(maxlen=w)
        # trend buffers (longer)
        self._t_egt: Deque[float] = deque(maxlen=tr)
        self._t_vib: Deque[float] = deque(maxlen=tr)
        self._t_oilp: Deque[float] = deque(maxlen=tr)

        self._seen = 0
        self._last_phase: str = ""

    # ── state ────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self.__init__(window_s=self.window_s, trend_s=self.trend_s)

    @property
    def warm(self) -> bool:
        """True once every rolling window has enough history (≥ window_s)."""
        return self._seen >= self.window_s

    # ── update ───────────────────────────────────────────────────────────

    def update(self, row: Dict[str, object]) -> None:
        """Ingest one telemetry row (dict keyed like the telemetry CSV)."""
        self._row = row
        res = residual_summary(row)

        self._r_egt.append(float(res["r_egt_avg"]))
        self._r_cht.append(float(res["r_cht_avg"]))
        self._r_vib.append(float(res["r_vib"]))
        self._r_oilp.append(float(res["r_oil_p"]))
        self._t_egt.append(float(res["r_egt_avg"]))
        self._t_vib.append(float(res["r_vib"]))
        self._t_oilp.append(float(res["r_oil_p"]))

        self._egt.append(float(np.mean([row[f"egt_c{i}"] for i in range(1, 5)])))
        self._cht.append(float(np.mean([row[f"cht_c{i}"] for i in range(1, 5)])))
        self._oilp.append(float(row["oil_pressure_kpa"]))
        self._rpm.append(float(row["rpm"]))
        self._fuel.append(float(row["fuel_flow_lph"]))
        self._vib.append(float(row["vibration_rms_g"]))

        self._last_phase = str(row.get("phase", ""))
        self._seen += 1

    # ── features ─────────────────────────────────────────────────────────

    def features(self) -> OrderedDict[str, float]:
        """Current feature vector (only meaningful once :attr:`warm`)."""
        f: OrderedDict[str, float] = OrderedDict()
        f["throttle"] = self._f("throttle")
        f["altitude_ft"] = self._f("altitude_ft")
        f["ambient_temp_c"] = self._f("ambient_temp_c")
        f["rpm"] = self._f("rpm")
        for phase in PHASE_ORDER:
            f[f"phase_{phase}"] = 1.0 if phase.value == self._last_phase else 0.0
        f["fuel_flow_lph"] = self._f("fuel_flow_lph")
        f["oil_temp_c"] = self._f("oil_temp_c")
        f["battery_v"] = self._f("battery_v")
        f["alternator_a"] = self._f("alternator_a")
        f["injection_timing_deg"] = self._f("injection_timing_deg")
        f["cht_spread"] = self._cyl_spread("cht")
        f["egt_spread"] = self._cyl_spread("egt")

        res = residual_summary(self._last_row)
        f.update({k: res[k] for k in [
            "r_cht_avg", "r_cht_max", "r_egt_avg", "r_egt_max",
            "r_fuel", "r_oil_p", "r_oil_t", "r_vib", "r_batt", "r_alt",
        ]})

        f[f"roll_mean_r_egt_{self.window_s}s"] = float(np.mean(self._r_egt))
        f[f"roll_std_r_egt_{self.window_s}s"] = float(np.std(self._r_egt))
        f[f"roll_mean_r_cht_{self.window_s}s"] = float(np.mean(self._r_cht))
        f[f"roll_mean_r_vib_{self.window_s}s"] = float(np.mean(self._r_vib))
        f[f"roll_std_r_vib_{self.window_s}s"] = float(np.std(self._r_vib))
        f[f"roll_mean_r_oilp_{self.window_s}s"] = float(np.mean(self._r_oilp))
        f[f"trend_r_egt_{self.trend_s}s"] = _safe_slope(self._t_egt)
        f[f"trend_r_vib_{self.trend_s}s"] = _safe_slope(self._t_vib)
        f[f"trend_r_oilp_{self.trend_s}s"] = _safe_slope(self._t_oilp)

        f["corr_egt_cht"] = _safe_corr(self._egt, self._cht)
        f["corr_oilp_rpm"] = _safe_corr(self._oilp, self._rpm)
        f["corr_fuel_rpm"] = _safe_corr(self._fuel, self._rpm)
        f["corr_vib_rpm"] = _safe_corr(self._vib, self._rpm)
        return f

    # ── internals ────────────────────────────────────────────────────────

    @property
    def _last_row(self) -> Dict[str, object]:
        return self._row

    def _f(self, key: str) -> float:
        return float(self._row.get(key, 0.0))

    def _cyl_spread(self, kind: str) -> float:
        vals = [float(self._row[f"{kind}_c{i}"]) for i in range(1, 5)]
        return float(max(vals) - min(vals))


def batch_features_indexed(
    rows: List[Dict[str, object]],
    window_s: int = 60,
    trend_s: int = 180,
    step: int = 1,
) -> List[Tuple[OrderedDict[str, float], int]]:
    """
    One feature vector per row (after warm-up), each paired with the index of
    the telemetry row it was computed at — keeps labels aligned with features.

    ``step`` > 1 subsamples every step-th warm vector for faster training.
    """
    ext = FeatureExtractor(window_s=window_s, trend_s=trend_s)
    out: List[Tuple[OrderedDict[str, float], int]] = []
    warm_seen = 0
    for i, row in enumerate(rows):
        ext.update(row)
        if ext.warm:
            if warm_seen % step == 0:
                out.append((ext.features(), i))
            warm_seen += 1
    return out


def batch_features(
    rows: List[Dict[str, object]],
    window_s: int = 60,
    trend_s: int = 180,
    step: int = 1,
) -> List[OrderedDict[str, float]]:
    """Feature vectors only (see :func:`batch_features_indexed`)."""
    return [f for f, _ in batch_features_indexed(rows, window_s, trend_s, step)]