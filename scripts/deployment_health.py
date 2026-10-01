"""Container health includes the runtime heartbeat, not only the web server."""

import os
import time
import urllib.request
from smart_cooling_twin.repository import Repository


def main() -> None:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{os.environ.get('PORT', '8501')}/_stcore/health", timeout=3
    ) as response:
        if response.status != 200:
            raise SystemExit(1)
    path = os.environ.get("DATABASE_PATH", "/data/twin.sqlite")
    repo = Repository(path)
    try:
        snapshot = repo.get("snapshot")
    finally:
        repo.close()
    if snapshot is None:
        raise SystemExit(1)
    state = snapshot["state"]
    if time.time() - snapshot["timestamp"] > 15 or not state["mqtt_connected"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
