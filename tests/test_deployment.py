from pathlib import Path
import importlib.util
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_hosted_dashboard_blocks_data_and_controls_until_login(
    tmp_path, monkeypatch, dashboard_backend
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "private.sqlite"))
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-only-long-password")
    monkeypatch.setenv("PUBLIC_DEMO", "false")
    app = AppTest.from_file(str(ROOT / "dashboard/app.py")).run()
    assert not app.exception
    assert len(app.slider) == 0
    assert len(app.metric) == 0
    app.text_input[0].set_value("incorrect")
    app.button[0].click().run()
    assert app.error[0].value == "Incorrect password."
    assert len(app.slider) == 0
    app.text_input[0].set_value("test-only-long-password")
    app.button[0].click().run()
    assert not app.exception
    assert len(app.slider) > 0
    monkeypatch.setenv("DASHBOARD_PASSWORD", "rotated-test-password")
    app.run()
    assert len(app.slider) == 0


def test_deployment_port_validation():
    spec = importlib.util.spec_from_file_location("deploy", ROOT / "scripts/deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError):
        module.service_commands(65536)
    commands = module.service_commands(10000)
    assert "--server.port=8502" in commands[1]
    assert commands[-1][0] == "nginx"
