You are a senior aerospace systems architect, AI/ML engineer, digital-twin researcher, embedded systems engineer, frontend/backend developer, product manager, and Smart India Hackathon mentor.

We are participating in Smart India Hackathon with the following problem statement:

Problem Statement ID: SIH26054 / 26054

Title:
AI-Enabled Real-Time Digital Twin System for Health Monitoring, Fault Prediction and Mission Reliability Enhancement of Aero Piston Engines used in MALE UAVs.

Organization:
DRDO

Department:
Department of Defence Production / iDEX

Category:
Software

Theme:
Robotics and Drones

Our team is late and needs to rapidly build a credible, working, technically convincing software demonstrator. We need to prioritize execution, integration, demo quality, explainability, and judging impact over unnecessary complexity.

PROJECT CONTEXT

The system should create a real-time digital twin of an aero piston engine used in a MALE UAV. It must combine:

1. Engine sensor telemetry.
2. Thermodynamic and physics-based behavior models.
3. Engine performance maps.
4. Failure and degradation logic.
5. AI/ML-based predictive analytics.
6. Real-time dashboard visualization.
7. Mission simulation and historical replay.

Required monitoring parameters include:

- RPM.
- Cylinder Head Temperature, or CHT.
- Exhaust Gas Temperature, or EGT.
- Oil pressure.
- Oil temperature.
- Fuel flow.
- Vibration signatures.
- Battery and alternator health.
- Injection timing parameters.

Required diagnostic capabilities include:

- Misfire detection.
- Injector abnormality detection.
- Engine degradation detection.
- Lubrication issue detection.
- Sensor drift or sensor failure detection.
- Combustion instability detection.
- Overheating trend prediction.
- Abnormal vibration pattern detection.
- Engine health index calculation.
- Remaining Useful Life, or RUL, estimation.
- Predictive maintenance recommendations.

Required operational capabilities include:

- Real-time engine parameter visualization.
- Digital twin state synchronization.
- Historical mission replay.
- Mission-wise health reports.
- Environmental condition simulation.
- Simulation under high altitude.
- Endurance missions.
- Hot-weather operation.
- Rapid throttle transitions.
- Post-flight analysis.
- Fault injection for demonstration.
- Future edge deployment and cloud or local server analytics.

OUR PRIMARY GOAL

Design the smallest but strongest end-to-end prototype that can be completed quickly and demonstrated reliably.

The prototype does not need to control a real UAV or real engine. It should use a realistic synthetic engine telemetry generator and clearly explain that it is a software demonstrator suitable for future integration with CAN bus, SocketCAN, ECU, FADEC, engine test-rig, or real flight telemetry.

IMPORTANT ENGINEERING PRINCIPLE

Do not recommend building every advanced feature independently. Define:

- MVP features that must work.
- Strong demo features that create judging impact.
- Future roadmap features that can be shown architecturally but do not need full implementation.

The final recommendation should be practical for a student team with limited time.

TEAM ASSUMPTIONS

Assume the team can use:

- Python.
- FastAPI or Flask.
- React, Next.js, or another modern frontend.
- PostgreSQL, SQLite, or TimescaleDB.
- WebSockets.
- Pandas and NumPy.
- Scikit-learn.
- XGBoost or LightGBM if suitable.
- PyTorch only if genuinely necessary.
- Plotly, ECharts, Recharts, or similar dashboard libraries.
- Docker.
- GitHub.
- Google Colab for model training.
- VS Code and terminal.
- Open-source libraries.
- Synthetic data generation.
- A laptop or cloud notebook rather than specialized hardware.

The team has experience with Python, JavaScript, full-stack development, AI/ML, technical documentation, and research-style work.

REQUIRED RESPONSE STRUCTURE

Work as a strict product and engineering consultant. Do not provide vague suggestions. Produce an implementation-ready plan.

PART 1: REFRAME THE PROBLEM

Explain:

1. What the real operational problem is.
2. Who will use the system:
   - UAV operator.
   - Maintenance engineer.
   - Propulsion engineer.
   - Fleet manager.
   - Research or test-rig engineer.
3. What decisions the system should help users make.
4. What a digital twin means specifically for this project.
5. What the system should not claim, especially if it is based on synthetic data.
6. What makes this different from a normal IoT dashboard or threshold-based alerting system.

PART 2: DEFINE THE WINNING MVP

Create a table with these columns:

- Feature.
- Why it matters.
- Must-have or optional.
- Implementation difficulty.
- Demo impact.
- Recommended technology.
- Acceptance test.

Prioritize a working MVP containing:

1. Live synthetic engine telemetry.
2. Engine state estimation.
3. Physics-informed baseline model.
4. Engine Health Index.
5. Anomaly detection.
6. Fault classification.
7. RUL or degradation estimation.
8. Fault injection.
9. Mission replay.
10. Simulation of altitude, temperature, throttle, and endurance.
11. Maintenance recommendation.
12. Dashboard.
13. Exportable mission report.

Select only the most achievable algorithm for each requirement.

PART 3: PROPOSE THE SYSTEM ARCHITECTURE

Design a complete architecture using text and Mermaid diagrams.

Include:

1. Frontend.
2. Backend API.
3. WebSocket real-time streaming layer.
4. Telemetry simulator.
5. Digital twin engine.
6. Physics-based model.
7. Feature engineering service.
8. ML inference service.
9. Anomaly detection service.
10. Fault diagnosis service.
11. RUL/degradation service.
12. Mission simulator.
13. Historical replay service.
14. Database.
15. Alert and recommendation engine.
16. Report generation.
17. Optional edge deployment layer.

Show the complete data flow:

Telemetry source → ingestion → validation → digital twin synchronization → feature extraction → physics model → AI/ML inference → health index → fault prediction → alert → dashboard → mission report.

Explain which components should run synchronously and which can run asynchronously.

PART 4: RECOMMEND THE TECHNOLOGY STACK

Recommend one final stack, not five alternatives.

Compare only when necessary:

- React versus Next.js.
- FastAPI versus Flask.
- SQLite versus PostgreSQL.
- REST versus WebSockets.
- Scikit-learn versus PyTorch.
- Isolation Forest versus Autoencoder.
- XGBoost versus LSTM for RUL.
- Docker versus local execution.

For each recommendation, explain:

- Why it is suitable.
- How quickly the team can implement it.
- Its limitations.
- What to use during the hackathon.
- What to use in a production roadmap.

Keep the stack lightweight and reliable.

PART 5: DESIGN THE DIGITAL TWIN

Define the digital twin mathematically and architecturally.

Include:

1. Engine state vector.
2. Sensor observation vector.
3. Operating condition vector.
4. Health state.
5. Degradation state.
6. Fault state.
7. Environmental variables.
8. Mission state.
9. Model update frequency.
10. Data synchronization strategy.

Propose variables such as:

- RPM.
- CHT.
- EGT.
- Oil pressure.
- Oil temperature.
- Fuel flow.
- Vibration RMS.
- Vibration frequency features.
- Battery voltage.
- Alternator current.
- Injection timing.
- Throttle.
- Altitude.
- Ambient temperature.
- Humidity if useful.
- Engine load.
- Fuel remaining.
- Mission phase.
- Engine age or operating cycles.

Define how the digital twin will estimate values that are not directly measured.

Provide example equations or pseudocode for:

- Expected EGT.
- Expected CHT.
- Expected oil pressure.
- Fuel consumption.
- Vibration baseline.
- Sensor residual.
- Health score.
- Degradation score.

Use simplified, physically plausible equations. Clearly label them as simulation equations rather than certified engine equations.

PART 6: CREATE A SYNTHETIC DATA STRATEGY

Design a realistic synthetic telemetry generator because we may not have access to real aero piston engine data.

The generator must produce:

1. Healthy engine data.
2. Misfire data.
3. Injector degradation.
4. Lubrication failure.
5. Overheating.
6. Sensor drift.
7. Sensor dropout.
8. Abnormal vibration.
9. Combustion instability.
10. Alternator or battery degradation.
11. Rapid throttle transitions.
12. High-altitude operation.
13. Hot-weather operation.
14. Long-endurance operation.
15. Combined faults.

For each fault, specify:

- Which sensor changes.
- How the signal changes over time.
- Whether the change is gradual or sudden.
- The expected physical relationship.
- How to inject noise.
- How to prevent unrealistic data.
- The label format.
- The severity scale.
- The lead time before failure.

Propose an exact dataset schema in CSV or database form.

Include example rows.

Create a timeline model with:

- Timestamp.
- Mission ID.
- Engine ID.
- Mission phase.
- Operating conditions.
- Sensor readings.
- Ground-truth fault.
- Fault severity.
- Health index.
- Degradation percentage.
- RUL target.

PART 7: DESIGN THE PHYSICS-INFORMED LAYER

Create a simplified physics-informed model that makes the system look like a genuine digital twin instead of a generic ML dashboard.

Use relationships involving:

- RPM.
- Throttle.
- Engine load.
- Fuel flow.
- Air density.
- Altitude.
- Ambient temperature.
- CHT.
- EGT.
- Oil pressure.
- Oil temperature.
- Vibration.

Explain:

1. What is calculated using physics-inspired equations.
2. What is predicted using machine learning.
3. How residuals between expected and observed values are used.
4. How the model detects abnormal behavior.
5. How the physics layer improves explainability.
6. How the system behaves when the ML model is uncertain.

Include a hybrid model formulation such as:

Predicted sensor value =
physics-based expected value + data-driven correction

And:

Residual =
observed value - predicted value

PART 8: SELECT THE ML MODELS

Choose practical models for:

1. Anomaly detection.
2. Fault classification.
3. Sensor fault detection.
4. Degradation estimation.
5. RUL estimation.
6. Trend forecasting.
7. Maintenance recommendation.

For each model, specify:

- Input features.
- Output.
- Training data.
- Why the model is appropriate.
- Inference latency.
- Explainability approach.
- Evaluation metrics.
- Fallback method.

Prefer models that can work on synthetic time-series data and run easily on a laptop.

Discuss whether to use:

- Rule-based safety limits.
- Isolation Forest.
- One-Class SVM.
- Autoencoder.
- Random Forest.
- XGBoost.
- Logistic Regression.
- Gradient Boosting.
- LSTM.
- Temporal CNN.
- Kalman Filter.
- Exponential smoothing.

Give one final recommended model pipeline. Do not make deep learning mandatory unless it adds clear value.

PART 9: DESIGN THE HEALTH INDEX

Create a transparent Health Index from 0 to 100.

It should combine:

- Sensor residuals.
- Anomaly score.
- Fault probability.
- Degradation score.
- Operating-condition-adjusted limits.
- Criticality weighting.
- Data quality and sensor confidence.

Define:

1. The formula.
2. Weight values.
3. Normal, warning, critical, and emergency ranges.
4. How the health index changes over time.
5. How to avoid sudden unrealistic fluctuations.
6. How to handle missing sensors.
7. How to display the reasons behind the score.

Example output:

Health Index: 71/100
Status: Warning
Main contributors:
- EGT residual above expected level.
- Vibration RMS rising for 18 minutes.
- Oil pressure declining under constant RPM.
- Injector fault probability: 0.68.
Recommended action:
- Inspect injector and lubrication system within the next maintenance window.
- Avoid high-throttle operation until inspection.

PART 10: DESIGN RUL AND DEGRADATION LOGIC

Because real run-to-failure data may not be available, design a credible demonstrator approach.

Explain three options:

1. Synthetic degradation-based RUL.
2. Time-to-threshold prediction.
3. Survival or regression model.

Choose one primary approach and one fallback approach.

Define:

- What RUL means in this prototype.
- Whether it should be displayed in hours, mission cycles, or percentage.
- How to avoid falsely presenting synthetic RUL as certified.
- Confidence intervals.
- Uncertainty labels.
- Early warning thresholds.
- RUL trend graph.

Use a clear example:

RUL estimate: 42 operating hours
Confidence: Medium
Trend: Declining
Main evidence: increasing vibration, rising EGT residual, falling oil pressure.

PART 11: DESIGN THE FAULT-INJECTION DEMO

Create a dramatic but technically credible 5-minute demonstration.

The demo should begin with a healthy engine and then inject faults.

Design the exact sequence:

1. Mission initialization.
2. Takeoff phase.
3. Climb phase.
4. Cruise phase.
5. Endurance phase.
6. Hot-weather or high-altitude condition.
7. Injector degradation injection.
8. EGT and CHT trend changes.
9. Vibration increase.
10. Anomaly detection.
11. Fault classification.
12. RUL reduction.
13. Maintenance recommendation.
14. Mission risk score.
15. Mission replay.
16. Generated report.

Specify what appears on the dashboard at every stage.

Create two versions:

- A 2-minute backup demo.
- A 5-minute complete demo.

Also list likely demo failure points and fallback screenshots or prerecorded data.

PART 12: DESIGN THE FRONTEND

Design the dashboard as a high-quality mission-control interface.

Create the exact pages and components:

1. Overview dashboard.
2. Live engine twin.
3. Telemetry charts.
4. Health and risk panel.
5. Fault diagnosis panel.
6. RUL and degradation panel.
7. Mission simulator.
8. Historical replay.
9. Maintenance advisory.
10. Mission report.
11. System settings or data source page.

For every page, define:

- Purpose.
- Widgets.
- Data displayed.
- User actions.
- API endpoints needed.
- WebSocket events needed.
- Empty state.
- Error state.
- Loading state.
- Demo state.

Use a dark aerospace-style interface, but prioritize readability over decoration.

Recommend exact chart types:

- Time-series line charts.
- Gauge chart.
- Heatmap.
- Radar chart only if useful.
- Engine schematic.
- Fault timeline.
- Mission map only if it adds value.
- RUL trend.
- Health-index timeline.
- Sensor correlation matrix.

Do not recommend visually impressive components that do not improve operational decisions.

PART 13: DESIGN THE BACKEND

Define:

1. API endpoints.
2. WebSocket message formats.
3. Database tables.
4. Background workers.
5. Authentication assumptions.
6. Error handling.
7. Logging.
8. Configuration management.
9. Data validation.
10. Model versioning.
11. Report generation.

Provide example JSON schemas for:

- Telemetry packet.
- Twin state.
- Anomaly event.
- Fault prediction.
- RUL prediction.
- Maintenance recommendation.
- Mission summary.
- Replay request.

Include exact endpoint names such as:

- POST /api/missions/start
- POST /api/missions/stop
- GET /api/engine/{engine_id}/state
- GET /api/engine/{engine_id}/telemetry
- GET /api/engine/{engine_id}/health
- GET /api/engine/{engine_id}/faults
- GET /api/engine/{engine_id}/rul
- POST /api/simulation/start
- POST /api/faults/inject
- POST /api/replay/start
- GET /api/reports/{mission_id}
- WS /ws/telemetry/{engine_id}

Improve these endpoints if needed.

PART 14: DESIGN THE DATABASE

Create a minimal relational schema.

Include tables for:

- engines.
- missions.
- telemetry.
- twin_states.
- anomalies.
- fault_predictions.
- rul_predictions.
- maintenance_advisories.
- mission_reports.
- model_versions.
- fault_injections.

Specify:

- Columns.
- Data types.
- Primary keys.
- Foreign keys.
- Indexes.
- Which tables are optional for the MVP.

Also explain when SQLite is sufficient and when PostgreSQL or TimescaleDB is justified.

PART 15: DEFINE API AND WEBSOCKET CONTRACTS

Provide concrete JSON examples.

Telemetry example should contain:

- engine_id.
- mission_id.
- timestamp.
- rpm.
- cht.
- egt.
- oil_pressure.
- oil_temperature.
- fuel_flow.
- vibration_rms.
- battery_voltage.
- alternator_current.
- injection_timing.
- throttle.
- altitude.
- ambient_temperature.
- mission_phase.

Twin-state response should contain:

- expected sensor values.
- observed values.
- residuals.
- health index.
- anomaly score.
- fault probabilities.
- degradation level.
- RUL.
- confidence.
- alerts.
- explanations.

PART 16: DEFINE THE IMPLEMENTATION PLAN

Assume we need to work quickly.

Create:

1. 24-hour emergency plan.
2. 48-hour plan.
3. 72-hour plan.
4. One-week ideal plan.

For each period, list:

- Goals.
- Deliverables.
- Team members required.
- Dependencies.
- Definition of done.
- What to skip.

Divide work among:

- Project lead/system architect.
- Frontend developer.
- Backend developer.
- ML engineer.
- Data/simulation engineer.
- Documentation and presentation lead.

If the team has fewer people, show how to merge responsibilities.

PART 17: CREATE THE FILE AND FOLDER STRUCTURE

Provide a practical monorepo structure, for example:

project-root/
  backend/
  frontend/
  ml/
  simulator/
  data/
  reports/
  docs/
  docker/
  tests/

Define important files such as:

- simulator/engine_model.py
- simulator/fault_injection.py
- simulator/mission_profiles.py
- backend/main.py
- backend/api/routes.py
- backend/services/digital_twin.py
- backend/services/health_index.py
- backend/services/predictor.py
- ml/train_anomaly.py
- ml/train_fault_classifier.py
- ml/train_rul.py
- frontend/src/pages/Dashboard.jsx
- frontend/src/components/HealthGauge.jsx
- frontend/src/components/TelemetryChart.jsx
- docs/architecture.md
- docs/model_card.md
- README.md

Improve the structure if necessary.

PART 18: GENERATE A STEP-BY-STEP BUILD ORDER

Give exact implementation order.

For every step, include:

- Task.
- Files to create.
- Input.
- Output.
- How to test.
- Expected completion time.
- Common error.
- Fallback.

The order must ensure that the frontend can display simulated data early, even before ML is complete.

PART 19: CREATE A TESTING STRATEGY

Define tests for:

1. Sensor data validation.
2. Fault injection.
3. Physics model.
4. Digital twin synchronization.
5. Health index.
6. Anomaly detection.
7. Fault classification.
8. RUL estimation.
9. WebSocket streaming.
10. API endpoints.
11. Dashboard rendering.
12. Mission replay.
13. Report generation.
14. System recovery when the ML service is unavailable.

Include unit tests, integration tests, and one end-to-end demo test.

PART 20: EVALUATION METRICS

Define suitable metrics for:

- Anomaly detection.
- Fault classification.
- RUL estimation.
- Sensor fault detection.
- Alert latency.
- False alarm rate.
- System throughput.
- Dashboard refresh latency.
- Replay accuracy.
- Recommendation usefulness.

Explain why accuracy alone is insufficient for safety-critical monitoring.

Include a sample evaluation table using realistic but clearly labeled prototype values. Do not invent real-world certification claims.

PART 21: SECURITY AND DEFENCE CONTEXT

Discuss practical cybersecurity and reliability features without overengineering.

Include:

- Secure telemetry.
- Authentication.
- Role-based access.
- Data integrity.
- Audit logs.
- Model versioning.
- Offline operation.
- Network disconnection behavior.
- Data encryption.
- Tamper detection.
- Fail-safe behavior.
- No automatic engine-control commands from the prototype.
- Separation between monitoring and control systems.

Clearly distinguish:

- Prototype security.
- Production defence-grade roadmap.

PART 22: LIMITATIONS AND ETHICAL CLAIMS

Write a truthful limitations section.

Mention:

- Synthetic data limitations.
- Difference between piston and turbofan datasets.
- Lack of real engine calibration.
- Need for hardware-in-the-loop testing.
- Need for real maintenance logs.
- Need for domain expert validation.
- RUL uncertainty.
- Sensor placement and calibration.
- Generalization limitations.
- No certification or flight-safety approval.

Explain how to present the prototype confidently without making unsupported claims.

PART 23: INNOVATION FEATURES

Rank innovation features by effort and judging impact.

Consider:

- Hybrid physics plus ML residual modeling.
- Explainable fault diagnosis.
- Adaptive health index.
- Mission-risk prediction.
- What-if mission simulation.
- Edge inference.
- Federated learning.
- Digital thread from telemetry to maintenance report.
- Sensor confidence scoring.
- Counterfactual explanation.
- Fleet-level comparison.
- Maintenance cost or mission-criticality optimization.

Choose the top three innovations that are realistic to implement quickly.

PART 24: PITCH AND STORYLINE

Create:

1. One-sentence value proposition.
2. 30-second elevator pitch.
3. 2-minute pitch.
4. 5-minute technical demo narration.
5. Problem slide.
6. Solution slide.
7. Architecture slide.
8. AI/ML slide.
9. Digital twin slide.
10. Demo slide.
11. Results slide.
12. Innovation slide.
13. Deployment roadmap slide.
14. Limitations slide.
15. Final impact slide.

Use language suitable for DRDO, iDEX, defence technology, aerospace reliability, and Smart India Hackathon judges.

Avoid exaggerated claims such as:

- 100% accurate.
- Fully autonomous aircraft safety.
- Production-ready defence system.
- Certified predictive maintenance.
- Guaranteed failure prevention.

Use credible phrases such as:

- Software demonstrator.
- Physics-informed prototype.
- Early-warning capability.
- Explainable decision support.
- Hardware-in-the-loop ready.
- Designed for future integration.
- Demonstrated on synthetic telemetry.

PART 25: ANTICIPATE JUDGE QUESTIONS

List at least 30 difficult questions judges may ask, with strong answers.

Include questions about:

- Real versus synthetic data.
- Why this is a digital twin.
- Why not only use thresholds.
- Why the chosen ML models.
- How RUL is calculated.
- How faults are labelled.
- How the system handles new faults.
- How sensor drift is detected.
- What happens if data is missing.
- How the physics model works.
- How the prototype would connect to CAN bus.
- How it runs at the edge.
- How it scales to a fleet.
- How it handles cybersecurity.
- How it avoids false alarms.
- What happens if the model is wrong.
- Why a piston engine model is appropriate.
- Whether NASA turbofan data can be used.
- How real DRDO data would be integrated.
- What is novel.
- What happens after the hackathon.
- What is the deployment cost.
- How the system supports maintenance personnel.
- How mission reliability is measured.

PART 26: FINAL RECOMMENDATION

End with:

1. The final MVP scope.
2. Features to implement immediately.
3. Features to fake or simplify transparently.
4. Features to exclude.
5. Final technology stack.
6. Final architecture.
7. Final demo flow.
8. Final team allocation.
9. Top five risks.
10. Top five actions to complete today.

Be decisive. If there are multiple valid choices, select one and explain why.

Do not give generic advice. Give concrete schemas, formulas, interfaces, folder structures, algorithms, demo steps, and implementation priorities.