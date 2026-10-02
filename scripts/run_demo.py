"""Start the API and portfolio dashboard locally; optionally retain the MQTT demo."""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--local-broker",
        action="store_true",
        help="Include the legacy MQTT broker and physical simulator",
    )
    parser.add_argument(
        "--mqtt", action="store_true", help="Use the legacy MQTT simulator with an existing broker"
    )
    parser.add_argument(
        "--port", type=int, default=1883, help="MQTT port for the optional legacy demo"
    )
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--dashboard-port", type=int, default=8501)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    mqtt_demo = args.mqtt or args.local_broker
    env.update(
        MQTT_HOST="localhost",
        MQTT_PORT=str(args.port),
        SIMULATION_MODE="true",
        PUBLIC_DEMO="true",
        LLM_ENABLED="false",
        HARDWARE_TRANSPORT="MQTT" if mqtt_demo else "REST",
        BACKEND_URL=f"http://127.0.0.1:{args.api_port}",
    )
    commands = []
    if args.local_broker:
        commands.append([sys.executable, "scripts/test_broker.py", str(args.port)])
    if mqtt_demo:
        commands.append([sys.executable, "-m", "simulator.physical_system", "--demo"])
    commands += [
        [
            sys.executable,
            "-m",
            "uvicorn",
            "smart_cooling_twin.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.api_port),
            "--no-access-log",
        ],
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "dashboard/app.py",
            "--server.address=127.0.0.1",
            f"--server.port={args.dashboard_port}",
            "--server.headless=true",
        ],
    ]
    processes = []
    try:
        for command in commands:
            processes.append(subprocess.Popen(command, cwd=root, env=env))
        print(
            f"Demo: http://127.0.0.1:{args.dashboard_port} · Choose Simulation → Run Demo Scenario",
            flush=True,
        )
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
        raise RuntimeError("A demo process exited; inspect its output above")
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
