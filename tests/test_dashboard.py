from pathlib import Path
from streamlit.testing.v1 import AppTest
from smart_cooling_twin.api_client import TwinAPIClient, APIError

APP = Path(__file__).resolve().parents[1] / "dashboard/app.py"


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_dashboard_simulation_actions_and_controls(dashboard_backend):
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert any(m.value == "27.00 °C" for m in app.metric)
    button(app, "Start Simulation").click().run()
    assert not app.exception
    assert any(m.value == "Running" for m in app.metric)
    app.number_input[0].set_value(35.0)
    button(app, "Apply simulation settings").click().run()
    assert not app.exception
    assert any(
        m.label == "Temperature" and 34.9 <= float(m.value.split()[0]) <= 35.1 for m in app.metric
    )
    button(app, "Simulate Overheating").click().run()
    assert any(m.value == "OVERHEATING" for m in app.metric)
    button(app, "Run Demo Scenario").click().run()
    assert not app.exception
    assert any("Guided demo" in item.value for item in app.subheader)
    assert any("Maskini" in item.value for item in app.caption)


def test_dashboard_live_offline_is_read_only_and_simulation_still_works(dashboard_backend):
    app = AppTest.from_file(str(APP)).run()
    app.radio[0].set_value("Live Hardware").run()
    assert not app.exception
    assert any(m.value == "Offline" for m in app.metric)
    assert len(app.slider) == 0
    assert not any(b.label == "Run Demo Scenario" for b in app.button)
    app.radio[0].set_value("Simulation").run()
    assert not app.exception
    button(app, "Run Demo Scenario").click().run()
    assert not app.exception


def test_dashboard_backend_failure_has_reconnect_message(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "true")

    def unavailable(*args, **kwargs):
        raise APIError("Backend is unavailable")

    monkeypatch.setattr(TwinAPIClient, "request", unavailable)
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert any("unavailable" in e.value for e in app.error)
    assert button(app, "Reconnect / new session")
