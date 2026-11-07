"""Generate the ANALYSIS pages for Grafana (the admin's view of all customers, live data from the ESP32 sites).

    python grafana/make_cockpit_pages.py            # writes grafana/dashboards/cockpit_*.json
    python grafana/make_cockpit_pages.py sql        # print every query with filters set to "all" (for testing)

The data is what our customers' boards measured (pickups, alerts) and the invoices they typed in (invoices,
invoice_lines, checked by backend/app/invoice_check.py). The Europress dataset is only used to TRAIN the models.
Customers get their own layout on the user platform (teammate), from the same data via /api/analysis/*.
Design rules: one fixed menu (same order on every page), plain-language names, every panel title says what it shows.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "compactor-pg"}
TIME = {"from": "now-7d", "to": "now"}
API_URL = "http://localhost:8000"   # embedded pages are opened by the viewer's browser

PAGES = [  # (uid, menu label)
    ("value-cockpit", "1 Problems"), ("cockpit-cost", "2 Cost & weight"),
    ("cockpit-operators", "3 Waste companies"), ("cockpit-actions", "4 Invoices"),
]
LIVE_PAGES = [  # the live product (grafana/make_live_pages.py)
    ("smart-compactor", "Site now"), ("live-pickups", "Pickups"), ("live-money", "Money & CO₂"), ("edge-live", "Devices"),
]

PROBLEM = {  # alert type -> plain language
    "pickup_too_early": "Emptied too early (<60%)", "pickup_too_late": "Left full 2h+", "ml_premature_unjustified": "AI: lift not needed",
    "ml_delayed_collection": "AI: lift came late", "ml_anomaly": "AI: unusual reading", "contamination": "Wrong material (density)",
    "spike": "Sensor spike", "sensor_stuck": "Sensor stuck", "sensor_fault": "Sensor fault", "data_gap": "No data",
    "zero_shift": "Scale not zero after emptying", "overload": "Overloaded", "unexpected_drop": "Weight dropped without emptying",
    "signature_invalid": "Reading tampered / wrong key",
}
CHECK = {"OK": "ok", "WRONG_PRICE": "wrong price", "NO_LIFT": "no lift measured", "DUPLICATE": "billed twice",
         "WEIGHT_MISMATCH": "weight differs", "NO_EVIDENCE": "needs proof", "UNKNOWN_COMPACTOR": "not their compactor"}
LINE = {"LIFT_FEE": "Lift fee", "MATERIAL_CREDIT": "Material credit", "PROCESSING": "Processing", "HAULAGE": "Haulage",
        "SURCHARGE": "Surcharge", "PENALTY": "Penalty", "OTHER": "Other"}


def case(col, mapping):
    return "CASE " + col + " " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in mapping.items()) + f" ELSE {col} END"


# an ISSUE = something a person should look at, counted once (same rule as backend app/analysis.py):
#   one per lift judged too early / too late  +  device faults: same fault, same compactor, same hour = one
# AI lift-model alerts are a second opinion on a lift (event log), never an extra issue.
DEVICE_TYPES = ["spike", "sensor_stuck", "sensor_fault", "data_gap", "zero_shift", "overload", "unexpected_drop",
                "signature_invalid", "contamination"]
DEV_IN = ", ".join(f"'{t}'" for t in DEVICE_TYPES)
INV_LATEST = ("LEFT JOIN (SELECT d.* FROM invoice_decisions d JOIN (SELECT invoice_id, MAX(id) AS max_id FROM invoice_decisions "
              "GROUP BY invoice_id) m ON m.max_id = d.id) d ON d.invoice_id = i.invoice_id")
STATUS_SQL = ("COALESCE(CASE d.decision WHEN 'APPROVE' THEN 'approved' WHEN 'REJECT' THEN 'rejected' WHEN 'HOLD' THEN 'on hold' END, "
              "CASE WHEN i.suggestion = 'CHECK' THEN 'to check' ELSE 'matches' END)")
STATUS_COLOURS = {"to check": "orange", "matches": "green", "approved": "green", "rejected": "red", "on hold": "orange"}
SQL = []


def menu_text(current_uid):
    """The page menu as its own line (a text panel), so filters can never squeeze it."""
    def items(pages):
        return " · ".join(f"**● {label}**" if uid == current_uid else f"[{label}](/d/{uid})" for uid, label in pages)
    return f"🟢 **Live (ESP32):** {items(LIVE_PAGES)} &nbsp;&nbsp;|&nbsp;&nbsp; 📊 **Analysis (all customers):** {items(PAGES)}"


def menu_panel(current_uid):
    return {"id": 99, "type": "text", "title": "", "transparent": True, "gridPos": {"x": 0, "y": 0, "w": 24, "h": 2},
            "options": {"mode": "markdown", "content": menu_text(current_uid)}}


def var(name, label, sql):
    SQL.append(sql)
    return {"name": name, "label": label, "type": "query", "datasource": DS, "query": sql, "definition": sql,
            "multi": True, "includeAll": True, "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
            "refresh": 1, "sort": 1}


def page(uid, title, intro, panels, variables=()):
    out = [menu_panel(uid),
           {"id": 100, "type": "text", "title": "", "transparent": True, "gridPos": {"x": 0, "y": 2, "w": 24, "h": 3},
            "options": {"mode": "markdown", "content": intro}}]
    for i, p in enumerate(panels, 1):
        p["id"] = i
        p["gridPos"]["y"] += 2          # make room for the menu line
        for t in p.get("targets", []):
            SQL.append(t["rawSql"])
        out.append(p)
    return {"uid": uid, "title": title, "tags": ["analysis"], "timezone": "browser", "schemaVersion": 39, "version": 4,
            "refresh": "30s", "time": TIME, "graphTooltip": 1, "editable": True, "links": [],
            "description": "Analysis of our customers' live data. The system only suggests; a person decides.",
            "panels": out, "templating": {"list": list(variables)}}


def P(title, typ, sql, x, y, w, h, fmt="table", field=None, options=None, desc=""):
    field = field or {"defaults": {}, "overrides": []}
    if typ == "bargauge":
        field["defaults"]["color"] = {"mode": "fixed", "fixedColor": "#5794F2"}
    return {"title": title, "description": desc, "type": typ, "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [{"refId": "A", "datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True, "rawSql": sql}],
            "fieldConfig": field, "options": options or {}}


def embed(title, path, y, h, px):
    return {"title": title, "type": "text", "gridPos": {"x": 0, "y": y, "w": 24, "h": h},
            "options": {"mode": "html", "content": f'<iframe src="{API_URL}{path}" title="{title}" '
                                                   f'style="width:100%;height:{px}px;border:0;display:block"></iframe>'}}


STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "none", "graphMode": "none",
        "textMode": "value", "justifyMode": "center", "wideLayout": True}
EUR = {"defaults": {"unit": "currencyEUR", "decimals": 0, "noValue": "–"}, "overrides": []}
NUM = {"defaults": {"noValue": "0"}, "overrides": []}
BAR = lambda f: {"orientation": "horizontal", "displayMode": "basic", "valueMode": "text", "showUnfilled": True,  # noqa: E731
                 "namePlacement": "left", "sizing": "auto", "reduceOptions": {"calcs": ["lastNotNull"], "fields": f, "values": True}}
TABLE = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}


def o_unit(n, u): return {"matcher": {"id": "byName", "options": n}, "properties": [{"id": "unit", "value": u}]}
def o_width(n, w): return {"matcher": {"id": "byName", "options": n}, "properties": [{"id": "custom.width", "value": w}]}
def o_map(n, colours):
    return {"matcher": {"id": "byName", "options": n}, "properties": [
        {"id": "custom.cellOptions", "value": {"type": "color-text"}},
        {"id": "mappings", "value": [{"type": "value", "options": {k: {"color": v, "index": i} for i, (k, v) in enumerate(colours.items())}}]}]}


V_CUST = var("customer", "Customer", "SELECT DISTINCT customer_name FROM compactors WHERE customer_name IS NOT NULL ORDER BY 1")
V_OP = var("operator", "Waste company", "SELECT DISTINCT operator_name FROM compactors WHERE operator_name IS NOT NULL ORDER BY 1")
CW = "c.customer_name IN ($customer) AND c.operator_name IN ($operator)"
IW = "i.customer_name IN ($customer) AND i.operator_name IN ($operator)"
PICK = ("FROM pickups p JOIN compactors c ON c.id = p.compactor_id JOIN materials m ON m.name = c.material "
        f"WHERE p.status = 'done' AND {CW} AND $__timeFilter(p.done_at)")
COST = "(coalesce(m.lift_fee_eur, p.fee_eur, 0) - p.kg_collected * m.price_eur_per_kg)"   # live estimate (backend pickups.costs)
ISSUES = (
    "SELECT p.done_at AS ts, c.customer_name, p.compactor_id, c.operator_name, "
    "CASE p.verdict WHEN 'TOO_EARLY' THEN 'Emptied too early (<60%)' ELSE 'Left full 2h+' END AS problem, "
    "p.verdict_reason AS what, 1 AS times FROM pickups p JOIN compactors c ON c.id = p.compactor_id "
    f"WHERE p.status = 'done' AND p.verdict IN ('TOO_EARLY', 'TOO_LATE') AND {CW} AND $__timeFilter(p.done_at) "
    f"UNION ALL SELECT min(a.ts), c.customer_name, a.compactor_id, c.operator_name, {case('a.type', PROBLEM)}, min(a.message), count(*) "
    f"FROM alerts a JOIN compactors c ON c.id = a.compactor_id WHERE a.type IN ({DEV_IN}) AND {CW} AND $__timeFilter(a.ts) "
    "GROUP BY c.customer_name, a.compactor_id, c.operator_name, a.type, date_trunc('hour', a.ts)")
LINES = f"FROM invoice_lines l JOIN invoices i ON i.invoice_id = l.invoice_id {INV_LATEST} WHERE {IW}"
IN_PERIOD = ("p.compactor_id = l.compactor_id AND p.status = 'done' AND p.done_at >= i.period_from "
             "AND p.done_at < i.period_to + 1")

# ------------------------------------------------------------------ 1 PROBLEMS
problems = page("value-cockpit", "1 Problems",
"""### What went wrong — from the board's own measurements and the checked invoices
Pick a **customer** or **waste company** at the top. An **issue** is counted once: one per lift that was emptied too early or left full too long, and a device fault once per compactor per hour. The AI's opinion on each lift is shown in the event log, not counted again. **Charged too much** is proven by our measurement; **needs proof** = a surcharge or penalty the sensor cannot check.""",
[
    P("Lifts measured", "stat", f"SELECT count(*) AS v {PICK}", 0, 3, 4, 4, field=NUM, options=STAT),
    P("Collected", "stat", f"SELECT round(sum(p.kg_collected)) AS v {PICK}", 4, 3, 4, 4,
      field={"defaults": {"unit": "masskg", "noValue": "0"}, "overrides": []}, options=STAT),
    P("Issues", "stat", f"SELECT count(*) AS v FROM ({ISSUES}) x", 8, 3, 4, 4, field=NUM, options=STAT,
      desc="One per lift judged too early / too late, plus device faults (same fault, same compactor, same hour = one)."),
    P("Invoices to check", "stat", f"SELECT count(*) AS v FROM invoices i {INV_LATEST} WHERE {IW} AND i.suggestion = 'CHECK' AND d.decision IS NULL",
      12, 3, 4, 4, field=NUM, options=STAT, desc="Invoices where a line differs from the measurement and nobody decided yet."),
    P("Charged too much", "stat", f"SELECT round(sum(i.overcharged_eur)::numeric) AS v FROM invoices i {INV_LATEST} WHERE {IW}",
      16, 3, 4, 4, field=EUR, options=STAT, desc="Billed more than the board measured or than the customer's prices."),
    P("Needs proof", "stat", f"SELECT round(sum(i.unverified_eur)::numeric) AS v FROM invoices i {INV_LATEST} WHERE {IW}",
      20, 3, 4, 4, field=EUR, options=STAT, desc="Surcharges and penalties the sensor cannot prove or disprove: ask for evidence."),
    P("Issues by type", "bargauge",
      f"SELECT problem AS \"Problem\", count(*) AS \"Issues\" FROM ({ISSUES}) x GROUP BY 1 ORDER BY 2 DESC",
      0, 7, 8, 11, options=BAR("/Issues/")),
    P("Issues — newest first (times = how often the same fault repeated within the hour)", "table",
      f"SELECT ts AS \"Time\", customer_name AS \"Customer\", compactor_id AS \"Compactor\", operator_name AS \"Waste company\", "
      f"problem AS \"Problem\", what AS \"What the data shows\", times AS \"Times\" FROM ({ISSUES}) x ORDER BY ts DESC LIMIT 500",
      8, 7, 16, 11, field={"defaults": {"custom": {"filterable": True}}, "overrides": [o_width("Time", 150), o_width("Compactor", 90),
          o_width("Problem", 200)]}, options=TABLE),
    P("Invoice lines that do not match the measurement", "table",
      f"SELECT i.invoice_id AS \"Invoice\", i.operator_name AS \"Waste company\", {case('l.line_type', LINE)} AS \"Line\", "
      f"l.compactor_id AS \"Compactor\", l.service_date AS \"Date\", l.amount_eur AS \"Billed €\", l.expected_eur AS \"Should be €\", "
      f"l.difference_eur AS \"Difference €\", {case('l.check_status', CHECK)} AS \"Check\", l.check_reason AS \"Why\" "
      f"{LINES} AND l.check_status <> 'OK' ORDER BY l.difference_eur DESC NULLS LAST LIMIT 500",
      0, 18, 24, 10, field={"defaults": {"custom": {"filterable": True}}, "overrides": [o_unit("Billed €", "currencyEUR"),
          o_unit("Should be €", "currencyEUR"), o_unit("Difference €", "currencyEUR"),
          o_map("Check", {"needs proof": "orange", **{v: "red" for k, v in CHECK.items() if k not in ("OK", "NO_EVIDENCE")}})]}, options=TABLE),
], [V_CUST, V_OP])

# ------------------------------------------------------------------ 2 COST & WEIGHT
cost = page("cockpit-cost", "2 Cost & weight",
"""### What the waste cost, per tonne — and does the invoice agree with our scale?
**Estimated** = the live estimate with the customer's prices (cost per lift − kg × price per tonne). **Billed** = what the waste companies invoiced. The middle table puts the **lifts and tonnes we measured** next to what each invoice **billed**.""",
[
    P("Tonnes measured", "stat", f"SELECT round((sum(p.kg_collected) / 1000)::numeric, 2) AS v {PICK}", 0, 3, 5, 4, field=NUM, options=STAT),
    P("Estimated cost", "stat", f"SELECT round(sum({COST})::numeric) AS v {PICK}", 5, 3, 5, 4, field=EUR, options=STAT,
      desc="Cost per lift − kg × price per tonne, with the prices on Money & CO₂."),
    P("Estimated € per tonne", "stat", f"SELECT round((sum({COST}) / NULLIF(sum(p.kg_collected) / 1000, 0))::numeric, 1) AS v {PICK}",
      10, 3, 4, 4, field=EUR, options=STAT),
    P("Billed (invoices entered)", "stat", f"SELECT round(sum(i.total_eur)::numeric) AS v FROM invoices i {INV_LATEST} WHERE {IW}",
      14, 3, 5, 4, field=EUR, options=STAT),
    P("Charged too much", "stat", f"SELECT round(sum(i.overcharged_eur)::numeric) AS v FROM invoices i {INV_LATEST} WHERE {IW}",
      19, 3, 5, 4, field=EUR, options=STAT),
    P("Per compactor (measured)", "table",
      f"SELECT c.customer_name AS \"Customer\", p.compactor_id AS \"Compactor\", c.material AS \"Material\", c.operator_name AS \"Waste company\", "
      f"count(*) AS \"Lifts\", round((sum(p.kg_collected) / 1000)::numeric, 2) AS \"Tonnes\", round(avg(p.load_before_pct)::numeric) AS \"Avg load at lift %\", "
      f"round(sum({COST})::numeric) AS \"Estimated €\", round((sum({COST}) / NULLIF(sum(p.kg_collected) / 1000, 0))::numeric, 1) AS \"Estimated € / t\" "
      f"{PICK} GROUP BY 1, 2, 3, 4 ORDER BY 1, 2", 0, 7, 24, 6, options=TABLE),
    P("Invoice vs our measurement, per compactor", "table",
      "SELECT i.invoice_id AS \"Invoice\", i.operator_name AS \"Waste company\", l.compactor_id AS \"Compactor\", "
      "sum(CASE WHEN l.line_type = 'LIFT_FEE' THEN coalesce(l.quantity, 1) ELSE 0 END) AS \"Lifts billed\", "
      f"(SELECT count(*) FROM pickups p WHERE {IN_PERIOD}) AS \"Lifts measured\", "
      "round(sum(CASE WHEN l.line_type IN ('PROCESSING', 'MATERIAL_CREDIT') THEN CASE WHEN l.unit = 'kg' THEN l.quantity / 1000 ELSE l.quantity END "
      "ELSE 0 END)::numeric, 3) AS \"Tonnes billed\", "
      f"(SELECT round((sum(p.kg_collected) / 1000)::numeric, 3) FROM pickups p WHERE {IN_PERIOD}) AS \"Tonnes measured\", "
      "round(sum(l.amount_eur)::numeric, 2) AS \"Billed €\", round(sum(l.difference_eur)::numeric, 2) AS \"Difference €\" "
      f"{LINES} AND l.compactor_id IS NOT NULL GROUP BY i.invoice_id, i.operator_name, l.compactor_id, i.period_from, i.period_to "
      "ORDER BY i.invoice_id, l.compactor_id", 0, 13, 24, 8,
      field={"defaults": {}, "overrides": [o_unit("Billed €", "currencyEUR"), o_unit("Difference €", "currencyEUR")]}, options=TABLE),
    P("Every lift the board measured", "table",
      f"SELECT p.done_at AS \"Emptied\", c.customer_name AS \"Customer\", p.compactor_id AS \"Compactor\", c.material AS \"Material\", "
      f"c.operator_name AS \"Waste company\", p.load_before_pct AS \"Load %\", p.kg_collected AS \"kg\", "
      f"round({COST}::numeric, 2) AS \"Estimated €\", p.co2_kg AS \"CO₂ saved kg\" {PICK} ORDER BY p.done_at DESC LIMIT 1000",
      0, 21, 24, 10, field={"defaults": {"custom": {"filterable": True}}, "overrides": [o_unit("Estimated €", "currencyEUR")]}, options=TABLE),
], [V_CUST, V_OP])

# ------------------------------------------------------------------ 3 WASTE COMPANIES
OP_PICK = ("SELECT c.operator_name AS op, count(*) AS lifts, avg(CASE WHEN p.verdict = 'ON_TIME' THEN 100.0 ELSE 0 END) AS on_time, "
           "avg(p.load_before_pct) AS load, sum(CASE WHEN p.verdict = 'TOO_EARLY' THEN 1 ELSE 0 END) AS early, "
           "sum(CASE WHEN p.verdict = 'TOO_LATE' THEN 1 ELSE 0 END) AS late FROM pickups p JOIN compactors c ON c.id = p.compactor_id "
           f"WHERE p.status = 'done' AND {CW} AND $__timeFilter(p.done_at) GROUP BY 1")
OP_INV = ("SELECT i.operator_name AS op, count(*) AS invoices, 100.0 * sum(i.lines_ok) / NULLIF(sum(i.lines_total), 0) AS lines_ok, "
          f"sum(i.overcharged_eur) AS over, sum(i.unverified_eur) AS proof FROM invoices i {INV_LATEST} WHERE {IW} GROUP BY 1")
operators = page("cockpit-operators", "3 Waste companies",
"""### Which waste company performs best?
**Lifts at ≥60 %** = emptied when the container was worth it and not left full. **Invoice lines correct** = lines that match the board's measurement and the customer's prices. Facts for contract talks, not blame — a sensor can be wrong too.""",
[
    P("Lifts at ≥60 % (on time)", "bargauge", f"SELECT op AS \"Waste company\", round(on_time::numeric) AS \"%\" FROM ({OP_PICK}) x ORDER BY 2 DESC",
      0, 3, 8, 7, field={"defaults": {"unit": "percent", "min": 0, "max": 100}, "overrides": []}, options=BAR("/%/")),
    P("Invoice lines correct", "bargauge", f"SELECT op AS \"Waste company\", round(lines_ok::numeric) AS \"%\" FROM ({OP_INV}) x ORDER BY 2 DESC",
      8, 3, 8, 7, field={"defaults": {"unit": "percent", "min": 0, "max": 100}, "overrides": []}, options=BAR("/%/")),
    P("Charged too much", "bargauge", f"SELECT op AS \"Waste company\", round(over::numeric) AS \"EUR\" FROM ({OP_INV}) x ORDER BY 2 DESC",
      16, 3, 8, 7, field={"defaults": {"unit": "currencyEUR", "decimals": 0}, "overrides": []}, options=BAR("/EUR/")),
    P("Scorecard", "table",
      "SELECT coalesce(a.op, b.op) AS \"Waste company\", a.lifts AS \"Lifts\", round(a.on_time::numeric) AS \"At ≥60 % %\", "
      "round(a.load::numeric) AS \"Avg load at lift %\", a.early AS \"Too early\", a.late AS \"Left full 2h+\", b.invoices AS \"Invoices\", "
      "round(b.lines_ok::numeric) AS \"Lines correct %\", round(b.over::numeric, 2) AS \"Charged too much €\", round(b.proof::numeric, 2) AS \"Needs proof €\" "
      f"FROM ({OP_PICK}) a FULL JOIN ({OP_INV}) b ON b.op = a.op ORDER BY 1", 0, 10, 24, 8,
      field={"defaults": {}, "overrides": [o_unit("Charged too much €", "currencyEUR"), o_unit("Needs proof €", "currencyEUR")]}, options=TABLE),
], [V_CUST, V_OP])

# ------------------------------------------------------------------ 4 INVOICES
invoices_pg = page("cockpit-actions", "4 Invoices",
"""### Enter an invoice, see it compared with what the board measured, then decide
**Enter an invoice** tab: type in the waste company's invoice (or *Fill from measurement* and change a number). It is checked at once: lifts against the board's emptyings, tonnes against the measured weight, prices against the customer's prices. **Check & decide** tab: read every line, then **Approve**, **Reject** or **Hold** with your name — every decision is kept.""",
[
    P("Waiting", "stat", f"SELECT count(*) AS v FROM invoices i {INV_LATEST} WHERE {IW} AND d.decision IS NULL", 0, 3, 4, 4, field=NUM, options=STAT),
    P("To check", "stat", f"SELECT count(*) AS v FROM invoices i {INV_LATEST} WHERE {IW} AND d.decision IS NULL AND i.suggestion = 'CHECK'",
      4, 3, 4, 4, field=NUM, options=STAT),
    P("Charged too much (waiting)", "stat", f"SELECT round(sum(i.overcharged_eur)::numeric) AS v FROM invoices i {INV_LATEST} WHERE {IW} AND d.decision IS NULL",
      8, 3, 4, 4, field=EUR, options=STAT),
    P("Approved", "stat", f"SELECT count(*) AS v FROM invoices i {INV_LATEST} WHERE {IW} AND d.decision = 'APPROVE'", 12, 3, 4, 4, field=NUM, options=STAT),
    P("Rejected", "stat", f"SELECT count(*) AS v FROM invoices i {INV_LATEST} WHERE {IW} AND d.decision = 'REJECT'", 16, 3, 4, 4, field=NUM, options=STAT),
    P("On hold", "stat", f"SELECT count(*) AS v FROM invoices i {INV_LATEST} WHERE {IW} AND d.decision = 'HOLD'", 20, 3, 4, 4, field=NUM, options=STAT),
    embed("Invoices — enter, compare, decide", "/invoices", 7, 21, 630),
    P("All invoices", "table",
      f"SELECT {STATUS_SQL} AS \"Status\", i.invoice_id AS \"Invoice\", i.customer_name AS \"Customer\", i.operator_name AS \"Waste company\", "
      "i.period_from AS \"From\", i.period_to AS \"To\", i.total_eur AS \"Billed €\", i.overcharged_eur AS \"Charged too much €\", "
      "i.unverified_eur AS \"Needs proof €\", i.lines_ok || ' / ' || i.lines_total AS \"Lines ok\", i.summary AS \"Check\", "
      f"d.decided_by AS \"Decided by\" FROM invoices i {INV_LATEST} WHERE {IW} ORDER BY i.entered_at DESC",
      0, 28, 24, 9, field={"defaults": {"custom": {"filterable": True}}, "overrides": [o_unit("Billed €", "currencyEUR"),
          o_unit("Charged too much €", "currencyEUR"), o_unit("Needs proof €", "currencyEUR"), o_width("Status", 90), o_map("Status", STATUS_COLOURS)]},
      options=TABLE),
], [V_CUST, V_OP])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sql":   # print every query with filters set to "all", for testing
        for s in SQL:
            for f in ["p.done_at", "a.ts"]:
                s = s.replace(f"$__timeFilter({f})", f"{f} > now() - interval '7 days'")
            for v in ["$customer", "$operator"]:
                s = s.replace(f"IN ({v})", "IS NOT NULL OR TRUE")
            print(s + ";")
    else:
        out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
        for old in out.glob("cockpit_*.json"):
            old.unlink()                                  # older page sets (Europress dataset pages) are gone
        for name, d in [("cockpit_1_problems", problems), ("cockpit_2_cost_weight", cost),
                        ("cockpit_3_operators", operators), ("cockpit_4_invoices", invoices_pg)]:
            (out / f"{name}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written to {out}")
