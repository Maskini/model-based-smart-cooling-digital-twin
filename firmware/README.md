# ESP32 firmware

## Dependencies

- Arduino IDE 2.x or Arduino CLI
- Espressif `esp32` board package 3.x
- PubSubClient 2.8
- ArduinoJson 7.x
- Adafruit DHT sensor library and Adafruit Unified Sensor

Copy `smart_cooling/config.example.h` to `smart_cooling/config.h` and edit the Wi-Fi, broker, device ID and pins. `config.h` is ignored. Select the appropriate ESP32 board and build/upload `smart_cooling/smart_cooling.ino`.

Example Arduino CLI commands after installing the board package and libraries:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/smart_cooling
arduino-cli upload --fqbn esp32:esp32:esp32 --port /dev/ttyUSB0 firmware/smart_cooling
```

Use the serial port corresponding to your board. Arduino-ESP32 3.x uses [`ledcAttach` / `ledcWrite`](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/ledc.html). The sketch uses GPIO 18 with 25 kHz, 8-bit PWM, and GPIO 4 for DHT22 by default. If PWM initialization fails, it holds the output high and stops startup.

## Wiring and behavior

Use a logic-level MOSFET power stage suited to the fan, a gate pull-down, a common ground and the appropriate motor protection. Supply the fan from its rated supply; an ESP32 GPIO cannot supply a motor. Verify the fan/power-stage PWM polarity before connecting the load.

Boot, invalid sensor readings, MQTT loss, command expiry and missing commands all select 100% fan. A local 40 °C limit also selects 100%, independent of Python. Commands have device IDs, timestamps, expiry and range checks. The ESP32 obtains UTC time by NTP; until synchronized it rejects commands and keeps the safe fallback. MQTT reconnect attempts occur every three seconds, with a one-second socket timeout.

DHT22 is sampled every two seconds. Fault telemetry reuses the last finite readings and marks `sensor_ok=false`; the twin rejects them from model calculations. `fan_speed` describes applied PWM and is not an RPM measurement. With only one DHT22, ambient temperature is a configured estimate (`AMBIENT_TEMPERATURE`); add a second sensor for measured ambient temperature.

The firmware uses the exact fields and topics in [MQTT.md](../docs/MQTT.md). Set `SIMULATION_MODE=false` and stop the simulator before connecting this device. Use an authenticated broker on a trusted isolated LAN; the included sketch uses plain MQTT, while the Python transport can also use TLS. The Compose broker binds to loopback and is not directly reachable by a Wi-Fi ESP32.

The sketch was compiled successfully with Arduino-ESP32 3.3.12; see [validation results](../docs/VALIDATION.md).

Hardware timing, wiring, temperature accuracy and fan operation require a physical commissioning test. Software simulation does not establish those properties.
