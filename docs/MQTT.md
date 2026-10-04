# MQTT contract

UTF-8 JSON, MQTT 3.1.1, one configured `DEVICE_ID` per deployment. All times are Unix UTC seconds and all numerical values must be finite. Device and host clocks must be synchronized. Unknown telemetry fields are rejected by Python. A device reporting failed sensing publishes its last finite values with `sensor_ok=false`; those readings are never used for predictions or calibration.

| Topic | Producer → consumer | Retained | QoS |
|---|---|---|---|
| `smartcooling/telemetry` | Device → twin | No | Python 1; ESP32 0 |
| `smartcooling/command` | Twin → device | No | 0 |
| `smartcooling/status` | Device → twin | Yes | Python / LWT 1; ESP32 live status 0 |
| `smartcooling/agent` | Twin → observers | No | 1 |

## Telemetry — every two seconds

```json
{"device_id":"cooling-01","timestamp":1790899200,"temperature":30.2,"ambient_temperature":24,"humidity":47,"fan_speed":35,"sensor_ok":true,"powered":true}
```

Required: device_id, timestamp, temperature, ambient_temperature, humidity, fan_speed. Optional sensor_ok/powered default true. Temperatures −40 to 125 °C; humidity/fan 0–100. The applied PWM at the end of the interval is used for calibration. Run only one physical device or simulator for this ID.

The twin rejects stale timestamps (outside `TELEMETRY_TIMEOUT`, default 10 s), duplicate timestamps and out-of-order timestamps. A wrong device ID is ignored. Invalid telemetry activates fault fallback; packets over 16 KiB or beyond the 1,000-event queue capacity are dropped and counted. Absence of valid telemetry still activates the watchdog.

## Fan command — refreshed every second

```json
{"device_id":"cooling-01","timestamp":1790899200,"expires_at":1790899205,"fan_speed":75}
```

Values outside 0–100 are invalid. The simulator and firmware require the matching device ID, a newer command timestamp, issue time at most one second ahead, and an expiry in the next ten seconds and after issue time. Commands are never retained or queued while disconnected. The device falls back to 100% after five seconds without a fresh command, on command expiry, sensor failure, or local overheating.

## Status

```json
{"device_id":"cooling-01","online":true,"sensor_ok":true}
```

A retained Last Will sets online=false. Simulator graceful shutdown also publishes offline. Online status alone never clears a telemetry fault: a valid fresh measurement is required. Do not use retained online state as a live heartbeat.

## Agent events

Payloads follow `AgentDecision` in `models.py`: timestamp, observation, model_health, decision, reason, action, expected_outcome, actual_outcome, verification_status. The SQLite event timeline is authoritative; MQTT publishes the latest event after a service tick and can coalesce multiple decisions from that tick.

## Recovery and deployment

Paho uses callback API VERSION2, reconnect delays 1–10 seconds and clean-session resubscription. Callbacks enqueue messages; `TwinService` validates and routes them on its service thread. Device watchdogs protect the interval before a broker disconnect is detected. The dashboard exchanges validated settings through SQLite, never through raw command publishing.

Python supports username/password and optional TLS. The development Compose mapping binds only to 127.0.0.1 and allows anonymous clients. Do not expose that anonymous configuration on a public interface. Configure a separate authenticated LAN broker for hardware.

Reference: [Paho client API](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).
