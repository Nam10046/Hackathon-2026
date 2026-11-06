# Put the server on CSC Rahti (so the whole team can use it)

## What runs where

| | Laptop (`docker compose`) | Rahti (cloud) |
|---|---|---|
| Backend (API + AI) | ✅ | ✅ `https://compactor-api-<project>.2.rahtiapp.fi/docs` |
| Grafana dashboard | ✅ | ✅ `https://compactor-grafana-<project>.2.rahtiapp.fi` |
| PostgreSQL | ✅ | ✅ (Rahti template, internal only) |
| Mosquitto + Node-RED | ✅ | ❌ — Rahti only lets **HTTP/HTTPS** in from outside, so no MQTT |
| Adminer | ✅ | ❌ — would put the database on the internet |

On Rahti the ESP32 sends readings by **HTTPS** to the backend (see `firmware/.../config.h.example`, option B),
with a secret **API key** so strangers can't send fake data. Reading the API and Grafana is open.

## Before you start (once)

1. **CSC project with Rahti:** my.csc.fi → your project → *Services* → add **Rahti**.
2. **Install `oc`** (the Rahti command line tool): open https://rahti.csc.fi → log in →
   **?** (top right) → *Command Line Tools* → download `oc` for Windows → put `oc.exe` in a folder on your PATH.
3. **Commit your work.** `--from-repo=.` builds from your latest *commit*, not unsaved changes.

## Deploy (PowerShell, in the repo folder)

**1. Log in** — Rahti web console → your name (top right) → *Copy login command* → paste:
```powershell
oc login https://api.2.rahti.csc.fi:6443 --token=<your-token>
```

**2. Create a Rahti project** (the description must contain your CSC project number):
```powershell
oc new-project compactor-hackathon --description="csc_project: <your CSC project number>"
```

**3. Database** (Rahti's ready-made PostgreSQL, with a 1 GB disk). Pick your own password:
```powershell
oc new-app --template=postgresql-persistent `
  -p DATABASE_SERVICE_NAME=postgres `
  -p POSTGRESQL_USER=compactor `
  -p POSTGRESQL_PASSWORD=<db-password> `
  -p POSTGRESQL_DATABASE=compactor `
  -p VOLUME_CAPACITY=1Gi
```

**4. Secrets** — the API key for the sensor + the Grafana admin password:
```powershell
$key = -join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object {[char]$_})
oc create secret generic compactor-secrets `
  --from-literal=ingest-api-key=$key `
  --from-literal=grafana-admin-password=<grafana-password>
echo "API key: $key"      # save it — the ESP32 and Node-RED need it
```

**5. Create everything else, then build the images from your repo:**
```powershell
oc apply -f deploy/rahti/rahti.yaml
oc start-build backend --from-repo=. --follow
oc start-build grafana --from-repo=. --follow
```

**6. Get the links** and share them with the team:
```powershell
oc get routes
```

**7. Test** — send one reading:
```powershell
$api = "https://" + (oc get route compactor-api -o jsonpath='{.spec.host}')
Invoke-RestMethod -Method Post -Uri "$api/api/readings" -ContentType "application/json" `
  -Headers @{ "X-API-Key" = $key } -Body '{"compactor_id":"C1","weight_kg":800,"fill_pct":50}'
```
Then open the Grafana link — C1 shows 800 kg.

## Update after new code is merged
```powershell
git checkout main; git pull
oc start-build backend --from-repo=. --follow     # backend / AI / models changed
oc start-build grafana --from-repo=. --follow     # dashboard changed
```
The new version goes live automatically when the build finishes.

## Give teammates access to Rahti (only people who deploy)
Everyone can open the links without access. To let someone run `oc` commands:
```powershell
oc policy add-role-to-user edit <their-csc-username>
```

## Handy commands
```powershell
oc get pods                      # what is running
oc logs -f deployment/backend    # backend messages
oc rollout restart deployment/backend
oc port-forward svc/postgres 5433:5432   # look in the database from your laptop (DBeaver: localhost:5433)
```

## Troubleshooting
- **Pod "CrashLoopBackOff":** `oc logs deployment/backend` — often a wrong DB password/secret name.
- **Build fails:** `oc logs -f bc/backend`. Did you commit?
- **`postgresql-persistent` not found:** add PostgreSQL in the web console → *+Add* → *Developer Catalog* → *PostgreSQL*, service name `postgres`.
- **Security note:** no `seccompProfile` is set in our files — that's what Rahti wants since its 10 Nov 2026 change.
