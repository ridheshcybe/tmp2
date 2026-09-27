# Engine Health Index (EHI) — Design Specification

*A transparent 0–100 health score for the AeroTwin aero-piston-engine digital
twin, written for the person who has to decide whether the UAV flies today.*

| | |
|---|---|
| **Scope** | AeroTwin software demonstrator (SIH26054). Physics-informed, synthetic-telemetry based. Not a certified airworthiness index. |
| **Read this first** | `ml/health_index.py` (implementation), `ml/tests/test_health_index.py` + `ml/tests/test_health_index_streaming.py` (tests), `ml/demo_health_index.py` (runnable demo). |
| **One sentence** | EHI is a weighted sum of five explainable penalties — every point lost is traceable to a physical observation in plain language. |

**What the number means**

- **100** — a healthy engine at the current operating point (physics model says
  every sensor is where it should be).
- **0** — do not fly.
- It is **not** a probability of failure and **not** a certified rating. It is
  an *early-warning decision-support score* computed from residual, anomaly,
  fault, degradation, and sensor-quality evidence, updated continuously.

---

## 1. Exact formula

```
EHI = 100 × (1 − Σᵢ wᵢ · pᵢ),   clamped to [0, 100]

p_residual     = worst normalised physics residual  = max_channel(|obs − expected|σ  / Z_MAX),   capped 0..1
p_anomaly      = anomaly score / 100                                                        (0..1)
p_fault        = fault probability × fault criticality                                      (0..1)
p_degradation  = degradation severity                                                       (0..1)
p_sensor       = 1 − (valid sensors / expected sensors)                                     (0..1)

expected value = physics baseline at current throttle, altitude, ambient, RPM   ← operating-condition-adjusted
residual       = observed − expected
z              = (residual − healthy_mean) / healthy_σ                           ← per-channel healthy statistics
```

Implementation: `ml/health_index.py::compute_ehi`, `::_residual_penalty`.
The physics expectations are in `ml/physics_baseline.py::expected_sensors`
(analytic, mirrors the simulator calibration — no training required).

### Where each requested input lives

| Requested input | Term | Source |
|---|---|---|
| Physics residuals | `p_residual` | `residual_summary(row)` in `ml/physics_baseline.py` |
| Operating-condition-adjusted limits | healthy `(μ, σ)` per residual channel + Z_MAX=8 | `HEALTHY_RESIDUAL_STATS`, `Z_MAX` in `ml/health_index.py` |
| Anomaly score | `p_anomaly` | Isolation-Forest margin → `anomaly_score` (fallback: physics-residual z-rule) |
| Fault probabilities | `p_fault` | classifier `confidence` |
| Fault criticality | `CRITICALITY[class]` | table in `ml/health_index.py` (see §6) |
| Degradation score | `p_degradation` | regressor `severity` 0..1 |
| Sensor reliability | `p_sensor` | presence/validity check over 15 channels + optional `sensor_valid` map |

### Operating-condition-adjusted limits (why there are no fixed thresholds)

CHT of 150 °C is fine in cruise and alarming on the ground; oil pressure of
350 kPa is normal at 4000 rpm and wrong at idle. Fixed thresholds would fire
false alarms on every throttle move. Instead:

1. The physics baseline predicts the **healthy value for the current
   operating point** (throttle, altitude, ambient temperature, RPM, oil
   temperature) — see the equations in `ml/physics_baseline.py`.
2. The residual is compared against **healthy residual statistics** collected
   across the full operating envelope (per-channel μ and σ).
3. Penalty = `|z| / Z_MAX` with Z_MAX = 8.0 ≈ a >6σ event ⇒ full penalty.

So the “limit” moves with the operating point automatically, and the units
stayed physical (°C, kPa, l/h, g, V, A) — which is what makes the explanation
readable.

---

## 2. Recommended weights

`DEFAULT_WEIGHTS` in `ml/health_index.py` (sum = 1.0):

| Component | Weight | Rationale |
|---|---|---|
| Residual | 0.25 | Direct physical evidence — sensor deviates from the physics model **now**. |
| Fault | 0.25 | Classified fault probability × criticality — highest information density. |
| Anomaly | 0.20 | Catches *unseen* patterns the classifier has no label for. |
| Degradation | 0.20 | Slow wear/severity trend; deliberately smaller so a mis-calibrated severity model cannot dominate. |
| Sensor | 0.10 | Data-quality gate. Small but never zero: a score from broken sensors must not look trustworthy. |

**Redistribution.** If a model output is missing (e.g., no trained anomaly
model), its weight is redistributed proportionally over the *available*
components (`weights_used`), and the explanation says so. Never silently drop
evidence. Rule of thumb: residuals carry the weight when ML is unavailable —
the index still works, at lower confidence.

---

## 3. Smoothing method

Perceived score never jumps: raw per-tick score → exponential moving average
plus a hard rate limit.

```
α        = 1 − exp(−dt_eff / τ),        τ = 60 s
step_cap = max_step × dt_eff / dt_s,    max_step = 15 points
smoothed = previous + clamp(α·(raw − previous), −step_cap, +step_cap)
```

- `dt_eff` is the **measured** simulated-time interval between updates,
  clamped to ≤ one nominal tick (`dt_s` = 1 s). This makes smoothing
  cadence-independent: the live API feeds frames at 10 Hz (Δt = 0.1 s) and
  CSV replay at 1 Hz, and both produce the same physical response
  (τ ≈ 60 s, ≤ 15 points/s of engine time).
- A data gap (Δt large) never causes a jump — one update may move at most
  `max_step` points, and the EMA barely advances across a gap.
- Trend is reported from a 5-minute window of the smoothed history
  (`delta_5min`): < −2 points ⇒ `declining`, > +2 ⇒ `improving`.

*Why 60 s?* Short enough to flag a developing fault within a minute of
evidence, long enough that a single noisy frame cannot swing the needle. The
±15/s clamp guarantees the gauge is readable during the demo.

Implementation: `HealthIndexCalculator.update`, `::_dt_effective`
(cadence-adaptive fix), `::_trend`.

---

## 4. Missing-data handling

| Situation | Behaviour |
|---|---|
| One channel NaN / frozen / `sensor_valid[ch]=False` | Counted in `bad_channels`; raises `p_sensor`; named in explanation. |
| < 95 % valid | Confidence `MEDIUM`. |
| < 80 % valid | Confidence `LOW`. |
| < 60 % valid (`MIN_SENSOR_FRACTION`) | State `STALE`; **index capped at 50** (a score above that would imply we know more than we do); confidence `LOW`. |
| Model output missing (no `anomaly_score`, `severity`, …) | Weight redistribution (§2); `weights_used` shows the new split; explanation line “Models unavailable (…); weights redistributed to remaining evidence.” |
| Whole ML pipeline down | `backend/services/health_index.py` rule-based fallback computes from anomaly score + fault severity at reduced confidence; the streaming service still answers. |

The calculator never fabricates a reading for a lost sensor — it treats a
missing sensor as *evidence of a problem*, because in an engine-monitoring
context a dead channel is itself a maintenance signal.

---

## 5. Health categories

`CATEGORY_RANGES` in `ml/health_index.py` — evaluated highest-first.

| Range | Category | Operational meaning | Gauge |
|---|---|---|---|
| ≥ 85 | `NORMAL` | All evidence within healthy limits | green |
| 70 – 84 | `WATCH` | Mild deviation; continue, monitor | light green / teal |
| 50 – 69 | `WARNING` | Degraded; plan inspection, avoid aggressive throttle | amber |
| 30 – 49 | `CRITICAL` | Real fault evidence; abort objective / consider RTB | orange/red |
| < 30 | `EMERGENCY` | Loss-of-engine risk; land immediately | red |

Category boundaries are **stable** and purely score-driven — an engineer can
memorise them. They are deliberately *not* re-derived per operating point;
the operating-point dependence lives in the residual penalty (§1).

---

## 6. Alert rules

`alert_level(ehi, penalties, class)` — the alert that reaches the operator:

| Condition | Alert |
|---|---|
| `EHI ≥ 85` | `NONE` |
| `EHI ≥ 70` | `WATCH` |
| `EHI < 70` OR anomaly penalty > 0.35 OR degradation > 0.35 | `ADVISORY` |
| `EHI < 50` OR degradation > 0.7 OR (fault penalty > 0.5 AND criticality ≥ 0.75) | `CRITICAL` |

Criticality table (`CRITICALITY`): LUBRICATION_FAILURE 1.0 · OVERHEATING 0.90 ·
MISFIRE 0.75 · ABNORMAL_VIBRATION 0.70 · INJECTOR_DEGRADATION 0.65 ·
ALTERNATOR_DEGRADATION 0.50 · SENSOR_DRIFT 0.35 · SENSOR_DROPOUT 0.30 ·
UNKNOWN 0.50.

**Escalation is single-trigger, not sticky.** Every tick re-evaluates: a
fault that clears stops alerting immediately (the smoothed score still takes
~1 min to climb back). In the dashboard these map to the alert banner, and
`backend/services/digital_twin.py::_build_alerts` turns `CRITICAL` health or
fault states into structured `alerts[]` entries broadcast over WebSocket.

---

## 7. Explanation generation

Every result carries a plain-language, multi-line explanation — the text the
dashboard renders beside the gauge. Template:

```
Health Index: <score>/100 · <CATEGORY> · trend <trend>
Main contributors:
  – <top contributor label, physical units, σ>
  – <fault class> probability <conf> (criticality <crit>)
  – Anomaly score <n>/100
  – Degradation score <n>
  – <n> sensors degraded (<names>)
Recommended action: <one-line maintenance instruction>
[Data quality POOR — >40% sensors unavailable; index capped at 50.]
[Models unavailable (<names>); weights redistributed to remaining evidence.]
```

Rules:
- Contributors are sorted by penalty; only penalties > 0.05 appear; top 4 shown.
- Residual labels use **units and σ**, not feature names: e.g.
  `EGT residual (max cyl) +71°C (11.5σ above healthy baseline)` — never
  `feature_17 = 0.83`.
- The recommended action comes from a per-fault table written for the
  maintainer (`ml/inference.py::ACTIONS`).
- The explanation list is exactly what is stored per frame in the database
  and printed in the mission report — the operator can always answer
  *“why is it a 33?”*.

---

## 8. Python implementation

| Concern | File / symbol |
|---|---|
| Core calculator | `ml/health_index.py::HealthIndexCalculator` (`update()` per tick) |
| Pure formula | `ml/health_index.py::compute_ehi`, `::category`, `::alert_level` |
| Physics expected values / residuals | `ml/physics_baseline.py::expected_sensors`, `::residual_summary` |
| Constants (weights, criticality, stats, channels) | module constants in `ml/health_index.py` |
| Streaming API wrapper + fallback | `backend/services/health_index.py::HealthIndexService` |
| Mission-start reset | `HealthIndexService.reset()` → called in `backend/routes/mission.py` |
| Orchestration | `backend/services/digital_twin.py::DigitalTwinService.process_frame` |
| Render | `frontend/src/components/dashboard/MasterHealthGauge.tsx` |

Typical call (streaming, 10 Hz):

```python
from ml.health_index import HealthIndexCalculator
calc = HealthIndexCalculator()          # optionally healthy_stats=bundle["healthy_residual_stats"]
for row, pred in stream():              # row = CSV-keyed telemetry, pred = ML inference dict
    result = calc.update(row, pred)     # ehi, category, alert_level, contributors, explanation, …
```

Regenerate the demo artifacts:

```bash
python -m ml.demo_health_index --csv data/aerotwin_faulty_demo.csv --every 2
# → data/ehi_timeline.csv and data/ehi_dashboard_example.txt
python -m pytest ml/tests/test_health_index.py ml/tests/test_health_index_streaming.py -q
```

---

## 9. Test cases

`ml/tests/test_health_index.py` — the ten core cases:

1. Healthy engine at steady state scores ≥ 85, NORMAL.
2. Extreme EGT residual deducts ≈ 25 points (residual weight × saturated penalty).
3. Anomaly score 95 deducts ≈ 20 points.
4. Critical fault (LUBRICATION_FAILURE) costs ≥ 10 points more than minor (SENSOR_DRIFT) at equal probability.
5. Severity = 1.0 deducts ≈ 20 points.
6. > 40 % sensors lost ⇒ sensor penalty, `STALE`, index capped at 50, confidence LOW.
7. Smoothing + rate limit: single update moves ≤ 15; converges after ~400 ticks.
8. Missing model fields ⇒ weight redistribution (0.25/0.35 ≈ 0.714) + explanation note.
9. Explanation is plain language (units, σ, action text present).
10. Alert rules, category boundaries, monotonicity, saturation.

`ml/tests/test_health_index_streaming.py` — cadence/robustness cases added for
the live API path:

1. τ is cadence-invariant — 10 Hz and 1 Hz feeds give the same score after 60 s.
2. Per-tick rate limit scales with Δt (1.5 pts @ 10 Hz vs 15 pts @ 1 Hz).
3. A 540 s data gap cannot jump the needle more than one capped update.
4. `reset()` at mission start restores a fresh healthy score (no EMA carry-over).

---

## 10. Example dashboard output

The text panel under the gauge (what the operator sees and the report prints).
Illustrative snapshots from the fault-injection demo mission
(`data/aerotwin_faulty_demo.csv` — synthetic telemetry); regenerate with
`python -m ml.demo_health_index`.

```
Health Index: 96/100 · NORMAL · trend stable          Health Index: 33/100 · CRITICAL · trend declining
alert: NONE  confidence: HIGH  data quality: 100%     alert: CRITICAL  confidence: HIGH  data quality: 100%
  Main contributors:                                     Main contributors:
    – all monitored channels within healthy limits         – EGT residual (max cyl) +71°C (11.5σ above healthy baseline)
                                                           – INJECTOR_DEGRADATION probability 0.85 (criticality 0.65)
   t ≈ 900 s · CRUISE · 18,000 ft · healthy engine         – Anomaly score 78/100
   rpm 4000 · EGT 638 °C avg · CHT 150 °C · oil 473 kPa    – Degradation score 0.60
                                                         Recommended action: Inspect injector / fuel delivery on the
   (t ≈ 2000 s · CRUISE · 18,000 ft · injector fault       affected cylinder; avoid high-throttle operation.
    injected at t ≈ 1380 s, severity ramping to 0.6.
    Cylinder 2 EGT 717 °C vs 647 °C expected — the
    physics model catches the fault the threshold
    table cannot: 647 °C is “normal” for cruise.)
```

A minute-by-minute read for the maintainer: healthy cruise reads ~96 with no
contributors. When the injector fault develops, the *physics* component
(EGT cyl-2 z ≈ 11.5) drags the score down first — faster and more specific
than a threshold — followed by the classifier probability and degradation,
until the smoothed score settles around 33 (CRITICAL) with a clear,
actionable explanation. When the fault clears or the mission restarts
(`reset()`), the score climbs back under the same rate limit, so the gauge
never “snaps”.

---

## 11. Honesty guardrails

- Label the score everywhere as **demonstrator / synthetic-data based**:
  “Engine Health Index (simulation)” on the gauge and in reports.
- Never display EHI as a probability or certified rating.
- When confidence is LOW (sensors missing, models unavailable), say so on the
  same panel as the number — the score and its trust level travel together.
