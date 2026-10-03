"""Exercise public simulation and protected hardware routes through the deployed proxy."""

import os
import httpx


def main() -> None:
    base = f"http://127.0.0.1:{os.environ.get('PORT', '8501')}"
    with httpx.Client(base_url=base, timeout=5) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/live/state").json()["device_status"] == "Offline"
        assert client.get("/api/devices/cooling-01/command").status_code == 401
        created = client.post("/api/simulations")
        created.raise_for_status()
        session = created.json()
        path = "/api/simulations/" + session["session_id"]
        headers = {"Authorization": "Bearer " + session["token"]}
        try:
            result = client.post(path + "/actions", json={"action": "OVERHEAT"}, headers=headers)
            result.raise_for_status()
            assert result.json()["state"]["state"] == "OVERHEATING"
            assert result.json()["state"]["fan_command"] == 100
            assert client.get("/api/live/state").json()["state"]["telemetry"] is None
            result = client.post(path + "/actions", json={"action": "RESET"}, headers=headers)
            result.raise_for_status()
            assert result.json()["simulation"]["running"] is False
            assert result.json()["state"]["telemetry"]["temperature"] == 27
        finally:
            client.delete(path, headers=headers).raise_for_status()
    print("Public demo, offline hardware, safety commands and session isolation verified")


if __name__ == "__main__":
    main()
