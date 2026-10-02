import pytest
from fastapi.testclient import TestClient
from smart_cooling_twin.api import create_app
from smart_cooling_twin.api_client import TwinAPIClient, APIError
from smart_cooling_twin.config import Settings


@pytest.fixture
def dashboard_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "ui.sqlite"))
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-owner-token")
    settings = Settings(
        database_path=str(tmp_path / "ui.sqlite"),
        admin_api_token="test-owner-token",
        hardware_api_token="test-device-token",
    )
    with TestClient(create_app(settings)) as client:

        def request(self, method, path, *, token="", data=None):
            response = client.request(
                method,
                path,
                headers={"Authorization": "Bearer " + token} if token else {},
                json=data,
            )
            if response.status_code >= 400:
                raise APIError(str(response.json()["detail"]), response.status_code)
            return response.json() if response.content else {}

        monkeypatch.setattr(TwinAPIClient, "request", request)
        yield client
