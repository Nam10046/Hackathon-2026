# Third-party components, licences and assumptions

Checked on 6 Nov 2026: Python licences read from the installed package metadata (`pip-licenses`, exact pinned versions in
`backend/`, `analytics/` and `training/requirements.txt`); other items from each project's licence file or official terms page.
Not legal advice — Europress legal should confirm before commercial use.

## Software and libraries

| Component | Used for | Licence | Commercial-use note |
|---|---|---|---|
| Python 3.12 | backend, analytics | PSF License | none |
| FastAPI (+ Starlette) | API | MIT (Starlette: BSD-3-Clause) | none |
| Uvicorn (+ uvloop, httptools, watchfiles, websockets) | API server | BSD-3-Clause (uvloop: MIT / Apache-2.0; others MIT or BSD) | none |
| Pydantic | data validation | MIT | none |
| SQLAlchemy | database access | MIT | none |
| psycopg 3 + psycopg-binary | PostgreSQL driver | LGPL-3.0 (binary wheel bundles libpq: PostgreSQL License, and OpenSSL: Apache-2.0) | using it as a library is fine; changes to psycopg itself must be shared |
| NumPy | numerics | BSD-3-Clause | none |
| pandas | data processing | BSD-3-Clause | none |
| PyArrow | Parquet reading | Apache-2.0 | none |
| DuckDB | used by the organisers' engine | MIT | none |
| PyYAML, pytz, tabulate | engine dependencies | MIT | none |
| scikit-learn (+ SciPy, joblib, threadpoolctl) | training our lift models and the optional anomaly model | BSD-3-Clause | training only, not shipped in the backend |
| skl2onnx, ONNX (+ protobuf) | exporting the models to ONNX | Apache-2.0 (protobuf: BSD-3-Clause) | training only |
| ONNX Runtime (+ flatbuffers, sympy, coloredlogs) | running our models in the backend and cockpit build | MIT (flatbuffers: Apache-2.0; sympy: BSD) | none |
| httpx, pytest | tests only | BSD-3-Clause / MIT | not shipped |
| certifi | TLS root certificates (dependency) | **MPL-2.0** | file-level copyleft: fine unmodified |
| Other small dependencies (anyio, h11, idna, click, python-dateutil, python-dotenv, tzdata, typing_extensions, packaging, annotated-types) | dependencies | MIT, BSD, Apache-2.0 or PSF | none |
| PostgreSQL 16 (`postgres:16-alpine` image) | database | PostgreSQL License | none |
| Grafana OSS 11.3.0 | dashboards | **AGPL-3.0** (since Grafana 8; built-in panels and PostgreSQL data source only, no extra plugins) | if Europress modifies Grafana and offers it as a service, the modified source must be made available; using it unmodified, or Grafana Cloud/Enterprise, avoids this |
| Node-RED 4 | sensor message flows | Apache-2.0 | none |
| Eclipse Mosquitto 2 | MQTT broker | EPL-2.0 / EDL-1.0 | none |
| Adminer | database browser (local only, not deployed to Rahti) | Apache-2.0 or GPL-2.0 | local tool only |
| Container base images (`python:3.12-slim` = Debian, `*-alpine`) | OS layer inside containers | mixed open-source licences incl. GPL (e.g. BusyBox, glibc LGPL) | normal for container use; a product should ship an SBOM per image |
| Docker Engine / Docker Compose | running the stack | Apache-2.0 | none |
| Docker Desktop (our laptops only) | running Docker on Windows | Docker Subscription Service Agreement | free for education and small companies; **paid per user for organisations with > 250 employees or > $10 M revenue** — Europress servers would use Docker Engine or Kubernetes instead |

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
| CSC Rahti (container cloud) | online demo | CSC General Terms of Use; free of charge only for research and education | a commercial service must buy CSC services or run elsewhere (any Kubernetes/OpenShift) |
| Tiger Cloud / TigerData (managed PostgreSQL) | shared team database | TigerData terms of service; commercial service |
| Claude (Anthropic) | AI coding assistant for code and docs | output reviewed by the team; no customer data used |

No pretrained third-party AI model is included in the product. Our two lift models (`models/lift_premature`,
`models/lift_delayed`) and the optional anomaly model are trained by us, only on the synthetic dataset's train months.
The Europress package itself has no separate licence file; we use it under the hackathon rules and do not redistribute it.

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
