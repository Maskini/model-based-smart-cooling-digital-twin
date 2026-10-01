import time
from pathlib import Path
from streamlit.testing.v1 import AppTest
from smart_cooling_twin.repository import Repository
from smart_cooling_twin.twin import DigitalTwin
from smart_cooling_twin.models import Telemetry

APP = Path(__file__).resolve().parents[1] / "dashboard/app.py"


def test_dashboard_live_data_and_control_forms(tmp_path, monkeypatch):
    path = str(tmp_path / "ui.sqlite")
    monkeypatch.setenv("DATABASE_PATH", path)
    monkeypatch.setenv("SIMULATION_MODE", "true")
    repo = Repository(path)
    twin = DigitalTwin(repo)
    twin.state.mqtt_connected = True
    now = time.time()
    twin.receive(
        Telemetry(
            device_id="cooling-01",
            timestamp=now,
            temperature=31,
            ambient_temperature=24,
            humidity=47,
            fan_speed=40,
        ),
        now,
    )
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert any(m.value == "31.00 °C" for m in app.metric)
    app.selectbox[0].select("MANUAL")
    app.slider[0].set_value(35)
    app.button[0].click().run()
    assert not app.exception
    assert repo.get("control")["mode"] == "MANUAL"
    assert repo.get("control")["manual_fan"] == 35
    app.checkbox[0].check()
    app.button[1].click().run()
    assert repo.get("simulator")["sensor_failure"] is True
    repo.close()


def test_dashboard_hides_simulator_for_hardware(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ui.sqlite"))
    monkeypatch.setenv("SIMULATION_MODE", "false")
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert len(app.checkbox) == 0
    assert any("Waiting for the twin" in message.value for message in app.info)
