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

    def text(self, md, h=3, title=""):
        self._add({"type": "text", "title": title, "transparent": not title, "gridPos": {"x": 0, "y": self.y, "w": 24, "h": h},
                   "options": {"mode": "markdown", "content": md}}, 24, h)
        self.y += h

    def stats(self, items, h=4, color_mode="background", no_value="–"):
        w = 24 // len(items)
        for i, (title, sql, unit, steps, desc) in enumerate(items):
            p = self.panel("stat", title, i * w, self.y, w, h, sql, desc=desc)
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
    ("Trucks on the way", "SELECT count(*) FROM pickups WHERE status = 'booked'", "short", None, "Booked by the system, not arrived yet"),
    ("Next truck in (site h)", f"SELECT round((extract(epoch FROM min(truck_due) - now()) / 3600 * {SCALE})::numeric, 1) FROM pickups "
     "WHERE status = 'booked' AND cmd_sent_at IS NULL", "none", None, "Site hours until the next booked truck arrives"),
    ("Pickups (last 24 site h)", f"SELECT count(*) FROM pickups WHERE status = 'done' AND done_at > now() - interval '{24 / SCALE * 60:.0f} minutes'",
     "short", None, ""),
    ("On time", "SELECT round(100.0 * count(*) FILTER (WHERE verdict = 'ON_TIME') / NULLIF(count(*), 0)) FROM pickups WHERE status = 'done'",
     "percent", [{"color": "red", "value": None}, {"color": "orange", "value": 60}, {"color": "green", "value": 85}], "Share of all lifts that were on time"),
    ("Net result €", "SELECT round(sum(net_eur)) FROM pickups WHERE status = 'done'", "currencyEUR",
     [{"color": "red", "value": None}, {"color": "green", "value": 0}], "Material value minus lift fees, all pickups"),
    ("Invoice claims €", "SELECT round(sum(claim_eur)) FROM pickups WHERE status = 'done'", "currencyEUR",
     [{"color": "green", "value": None}, {"color": "orange", "value": 1}], "Money to claim back: invoices that do not match what we measured"),
])
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
             "WHERE $__timeFilter(ts) ORDER BY ts DESC, id DESC LIMIT 60")
p["fieldConfig"]["overrides"] = [{"matcher": {"id": "byName", "options": "Time"}, "properties": [{"id": "custom.width", "value": 150}]},
                                 {"matcher": {"id": "byName", "options": "Compactor"}, "properties": [{"id": "custom.width", "value": 90}]},
                                 {"matcher": {"id": "byName", "options": "Event"}, "properties": [{"id": "custom.width", "value": 160}]}]
pg.y += 8
pg.text("**How it works:** the board measures (stable weight, spikes removed, signed). At the on-call % the system **books a truck**. "
        "When the truck arrives, the system tells the board over MQTT; the board **detects the emptying itself**. Every lift is then "
        "**judged** (on time / too early / too late), **priced** (material value − lift fee), its **CO₂** counted and the operator's "
        "**invoice checked** against our kg. Some trucks are late and the old fixed route sometimes comes early — on purpose, so you "
        "see every case.", h=3)
site = pg.dash()

# ======================================================================== 2. PICKUPS
SITE_TIME = (" In fast demo mode 1 real minute is {:.0f} site minutes.".format(SCALE)) if SCALE != 1 else ""
NO_EVENTS = "Nothing to show here. See the status line above."   # also appears when a query fails, so it must not claim "no pickups"
pg = Page("live-pickups", "Live 2 · Pickups",
          "### Pickups: did each truck come at the right moment?\n"
          "Every emptied container is judged and priced. Check the status line first: it says what this page can show right now.",
          time_from="now-6h", refresh="10s", intro_h=3)
pg.links = [{"type": "dashboards", "tags": ["live"], "asDropdown": True, "title": "Live pages", "keepTime": True, "icon": "external link",
             "includeVars": False, "targetBlank": False}]
pg.annotations.append(pickup_anno)
done = "status = 'done' AND $__timeFilter(done_at)"

# --- status line: separates "zero", "nothing in this time range", "no data at all", "missing values" and "simulated"
pg.status("Pickups in this view", f"""SELECT CASE
  WHEN total = 0 THEN 'No pickups recorded yet'
  WHEN in_range = 0 THEN 'None in this time range. ' || total || ' recorded, latest ' || to_char(latest AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI') || ' UTC'
  ELSE in_range || ' of ' || total || ' recorded pickups' || CASE WHEN incomplete > 0 THEN ', ' || incomplete || ' with a missing measurement' ELSE '' END
  END AS "Pickups"
FROM (SELECT count(*) AS total, max(done_at) AS latest,
        count(*) FILTER (WHERE $__timeFilter(done_at)) AS in_range,
        count(*) FILTER (WHERE $__timeFilter(done_at) AND (kg_collected IS NULL OR load_before_pct IS NULL)) AS incomplete
      FROM pickups WHERE status = 'done') t""", 0, 10,
          desc="Zero here means nothing was recorded. It does not mean the system failed. Widen the time range at the top right to see older pickups.")
pg.status("Device readings", """SELECT CASE
  WHEN last_ts IS NULL THEN 'No readings received yet'
  WHEN last_ts > now() - interval '2 hours' THEN 'Arriving, latest ' || to_char(last_ts AT TIME ZONE 'UTC', 'HH24:MI') || ' UTC'
  ELSE 'Silent since ' || to_char(last_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI') || ' UTC'
  END AS "Readings"
FROM (SELECT max(ts) AS last_ts FROM readings) t""", 10, 6,
          desc="Latest reading from any compactor. Silent means no reading for 2 hours or more, so new pickups cannot be detected.")
pg.status("Source of these pickups", f"""SELECT CASE
  WHEN count(*) = 0 THEN 'No pickups to describe'
  WHEN bool_and(demo) THEN 'SIMULATED: demo seed, no device'
  WHEN bool_and(board AND NOT demo) THEN 'SIMULATED load cell on real ESP32'
  WHEN bool_or(demo) THEN 'SIMULATED: demo seed and ESP32 mixed'
  ELSE 'NOT VERIFIED: no device counter' END AS "Source"
FROM (SELECT p.compactor_id,
        coalesce(bool_or(r.edge_quality = 'simulated'), false) AS demo, coalesce(bool_or(r.seq IS NOT NULL), false) AS board
      FROM pickups p LEFT JOIN readings r ON r.compactor_id = p.compactor_id
      WHERE p.status = 'done' AND $__timeFilter(p.done_at) GROUP BY 1) s""", 16, 8, warn="^(SIMULATED|NOT VERIFIED).*",
          desc="No physical load cell is connected yet, so no weight on this page is a real measurement. The ESP32 edge processing is real.")
pg.y += 3

# --- KPIs: coloured numbers on a calm background. Green = fine, orange = worth a look, red = a problem
pg.stats([
    ("Pickups", f"SELECT count(*) FROM pickups WHERE {done}", "short", [{"color": "text", "value": None}], "Completed in this time range. 0 means none were recorded."),
    ("On time", f"SELECT count(*) FROM pickups WHERE {done} AND verdict = 'ON_TIME'", "short", GOOD, "Neither too early nor too late"),
    ("Too early", f"SELECT count(*) FROM pickups WHERE {done} AND verdict = 'TOO_EARLY'", "short",
     [{"color": "green", "value": None}, {"color": "orange", "value": 1}], "Emptied well below the on-call level"),
    ("Too late", f"SELECT count(*) FROM pickups WHERE {done} AND verdict = 'TOO_LATE'", "short",
     [{"color": "green", "value": None}, {"color": "red", "value": 1}], "Full for 2+ site hours before the truck came"),
    ("Avg load at pickup", f"SELECT round(avg(load_before_pct)) FROM pickups WHERE {done}", "percent",
     [{"color": "red", "value": None}, {"color": "orange", "value": 60}, {"color": "green", "value": 80}], "Higher means fewer trucks for the same waste"),
    ("Wasted fees (est.)", f"SELECT round(sum(fee_eur * greatest(0, 1 - load_before_pct / 100))) FROM pickups WHERE {done}",
     "currencyEUR", [{"color": "green", "value": None}, {"color": "orange", "value": 20}],
     "Fees paid for empty space. Estimate: placeholder lift fee × the empty part of the container"),
], h=3, color_mode="value")
for tile in pg.panels[-2:]:   # no pickups is not good or bad news, so it gets no threshold colour
    tile["fieldConfig"]["defaults"]["mappings"] = [{"type": "special", "options": {"match": "null+nan", "result": {"text": "No pickups", "color": "text", "index": 0}}}]

pg.text("- **Too late:** full (98 % or more) for 2 site hours or longer before the lift. Overflow and side-waste risk. Checked first.\n"
        "- **Too early:** emptied more than 20 points below that compactor's on-call level. A paid lift for a part-full container.\n"
        "- **On time:** neither of the above.\n\n"
        "The on-call level is the fill at which a truck is ordered: 80 % for C1 and C2, 85 % for C3." + SITE_TIME, h=5, title="How each pickup is judged")

# --- analysis
p = pg.panel("barchart", "Verdict per compactor", 0, pg.y, 10, 9,
             f"SELECT p.compactor_id || ' ' || c.material AS \"Compactor\", "
             f"count(*) FILTER (WHERE verdict = 'ON_TIME') AS \"On time\", count(*) FILTER (WHERE verdict = 'TOO_EARLY') AS \"Too early\", "
             f"count(*) FILTER (WHERE verdict = 'TOO_LATE') AS \"Too late\" FROM pickups p JOIN compactors c ON c.id = p.compactor_id "
             f"WHERE p.{done.replace('$__timeFilter(done_at)', '$__timeFilter(p.done_at)')} GROUP BY 1 ORDER BY 1",
             desc="How the pickups of each compactor were judged. A compactor with mostly orange gets trucks too soon.")
p["options"] = {"stacking": "normal", "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}, "xTickLabelRotation": -25}
p["fieldConfig"]["defaults"] = {"noValue": NO_EVENTS}
p["fieldConfig"]["overrides"] = [{"matcher": {"id": "byName", "options": k}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": v}}]}
                                 for k, v in [("On time", "green"), ("Too early", "orange"), ("Too late", "red")]]
p = pg.panel("barchart", "Average load by who sent the truck", 10, pg.y, 7, 9,
             f"SELECT CASE kind WHEN 'booked' THEN 'Booked by the system' WHEN 'fixed_route' THEN 'Old fixed route' ELSE 'By hand' END AS \"Who\", "
             f"round(avg(load_before_pct)) AS \"Avg load at pickup %\" FROM pickups WHERE {done} GROUP BY 1 ORDER BY 1",
             desc="Fill level at pickup when the system booked the truck, compared with the old fixed schedule. Trucks are simulated.")
p["fieldConfig"]["defaults"] = {"unit": "percent", "min": 0, "max": 100, "color": {"mode": "fixed", "fixedColor": "blue"}, "noValue": NO_EVENTS}
p = pg.panel("piechart", "Share of verdicts", 17, pg.y, 7, 9,
             f"SELECT verdict AS metric, count(*) AS value FROM pickups WHERE {done} GROUP BY 1", desc="The same pickups as the numbers above, as shares of the total.")
p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True}, "pieType": "donut",
                "legend": {"displayMode": "table", "placement": "bottom", "values": ["value", "percent"], "showLegend": True}}
p["fieldConfig"]["defaults"] = {"noValue": NO_EVENTS}
p["fieldConfig"]["overrides"] = [{"matcher": {"id": "byName", "options": k}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": v}}]}
                                 for k, v in VERDICT_COLORS.items()]
pg.y += 9

# --- history
p = pg.panel("table", "Pickup history", 0, pg.y, 24, 11,
             f"SELECT p.id AS \"#\", p.done_at AS \"Emptied\", p.compactor_id AS \"Compactor\", c.material AS \"Material\", "
             f"p.kind AS \"Who\", p.load_before_pct AS \"Load %\", p.kg_collected AS \"kg\", p.wait_hours AS \"Wait (site h)\", "
             f"p.full_hours AS \"Full for (site h)\", p.verdict AS \"Verdict\", p.verdict_reason AS \"Why\", p.net_eur AS \"Net € (estimate)\", "
             f"p.invoice_check AS \"Simulated invoice\", p.claim_eur AS \"Simulated claim €\" FROM pickups p JOIN compactors c ON c.id = p.compactor_id "
             f"WHERE p.status = 'done' AND $__timeFilter(p.done_at) ORDER BY p.done_at DESC",
             desc="Newest first. A dash means the value was not recorded. Weights are simulated, net is an estimate with placeholder prices, and invoices are simulated.")
p["fieldConfig"]["defaults"] = {"noValue": NO_EVENTS}     # whole table empty
p["options"] = {"showHeader": True, "cellHeight": "sm"}
p["fieldConfig"]["overrides"] = [*[{"matcher": {"id": "byType", "options": t}, "properties": [{"id": "noValue", "value": "–"}]}   # one value missing
                                   for t in ("number", "string", "time")],
                                 text_col("Verdict", {"ON_TIME": ("green", "On time"), "TOO_EARLY": ("orange", "Too early"), "TOO_LATE": ("red", "Too late")}),
                                 text_col("Simulated invoice", {"OK": ("green", "OK")}),
                                 {"matcher": {"id": "byName", "options": "Why"}, "properties": [{"id": "custom.width", "value": 330}]}]
pg.y += 11
pg.text("The lift model's second opinion, trained on the Europress history, is on the *Site now* page.", h=2)
pickups_page = pg.dash()

# ======================================================================== 3. MONEY & CO2
pg = Page("live-money", "Live 3 · Money & CO₂", "### What the measured kilograms are worth — and what the invoices got wrong",
          time_from="now-6h", refresh="10s")
pg.stats([
    ("Collected", f"SELECT round(sum(kg_collected)) FROM pickups WHERE {done}", "masskg", None, "Measured by the board, not by the truck"),
    ("Material value €", f"SELECT round(sum(value_eur)) FROM pickups WHERE {done}", "currencyEUR", None, "+ earned (cardboard, plastic) / − paid (mixed waste)"),
    ("Lift fees €", f"SELECT round(sum(fee_eur)) FROM pickups WHERE {done}", "currencyEUR", None, "Contract fee per lift"),
    ("Net €", f"SELECT round(sum(net_eur)) FROM pickups WHERE {done}", "currencyEUR",
     [{"color": "red", "value": None}, {"color": "green", "value": 0}], ""),
    ("CO₂ saved", f"SELECT round(sum(co2_kg)) FROM pickups WHERE {done}", "masskg", GOOD, "Recycled material × CO₂ factor"),
    ("To claim back €", f"SELECT round(sum(claim_eur)) FROM pickups WHERE {done}", "currencyEUR",
     [{"color": "green", "value": None}, {"color": "orange", "value": 1}], "Invoice errors found by comparing with our own kg"),
])
p = pg.panel("barchart", "Per material (€)", 0, pg.y, 10, 9,
             f"SELECT c.material AS \"Material\", round(sum(p.value_eur)) AS \"Material value\", -round(sum(p.fee_eur)) AS \"Lift fees\", "
             f"round(sum(p.net_eur)) AS \"Net\" FROM pickups p JOIN compactors c ON c.id = p.compactor_id "
             f"WHERE p.status = 'done' AND $__timeFilter(p.done_at) GROUP BY 1 ORDER BY 1")
p["fieldConfig"]["defaults"] = {"unit": "currencyEUR"}
p["options"] = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}}
p = pg.panel("timeseries", "Running total: net € and CO₂ saved", 10, pg.y, 14, 9, [
    f"SELECT done_at AS time, sum(net_eur) OVER (ORDER BY done_at) AS \"Net € (running)\" FROM pickups WHERE {done} ORDER BY 1",
    f"SELECT done_at AS time, sum(co2_kg) OVER (ORDER BY done_at) AS \"CO₂ saved kg (running)\" FROM pickups WHERE {done} ORDER BY 1",
], fmt="time_series")
p["fieldConfig"] = {"defaults": {"custom": {"drawStyle": "line", "lineInterpolation": "stepAfter", "lineWidth": 2, "showPoints": "always"}},
                    "overrides": [{"matcher": {"id": "byName", "options": "Net € (running)"}, "properties": [{"id": "unit", "value": "currencyEUR"}]},
                                  {"matcher": {"id": "byName", "options": "CO₂ saved kg (running)"}, "properties": [
                                      {"id": "unit", "value": "masskg"}, {"id": "custom.axisPlacement", "value": "right"},
                                      {"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]}]}
pg.y += 9
p = pg.panel("table", "Invoice check: their bill vs our measurement", 0, pg.y, 24, 10,
             f"SELECT p.id AS \"Pickup\", p.done_at AS \"Emptied\", p.compactor_id AS \"Compactor\", c.material AS \"Material\", "
             f"p.kg_collected AS \"We measured kg\", p.invoice_kg AS \"Billed kg\", p.fee_eur AS \"Contract fee €\", "
             f"p.invoice_fee_eur AS \"Billed fee €\", p.invoice_check AS \"Check\", p.claim_eur AS \"Claim €\" "
             f"FROM pickups p JOIN compactors c ON c.id = p.compactor_id WHERE p.status = 'done' AND $__timeFilter(p.done_at) "
             f"ORDER BY (p.invoice_check <> 'OK') DESC, p.done_at DESC")
p["fieldConfig"]["overrides"] = [color_col("Check", {"OK": "green", "WEIGHT_MISMATCH": "red", "WRONG_FEE": "red", "WEIGHT_MISMATCH+WRONG_FEE": "red"})]
pg.y += 10
pg.text("Prices, fees and CO₂ factors are placeholders (backend `materials` table and `FEE_EUR` in `backend/app/pickups.py`) — "
        "replace them with the customer's contract. Operator invoices are simulated: most are right, some bill more kg than we "
        "measured (or fewer, when they pay us), some still use an old fee.", h=2)
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
p = pg.panel("timeseries", "Weight from the board (kg) — dots = delivered later from the offline buffer", 0, pg.y, 24, 8, [
    "SELECT ts AS time, compactor_id AS metric, weight_kg FROM readings WHERE $__timeFilter(ts) ORDER BY 1",
    "SELECT ts AS time, compactor_id || ' (from buffer)' AS metric, weight_kg FROM readings WHERE from_buffer AND $__timeFilter(ts) ORDER BY 1",
], fmt="time_series")
p["fieldConfig"] = {"defaults": {"unit": "masskg", "custom": {"lineWidth": 2, "showPoints": "never", "spanNulls": 60000}},
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
print(f"written to {out}: " + (args.only or "compactor, live_pickups, live_money, edge_live"))
