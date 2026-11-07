# Handoff — state on Sat 7 Nov 2026, 18:10 (deadline 22:00 today)

Read this first, then README.md, CONTRACT.md, firmware/edge_node/README.md.

## What exists (commit deac81c on branch feature/compactor-framework, NOT pushed yet)
- **Live product, fed only by the ESP32-C6 edge node** (firmware/edge_node): one board runs a site with 3 compactors
  (C1 cardboard 2000 kg, C2 plastic 1500 kg, C3 mixed 4000 kg), fast mode TIME_SCALE=60 (1 real min = 1 site hour).
  Per compactor: 10 Hz sampling, median spike filter, stable weighing, stuck detection, emptying detection, offline
  buffer, HMAC-signed readings. Listens for truck commands on MQTT `site/S1/cmd`.
- **Backend pickups loop** (backend/app/pickups.py): book truck at on-call % -> command to board when due ->
  board empties -> pickup judged ON_TIME / TOO_EARLY / TOO_LATE, priced (value - fee), CO2, simulated operator invoice
  checked vs measured kg (claims). Demo realism via DEMO_P_* env (late trucks, old fixed route, wrong invoices).
  Fast mode stretches time for the lift model + forecast (service._stretch).
- **Node-RED**: backend response `commands` -> MQTT `site/<id>/cmd`.
- **Grafana**: Live section (uids smart-compactor, live-pickups, live-money, edge-live) built by
  `grafana/make_cockpit_pages.py` then `grafana/make_live_pages.py`. Europress dataset pages 1-5 = Analysis section.
- Tests: `cd backend && python -m pytest -q` -> 24 pass. All live-page SQL was checked against Postgres 16.

## The board (IMPORTANT)
- Secure Boot V2 + flash encryption (dev mode) are burned in eFuses. A normal PlatformIO upload breaks booting.
- Always flash with `firmware/edge_node/secure_flash.ps1` (default env esp32c6_secure). It checks the key digest,
  signs bootloader + app, writes with `--encrypt`. Needs `$env:SB_KEY` = path of the signing key (outside the repo:
  C:\Users\Nam\Desktop\Thesis_NamTon\hello_world\secure_boot_signing_key.pem). Never commit keys.
- NEVER run any `espefuse burn-*` command.
- COM4 "Access is denied" = a serial monitor is still open. Close it first.
- Board on laptop hotspot "LEGION-7-SUPERV 7789" (2.4 GHz), broker at 192.168.137.1:1883, firewall rule for TCP 1883.

## Next steps
1. `git push origin feature/compactor-framework`
2. `docker compose up -d --force-recreate backend nodered grafana`
3. `docker compose exec backend python -m app.reset_live`   (wipes old simulated readings; ESP32 = only source)
4. close serial monitors, then `cd firmware\edge_node; powershell -ExecutionPolicy Bypass -File .\secure_flash.ps1 -NoBuild`
   (new firmware is already built + signed; drop -NoBuild after code changes)
5. monitor: `pio device monitor -e esp32c6_secure` -> expect "EDGE NODE site S1: 3 compactors" and
   "listening for trucks on site/S1/cmd"
6. check Grafana http://localhost:3000 Live pages; first pickups appear after ~5-20 min (fast mode)
7. record the demo video; open the PR and merge

## Never commit
.env, firmware/edge_node/include/config.h (Wi-Fi password, device key), *.pem, .pio/
