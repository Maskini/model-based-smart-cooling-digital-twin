"""Health is independent of whether a physical ESP32 is powered on."""

import json
import os
import urllib.request


def main() -> None:
    base = f"http://127.0.0.1:{os.environ.get('PORT', '8501')}"
    for path in ("/_stcore/health", "/api/health"):
        with urllib.request.urlopen(base + path, timeout=3) as response:
            if response.status != 200:
                raise SystemExit(1)
            if path == "/api/health" and json.load(response)["status"] != "ok":
                raise SystemExit(1)


if __name__ == "__main__":
    main()
