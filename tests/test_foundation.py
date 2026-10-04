import math
import pytest
from pydantic import ValidationError
from smart_cooling_twin.models import Telemetry, FanCommand, SystemState as S, ControlSettings
from smart_cooling_twin.control import Controller, SafetyLayer, StateMachine
from smart_cooling_twin.thermal import ThermalModel
from smart_cooling_twin.validation import ModelValidator
from smart_cooling_twin.repository import Repository


def telemetry(**kwargs):
    return Telemetry(
        **(
            dict(
                device_id="cooling-01",
                timestamp=1,
                temperature=30,
                ambient_temperature=24,
                humidity=50,
                fan_speed=0,
            )
            | kwargs
        )
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", math.nan),
        ("temperature", 126),
        ("temperature", -41),
        ("humidity", -1),
        ("humidity", 101),
        ("fan_speed", 101),
        ("timestamp", math.inf),
        ("ambient_temperature", math.nan),
    ],
)
def test_invalid_telemetry(field, value):
    with pytest.raises(ValidationError):
        telemetry(**{field: value})


def test_missing_fields_and_commands():
    with pytest.raises(ValidationError):
        Telemetry.model_validate_json("{}")
    with pytest.raises(ValidationError):
        FanCommand(device_id="x", timestamp=1, expires_at=3, fan_speed=101)


def test_thermal_equation():
    model = ThermalModel()
    assert model.predict(30, 24, 50, 1) == pytest.approx(30 + 0.12 - 0.012 * 6 - 0.25 * 0.5)
    assert model.predict(30, 24, 100, 60) < model.predict(30, 24, 0, 60)
    with pytest.raises(ValueError):
        model.predict(30, 24, 0, -1)


def test_all_state_transitions_and_hysteresis():
    machine = StateMachine()
    assert machine.update(25, 0, powered=False) == S.OFF
    assert machine.update(25, 0) == S.NORMAL
    assert machine.update(26, 0.04) == S.HEATING
    assert machine.update(26, 0.01) == S.HEATING
    assert machine.update(26, 0) == S.NORMAL
    assert machine.update(30, 0.1) == S.COOLING
    assert machine.update(29.5, -0.1) == S.COOLING
    assert machine.update(28.9, -0.1) == S.NORMAL
    assert machine.update(40, 0.1) == S.OVERHEATING
    assert machine.update(39.5, -0.1) == S.OVERHEATING
    assert machine.update(38.9, -0.1) == S.COOLING
    assert machine.update(25, 0, healthy=False) == S.FAULT
    assert machine.update(25, 0) == S.NORMAL


@pytest.mark.parametrize("prior", list(S))
def test_fault_and_overheat_from_every_state(prior):
    m = StateMachine()
    m.state = prior
    assert m.update(25, 0, healthy=False) == S.FAULT
    m.state = prior
    assert m.update(42, 0) == S.OVERHEATING


def test_control_safety_manual():
    c = Controller(SafetyLayer())
    assert c.command(S.NORMAL, 25) == 0
    assert c.command(S.COOLING, 32) == 60
    c.settings = ControlSettings(mode="MANUAL", manual_fan=10)
    assert c.command(S.NORMAL, 25) == 10
    assert c.command(S.OVERHEATING, 42) == 100
    assert c.command(S.FAULT, 25) == 100
    assert c.safety.constrain(-8, S.NORMAL, 25) == 0
    assert c.safety.constrain(108, S.NORMAL, 25) == 100
    assert c.safety.constrain(math.nan, S.NORMAL, 25) == 100


def test_rolling_mae_and_persistence():
    validator = ModelValidator(2)
    validator.update(31, 30)
    validator.update(28, 30)
    metrics = validator.update(33, 30)
    assert metrics.rolling_mae == 2.5
    assert metrics.residual_bias == 0.5
    repo = Repository(":memory:")
    repo.append("telemetry", telemetry())
    assert repo.recent("telemetry")[0]["temperature"] == 30
    repo.close()
