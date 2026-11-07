// EDGE NODE — ESP32-C6. Owner: hardware person.
//
// The board does the edge work for real; only the load cell is simulated (no hardware needed):
//   1. samples the "load cell" 10 times per second
//   2. SPIKE FILTER: median of 5 samples, so a single bad sample never reaches the cloud
//   3. WEIGH ONLY AT IDLE: reports a weight only when the press is still and the signal is stable for 3 s
//   4. STUCK SENSOR: 5 s of exactly identical raw samples -> quality STUCK
//   5. EMPTYING detected on the board (weight falls from >=10 % to <5 % of capacity) -> sent at once
//   6. OFFLINE BUFFER: no Wi-Fi/MQTT -> readings are kept (with their time) and sent later, oldest first
//   7. SIGNED READINGS: HMAC-SHA256 over "id|seq|time|weight|fill" -> the backend can prove nobody changed them
//   8. STATUS LED: green ok · blue flash = sent · yellow = offline, buffering · red = sensor problem · purple = emptied
//
// Demo controls
//   BOOT button: short press = the truck empties the container · hold 2 s = pretend the network is down / back
//   Serial monitor (115200): e empty · s spike · k stuck sensor · h heavy material · n normal · o offline · ? help
//
// Path: Wi-Fi -> MQTT (Espressif esp-mqtt, no extra library) topic compactor/<ID>/reading -> Node-RED -> backend /api/readings -> Grafana "6 Live sensors"
#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <time.h>

#include "config.h"
#include "mbedtls/md.h"
#include "mqtt_client.h"    // Espressif esp-mqtt, built into the ESP32 Arduino core (auto-reconnects)

#define LED_PIN 8      // addressable RGB LED on ESP32-C6 DevKitC-1 and most C6 boards
#define BUTTON_PIN 9   // BOOT button (free to use after boot)

static const float NOISE_KG = 15.0f;        // 1 sigma of one raw sample (like the dataset's sensors)
static const uint32_t SAMPLE_MS = 100;      // 10 Hz
static const int WIN = 30;                  // 3 s window for stability
static const int STUCK_SAMPLES = 50;        // 5 s of identical raw samples
static const int BUF_MAX = 200;             // offline buffer (readings)

// ------------------------------------------------------------------ simulated load cell + fill sensor
struct SimSensor {
  float mass = CAPACITY_KG * 0.10f;         // true material mass (kg)
  float fill = 10.0f;                       // true fill level (%)
  bool heavy = false;                       // heavy / wet material: mass grows 2x faster than the fill level
  bool pressOn = false;
  uint32_t pressUntil = 0, nextPress = 20000;
  int spikePending = 0;
  uint32_t stuckUntil = 0;
  float stuckValue = 0, stuckFill = 0;

  static float gauss() {                     // Box-Muller
    float u1 = (esp_random() + 1.0f) / 4294967297.0f, u2 = (esp_random() + 1.0f) / 4294967297.0f;
    return sqrtf(-2.0f * logf(u1)) * cosf(2.0f * PI * u2);
  }
  void step(uint32_t now) {                  // called every SAMPLE_MS
    float dFill = FILL_PCT_PER_MIN / 600.0f; // % per sample
    if (fill < 100.0f) {
      fill = min(100.0f, fill + dFill);
      mass += CAPACITY_KG * dFill / 100.0f * (heavy ? 2.0f : 1.0f);
    }
    if (!pressOn && now > nextPress) { pressOn = true; pressUntil = now + 6000; }       // press runs 6 s
    if (pressOn && now > pressUntil) { pressOn = false; nextPress = now + 40000 + esp_random() % 20000; }
  }
  float rawWeight(uint32_t now) {
    if (now < stuckUntil) return stuckValue;                                            // frozen ADC
    float w = mass + gauss() * NOISE_KG + (pressOn ? gauss() * 150.0f : 0.0f);           // press shakes the frame
    if (spikePending > 0) { spikePending--; w += CAPACITY_KG * 0.4f; }
    return w;
  }
  float fillPct(uint32_t now) {
    if (now < stuckUntil) return stuckFill;
    return constrain(fill + gauss() * 1.5f, 0.0f, 100.0f);
  }
  void empty() { mass = (esp_random() % 25); fill = 1.0f; heavy = false; }
  void stuck(uint32_t now, float lastRaw) { stuckUntil = now + 70000; stuckValue = roundf(lastRaw); stuckFill = roundf(fill); }
};

// ------------------------------------------------------------------ state
struct Reading {
  uint32_t seq; time_t epoch; float weight, fill; char quality[10]; uint16_t spikes; bool emptied;
};

SimSensor sim;
esp_mqtt_client_handle_t mq = nullptr;
volatile bool mqttUp = false;
Preferences prefs;

float rawBuf[WIN], filtBuf[WIN];
int nSamples = 0, head = 0, sameRaw = 0;
float lastRaw = NAN, lastStable = NAN, lastStableFill = 0;
uint32_t lastStableAt = 0, lastSample = 0, lastReport = 0, lastWifiTry = 0;
uint16_t spikesFiltered = 0;
uint32_t bootNo = 0, counter = 0;
bool offlineDemo = false, stuckFlag = false;
Reading buf[BUF_MAX];
int bufHead = 0, bufCount = 0;
uint32_t flashUntil = 0; uint8_t flashR = 0, flashG = 0, flashB = 0;

// ------------------------------------------------------------------ helpers
void led(uint8_t r, uint8_t g, uint8_t b) { rgbLedWrite(LED_PIN, r, g, b); }
void flash(uint8_t r, uint8_t g, uint8_t b, uint32_t ms) { flashR = r; flashG = g; flashB = b; flashUntil = millis() + ms; }

bool timeValid() { return time(nullptr) > 1700000000; }

String hmacHex(const String& msg) {
  uint8_t out[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, (const unsigned char*)DEVICE_KEY, strlen(DEVICE_KEY));
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)msg.c_str(), msg.length());
  mbedtls_md_hmac_finish(&ctx, out);
  mbedtls_md_free(&ctx);
  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + 2 * i, "%02x", out[i]);
  return String(hex);
}

float median5() {                            // median of the last 5 raw samples -> kills single spikes
  float v[5];
  int n = min(nSamples, 5);
  for (int i = 0; i < n; i++) v[i] = rawBuf[(head - 1 - i + WIN) % WIN];
  for (int i = 1; i < n; i++) for (int j = i; j > 0 && v[j] < v[j - 1]; j--) { float t = v[j]; v[j] = v[j - 1]; v[j - 1] = t; }
  return v[n / 2];
}

// message the backend can verify: same text on both sides
String canonical(const Reading& r) {
  char w[16], f[16], t[16];
  snprintf(w, sizeof w, "%.1f", r.weight);
  snprintf(f, sizeof f, "%.1f", r.fill);
  if (r.epoch) snprintf(t, sizeof t, "%ld", (long)r.epoch); else strcpy(t, "-");
  return String(COMPACTOR_ID) + "|" + r.seq + "|" + t + "|" + w + "|" + f;
}

String payload(const Reading& r, bool fromBuffer) {
  char ts[32] = "";
  if (r.epoch) { struct tm g; gmtime_r(&r.epoch, &g); strftime(ts, sizeof ts, "\"ts\":\"%Y-%m-%dT%H:%M:%SZ\",", &g); }
  char out[512];
  snprintf(out, sizeof out,
           "{\"compactor_id\":\"%s\",%s\"weight_kg\":%.1f,\"fill_pct\":%.1f,\"seq\":%lu,\"sig\":\"%s\","
           "\"edge\":{\"quality\":\"%s\",\"spikes_filtered\":%u,\"emptied\":%s,\"from_buffer\":%s,\"buffered\":%d,\"fw\":\"edge-1.0\"}}",
           COMPACTOR_ID, ts, r.weight, r.fill, (unsigned long)r.seq, hmacHex(canonical(r)).c_str(), r.quality, r.spikes,
           r.emptied ? "true" : "false", fromBuffer ? "true" : "false", bufCount);
  return String(out);
}

bool online() { return !offlineDemo && WiFi.status() == WL_CONNECTED && mqttUp; }

bool publish(const Reading& r, bool fromBuffer) {
  if (!online()) return false;
  String topic = String("compactor/") + COMPACTOR_ID + "/reading";
  String body = payload(r, fromBuffer);
  // QoS 1: the broker confirms; a resend after a broken link is harmless (the backend stores a reading once)
  return esp_mqtt_client_publish(mq, topic.c_str(), body.c_str(), 0, 1, 0) >= 0;
}

void bufferPush(const Reading& r) {
  if (!r.epoch) { Serial.println("  ! no clock yet: reading dropped (cannot be sent later without its time)"); return; }
  buf[(bufHead + bufCount) % BUF_MAX] = r;
  if (bufCount < BUF_MAX) bufCount++; else bufHead = (bufHead + 1) % BUF_MAX;   // full: oldest is lost
}

void flushBuffer() {                         // oldest first, a few per loop so the board stays responsive
  for (int i = 0; i < 5 && bufCount > 0 && online(); i++) {
    if (!publish(buf[bufHead], true)) break;
    Serial.printf("  -> sent from buffer: seq %lu (%d left)\n", (unsigned long)buf[bufHead].seq, bufCount - 1);
    bufHead = (bufHead + 1) % BUF_MAX; bufCount--;
    flash(0, 0, 60, 60);
  }
}

void send(Reading& r) {
  if (publish(r, false)) {
    Serial.printf("  -> sent: %.1f kg, %.1f %%, %s, seq %lu\n", r.weight, r.fill, r.quality, (unsigned long)r.seq);
    flash(0, 0, 80, 120);
  } else {
    bufferPush(r);
    Serial.printf("  .. offline: kept in buffer (%d waiting)\n", bufCount);
  }
}

Reading makeReading(float w, float f, const char* quality, bool emptied) {
  Reading r;
  r.seq = bootNo * 100000UL + (++counter);
  r.epoch = timeValid() ? time(nullptr) : 0;
  r.weight = roundf(w * 10) / 10;            // round BEFORE signing so both sides format the same number
  r.fill = roundf(f * 10) / 10;
  strncpy(r.quality, quality, sizeof r.quality - 1); r.quality[sizeof r.quality - 1] = 0;
  r.spikes = spikesFiltered;
  r.emptied = emptied;
  return r;
}

// ------------------------------------------------------------------ edge processing (runs at 10 Hz)
void sampleAndProcess(uint32_t now) {
  sim.step(now);
  float raw = sim.rawWeight(now);
  sameRaw = (raw == lastRaw) ? sameRaw + 1 : 0;
  lastRaw = raw;
  rawBuf[head] = raw;
  head = (head + 1) % WIN;
  if (nSamples < WIN) nSamples++;
  float m = median5();
  if (fabsf(raw - m) > 6 * NOISE_KG && !sim.pressOn) { spikesFiltered++; Serial.printf("  edge: spike %.0f kg filtered out\n", raw); }
  filtBuf[(head - 1 + WIN) % WIN] = m;

  bool nowStuck = sameRaw >= STUCK_SAMPLES;
  if (nowStuck && !stuckFlag) Serial.println("  edge: raw samples frozen -> sensor STUCK");
  stuckFlag = nowStuck;

  // stability: press still + 3 s of filtered samples within 4 sigma
  if (nSamples < WIN || sim.pressOn) return;
  float lo = 1e9, hi = -1e9, sum = 0;
  for (int i = 0; i < WIN; i++) { lo = min(lo, filtBuf[i]); hi = max(hi, filtBuf[i]); sum += filtBuf[i]; }
  if (hi - lo > 4 * NOISE_KG && !stuckFlag) return;
  float stable = sum / WIN, fill = sim.fillPct(now);

  // EMPTYING detected on the board -> report immediately
  if (!isnan(lastStable) && lastStable >= 0.10f * CAPACITY_KG && stable < 0.05f * CAPACITY_KG) {
    Serial.printf("  edge: EMPTIED (%.0f kg collected) -> reporting now\n", lastStable - stable);
    Reading r = makeReading(stable, fill, "OK", true);
    send(r);
    flash(60, 0, 60, 1000);
    lastReport = now;
  }
  lastStable = stable; lastStableFill = fill; lastStableAt = now;
}

void report(uint32_t now) {
  const char* q = stuckFlag ? "STUCK" : (lastStable > 1.05f * CAPACITY_KG ? "OVERLOAD" : "OK");
  if (now - lastStableAt > 15000 || isnan(lastStable)) {
    Serial.println("  edge: no stable weight yet (press running) -> waiting, nothing sent");
    return;
  }
  Reading r = makeReading(lastStable, lastStableFill, q, false);
  send(r);
}

// ------------------------------------------------------------------ connectivity
static void mqttEvent(void*, esp_event_base_t, int32_t id, void*) {
  if (id == MQTT_EVENT_CONNECTED) { mqttUp = true; Serial.println("mqtt: connected"); }
  else if (id == MQTT_EVENT_DISCONNECTED) {
    if (mqttUp) Serial.println("mqtt: disconnected (will retry)");
    else Serial.println("mqtt: cannot reach broker (is docker compose running? is the laptop IP right? firewall?)");
    mqttUp = false;
  }
}

void mqttStart() {
  static String uri = String("mqtt://") + MQTT_HOST + ":" + MQTT_PORT;
  static String cid = String("edge-") + COMPACTOR_ID + "-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  esp_mqtt_client_config_t cfg = {};
  cfg.broker.address.uri = uri.c_str();
  cfg.credentials.client_id = cid.c_str();
  cfg.network.reconnect_timeout_ms = 5000;
  cfg.buffer.size = 1024;                                                 // a signed reading is ~400 bytes
  mq = esp_mqtt_client_init(&cfg);
  esp_mqtt_client_register_event(mq, (esp_mqtt_event_id_t)ESP_EVENT_ANY_ID, mqttEvent, nullptr);
  esp_mqtt_client_start(mq);
}

void keepConnected(uint32_t now) {
  if (offlineDemo) return;
  if (WiFi.status() != WL_CONNECTED && now - lastWifiTry > 10000) {
    lastWifiTry = now;
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.println("wifi: connecting...");
  }
}

void help() {
  Serial.println("commands: e empty · s spike · k stuck sensor (70 s) · h heavy material · n normal · o offline on/off · ? help");
  Serial.println("BOOT button: short = empty · hold 2 s = offline on/off");
}

void handleInput(uint32_t now) {
  static uint32_t pressedAt = 0;
  static bool wasDown = false;
  bool down = digitalRead(BUTTON_PIN) == LOW;
  if (down && !wasDown) pressedAt = now;
  if (!down && wasDown) {
    if (now - pressedAt >= 2000) { offlineDemo = !offlineDemo; Serial.printf("demo: network %s\n", offlineDemo ? "DOWN" : "back"); }
    else if (now - pressedAt > 40) { sim.empty(); Serial.println("demo: truck empties the container"); }
  }
  wasDown = down;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'e') { sim.empty(); Serial.println("demo: truck empties the container"); }
    else if (c == 's') { sim.spikePending = 1; Serial.println("demo: one bad sample (+40 % capacity)"); }
    else if (c == 'k') { sim.stuck(now, lastRaw); Serial.println("demo: sensor frozen for 70 s"); }
    else if (c == 'h') { sim.heavy = true; Serial.println("demo: heavy / wet material (2x weight per fill)"); }
    else if (c == 'n') { sim.heavy = false; sim.stuckUntil = 0; Serial.println("demo: back to normal"); }
    else if (c == 'o') { offlineDemo = !offlineDemo; Serial.printf("demo: network %s\n", offlineDemo ? "DOWN" : "back"); }
    else if (c == '?') help();
  }
}

void updateLed(uint32_t now) {
  if (now < flashUntil) { led(flashR, flashG, flashB); return; }
  if (stuckFlag || lastStable > 1.05f * CAPACITY_KG) led(60, 0, 0);       // red: sensor problem / overload
  else if (!online()) led(50, 30, 0);                                     // yellow: offline, buffering
  else led(0, 25, 0);                                                     // green: ok
}

// ------------------------------------------------------------------ main
void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  led(0, 0, 40);
  prefs.begin("edge", false);
  bootNo = prefs.getUInt("boot", 0) + 1;                                  // seq keeps rising across restarts
  prefs.putUInt("boot", bootNo);
  Serial.printf("\nEDGE NODE %s (capacity %.0f kg) boot #%lu\n", COMPACTOR_ID, CAPACITY_KG, (unsigned long)bootNo);
  help();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.google.com");                    // UTC clock for timestamps
  mqttStart();                                                            // keeps retrying by itself
}

void loop() {
  uint32_t now = millis();
  handleInput(now);
  keepConnected(now);
  if (now - lastSample >= SAMPLE_MS) { lastSample = now; sampleAndProcess(now); }
  if (now - lastReport >= REPORT_MS) {
    lastReport = now;
    Serial.printf("[%s] true %.0f kg / %.0f %% | stable %.0f kg | %s | buffer %d | spikes filtered %u\n",
                  timeValid() ? "clock ok" : "no clock", sim.mass, sim.fill, lastStable,
                  online() ? "online" : "OFFLINE", bufCount, spikesFiltered);
    report(now);
  }
  flushBuffer();
  updateLed(now);
  delay(2);
}
