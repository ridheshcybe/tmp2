# AeroTwin — AI Models & ML Pipeline

Package `sih/ml/` — everything the "AI" in AI-enabled digital twin means.
Train with `cd sih && train.bat` (or `python -m ml.train --runs-per-fault 2 --healthy-runs 4 --model-dir ml/models`).
Artifacts land in `sih/ml/models/`: `anomaly.joblib`, `anomaly_scaler.joblib`, `classifier.joblib`, `degradation.joblib`, `rul.joblib`, `bundle.json`.

**Design philosophy:** engineered features + tree ensembles instead of an LSTM. The temporal patterns (trends, rolling variance, breaking correlations) are encoded explicitly in the features, so a tree ensemble reaches the same accuracy with ~100× less data, no GPU, and free explainability (feature importances + tree variance for confidence intervals).

---

## 1. `physics_baseline.py` — the analytic backbone (not trained)

Computes the *expected healthy* value of every sensor from the operating point (`throttle`, `altitude_ft`, `ambient_temp_c`, `rpm`, `oil_temp_c`). Mirrors the calibration equations of the simulator's engine model, so a healthy engine produces residuals ≈ 0.

- `expected_sensors(row)` → dict: `fuel_flow_lph`, `egt_c1..c4` (fast, altitude-lean), `cht_c1..c4` (slow thermal steady state), `oil_pressure_kpa` (pump ∝ RPM, viscosity ∝ T), `oil_temp_c`, `vibration_rms_g`, `battery_v` (14.25 V above 1500 RPM else 12.55 V), `alternator_a`, `injection_timing_deg` (RPM advance + CHT retard).
- `residuals(row, expected)` → `observed − expected` per channel.
- `residual_summary(row)` → the compact 10-vector used everywhere downstream:
  `r_cht_avg, r_cht_max, r_egt_avg, r_egt_max, r_fuel, r_oil_p, r_oil_t, r_vib, r_batt, r_alt` (avg/max-abs across the 4 cylinders for CHT/EGT).

Why analytic: deterministic, explainable ("EGT is +76 °C above physics"), robust to dataset shift, and the hybrid backbone (`predicted = physics + ML correction`).

## 2. `feature_engineering.py` — `FeatureExtractor`

Streaming, strictly **causal** (trailing-only) feature windows. Same code path for training (batch) and inference (online) — no train/serve skew.

Feature groups (`feature_names()`, ~30 features):
1. **Conditions**: `throttle, altitude_ft, ambient_temp_c, rpm` + one-hot `phase_*`.
2. **Raw channels**: `fuel_flow_lph, oil_temp_c, battery_v, alternator_a, injection_timing_deg`, `cht_spread`, `egt_spread`.
3. **Physics residuals**: the 10-vector from §1.
4. **Rolling stats** (60 s window): mean/std of `r_egt`, `r_cht`, `r_vib`, `r_oilp`.
5. **Trend slopes** (180 s window): `trend_r_egt`, `trend_r_vib`, `trend_r_oilp` — *faults are trends, not jumps*.
6. **Coupling correlations** (Pearson, trailing window): `corr_egt_cht`, `corr_oilp_rpm`, `corr_fuel_rpm`, `corr_vib_rpm` — couplings break characteristically under faults.

`update(row)` ingests; `.warm` flips after the trend window fills; `.features()` returns the vector.

## 3. The four trained models

Loaded by `InferencePipeline` from `MODEL_DIR` (see §5). All scikit-learn, all joblib-serialised.

| # | Model | Algorithm | Target | Key outputs |
|---|---|---|---|---|
| 1 | **Anomaly detector** | Isolation Forest (+ `StandardScaler`), trained on **healthy-only** windows | Novelty score | `anomaly_score` 0–100 (`100·(threshold − decision)/scale`, clipped), `is_anomaly` (`decision < threshold`) |
| 2 | **Fault classifier** | Random Forest, 9 classes | `{HEALTHY, 8 fault classes}` | `fault_class`, `confidence` = max class probability, `low_confidence` (< 0.6) |
| 3 | **Degradation severity** | Random Forest regressor | severity ∈ [0, 1] | `severity` (mean over trees), `severity_conf` = `1 − std(trees)/0.3` |
| 4 | **RUL regressor** | Random Forest regressor on **log(remaining minutes)** | minutes to failure | `rul_min` = `expm1(mean(log-trees))`, 68% interval `rul_lo/hi` = `expm1(mean ∓ std)`, `rul_conf` = `1 − std/1.5` |

Tree-variance trick (models 3 & 4): per-tree spread doubles as a confidence estimate — no extra model needed.

**RUL calibration.** Model 4 is fit on a *compressed* training mission
(`ml.training_data.TRAIN_DURATIONS` totals 1035 s = 17.25 min), so its raw
output means "minutes left in that training run" — a healthy engine reads
2–10 min, which trips every RUL-keyed alert on the first frame. `InferencePipeline`
therefore scales `rul_min`/`rul_lo`/`rul_hi` by `RUL_SCALE =
NOMINAL_ENDURANCE_MIN / TRAIN_HORIZON_MIN` (120 / 17.25 ≈ 6.96) so the value
leaving the pipeline is an engine-life figure: ~30–40 min healthy, falling
below the 10 min RTB_CRITICAL bar as a fault develops. Retraining on a longer
mission is the honest fix; until then this is a documented projection, not a
measurement.

## 4. `health_index.py` — the explainable Engine Health Index (EHI)

Not a black box: a weighted sum of five penalties, every point traceable to a physical observation.

```
EHI = 100 × (1 − Σ wᵢ·penaltyᵢ)
```

| Penalty | Weight | Definition |
|---|---|---|
| `residual` | 0.25 | worst \|z\| of the physics residuals vs healthy stats, ÷ Z_MAX (8.0σ ⇒ full penalty). `r_oil_t` excluded (thermal lag makes healthy transients look bad) |
| `anomaly` | 0.20 | `anomaly_score / 100` |
| `fault` | 0.25 | `P(class) × criticality(class)` (0 if HEALTHY) |
| `degradation` | 0.20 | severity from model 3 |
| `sensor` | 0.10 | fraction of missing/frozen sensors |

Mechanics:
- **Smoothing**: EMA with cadence-adaptive τ ≈ 60 s (measured Δt, so 10 Hz live and 1 Hz replay behave identically) + hard rate limit ±15 points per second of engine time.
- **Weight redistribution**: if a model output is missing, its weight is redistributed across available components — never silently ignored.
- **Data-quality gate**: below 60 % valid sensors the index is `stale` and capped at 50; confidence HIGH/MEDIUM/LOW from sensor fraction + missing models.
- **Categories**: NORMAL ≥ 85 · WATCH 70–84 · WARNING 50–69 · CRITICAL 30–49 · EMERGENCY < 30.
- **`explanation`** is engineer-readable: "EGT residual (max cyl) +76°C (4.2σ above healthy baseline)".
- `reset()` at mission start (no inheritance of a degraded EMA); `update(row, pred)` returns the full result dict; `explain_text(result)` pretty-prints.

Criticality table (also used by fault_prediction service): LUBRICATION_FAILURE 1.0 · OVERHEATING 0.90 · MISFIRE 0.75 · ABNORMAL_VIBRATION 0.70 · INJECTOR_DEGRADATION 0.65 · ALTERNATOR_DEGRADATION 0.50 · SENSOR_DRIFT 0.35 · SENSOR_DROPOUT 0.30 · UNKNOWN 0.50.

## 5. `inference.py` — streaming inference

- `InferencePipeline(model_dir)` — loads bundle + 4 models; `update(row)` → prediction once the feature window is warm; `predict_row(row)` = update+predict returning JSON-safe primitives with `sim_time_s`; `explain(row, pred)` prints the prediction line, top-3 physics residuals (observed vs expected), top-3 feature impacts (importance × z-score — a SHAP-free approximation), the recommended action, and a low-confidence caveat.
- `FallbackAnalyzer` — **the model-unavailable fallback** (never raises): z-scores residuals against bundle stats or built-in `DEFAULT_STATS`, anomaly = max|z| > 4, score = `100·max|z|/8`, rule-based class from residual signature (`r_oil_p < −2.5` → LUBRICATION_FAILURE, `r_cht_avg > 2.5` → OVERHEATING, `r_egt_max > 3.0 ∧ r_egt_avg > 0.5` → INJECTOR_DEGRADATION, `r_egt_max < −2.5` → MISFIRE, `r_vib > 3.0` → ABNORMAL_VIBRATION, `r_batt < −3.0` → ALTERNATOR_DEGRADATION, else UNKNOWN), severity = `max|z|/8`, slope-based RUL. Always `low_confidence: True`.
- `build_pipeline(model_dir)` — tries `InferencePipeline`, prints a warning and returns `FallbackAnalyzer` on any failure. **The dashboard keeps working with zero model files.**
- Alert ladder `_alert_level(...)`: CRITICAL if severity > 0.7 ∨ RUL < 5 min ∨ (LUBRICATION/OVERHEATING ∧ severity > 0.5); else ADVISORY if anomaly ∨ fault with severity > 0.35 ∨ RUL < 15 min; else WATCH if fault class with confidence < 0.6; else NONE.
- CLI: `python -m ml.inference --csv <telemetry.csv> --model-dir ml/models [--out preds.json] [--explain]` — streams a CSV, prints alert histogram + final prediction.

## 6. `train.py` — the training pipeline (one command)

```
python -m ml.train --runs-per-fault 2 --healthy-runs 4 --model-dir ml/models
```

1. **Generate labelled runs** — healthy + all 8 faults via `training_data.generate_training_runs()` (deterministic seeds, reuses the simulator).
2. **Feature extraction** per run (60 s window / 180 s trend / step 5).
3. **Run-level split** — train/val/test group *whole runs* (no row leakage), stratified by fault type.
4. **Fit** the 4 models of §3. The Isolation Forest threshold is fit on *validation* healthy windows at the 95th percentile (contamination prior 0.10) — not on test data.
5. **Evaluate** on held-out runs (`ml/evaluate.py`: metrics, confusion matrix, classification report).
6. **Serialise** models + `bundle.json` (feature names, class names, thresholds, healthy residual stats, window metadata).

## 7. `labels.py` — labelling rules

- `class` — first fault in `faults_active` (single-fault runs are the training default); `HEALTHY` otherwise.
- `severity` — max active fault severity ∈ [0, 1].
- `rul_min` — time until the primary fault is fully developed (`onset_s + ramp_s`) or mission end, whichever is smaller ÷ 60. Failure = severity ≥ 0.9. This is the **training-run** clock, so the live readout is rescaled before it is shown (see §3).
- `RunMeta` (per run: fault type, severity, onset, ramp, t_fail, mission end) is kept out of the features.
- Leakage prevention: run-level splits · causal features · scalers/thresholds fit on train/val only · stratified by fault type.

## 8. Other ML modules

| Module | Role |
|---|---|
| `training_data.py` | Deterministic mission-run generator for training (wraps the simulator with per-run FaultSpecs). |
| `evaluate.py` | Test-set metrics + confusion matrix, shared by train CLI and tests. |
| `demo_health_index.py` | Standalone EHI demo script. |
| `README.md`, `tests/` | Package docs and unit tests. |

## 9. Fallback chain (graceful degradation)

```
trained bundle present?  ── yes ─▶ InferencePipeline (4 models + explanations)
        │ no
        ▼
FallbackAnalyzer          physics-residual z-score rules, honest low confidence
        │ fails?
        ▼
ultra-minimal heuristic   vibration/RPM score, conf 0.3          (backend/services/anomaly.py)
```
Health index mirrors this: real calculator → rule-based `_fallback` in `backend/services/health_index.py`. Every API response stays well-formed at every level; `/health` reports `ml_models: loaded | fallback | error`.
