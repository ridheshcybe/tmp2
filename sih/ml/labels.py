"""
Label design and leakage-free data splitting.
=============================================

Labels
------
* ``class``      — HEALTHY or one of the 8 ``FaultType`` values (primary =
                   first fault listed in ``faults_active``; combined faults
                   are labelled by the first — single-fault runs are the
                   default training data).
* ``severity``   — max active fault severity ∈ [0, 1] (degradation target).
* ``rul_s``      — Remaining Useful Life in seconds: time until the *primary*
                   fault is fully developed (``onset_s + ramp_s``), or until
                   mission end for healthy segments — whichever is smaller.
                   ``rul_min = rul_s / 60`` is the regression target.
* ``is_fault``   — binary anomaly flag (for anomaly-detection evaluation).

Leakage prevention
------------------
1. **Run-level split** — train / validation / test splits group *whole runs*,
   never rows. Rows from one run never appear in more than one split.
2. **Causal features** — rolling/trend/correlation features only use trailing
   history (see :mod:`ml.feature_engineering`), so no future information.
3. **Scalers/thresholds fit on train only** — the Isolation Forest
   contamination threshold and residual statistics are fit on training /
   validation data, then frozen on test data.
4. **Stratified by fault type** — every fault type is represented in every
   split so a rare fault cannot leak via class imbalance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from simulator.telemetry_gen.telemetry_schema import FaultType

HEALTHY_LABEL = "HEALTHY"

#: Failure definition — fault fully developed.
FAILURE_SEVERITY = 0.9


@dataclass
class RunMeta:
    """Metadata for one generated training run (kept out of the features)."""

    run_id: str
    fault_type: str            # HEALTHY_LABEL or FaultType value
    severity: float
    onset_s: float             # 0 for healthy runs
    ramp_s: float              # 0 for healthy runs
    t_fail_s: float            # fault fully developed (onset + ramp), 0 for healthy
    mission_end_s: float

    @property
    def faulted(self) -> bool:
        return self.fault_type != HEALTHY_LABEL


def label_row(row: Dict[str, object]) -> Tuple[str, float]:
    """(class, severity) for a telemetry row with ground truth columns."""
    active = str(row.get("faults_active", ""))
    if not active:
        return HEALTHY_LABEL, 0.0
    primary = active.split(",")[0]
    sev = float(row.get("fault_severity", 0.0))
    return primary, min(1.0, sev)


def compute_rul_s(row: Dict[str, object], meta: RunMeta) -> float:
    """
    Seconds to failure (fault fully developed) or mission end, whichever
    comes first. Healthy rows simply count down the remaining mission time,
    so RUL transitions smoothly at fault onset.
    """
    t = float(row["sim_time_s"])
    mission_left = max(0.0, meta.mission_end_s - t)
    if not meta.faulted:
        return mission_left
    fault_left = max(0.0, meta.t_fail_s - t)
    return min(mission_left, fault_left)


def split_runs(
    metas: List[RunMeta],
    val_frac: float = 0.2,
    test_frac: float = 0.2,
    seed: int = 0,
) -> Tuple[List[RunMeta], List[RunMeta], List[RunMeta]]:
    """
    Deterministic stratified run-level split.

    Runs are grouped by ``fault_type``; within each group a seeded shuffle
    assigns the requested fractions to validation and test, the rest to
    training. Guarantees every fault type appears in every split (given ≥ 2
    runs per type).
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    by_type: Dict[str, List[RunMeta]] = {}
    for m in metas:
        by_type.setdefault(m.fault_type, []).append(m)

    train, val, test = [], [], []
    for _type, group in by_type.items():
        order = rng.permutation(len(group)).tolist()
        if len(group) >= 3:
            n_val = max(1, int(round(len(group) * val_frac)))
            n_test = max(1, int(round(len(group) * test_frac)))
            if n_val + n_test >= len(group):
                n_test = max(1, len(group) - n_val - 1)
        elif len(group) == 2:
            n_val, n_test = 1, 0   # 1 train + 1 validation
        else:
            n_val, n_test = 0, 0   # single run → training only

        for i in order[:n_val]:
            val.append(group[i])
        for i in order[n_val:n_val + n_test]:
            test.append(group[i])
        for i in order[n_val + n_test:]:
            train.append(group[i])

    return train, val, test