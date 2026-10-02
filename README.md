# Model-Based Digital Twin of a Smart Cooling System

A small cyber-physical system combining an ESP32, real temperature and humidity sensing, MQTT communication, a simplified thermal model, state-based control, prediction, and model calibration.

The project is designed as a practical exploration of **Model-Based Systems Engineering (MBSE)** and **Digital Twin** concepts.

## Project Status

Current progress:

- System architecture defined
- Hardware selected
- Dashboard UI designed
- Physical components ordered
- ESP32 firmware planned
- MQTT integration planned
- Thermal model and calibration planned

## Dashboard

[![Current Smart Cooling Digital Twin dashboard in Simulation mode](docs/assets/dashboard-current.png)](https://maskini.github.io/model-based-smart-cooling-digital-twin/)

Current dashboard captured with simulated cooling active, receiving status, and measured versus predicted temperature. **[Try the live demo](https://maskini.github.io/model-based-smart-cooling-digital-twin/)**.


The final dashboard displays:

- measured temperature
- humidity
- physical fan command
- digital-twin system state
- predicted temperature
- prediction error
- rolling mean absolute error
- MQTT connection status
- manual and automatic control
- model parameters
- model calibration results

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

## System Architecture

```text
DHT22
  │
  ▼
ESP32
  │
  │ Temperature + Humidity
  │ MQTT
  ▼
Python Digital Twin
  ├── State Machine
  ├── Thermal Model
  ├── Prediction
  ├── Model Validation
  ├── Calibration
  └── Control Logic
          │
          │ MQTT Command
          ▼
        ESP32
          │
          ▼
       MOSFET
          │
          ▼
        5V Fan
