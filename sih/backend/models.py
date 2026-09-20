"""
AeroTwin Backend — Pydantic Schemas
====================================

Single source of truth for every REST request and response body.
Typed, documented, serialisable — the frontend imports these shapes
via the OpenAPI spec at /docs.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════════
#  Enums
# ══════════════════════════════════════════════════════════════════════════════


class MissionPhase(str, Enum):
    STARTUP = "STARTUP"
    TAKEOFF = "TAKEOFF"
    CLIMB = "CLIMB"
    CRUISE = "CRUISE"
    ENDURANCE = "ENDURANCE"
    DESCENT = "DESCENT"
    LANDING = "LANDING"


class FaultType(str, Enum):
    HEALTHY = "HEALTHY"
    INJECTOR_DEGRADATION = "INJECTOR_DEGRADATION"
    MISFIRE = "MISFIRE"
    LUBRICATION_FAILURE = "LUBRICATION_FAILURE"
    OVERHEATING = "OVERHEATING"
    SENSOR_DRIFT = "SENSOR_DRIFT"
    SENSOR_DROPOUT = "SENSOR_DROPOUT"
    ABNORMAL_VIBRATION = "ABNORMAL_VIBRATION"
    ALTERNATOR_DEGRADATION = "ALTERNATOR_DEGRADATION"


class HealthCategory(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class AlertLevel(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    ADVISORY = "ADVISORY"
    CRITICAL = "CRITICAL"


class Trend(str, Enum):
    STABLE = "stable"
    DECLINING = "declining"
    IMPROVING = "improving"


class MissionStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAULT_INJECTED = "FAULT_INJECTED"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# ══════════════════════════════════════════════════════════════════════════════
#  Telemetry Frame
# ══════════════════════════════════════════════════════════════════════════════


class TelemetryFrame(BaseModel):
    """One tick of engine telemetry — the fundamental data unit."""

    frame_id: int
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    engine_id: str = "TAPAS-BH-201-001"
    mission_id: Optional[str] = None

    # Operating conditions
    phase: str = "STARTUP"
    throttle: float = 0.0
    altitude_ft: float = 0.0
    ambient_temp_c: float = 15.0

    # Engine sensors
    rpm: float = 0.0
    fuel_flow_lph: float = 0.0
    cht: List[float] = Field(default_factory=lambda: [0.0] * 4)
    egt: List[float] = Field(default_factory=lambda: [0.0] * 4)
    oil_pressure_kpa: float = 0.0
    oil_temp_c: float = 15.0
    vibration_rms: float = 0.0
    battery_voltage: float = 12.5
    alternator_current: float = 0.0
    injection_timing: float = 24.0

    # Ground truth (for demo / training)
    injected_fault: Optional[str] = None
    fault_severity: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  Engine State (Digital Twin)
# ══════════════════════════════════════════════════════════════════════════════


class SensorResidual(BaseModel):
    """Observed vs expected for one sensor channel."""

    channel: str
    observed: float
    expected: float
    residual: float
    z_score: float
    unit: str = ""


class EngineState(BaseModel):
    """Full digital twin state — what the dashboard consumes."""

    engine_id: str
    mission_id: Optional[str] = None
    timestamp: str

    # Observed telemetry
    observed: TelemetryFrame

    # Physics-expected values
    expected: Dict[str, float] = Field(default_factory=dict)

    # Residuals
    residuals: List[SensorResidual] = Field(default_factory=list)

    # Health
    health_index: float = 100.0
    health_category: str = "NORMAL"
    health_trend: str = "stable"
    health_delta_5min: float = 0.0
    health_confidence: str = "HIGH"
    health_explanation: List[str] = Field(default_factory=list)
    health_contributors: List[Dict[str, Any]] = Field(default_factory=list)

    # Anomaly
    anomaly_score: float = 0.0
    is_anomaly: bool = False
    anomaly_contributors: List[str] = Field(default_factory=list)

    # Fault
    fault_class: str = "HEALTHY"
    fault_confidence: float = 0.0
    fault_severity: float = 0.0
    fault_action: str = ""

    # RUL
    rul_minutes: Optional[float] = None
    rul_lo: Optional[float] = None
    rul_hi: Optional[float] = None
    rul_confidence: str = "HIGH"
    rul_trend: str = "stable"
    rtb_alert: str = "NONE"

    # Sensor health
    sensor_status: Dict[str, bool] = Field(default_factory=dict)
    isolated_sensors: List[str] = Field(default_factory=list)

    # Alerts
    alerts: List[Dict[str, Any]] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
#  Mission
# ══════════════════════════════════════════════════════════════════════════════


class MissionCreate(BaseModel):
    """Request to start a new mission."""

    engine_id: str = "TAPAS-BH-201-001"
    duration_s: int = 600
    ambient_offset_c: float = 0.0
    name: Optional[str] = None


class MissionInfo(BaseModel):
    """Mission metadata."""

    mission_id: str
    engine_id: str
    name: Optional[str] = None
    status: str
    started_at: str
    ended_at: Optional[str] = None
    duration_s: int
    frame_count: int = 0
    max_anomaly_score: float = 0.0
    min_health_index: float = 100.0
    faults_observed: List[str] = Field(default_factory=list)


class MissionSummary(BaseModel):
    """Post-mission summary report."""

    mission: MissionInfo
    health_stats: Dict[str, Any] = Field(default_factory=dict)
    anomaly_stats: Dict[str, Any] = Field(default_factory=dict)
    fault_stats: Dict[str, Any] = Field(default_factory=dict)
    rul_stats: Dict[str, Any] = Field(default_factory=dict)
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
#  Fault Injection
# ════════════════════════════════════════════════════════════════════════════


class FaultInjectionRequest(BaseModel):
    """Request to inject a fault into the running simulation."""

    fault_type: FaultType
    severity: float = Field(0.7, ge=0.0, le=1.0)
    target_sensor: Optional[str] = None  # for SENSOR_DRIFT / SENSOR_DROPOUT


class FaultInjectionResponse(BaseModel):
    """Confirmation of fault injection."""

    fault_type: str
    severity: float
    injected_at: str
    mission_id: str


# ══════════════════════════════════════════════════════════════════════════════
#  Replay
# ══════════════════════════════════════════════════════════════════════════════


class ReplayRequest(BaseModel):
    """Request to replay a past mission."""

    mission_id: str
    speed: float = Field(1.0, ge=0.1, le=10.0)
    start_s: Optional[float] = None
    end_s: Optional[float] = None


class ReplayFrame(BaseModel):
    """One frame in a replay sequence."""

    frame_id: int
    sim_time_s: float
    timestamp: str
    data: TelemetryFrame
    health: Optional[Dict[str, Any]] = None


# ══════════════════════════════════════════════════════════════════════════════
#  Report
# ══════════════════════════════════════════════════════════════════════════════


class MissionReport(BaseModel):
    """Exportable mission report."""

    mission: MissionInfo
    executive_summary: str
    health_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    anomaly_events: List[Dict[str, Any]] = Field(default_factory=list)
    fault_predictions: List[Dict[str, Any]] = Field(default_factory=list)
    rul_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    maintenance_advisories: List[Dict[str, Any]] = Field(default_factory=list)
    sensor_summary: Dict[str, Any] = Field(default_factory=dict)
    environmental_summary: Dict[str, Any] = Field(default_factory=dict)
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


# ══════════════════════════════════════════════════════════════════════════════
#  WebSocket Messages
# ══════════════════════════════════════════════════════════════════════════════


class WSMessage(BaseModel):
    """Outbound WebSocket message envelope."""

    type: str
    payload: Any
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class WSCommand(BaseModel):
    """Inbound WebSocket command from the frontend."""

    action: str
    fault: Optional[str] = None
    severity: Optional[float] = None
    sensor: Optional[str] = None
    throttle: Optional[float] = None
    altitude_ft: Optional[float] = None
    speed: Optional[float] = None


# ══════════════════════════════════════════════════════════════════════════════
#  Generic
# ══════════════════════════════════════════════════════════════════════════════


class HealthCheck(BaseModel):
    """GET /health response."""

    status: str = "ok"
    version: str
    uptime_s: float
    components: Dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    error: str
    detail: Optional[str] = None
    status_code: int = 500
