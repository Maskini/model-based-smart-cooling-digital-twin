"""Run the shared API and dashboard behind Render's single public HTTP port."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


def service_commands(port: int) -> list[list[str]]:
    if not 1024 <= port <= 65535 or port in (8000, 8502):
        raise ValueError("PORT must be an unprivileged port other than internal ports 8000/8502")
    return [
        [
            sys.executable,
            "-m",
            "uvicorn",
            "smart_cooling_twin.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--workers",
            "1",
            "--no-access-log",
        ],
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "dashboard/app.py",
            "--server.address=127.0.0.1",
            "--server.port=8502",
            "--server.headless=true",
        ],
        ["nginx", "-c", "/tmp/smart-cooling-nginx.conf", "-g", "daemon off;"],
    ]


def main() -> int:
    env = os.environ.copy()
    env["BACKEND_URL"] = "http://127.0.0.1:8000"
    root = Path(__file__).resolve().parents[1]
    port = int(env.get("PORT", "8501"))
    commands = service_commands(port)
    template = (root / "deployment/nginx.conf.template").read_text()
    Path("/tmp/smart-cooling-nginx.conf").write_text(template.replace("__PORT__", str(port)))
    stopping = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopping.set())
    processes: list[subprocess.Popen] = []
    try:
        for command in commands:
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
