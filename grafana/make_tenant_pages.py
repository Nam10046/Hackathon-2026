"""Builds the 7 customer pages and the admin "All customers" page.
    python grafana/make_tenant_pages.py
Customer pages go to backend/app/tenant_dashboards. The backend loads them into each customer's org when it is created.
Customer SQL only ever uses tenant_api.* and the datasource uid tenant-pg."""
import json
import pathlib

ROOT = pathlib.Path(__file__).parent
OUT = ROOT.parent / "backend" / "app" / "tenant_dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "tenant-pg"}
ADMIN_DS = {"type": "grafana-postgresql-datasource", "uid": "compactor-pg"}
GOOD_LOW = [{"color": "green", "value": None}, {"color": "orange", "value": 70}, {"color": "red", "value": 90}]
BLUE = [{"color": "blue", "value": None}]
KG = "suffix: kg"          # Grafana's own mass unit turns 7620 kg into "7.62 Mg"
DEV = "compactor_id IN ($device)"
LOAD = "round(greatest(r.weight_kg / c.capacity_kg * 100, coalesce(r.fill_pct, 0))::numeric, 1)"
VERDICTS = {"ON_TIME": "green", "TOO_EARLY": "orange", "TOO_LATE": "red"}

# Provenance. No physical load cell is connected yet (firmware/edge_node/README.md), so no weight here is "Real".
# When hardware arrives: add a real case to SOURCE_SQL and update LEGEND. Same words as SOURCE in static/assets/ui.js.
LEGEND = ("**Real** = recorded by the system · **Estimated** = calculated with placeholder prices or factors · "
          "**Simulated** = not from physical hardware or a real operator")
SIM = "message LIKE 'Simulated demo:%'"     # written by app/seed_demo.py, no model or rule produced it
ORIGIN = f"CASE WHEN {SIM} THEN 'Simulated' WHEN type LIKE 'ml\\_%' THEN 'AI model' ELSE 'Rule' END"
SOURCE_SQL = """SELECT CASE
  WHEN count(*) = 0 THEN 'No readings yet'
  WHEN bool_and(coalesce(edge_quality, '') = 'simulated') THEN 'SIMULATED: made-up demo history, no device connected'
  WHEN bool_or(seq IS NOT NULL) THEN 'SIMULATED load cell: real ESP32 edge processing, no physical sensor yet'
  ELSE 'SOURCE NOT VERIFIED: readings without a device counter' END AS "Source"
FROM (SELECT edge_quality, seq FROM tenant_api.readings ORDER BY ts DESC LIMIT 100) r"""


class Page:
    def __init__(self, uid, title, intro, ds=DS, time_from="now-7d", device_filter=True, tags=("customer",)):
        self.uid, self.title, self.ds, self.time_from, self.tags = uid, title, ds, time_from, list(tags)
        self.panels, self.y, self.device_filter = [], 0, device_filter
        customer = ds is DS
        self.add({"type": "text", "transparent": True, "title": "", "options": {"mode": "markdown", "content":
                  intro + ("\n\n" + LEGEND if customer else "")}}, 0, 24, 4 if customer else 3)
        self.y = 4 if customer else 3
        if customer:
            self.query("stat", "Where the weights on this page come from", SOURCE_SQL, 0, 24, 3,
                       defaults={"color": {"mode": "fixed", "fixedColor": "#8A5A00"}, "noValue": "No readings yet"},
                       options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/", "values": False}, "colorMode": "background",
                                "graphMode": "none", "textMode": "value", "justifyMode": "center", "text": {"valueSize": 20}})
            self.y += 3

    def add(self, p, x, w, h):
        p["gridPos"] = {"x": x, "y": self.y, "w": w, "h": h}
        p["id"] = len(self.panels) + 1
        self.panels.append(p)
        return p

    def query(self, kind, title, sql, x, w, h, fmt="table", desc="", defaults=None, options=None, overrides=None):
        return self.add({
            "type": kind, "title": title, "description": desc, "datasource": self.ds,
            "targets": [{"refId": "A", "datasource": self.ds, "editorMode": "code", "rawQuery": True, "format": fmt, "rawSql": sql}],
            "fieldConfig": {"defaults": defaults or {}, "overrides": overrides or []}, "options": options or {}}, x, w, h)

    def stats(self, items, h=4):
        w = 24 // len(items)
        for i, (title, sql, unit, steps, desc) in enumerate(items):
            self.query("stat", title, sql, i * w, w, h, desc=desc,
                       defaults={"unit": unit, "noValue": "–", "color": {"mode": "thresholds"},
                                 "thresholds": {"mode": "absolute", "steps": steps or BLUE}},
                       options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                                "colorMode": "background", "graphMode": "none", "textMode": "value", "justifyMode": "center"})
        self.y += h

    def chart(self, title, sql, unit, h=9, x=0, w=24, move=True, desc="", bars=False):
        self.query("timeseries", title, sql, x, w, h, fmt="time_series", desc=desc,
                   defaults={"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 60 if bars else 8, "showPoints": "never",
                                                      "drawStyle": "bars" if bars else "line", "spanNulls": True}},
                   options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}})
        if move:
            self.y += h

    def table(self, title, sql, h=9, x=0, w=24, move=True, overrides=None, desc=""):
        self.query("table", title, sql, x, w, h, desc=desc, overrides=overrides, defaults={"noValue": "–"},
                   options={"showHeader": True, "cellHeight": "sm"})
        if move:
            self.y += h

    def dash(self):
        variables = []
        if self.device_filter:
            q = "SELECT name AS __text, id AS __value FROM tenant_api.compactors ORDER BY id"
            variables = [{"name": "device", "label": "Compactor", "type": "query", "datasource": self.ds, "query": q,
                          "definition": q, "refresh": 1, "multi": True, "includeAll": True,
                          "current": {"text": ["All"], "value": ["$__all"]}, "sort": 1}]
        return {"uid": self.uid, "title": self.title, "tags": self.tags, "timezone": "browser", "schemaVersion": 39, "version": 1,
                "editable": False, "refresh": "30s", "time": {"from": self.time_from, "to": "now"}, "panels": self.panels,
                "templating": {"list": variables}, "annotations": {"list": []},
                "links": [{"type": "dashboards", "tags": self.tags, "asDropdown": False, "title": "Pages", "keepTime": True,
                           "includeVars": False, "targetBlank": False, "icon": "external link"}]}


def colors(column, mapping):
    return {"matcher": {"id": "byName", "options": column}, "properties": [
        {"id": "custom.cellOptions", "value": {"type": "color-background"}},
        {"id": "mappings", "value": [{"type": "value", "options": {k: {"color": v, "index": i} for i, (k, v) in enumerate(mapping.items())}}]}]}


SEVERITY = colors("Severity", {"info": "blue", "warning": "orange", "critical": "red"})
VERDICT = colors("Verdict", VERDICTS)
pages = []

# --- 1 Overview
p = Page("cust-overview", "1 · Overview", "### Your compactors at a glance\nOnly devices that belong to your company are shown.",
         device_filter=False)
p.stats([
    ("Compactors", "SELECT count(*) FROM tenant_api.compactors", "none", None, "Devices connected to your account"),
    ("Weight now (simulated)", "SELECT sum(weight_kg) FROM tenant_api.compactor_status", KG, None, ""),
    ("Material value (estimate)", "SELECT sum(value_eur) FROM tenant_api.compactor_status", "currencyEUR", None,
     "Weight × placeholder price. Positive = you earn, negative = you pay"),
    ("CO₂ saved (estimate)", "SELECT sum(co2_kg) FROM tenant_api.pickups WHERE status = 'done' AND $__timeFilter(done_at)", KG,
     [{"color": "green", "value": None}], "Collected kg × placeholder material factor"),
    ("Warnings, last 24 h", "SELECT count(*) FROM tenant_api.alerts WHERE severity <> 'info' AND ts > now() - interval '24 hours'", "none",
     [{"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 5}], ""),
    ("Next full in (estimate)", "SELECT min(hours_to_full) FROM tenant_api.compactor_status", "h",
     [{"color": "red", "value": None}, {"color": "orange", "value": 12}, {"color": "green", "value": 24}],
     "Straight-line forecast from the filling speed, in site time"),
])
p.table("Compactors now", """SELECT c.name AS "Compactor", c.material AS "Material", s.load_pct AS "Full %", s.weight_kg AS "kg",
  s.value_eur AS "Value € (estimate)", s.hours_to_full AS "Full in h (estimate)", s.last_ts AS "Last reading"
FROM tenant_api.compactors c LEFT JOIN tenant_api.compactor_status s ON s.compactor_id = c.id ORDER BY c.id""", h=7)
p.table("Latest warnings", f"""SELECT ts AS "Time", compactor_id AS "Compactor", severity AS "Severity", {ORIGIN} AS "Origin", message AS "What happened"
FROM tenant_api.alerts WHERE severity <> 'info' ORDER BY ts DESC LIMIT 8""", h=8, overrides=[SEVERITY])
pages.append(p)

# --- 2 Live
p = Page("cust-live", "2 · Live monitoring", "### Weight and fill level\nUpdates by itself every 30 seconds.", time_from="now-24h")
p.query("gauge", "Fill level now (simulated)", f"""SELECT c.name AS metric, s.load_pct AS value
FROM tenant_api.compactor_status s JOIN tenant_api.compactors c ON c.id = s.compactor_id WHERE s.{DEV} ORDER BY c.id""", 0, 24, 7,
        defaults={"unit": "percent", "min": 0, "max": 100, "thresholds": {"mode": "absolute", "steps": GOOD_LOW}},
        options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/^value$/", "values": True}, "showThresholdLabels": False})
p.y += 7
p.chart("Weight (simulated)", f"""SELECT ts AS "time", compactor_id AS metric, weight_kg AS value
FROM tenant_api.readings WHERE $__timeFilter(ts) AND {DEV} ORDER BY 1""", KG)
p.table("Latest readings", f"""SELECT ts AS "Time", compactor_id AS "Compactor", weight_kg AS "kg", fill_pct AS "Fill %", edge_quality AS "Quality"
FROM tenant_api.readings WHERE {DEV} ORDER BY ts DESC LIMIT 20""", h=8)
pages.append(p)

# --- 3 Value
p = Page("cust-value", "3 · Material value", "### What your waste could be worth\nMaterial value minus lift fees. Prices and fees are placeholders until your contract is entered.",
         time_from="now-30d")
done = f"FROM tenant_api.pickups WHERE status = 'done' AND $__timeFilter(done_at) AND {DEV}"
p.stats([
    ("Material value (estimate)", f"SELECT sum(value_eur) {done}", "currencyEUR", None, ""),
    ("Lift fees (placeholder)", f"SELECT sum(fee_eur) {done}", "currencyEUR", None, ""),
    ("Net result (estimate)", f"SELECT sum(net_eur) {done}", "currencyEUR", None, "Value minus fees"),
    ("Claims on simulated invoices", f"SELECT sum(claim_eur) {done}", "currencyEUR", [{"color": "green", "value": None}, {"color": "orange", "value": 1}],
     "No real operator invoice exists here. Shows how the check would work."),
])
p.chart("Net per day (estimate)", f"""SELECT date_trunc('day', done_at) AS "time", compactor_id AS metric, sum(net_eur) AS value {done} GROUP BY 1, 2 ORDER BY 1""",
        "currencyEUR", bars=True)
p.table("Invoice check (simulated invoices)", f"""SELECT done_at AS "Time", compactor_id AS "Compactor", kg_collected AS "Collected kg", invoice_kg AS "Simulated invoice kg",
  invoice_check AS "Problem", claim_eur AS "Simulated claim €" {done} AND invoice_check <> 'OK' ORDER BY done_at DESC""", h=8)
pages.append(p)

# --- 4 CO2
p = Page("cust-co2", "4 · CO₂ impact", "### Your recycling impact\nCO₂ figures are estimates: collected kg × a placeholder factor per material.", time_from="now-30d")
p.stats([
    ("CO₂ saved (estimate)", f"SELECT sum(co2_kg) {done}", KG, [{"color": "green", "value": None}], ""),
    ("Waste collected (simulated)", f"SELECT sum(kg_collected) {done}", KG, None, ""),
    ("Lifts", f"SELECT count(*) {done}", "none", None, ""),
    ("kg per lift", f"SELECT avg(kg_collected) {done}", KG, None, "Fuller lifts mean fewer truck trips"),
])
p.chart("CO₂ saved per day (estimate)", f"""SELECT date_trunc('day', done_at) AS "time", compactor_id AS metric, sum(co2_kg) AS value {done} GROUP BY 1, 2 ORDER BY 1""",
        KG, bars=True)
p.table("By material", f"""SELECT c.material AS "Material", sum(p.kg_collected) AS "kg collected", sum(p.co2_kg) AS "CO₂ saved kg (estimate)", m.co2_factor AS "Placeholder factor"
FROM tenant_api.pickups p JOIN tenant_api.compactors c ON c.id = p.compactor_id JOIN tenant_api.materials m ON m.name = c.material
WHERE p.status = 'done' AND $__timeFilter(p.done_at) AND p.{DEV} GROUP BY 1, 4 ORDER BY 3 DESC""", h=6)
pages.append(p)

# --- 5 AI
ML = "type LIKE 'ml\\_%'"
p = Page("cust-ai", "5 · AI anomaly detection", "### What the AI and the safety rules found\nThe Origin column shows what produced each finding.")
al = f"FROM tenant_api.alerts WHERE $__timeFilter(ts) AND {DEV}"
p.stats([
    ("AI model findings", f"SELECT count(*) {al} AND {ML} AND NOT {SIM}", "none", None, "Output of the trained models, on simulated weights"),
    ("Rule findings", f"SELECT count(*) {al} AND severity <> 'info' AND NOT {ML} AND NOT {SIM}", "none", None, "Fixed safety rules: sensor faults, density"),
    ("Simulated examples", f"SELECT count(*) {al} AND {SIM}", "none", [{"color": "#8A5A00", "value": None}], "Written by the demo seed. No model or rule produced these."),
])
p.chart("Findings per day", f"""SELECT date_trunc('day', ts) AS "time", {ORIGIN} AS metric, count(*) AS value {al} AND severity <> 'info' GROUP BY 1, 2 ORDER BY 1""",
        "none", bars=True)
p.table("All findings", f"""SELECT ts AS "Time", compactor_id AS "Compactor", severity AS "Severity", {ORIGIN} AS "Origin", type AS "Type", message AS "What happened"
{al} AND severity <> 'info' ORDER BY ts DESC LIMIT 100""", h=10, overrides=[SEVERITY])
pages.append(p)

# --- 6 Forecast
p = Page("cust-forecast", "6 · Fill forecast", "### When will each compactor be full?\nAn estimate from the filling speed since the last emptying, in site time: in fast demo mode 1 real minute is 1 site hour.", time_from="now-3d")
p.table("Forecast (estimate)", f"""SELECT c.name AS "Compactor", s.load_pct AS "Full %", c.on_call_threshold_pct AS "Truck ordered at %",
  s.hours_to_full AS "Full in site hours (estimate)"
FROM tenant_api.compactors c JOIN tenant_api.compactor_status s ON s.compactor_id = c.id WHERE c.id IN ($device) ORDER BY s.hours_to_full NULLS LAST""", h=7)
p.chart("Fill level (simulated)", f"""SELECT r.ts AS "time", r.compactor_id AS metric, {LOAD} AS value
FROM tenant_api.readings r JOIN tenant_api.compactors c ON c.id = r.compactor_id WHERE $__timeFilter(r.ts) AND r.{DEV} ORDER BY 1""", "percent", h=10)
pages.append(p)

# --- 7 Pickups
p = Page("cust-pickups", "7 · Pickups", "### Pickup schedule and history\nThe booking and judging logic is real. Trucks and operator invoices are simulated.", time_from="now-30d")
p.stats([
    ("Open pickups (simulated trucks)", f"SELECT count(*) FROM tenant_api.pickups WHERE status IN ('booked', 'scheduled') AND {DEV}", "none", None, ""),
    ("On time", f"SELECT count(*) {done} AND verdict = 'ON_TIME'", "none", [{"color": "green", "value": None}], ""),
    ("Too early", f"SELECT count(*) {done} AND verdict = 'TOO_EARLY'", "none", [{"color": "green", "value": None}, {"color": "orange", "value": 1}], "A paid lift for a part-full container"),
    ("Too late", f"SELECT count(*) {done} AND verdict = 'TOO_LATE'", "none", [{"color": "green", "value": None}, {"color": "red", "value": 1}], "Overflow risk"),
])
p.table("Upcoming", f"""SELECT compactor_id AS "Compactor", status AS "Status", kind AS "Type", booked_at AS "Booked", booked_load_pct AS "Booked at %", truck_due AS "Truck due"
FROM tenant_api.pickups WHERE status IN ('booked', 'scheduled') AND {DEV} ORDER BY truck_due NULLS LAST""", h=6)
p.table("History", f"""SELECT done_at AS "Emptied", compactor_id AS "Compactor", verdict AS "Verdict", load_before_pct AS "Full %", kg_collected AS "kg",
  net_eur AS "Net € (estimate)", co2_kg AS "CO₂ kg (estimate)", invoice_check AS "Simulated invoice", verdict_reason AS "Why" {done} ORDER BY done_at DESC LIMIT 200""", h=11, overrides=[VERDICT])
pages.append(p)

OUT.mkdir(exist_ok=True)
for i, p in enumerate(pages, 1):
    (OUT / f"{i}_{p.uid}.json").write_text(json.dumps(p.dash(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

# --- Admin: every customer (org 1, the existing admin datasource)
a = Page("admin-customers", "Admin · All customers", "### Every customer on the platform\nAdmins only. Approve new customers in the [portal](http://localhost:8000/portal).",
         ds=ADMIN_DS, device_filter=False, tags=("admin",), time_from="now-7d")
a.stats([
    ("Customers", "SELECT count(*) FROM tenants WHERE status = 'active'", "none", None, ""),
    ("Waiting for approval", "SELECT count(*) FROM users WHERE status = 'pending'", "none",
     [{"color": "green", "value": None}, {"color": "orange", "value": 1}], ""),
    ("Devices with an owner", "SELECT count(*) FROM tenant_devices", "none", None, ""),
    ("Devices without an owner", "SELECT count(*) FROM compactors c LEFT JOIN tenant_devices d ON d.compactor_id = c.id WHERE d.compactor_id IS NULL", "none", None,
     "Only admins see these"),
])
a.table("Customers", """SELECT t.name AS "Customer", t.status AS "Status", count(d.compactor_id) AS "Devices",
  (SELECT count(*) FROM users u WHERE u.tenant_id = t.id) AS "Users", sum(s.weight_kg) AS "kg now", sum(s.value_eur) AS "Value €"
FROM tenants t LEFT JOIN tenant_devices d ON d.tenant_id = t.id LEFT JOIN compactor_status s ON s.compactor_id = d.compactor_id
GROUP BY t.id, t.name, t.status ORDER BY t.name""", h=7)
a.table("Devices and owners", """SELECT c.id AS "Device", c.name AS "Name", coalesce(t.name, '(no owner)') AS "Customer", s.load_pct AS "Full %", s.last_ts AS "Last reading"
FROM compactors c LEFT JOIN tenant_devices d ON d.compactor_id = c.id LEFT JOIN tenants t ON t.id = d.tenant_id
LEFT JOIN compactor_status s ON s.compactor_id = c.id ORDER BY 3, 1""", h=9)
a.chart("Readings per customer", """SELECT date_trunc('hour', r.ts) AS "time", coalesce(t.name, '(no owner)') AS metric, count(*) AS value
FROM readings r LEFT JOIN tenant_devices d ON d.compactor_id = r.compactor_id LEFT JOIN tenants t ON t.id = d.tenant_id
WHERE $__timeFilter(r.ts) GROUP BY 1, 2 ORDER BY 1""", "none")
(ROOT / "dashboards" / "admin_customers.json").write_text(json.dumps(a.dash(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {len(pages)} customer pages and the admin page")
