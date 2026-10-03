import pytest
from fastapi.testclient import TestClient
from smart_cooling_twin.api import create_app
from smart_cooling_twin.config import Settings
from smart_cooling_twin.runtime import TwinRuntime
from smart_cooling_twin.models import SimulationControls


@pytest.fixture
def api(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "twin.sqlite"),
        hardware_api_token="device-secret",
        admin_api_token="owner-secret",
    )
    now = [1000.0]
    with TestClient(create_app(settings, clock=lambda: now[0])) as client:
        yield client, now


def reading(now=1000, **fields):
    return dict(
        device_id="cooling-01",
        timestamp=now,
        temperature=31,
        humidity=45,
        ambient_temperature=24,
        fan_speed=0,
        **fields,
    )


def create_session(client):
    result = client.post("/api/simulations")
    assert result.status_code == 201
    data = result.json()
    return data["session_id"], {"Authorization": "Bearer " + data["token"]}


def test_authenticated_hardware_command_roundtrip_and_offline(api):
    client, now = api
    url = "/api/devices/cooling-01/telemetry"
    assert client.post(url, json=reading()).status_code == 401
    headers = {"Authorization": "Bearer device-secret"}
    response = client.post(url, json=reading(), headers=headers)
    assert response.status_code == 200
    assert response.json()["command"]["fan_speed"] == 40
    state = client.get("/api/live/state").json()
    assert state["device_status"] == "Online"
    assert state["last_update"] == 1000
    assert state["state"]["operating_mode"] == "LIVE"
    assert state["state"]["mqtt_connected"] is False
    now[0] += 11
    offline = client.get("/api/live/state").json()
    assert offline["device_status"] == "Offline"
    assert offline["state"]["state"] == "FAULT"
    command = client.get("/api/devices/cooling-01/command", headers=headers).json()
    assert command["fan_speed"] == 100
    now[0] += 1
    assert client.post(url, json=reading(now[0]), headers=headers).status_code == 200
    assert client.get("/api/live/state").json()["device_status"] == "Online"


def test_replay_invalid_values_and_owner_control(api):
    client, now = api
    url = "/api/devices/cooling-01/telemetry"
    headers = {"Authorization": "Bearer device-secret"}
    assert client.post(url, json=reading(), headers=headers).status_code == 200
    assert client.post(url, json=reading(), headers=headers).status_code == 409
    bad = reading(1002)
    bad["humidity"] = 150
    assert client.post(url, json=bad, headers=headers).status_code == 422
    assert client.post(url, json=reading(900), headers=headers).status_code == 409
    bad["humidity"] = 45
    bad["device_id"] = "other"
    assert client.post(url, json=bad, headers=headers).status_code == 422
    control = {"mode": "MANUAL", "manual_fan": 0, "setpoint": 30}
    assert client.put("/api/live/control", json=control, headers=headers).status_code == 401
    now[0] += 20
    response = client.put(
        "/api/live/control", json=control, headers={"Authorization": "Bearer owner-secret"}
    )
    assert response.status_code == 200
    assert response.json()["state"]["fan_command"] == 100


def test_sessions_and_hardware_cannot_cross_contaminate(api):
    client, now = api
    first, first_headers = create_session(client)
    second, second_headers = create_session(client)
    now[0] += 2
    result = client.post(
        f"/api/simulations/{first}/actions", json={"action": "OVERHEAT"}, headers=first_headers
    )
    assert result.status_code == 200
    assert result.json()["state"]["state"] == "OVERHEATING"
    assert result.json()["state"]["fan_command"] == 100
    untouched = client.get(f"/api/simulations/{second}/state", headers=second_headers).json()
    assert untouched["state"]["telemetry"]["temperature"] == 27
    assert client.get("/api/live/state").json()["state"]["telemetry"] is None
    assert client.get(f"/api/simulations/{first}/state", headers=second_headers).status_code == 401
    assert (
        client.put("/api/live/control", json={"manual_fan": 0}, headers=first_headers).status_code
        == 401
    )


def test_demo_traverses_overheating_and_recovers(tmp_path):
    runtime = TwinRuntime(Settings(database_path=str(tmp_path / "twin.sqlite")))
    _, context = runtime.create_session(1000)
    runtime.simulation_action(context, "DEMO", 1002)
    temperatures, commands, states = [], [], []
    for now in range(1004, 1280, 2):
        runtime.tick(now)
        state = context.twin.state
        temperatures.append(state.telemetry.temperature)
        commands.append(state.fan_command)
        states.append(state.state)
        if context.source.phase == "COMPLETE":
            break
    assert context.source.phase == "COMPLETE"
    assert now - 1002 <= 30  # Portfolio demo completes without a long wait.
    assert "OVERHEATING" in states
    assert max(temperatures) >= 40
    assert 100 in commands
    assert commands[-1] == 0
    assert temperatures[-1] <= 29
    assert "FAULT" not in states
    assert len(context.repository.recent("transitions")) >= 5
    assert context.twin.agent.enabled
    assert context.repository.recent("agent_events")
    runtime.close()


def test_stop_reset_settings_capacity_and_expiry(tmp_path):
    runtime = TwinRuntime(
        Settings(
            database_path=str(tmp_path / "twin.sqlite"),
            simulation_max_sessions=1,
            simulation_session_ttl=60,
        )
    )
    key, context = runtime.create_session(1000)
    with pytest.raises(ValueError):
        runtime.create_session(1001)
    runtime.simulation_controls(
        context,
        SimulationControls(temperature=34, humidity=60, heat_load=0.2, target_temperature=28),
        1002,
    )
    runtime.simulation_action(context, "START", 1004)
    assert context.twin.state.fan_command > 0
    assert context.twin.state.telemetry.humidity == 60
    runtime.simulation_action(context, "STOP", 1006)
    runtime.tick(1010)
    assert context.twin.state.state == "OFF"
    assert context.twin.state.fan_command == 0
    token = context.token
    runtime.simulation_action(context, "RESET", 1012)
    assert context.token == token
    assert context.source.system.temperature == 27
    assert not context.source.running
    assert context.twin.controller.settings.setpoint == 30
    runtime.expire_sessions(1061)
    assert key not in runtime.sessions
    runtime.close()


def test_no_token_never_authorizes_hardware(tmp_path):
    with TestClient(create_app(Settings(database_path=str(tmp_path / "twin.sqlite")))) as client:
        assert (
            client.get(
                "/api/devices/cooling-01/command", headers={"Authorization": "Bearer "}
            ).status_code
            == 401
        )
        assert client.get("/api/health").status_code == 200
        assert client.post("/api/simulations", content=b"x" * 17000).status_code == 413


def test_live_overheating_overrides_owner_manual_request(api):
    client, now = api
    hot = reading()
    hot["temperature"] = 42
    response = client.post(
        "/api/devices/cooling-01/telemetry",
        json=hot,
        headers={"Authorization": "Bearer device-secret"},
    )
    assert response.json()["state"] == "OVERHEATING"
    response = client.put(
        "/api/live/control",
        json={"mode": "MANUAL", "manual_fan": 0},
        headers={"Authorization": "Bearer owner-secret"},
    )
    assert response.json()["state"]["fan_command"] == 100
    assert "40 °C" in response.json()["analysis"]["summary"]


def test_simulation_pause_freezes_history_and_timestamp(tmp_path):
    runtime = TwinRuntime(Settings(database_path=str(tmp_path / "twin.sqlite")))
    _, context = runtime.create_session(1000)
    runtime.simulation_action(context, "START", 1002)
    runtime.tick(1004)
    runtime.simulation_action(context, "STOP", 1006)
    stamp = context.twin.state.telemetry.timestamp
    count = len(context.repository.recent("telemetry"))
    runtime.tick(1020)
    assert context.twin.state.telemetry.timestamp == stamp
    assert len(context.repository.recent("telemetry")) == count
    runtime.close()


def test_restart_preserves_live_history_but_waits_for_fresh_data(tmp_path):
    path = str(tmp_path / "twin.sqlite")
    settings = Settings(database_path=path, hardware_api_token="secret")
    with TestClient(create_app(settings, clock=lambda: 1000)) as client:
        client.post(
            "/api/devices/cooling-01/telemetry",
            json=reading(),
            headers={"Authorization": "Bearer secret"},
        )
    with TestClient(create_app(settings, clock=lambda: 1010)) as client:
        state = client.get("/api/live/state").json()
        assert state["last_update"] == 1000
        assert state["device_status"] == "Offline"
        assert len(state["history"]) == 1
        assert state["state"]["fan_command"] == 100


def test_optional_ai_is_validated_rate_limited_and_never_controls_hardware(tmp_path, monkeypatch):
    from smart_cooling_twin.llm import HTTPDiagnosticProvider

    settings = Settings(
        database_path=str(tmp_path / "twin.sqlite"),
        llm_enabled=True,
        llm_api_url="https://example.invalid/diagnose",
        llm_api_key="test",
    )
    monkeypatch.setattr(
        HTTPDiagnosticProvider,
        "diagnose",
        lambda *_: {"summary": "Normal operation", "possible_causes": []},
    )
    with TestClient(create_app(settings, clock=lambda: 1000)) as client:
        key, headers = create_session(client)
        before = client.get(f"/api/simulations/{key}/state", headers=headers).json()["state"][
            "fan_command"
        ]
        result = client.post(f"/api/simulations/{key}/analysis", headers=headers)
        assert result.status_code == 200
        assert result.json()["summary"] == "Normal operation"
        assert client.post(f"/api/simulations/{key}/analysis", headers=headers).status_code == 429
        after = client.get(f"/api/simulations/{key}/state", headers=headers).json()["state"][
            "fan_command"
        ]
        assert after == before
    monkeypatch.setattr(
        HTTPDiagnosticProvider, "diagnose", lambda *_: {"summary": "Unsafe output", "fan_speed": 0}
    )
    with TestClient(create_app(settings, clock=lambda: 2000)) as client:
        key, headers = create_session(client)
        assert client.post(f"/api/simulations/{key}/analysis", headers=headers).status_code == 502
        assert client.get("/api/health").status_code == 200


def test_reception_status_tracks_packets_not_dashboard_refreshes(api):
    client, now = api
    assert client.get("/api/live/state").json()["connection"]["activity"] == "WAITING"
    headers = {"Authorization": "Bearer device-secret"}
    client.post("/api/devices/cooling-01/telemetry", json=reading(), headers=headers)
    connection = client.get("/api/live/state").json()["connection"]
    assert connection["activity"] == "RECEIVING"
    assert connection["received_samples"] == 1
    now[0] += 6
    delayed = client.get("/api/live/state").json()["connection"]
    assert delayed["activity"] == "DELAYED"
    assert delayed["received_samples"] == 1
    assert delayed["last_received"] == 1000
    now[0] += 5
    assert client.get("/api/live/state").json()["connection"]["activity"] == "OFFLINE"
    client.post("/api/devices/cooling-01/telemetry", json=reading(now[0]), headers=headers)
    assert client.get("/api/live/state").json()["connection"]["received_samples"] == 2
    sid, auth = create_session(client)
    path = f"/api/simulations/{sid}"
    assert client.get(path + "/state", headers=auth).json()["connection"]["activity"] == "PAUSED"
    client.post(path + "/actions", json={"action": "START"}, headers=auth)
    assert client.get(path + "/state", headers=auth).json()["connection"]["activity"] == "RECEIVING"
    client.post(path + "/actions", json={"action": "STOP"}, headers=auth)
    now[0] += 20
    assert client.get(path + "/state", headers=auth).json()["connection"]["activity"] == "PAUSED"


def test_manual_calibration_auth_safety_and_insufficient_data(api):
    client, now = api
    assert client.post("/api/live/calibration").status_code == 401
    assert (
        client.post(
            "/api/live/calibration", headers={"Authorization": "Bearer owner-secret"}
        ).status_code
        == 409
    )
    sid, auth = create_session(client)
    path = f"/api/simulations/{sid}"
    assert client.post(path + "/calibration").status_code == 401
    assert client.post(path + "/calibration", headers=auth).status_code == 409
    client.post(path + "/actions", json={"action": "START"}, headers=auth)
    before = client.get(path + "/state", headers=auth).json()["parameters"]
    result = client.post(path + "/calibration", headers=auth)
    assert result.status_code == 200
    assert result.json()["pending_verification"] is False
    assert client.get(path + "/state", headers=auth).json()["parameters"] == before
    assert client.post(path + "/calibration", headers=auth).status_code == 409
    now[0] += 181
    client.post(path + "/actions", json={"action": "OVERHEAT"}, headers=auth)
    assert client.post(path + "/calibration", headers=auth).status_code == 409


def test_sensor_fault_remains_connected_but_invalidates_prediction(api):
    client, now = api
    headers = {"Authorization": "Bearer device-secret"}
    client.post("/api/devices/cooling-01/telemetry", json=reading(), headers=headers)
    assert client.get("/api/live/state").json()["state"]["prediction"] is not None
    now[0] += 2
    client.post(
        "/api/devices/cooling-01/telemetry", json=reading(now[0], sensor_ok=False), headers=headers
    )
    snapshot = client.get("/api/live/state").json()
    assert snapshot["device_status"] == "Online"
    assert snapshot["connection"]["activity"] == "RECEIVING"
    assert snapshot["state"]["state"] == "FAULT"
    assert snapshot["state"]["fan_command"] == 100
    assert snapshot["state"]["prediction"] is None


def test_control_change_ends_demo_and_power_off_blocks_normal_manual_demand(api):
    client, now = api
    sid, auth = create_session(client)
    path = f"/api/simulations/{sid}"
    client.post(path + "/actions", json={"action": "DEMO"}, headers=auth)
    result = client.put(
        path + "/control", json={"mode": "MANUAL", "manual_fan": 100, "setpoint": 30}, headers=auth
    )
    assert result.json()["simulation"]["phase"] == "IDLE"
    now[0] += 2
    client.post(path + "/actions", json={"action": "STOP"}, headers=auth)
    result = client.put(
        path + "/control", json={"mode": "MANUAL", "manual_fan": 100, "setpoint": 30}, headers=auth
    )
    assert result.json()["state"]["fan_command"] == 0
    assert result.json()["state"]["state"] == "OFF"


def test_calibration_rechecks_timeout_inside_step_throttle(api):
    client, now = api
    client.post(
        "/api/devices/cooling-01/telemetry",
        json=reading(),
        headers={"Authorization": "Bearer device-secret"},
    )
    now[0] = 1009.9
    assert client.get("/api/live/state").json()["state"]["device_online"] is True
    now[0] = 1010.1
    result = client.post("/api/live/calibration", headers={"Authorization": "Bearer owner-secret"})
    assert result.status_code == 409
    state = client.get("/api/live/state").json()["state"]
    assert state["state"] == "FAULT"
    assert state["prediction"] is None


def test_mqtt_offline_event_discards_earlier_queued_reading():
    from smart_cooling_twin.sources import MqttSensorSource, Esp32SensorSource
    from smart_cooling_twin.mqtt import TELEMETRY, STATUS
    from smart_cooling_twin.models import Telemetry
    import json

    class Transport:
        events = [
            (TELEMETRY, Telemetry(**reading()).model_dump_json().encode()),
            (
                STATUS,
                json.dumps({"device_id": "cooling-01", "online": False}).encode(),
            ),
        ]

        def drain(self):
            events, self.events = self.events, []
            return events

    source = MqttSensorSource.__new__(MqttSensorSource)
    Esp32SensorSource.__init__(source, "cooling-01")
    source.transport = Transport()
    with pytest.raises(ValueError, match="offline"):
        source.poll(1000)
    assert source.poll(1001) == []


def test_pages_cors_allows_only_configured_origin(api):
    client, _ = api
    headers = {
        "Origin": "https://maskini.github.io",
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    allowed = client.options("/api/live/control", headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://maskini.github.io"
    headers["Origin"] = "https://untrusted.example"
    rejected = client.options("/api/live/control", headers=headers)
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers
    assert (
        client.put(
            "/api/live/control",
            json={"mode": "AUTO", "manual_fan": 0, "setpoint": 30},
            headers={"Origin": "https://maskini.github.io"},
        ).status_code
        == 401
    )
