import math
from dataclasses import dataclass
from .models import AgentAction, ControlSettings, SystemState


@dataclass(frozen=True)
class SafetyLimits:
    overheat: float = 40
    hysteresis: float = 1
    fallback_fan: float = 100


class SafetyLayer:
    def __init__(self, limits: SafetyLimits | None = None):
        self.limits = limits or SafetyLimits()

    def constrain(self, fan: float, state: SystemState, temperature: float | None) -> float:
        if (
            state in (SystemState.FAULT, SystemState.OVERHEATING)
            or temperature is None
            or not math.isfinite(temperature)
            or temperature >= self.limits.overheat
            or not math.isfinite(fan)
        ):
            return self.limits.fallback_fan
        return min(100, max(0, fan))

    def authorize(self, action: AgentAction, healthy_device: bool) -> bool:
        return action.kind in {"NONE", "ALERT", "FORECAST", "ROLLBACK"} or healthy_device


class StateMachine:
    def __init__(self, limits: SafetyLimits | None = None):
        self.limits = limits or SafetyLimits()
        self.state = SystemState.OFF

    def update(
        self,
        temperature: float,
        trend: float,
        setpoint: float = 30,
        healthy: bool = True,
        powered: bool = True,
    ) -> SystemState:
        old, h = self.state, self.limits.hysteresis
        if not healthy or not math.isfinite(temperature):
            state = SystemState.FAULT
        elif temperature >= self.limits.overheat or (
            old == SystemState.OVERHEATING and temperature > self.limits.overheat - h
        ):
            state = SystemState.OVERHEATING
        elif not powered:
            state = SystemState.OFF
        elif temperature >= setpoint or (old == SystemState.COOLING and temperature > setpoint - h):
            state = SystemState.COOLING
        elif trend > 0.02 or (old == SystemState.HEATING and trend > 0.005):
            state = SystemState.HEATING
        else:
            state = SystemState.NORMAL
        self.state = state
        return state


class Controller:
    def __init__(self, safety: SafetyLayer):
        self.safety = safety
        self.settings = ControlSettings()

    def command(self, state: SystemState, temperature: float | None) -> float:
        cfg = self.settings
        if state == SystemState.OFF:
            desired = 0
        elif cfg.mode == "MANUAL":
            desired = cfg.manual_fan
        elif state == SystemState.COOLING and temperature is not None:
            desired = 20 + 20 * (temperature - cfg.setpoint)
        else:
            desired = 0
        return self.safety.constrain(desired, state, temperature)
