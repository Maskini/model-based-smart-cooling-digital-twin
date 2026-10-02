// HTTPS adapter for Arduino-ESP32 3.x, ArduinoJson 7.x and Adafruit DHT22.
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <time.h>
#include "config.h"

DHT sensor(DHT_PIN, DHT22);
float temperature = 25, humidity = 47, fan = 100;
bool sensorHealthy = false;
unsigned long lastSample = 0, lastCommand = 0, lastReconnect = 0;
double lastIssued = 0, expiresAt = 0;

void setFan(float value) {
  fan = constrain(value, 0.0f, 100.0f);
  ledcWrite(FAN_PIN, (uint32_t)roundf(fan * 255 / 100));
}

void failsafe() {
  if (!sensorHealthy || WiFi.status() != WL_CONNECTED || temperature >= 40 ||
      millis()-lastCommand > 5000 || (double)time(nullptr) >= expiresAt) setFan(100);
}

bool finiteNumber(JsonVariantConst value) {
  return value.is<double>() && isfinite(value.as<double>());
}

void applyCommand(JsonVariantConst command) {
  if (!command["device_id"].is<const char*>() || strcmp(command["device_id"], DEVICE_ID)) return;
  if (!finiteNumber(command["fan_speed"]) || !finiteNumber(command["timestamp"]) ||
      !finiteNumber(command["expires_at"])) return;
  double issued = command["timestamp"], expiry = command["expires_at"], now = time(nullptr);
  float requested = command["fan_speed"];
  if (now < 1700000000 || requested < 0 || requested > 100 || issued <= lastIssued ||
      issued > now+1 || expiry <= now || expiry > now+10 || expiry <= issued) return;
  lastIssued = issued;
  expiresAt = expiry;
  lastCommand = millis();
  setFan((!sensorHealthy || temperature >= 40) ? 100 : requested);
}

void sendTelemetry() {
  if (WiFi.status() != WL_CONNECTED || time(nullptr) < 1700000000) {
    setFan(100);
    return;
  }
  if (!String(BACKEND_URL).startsWith("https://")) {
    setFan(100);  // Hardware credentials are only transmitted over validated TLS.
    return;
  }
  WiFiClientSecure network;
  network.setCACert(BACKEND_CA_PEM);
  network.setHandshakeTimeout(2);
  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(1500);
  String url = String(BACKEND_URL) + "/api/devices/" + DEVICE_ID + "/telemetry";
  if (!http.begin(network, url)) { setFan(100); return; }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + HARDWARE_API_TOKEN);
  JsonDocument payload;
  payload["device_id"] = DEVICE_ID;
  payload["timestamp"] = (double)time(nullptr);
  payload["temperature"] = temperature;
  payload["humidity"] = humidity;
  payload["ambient_temperature"] = AMBIENT_TEMPERATURE;
  payload["fan_speed"] = fan;  // Applied cooling actuator state; not measured RPM.
  payload["sensor_ok"] = sensorHealthy;
  payload["powered"] = true;
  String body;
  serializeJson(payload, body);
  int status = http.POST(body);
  if (status == 200) {
    if (http.getSize() > 2048) { setFan(100); http.end(); return; }
    JsonDocument reply;
    DeserializationError error = deserializeJson(reply, http.getString());
    if (!error) applyCommand(reply["command"]);
    else setFan(100);
  } else {
    setFan(100);
    Serial.printf("Backend unavailable or rejected telemetry (HTTP %d)\n", status);
  }
  http.end();
  failsafe();
}

void setup() {
  Serial.begin(115200);
  if (!ledcAttach(FAN_PIN, 25000, 8)) {
    pinMode(FAN_PIN, OUTPUT);
    digitalWrite(FAN_PIN, HIGH);
    while (true) delay(1000);
  }
  setFan(100);
  sensor.begin();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
}

void loop() {
  failsafe();
  unsigned long now = millis();
  if (WiFi.status() != WL_CONNECTED && now-lastReconnect >= 3000) {
    lastReconnect = now;
    WiFi.reconnect();
  }
  if (now-lastSample >= 2000) {
    lastSample = now;
    float t = sensor.readTemperature(), h = sensor.readHumidity();
    sensorHealthy = isfinite(t) && isfinite(h) && t >= -40 && t <= 125 && h >= 0 && h <= 100;
    if (sensorHealthy) { temperature = t; humidity = h; }
    failsafe();
    sendTelemetry();
  }
  delay(5);
}
