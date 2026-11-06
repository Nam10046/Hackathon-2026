// Compactor sensor node — ESP32 + HX711 load cell (+ optional HC-SR04 fill sensor)
// Owner: hardware person. Sends the reading format from CONTRACT.md via MQTT.
//
// Libraries (Arduino Library Manager): "HX711" by Bogdan Necula, "PubSubClient" by Nick O'Leary
// Board: ESP32 Dev Module

#include <WiFi.h>
#include <PubSubClient.h>
#include "HX711.h"
#include "config.h"   // copy config.h.example -> config.h first

HX711 scale;
WiFiClient wifi;
PubSubClient mqtt(wifi);

const int AVG_N = 10;           // moving average size (the press vibrates a lot)
float samples[AVG_N];
int sampleIdx = 0;
bool samplesFull = false;
unsigned long lastSend = 0;

void connectWifi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf(" ok, IP %s\n", WiFi.localIP().toString().c_str());
}

void connectMqtt() {
  while (!mqtt.connected()) {
    Serial.print("MQTT...");
    if (mqtt.connect(COMPACTOR_ID)) Serial.println(" ok");
    else { Serial.printf(" failed rc=%d, retry\n", mqtt.state()); delay(2000); }
  }
}

float readWeightKg() {
  float kg = scale.get_units(3) * DEMO_SCALE;   // 3 raw reads averaged by the library
  samples[sampleIdx] = kg;
  sampleIdx = (sampleIdx + 1) % AVG_N;
  if (sampleIdx == 0) samplesFull = true;
  int n = samplesFull ? AVG_N : sampleIdx;
  float sum = 0;
  for (int i = 0; i < n; i++) sum += samples[i];
  return sum / n;
}

float readFillPct() {
  digitalWrite(US_TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(US_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(US_TRIG, LOW);
  long us = pulseIn(US_ECHO, HIGH, 30000);        // timeout 30 ms
  if (us == 0) return -1;                         // no sensor / no echo
  float cm = us * 0.0343 / 2;
  float pct = (EMPTY_DISTANCE_CM - cm) / (EMPTY_DISTANCE_CM - FULL_DISTANCE_CM) * 100;
  return constrain(pct, 0, 100);
}

void setup() {
  Serial.begin(115200);
  pinMode(TARE_BUTTON, INPUT_PULLUP);
  pinMode(US_TRIG, OUTPUT);
  pinMode(US_ECHO, INPUT);

  scale.begin(HX711_DOUT, HX711_SCK);
  scale.set_scale(CALIBRATION_FACTOR);
  scale.tare();                                   // empty compactor = 0 kg

  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  if (digitalRead(TARE_BUTTON) == LOW) {          // press BOOT = set zero
    scale.tare();
    Serial.println("Tared");
    delay(500);
  }

  float kg = readWeightKg();

  if (millis() - lastSend >= SEND_INTERVAL_MS) {
    lastSend = millis();
    float fill = readFillPct();
    char topic[64], payload[160];
    snprintf(topic, sizeof(topic), "compactor/%s/reading", COMPACTOR_ID);
    if (fill >= 0)
      snprintf(payload, sizeof(payload), "{\"compactor_id\":\"%s\",\"weight_kg\":%.1f,\"fill_pct\":%.1f}", COMPACTOR_ID, kg, fill);
    else  // no fill sensor -> leave the field out (server uses its own time too)
      snprintf(payload, sizeof(payload), "{\"compactor_id\":\"%s\",\"weight_kg\":%.1f}", COMPACTOR_ID, kg);
    mqtt.publish(topic, payload);
    Serial.println(payload);
  }
  delay(100);
}
