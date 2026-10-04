import pytest
from smart_cooling_twin.models import Telemetry, SystemState, ControlSettings
from smart_cooling_twin.repository import Repository
from smart_cooling_twin.twin import DigitalTwin
from simulator.physical_system import PhysicalSystem


def sample(now=100, **fields):
    return Telemetry(
        **(
            dict(
                device_id="cooling-01",
                timestamp=now,
                temperature=30,
                ambient_temperature=24,
                humidity=50,
                fan_speed=0,
            )
            | fields
        )
    )


def test_prediction_association_and_timeout():
    twin = DigitalTwin(Repository(":memory:"), agent_enabled=False)
    twin.state.mqtt_connected = True
    command = twin.receive(sample(), 100)
    predicted = twin.state.prediction.predicted_temperature
    twin.receive(sample(102, temperature=predicted + 0.03, fan_speed=command.fan_speed), 102)
    assert twin.state.metrics.prediction_error == pytest.approx(0.03)
    assert twin.repository.recent("predictions")[0]["target_timestamp"] == 102
    assert twin.tick(113).fan_speed == 100
    assert twin.state.state == SystemState.FAULT
    twin.receive(sample(114), 114)
    assert twin.state.state == SystemState.COOLING


def test_stale_duplicates_wrong_device_and_missing_prediction():
    twin = DigitalTwin(Repository(":memory:"), agent_enabled=False)
    twin.state.mqtt_connected = True
    assert twin.receive(sample(device_id="another"), 100) is None
    twin.receive(sample(), 100)
    assert twin.receive(sample(), 101) is None
    assert twin.last_received == 100
    twin.receive(sample(105), 105)
    assert twin.state.metrics.samples == 0
    assert twin.receive(sample(106), 130).fan_speed == 100


def test_closed_loop_and_overheat_override():
    twin = DigitalTwin(Repository(":memory:"), agent_enabled=False)
    twin.state.mqtt_connected = True
    sim = PhysicalSystem()
    sim.settings.noise = 0
    commands, temperatures = [], []
    for i in range(400):
        now = 100 + i * 2
        command = twin.receive(sim.step(2, now), now)
        sim.apply_command(command, now)
        commands.append(command.fan_speed)
        temperatures.append(sim.temperature)
    assert max(commands[1:]) > 0
    assert max(temperatures) < 32
    assert temperatures[-1] > 29
    twin.controller.settings = ControlSettings(mode="MANUAL", manual_fan=0)
    # Start a fresh twin observation so jump diagnostics don't mask the state-machine test.
    twin.state.telemetry = None
    command = twin.receive(sample(1000, temperature=42), 1000)
    assert twin.state.state == SystemState.OVERHEATING
    assert command.fan_speed == 100


def test_jump_and_sensor_fault():
    twin = DigitalTwin(Repository(":memory:"))
    twin.state.mqtt_connected = True
    twin.receive(sample(), 100)
    assert twin.receive(sample(102, temperature=38), 102).fan_speed == 100
    assert twin.state.state == SystemState.FAULT
    assert twin.receive(sample(104, sensor_ok=False), 104).fan_speed == 100
