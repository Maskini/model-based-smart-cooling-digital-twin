#pragma once
// Copy to config.h (ignored by Git). These values must match the backend environment.
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define BACKEND_URL "https://YOUR-SERVICE.onrender.com"
#define HARDWARE_API_TOKEN "YOUR_RENDER_HARDWARE_API_TOKEN"
#define DEVICE_ID "cooling-01"
#define DHT_PIN 4
#define FAN_PIN 18
#define AMBIENT_TEMPERATURE 24.0f
// Install the trusted root CA for YOUR backend's HTTPS certificate chain.
// Never disable certificate validation. This placeholder deliberately cannot connect.
static const char BACKEND_CA_PEM[] = R"CERT(-----BEGIN CERTIFICATE-----
REPLACE_WITH_YOUR_BACKEND_TRUSTED_ROOT_CA
-----END CERTIFICATE-----
)CERT";
