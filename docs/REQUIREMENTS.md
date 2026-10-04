# Requirements and verification map

| Requirement | Implementation | Verification |
|---|---|---|
| Python 3.11+, installable package | pyproject, src layout | CI 3.11/3.12, editable install |
| Simulator without hardware | PhysicalSystem, disturbance methods | Closed-loop and degradation tests |
| Real ESP32 | Arduino sketch + config example | Arduino-ESP32 3.3.12 compile passed; hardware test pending |
| MQTT telemetry/commands/status/agent | MQTTClient, TwinService | Real TCP broker integration |
| Automatic MQTT recovery | Paho reconnect + resubscription | Broker stop/restart integration |
| Validated finite bounded inputs | Pydantic records | Invalid values, missing fields, malformed JSON |
| Synchronized twin and six states | DigitalTwin, StateMachine | Transition, hysteresis, freshness tests |
| Predictions and rolling MAE | ThermalModel, ModelValidator | Equations and timestamp matching tests |
| AUTO/MANUAL and hard safety | Controller, SafetyLayer | Clamp, manual override, overheating, watchdog |
| Bounded calibration and holdout | Calibrator | Excitation, bounds, holdout quality tests |
| Autonomous supervisor | TwinSupervisorAgent | Degradation → adoption → fresh verification |
| Persistent memory and cooldown | Repository, agent_memory | Supervisor restart and cooldown tests |
| Alert deduplication | Repository active_alerts | Repeated fault alert tests |
| Rollback and outcome checks | SupervisorTools, pending verification | Failed improvement / timeout tests |
| Forecast diagnostics | SupervisorTools.run_forecast | Forecast comparisons |
| SQLite historical records | Repository | Roundtrip and integration assertions |
| Live dashboard and controls | Streamlit app | AppTest and local browser verification |
| Documentation and launch | README, docs, run_demo | Actual demo launch and quality checks |

## Acceptance constraints

- No supervisor has raw actuator, MQTT publishing, shell or Python execution authority.
- Every actuator command is computed by the deterministic controller and constrained by safety.
- Invalid or stale data cannot refresh health; device-local watchdog covers host/broker loss.
- Calibration is accepted only after a separate chronological quality comparison and parameter checks.
- Applied calibrations are checked on subsequent data and rolled back when improvement fails.
- Secrets and runtime databases are excluded from Git.
- Original architecture and visual assets remain available.

## Deployment assumptions

Single device, one twin process, one simulator or ESP32 process, shared local database for UI/runtime, synchronized clocks, two-second telemetry. Hardware qualification and network security outside the local development broker are deployment responsibilities. Physical hardware is not required for the software acceptance tests.

## Live and Simulation extension

| Requirement | Implementation | Verification |
|---|---|---|
| HTTPS hardware telemetry and return commands | Esp32SensorSource, authenticated REST routes, HTTPS sketch | API roundtrip, replay/invalid rejection, compiled sketch |
| Common source interface and core | SensorSource, TwinContext, DigitalTwin | Same controller in both modes, original MQTT suite retained |
| Offline hardware does not block public demo | Separate source contexts and health endpoint | Offline/recovery and API health tests |
| Isolated visitor simulation | Capability tokens, session TTL/capacity, bounded in-memory history | Cross-session and hardware isolation tests |
| Temperature, humidity, heat and target controls | SimulationControls and dashboard forms | API and AppTest interactions |
| Start/stop/reset/increase/overheat actions | SimulationSensorSource and runtime actions | Pause, reset, bounds and UI tests |
| One-click scenario with recovery | Physical heating, normal safety and hysteresis | End-to-end transition and fan-off assertion |
| Explanations for both modes | Deterministic state explanations | Safety rationale tests |
| Render single endpoint | Nginx + FastAPI + Streamlit | Container CI and public route smoke test |

The live database is durable. Visitor sessions are deliberately temporary and isolated. Hosting remains deferred until the owner approves deployment.
