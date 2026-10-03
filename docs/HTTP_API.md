# HTTP API and source adapters

## Shared architecture

`SensorSource` exposes `poll(now)`, `send_command(command, now)`, `connected(now)` and `close()`.

- `Esp32SensorSource` accepts authenticated HTTPS telemetry and maintains an expiring command mailbox.
- `SimulationSensorSource` uses the existing physical thermal simulator and receives the same controller commands.
- `MqttSensorSource` preserves the original LAN MQTT contract when `HARDWARE_TRANSPORT=MQTT`.

Every context uses the same `Telemetry`, `DigitalTwin`, `StateMachine`, `Controller`, `SafetyLayer`, thermal model, validator and supervisor. Visitor sessions have separate instances of this common core so their measurements, settings, model parameters and actions cannot reach the hardware context. Selecting a dashboard mode changes the displayed context; it never changes the device's data source or transfers commands between contexts.

The dashboard talks to the API through `TwinAPIClient`. It contains no SQL or thermal/control logic. The API owns the shared core, updates it once per second, samples simulation physics every two seconds, and serves snapshots. Streamlit refreshes every two seconds. Run one Uvicorn worker because the source mailbox and visitor sessions are in-process.

## Hardware authentication and payload

Set `HARDWARE_API_TOKEN` on the backend and copy the same secret to the ESP32's ignored `config.h`. Set `DEVICE_ID` identically. Use HTTPS and validate the backend certificate. The firmware synchronizes UTC by NTP.

`POST /api/devices/cooling-01/telemetry`

Header: `Authorization: Bearer <HARDWARE_API_TOKEN>`

```json
{
  "device_id": "cooling-01",
  "timestamp": 1790899200,
  "temperature": 31.2,
  "humidity": 47,
  "ambient_temperature": 24,
  "fan_speed": 44,
  "sensor_ok": true,
  "powered": true,
  "servo_angle": null
}
```

The timestamp must be current Unix seconds. `fan_speed` is applied cooling PWM (0–100%), not measured fan RPM. `servo_angle` is an optional measured/reported position (0–180°) for future servo hardware. The existing physical prototype uses a PWM fan, so the firmware leaves servo position absent. Temperature, humidity, time and actuator data are validated and finite. Ambient temperature can be configured in the one-sensor firmware.

Successful reply:

```json
{
  "accepted": true,
  "received_at": 1790899200,
  "state": "COOLING",
  "command": {
    "device_id": "cooling-01",
    "timestamp": 1790899200,
    "expires_at": 1790899205,
    "fan_speed": 44
  }
}
```

The ESP32 applies only a valid, fresh command for its own ID. `GET /api/devices/cooling-01/command` retrieves the latest command with the same authentication, if a separate polling loop is preferred. The included firmware receives commands in each telemetry response, avoiding an inbound connection to the device.

Missing/wrong token → 401; wrong device → 404; malformed values → 422; stale, duplicate or out-of-order telemetry → 409. Bodies over 16 KiB → 413. Rejected telemetry cannot refresh the core watchdog. No configured token means hardware ingress is disabled. REST ingress is disabled when the selected hardware transport is MQTT.

The device locally requests maximum cooling on sensor failure, overheating, command timeout, invalid replies or network loss. Backend health does not depend on the device being online. API snapshots clearly retain the last update timestamp and mark stale hardware Offline.

## Read-only and owner routes

| Route | Purpose | Access |
|---|---|---|
| `GET /api/health` | Backend update-loop health | Public |
| `GET /api/info` | Safe capability flags, no secrets | Public |
| `GET /api/live/state` | Latest hardware state/history/analysis | Public when `PUBLIC_DEMO=true`; otherwise owner |
| `PUT /api/live/control` | Validated AUTO/MANUAL/setpoint settings | `ADMIN_API_TOKEN` |
| `POST /api/live/analysis` | Optional external AI diagnostic | `ADMIN_API_TOKEN` |
| `GET /api/docs` | Interactive schemas | Public |

The owner token is separate from the device token. The dashboard only uses it after `DASHBOARD_PASSWORD` authentication. Live manual control never bypasses stale-data fallback or the fixed 40 °C limit. Public visitors can view the hardware context, but cannot change its controls.

## Simulation sessions

`POST /api/simulations` creates a stopped visitor session and returns `{session_id, token, snapshot}`. Include its token as a Bearer token on all subsequent session routes:

| Method and suffix under `/api/simulations/{session_id}` | Purpose |
|---|---|
| GET `/state` | Shared domain snapshot, history, predictions, transitions and analysis |
| POST `/actions` | `{ "action": "START|STOP|RESET|INCREASE|OVERHEAT|DEMO" }` (one value) |
| PUT `/settings` | temperature, humidity, heat_load, target_temperature and optional disturbances |
| PUT `/control` | AUTO/MANUAL, manual_fan, setpoint |
| POST `/analysis` | Optional rate-limited external AI explanation |
| DELETE (no suffix) | End and release this visitor's session |

Public demo sessions work with no hardware token and no powered-on ESP32. When `PUBLIC_DEMO=false`, creating a session requires the owner token. Each session expires after 15 minutes without dashboard/API activity; the default limit is 16 concurrent sessions. Exhaustion returns 429 with a friendly retry message. Session history is bounded to 1,000 rows per table and is intentionally ephemeral; restarting the server resets visitor demos. Live data is durable in the `.live.sqlite` database next to `DATABASE_PATH`. Existing MQTT databases are left untouched.

Stop freezes physics, history and timestamps. Reset creates a fresh context for that session only. Explicit temperature edits clear its prediction segment to avoid treating a deliberate visitor edit as a hardware sensor jump. Automatic demo heating uses the physical model normally and does not bypass anomaly detection or safety rules.

## Guided scenario

DEMO resets only the visitor context, enables AUTO with a 30 °C target, and starts near 27 °C. After four seconds, a controlled heat load raises temperature beyond 40 °C despite normal cooling. The unchanged safety controller activates 100%. The scenario then removes the heat load and improves available cooling so recovery is visible. Once temperature is at or below 29 °C, normal hysteresis switches cooling off. Scenario milestones and actual state transitions are shown separately. The run takes approximately one minute, depending on scheduler timing.

## Agent and optional AI

The deterministic supervisor and plain-language explanations work in both modes without an API key. They explain observed state, the actual cooling command, safety overrides, hysteresis and calibration health, and recommend diagnostic actions. External LLM text never enters an actuator route.

Optional `LLM_ENABLED=true`, `LLM_API_URL`, `LLM_API_KEY` and `LLM_MODEL` enable an explicit “Request optional AI explanation” button. The provider-neutral URL must accept a JSON POST `{model, observation}` with Bearer authentication and return `{summary, possible_causes}`. This is a diagnostic adapter contract, not a claim that arbitrary vendor endpoints accept this format. Additional fields such as `fan_speed` are rejected. Use an HTTPS diagnostic service that wraps your chosen model provider. No provider is bundled or contacted by default.

Requests run off the control loop, time out after five seconds and are limited to one request per minute across the service. Cached responses show their timestamp. Failures leave deterministic analysis and actuator control operational. Enabling the provider allows visitor-triggered diagnostic requests within that limit; consider provider-side usage limits before enabling it publicly.

## Reception status and dashboard calibration

Every state snapshot includes `connection`: transport, connected state, activity, backend receipt time, age, accepted sample count since context creation, device ID, expected 2-second interval and configured offline timeout. Activity is `RECEIVING`, `DELAYED` (over 5 seconds), `OFFLINE` (timeout/disconnect), `WAITING` (no received packet), or `PAUSED` for stopped simulation. Dashboard polling never refreshes the receipt timestamp. A connected MQTT broker is separate from fresh device data; sensor validity is reflected in the twin state.

`POST /api/live/calibration` requires the owner token; `POST /api/simulations/{id}/calibration` requires that session's token. Both use the same supervisor safety policy, cooldown, bounded fitting, holdout validation and fresh-data verification/rollback. Disabled supervision, paused simulation, unsafe state, pending verification or cooldown returns 409. An unsuccessful fit returns 200 with its reason and leaves model parameters unchanged. This endpoint cannot command actuators.
