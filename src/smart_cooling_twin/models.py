"""Validated wire contracts and inspectable domain records. Times are Unix seconds."""

from enum import StrEnum
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field

Finite = Annotated[float, Field(allow_inf_nan=False)]
Temperature = Annotated[Finite, Field(ge=-40, le=125)]
Percent = Annotated[Finite, Field(ge=0, le=100)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SystemState(StrEnum):
    OFF = "OFF"
    NORMAL = "NORMAL"
    HEATING = "HEATING"
    COOLING = "COOLING"
    OVERHEATING = "OVERHEATING"
    FAULT = "FAULT"


class ModelHealth(StrEnum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    DEGRADED = "DEGRADED"
    CALIBRATING = "CALIBRATING"
    FAULT = "FAULT"


class Telemetry(Record):
    device_id: str = Field(min_length=1, max_length=64)
    timestamp: Finite = Field(ge=0)
    temperature: Temperature
    ambient_temperature: Temperature
    humidity: Percent
    fan_speed: Percent
    sensor_ok: bool = True
    powered: bool = True


class FanCommand(Record):
    device_id: str
    timestamp: Finite = Field(ge=0)
    expires_at: Finite = Field(ge=0)
    fan_speed: Percent


class DeviceStatus(Record):
    device_id: str
    online: bool
    sensor_ok: bool = True


class ThermalParameters(Record):
    k_heat: Finite = Field(default=0.12, ge=0, le=2)
    k_ambient: Finite = Field(default=0.012, ge=0.0001, le=0.2)
    k_fan: Finite = Field(default=0.25, ge=0.001, le=3)


class ValidationMetrics(Record):
    prediction_error: Finite | None = None
    absolute_error: Finite | None = None
    rolling_mae: Finite | None = None
    residual_bias: Finite = 0
    samples: int = 0


class PredictionResult(Record):
    timestamp: Finite
    target_timestamp: Finite
    predicted_temperature: Finite
    measured_temperature: Finite | None = None
    prediction_error: Finite | None = None
    rolling_mae: Finite | None = None


class TwinState(Record):
    telemetry: Telemetry | None = None
    state: SystemState = SystemState.OFF
    mode: Literal["AUTO", "MANUAL"] = "AUTO"
    fan_command: Percent = 100
    mqtt_connected: bool = False
    device_online: bool = False
    model_health: ModelHealth = ModelHealth.WATCH
    prediction: PredictionResult | None = None
    metrics: ValidationMetrics = Field(default_factory=ValidationMetrics)


class AgentObservation(Record):
    timestamp: Finite
    state: TwinState
    trend: Finite = 0
    calibration_age: Finite | None = None
    recent_actions: list[dict[str, Any]] = Field(default_factory=list)
    active_alerts: list[dict[str, Any]] = Field(default_factory=list)


class AgentAction(Record):
    kind: Literal["NONE", "CALIBRATE", "APPLY", "ROLLBACK", "ALERT", "FORECAST"]
    details: str = ""


class AgentDecision(Record):
    timestamp: Finite
    observation: AgentObservation
    model_health: ModelHealth
    decision: str
    reason: str
    action: AgentAction
    expected_outcome: str
    actual_outcome: str = "pending"
    verification_status: Literal["PENDING", "VERIFIED", "REJECTED", "FAILED"] = "PENDING"


class CalibrationResult(Record):
    timestamp: Finite
    previous: ThermalParameters
    candidate: ThermalParameters | None = None
    previous_mae: Finite | None = None
    candidate_mae: Finite | None = None
    accepted: bool = False
    reason: str


class Alert(Record):
    timestamp: Finite
    code: str
    message: str
    active: bool = True


class ControlSettings(Record):
    mode: Literal["AUTO", "MANUAL"] = "AUTO"
    manual_fan: Percent = 0
    setpoint: Finite = Field(default=30, ge=20, le=35)


class SimulatorSettings(Record):
    heat_load: Finite = Field(default=0.12, ge=0, le=2)
    ambient_temperature: Temperature = 24
    fan_effectiveness: Finite = Field(default=0.25, ge=0, le=3)
    noise: Finite = Field(default=0.02, ge=0, le=5)
    sensor_failure: bool = False
