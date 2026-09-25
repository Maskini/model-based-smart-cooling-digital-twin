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
