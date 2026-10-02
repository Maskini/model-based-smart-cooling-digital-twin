"""Operational explanations based on observed evidence and actual controller decisions."""

from .models import SystemState
from .twin import DigitalTwin


def explain_state(twin: DigitalTwin) -> dict:
    state, control = twin.state, twin.controller.settings
    t = state.telemetry
    recommendations = []
    if not t:
        summary = "Waiting for the first sensor reading. The device uses its local safe fallback."
        recommendations.append("Start a simulation or connect the ESP32 to the configured backend.")
    elif state.state == SystemState.FAULT:
        summary = "Fresh, valid telemetry is unavailable. The controller requests 100% cooling as a safety fallback."
        recommendations.append("Check device power, connectivity, timestamps and sensor health.")
    elif state.state == SystemState.OVERHEATING:
        summary = (
            f"Temperature reached {t.temperature:.1f} °C. The 40 °C safety limit was crossed; "
            "maximum cooling overrides both manual demand and the normal target."
        )
        recommendations.append("Reduce the heat load and inspect the fan and airflow.")
    elif state.state == SystemState.OFF:
        summary = (
            "Simulation is stopped or the device reports power off. No normal cooling is requested."
        )
    elif control.mode == "MANUAL":
        summary = (
            f"Temperature is {t.temperature:.1f} °C. Manual demand is {control.manual_fan:.0f}%; "
            f"the safety-validated command is {state.fan_command:.0f}%."
        )
    elif state.state == SystemState.COOLING:
        summary = (
            f"Temperature is {t.temperature:.1f} °C, with a {control.setpoint:.1f} °C target. "
            f"Cooling is active at {state.fan_command:.0f}%. It switches off at or below "
            f"{control.setpoint - 1:.1f} °C to avoid rapid switching."
        )
    elif state.state == SystemState.HEATING:
        summary = (
            f"Temperature is rising at {t.temperature:.1f} °C. Cooling starts at "
            f"the {control.setpoint:.1f} °C target; the safety limit remains 40 °C."
        )
    else:
        summary = f"Temperature is {t.temperature:.1f} °C and cooling is off. The system is within its normal range."
    alerts = list((twin.repository.get("active_alerts") or {}).values())
    if state.metrics.rolling_mae is not None and state.metrics.rolling_mae > 0.06:
        recommendations.append(
            "The thermal model differs from measurements; the supervisor evaluates calibration when enough data is available."
        )
    if not recommendations:
        recommendations.append(
            "Continue monitoring temperature, device health and prediction error."
        )
    return {
        "summary": summary,
        "recommendations": recommendations,
        "alerts": alerts,
        "engine": "Deterministic supervisor",
        "llm": None,
    }
