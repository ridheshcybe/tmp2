# AeroTwin Synthetic Telemetry Generator

Deterministic, physics-informed synthetic telemetry for the Aero Piston Engine
digital twin prototype (SIH26054 / DRDO). Generates realistic sensor streams
for a healthy engine and for 8 fault modes, with ground-truth labels, and
exports CSV (+ optional validation plots).

> These are **simulation equations** calibrated to realistic sensor envelopes —
> they are *not* certified engine equations and must not be presented as such.

## Quick start

```bash
# healthy mission (~99 min at 1 Hz → ~6,000 rows)
python -m simulator.telemetry_gen.run_simulation --out data/aerotwin_healthy_demo.csv

# demo fault sequence + validation plot
python -m simulator.telemetry_gen.run_simulation --demo-faults --plot \
    --out data/aerotwin_faulty_demo.csv
```

## Configuration

| Flag | Default | Purpose |
|---|---|---|
| `--hz` | `1.0` | Sampling rate (Hz). Use `10` to match the live streamer. |
| `--seed` | `42` | RNG seed — same seed ⇒ identical output. |
| `--out` | `data/aerotwin_telemetry.csv` | CSV output path. |
| `--plot` | off | Write `<out>_plot.png` (needs matplotlib). |
| `--phase-duration` | — | e.g. `CRUISE=600,ENDURANCE=900` to compress the mission. |
| `--fault` | — | `TYPE@SEVERITY:ONSET_S:RAMPS`, repeatable. |
| `--fault-drift-channel` | `egt_c2` | Channel for `SENSOR_DRIFT`. |
| `--fault-drop-channel` | `egt_c1` | Channel for `SENSOR_DROPOUT`. |
| `--demo-faults` | off | Predefined 6-fault demo sequence. |
| `--ambient-offset` | `0.0` | °C added to ISA ambient (e.g. `+15` = hot weather). |

Example: `--fault INJECTOR_DEGRADATION@0.6:1380:240` injects injector
degradation at severity 0.6, starting at t=1380 s, ramping in over 240 s.
`RAMPS=0` (or omitted) = sudden onset.

## Mission phases

`STARTUP → TAKEOFF → CLIMB → CRUISE → ENDURANCE → DESCENT → LANDING` (default
durations 120 / 60 / 900 / 1800 / 2400 / 600 / 90 s). Throttle and altitude
ramp linearly within each phase; altitude follows ISA conditions.

## Output schema (CSV columns)

`timestamp`, `sim_time_s`, `phase`, `throttle`, `altitude_ft`,
`ambient_temp_c`, `rpm`, `fuel_flow_lph`, `cht_c1..c4`, `egt_c1..c4`,
`oil_pressure_kpa`, `oil_temp_c`, `vibration_rms_g`, `battery_v`,
`alternator_a`, `injection_timing_deg`, `faults_active` (ground truth, comma-
joined), `fault_severity` (max active severity).

## Fault → sensor effects (exact)

| Fault | Sensors that change | How they change over time | Onset type |
|---|---|---|---|
| **INJECTOR_DEGRADATION** | `egt_cX`, `cht_cX` (one cylinder), `fuel_flow_lph`, `vibration_rms_g`, `injection_timing_deg` | Lean burn: EGT +120·s + 25·s·sin(2π·0.35·t) pulsing, CHT +22·s, fuel flow −2.8·s with the same 0.35 Hz pulsation, vibration +0.28·s, injection advance −3·s | Gradual (ramp) |
| **MISFIRE** | `egt_cX` −150·s (cold cylinder), `cht_cX` −35·s, `rpm` −300·s, `fuel_flow_lph` +0.7·s (unburned), `vibration_rms_g` +0.9·s with 0.4 Hz surging, other EGTs +25·s | Instantaneous lost combustion; vibration surges periodically at ~0.4 Hz | Sudden (step) |
| **LUBRICATION_FAILURE** | `oil_pressure_kpa` ↓, `oil_temp_c` ↑, all `cht`/`egt` ↑, `vibration_rms_g` ↑, `rpm` ↓ | Oil pressure −120·s accelerating (progress^0.3 shaped), oil temp +10·s, CHT/EGT +15/18·s, vibration +0.35·s, RPM −100·s | Gradual (ramp) |
| **OVERHEATING** | all `cht` +65·s, all `egt` +55·s, `oil_temp_c` +16·s, `oil_pressure_kpa` −55·s, `rpm` −380·s (thermal derate) | Steady climb of all temperatures; derate kicks in with severity | Gradual (ramp) |
| **SENSOR_DRIFT** | target channel only | Linear additive drift: severity × rate × (elapsed hr). Rates: EGT 90 °C/h, CHT 40 °C/h, oil pressure 25 kPa/h, RPM 120/h, battery 0.4 V/h, … | Gradual, linear |
| **SENSOR_DROPOUT** | target channel only | Channel holds its last value (stuck-at) after a 30 s grace period | Sudden (freeze) |
| **ABNORMAL_VIBRATION** | `vibration_rms_g`, slight `cht`/`egt` ripple | Vibration +1.5·s with 0.22 Hz pulsation (+0.35·s·sin); CHT/EGT ripple +8/12·s | Gradual (ramp) |
| **ALTERNATOR_DEGRADATION** | `alternator_a`, `battery_v` | Alternator output −20·s A (floor 0), battery decays −2.1·s V toward 11.6 V; below 1500 RPM bus runs on battery (≤12.4 V) | Gradual (ramp) |

`s` = effective severity (configured severity × ramp progress, 0→1).

## Determinism

The only randomness source is `numpy.random.default_rng(seed)` — engine noise,
cylinder spread jitter, and fault noise all flow through it. Same
`(--hz, --seed, plan, faults, ambient_offset)` ⇒ byte-identical CSV.

## Validation

```bash
python -m pytest simulator/telemetry_gen/tests -q
```

Tests assert: reproducibility, full phase coverage, physical-envelope
compliance, and per-fault sensor responses (e.g. misfire cools `egt_cX`,
injector degradation raises it, dropout freezes the channel, alternator
degradation drains the battery).

## Integration notes

- The CSV schema is a superset of what the downstream
  `fusion_ml/sensor_validator.py` expects — the enrichment pipeline can
  consume these datasets for offline training of the VAE / RUL models.
- The live 10 Hz `telemetry_streamer.py` remains the real-time source; this
  generator produces offline datasets, mission replay material, and
  fault-labelled training data (`faults_active` column is the ground truth).