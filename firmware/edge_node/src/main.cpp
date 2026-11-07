// EDGE NODE — ESP32-C6 running a whole SITE: 3 compactors on one board. Owner: hardware person.
//
// The board does the edge work for real; only the load cells are simulated (no hardware needed). Per compactor:
//   1. samples its "load cell" 10 times per second
//   2. SPIKE FILTER: median of 5 samples, so a single bad sample never reaches the cloud
//   3. WEIGH ONLY AT IDLE: reports a weight only when the press is still and the signal is stable for 3 s
//   4. STUCK SENSOR: 5 s of exactly identical raw samples -> quality STUCK
//   5. EMPTYING detected on the board (weight falls from >=10 % to <5 % of capacity) -> sent at once
//   6. OFFLINE BUFFER: no Wi-Fi/MQTT -> readings are kept (with their time) and sent later, oldest first
//   7. SIGNED READINGS: HMAC-SHA256 over "id|seq|time|weight|fill" -> the backend can prove nobody changed them
// Site level:
//   8. TRUCK COMMANDS: the backend books pickups; when the (simulated) truck arrives it sends
//      {"compactor_id":"C2","action":"empty"} on site/<SITE_ID>/cmd and the board empties that container
//   9. FAST MODE: material arrives TIME_SCALE x faster (60 = 1 real minute is 1 site hour)
//  10. STATUS LED: green ok · blue flash = sent · yellow = offline · red = sensor problem · purple = emptied · white = truck
//
// Demo controls
//   BOOT button: short press = empty the selected compactor · hold 2 s = pretend the network is down / back
//   Serial monitor (115200): 1/2/3 select compactor · e empty · s spike · k stuck sensor · h heavy material
//                            n normal · o offline · ? help
//
// Path: Wi-Fi -> MQTT compactor/<ID>/reading -> Node-RED -> backend /api/readings -> Grafana "Live product" pages
#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <time.h>

#include "config.h"
#include "mbedtls/md.h"
#include "mqtt_client.h"    // Espressif esp-mqtt, built into the ESP32 Arduino core (auto-reconnects)

#ifndef SITE_ID
#define SITE_ID "S1"
#endif
#ifndef TIME_SCALE
#define TIME_SCALE 60       // 60 = fast demo (1 min = 1 h). 1 = real time. Must match DEMO_TIME_SCALE in the backend .env
#endif

#define LED_PIN 8      // addressable RGB LED on ESP32-C6 DevKitC-1 and most C6 boards
#define BUTTON_PIN 9   // BOOT button (free to use after boot)

static const float NOISE_KG = 15.0f;        // 1 sigma of one raw sample (like the dataset's sensors)
static const uint32_t SAMPLE_MS = 100;      // 10 Hz
static const int WIN = 30;                  // 3 s window for stability
static const int STUCK_SAMPLES = 50;        // 5 s of identical raw samples
static const int BUF_MAX = 240;             // offline buffer (readings, all compactors)

// the site: id, material (for the log only - the backend knows it), capacity, fill speed in % per SITE hour
struct ChannelDef { const char* id; const char* material; float capacityKg; float fillPctPerHour; };
static const ChannelDef DEFS[] = {
  {"C1", "cardboard", 2000, 5.0f},   // busy warehouse: full in ~20 h
  {"C2", "plastic",   1500, 3.5f},   // ~28 h
  {"C3", "mixed",     4000, 4.0f},   // ~25 h
};
static const int NCH = sizeof(DEFS) / sizeof(DEFS[0]);

// ------------------------------------------------------------------ simulated load cell + fill sensor
struct SimSensor {
  float cap = 2000, rate = 3;               // capacity kg, % per site hour
  float mass = 0, fill = 0;                 // true material mass (kg), true fill level (%)
  bool heavy = false;                       // heavy / wet material: mass grows 2x faster than the fill level
  bool pressOn = false;
  uint32_t pressUntil = 0, nextPress = 0;
  int spikePending = 0;
  uint32_t stuckUntil = 0;
  float stuckValue = 0, stuckFill = 0;

  static float gauss() {                     // Box-Muller
    float u1 = (esp_random() + 1.0f) / 4294967297.0f, u2 = (esp_random() + 1.0f) / 4294967297.0f;
    return sqrtf(-2.0f * logf(u1)) * cosf(2.0f * PI * u2);
  }
  void init(const ChannelDef& d, int i) {
    cap = d.capacityKg; rate = d.fillPctPerHour;
    fill = 8.0f + (esp_random() % 50);       // start somewhere between 8 and 58 % so the site is not in sync
    mass = cap * fill / 100.0f;
    nextPress = 15000 + i * 9000;
  }
  void step(uint32_t now) {                  // called every SAMPLE_MS
    // % per sample = rate per site hour * TIME_SCALE / 36000 samples per real hour, with some randomness
    float dFill = rate * TIME_SCALE / 36000.0f * (0.5f + (esp_random() % 1000) / 1000.0f);
    if (fill < 100.0f) {                     // at 100 % it is full: new waste goes NEXT to it (overflow)
      fill = min(100.0f, fill + dFill);
      mass = min(cap * 1.08f, mass + cap * dFill / 100.0f * (heavy ? 2.0f : 1.0f));
    }
    if (!pressOn && now > nextPress) { pressOn = true; pressUntil = now + 6000; }       // press runs 6 s
    if (pressOn && now > pressUntil) { pressOn = false; nextPress = now + 40000 + esp_random() % 30000; }
  }
  float rawWeight(uint32_t now) {
    if (now < stuckUntil) return stuckValue;                                            // frozen ADC
    float w = mass + gauss() * NOISE_KG + (pressOn ? gauss() * 150.0f : 0.0f);           // press shakes the frame
    if (spikePending > 0) { spikePending--; w += cap * 0.4f; }
    return w;
  }
  float fillPct(uint32_t now) {
    if (now < stuckUntil) return stuckFill;
    return constrain(fill + gauss() * 1.5f, 0.0f, 100.0f);
  }
  void empty() { mass = (esp_random() % 25); fill = 1.0f; heavy = false; }
  void stuck(uint32_t now, float lastRaw) { stuckUntil = now + 70000; stuckValue = roundf(lastRaw); stuckFill = roundf(fill); }
};

struct Reading {
  uint8_t ch; uint32_t seq; time_t epoch; float weight, fill; char quality[10]; uint16_t spikes; bool emptied;
};

// everything one compactor needs for its own edge pipeline
struct Channel {
  SimSensor sim;
  float rawBuf[WIN], filtBuf[WIN];
  int nSamples = 0, head = 0, sameRaw = 0;
  float lastRaw = NAN, lastStable = NAN, lastStableFill = 0;
  uint32_t lastStableAt = 0;
  uint16_t spikesFiltered = 0;
  bool stuckFlag = false;
  volatile bool truckPending = false;        // set by the MQTT task, handled in loop()
};

Channel ch[NCH];
int selected = 0;
esp_mqtt_client_handle_t mq = nullptr;
volatile bool mqttUp = false;
Preferences prefs;
uint32_t lastSample = 0, lastReport = 0, lastWifiTry = 0;
uint32_t bootNo = 0, counter = 0;
bool offlineDemo = false;
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

float median5(Channel& c) {                  // median of the last 5 raw samples -> kills single spikes
  float v[5];
  int n = min(c.nSamples, 5);
  for (int i = 0; i < n; i++) v[i] = c.rawBuf[(c.head - 1 - i + WIN) % WIN];
  for (int i = 1; i < n; i++) for (int j = i; j > 0 && v[j] < v[j - 1]; j--) { float t = v[j]; v[j] = v[j - 1]; v[j - 1] = t; }
  return v[n / 2];
}

// message the backend can verify: same text on both sides
String canonical(const Reading& r) {
  char w[16], f[16], t[16];
  snprintf(w, sizeof w, "%.1f", r.weight);
  snprintf(f, sizeof f, "%.1f", r.fill);
  if (r.epoch) snprintf(t, sizeof t, "%ld", (long)r.epoch); else strcpy(t, "-");
  return String(DEFS[r.ch].id) + "|" + r.seq + "|" + t + "|" + w + "|" + f;
}

String payload(const Reading& r, bool fromBuffer) {
  char ts[32] = "";
  if (r.epoch) { struct tm g; gmtime_r(&r.epoch, &g); strftime(ts, sizeof ts, "\"ts\":\"%Y-%m-%dT%H:%M:%SZ\",", &g); }
  char out[560];
  snprintf(out, sizeof out,
           "{\"compactor_id\":\"%s\",%s\"weight_kg\":%.1f,\"fill_pct\":%.1f,\"seq\":%lu,\"sig\":\"%s\","
           "\"edge\":{\"quality\":\"%s\",\"spikes_filtered\":%u,\"emptied\":%s,\"from_buffer\":%s,\"buffered\":%d,"
           "\"site\":\"%s\",\"fw\":\"edge-2.0\"}}",
           DEFS[r.ch].id, ts, r.weight, r.fill, (unsigned long)r.seq, hmacHex(canonical(r)).c_str(), r.quality, r.spikes,
           r.emptied ? "true" : "false", fromBuffer ? "true" : "false", bufCount, SITE_ID);
  return String(out);
}

bool online() { return !offlineDemo && WiFi.status() == WL_CONNECTED && mqttUp; }

bool publish(const Reading& r, bool fromBuffer) {
  if (!online()) return false;
  String topic = String("compactor/") + DEFS[r.ch].id + "/reading";
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
    Serial.printf("  -> %s sent from buffer: seq %lu (%d left)\n", DEFS[buf[bufHead].ch].id, (unsigned long)buf[bufHead].seq, bufCount - 1);
    bufHead = (bufHead + 1) % BUF_MAX; bufCount--;
    flash(0, 0, 60, 60);
  }
}

void send(Reading& r) {
  if (publish(r, false)) {
    flash(0, 0, 80, 80);
  } else {
    bufferPush(r);
  }
}

Reading makeReading(int i, float w, float f, const char* quality, bool emptied) {
  Reading r;
  r.ch = i;
  r.seq = bootNo * 100000UL + (++counter);
  r.epoch = timeValid() ? time(nullptr) : 0;
  r.weight = roundf(w * 10) / 10;            // round BEFORE signing so both sides format the same number
  r.fill = roundf(f * 10) / 10;
  strncpy(r.quality, quality, sizeof r.quality - 1); r.quality[sizeof r.quality - 1] = 0;
  r.spikes = ch[i].spikesFiltered;
  r.emptied = emptied;
  return r;
}

// ------------------------------------------------------------------ edge processing (runs at 10 Hz per compactor)
void sampleAndProcess(int i, uint32_t now) {
  Channel& c = ch[i];
  const float CAP = DEFS[i].capacityKg;
  c.sim.step(now);
  float raw = c.sim.rawWeight(now);
  c.sameRaw = (raw == c.lastRaw) ? c.sameRaw + 1 : 0;
  c.lastRaw = raw;
  c.rawBuf[c.head] = raw;
  c.head = (c.head + 1) % WIN;
  if (c.nSamples < WIN) c.nSamples++;
  float m = median5(c);
  if (fabsf(raw - m) > 6 * NOISE_KG && !c.sim.pressOn) { c.spikesFiltered++; Serial.printf("  %s edge: spike %.0f kg filtered out\n", DEFS[i].id, raw); }
  c.filtBuf[(c.head - 1 + WIN) % WIN] = m;

  bool nowStuck = c.sameRaw >= STUCK_SAMPLES;
  if (nowStuck && !c.stuckFlag) Serial.printf("  %s edge: raw samples frozen -> sensor STUCK\n", DEFS[i].id);
  c.stuckFlag = nowStuck;

  // stability: press still + 3 s of filtered samples within 4 sigma
  if (c.nSamples < WIN || c.sim.pressOn) return;
  float lo = 1e9, hi = -1e9, sum = 0;
  for (int k = 0; k < WIN; k++) { lo = min(lo, c.filtBuf[k]); hi = max(hi, c.filtBuf[k]); sum += c.filtBuf[k]; }
  if (hi - lo > 4 * NOISE_KG && !c.stuckFlag) return;
  float stable = sum / WIN, fill = c.sim.fillPct(now);

  // EMPTYING detected on the board -> report immediately
  if (!isnan(c.lastStable) && c.lastStable >= 0.10f * CAP && stable < 0.05f * CAP) {
    Serial.printf("  %s edge: EMPTIED (%.0f kg collected) -> reporting now\n", DEFS[i].id, c.lastStable - stable);
    Reading r = makeReading(i, stable, fill, "OK", true);
    send(r);
    flash(60, 0, 60, 1000);
  }
  c.lastStable = stable; c.lastStableFill = fill; c.lastStableAt = now;
}

void report(int i, uint32_t now) {
  Channel& c = ch[i];
  if (now - c.lastStableAt > 15000 || isnan(c.lastStable)) return;      // press running: nothing stable to send
  const char* q = c.stuckFlag ? "STUCK" : (c.lastStable > 1.05f * DEFS[i].capacityKg ? "OVERLOAD" : "OK");
  Reading r = makeReading(i, c.lastStable, c.lastStableFill, q, false);
  send(r);
}

// ------------------------------------------------------------------ connectivity + truck commands
static void mqttEvent(void*, esp_event_base_t, int32_t id, void* data) {
  esp_mqtt_event_handle_t e = (esp_mqtt_event_handle_t)data;
  if (id == MQTT_EVENT_CONNECTED) {
    mqttUp = true;
    String t = String("site/") + SITE_ID + "/cmd";
    esp_mqtt_client_subscribe_single(mq, t.c_str(), 1);
    Serial.printf("mqtt: connected, listening for trucks on %s\n", t.c_str());
  } else if (id == MQTT_EVENT_DISCONNECTED) {
    if (mqttUp) Serial.println("mqtt: disconnected (will retry)");
    else Serial.println("mqtt: cannot reach broker (is docker compose running? is the laptop IP right? firewall?)");
    mqttUp = false;
  } else if (id == MQTT_EVENT_DATA && e->data_len > 0 && e->data_len < 400) {
    char msg[400]; memcpy(msg, e->data, e->data_len); msg[e->data_len] = 0;
    if (!strstr(msg, "\"empty\"")) return;
    for (int i = 0; i < NCH; i++) {
      char needle[40]; snprintf(needle, sizeof needle, "\"compactor_id\":\"%s\"", DEFS[i].id);
      if (strstr(msg, needle)) ch[i].truckPending = true;              // handled in loop(), not in the MQTT task
    }
  }
}

void mqttStart() {
  static String uri = String("mqtt://") + MQTT_HOST + ":" + MQTT_PORT;
  static String cid = String("edge-") + SITE_ID + "-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  esp_mqtt_client_config_t cfg = {};
  cfg.broker.address.uri = uri.c_str();
  cfg.credentials.client_id = cid.c_str();
  cfg.network.reconnect_timeout_ms = 5000;
  cfg.buffer.size = 1024;                                                 // a signed reading is ~450 bytes
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
  Serial.println("commands: 1/2/3 select compactor · e empty · s spike · k stuck sensor (70 s) · h heavy material · n normal");
  Serial.println("          o offline on/off · ? help.   BOOT button: short = empty selected · hold 2 s = offline on/off");
  Serial.printf("selected: %s (%s)\n", DEFS[selected].id, DEFS[selected].material);
}

void handleInput(uint32_t now) {
  static uint32_t pressedAt = 0;
  static bool wasDown = false;
  bool down = digitalRead(BUTTON_PIN) == LOW;
  Channel& c = ch[selected];
  if (down && !wasDown) pressedAt = now;
  if (!down && wasDown) {
    if (now - pressedAt >= 2000) { offlineDemo = !offlineDemo; Serial.printf("demo: network %s\n", offlineDemo ? "DOWN" : "back"); }
    else if (now - pressedAt > 40) { c.sim.empty(); Serial.printf("demo: %s emptied by hand (no booking)\n", DEFS[selected].id); }
  }
  wasDown = down;
  while (Serial.available()) {
    char k = Serial.read();
    if (k >= '1' && k < '1' + NCH) { selected = k - '1'; Serial.printf("selected: %s (%s)\n", DEFS[selected].id, DEFS[selected].material); }
    else if (k == 'e') { ch[selected].sim.empty(); Serial.printf("demo: %s emptied by hand (no booking)\n", DEFS[selected].id); }
    else if (k == 's') { ch[selected].sim.spikePending = 1; Serial.printf("demo: %s one bad sample (+40 %% capacity)\n", DEFS[selected].id); }
    else if (k == 'k') { ch[selected].sim.stuck(now, ch[selected].lastRaw); Serial.printf("demo: %s sensor frozen for 70 s\n", DEFS[selected].id); }
    else if (k == 'h') { ch[selected].sim.heavy = true; Serial.printf("demo: %s heavy / wet material\n", DEFS[selected].id); }
    else if (k == 'n') { ch[selected].sim.heavy = false; ch[selected].sim.stuckUntil = 0; Serial.printf("demo: %s back to normal\n", DEFS[selected].id); }
    else if (k == 'o') { offlineDemo = !offlineDemo; Serial.printf("demo: network %s\n", offlineDemo ? "DOWN" : "back"); }
    else if (k == '?') help();
  }
}

void updateLed(uint32_t now) {
  if (now < flashUntil) { led(flashR, flashG, flashB); return; }
  bool problem = false;
  for (int i = 0; i < NCH; i++) problem |= ch[i].stuckFlag || ch[i].lastStable > 1.05f * DEFS[i].capacityKg;
  if (problem) led(60, 0, 0);                    // red: sensor problem / overload somewhere
  else if (!online()) led(50, 30, 0);            // yellow: offline, buffering
  else led(0, 25, 0);                            // green: ok
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
  for (int i = 0; i < NCH; i++) ch[i].sim.init(DEFS[i], i);
  Serial.printf("\nEDGE NODE site %s: %d compactors, speed x%d, boot #%lu\n", SITE_ID, NCH, TIME_SCALE, (unsigned long)bootNo);
  help();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");   // UTC clock for timestamps
  mqttStart();                                                            // keeps retrying by itself
}

void loop() {
  uint32_t now = millis();
  handleInput(now);
  keepConnected(now);
  for (int i = 0; i < NCH; i++) if (ch[i].truckPending) {
    ch[i].truckPending = false;
    ch[i].sim.empty();
    Serial.printf("TRUCK: booked pickup at %s -> emptying now\n", DEFS[i].id);
    flash(60, 60, 60, 1500);
  }
  if (now - lastSample >= SAMPLE_MS) { lastSample = now; for (int i = 0; i < NCH; i++) sampleAndProcess(i, now); }
  if (now - lastReport >= REPORT_MS) {
    lastReport = now;
    Serial.printf("[%s|%s|buf %d]", timeValid() ? "clock ok" : "no clock", online() ? "online" : "OFFLINE", bufCount);
    for (int i = 0; i < NCH; i++) {
      Serial.printf("  %s %4.0f kg %3.0f%%", DEFS[i].id, ch[i].lastStable, ch[i].sim.fill);
      report(i, now);
    }
    Serial.println();
  }
  flushBuffer();
  updateLed(now);
  delay(2);
}
