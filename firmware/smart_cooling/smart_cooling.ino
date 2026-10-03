// Arduino-ESP32 3.x, ArduinoJson 7.x, PubSubClient 2.8, Adafruit DHT sensor library.
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <time.h>
#include "config.h"

WiFiClient network;
PubSubClient mqtt(network);
DHT dht(DHT_PIN, DHT22);
const char* TELEMETRY = "smartcooling/telemetry";
const char* COMMAND = "smartcooling/command";
const char* STATUS_TOPIC = "smartcooling/status";
float fan = 100, lastTemperature = 25, lastHumidity = 50;
bool sensorHealthy = false;
unsigned long lastCommand = 0, lastSample = 0, lastReconnect = 0;
double lastCommandTimestamp = 0, commandExpiry = 0;

void setFan(float value) {
  fan = constrain(value, 0.0f, 100.0f);
  ledcWrite(FAN_PIN, (uint32_t)roundf(fan * 255.0f / 100.0f));
}

bool number(JsonVariantConst value) {
  return value.is<double>() && isfinite(value.as<double>());
}

void receive(char* topic, byte* payload, unsigned int length) {
  if (strcmp(topic, COMMAND) || length > 512) return;
  JsonDocument doc;
  if (deserializeJson(doc, payload, length)) return;
  if (!doc["device_id"].is<const char*>() || strcmp(doc["device_id"], DEVICE_ID)) return;
  if (!number(doc["fan_speed"]) || !number(doc["timestamp"]) || !number(doc["expires_at"])) return;
  float requested = doc["fan_speed"];
  double issued = doc["timestamp"], expiry = doc["expires_at"];
  double now = (double)time(nullptr);
  if (now < 1700000000 || requested < 0 || requested > 100 || issued <= lastCommandTimestamp
      || issued > now + 1 || expiry <= now || expiry > now + 10 || expiry <= issued) return;
  lastCommandTimestamp = issued;
  commandExpiry = expiry;
  lastCommand = millis();
  setFan((!sensorHealthy || lastTemperature >= 40) ? 100 : requested);
}

void status(bool online) {
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["online"] = online;
  doc["sensor_ok"] = sensorHealthy;
  char out[192];
  serializeJson(doc, out, sizeof(out));
  mqtt.publish(STATUS_TOPIC, out, true);
}

void setup() {
  Serial.begin(115200);
  if (!ledcAttach(FAN_PIN, 25000, 8)) {
    pinMode(FAN_PIN, OUTPUT);
    digitalWrite(FAN_PIN, HIGH);
    while (true) delay(1000);
  }
  setFan(100);
  dht.begin();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(receive);
  mqtt.setBufferSize(768);
  mqtt.setKeepAlive(10);
  mqtt.setSocketTimeout(1);
}

void loop() {
  unsigned long nowMs = millis();
  if (!sensorHealthy || !mqtt.connected() || nowMs-lastCommand > 5000
      || (double)time(nullptr) >= commandExpiry || lastTemperature >= 40) setFan(100);
  if (nowMs-lastReconnect >= 3000) {
    lastReconnect = nowMs;
    if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
    else if (!mqtt.connected()) {
      JsonDocument will;
      will["device_id"] = DEVICE_ID;
      will["online"] = false;
      will["sensor_ok"] = false;
      char payload[192];
      serializeJson(will, payload, sizeof(payload));
      if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASSWORD, STATUS_TOPIC, 1, true, payload)) {
        mqtt.subscribe(COMMAND, 1);
        status(true);
      }
    }
  }
  mqtt.loop();
  if (nowMs-lastSample >= 2000) {
    lastSample = nowMs;
    float temperature = dht.readTemperature(), humidity = dht.readHumidity();
    sensorHealthy = isfinite(temperature) && isfinite(humidity) && temperature >= -40
                    && temperature <= 125 && humidity >= 0 && humidity <= 100;
    if (sensorHealthy) {
      lastTemperature = temperature;
      lastHumidity = humidity;
    } else setFan(100);
    if (lastTemperature >= 40) setFan(100);
    if (mqtt.connected() && time(nullptr) >= 1700000000) {
      JsonDocument doc;
      doc["device_id"] = DEVICE_ID;
      doc["timestamp"] = (double)time(nullptr);
      // Fault frames retain the last finite readings and explicitly mark them invalid.
      doc["temperature"] = lastTemperature;
      doc["ambient_temperature"] = AMBIENT_TEMPERATURE;
      doc["humidity"] = lastHumidity;
      doc["fan_speed"] = fan;
      doc["sensor_ok"] = sensorHealthy;
      doc["powered"] = true;
      char payload[512];
      serializeJson(doc, payload, sizeof(payload));
      mqtt.publish(TELEMETRY, payload);
      status(true);
    }
  }
  delay(5);
}
