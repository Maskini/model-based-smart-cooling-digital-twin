"""Bounded autonomous diagnostics; no actuator, shell, or code execution tool exists."""

from typing import TYPE_CHECKING
from .calibration import Calibrator, calibration_rows
from .models import (
    AgentAction,
    AgentDecision,
    AgentObservation,
    Alert,
    CalibrationResult,
    ModelHealth,
    SystemState,
    ThermalParameters,
)
import numpy as np

if TYPE_CHECKING:
    from .twin import DigitalTwin


class SupervisorTools:
    def __init__(self, twin: "DigitalTwin"):
        self.twin = twin
        self.calibrator = Calibrator()

    def get_current_state(self):
        return self.twin.state.model_copy(deep=True)

    def get_recent_telemetry(self):
        return list(self.twin.history)

    def get_prediction_metrics(self):
        return self.twin.state.metrics.model_copy()

    def run_forecast(self, fan: float | None = None, seconds: float = 60) -> float | None:
        t = self.twin.state.telemetry
        if t is None:
            return None
        return self.twin.model.predict(
            t.temperature, t.ambient_temperature, t.fan_speed if fan is None else fan, seconds
        )

    def evaluate_model_health(self) -> ModelHealth:
        state = self.twin.state
        if (
            not state.device_online
            or not state.connection_healthy
            or state.state == SystemState.FAULT
        ):
            return ModelHealth.FAULT
        metrics = state.metrics
        if metrics.samples < 10:
            return ModelHealth.WATCH
        if metrics.rolling_mae > 0.06:
            return ModelHealth.DEGRADED
        return ModelHealth.WATCH if metrics.rolling_mae > 0.035 else ModelHealth.HEALTHY

    def request_calibration(self, now: float) -> CalibrationResult:
        return self.calibrator.fit(list(self.twin.history)[-121:], self.twin.model.parameters, now)

    def evaluate_calibration_candidate(self, result: CalibrationResult) -> bool:
        return (
            result.accepted
            and result.candidate is not None
            and result.previous_mae is not None
            and result.previous_mae > 0.005
            and result.candidate_mae is not None
            and result.candidate_mae <= result.previous_mae * (1 - self.calibrator.improvement)
        )

    def _allowed(self, action: AgentAction) -> bool:
        s = self.twin.state
        return self.twin.safety.authorize(
            action,
            s.device_online
            and s.connection_healthy
            and s.state not in (SystemState.FAULT, SystemState.OVERHEATING),
        )

    def apply_calibration(self, result: CalibrationResult) -> bool:
        if not self._allowed(AgentAction(kind="APPLY")) or not self.evaluate_calibration_candidate(
            result
        ):
            return False
        self.twin.repository.set("rollback", result.previous.model_dump())
        self.twin.model.parameters = result.candidate.model_copy()
        self.twin.repository.set("parameters", result.candidate.model_dump())
        self.twin.clear_predictions()
        return True

    def rollback_calibration(self) -> bool:
        if not self._allowed(AgentAction(kind="ROLLBACK")):
            return False
        saved = self.twin.repository.get("rollback")
        if saved is None:
            return False
        self.twin.model.parameters = ThermalParameters.model_validate(saved)
        self.twin.repository.set("parameters", saved)
        self.twin.clear_predictions()
        return True

    def create_alert(self, now: float, code: str, message: str) -> bool:
        if not self._allowed(AgentAction(kind="ALERT")):
            return False
        return self.twin.repository.create_alert(Alert(timestamp=now, code=code, message=message))

    def record_decision(self, decision: AgentDecision) -> None:
        self.twin.repository.append("agent_events", decision)


class TwinSupervisorAgent:
    def __init__(self, tools: SupervisorTools, enabled: bool = True, cooldown: float = 180):
        self.tools, self.enabled, self.cooldown = tools, enabled, cooldown
        saved = tools.twin.repository.get("agent_memory") or {}
        self.last_calibration = saved.get("last_calibration", -1e12)
        self.pending = saved.get("pending")
        self.degraded_windows = 0
        self.fan_mismatch_windows = 0
        self.last_tick = -1e12

    def _save(self):
        self.tools.twin.repository.set(
            "agent_memory", {"last_calibration": self.last_calibration, "pending": self.pending}
        )

    def observe(self, now: float) -> AgentObservation:
        history = self.tools.get_recent_telemetry()
        trend = 0
        if len(history) > 1:
            a, b = history[-2:]
            trend = (b.temperature - a.temperature) / max(0.001, b.timestamp - a.timestamp)
        return AgentObservation(
            timestamp=now,
            state=self.tools.get_current_state(),
            trend=trend,
            calibration_age=None if self.last_calibration < 0 else now - self.last_calibration,
            recent_actions=self.tools.twin.repository.recent("agent_events", 5),
            active_alerts=list((self.tools.twin.repository.get("active_alerts") or {}).values()),
        )

    def record(
        self,
        obs: AgentObservation,
        decision: str,
        reason: str,
        kind: str = "NONE",
        outcome: str = "recorded",
        status: str = "VERIFIED",
    ):
        # Avoid recursively embedding complete older observations into every new observation.
        obs.recent_actions = [
            {k: e[k] for k in ("timestamp", "decision", "verification_status")}
            for e in obs.recent_actions
        ]
        self.tools.record_decision(
            AgentDecision(
                timestamp=obs.timestamp,
                observation=obs,
                model_health=self.tools.twin.state.model_health,
                decision=decision,
                reason=reason,
                action=AgentAction(kind=kind),
                expected_outcome="Maintain safe operation and model accuracy",
                actual_outcome=outcome,
                verification_status=status,
            )
        )

    def tick(self, now: float) -> None:
        if not self.enabled or now - self.last_tick < 10:
            return
        self.last_tick = now
        obs = self.observe(now)
        health = self.tools.evaluate_model_health()
        self.tools.twin.state.model_health = health
        alerts = []
        if health == ModelHealth.FAULT:
            alerts.append(
                (
                    "DEVICE_HEALTH",
                    "Telemetry, sensor or connection health failed; safe fallback active",
                )
            )
        else:
            self.tools.twin.repository.resolve_alert("DEVICE_HEALTH")
        m = obs.state.metrics
        if m.samples >= 10 and abs(m.residual_bias) > 0.06:
            alerts.append(
                ("RESIDUAL_BIAS", "Persistent residual bias; thermal model may have drifted")
            )
        else:
            self.tools.twin.repository.resolve_alert("RESIDUAL_BIAS")
        t = obs.state.telemetry
        mismatch = t is not None and abs(t.fan_speed - obs.state.fan_command) > 25
        self.fan_mismatch_windows = self.fan_mismatch_windows + 1 if mismatch else 0
        if self.fan_mismatch_windows >= 3:
            alerts.append(
                (
                    "FAN_COMMAND_MISMATCH",
                    "Applied PWM differs from commanded fan by more than 25% across three assessments",
                )
            )
        else:
            self.tools.twin.repository.resolve_alert("FAN_COMMAND_MISMATCH")
        if t and t.fan_speed > 60 and obs.trend > 0.02 and m.residual_bias > 0.06:
            alerts.append(
                (
                    "FAN_RESPONSE",
                    "Cooling weaker than expected; inspect fan effectiveness or heat load",
                )
            )
        else:
            self.tools.twin.repository.resolve_alert("FAN_RESPONSE")
        for code, message in alerts:
            if self.tools.create_alert(now, code, message):
                self.record(obs, code, message, "ALERT")
        if self.pending:
            self._verify(obs)
            return
        self.degraded_windows = self.degraded_windows + 1 if health == ModelHealth.DEGRADED else 0
        if self.degraded_windows < 3 or now - self.last_calibration < self.cooldown:
            self.record(obs, "ASSESS", f"Model {health}; degraded windows={self.degraded_windows}")
            return
        if not self.tools._allowed(AgentAction(kind="CALIBRATE")):
            self.record(
                obs,
                "CALIBRATION_BLOCKED",
                "Device safety policy denied calibration",
                status="REJECTED",
            )
            return
        self.last_calibration = now
        current_forecast = self.tools.run_forecast()
        maximum_forecast = self.tools.run_forecast(100)
        self.record(
            obs,
            "FORECAST_COMPARISON",
            "Diagnostic forecasts at current and maximum fan",
            "FORECAST",
            f"60 s forecast: current={current_forecast}, maximum={maximum_forecast}",
        )
        self.tools.twin.state.model_health = ModelHealth.CALIBRATING
        self.record(
            obs, "CALIBRATION_INITIATED", "Sustained rolling MAE above 0.06 °C", "CALIBRATE"
        )
        result = self.tools.request_calibration(now)
        self.tools.twin.repository.append("calibrations", result)
        self.record(
            obs,
            "CANDIDATE_EVALUATED",
            result.reason,
            "CALIBRATE",
            outcome=f"holdout MAE: {result.previous_mae} → {result.candidate_mae}",
        )
        if self.tools.apply_calibration(result):
            self.pending = {
                "timestamp": now,
                "previous": result.previous.model_dump(),
                "candidate": result.candidate.model_dump(),
            }
            self.record(
                obs,
                "CANDIDATE_ACCEPTED",
                "Bounded candidate improves chronological holdout",
                "APPLY",
                "Awaiting 30 fresh intervals",
                "PENDING",
            )
        else:
            self.record(obs, "CANDIDATE_REJECTED", result.reason, "CALIBRATE", status="REJECTED")
        self._save()

    def _verify(self, obs: AgentObservation):
        now = obs.timestamp
        rows = [
            t for t in self.tools.get_recent_telemetry() if t.timestamp > self.pending["timestamp"]
        ]
        x, y, dt = calibration_rows(rows)
        if len(y) < 30:
            if now - self.pending["timestamp"] > 180:
                self.tools.rollback_calibration()
                self.record(
                    obs,
                    "VERIFICATION_FAILED",
                    "Insufficient fresh healthy data; rolled back",
                    "ROLLBACK",
                    "Previous parameters restored",
                    "FAILED",
                )
                self.pending = None
                self._save()
            return
        old, new = self.pending["previous"], self.pending["candidate"]
        keys = ("k_heat", "k_ambient", "k_fan")
        old_mae = float(np.mean(abs((x @ np.array([old[k] for k in keys]) - y) * dt)))
        new_mae = float(np.mean(abs((x @ np.array([new[k] for k in keys]) - y) * dt)))
        if new_mae <= old_mae * 0.95:
            self.record(
                obs,
                "IMPROVEMENT_VERIFIED",
                "Fresh data confirms improvement",
                "NONE",
                f"Fresh MAE {old_mae:.5f} → {new_mae:.5f}",
            )
        else:
            self.tools.rollback_calibration()
            self.record(
                obs,
                "CALIBRATION_ROLLED_BACK",
                "Improvement did not persist",
                "ROLLBACK",
                f"Fresh MAE {old_mae:.5f} → {new_mae:.5f}",
                "FAILED",
            )
        self.pending = None
        self._save()
