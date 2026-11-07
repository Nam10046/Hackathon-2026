# Edge node — ESP32-C6 (no load cell needed)

The board does the **edge computing** for real. Only the load cell is simulated inside the firmware (no hardware yet).

| On the board | Why it matters |
|---|---|
| Samples the "load cell" 10× per second, **median filter** removes single bad samples | a spike never reaches the cloud, so no false alarm |
| **Weighs only at idle**: press still and the signal stable for 3 s | clean numbers, fewer messages |
| **Stuck sensor**: 5 s of identical raw samples → quality `STUCK` | a frozen sensor is noticed at the source |
| **Emptying** detected on the board → sent at once | exact time, even before the cloud sees it |
| **Offline buffer** (200 readings, with their time) → sent later, oldest first | no data lost when Wi-Fi or the server is down |
| **Signed readings** (HMAC-SHA256 with a device key) → the backend marks them *verified* | proof that nobody changed a weight after it left the compactor |
| **RGB LED**: green ok · blue flash sent · yellow offline/buffering · red sensor problem · purple emptied | you can see the state from across the room |

Data path: board → Wi-Fi → MQTT (laptop port 1883) → Node-RED → backend → Grafana **6 Live sensors**.
No extra libraries: Wi-Fi, MQTT (Espressif esp-mqtt), HMAC (mbedTLS) and the LED driver are part of the ESP32 core.

## 1. Set up (5 min)

1. **Laptop IP:** PowerShell → `ipconfig` → "IPv4 Address" of your Wi-Fi adapter (e.g. `192.168.1.50`).
   The ESP32 and the laptop must be on the **same Wi-Fi**.
2. **Config:** copy `include/config.h.example` to `include/config.h` and fill in Wi-Fi, `MQTT_HOST` (the IP above)
   and a `DEVICE_KEY` (any long random text).
3. **Backend key:** in the project's `.env` add the same key: `DEVICE_KEYS=E1:<your DEVICE_KEY>`, then
   `docker compose up -d backend` (restarts it with the key).
4. **Windows firewall:** the first time, Windows may ask whether Docker can accept connections. Allow it on
   **private networks**; otherwise the board cannot reach MQTT on port 1883.

## 2. Build and flash

Open the folder `firmware/edge_node` in VS Code (PlatformIO). Plug in the board, then:

```powershell
pio run -e esp32c6 -t upload        # ESP32-C6-DevKitC-1, cable in the port marked "UART"
pio run -e esp32c6_usb -t upload    # boards with only the chip's own USB port ("SuperMini"), or the DevKitC "USB" port
pio device monitor                  # see what the board decides (115200)
```
The first build downloads the ESP32-C6 tools (a few minutes). If PlatformIO says
"This board doesn't support arduino framework", the `platform =` line is not the pioarduino one — keep it as in
`platformio.ini`. If uploading fails, hold **BOOT**, press **RST**, release BOOT, and upload again.

## 3. Demo (great for the video)

| Do | You see on the board | You see in Grafana "6 Live sensors" |
|---|---|---|
| wait | green LED, a reading every 10 s, weight rising | weight and fill curves rise |
| press **BOOT** briefly | purple flash, "EMPTIED" in the monitor | an **emptied** alert; the lift model judges it |
| type `s` in the monitor | "spike filtered out" | **nothing** — the board removed it |
| type `k` | red LED, quality STUCK | **sensor stuck** alert after 6 readings |
| **hold BOOT 2 s** (or type `o`), wait 1 min, then again | yellow LED, "kept in buffer" … then "sent from buffer" | the gap fills in with the original times; **offline buffer** counter goes up |
| type `h` | red LED when above capacity | **overload** alert |
| change `DEVICE_KEY` on one side only | — | **signature problems** counter goes up |

Speed: one reading every 10 s and 3 % fill per minute (`REPORT_MS`, `FILL_PCT_PER_MIN` in `config.h`).
A real unit would send every 15–60 minutes.

## 4. From demo to product
- Replace the simulated cell by the 4-channel weight transmitter on RS-485 (Part 1 §7); the edge logic stays.
- The same logic can run inside the SMART controller's firmware; the ESP32 version is a reference and a
  low-cost retrofit box for older compactors. A product needs an industrial board and enclosure (EMC, −25…+40 °C).
- Next: secure boot + flash encryption so the key cannot be read from the chip, TLS to the cloud, and a
  per-device key from production.
