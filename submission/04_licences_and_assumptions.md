# Third-party components, licences and assumptions

Licences as published by each project at the time of writing — **verify before any commercial use**.

## Software and libraries

| Component | Used for | Licence | Commercial-use note |
|---|---|---|---|
| Python 3.12 | backend, analytics | PSF License | none |
| FastAPI | API | MIT | none |
| Uvicorn | API server | BSD-3-Clause | none |
| Pydantic | data validation | MIT | none |
| SQLAlchemy | database access | MIT | none |
| psycopg 3 | PostgreSQL driver | LGPL-3.0 | dynamic linking/use as library is fine; modifications to psycopg itself must be shared |
| NumPy | numerics | BSD-3-Clause | none |
| pandas | data processing | BSD-3-Clause | none |
| PyArrow | Parquet reading | Apache-2.0 | none |
| DuckDB | used by the organisers' engine | MIT | none |
| PyYAML, pytz, tabulate | engine dependencies | MIT | none |
| scikit-learn | training the optional anomaly model | BSD-3-Clause | none |
| skl2onnx | exporting the model to ONNX | Apache-2.0 | none |
| ONNX Runtime | running models in the backend | MIT | none |
| PostgreSQL 16 (local) | database | PostgreSQL License | none |
| Grafana OSS 11 | dashboards | **AGPL-3.0** | if Europress modifies Grafana and offers it as a service, the modified source must be made available; using it unmodified, or Grafana Cloud/Enterprise, avoids this |
| Node-RED 4 | sensor message flows | Apache-2.0 | none |
| Eclipse Mosquitto 2 | MQTT broker | EPL-2.0 / EDL-1.0 | none |
| Adminer | database browser (local only) | Apache-2.0 or GPL-2.0 | local tool only |
| Docker / Docker Compose | running the stack | Apache-2.0 (Engine/Compose); Docker Desktop has its own licence terms | Docker Desktop needs a paid subscription for larger companies |

## Firmware (reference ESP32 node)

| Component | Licence | Note |
|---|---|---|
| Arduino core for ESP32 (Espressif) | LGPL-2.1 | none for use |
| PlatformIO Core | Apache-2.0 | build tool |
| HX711 library (bogde) | MIT | prototype ADC only; production would use an industrial weighing amplifier |
| PubSubClient (knolleary) | MIT | MQTT client |

## Services and data

| Item | Used for | Terms / restriction |
|---|---|---|
| **Europress SMART Material Value Engine v1.0.1** (synthetic dataset, calculators B1/B2/B5/B6, business-case calculator) | data, baselines, scoring | Since AI Hackathon 2026 rules; synthetic, no real Europress data; dataset is **not committed** to our repo |
| CSC Rahti (container cloud) | online demo | CSC terms of use; intended for research/education — commercial production use needs a separate agreement |
| Tiger Cloud / TigerData (managed PostgreSQL) | shared team database | TigerData terms of service; commercial service |
| Claude (Anthropic) | AI coding assistant for code and docs | output reviewed by the team; no customer data used |

No pretrained third-party AI model is included in the product. The optional anomaly model is trained by us on the
synthetic dataset.

## Key assumptions

| Assumption | Type | Where |
|---|---|---|
| Accuracy target σ ≤ 1.5 % of load | derived from simulated value analysis | Part 1 §1 |
| Component costs (€370–920 hardware) | estimate, catalogue-level ranges | Part 1 §3 |
| Weighbridge tickets are shared by some operators | dataset assumption | self-calibration layer 3 |
| Prices, tariffs, credits | **hypothetical** customer–operator terms (synthetic) | whole dataset |
| Realisation shares 20–60 %, buying rule value ≥ 3× fee | **hypothetical** team parameters | Part 3 §3–4 |
| Service price €15 / €25 / €39 per device per month, success fee 20 % | **hypothetical** | Part 3 §4 |
| Operating cost €9 / device / month, onboarding €600 + €200 / device | estimate | Part 3 §4 |

## What remains untested

- Weighing hardware on a real compactor (accuracy, durability, winter, installation time).
- Willingness to pay; operators' willingness to share data or accept disputes.
- Our cockpit on real customer contracts and invoices (only the synthetic dataset was used).
- The online deployment on Rahti + TigerData under real load.
- The reference ESP32 firmware's HTTPS mode on hardware.
