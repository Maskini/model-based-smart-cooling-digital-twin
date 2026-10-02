"""Orchestration of telemetry, prediction, deterministic control and supervision."""

from collections import deque
from .agent import SupervisorTools, TwinSupervisorAgent
from .control import Controller, SafetyLayer, StateMachine
from .models import (
    Alert,
    FanCommand,
    PredictionResult,
    SystemState,
    StateTransition,
    Telemetry,
    ThermalParameters,
    TwinState,
)
from .repository import Repository
from .thermal import ThermalModel
from .validation import ModelValidator


class DigitalTwin:
    def __init__(
        self,
        repository: Repository,
        device_id: str = "cooling-01",
        timeout: float = 10,
        agent_enabled: bool = True,
    ):
        self.repository, self.device_id, self.timeout = repository, device_id, timeout
        saved = repository.get("parameters")
        self.model = ThermalModel(ThermalParameters.model_validate(saved) if saved else None)
        self.safety = SafetyLayer()
        self.controller = Controller(self.safety)
        self.machine = StateMachine(self.safety.limits)
        self.validator = ModelValidator()
        self.state = TwinState()
        self.history: deque[Telemetry] = deque(maxlen=600)
        self.pending: deque[PredictionResult] = deque(maxlen=60)
        self.last_received: float | None = None
        self.agent = TwinSupervisorAgent(SupervisorTools(self), enabled=agent_enabled)

    def set_state(self, state: SystemState, now: float, reason: str) -> None:
        previous = self.state.state
        self.state.state = self.machine.state = state
        if state != previous:
            self.repository.append(
                "transitions",
                StateTransition(timestamp=now, previous=previous, current=state, reason=reason),
            )

    def clear_predictions(self):
        self.pending.clear()
        self.state.prediction = None
        self.validator = ModelValidator()
        self.state.metrics = self.state.metrics.__class__()

    def fault(self, now: float, code: str, message: str) -> FanCommand:
        self.set_state(SystemState.FAULT, now, message)
        self.state.device_online = False
        self.repository.create_alert(Alert(timestamp=now, code=code, message=message))
        self.clear_predictions()
        return self.command(now)

    def receive(self, telemetry: Telemetry, now: float) -> FanCommand | None:
        if telemetry.device_id != self.device_id:
            return None
        if abs(telemetry.timestamp - now) > self.timeout:
            return self.fault(
                now, "STALE_TELEMETRY", "Telemetry timestamp outside freshness window"
            )
        previous = self.state.telemetry
        if previous and telemetry.timestamp <= previous.timestamp:
            return None  # QoS duplicate / out-of-order sample cannot refresh watchdog.
        self.last_received = now
        self.state.telemetry = telemetry
        self.state.device_online = telemetry.sensor_ok
        if not telemetry.sensor_ok:
            return self.fault(now, "SENSOR_FAULT", "Device reports sensor failure")
        self.repository.resolve_alert("SENSOR_FAULT")
        self.repository.resolve_alert("TELEMETRY_TIMEOUT")
        self.repository.resolve_alert("STALE_TELEMETRY")
        self.repository.resolve_alert("INVALID_TELEMETRY")
        dt = telemetry.timestamp - previous.timestamp if previous else 0
        trend = (telemetry.temperature - previous.temperature) / dt if dt > 0 else 0
        if previous and abs(trend) > 2:
            return self.fault(now, "TEMPERATURE_JUMP", "Temperature changed by over 2 °C/s")
        self.repository.resolve_alert("TEMPERATURE_JUMP")
        self.repository.append("telemetry", telemetry)
        self.history.append(telemetry)
        self.set_state(
            self.machine.update(
                telemetry.temperature,
                trend,
                self.controller.settings.setpoint,
                healthy=self.state.connection_healthy,
                powered=telemetry.powered,
            ),
            now,
            "Validated temperature, trend and safety thresholds",
        )
        while self.pending and self.pending[0].target_timestamp <= telemetry.timestamp + 0.25:
            prediction = self.pending.popleft()
            if abs(prediction.target_timestamp - telemetry.timestamp) <= 0.5:
                metrics = self.validator.update(
                    telemetry.temperature, prediction.predicted_temperature
                )
                self.state.metrics = metrics
                prediction.measured_temperature = telemetry.temperature
                prediction.prediction_error = metrics.prediction_error
                prediction.rolling_mae = metrics.rolling_mae
                self.repository.append("predictions", prediction)
        command = self.command(now)
        prediction = PredictionResult(
            timestamp=telemetry.timestamp,
            target_timestamp=telemetry.timestamp + 2,
            predicted_temperature=self.model.predict(
                telemetry.temperature, telemetry.ambient_temperature, command.fan_speed, 2
            ),
        )
        self.pending.append(prediction)
        self.state.prediction = prediction
        self.agent.tick(now)
        self.persist(now)
        return command

    def command(self, now: float) -> FanCommand:
        t = self.state.telemetry
        self.state.mode = self.controller.settings.mode
        self.state.fan_command = self.controller.command(
            self.state.state, t.temperature if t else None
        )
        return FanCommand(
            device_id=self.device_id,
            timestamp=now,
            expires_at=now + 5,
            fan_speed=self.state.fan_command,
        )

    def tick(self, now: float) -> FanCommand:
        if (
            not self.state.connection_healthy
            or self.last_received is None
            or now - self.last_received > self.timeout
        ):
            self.fault(now, "TELEMETRY_TIMEOUT", "No fresh telemetry or broker connection")
        self.agent.tick(now)
        self.persist(now)
        return self.command(now)

    def persist(self, now: float):
        self.repository.set(
            "snapshot",
            {
                "timestamp": now,
                "state": self.state.model_dump(mode="json"),
                "parameters": self.model.parameters.model_dump(),
                "agent_enabled": self.agent.enabled,
            },
        )
