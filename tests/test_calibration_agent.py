import math
import pytest
from pydantic import ValidationError
from simulator.physical_system import PhysicalSystem
from smart_cooling_twin.agent import TwinSupervisorAgent
from smart_cooling_twin.calibration import Calibrator
from smart_cooling_twin.models import (
    AgentAction,
    FanCommand,
    ThermalParameters,
    ModelHealth,
    Telemetry,
)
from smart_cooling_twin.repository import Repository
from smart_cooling_twin.twin import DigitalTwin


def history(parameters=ThermalParameters(k_heat=0.2, k_fan=0.15)):
    samples = []
    t = 30.0
    for i in range(160):
        ambient = 24 + 2 * math.sin(i / 11)
        fan = (i % 7) * 15
        if samples:
            a = samples[-1]
            t += (
                parameters.k_heat
                + parameters.k_ambient * (a.ambient_temperature - t)
                - parameters.k_fan * fan / 100
            )
        samples.append(
            Telemetry(
                device_id="cooling-01",
                timestamp=i,
                temperature=t,
                ambient_temperature=ambient,
                humidity=50,
                fan_speed=fan,
            )
        )
    return samples


def test_calibration_holdout_and_bounds():
    result = Calibrator().fit(history(), ThermalParameters(), 200)
    assert result.accepted
    assert result.candidate.k_heat == pytest.approx(0.2)
    assert result.candidate.k_fan == pytest.approx(0.15)
    assert result.candidate.k_ambient == pytest.approx(0.012)
    assert result.candidate_mae < 1e-10
    assert not Calibrator().fit(history(), result.candidate, 201).accepted
    with pytest.raises(ValidationError):
        ThermalParameters(k_fan=-0.2)


def test_calibration_needs_excitation_and_data():
    samples = history()
    assert not Calibrator().fit(samples[:10], ThermalParameters(), 200).accepted
    for sample in samples:
        sample.fan_speed = 50
    result = Calibrator().fit(samples, ThermalParameters(), 200)
    assert not result.accepted
    assert "excitation" in result.reason


def test_policy_restricts_actions():
    twin = DigitalTwin(Repository(":memory:"))
    assert not twin.safety.authorize(AgentAction(kind="APPLY"), False)
    with pytest.raises(ValidationError):
        AgentAction(kind="SHELL")
    result = Calibrator().fit(history(), ThermalParameters(), 200)
    assert not twin.agent.tools.apply_calibration(result)


def test_autonomous_degradation_calibration_and_verification():
    twin = DigitalTwin(Repository(":memory:"))
    twin.state.mqtt_connected = True
    sim = PhysicalSystem()
    sim.settings.noise = 0
    sim.temperature = 30
    events = []
    maes = []
    for i in range(900):
        now = 1000 + i * 2
        sim.change_ambient_temperature(24 + 2 * math.sin(i / 17))
        if i == 150:
            sim.change_fan_effectiveness(0.10)
        sample = sim.step(2, now)
        command = twin.receive(sample, now)
        sim.apply_command(command, now)
        maes.append(twin.state.metrics.rolling_mae or 0)
    events = twin.repository.recent("agent_events", 1000)
    names = [e["decision"] for e in events]
    assert max(maes[150:]) > 0.06
    assert "CALIBRATION_INITIATED" in names
    assert "CANDIDATE_ACCEPTED" in names
    assert "IMPROVEMENT_VERIFIED" in names
    assert twin.model.parameters.k_fan == pytest.approx(0.1, abs=0.03)
    assert sum(maes[-30:]) / 30 < 0.04
    # Cooldown survives a supervisor restart.
    agent = TwinSupervisorAgent(twin.agent.tools)
    assert agent.last_calibration == twin.agent.last_calibration


def test_alert_deduplication_and_fault_assessment():
    repo = Repository(":memory:")
    twin = DigitalTwin(repo)
    for i in range(5):
        twin.tick(100 + i * 10)
    codes = [r["code"] for r in repo.recent("alerts")]
    assert codes.count("DEVICE_HEALTH") == 1
    assert codes.count("TELEMETRY_TIMEOUT") == 1
    assert twin.state.model_health == ModelHealth.FAULT


def test_command_freshness_and_device_watchdog():
    sim = PhysicalSystem()
    assert not sim.apply_command(
        FanCommand(device_id="cooling-01", timestamp=0, expires_at=1, fan_speed=0), 2
    )
    good = FanCommand(device_id="cooling-01", timestamp=2, expires_at=7, fan_speed=0)
    assert sim.apply_command(good, 2)
    assert not sim.apply_command(good, 2)
    assert sim.step(1, 8).fan_speed == 100
    sim.simulate_sensor_failure()
    assert not sim.step(1, 9).sensor_ok


def test_holdout_can_reject_successful_fit():
    samples = history()
    # A new regime begins only in validation: a good training fit must not auto-apply.
    for i in range(113, len(samples)):
        a, b = samples[i - 1], samples[i]
        b.temperature = (
            a.temperature
            + 0.12
            + 0.012 * (a.ambient_temperature - a.temperature)
            - 0.25 * b.fan_speed / 100
        )
    result = Calibrator().fit(samples, ThermalParameters(), 200)
    assert result.candidate is not None
    assert not result.accepted


def test_failed_fresh_verification_rolls_back_and_persists(tmp_path):
    repo = Repository(str(tmp_path / "memory.sqlite"))
    twin = DigitalTwin(repo)
    twin.state.mqtt_connected = twin.state.device_online = True
    twin.state.state = "NORMAL"
    old = ThermalParameters()
    candidate = Calibrator().fit(history(), old, 200)
    assert twin.agent.tools.apply_calibration(candidate)
    twin.agent.pending = {
        "timestamp": 200,
        "previous": old.model_dump(),
        "candidate": candidate.candidate.model_dump(),
    }
    twin.agent.last_calibration = 200
    twin.agent._save()
    twin.agent = TwinSupervisorAgent(twin.agent.tools)
    samples = history(old)
    for t in samples:
        t.timestamp += 201
    twin.history.extend(samples)
    twin.agent.tick(400)
    assert twin.model.parameters == old
    assert twin.agent.pending is None
    assert repo.get("parameters") == old.model_dump()
    assert repo.recent("agent_events")[-1]["decision"] == "CALIBRATION_ROLLED_BACK"
    assert repo.recent("agent_events")[-1]["verification_status"] == "FAILED"
    repo.close()


def test_verification_timeout_and_forecasts():
    repo = Repository(":memory:")
    twin = DigitalTwin(repo)
    old = twin.model.parameters.model_dump()
    repo.set("rollback", old)
    twin.agent.pending = {"timestamp": 10, "previous": old, "candidate": old}
    twin.agent.tick(200)
    assert twin.agent.pending is None
    assert repo.recent("agent_events")[-1]["decision"] == "VERIFICATION_FAILED"
    twin.state.telemetry = history()[0]
    assert twin.agent.tools.run_forecast(100) < twin.agent.tools.run_forecast(0)


def test_persistent_actuator_mismatch_is_alerted():
    twin = DigitalTwin(Repository(":memory:"))
    twin.state.mqtt_connected = twin.state.device_online = True
    twin.state.state = "NORMAL"
    twin.state.telemetry = history()[0]
    twin.state.fan_command = 100
    for now in (1000, 1010, 1020, 1030):
        twin.agent.tick(now)
    alerts = twin.repository.recent("alerts")
    assert sum(a["code"] == "FAN_COMMAND_MISMATCH" for a in alerts) == 1
    twin.state.telemetry.fan_speed = 100
    twin.agent.tick(1040)
    assert "FAN_COMMAND_MISMATCH" not in twin.repository.get("active_alerts")
