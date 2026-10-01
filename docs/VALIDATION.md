# Validation performed

Verified locally with Python 3.12.14:

- Full suite: **38 tests passed**, including actual TCP MQTT broker restart and delayed startup.
- Ruff lint and formatting checks passed.
- Python wheel built successfully from `pyproject.toml`.
- Simulator, twin, development broker and Streamlit ran as separate processes with LLM disabled.
- Live browser inspection confirmed incoming physical state, model metrics, charts and agent health.
- Dashboard AppTest verified control submission, sensor fault settings and hidden simulation controls in hardware mode.
- Running MQTT demo autonomously accepted a calibration and verified fresh-data MAE improvement from **0.29106 °C to 0.02378 °C**. This is one observed demonstration, not an accuracy guarantee.
- `.env`, hardware `config.h`, SQLite databases and the virtual environment are excluded by Git.

## Firmware compilation

The actual Arduino sketch compiled successfully for `esp32:esp32:esp32` using:

- Arduino CLI 1.5.1
- Arduino-ESP32 3.3.12
- PubSubClient 2.8
- ArduinoJson 7.4.2
- DHT sensor library 1.4.7
- Adafruit Unified Sensor 1.1.15

Build output: 934,473 bytes program storage (71%) and 47,676 bytes global dynamic memory (14%). The build used the example configuration in a temporary sketch directory. No credentials were added to the repository.

## Boundaries of this validation

No physical ESP32, DHT22 or fan was available for flashing or hardware-in-the-loop testing. Compilation verifies API compatibility, not wiring, sensor accuracy, motor operation or timing on a deployed board. Docker Desktop's daemon was unavailable, so real MQTT tests and the local demonstration used AMQTT rather than the supplied Mosquitto Compose deployment. The Compose configuration was statically validated. CI is configured for Python 3.11 and 3.12; the remote CI run has not been observed in this local session.

To repeat software checks:

```bash
pip install -e '.[dev]'
pytest -q
ruff check src simulator dashboard tests scripts
ruff format --check src simulator dashboard tests scripts
```
