"""Builds the LIVE PRODUCT pages (data only from the ESP32 edge node, nothing from the dataset):
  Site now (uid smart-compactor = home page) · Pickups · Money & CO2 · Devices
Run:  python grafana/make_live_pages.py      (after make_cockpit_pages.py; Grafana reloads the files by itself)

CAREFUL: grafana/dashboards is mounted into Grafana, so writing there changes the running dashboards within seconds.
To try a page without touching them, write somewhere else:
  DEMO_TIME_SCALE=60 python grafana/make_live_pages.py --out grafana/candidates --only live_pickups
DEMO_TIME_SCALE from the environment wins over .env, so a laptop on real time cannot change the committed demo speed."""
import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from make_cockpit_pages import menu_panel  # noqa: E402

DS = {"type": "grafana-postgresql-datasource", "uid": "compactor-pg"}
ROOT = pathlib.Path(__file__).parent
SCALE = float(os.environ["DEMO_TIME_SCALE"]) if os.getenv("DEMO_TIME_SCALE") else \
    float(next((l.split("=", 1)[1] for l in (ROOT.parent / ".env").read_text().splitlines()
                if l.startswith("DEMO_TIME_SCALE=")), "60")) if (ROOT.parent / ".env").exists() else 60.0
LOAD = "greatest(r.weight_kg / c.capacity_kg * 100, coalesce(r.fill_pct, 0))"
VERDICT_COLORS = {"ON_TIME": "green", "TOO_EARLY": "orange", "TOO_LATE": "red", "booked": "blue", "scheduled": "purple"}
# what the verdicts are called on the pages (the database keeps ON_TIME / TOO_EARLY / TOO_LATE, see CONTRACT.md)
# = the rules in backend/app/pickups.py: TOO_EARLY below on-call (80 %) - 20 points, TOO_LATE full (>= 98 %) for 2+ site h
LABEL = {"ON_TIME": "≥60%", "TOO_EARLY": "<60%", "TOO_LATE": "Full 2h+"}
LABEL_COLORS = {LABEL[k]: VERDICT_COLORS[k] for k in LABEL}
LABEL_SQL = "CASE verdict " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in LABEL.items()) + " ELSE verdict END"
# the booking panel is a page served by the backend, opened by the viewer's browser (so: the address the browser sees)
API_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8000")
# LIVE estimate of one pickup p with the customer's 2 numbers in m (= backend app/pickups.costs)
LIFT = "coalesce(m.lift_fee_eur, p.fee_eur, 0)"                 # cost per lift
VALUE = "(p.kg_collected * m.price_eur_per_kg)"                  # + earned / - paid
TOTAL = f"({LIFT} - {VALUE})"                                    # total cost of the pickup


class Page:
    def __init__(self, uid, title, intro, time_from="now-30m", refresh="5s", intro_h=2):
        self.uid, self.title, self.time_from, self.refresh = uid, title, time_from, refresh
        self.panels, self.y, self.annotations, self.links = [menu_panel(uid)], 2, [], []
        self.text(intro, h=intro_h)

    def _add(self, p, w, h, x=None):
        self.panels.append(p)
        p["id"] = len(self.panels) + 100
        return p

    def panel(self, kind, title, x, y, w, h, sql, fmt="table", desc=""):
        sqls = sql if isinstance(sql, list) else [sql]
        p = {"type": kind, "title": title, "datasource": DS, "description": desc, "gridPos": {"x": x, "y": y, "w": w, "h": h},
             "targets": [{"refId": chr(65 + i), "datasource": DS, "editorMode": "code", "rawQuery": True, "format": fmt, "rawSql": q}
                         for i, q in enumerate(sqls)],
             "fieldConfig": {"defaults": {}, "overrides": []}, "options": {}}
        return self._add(p, w, h)

    def text(self, md, h=3, title="", x=0, w=24, move=True):
        self._add({"type": "text", "title": title, "transparent": not title, "gridPos": {"x": x, "y": self.y, "w": w, "h": h},
                   "options": {"mode": "markdown", "content": md}}, w, h)
        if move:
            self.y += h

    def stats(self, items, h=4, color_mode="background", no_value="–"):
        n = len(items)
        widths = [24 // n + (1 if i < 24 % n else 0) for i in range(n)]
        for i, (title, sql, unit, steps, desc) in enumerate(items):
            p = self.panel("stat", title, sum(widths[:i]), self.y, widths[i], h, sql, desc=desc)
            p["fieldConfig"]["defaults"] = {"unit": unit or "none", "decimals": 0 if unit in (None, "none", "short") else None,
                                            "color": {"mode": "thresholds"}, "noValue": no_value,
                                            "thresholds": {"mode": "absolute", "steps": steps or [{"color": "blue", "value": None}]}}
            p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                            "colorMode": color_mode, "graphMode": "none", "textMode": "value", "justifyMode": "center"}
        self.y += h

    def status(self, title, sql, x, w, h=3, warn=None, desc=""):
        """A sentence computed by SQL. Says what the page can and cannot show, so an empty panel is never a mystery."""
        p = self.panel("stat", title, x, self.y, w, h, sql, desc=desc)
        p["fieldConfig"]["defaults"] = {"noValue": "Data unavailable", "color": {"mode": "fixed", "fixedColor": "text"}}
        if warn:   # amber only when the sentence really is a warning
            p["fieldConfig"]["defaults"]["mappings"] = [{"type": "regex", "options": {"pattern": warn, "result": {"color": "#D79A32", "index": 0}}}]
        p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/", "values": False}, "colorMode": "value",
                        "graphMode": "none", "textMode": "value", "justifyMode": "auto", "text": {"valueSize": 17}}
        return p

    def dash(self):
        return {"uid": self.uid, "title": self.title, "tags": ["live", "esp32"], "timezone": "browser", "schemaVersion": 39,
                "version": 1, "refresh": self.refresh, "time": {"from": self.time_from, "to": "now"}, "panels": self.panels,
                "templating": {"list": []}, "links": self.links, "annotations": {"list": self.annotations}}


def color_col(name, mapping):
    return {"matcher": {"id": "byName", "options": name}, "properties": [
        {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
        {"id": "mappings", "value": [{"type": "value", "options": {k: {"color": v, "index": i} for i, (k, v) in enumerate(mapping.items())}}]}]}


def text_col(name, mapping):
    """Coloured words on the normal background: calmer than filling the cell. mapping: value -> (colour, text)."""
    return {"matcher": {"id": "byName", "options": name}, "properties": [
        {"id": "custom.cellOptions", "value": {"type": "color-text"}},
        {"id": "mappings", "value": [{"type": "value", "options": {k: {"color": c, "text": t, "index": i}
                                                                   for i, (k, (c, t)) in enumerate(mapping.items())}}]}]}


GOOD = [{"color": "green", "value": None}]
pickup_anno = {"datasource": DS, "enable": True, "name": "Pickups", "iconColor": "purple",
               "target": {"refId": "Anno", "datasource": DS, "editorMode": "code", "rawQuery": True, "format": "table",
                          "rawSql": "SELECT done_at AS time, compactor_id || ' emptied: ' || verdict || ' (' || round(kg_collected) || ' kg)' AS text, "
                                    "compactor_id AS tags FROM pickups WHERE status = 'done' AND $__timeFilter(done_at)"}}

# ======================================================================== 1. SITE NOW
pg = Page("smart-compactor", "Live 1 · Site now",
          f"### Site S1 — live from the ESP32 edge node &nbsp;·&nbsp; 3 compactors &nbsp;·&nbsp; "
          f"**demo speed: 1 real minute = {SCALE:.0f} site minutes**" if SCALE != 1 else "### Site S1 — live from the ESP32 edge node")
pg.annotations.append(pickup_anno)
pg.stats([
    ("Need a truck", "SELECT count(*) FROM compactors c JOIN compactor_status s ON s.compactor_id = c.id "
     "WHERE s.load_pct >= coalesce(c.on_call_threshold_pct, 80) AND NOT EXISTS (SELECT 1 FROM pickups p "
     "WHERE p.compactor_id = c.id AND p.status = 'booked')", "short", [{"color": "green", "value": None}, {"color": "orange", "value": 1}],
     "Over the on-call level and no truck booked yet: press Book truck below"),
    ("Trucks on the way", "SELECT count(*) FROM pickups WHERE status = 'booked'", "short", None, "Booked by a person, not arrived yet"),
    ("Next truck in (site h)", f"SELECT round((extract(epoch FROM min(truck_due) - now()) / 3600 * {SCALE})::numeric, 1) FROM pickups "
     "WHERE status = 'booked' AND cmd_sent_at IS NULL", "none", None, "Site hours until the next booked truck arrives"),
    ("Pickups (last 24 site h)", f"SELECT count(*) FROM pickups WHERE status = 'done' AND done_at > now() - interval '{24 / SCALE * 60:.0f} minutes'",
     "short", None, ""),
    ("Pickups at ≥60%", "SELECT round(100.0 * count(*) FILTER (WHERE verdict = 'ON_TIME') / NULLIF(count(*), 0)) FROM pickups WHERE status = 'done'",
     "percent", [{"color": "red", "value": None}, {"color": "orange", "value": 60}, {"color": "green", "value": 85}], "Share of all lifts emptied at 60 % or more and not left full for 2+ site h"),
])
pg._add({"type": "text", "title": "Book a truck — the system only warns at the on-call level, a person decides",
         "gridPos": {"x": 0, "y": pg.y, "w": 24, "h": 8},
         "options": {"mode": "html", "content": f'<iframe src="{API_URL}/book" title="Book a truck" '
                                                f'style="width:100%;height:230px;border:0;display:block"></iframe>'}}, 24, 8)
pg.y += 8
p = pg.panel("bargauge", "Load now", 0, pg.y, 8, 9,
             f"SELECT c.id || ' ' || c.material AS \"Compactor\", s.load_pct AS \"Load\" FROM compactors c "
             f"LEFT JOIN compactor_status s ON s.compactor_id = c.id ORDER BY c.id")
p["fieldConfig"]["defaults"] = {"unit": "percent", "min": 0, "max": 100, "thresholds": {"mode": "absolute", "steps": [
    {"color": "green", "value": None}, {"color": "orange", "value": 80}, {"color": "red", "value": 98}]}}
p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True}, "orientation": "horizontal",
                "displayMode": "lcd", "showUnfilled": True, "valueMode": "color"}
p = pg.panel("timeseries", "Load over time (%) — dashed = on-call 80 %, purple marks = pickups", 8, pg.y, 16, 9,
             f"SELECT r.ts AS time, r.compactor_id AS metric, round(({LOAD})::numeric, 1) AS load FROM readings r "
             f"JOIN compactors c ON c.id = r.compactor_id WHERE $__timeFilter(r.ts) ORDER BY 1", fmt="time_series")
p["fieldConfig"]["defaults"] = {"unit": "percent", "min": 0, "max": 105, "custom": {
    "lineWidth": 2, "showPoints": "never", "spanNulls": 60000, "thresholdsStyle": {"mode": "dashed"}},
    "thresholds": {"mode": "absolute", "steps": [{"color": "transparent", "value": None}, {"color": "orange", "value": 80},
                                                 {"color": "red", "value": 100}]}}
pg.y += 9
p = pg.panel("table", "Trucks: booked and on the way", 0, pg.y, 10, 8,
             f"SELECT id AS \"#\", compactor_id AS \"Compactor\", kind AS \"Who\", status AS \"Status\", "
             f"booked_load_pct AS \"Booked at %\", "
             f"CASE WHEN cmd_sent_at IS NOT NULL THEN 'arrived' ELSE round((extract(epoch FROM truck_due - now()) / 3600 * {SCALE})::numeric, 1)::text || ' h' END AS \"Arrives in (site)\", "
             f"CASE WHEN truck_late THEN 'late' ELSE '' END AS \"Note\" "
             f"FROM pickups WHERE status IN ('booked', 'scheduled') ORDER BY id DESC",
             desc="'scheduled' = the old fixed route will still come at a set load, without looking at the sensor")
p["fieldConfig"]["overrides"] = [color_col("Status", VERDICT_COLORS)]
p = pg.panel("table", "What happened (all decisions, newest first)", 10, pg.y, 14, 8,
             "SELECT ts AS \"Time\", compactor_id AS \"Compactor\", type AS \"Event\", message AS \"What\" FROM alerts "
             "WHERE $__timeFilter(ts) AND type <> 'invoice_mismatch' ORDER BY ts DESC, id DESC LIMIT 60")
p["fieldConfig"]["overrides"] = [{"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.width", "value": 150}]},
                                 {"matcher": {"id": "byName", "options": "Compactor"}, "properties": [{"id": "custom.width", "value": 90}]},
                                 {"matcher": {"id": "byName", "options": "Event"}, "properties": [{"id": "custom.width", "value": 160}]}]
pg.y += 8
pg.text("**How it works:** the board measures (stable weight, spikes removed, signed). At the on-call % the system **warns** "
        "(*pickup_needed*) — it does not book. A **person presses Book truck**. When the truck arrives, the system tells the board "
        "over MQTT; the board **detects the emptying itself**. Every lift is then **judged** (≥60% / <60% / Full 2h+) and its "
        "**CO₂** counted. Some trucks are late and the old fixed route sometimes comes early — on purpose, so you see every case.", h=3)
site = pg.dash()

# ======================================================================== 2. PICKUPS
pg = Page("live-pickups", "Live 2 · Pickups",
          "### Every lift, judged — from the board's own emptying detection", time_from="now-6h", refresh="10s")
pg.annotations.append(pickup_anno)
done = "status = 'done' AND $__timeFilter(done_at)"
pg.stats([
    ("Pickups", f"SELECT count(*) FROM pickups WHERE {done}", "short", None, ""),
    (LABEL["ON_TIME"], f"SELECT count(*) FROM pickups WHERE {done} AND verdict = 'ON_TIME'", "short", GOOD, "On time: emptied at 60 % or more"),
    (LABEL["TOO_EARLY"], f"SELECT count(*) FROM pickups WHERE {done} AND verdict = 'TOO_EARLY'", "short",
     [{"color": "green", "value": None}, {"color": "orange", "value": 1}], "Emptied well below the on-call level"),
    (LABEL["TOO_LATE"], f"SELECT count(*) FROM pickups WHERE {done} AND verdict = 'TOO_LATE'", "short",
     [{"color": "green", "value": None}, {"color": "red", "value": 1}], "Full for 2+ site hours before the truck came"),
    ("Avg load at pickup", f"SELECT round(avg(load_before_pct)) FROM pickups WHERE {done}", "percent",
     [{"color": "red", "value": None}, {"color": "orange", "value": 60}, {"color": "green", "value": 80}], "Higher = fewer trucks for the same waste"),
])
p = pg.panel("barchart", "Verdict per compactor", 0, pg.y, 8, 9,
             f"SELECT p.compactor_id || ' ' || c.material AS \"Compactor\", "
             f"count(*) FILTER (WHERE verdict = 'ON_TIME') AS \"{LABEL['ON_TIME']}\", count(*) FILTER (WHERE verdict = 'TOO_EARLY') AS \"{LABEL['TOO_EARLY']}\", "
             f"count(*) FILTER (WHERE verdict = 'TOO_LATE') AS \"{LABEL['TOO_LATE']}\" FROM pickups p JOIN compactors c ON c.id = p.compactor_id "
             f"WHERE p.{done.replace('$__timeFilter(done_at)', '$__timeFilter(p.done_at)')} GROUP BY 1 ORDER BY 1")
p["options"] = {"stacking": "normal", "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}, "xTickLabelRotation": 0}
p["fieldConfig"]["overrides"] = [{"matcher": {"id": "byName", "options": k}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": v}}]}
                                 for k, v in LABEL_COLORS.items()]
p = pg.panel("barchart", "Who sent the truck", 8, pg.y, 8, 9,
             f"SELECT CASE kind WHEN 'booked' THEN 'Booked by a person' WHEN 'fixed_route' THEN 'Old fixed route' ELSE 'By hand' END AS \"Who\", "
             f"round(avg(load_before_pct)) AS \"Avg load at pickup %\" FROM pickups WHERE {done} GROUP BY 1 ORDER BY 1",
             desc="A person booking on the sensor's warning vs the old fixed schedule")
p["fieldConfig"]["defaults"] = {"unit": "percent", "min": 0, "max": 100, "color": {"mode": "fixed", "fixedColor": "blue"}}
p = pg.panel("piechart", "Verdicts", 16, pg.y, 8, 9,
             f"SELECT {LABEL_SQL} AS metric, count(*) AS value FROM pickups WHERE {done} GROUP BY 1")
p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True}, "pieType": "donut",
                "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"], "showLegend": True}}
p["fieldConfig"]["overrides"] = [{"matcher": {"id": "byName", "options": k}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": v}}]}
                                 for k, v in LABEL_COLORS.items()]
pg.y += 9
pg._add({"type": "text", "title": "Rate the waste company — a person answers: truck on time? weighbridge ticket on time?",
         "gridPos": {"x": 0, "y": pg.y, "w": 24, "h": 13},
         "options": {"mode": "html", "content": f'<iframe src="{API_URL}/rate" title="Rate the waste company" '
                                                f'style="width:100%;height:440px;border:0;display:block"></iframe>'}}, 24, 13)
pg.y += 13
YES_NO = "CASE {} WHEN TRUE THEN 'yes' WHEN FALSE THEN 'no' ELSE '–' END"
p = pg.panel("table", "All pickups", 0, pg.y, 24, 11,
             f"SELECT p.id AS \"#\", p.done_at AS \"Emptied\", p.compactor_id AS \"Compactor\", c.material AS \"Material\", "
             f"p.kind AS \"Who\", p.load_before_pct AS \"Load %\", p.kg_collected AS \"kg\", p.wait_hours AS \"Wait (site h)\", "
             f"p.full_hours AS \"Full for (site h)\", {LABEL_SQL.replace('verdict', 'p.verdict')} AS \"Verdict\", p.verdict_reason AS \"Why\", "
             f"round((-{TOTAL})::numeric, 2) AS \"Net €\", {YES_NO.format('p.truck_on_time')} AS \"Truck on time\", "
             f"{YES_NO.format('p.weighbridge_on_time')} AS \"Weighbridge on time\" "
             f"FROM pickups p JOIN compactors c ON c.id = p.compactor_id JOIN materials m ON m.name = c.material "
             f"WHERE p.status = 'done' AND $__timeFilter(p.done_at) ORDER BY p.done_at DESC")
p["fieldConfig"]["overrides"] = [color_col("Verdict", LABEL_COLORS),
                                 color_col("Truck on time", {"yes": "green", "no": "red"}),
                                 color_col("Weighbridge on time", {"yes": "green", "no": "red"}),
                                 {"matcher": {"id": "byName", "options": "Why"}, "properties": [{"id": "custom.width", "value": 330}]}]
pg.y += 11
pg.text("**Rules:** Full 2h+ (too late) = full (≥ 98 %) for 2+ site hours before the lift · <60% (too early) = emptied more than 20 points "
        "below the on-call level (80 %) · otherwise ≥60% (on time). The lift-model verdicts (trained on the Europress history) are shown as a second "
        "opinion on the *Site now* page.", h=2)
pickups_page = pg.dash()

# ======================================================================== 3. MONEY & CO2
# a quick LIVE estimate with 2 numbers per material that the customer types in (materials.lift_fee_eur, price):
# change a number and every pickup on this page is re-priced. The full invoice formula is on the Analysis pages.
PRICED = ("FROM pickups p JOIN compactors c ON c.id = p.compactor_id JOIN materials m ON m.name = c.material "
          "WHERE p.status = 'done' AND $__timeFilter(p.done_at)")
pg = Page("live-money", "Live 3 · Money & CO₂", "### A quick estimate of what the collections cost — with your prices",
          time_from="now-6h", refresh="10s")
pg._add({"type": "text", "title": "Your prices — cost per lift and price per tonne, then Save",
         "gridPos": {"x": 0, "y": pg.y, "w": 24, "h": 9},
         "options": {"mode": "html", "content": f'<iframe src="{API_URL}/prices" title="Your prices" '
                                                f'style="width:100%;height:265px;border:0;display:block"></iframe>'}}, 24, 9)
pg.y += 9
pg.stats([
    ("Collected", f"SELECT round((sum(p.kg_collected) / 1000)::numeric, 2) {PRICED}", "suffix: t", None, "Measured by the board, not by the truck"),
    ("Lift costs €", f"SELECT round(sum({LIFT})) {PRICED}", "currencyEUR", None, "Cost per lift × number of lifts"),
    ("Material value €", f"SELECT round(sum({VALUE})) {PRICED}", "currencyEUR", None, "kg × your price per tonne: + earned / − paid"),
    ("Total cost €", f"SELECT round(sum({TOTAL})) {PRICED}", "currencyEUR",
     [{"color": "green", "value": None}, {"color": "orange", "value": 1}], "Lift costs − material value"),
    ("Total cost € / t", f"SELECT round((sum({TOTAL}) / NULLIF(sum(p.kg_collected) / 1000, 0))::numeric, 1) {PRICED}",
     "currencyEUR", None, "Total cost per tonne collected"),
    ("CO₂ saved", f"SELECT round((sum(p.co2_kg) / 1000)::numeric, 2) {PRICED}", "suffix: t", GOOD, "Recycled material × CO₂ factor"),
])
p = pg.panel("barchart", "Per material (€)", 0, pg.y, 10, 9,
             f"SELECT c.material AS \"Material\", round(sum({LIFT})) AS \"Lift costs\", round(sum({VALUE})) AS \"Material value\", "
             f"round(sum({TOTAL})) AS \"Total cost\" {PRICED} GROUP BY 1 ORDER BY 1")
p["fieldConfig"]["defaults"] = {"unit": "currencyEUR"}
p["options"] = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}}
p = pg.panel("timeseries", "Running total: total cost € and CO₂ saved", 10, pg.y, 14, 9, [
    f"SELECT p.done_at AS time, sum({TOTAL}) OVER (ORDER BY p.done_at) AS \"Total cost € (running)\" {PRICED} ORDER BY 1",
    f"SELECT p.done_at AS time, sum(p.co2_kg) OVER (ORDER BY p.done_at) / 1000 AS \"CO₂ saved t (running)\" {PRICED} ORDER BY 1",
], fmt="time_series")
p["fieldConfig"] = {"defaults": {"custom": {"drawStyle": "line", "lineInterpolation": "stepAfter", "lineWidth": 2, "showPoints": "always"}},
                    "overrides": [{"matcher": {"id": "byName", "options": "Total cost € (running)"}, "properties": [{"id": "unit", "value": "currencyEUR"}]},
                                  {"matcher": {"id": "byName", "options": "CO₂ saved t (running)"}, "properties": [
                                      {"id": "unit", "value": "suffix: t"}, {"id": "decimals", "value": 2}, {"id": "custom.axisPlacement", "value": "right"},
                                      {"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]}]}
pg.y += 9
r2 = "::numeric, 2)"
p = pg.panel("table", "Every pickup, priced with your prices", 0, pg.y, 24, 9,
             f"SELECT p.id AS \"Pickup\", p.done_at AS \"Emptied\", p.compactor_id AS \"Compactor\", c.material AS \"Material\", "
             f"p.kg_collected AS \"kg\", round(({LIFT}){r2} AS \"Lift cost €\", round(({VALUE}){r2} AS \"Material value €\", "
             f"round(({TOTAL}){r2} AS \"Total cost €\", round((({TOTAL}) / NULLIF(p.kg_collected / 1000, 0)){r2} AS \"€ / t\", "
             f"p.co2_kg AS \"CO₂ saved kg\" {PRICED} ORDER BY p.done_at DESC")
pg.y += 9
pg.text("**A quick estimate:** total cost = cost per lift − kg × price per tonne. The **kg** are measured by the board; the **€** "
        "use your prices above. The full invoice detail (haulage, processing, surcharges, penalties, credits) is on the "
        "**Analysis** pages, from the real invoice lines. CO₂ factors are placeholders.", h=2)
money = pg.dash()

# ======================================================================== 4. DEVICES & DATA HEALTH
pg = Page("edge-live", "Live 4 · Devices & data health",
          "### The ESP32-C6 edge node: can we trust its data?  Secure Boot V2 + flash encryption · every reading HMAC-signed")
pg.stats([
    ("Last reading", "SELECT round(extract(epoch FROM now() - max(ts)))::int FROM readings", "s",
     [{"color": "green", "value": None}, {"color": "orange", "value": 30}, {"color": "red", "value": 120}], "Seconds since the board's last reading"),
    ("Readings / min", "SELECT round(count(*) / 5.0, 1) FROM readings WHERE ts > now() - interval '5 minutes'", "none", None,
     "3 compactors × 6 per minute = 18 when all is well"),
    ("Signed & verified", "SELECT round(100.0 * count(*) FILTER (WHERE verified) / NULLIF(count(*), 0)) FROM readings WHERE $__timeFilter(ts)",
     "percent", [{"color": "red", "value": None}, {"color": "orange", "value": 50}, {"color": "green", "value": 100}], "Below 100 % = tampering or wrong key"),
    ("Spikes removed on the board", "SELECT coalesce(sum(m), 0) FROM (SELECT max(spikes_filtered) AS m FROM readings WHERE $__timeFilter(ts) GROUP BY compactor_id) x",
     "short", None, "Bad samples that never reached the cloud"),
    ("Sent from offline buffer", "SELECT count(*) FROM readings WHERE from_buffer AND $__timeFilter(ts)", "short", None, "Measured while offline, delivered later"),
    ("Data problems", "SELECT count(*) FROM alerts WHERE $__timeFilter(ts) AND type IN ('spike','sensor_stuck','sensor_fault','data_gap',"
     "'zero_shift','overload','unexpected_drop','signature_invalid')", "short", [{"color": "green", "value": None}, {"color": "orange", "value": 1}], ""),
])
p = pg.panel("table", "Per compactor", 0, pg.y, 12, 7,
             "SELECT c.id AS \"Compactor\", c.material AS \"Material\", round(extract(epoch FROM now() - max(r.ts)))::int AS \"Last seen (s)\", "
             "count(r.*) AS \"Readings\", round(100.0 * count(*) FILTER (WHERE r.verified) / NULLIF(count(r.*), 0)) AS \"Verified %\", "
             "max(r.spikes_filtered) AS \"Spikes removed\", count(*) FILTER (WHERE r.from_buffer) AS \"From buffer\", "
             "(array_agg(r.edge_quality ORDER BY r.ts DESC))[1] AS \"Quality now\" FROM compactors c "
             "LEFT JOIN readings r ON r.compactor_id = c.id AND $__timeFilter(r.ts) GROUP BY c.id, c.material ORDER BY c.id")
p["fieldConfig"]["overrides"] = [color_col("Quality now", {"OK": "green", "STUCK": "red", "OVERLOAD": "red"})]
p = pg.panel("barchart", "Data problems by type", 12, pg.y, 12, 7,
             "SELECT type AS \"Problem\", count(*) AS \"Count\" FROM alerts WHERE $__timeFilter(ts) AND type IN ('spike','sensor_stuck',"
             "'sensor_fault','data_gap','zero_shift','overload','unexpected_drop','signature_invalid','edge_buffered') GROUP BY 1 ORDER BY 2 DESC")
p["fieldConfig"]["defaults"] = {"color": {"mode": "fixed", "fixedColor": "orange"}}
pg.y += 7
p = pg.panel("timeseries", "Weight from the board (t) — dots = delivered later from the offline buffer", 0, pg.y, 24, 8, [
    "SELECT ts AS time, compactor_id AS metric, weight_kg / 1000 AS weight_t FROM readings WHERE $__timeFilter(ts) ORDER BY 1",
    "SELECT ts AS time, compactor_id || ' (from buffer)' AS metric, weight_kg / 1000 AS weight_t FROM readings WHERE from_buffer AND $__timeFilter(ts) ORDER BY 1",
], fmt="time_series")
p["fieldConfig"] = {"defaults": {"unit": "suffix: t", "decimals": 2, "custom": {"lineWidth": 2, "showPoints": "never", "spanNulls": 60000}},
                    "overrides": [{"matcher": {"id": "byRegexp", "options": ".*from buffer.*"}, "properties": [
                        {"id": "custom.drawStyle", "value": "points"}, {"id": "custom.pointSize", "value": 9},
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "purple"}}]}]}
pg.y += 8
p = pg.panel("table", "Latest readings", 0, pg.y, 24, 8,
             "SELECT ts AS \"Time\", compactor_id AS \"Compactor\", weight_kg AS \"Weight (kg)\", fill_pct AS \"Fill %\", seq AS \"Seq\", "
             "edge_quality AS \"Quality\", spikes_filtered AS \"Spikes removed (since boot)\", "
             "CASE WHEN from_buffer THEN 'yes' ELSE '' END AS \"From buffer\", "
             "CASE WHEN verified THEN '✓ signed' WHEN verified IS FALSE THEN '✗ BAD SIGNATURE' ELSE 'not signed' END AS \"Signature\" "
             "FROM readings ORDER BY ts DESC, id DESC LIMIT 20")
p["fieldConfig"]["overrides"] = [color_col("Signature", {"✓ signed": "green", "✗ BAD SIGNATURE": "red", "not signed": "orange"})]
pg.y += 8
pg.text("| Demo on the board (serial monitor) | You see |\n|---|---|\n"
        "| `1` `2` `3` select a compactor, `e` empty it by hand | a *manual* pickup, usually judged TOO EARLY |\n"
        "| `s` a spike hits the sensor | removed on the board: *Spikes removed* +1, no jump in the line |\n"
        "| hold **BOOT** 2 s (or `o`), wait 1 min, again | data gap, then **purple dots** = sent from the offline buffer |\n"
        "| `k` sensor stuck 70 s | quality STUCK, alert *sensor_stuck* |\n"
        "| `h` heavy / wet material | weight rises faster than the fill level |", h=6)
devices = pg.dash()

args = argparse.ArgumentParser()
args.add_argument("--out", default=str(ROOT / "dashboards"), help="folder to write to (default: the live, mounted folder)")
args.add_argument("--only", help="write just this page, e.g. live_pickups")
args = args.parse_args()
out = pathlib.Path(args.out)
out.mkdir(parents=True, exist_ok=True)
for name, d in [("compactor", site), ("live_pickups", pickups_page), ("live_money", money), ("edge_live", devices)]:
    if args.only in (None, name):
        (out / f"{name}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"written to {out}: " + (args.only or "compactor, live_pickups, live_money, edge_live") + f" (DEMO_TIME_SCALE={SCALE:g})")
