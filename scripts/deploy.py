"""Single-instance hosted simulation. Stop the whole service if any child fails."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


def service_commands(port: int) -> list[list[str]]:
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    return [
        ["mosquitto", "-c", "deployment/mosquitto.conf"],
        [sys.executable, "-m", "smart_cooling_twin"],
        [sys.executable, "-m", "simulator.physical_system"],
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "dashboard/app.py",
            "--server.address=0.0.0.0",
            f"--server.port={port}",
            "--server.headless=true",
        ],
    ]


def main() -> int:
    if len(os.environ.get("DASHBOARD_PASSWORD", "")) < 16:
        raise SystemExit(
            "Set DASHBOARD_PASSWORD to at least 16 characters in the hosting secret settings"
        )
    env = os.environ.copy()
    env.update(
        MQTT_HOST="127.0.0.1",
        MQTT_PORT="1883",
        MQTT_TLS="false",
        MQTT_USERNAME="",
        MQTT_PASSWORD="",
        SIMULATION_MODE="true",
        LLM_ENABLED="false",
    )
    root = Path(__file__).resolve().parents[1]
    stopping = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopping.set())
    processes: list[subprocess.Popen] = []
    try:
        for command in service_commands(int(env.get("PORT", "8501"))):
            processes.append(subprocess.Popen(command, cwd=root, env=env))
        while not stopping.wait(0.5):
            for index, process in enumerate(processes):
                if process.poll() is not None:
                    print(f"Service child {index} exited with {process.returncode}", flush=True)
                    return 1
        return 0
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
