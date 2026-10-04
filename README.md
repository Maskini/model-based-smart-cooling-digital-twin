# Model-Based Smart Cooling Digital Twin

An independent software and IoT engineering project combining thermal modelling, temperature prediction, interactive simulation and deterministic cooling control. The public demo is ready to explore without hardware, installation or an external service key.

**Made by Maskini · © 2026 Maskini**

## Live portfolio demo

**[Open the instant browser demo](https://maskini.github.io/model-based-smart-cooling-digital-twin/)**

Choose **Simulation → Run Demo Scenario** to see overheating detection, cooling and recovery without hardware or a server wake-up. The GitHub Pages dashboard runs simulation locally in JavaScript; its data stays in the tab and resets on reload. Live Hardware connects to the existing Render API and can still experience a cold start. The [Python dashboard](https://smart-cooling-twin-demo.onrender.com/) remains available.

## Project status

**Working software prototype · Public interactive demo available**

- **Deployed demo:** browser simulation with adjustable conditions, temperature history, fan state and a guided overheating-and-recovery scenario.
- **Implemented software:** Python API, thermal model, state-based control, model calibration, rule-based supervision and ESP32 communication adapters.
- **Automated validation:** Python 3.11/3.12 tests, browser control/model parity checks and Docker deployment checks. See the [validation report](docs/VALIDATION.md) for scope and results.
- **Next milestone:** physical ESP32 validation of wiring, sensor accuracy, fan response and end-to-end operation.

Actual actuator commands are validated by deterministic application rules.

## Dashboard preview

[![Current dashboard in Simulation mode with cooling active and measured versus predicted temperature](docs/assets/dashboard-current.png)](https://maskini.github.io/model-based-smart-cooling-digital-twin/)

Captured from the running browser demo. Values shown are simulated.

## Hardware Components

| Component | Model / specification | Quantity |
|---|---|---:|
| Microcontroller development board | ESP32-WROOM-32E (ESP32DEVKITC32E) | 1 |
| Temperature and humidity sensor module | DHT22 (DEBO DHT 22 BRD) | 1 |
| Cooling fan | FAN-MF 4010 5V — 40 × 40 × 10 mm, 5 V DC, 0.47 W | 1 |
| N-channel MOSFET | IRLZ44N, TO-220AB | 1 |
| Rectifier diode | 1N4007, 1 A, 1000 V, DO-41 | 2 |
| Metal-film resistor | 220 Ω, 250 mW, 0.1% | 1 |
| Metal-film resistor | 10 kΩ, 250 mW, 0.1% | 1 |
| Breadboard set with power module | BREADBOARD SET1, 830 contacts | 1 |
| USB power cable | Delock 85250 — USB-A to two open wire ends | 1 |
| USB power supply | YS10-0502100 USB — 5 V, 2.1 A, 10.5 W | 1 |
| Three-conductor connector | WAGO 221-413 | 2 |
| Two-conductor connector | WAGO 221-412 | 1 |
| USB cable | Delock 83333 — USB-C to Micro-B, 0.5 m | 1 |

## Try it locally — Python 3.11+

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
python scripts/run_demo.py
```

Open [the dashboard](http://127.0.0.1:8501), choose **Simulation**, and click **Run Demo Scenario**. FastAPI runs on port 8000 and the dashboard on 8501. Ctrl-C stops both. [Interactive API documentation](http://127.0.0.1:8000/api/docs) is also available.

For separate processes:

```bash
python -m uvicorn smart_cooling_twin.api:app --host 127.0.0.1 --port 8000
streamlit run dashboard/app.py --server.address=127.0.0.1 --server.headless=true
```

## Two modes, one application

| | Simulation | Live Hardware |
|---|---|---|
| Data source | Thermal physical simulator | ESP32 over HTTPS, or optional LAN MQTT |
| Hardware required | No | ESP32, DHT22 and cooling fan |
| Visitor controls | Temperature, humidity, heat load, target, disturbances | Read-only view |
| Owner controls | Same deterministic controller | Authenticated AUTO/MANUAL and target settings |
| History | Isolated, bounded visitor session | Persistent SQLite hardware history |
| Offline behavior | Works independently of any physical device | Shows Offline and last update; safety fallback remains active |
| Model and agent | Shared core, prediction, validation, calibration and supervision | The same core and policies |

The mode selector switches the displayed source context. It does not reroute simulated commands to hardware. Every visitor gets a separate simulation session; one visitor's experiment cannot change another visitor's values or the live device.

### Simulation controls

Use **Start Simulation**, **Stop Simulation**, **Reset**, **Increase Temperature**, **Simulate Overheating**, and **Run Demo Scenario**. Edit temperature, humidity, heat load and target temperature in the sidebar. Advanced controls retain ambient temperature, fan effectiveness, sensor noise and sensor-failure injection. AUTO/MANUAL control remains available within the visitor's own session.

Stop freezes physics, history and telemetry timestamps. Reset affects only that visitor. Explicit temperature edits start a new measurement segment so intentional edits are not mistaken for sensor corruption. The dashboard shows measured/applied PWM, requested cooling, state transitions, charts, predictions, rolling MAE, model parameters, alerts, calibration outcomes and readable agent analysis.

### One-click guided scenario

1. Start around 27 °C in NORMAL with cooling off.
2. Apply a gradually acting thermal load.
3. Cross the normal cooling target and then the fixed 40 °C overheating threshold.
4. Detect OVERHEATING and enforce maximum cooling.
5. Remove the excessive heat load and improve available cooling.
6. Temperature falls toward the 30 °C target.
7. At or below 29 °C, hysteresis switches cooling off.

The browser demo typically completes in about 30 seconds while the tab is active. Actual state transitions and scenario milestones appear in the UI. Physics generates the rising and falling measurements; the scenario does not directly set actuator commands or relax safety limits.

## Architecture

```mermaid
flowchart LR
    ESP[ESP32 / DHT22 / PWM fan] <-->|Wi-Fi / HTTPS telemetry and expiring commands| API[Digital Twin API]
    UI[Streamlit dashboard] <--> API
    API --> LIVE[Live source context]
    API --> SIM[Isolated visitor simulation contexts]
    LIVE --> CORE[Shared DigitalTwin implementation]
    SIM --> CORE
    CORE --> MODEL[Thermal prediction and validation]
    CORE --> CONTROL[Deterministic controller and safety]
    CORE <--> AGENT[Autonomous supervisor and explanations]
    AGENT --> POLICY[Bounded calibration policy]
    LIVE --> DB[(Durable SQLite history)]
```

`SensorSource` is the adapter interface. `Esp32SensorSource`, `SimulationSensorSource`, and the optional `MqttSensorSource` all exchange the same validated `Telemetry` and `FanCommand` domain records with the same core. Transport callbacks and firmware-specific details do not contain application control decisions.

For Render, Nginx exposes the dashboard and `/api/*` through a single HTTPS address. Simulation remains usable while the physical device is off. The backend keeps live state in a separate `*.live.sqlite` database and leaves existing MQTT history intact.

## Model and validation

```text
dT/dt = k_heat + k_ambient * (T_ambient - T) - k_fan * fan_speed / 100
T_next = T + dt * dT/dt
```

Temperature is °C and time is seconds. Defaults are `k_heat=0.12 °C/s`, `k_ambient=0.012 /s` and `k_fan=0.25 °C/s`. Euler integration uses steps no longer than one second. The model is a deliberately simplified thermal approximation, not a high-fidelity thermodynamic simulator.

Each accepted measurement creates a two-second forecast. Later measurements within 0.5 seconds of its target are matched. Residual = measured − predicted; rolling MAE uses 30 absolute residuals. Missing samples are not treated as prediction errors.

Calibration uses at least 60 usable intervals and at least 15 percentage points of fan excitation. The first 70% of recent intervals fit the candidate; the final 30% validate it. A candidate must stay within physical parameter bounds and improve holdout MAE by at least 15%. The supervisor then checks 30 fresh intervals and rolls back unless improvement persists by at least 5%. Calibration cooldown, decisions, outcomes and alerts remain inspectable.

## Agent analysis and safety

The supervisor operates in both modes through OBSERVE → ASSESS → DECIDE → ACT → VERIFY → RECORD. It monitors connectivity, sensor health, temperature trends, actuator response, residual bias, model drift and recent actions. Human-readable explanations describe the actual controller decision and recommendations, for example why maximum cooling overrode manual demand.

| Condition | Deterministic behavior |
|---|---|
| NORMAL / HEATING / OFF in AUTO | Zero normal fan demand |
| COOLING in AUTO | `20 + 20 × (temperature − target)`, clamped to 0–100% |
| MANUAL | Requested demand, subject to safety |
| Temperature ≥40 °C or FAULT | 100% fallback overrides manual demand |
| Cooling exit | Target −1 °C hysteresis |
| Owner/visitor target | 20–35 °C |
| No valid device telemetry | Offline / FAULT after 10 seconds by default |
| Device receives no valid command | Local maximum cooling within five seconds |

The deterministic controller owns actuation. The supervisor can request validated calibration, rollback and forecasts but cannot issue raw PWM, publish arbitrary commands or modify the hard limit. Explanations are generated from the current state and application rules.

## Connect real hardware

Use `firmware/smart_cooling_http` for the Render/Internet path. Configure its ignored `config.h` with Wi-Fi credentials, the public HTTPS backend URL, matching `DEVICE_ID` and `HARDWARE_API_TOKEN`, and the trusted root CA. The ESP32 POSTs telemetry every two seconds and receives the latest expiring command in the response. A separate authenticated command-polling endpoint is also available. The firmware validates TLS, identity, numeric ranges, command time and expiry, and reconnects after failures.

The intended hardware is an ESP32, DHT22, logic-level MOSFET and 5 V fan, with a suitable motor power stage and common ground. GPIO 4 is the default sensor pin and GPIO 18 the PWM pin. Do not power a fan from a GPIO. Fan telemetry is applied PWM, not measured RPM. `servo_angle` is an optional telemetry field for future servo-equipped hardware; the supplied firmware operates the existing PWM fan.

See [firmware setup](firmware/README.md) and [HTTP/API contract](docs/HTTP_API.md). No board is needed to run or deploy the public simulation.

### Preserved MQTT compatibility

The original MQTT sketch and runtime remain available:

```bash
docker compose up -d
python -m simulator.physical_system
python -m smart_cooling_twin
```

Those commands run the legacy MQTT core. To use MQTT with the new dashboard, run the API with `HARDWARE_TRANSPORT=MQTT` instead of starting that standalone twin, or use:

```bash
python scripts/run_demo.py --local-broker --port 18883
```

Select Live Hardware to inspect the optional MQTT source. Visitor simulations remain independent. The latter command retains the earlier model-degradation disturbance demo. Never run two controller processes against the same device ID. [MQTT contract](docs/MQTT.md).

## Deployment and configuration

The Dockerfile, process supervisor, Nginx routing, health checks, persistent disk and Render blueprint are prepared. **Hosting has not been provisioned.** See [deployment instructions](docs/DEPLOYMENT.md) for the complete variable list and operating steps.

Public Simulation does not require a login. Hardware ingress uses `HARDWARE_API_TOKEN`; owner controls use a separate `ADMIN_API_TOKEN` and dashboard password. Empty tokens disable those hardware operations. `PUBLIC_DEMO=false` protects the dashboard and live API views for a private deployment. Secrets belong in environment variables and ignored firmware configuration, never Git.

## Tests

```bash
pytest -q
ruff check src simulator dashboard tests scripts
ruff format --check src simulator dashboard tests scripts
```

Tests cover model equations, state transitions, safety, real TCP MQTT recovery, authenticated HTTP telemetry and commands, stale/replayed readings, offline recovery, visitor isolation, paused simulation, reset, guided overheating recovery, persistence, calibration verification/rollback, dashboard interactions. CI tests Python 3.11/3.12 and builds/starts the complete Docker deployment, then exercises its public API through Nginx.

## Repository map

```text
src/smart_cooling_twin/  Shared core, adapters, API, model, controller, agent and persistence
simulator/              Reusable physical thermal simulator and original MQTT runner
dashboard/              One portfolio dashboard for both modes
firmware/               HTTPS and original MQTT ESP32 sketches
scripts/                Local launcher, deployment supervisor and health checks
deployment/             Nginx configuration and container entrypoint
docs/                   Architecture, requirements, contracts, deployment and validation
data/                   Local runtime data (ignored)
```

## Limits and future work

This is an educational prototype, not a certified thermal safety system. The first-order model omits actuator lag, multiple thermal masses and nonlinear airflow. A constant cooling term can predict below ambient. Calibration depends on meaningful excitation and may reject data that mixes disturbances. A second ambient sensor, tachometer and hardware-in-the-loop commissioning are future improvements.

The default deployment uses one process/replica with bounded, disposable visitor sessions (16 concurrent, 15-minute idle timeout). Live history persists until archived by the operator. Physical wiring, sensor accuracy and motor behavior still require testing on the actual ESP32.

Original work is preserved in [the design README](docs/ORIGINAL_DESIGN.md) and [dashboard concept](docs/assets/dashboard-concept.jpg). See [requirements](docs/REQUIREMENTS.md), [architecture](docs/ARCHITECTURE.md), and [validation](docs/VALIDATION.md).
