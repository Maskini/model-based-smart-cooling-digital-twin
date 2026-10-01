"""Launch the local software stack, optionally using the development test broker."""

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
        "--local-broker", action="store_true", help="Use development AMQTT instead of Docker"
    )
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        MQTT_HOST="localhost", MQTT_PORT=str(args.port), SIMULATION_MODE="true", LLM_ENABLED="false"
    )
    commands = []
    if args.local_broker:
        commands.append([sys.executable, "scripts/test_broker.py", str(args.port)])
    commands += [
        [sys.executable, "-m", "simulator.physical_system", "--demo"],
        [sys.executable, "-m", "smart_cooling_twin"],
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "dashboard/app.py",
            "--server.address=127.0.0.1",
            "--server.headless=true",
        ],
    ]
    processes = []
    try:
        for command in commands:
            processes.append(subprocess.Popen(command, cwd=root, env=env))
        print("Demo: http://127.0.0.1:8501 · heat at 90 s · fan degradation at 180 s", flush=True)
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
