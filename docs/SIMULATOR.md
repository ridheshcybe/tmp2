# AeroTwin — Simulator (Physics Telemetry Generator)

Package `sih/simulator/` — the ground-truth world. A physics-based generator that produces realistic 10 Hz telemetry for a ~100–130 hp air-cooled, horizontally-opposed 4-cylinder aero piston engine (the class used in MALE UAVs such as DRDO Tapas-BH-201), plus the fault-injection engine that corrupts it.

> **Honesty note (from the source):** these are simulation equations *calibrated to land inside realistic sensor envelopes* (idle vs cruise vs climb), **not certified engine equations**. They exist to make the digital-twin demonstrator behave credibly and to give residual-based fault detection a meaningful baseline.
>
> **Determinism:** the only randomness is the injected `numpy.random.default_rng(seed)` — same seed, identical missions (`SIM_SEED=42` by default).

Layout:

```
simulator/
├── telemetry_gen/          ← the live generator used by the backend
│   ├── engine_model.py       physics engine model + isa_conditions()
│   ├── fault_injection.py    FaultInjector, FaultSpec, 8 fault modes
│   ├── mission_profiles.py   phase segments (throttle/altitude timeline)
│   └── telemetry_schema.py   FaultType/MissionPhase enums, noise, channels
├── engine_physics.py       alternate physics helper module
├── environment_model.py    atmosphere/environment model
├── fault_injector.py       alternate injector helper
├── generate_datasets.py    batch dataset generation (CSV)
├── telemetry_streamer.py   streaming helper
└── test_client.py          WS smoke-test client
```

---

## 1. `engine_model.py` — `EngineModel`

Sub-models, stepped once per tick by `EngineModel.step(throttle, altitude_ft, ambient_temp_c)`:

| Sub-model | Model shape | Calibration constants |
|---|---|---|
| ISA atmosphere | `isa_conditions(altitude_ft)` → ambient temp, pressure, `density_ratio` | standard lapse rates |
| RPM dynamics | first-order lag toward a throttle × air-density target | `RPM_IDLE=1100`, `RPM_MAX=5600`, `RPM_EXPONENT=0.95`, `TAU_RPM_S=1.0` |
| Fuel flow | power law on effective throttle | `FUEL_IDLE_LPH=1.1`, `FUEL_GAIN_LPH=13.8`, exponent 1.3 |
| CHT (per cyl) | Newton cooling, slow thermal lag | `TAU_CHT_S=45.0` |
| EGT (per cyl) | fast, altitude-lean effect | `TAU_EGT_S=2.0` |
| Oil temp | slow integrator | `TAU_OIL_S=400.0` |
| Oil pressure | pump ∝ RPM, viscosity ∝ temp | `OIL_P0_KPA=265.0`, `OIL_P_RPM_KPA=0.052`, `OIL_P_TEMP_KPA` |
| Vibration | RMS baseline ∝ RPM + load | — |
| Electrical | battery/alternator bus | charging above ~1500 RPM (14.25 V vs 12.55 V) |
| Injection timing | RPM advance + CHT retard, clamped 18–38° | — |

Sensor noise is applied per channel from `telemetry_schema.SENSOR_NOISE_STD`. Per-cylinder manufacturing spread (±15 °C EGT offset) is deliberate — the physics baseline is cylinder-*symmetric*, so that spread is a learnable, documented pattern.

## 2. `fault_injection.py` — the 8 fault modes

`FaultSpec(fault_type, severity 0–1, onset_s, ramp_s, channel)` + `FaultInjector.apply(row, t)`. Effects **ramp in** over `ramp_s` (60 s via the REST API); ground truth is written into the row (`faults_active`, `fault_severity`).

| Fault | Affected sensors |
|---|---|
| `INJECTOR_DEGRADATION` | EGT/CHT cyl ↑ (lean) · fuel flow ↓ + oscillates · vibration ↑ · injection advance ↓ |
| `MISFIRE` | EGT/CHT cyl ↓ (cold) · vibration ↑ periodic · RPM ↓ · fuel flow ↑ (unburned) |
| `LUBRICATION_FAILURE` | Oil pressure ↓ accelerating · oil temp ↑ · CHT/EGT ↑ |
| `OVERHEATING` | All CHT/EGT ↑ · oil temp ↑ · oil pressure ↓ · RPM ↓ |
| `SENSOR_DRIFT` | One channel drifts linearly (rate per `DRIFT_RATES`, e.g. CHT 40 °C/h, RPM 120 rpm/h at severity 1.0) |
| `SENSOR_DROPOUT` | One channel freezes stuck-at-last-value after a 30 s grace period (`DROPOUT_GRACE_S`) |
| `ABNORMAL_VIBRATION` | Vibration ↑ with low-frequency pulsing · CHT/EGT ripple |
| `ALTERNATOR_DEGRADATION` | Alternator current ↓ · battery voltage decays |

Driftable channels for `SENSOR_DRIFT`/`SENSOR_DROPOUT` (`target_sensor` in the inject API): `rpm`, `fuel_flow_lph`, `cht_c1..c4`, `egt_c1..c4`, `oil_pressure_kpa`, `oil_temp_c`, `vibration_rms_g`, `battery_v`, `alternator_a`, `injection_timing_deg`.

Each fault's residual *signature* is what the ML fallback rules key on (see ML_MODELS.md §5) — e.g. lubrication failure → `r_oil_p` strongly negative.

## 3. `mission_profiles.py` — mission timeline

`PhaseSegment(phase, duration_s, throttle_start→end, altitude_start→end_ft)`; throttle/altitude ramp **linearly** within each segment. `MissionProfile.at(t)` returns `(phase, throttle, altitude_ft)`. `build_mission_plan(duration_overrides=None)` allows compressing long phases for demos.

Default plan (~99 min at 1 Hz):

| Phase | Duration | Throttle | Altitude |
|---|---|---|---|
| STARTUP | 120 s | 0.10 → 0.12 | 0 ft |
| TAKEOFF | 60 s | 0.15 → 0.95 | 0 → 800 ft |
| CLIMB | 900 s | 0.88 → 0.85 | 800 → 18 000 ft |
| CRUISE | 1800 s | 0.78 | 18 000 ft |
| ENDURANCE | 2400 s | 0.68 → 0.70 | 18 000 → 19 000 ft |
| DESCENT | 600 s | 0.30 → 0.25 | 19 000 → 1 500 ft |
| LANDING | 90 s | 0.15 → 0.06 | 1 500 → 0 ft |

The backend simulator runs this at `SIM_HZ=10`; mission `duration_s` caps wall-clock run time. Interactive overrides (`POST /api/simulation/throttle|altitude`) beat the profile from the next tick; `POST /api/simulation/throttle/release` hands control back to the profile.

Two other plans ship in `mission_profiles.py`:

- **`test_flight`** — the same phase shape compressed to ~2.5 min (STARTUP 15 s, TAKEOFF 12 s, CLIMB 30 s, CRUISE 40 s, DESCENT 30 s, LANDING 15 s). This is what the dashboard's **Test Flight** button flies.
- **`manual`** — a single `MANUAL` segment: the engine parks at ground idle (throttle 0.05, 0 ft) for the session duration. Used for interactive sessions: presets, the throttle slider and the paired phone controller command the throttle from the next tick, and "To Idle" releases the override back to this plan.

## 4. `telemetry_schema.py` — the data contract

- Enums: `FaultType` (9 values incl. HEALTHY), `MissionPhase` (7 flight phases + `MANUAL` for interactive sessions), `PHASE_ORDER`.
- `NUM_CYLINDERS=4`, `CYLINDER_KEYS`, `SENSOR_NOISE_STD` per channel, `DRIFTABLE_CHANNELS`.
- This is the shared vocabulary imported by the backend, ML, and physics baseline — one schema, no drift.

## 5. Support modules

| Module | Role |
|---|---|
| `generate_datasets.py` | Batch CSV generation (training data at scale, 1 Hz storage cadence). |
| `telemetry_streamer.py` | Streaming helper for feeding telemetry to consumers. |
| `test_client.py` | WebSocket smoke-test client for the backend. |
| `engine_physics.py`, `environment_model.py`, `fault_injector.py` | Shared physics/atmosphere/fault helpers used by both the generator and alternate tooling. |
| `tests/` | Unit tests (engine physics, fault injector behaviour, mission profiles). |

## 6. Frame → database → ML mapping

The engine row (flat, CSV-keyed) is what ML consumes; the API frame (arrays) is what the frontend consumes:

```
engine row: {rpm, fuel_flow_lph, cht_c1..c4, egt_c1..c4, oil_pressure_kpa,
             oil_temp_c, vibration_rms_g, battery_v, alternator_a,
             injection_timing_deg, faults_active, fault_severity}
   │ SimulatorService._build_frame()
   ▼
API frame:  {rpm, fuel_flow_lph, cht:[c1..c4], egt:[c1..c4], oil_pressure_kpa,
             oil_temp_c, vibration_rms, battery_voltage, alternator_current,
             injection_timing, injected_fault, fault_severity, ...}
   │ DigitalTwinService._frame_to_row()   (exact inverse mapping)
   ▼
ML row:     flat CSV-keyed dict again → physics_baseline / FeatureExtractor
```
