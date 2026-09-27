# AeroTwin

## Physics-Constrained Real-Time Digital Twin & Predictive Health Monitoring System for MALE UAV Aero Piston Engines

**Smart India Hackathon 2026 | Problem Statement: DRDO**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-2.0-EE4C2C?style=flat&logo=pytorch&logoColor=white)
![Node.js](https://img.shields.io/badge/Node.js-20-339933?style=flat&logo=node.js&logoColor=white)
![Three.js](https://img.shields.io/badge/Three.js-0.169-000000?style=flat&logo=three.js&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-24-2496ED?style=flat&logo=docker&logoColor=white)
![SIH](https://img.shields.io/badge/SIH-2026-FF6B35?style=flat)
![DRDO](https://img.shields.io/badge/DRDO-Tapas--BH--201-1E3A5F?style=flat)

---

## Executive Summary

### The Problem

**Medium Altitude Long Endurance (MALE)** unmanned aerial vehicles like the **DRDO Tapas-BH-201** and **Archer-NG** conduct critical Intelligence, Surveillance, and Reconnaissance (ISR) missions lasting **18-24 hours** over hostile territories. These platforms rely on **aero piston engines** operating at sustained high power settings, making them vulnerable to:

- **Gradual mechanical degradation** (piston ring wear, valve leakage)
- **Thermal anomalies** (lean burn conditions causing EGT spikes)
- **Sensor failures** (frozen or drifting instrumentation)
- **Cascading failures** leading to **catastrophic engine loss**

### Why Traditional Thresholding Fails

| Approach | Limitation |
|----------|------------|
| **Static Thresholds** | Cannot adapt to varying altitude, temperature, or load conditions |
| **Single-Parameter Monitoring** | Misses correlated multi-sensor degradation patterns |
| **Reactive Alarms** | Detect failures only after they occur, leaving no RTB margin |
| **Manual Pilot Monitoring** | Cognitive overload during complex ISR missions |

### Our Solution: 30-Minute RTB Early Warning

AeroTwin provides **predictive health monitoring** that detects anomalies **30 minutes before critical failure**:

```
DETECTION TIMELINE

Anomaly Onset ──> AI Detection ──> RTB Advisory ──> Critical
     |                  |                |               |
  T-45 min          T-30 min         T-15 min         T-0
     |                  |                |               |
     └──────────────────┴────────────────┴───────────────┘
                    30-MINUTE RTB WINDOW

✓ Asset preservation  ✓ Mission continuity  ✓ Pilot safety
```

---

## Core Technical Innovations

### 1. Hybrid Thermodynamic & Environmental Simulator

A **10 Hz real-time simulator** modeling complete engine physics with ISA atmospheric conditions:

| Component | Implementation |
|-----------|----------------|
| **ISA Atmosphere Model** | Temperature lapse rate, barometric pressure, air density up to 25,000 ft |
| **Crank-Slider Kinematics** | Accurate piston displacement: x = r*cos(theta) + sqrt(l^2 - r^2*sin^2(theta)) |
| **4-Cylinder Thermodynamics** | Independent CHT/EGT per cylinder with Newton's law of cooling |
| **Fuel-Air Mixing** | BSFC-based fuel flow with equivalence ratio effects |
| **Sensor Noise Model** | Gaussian noise injection for realistic sensor behavior |
| **Weather Modifiers** | HUMID (-1.5% density), RAIN (-3K intake), DUST (-3% efficiency) |

### 2. Dynamic Sensor Validation & Freeze Detection

```
SENSOR VALIDATION PIPELINE

Raw Telemetry ──> FIFO Buffer (N=600) ──> Freeze Detection
     |                   |                       |
     |                   |              var(buffer) < 1e-6
     |                   |                       |
     |                   v                       v
     |          Physical Range Check    ISOLATED_FROZEN
     |                   |
     v                   v
ISOLATED_OOB    +-----------------+
                |  SanitizedFrame  |
                |  * valid_sensors |
                |  * sensor_mask   |
                |  * flags         |
                +-----------------+
```

- **Rolling FIFO Buffer**: 600 samples (60 seconds at 10 Hz) per channel
- **Freeze Detection**: Variance < 1e-6 over full buffer triggers isolation
- **Physical Bounds**: Per-channel clamping (RPM: 0-6000, CHT: -20-350C, etc.)

### 3. Physics-Constrained Cross-Modal Attention Fusion

Three sensor modalities fused via multi-head attention:

| Modality | Sensors | Embedding |
|----------|---------|-----------|
| **Thermal** | CHT 1-4, EGT 1-4, Ambient_Temp (9 features) | d=64 |
| **Mechanical** | RPM, MAP, Vibration (3 features) | d=64 |
| **Fluid** | Fuel_Flow, Oil_Pressure, Oil_Temp (3 features) | d=64 |

**Physics-Constrained Loss Function:**
```python
# Penalize thermodynamic violations
if fuel_flow Increases AND NOT (RPM Increases OR EGT/CHT Increases):
    penalty += physics_weight * violation_magnitude
```

### 4. Dual AI Pipeline

```
DUAL AI ARCHITECTURE

Fused Vector (32-dim)
     |
     +---> Variational Autoencoder (VAE)
     |    * Encoder: 32->64->32->mu,logvar (16-dim latent)
     |    * Beta-VAE Loss: MSE + 0.01*KL
     |    * Anomaly Score: 0-100 based on reconstruction error
     |    * Threshold: 99th percentile of nominal data
     |
     +---> TCN + XGBoost RUL Predictor
          * TCN: 3 dilated causal conv blocks (d=1,2,4)
          * Sliding Window: 300 samples (30 seconds)
          * XGBoost: 19-dim features -> RUL (minutes)
          * NASA PHM Scoring Function
          * RTB Thresholds: <=30 min Advisory, <=10 min Critical
```

### 5. Interactive 3D Digital Twin

| Feature | Implementation |
|---------|----------------|
| **Procedural Geometry** | 4-cylinder horizontally-opposed boxer engine |
| **RPM-Linked Animation** | Crankshaft rotation + piston reciprocation |
| **CHT Heatmap Shader** | Custom GLSL: Green->Amber->Red with pulsing emissive |
| **Camera Presets** | Overview, Bank A, Bank B, Top View |
| **Exploded View** | Slider to separate components for inspection |
| **Real-time Charts** | Chart.js streaming at 10 Hz for CHT, EGT, RPM, Anomaly |

---

## System Architecture

```
+===========================================================================+
|                         SIMULATION LAYER                                   |
|                                                                           |
|  +------------------+    +------------------+    +------------------+    |
|  |  ISA Atmosphere   |--->| Engine Physics    |--->| Fault Injector   |    |
|  |  Model (0-25k ft) |    | (4-Cyl Boxer)    |    | (5 Fault Modes)  |    |
|  +------------------+    +--------+---------+    +------------------+    |
|                                    |                                      |
|                                    v                                      |
|                           +------------------+                           |
|                           | Telemetry Stream  |                           |
|                           | (10 Hz WebSocket) |                           |
|                           +--------+---------+                           |
+====================================|=======================================+
                                     |
                                     v
+===========================================================================+
|                          AI/ML LAYER                                       |
|                                                                           |
|  +------------------+    +------------------+    +------------------+    |
|  | Sensor Validator  |--->| Cross-Modal       |--->| Health Index     |    |
|  | (Freeze/OOB)     |    | Fusion (4-Head)   |    | Calculator       |    |
|  +------------------+    +--------+---------+    +------------------+    |
|                                    |                                      |
|                         +----------+----------+                           |
|                         v                      v                           |
|                +------------------+    +------------------+               |
|                | Anomaly VAE   
