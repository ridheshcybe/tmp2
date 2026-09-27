# AeroTwin Lightweight ML Pipeline

The simplest credible ML stack for the digital twin: **tree ensembles on
engineered features** — physics residuals, rolling statistics, sensor
correlations, and operating-condition normalization. Everything runs on CPU
in seconds and needs only `scikit-learn` + `numpy`/`pandas` (+ `joblib`,
a scikit-learn dependency).

```
python -m ml.train                          # generate → train → evaluate → serialize
python -m ml.inference --csv <telemetry.csv> --explain   # stream through the bundle
python -m pytest ml/tests -q                # pipeline tests
```

## Model selection (and why not an LSTM)

| Task | Model | Why |
|---|---|---|
| Anomaly detection | Isolation Forest (healthy-only) | Unsupervised — no label leakage; O(n) fast; CPU |
| Fault classification | Random Forest, 9 classes | Engineered features already encode trends; interpretable; class-balanced |
| Degradation | Random Forest regressor (severity 0–1) | Tree variance → confidence for free |
| RUL | Random Forest regressor (log-minutes) | Same; log target stabilizes the countdown; tree std → 68 % interval |

An LSTM would need raw series, ~100× more data, GPU tuning and gives up
feature importances. The trends/correlations an LSTM would learn are already
computed explicitly (slopes, rolling std, pairwise correlations), so a forest
reaches the same accuracy more cheaply and explainably. **XGBoost** is a
drop-in upgrade for the regressors with identical features if you want
faster training — nothing else changes.

## Features (41)

1. **Operating conditions (12)** — `throttle`, `altitude_ft`,
   `ambient_temp_c`, `rpm`, 7 × one-hot `phase`.
2. **Raw aggregates (7)** — fuel flow, oil temp, battery, alternator,
   injection advance, `cht_spread`, `egt_spread` (max−min across cylinders).
3. **Physics residuals (10)** — `observed − physics_expected` from
   `ml/physics_baseline.py` (analytic ISA + thermal/fuel/oil/vib/electrical
   steady-state model): `r_cht_avg`, `r_cht_max`, `r_egt_avg`, `r_egt_max`,
   `r_fuel`, `r_oil_p`, `r_oil_t`, `r_vib`, `r_batt`, `r_alt`.
4. **Rolling statistics (9)** — 60 s mean/std of key residual series and
   180 s trend slopes (`trend_r_egt`, `trend_r_vib`, `trend_r_oilp`).
5. **Sensor correlations (4)** — 60 s rolling Pearson: `corr_egt_cht`,
   `corr_oilp_rpm`, `corr_fuel_rpm`, `corr_vib_rpm`.

(41 = 4 conditions + 7 phases + 5 raw + 2 spreads + 10 residuals +
9 rolling/trends + 4 correlations.)

Residuals give condition-relative normalization (cruising at 18,000 ft is
not a fault); rolling stats and trends catch *gradual* degradation; the
correlations break characteristically under misfire/injector faults.

## Labels

| Column | Meaning |
|---|---|
| `class` | `HEALTHY` or the primary `FaultType` (first in `faults_active`) |
| `severity` | max active fault severity ∈ [0, 1] — degradation target |
| `rul_min` | minutes until the fault is fully developed (`onset + ramp`) or mission end, whichever first |
| `is_fault` | binary anomaly flag (evaluation only) |

## Leakage prevention

1. **Run-level split** — train/val/test split whole runs
   (`ml.labels.split_runs`), stratified by fault type. Rows of one run never
   appear in two splits.
2. **Causal features** — rolling/trend/correlation buffers are trailing-only;
   no future information at time `t`.
3. **Fit-on-train-only** — anomaly scaler + threshold (P95 of healthy
   *validation* decisions) are frozen before test evaluation.
4. Windows are labelled by the last row in the window (standard practice;
   documented so the ground truth is unambiguous).

## Training

```bash
python -m ml.train --runs-per-fault 2 --healthy-runs 4 --severity 0.7 --seed 7 --model-dir ml/models
```

Pipeline: generate ~20 compressed runs (healthy + 8 faults, deterministic
seeds, faults anchored mid-CRUISE) → extract windows (step 5) → run split →
fit anomaly/classifier/degradation/RUL → evaluate on held-out test runs →
serialize. Outputs in `--model-dir`:

```
anomaly.joblib  classifier.joblib  degradation.joblib  rul.joblib
anomaly_scaler.joblib  bundle.json  metrics.json  report.md  confusion_matrix.png
```

## Evaluation (held-out test runs only)

Anomaly: ROC-AUC, precision/recall at threshold, healthy false-alarm rate,
and **detection latency** (seconds from onset to first flagged window — the
metric that matters for a 30-minute RTB decision). Classification: accuracy,
macro-F1, per-class F1, confusion matrix. Regression: RMSE/MAE/R² and
RUL-within-±20%. See `report.md` for the full table. On the synthetic test
set expect, roughly: anomaly ROC-AUC > 0.95, fault F1 (macro) > 0.9,
latency median < 60 s, RUL MAE ≈ 1–3 min. These are prototype numbers on
synthetic data — never present them as field performance.

## Confidence

* Classification → `predict_proba` max; `< 0.6` ⇒ `low_confidence` ⇒ alert
  degrades to anomaly-watch, not diagnosis.
* Degradation / RUL → variance across forest trees: severity 68 % band and
  `[rul_lo, rul_hi]` interval; confidence shrinks as tree spread grows.
* Anomaly → margin of the Isolation Forest decision below the P95 threshold,
  scaled to 0–100.

## Explainability

`InferencePipeline.explain(row, pred)` prints:

```
prediction: INJECTOR_DEGRADATION (P=0.83) | anomaly=71/100 | severity=0.62 | RUL≈31 min [24–38] | alert=ADVISORY
  residual r_egt_max: +76 (observed 716 vs expected 640)
  residual r_egt_avg: +19 (observed 659 vs expected 640)
  top feature r_egt_max: z=+3.1
  recommended action: Inspect injector / fuel delivery on the affected cylinder...
```

Residuals carry observed-vs-expected physics; top features use global
tree importance × feature z (a documented approximation — no SHAP
dependency). Every alert can be traced back to a residual + a trend.

## Fallback (models unavailable)

`ml.inference.build_pipeline()` loads the bundle, or — if models are missing
or corrupt — returns `FallbackAnalyzer`: z-scored physics residuals against
the stored healthy statistics, rule-based class hints, a severity-scaled
anomaly score, and a slope-based RUL estimate. It never raises, so the
dashboard keeps streaming. Outputs carry `"fallback": true` and low
confidence so operators know the models are offline.

## Health Index (0–100)

`ml/health_index.py` fuses the pipeline outputs into one operator-facing
number:

```
EHI = 100 × (1 − Σ w_i · p_i)
p_residual (0.25) · p_fault (0.25) · p_anomaly (0.20) ·
p_degradation (0.20) · p_sensor (0.10)
```

* **Smoothing** — EMA (τ = 60 s) + hard ±15 points/update rate limit.
* **Missing data** — lost/frozen sensors are penalised; weights of
  unavailable model outputs are redistributed; > 40 % sensors lost caps the
  index at 50 and marks it STALE.
* **Explainability** — every deduction carries a plain-language line:
  "EGT residual +76 °C (4.2σ above healthy)", "LUBRICATION_FAILURE
  probability 0.84 (criticality 1.00)", plus a recommended action.
* Categories NORMAL ≥ 85 · WATCH 70–84 · WARNING 50–69 · CRITICAL 30–49 ·
  EMERGENCY < 30.

Demo dashboard output:

```bash
python -m ml.demo_health_index --csv data/aerotwin_faulty_demo.csv
```

Writes `data/ehi_timeline.csv` + `data/ehi_dashboard_example.txt`.

## Roadmap (out of scope for the MVP)

SHAP-based instance explanations, quantile-regression forests, XGBoost
regressors, online model updating, fleet-level aggregation, calibration of
probabilities on real DRDO data.