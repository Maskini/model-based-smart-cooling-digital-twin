# Validation performed

Verified locally with Python 3.12.14:

- Full suite: **59 tests passed**, including actual TCP MQTT broker restart and delayed startup.
- Ruff lint and formatting checks passed.
- Python wheel built successfully from `pyproject.toml`.
- GitHub Actions passed on Python 3.11 and 3.12, including lint and formatting.
- The complete REST/Simulation container built and started successfully in [GitHub Actions](https://github.com/Maskini/model-based-smart-cooling-digital-twin/actions/runs/36948241936). Checks passed for the shared API, offline live state, authentication and an isolated simulation through the public proxy.
- Dashboard tests verified private password gating, isolated simulation controls, live read-only mode, and backend failure handling.
- API tests verified hardware authentication, stale/replayed telemetry rejection, offline recovery, owner control safety overrides, session isolation/expiry, pause/reset, and diagnostic-only AI responses.
- The shared MQTT adapter passed a real-broker integration test.
- Reception tests verify packet freshness, delayed/offline/recovery states, paused simulation, and sample counts independent of dashboard polling. Manual calibration tests verify authentication, safety, cooldown and insufficient-data rejection.
- The guided scenario completed in the browser: normal → heating → overheating → recovery → cooling off.
- Simulator, twin, development broker and Streamlit ran as separate processes with LLM disabled.
- Live browser inspection confirmed incoming physical state, model metrics, charts and agent health.
- Dashboard AppTest verified control submission, sensor fault settings and hidden simulation controls in hardware mode.
- Running MQTT demo autonomously accepted a calibration and verified fresh-data MAE improvement from **0.29106 °C to 0.02378 °C**. This is one observed demonstration, not an accuracy guarantee.
- `.env`, hardware `config.h`, SQLite databases and the virtual environment are excluded by Git.

## Functional review

Regression checks cover sensor faults with an intact connection, expired prediction removal, calibration requests at the telemetry timeout boundary, manual control interrupting a demo, zero normal demand when powered off, dashboard manual/demo/stop transitions, and MQTT offline events discarding queued readings.

## HTTPS firmware compilation

The new REST sketch compiled for `esp32:esp32:esp32` with Arduino-ESP32 3.3.12, ArduinoJson 7.4.2, DHT 1.4.7 and Unified Sensor 1.1.15. Program storage: **1,045,411 bytes (79%)**; global memory: **49,044 bytes (14%)**. It uses certificate-validated HTTPS; the operator must configure the backend root CA and hardware token before flashing.

## Original MQTT firmware compilation

The actual Arduino sketch compiled successfully for `esp32:esp32:esp32` using:

- Arduino CLI 1.5.1
- Arduino-ESP32 3.3.12
- PubSubClient 2.8
- ArduinoJson 7.4.2
- DHT sensor library 1.4.7
- Adafruit Unified Sensor 1.1.15

Build output: 934,473 bytes program storage (71%) and 47,676 bytes global dynamic memory (14%). The build used the example configuration in a temporary sketch directory. No credentials were added to the repository.

## Boundaries of this validation

No physical ESP32, DHT22 or fan was available for flashing or hardware-in-the-loop testing. Compilation verifies API compatibility, not wiring, sensor accuracy, motor operation or timing on a deployed board. Docker Desktop's daemon was unavailable, so real MQTT tests and the local demonstration used AMQTT rather than the supplied Mosquitto Compose deployment. The Compose configuration was statically validated. The remote CI run, including the complete container build and startup, passed: [GitHub Actions run](https://github.com/Maskini/model-based-smart-cooling-digital-twin/actions/runs/36939436687). Hosting resources have not been provisioned; the owner requested cost review before deployment.

To repeat software checks:

```bash
pip install -e '.[dev]'
pytest -q
ruff check src simulator dashboard tests scripts
ruff format --check src simulator dashboard tests scripts
```
