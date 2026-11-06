"""Generate the multi-page Customer Value Cockpit (Grafana). Output: grafana/dashboards/cockpit_*.json"""
import json, sys
from pathlib import Path
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "sql" else None
DS = {"type": "grafana-postgresql-datasource", "uid": "compactor-pg"}
TIME = {"from": "2025-10-01T00:00:00Z", "to": "2026-10-15T00:00:00Z"}
LATEST = ("LEFT JOIN (SELECT ad.* FROM action_decisions ad JOIN (SELECT action_id, MAX(id) AS max_id FROM action_decisions "
          "GROUP BY action_id) m ON m.max_id = ad.id) d ON d.action_id = a.action_id")
STATUS = "COALESCE(CASE d.decision WHEN 'APPROVE' THEN 'approved' WHEN 'REJECT' THEN 'rejected' END, 'pending')"
NICE = "replace(lower(label_family), '_', ' ')"
ALL_SQL = []

def var(name, label, sql):
    ALL_SQL.append(sql)
    return {"name": name, "label": label, "type": "query", "datasource": DS, "query": sql, "definition": sql,
            "multi": True, "includeAll": True, "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
            "refresh": 1, "sort": 1}

def page(uid, title, intro, panels, variables=()):
    pid = 0
    out = []
    # how-to-read box on top of every page
    out.append({"id": 100, "type": "text", "title": "How to read this page", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 4},
                "options": {"mode": "markdown", "content": intro}})
    for p in panels:
        pid += 1
        p["id"] = pid
        p.setdefault("datasource", DS)
        for t in p.get("targets", []):
            ALL_SQL.append(t["rawSql"])
        out.append(p)
    return {"uid": uid, "title": title, "tags": ["europress-cockpit"], "timezone": "browser", "schemaVersion": 39, "version": 1,
            "refresh": "1m", "time": TIME, "graphTooltip": 1, "editable": True,
            "description": "SYNTHETIC DATA (Europress SMART Material Value Engine v1.0.1). Proposals need human approval.",
            "links": [{"title": "Cockpit pages", "type": "dashboards", "tags": ["europress-cockpit"], "asDropdown": False,
                       "includeVars": False, "keepTime": True},
                      {"title": "Approve actions", "type": "link", "url": "http://localhost:8000/cockpit", "targetBlank": True, "icon": "external link"}],
            "panels": out, "templating": {"list": list(variables)}}

def P(title, typ, sql, x, y, w, h, fmt="table", field=None, options=None, desc=""):
    return {"title": title, "description": desc, "type": typ, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [{"refId": "A", "datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True, "rawSql": sql}],
            "fieldConfig": field or {"defaults": {}, "overrides": []}, "options": options or {}}

STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "none", "graphMode": "none",
        "textMode": "value", "justifyMode": "center"}
EUR0 = {"defaults": {"unit": "currencyEUR", "decimals": 0}, "overrides": []}
def unit_over(name, unit): return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "unit", "value": unit}]}
def width_over(name, w): return {"matcher": {"id": "byName", "options": name}, "properties": [{"id": "custom.width", "value": w}]}
def color_bg(name, steps): return {"matcher": {"id": "byName", "options": name}, "properties": [
    {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
    {"id": "thresholds", "value": {"mode": "absolute", "steps": steps}}]}
GREEN_RED = lambda a, b: [{"color": "transparent", "value": None}, {"color": "orange", "value": a}, {"color": "red", "value": b}]
BARH = lambda fields: {"orientation": "horizontal", "displayMode": "gradient", "valueMode": "color", "showUnfilled": True,
                       "namePlacement": "left", "reduceOptions": {"calcs": ["lastNotNull"], "fields": fields, "values": True}}
TABLE = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}

V_CUST = var("customer", "Customer", "SELECT DISTINCT customer_name FROM cp_collections WHERE customer_name IS NOT NULL ORDER BY 1")
V_OP = var("operator", "Operator", "SELECT DISTINCT operator_name FROM cp_collections WHERE operator_name IS NOT NULL ORDER BY 1")
V_FAM = var("finding", "Finding type", f"SELECT DISTINCT label_family FROM cp_flags ORDER BY 1")
V_MAT = var("material", "Material", "SELECT DISTINCT material_stream FROM cp_collections WHERE material_stream IS NOT NULL ORDER BY 1")

# ---------------------------------------------------------------- 1 OVERVIEW
overview = page("value-cockpit", "1 · Overview — Customer Value Cockpit",
"""**The whole year in one screen** (synthetic data). Top row = the four numbers to remember.
**Net material contribution** is negative = customers pay much more for collection and treatment than they get back as material credit.
**€ at stake** = estimated money behind all findings — things to *check*, not proven savings. Click the page names above to go deeper:
**2 · Findings** (what went wrong) · **3 · Cost & weight** (€ per tonne, scale vs weighbridge) · **4 · Operators** (neutral scorecard) · **5 · Actions** (what a person should approve).""",
[
 P("Lifts in 12 months", "stat", "SELECT count(*) AS \"Lifts\" FROM cp_collections WHERE status = 'COMPLETED'", 0, 4, 6, 4, options=STAT,
   desc="Completed collections (the truck emptied the container)."),
 P("Net material contribution", "stat", "SELECT round(sum(net_material_contribution_eur)::numeric) AS v FROM cp_collections", 6, 4, 6, 4, field=EUR0, options=STAT,
   desc="Material credits minus collection, processing and penalties, under the (hypothetical) customer–operator contracts."),
 P("€ at stake in findings", "stat", "SELECT round(sum(eur_at_stake)::numeric) AS v FROM cp_flags", 12, 4, 6, 4, field=EUR0, options=STAT,
   desc="Estimated: euro impact of all findings. To be checked by a person."),
 P("Actions waiting for a person", "stat", f"SELECT count(*) AS v FROM cp_actions a {LATEST} WHERE d.decision IS NULL OR d.decision = 'REVERT'",
   18, 4, 6, 4, options=STAT, desc="Proposals not yet approved or rejected. Approve them on page 5 / the approval page."),
 P("Where the money is — € at stake by finding type", "bargauge",
   f"SELECT {NICE} AS \"Finding\", round(sum(eur_at_stake)::numeric) AS \"EUR\" FROM cp_flags GROUP BY 1 HAVING sum(eur_at_stake) > 0 ORDER BY 2 DESC",
   0, 8, 12, 10, field=EUR0, options=BARH("/EUR/"), desc="Longest bar = biggest money pool to look at first."),
 P("Who is affected — top 10 customers by € at stake", "bargauge",
   "SELECT customer_name AS \"Customer\", round(sum(eur_at_stake)::numeric) AS \"EUR\" FROM cp_flags WHERE customer_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
   12, 8, 12, 10, field=EUR0, options=BARH("/EUR/")),
 P("Findings per month", "timeseries",
   "SELECT date_trunc('month', found_at) AS \"time\", CASE entity_type WHEN 'collection' THEN 'lift findings' ELSE 'invoice findings' END AS metric, count(*) AS n "
   "FROM cp_flags WHERE $__timeFilter(found_at) GROUP BY 1, 2 ORDER BY 1", 0, 18, 24, 8, fmt="time_series",
   field={"defaults": {"min": 0, "custom": {"drawStyle": "bars", "fillOpacity": 70, "stacking": {"mode": "normal"}, "barAlignment": 0}}, "overrides": []},
   options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}),
])

# ---------------------------------------------------------------- 2 FINDINGS
fwhere = "customer_name IN ($customer) AND operator_name IN ($operator) AND label_family IN ($finding)"
findings = page("cockpit-findings", "2 · Findings — what looks wrong",
"""**Every irregularity the system found**, with a plain-language explanation and the evidence. Use the filters at the top (customer, operator, finding type).
**Source record** = the exact lift or invoice line in the data (row-level audit trail). A finding is a **discrepancy to check, not an accusation** — causes can be the sensor, data gaps or combined truck loads.
Tip: sort the table by **€ at stake** (click the column header).""",
[
 P("Findings by type", "bargauge", f"SELECT {NICE} AS \"Finding\", count(*) AS \"Count\" FROM cp_flags WHERE {fwhere} GROUP BY 1 ORDER BY 2 DESC",
   0, 4, 8, 11, options=BARH("/Count/")),
 P("Lift findings vs invoice findings", "piechart",
   f"SELECT CASE entity_type WHEN 'collection' THEN 'lift' ELSE 'invoice line' END AS \"Type\", count(*) AS \"Count\" FROM cp_flags WHERE {fwhere} GROUP BY 1",
   8, 4, 6, 11, options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/Count/", "values": True}, "pieType": "donut",
                         "legend": {"displayMode": "list", "placement": "bottom", "values": ["value"]}}),
 P("Findings over time", "timeseries",
   f"SELECT date_trunc('week', found_at) AS \"time\", count(*) AS findings FROM cp_flags WHERE {fwhere} AND $__timeFilter(found_at) GROUP BY 1 ORDER BY 1",
   14, 4, 10, 11, fmt="time_series", field={"defaults": {"min": 0, "custom": {"drawStyle": "bars", "fillOpacity": 70}}, "overrides": []}),
 P("All findings (newest first) — click a column to sort", "table",
   f"SELECT found_at AS \"Date\", {NICE} AS \"Finding\", customer_name AS \"Customer\", site_name AS \"Site\", operator_name AS \"Operator\", "
   f"explanation AS \"What it means\", evidence AS \"Evidence\", eur_at_stake AS \"€ at stake\", entity_id AS \"Source record\" "
   f"FROM cp_flags WHERE {fwhere} AND $__timeFilter(found_at) ORDER BY found_at DESC LIMIT 1000",
   0, 15, 24, 16, field={"defaults": {"custom": {"filterable": True}}, "overrides": [unit_over("€ at stake", "currencyEUR"),
       width_over("Date", 110), width_over("Finding", 170), width_over("€ at stake", 95), width_over("Source record", 190)]}, options=TABLE),
], [V_CUST, V_OP, V_FAM])

# ---------------------------------------------------------------- 3 COST & WEIGHT
cwhere = "customer_name IN ($customer) AND material_stream IN ($material)"
cost = page("cockpit-cost", "3 · Cost & weight — € per tonne and the scale",
"""**€ per tonne (€/t) is the key cost number** — it needs a known weight. *% of benchmark* above 100 = more expensive than similar contracts (orange > 130 %, red > 200 %).
*% measured weight* = share of lifts where the weight came from a weighbridge ticket or the invoice (**observed**) instead of the device (**estimated**). No weight → no €/t (we never invent it).
Bottom: lifts where **our scale and the operator's weighbridge disagree by > 10 %** — the reason independent weighing matters. Causes can be either side.""",
[
 P("Average €/t by material", "bargauge",
   f"SELECT material_stream AS \"Material\", round(avg(collection_cost_eur_per_t)::numeric) AS \"EUR per t\" FROM cp_collections "
   f"WHERE collection_cost_eur_per_t IS NOT NULL AND {cwhere} GROUP BY 1 ORDER BY 2 DESC", 0, 4, 8, 9,
   field={"defaults": {"unit": "currencyEUR", "decimals": 0}, "overrides": []}, options=BARH("/EUR per t/")),
 P("Where the weight comes from", "piechart",
   f"SELECT CASE mass_evidence WHEN 'OBSERVED' THEN 'measured (ticket / invoice)' WHEN 'ESTIMATED' THEN 'device estimate' ELSE 'unknown' END AS \"Source\", "
   f"count(*) AS \"Lifts\" FROM cp_collections WHERE status = 'COMPLETED' AND {cwhere} GROUP BY 1", 8, 4, 6, 9,
   options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/Lifts/", "values": True}, "pieType": "donut",
            "legend": {"displayMode": "list", "placement": "bottom", "values": ["percent"]}}),
 P("Scale vs weighbridge: share of lifts with > 10 % difference, by operator", "bargauge",
   "SELECT operator_name AS \"Operator\", round((100.0 * avg(CASE WHEN abs(weighbridge_net_kg - device_estimated_collected_kg) > 0.1 * device_estimated_collected_kg "
   "THEN 1 ELSE 0 END))::numeric, 1) AS \"% of lifts\" FROM cp_collections WHERE weighbridge_net_kg IS NOT NULL AND device_estimated_collected_kg > 200 "
   f"AND {cwhere} GROUP BY 1 ORDER BY 2 DESC", 14, 4, 10, 9,
   field={"defaults": {"unit": "percent", "decimals": 1, "min": 0}, "overrides": []}, options=BARH("/% of lifts/")),
 P("Cost per tonne by site (most expensive first)", "table",
   "SELECT customer_name AS \"Customer\", site_name AS \"Site\", material_stream AS \"Material\", count(*) AS \"Lifts\", "
   "round(avg(collection_cost_eur_per_t)::numeric) AS \"€/t\", round(avg(benchmark_eur_per_t)::numeric) AS \"Benchmark €/t\", "
   "round((avg(collection_cost_eur_per_t) / NULLIF(avg(benchmark_eur_per_t), 0) * 100)::numeric) AS \"% of benchmark\", "
   "round((100.0 * avg(CASE WHEN mass_evidence = 'OBSERVED' THEN 1 ELSE 0 END))::numeric) AS \"% measured weight\" "
   f"FROM cp_collections WHERE collection_cost_eur_per_t IS NOT NULL AND {cwhere} GROUP BY 1, 2, 3 ORDER BY 7 DESC NULLS LAST LIMIT 200",
   0, 13, 24, 10, field={"defaults": {"custom": {"filterable": True}}, "overrides": [color_bg("% of benchmark", GREEN_RED(130, 200)),
       unit_over("€/t", "currencyEUR"), unit_over("Benchmark €/t", "currencyEUR")]}, options=TABLE),
 P("Lifts where scale and weighbridge differ by > 10 %", "table",
   "SELECT service_date AS \"Date\", customer_name AS \"Customer\", device_id AS \"Device\", operator_name AS \"Operator\", "
   "device_estimated_collected_kg AS \"Our scale kg\", weighbridge_net_kg AS \"Weighbridge kg\", "
   "round((100.0 * (weighbridge_net_kg - device_estimated_collected_kg) / NULLIF(device_estimated_collected_kg, 0))::numeric, 1) AS \"Difference %\", "
   "operator_job_ref AS \"Job ref\" FROM cp_collections WHERE weighbridge_net_kg IS NOT NULL AND device_estimated_collected_kg > 200 "
   f"AND abs(weighbridge_net_kg - device_estimated_collected_kg) > 0.1 * device_estimated_collected_kg AND {cwhere} "
   "AND $__timeFilter(service_date) ORDER BY abs(weighbridge_net_kg - device_estimated_collected_kg) DESC LIMIT 500",
   0, 23, 24, 10, field={"defaults": {"custom": {"filterable": True}}, "overrides": [color_bg("Difference %", [
       {"color": "red", "value": None}, {"color": "transparent", "value": -10}, {"color": "red", "value": 10}])]}, options=TABLE),
], [V_CUST, V_MAT])

# ---------------------------------------------------------------- 4 OPERATORS
owhere = "operator_name IN ($operator)"
ops = page("cockpit-operators", "4 · Operators — neutral performance scorecard",
"""**How each (fictional) waste operator performs**, measured from the customer's own records. Higher is better for *on time* and *tickets shared*; lower is better for the rest.
Use it as **facts for contract talks**, not blame: weight bias and billing differences can also come from device sensors, combined truck loads or missing data.""",
[
 P("On-time lifts %", "bargauge", f"SELECT operator_name AS \"Operator\", round((100 * avg(on_time_rate))::numeric, 1) AS \"On time %\" FROM cp_scorecard WHERE {owhere} GROUP BY 1 ORDER BY 2 DESC",
   0, 4, 8, 8, field={"defaults": {"unit": "percent", "min": 0, "max": 100, "decimals": 1}, "overrides": []}, options=BARH("/On time/")),
 P("Weighbridge tickets shared within 7 days %", "bargauge",
   f"SELECT operator_name AS \"Operator\", round((100 * avg(weighbridge_shared_7d_rate))::numeric, 1) AS \"Shared %\" FROM cp_scorecard WHERE {owhere} GROUP BY 1 ORDER BY 2 DESC",
   8, 4, 8, 8, field={"defaults": {"unit": "percent", "min": 0, "max": 100, "decimals": 1}, "overrides": []}, options=BARH("/Shared/")),
 P("Invoice lines that differ from the contract %", "bargauge",
   f"SELECT operator_name AS \"Operator\", round((100 * avg(discrepant_line_rate))::numeric, 2) AS \"Discrepant %\" FROM cp_scorecard WHERE {owhere} GROUP BY 1 ORDER BY 2 DESC",
   16, 4, 8, 8, field={"defaults": {"unit": "percent", "min": 0, "decimals": 2}, "overrides": []}, options=BARH("/Discrepant/")),
 P("On-time rate per month", "timeseries",
   f"SELECT to_date(month, 'YYYY-MM') AS \"time\", operator_name AS metric, round((100 * avg(on_time_rate))::numeric, 1) AS v FROM cp_scorecard WHERE {owhere} GROUP BY 1, 2 ORDER BY 1",
   0, 12, 24, 8, fmt="time_series", field={"defaults": {"unit": "percent", "min": 0, "max": 100}, "overrides": []},
   options={"legend": {"displayMode": "list", "placement": "right"}}),
 P("Scorecard by operator and region (averages over the year)", "table",
   "SELECT operator_name AS \"Operator\", region_code AS \"Region\", round((100 * avg(on_time_rate))::numeric, 1) AS \"On time %\", "
   "round((100 * avg(missed_visit_rate))::numeric, 2) AS \"Missed visits %\", round((100 * avg(weighbridge_shared_7d_rate))::numeric, 1) AS \"Tickets shared ≤ 7 d %\", "
   "round(avg(median_share_lag_days)::numeric, 1) AS \"Sharing delay (days)\", round(avg(weight_bias_pct)::numeric, 2) AS \"Weight bias %\", "
   "round(avg(billing_overcharge_pct)::numeric, 2) AS \"Overcharge %\", round(avg(billing_undercharge_pct)::numeric, 2) AS \"Undercharge %\", "
   f"round((100 * avg(discrepant_line_rate))::numeric, 2) AS \"Discrepant lines %\" FROM cp_scorecard WHERE {owhere} GROUP BY 1, 2 ORDER BY 1, 2",
   0, 20, 24, 10, field={"defaults": {}, "overrides": [color_bg("On time %", [{"color": "red", "value": None}, {"color": "orange", "value": 60}, {"color": "transparent", "value": 80}]),
       color_bg("Tickets shared ≤ 7 d %", [{"color": "red", "value": None}, {"color": "orange", "value": 50}, {"color": "transparent", "value": 80}])]}, options=TABLE),
], [V_OP])

# ---------------------------------------------------------------- 5 ACTIONS
awhere = "a.customer_name IN ($customer) AND a.operator_name IN ($operator)"
acts = page("cockpit-actions", "5 · Actions — proposals for a person to approve",
"""**The system only proposes; a person decides.** Each row = one proposed action for a contract: *dispute invoice*, *request weighbridge data*, *renegotiate contract*, *tender / switch operator*.
**Flagged €** = invoice lines that differ from the contract for that device (estimated). To decide: open the **Approve actions** link (top right) → *Show evidence* → Approve / Reject (with your name and a note).
Every decision is logged and can be reverted; this page updates within a minute.""",
[
 P("Pending", "stat", f"SELECT count(*) AS v FROM cp_actions a {LATEST} WHERE ({awhere}) AND (d.decision IS NULL OR d.decision = 'REVERT')", 0, 4, 6, 4, options=STAT),
 P("Approved", "stat", f"SELECT count(*) AS v FROM cp_actions a {LATEST} WHERE ({awhere}) AND d.decision = 'APPROVE'", 6, 4, 6, 4, options=STAT),
 P("Rejected", "stat", f"SELECT count(*) AS v FROM cp_actions a {LATEST} WHERE ({awhere}) AND d.decision = 'REJECT'", 12, 4, 6, 4, options=STAT),
 P("Flagged € behind pending proposals", "stat",
   f"SELECT round(sum(a.flagged_invoice_eur)::numeric) AS v FROM cp_actions a {LATEST} WHERE ({awhere}) AND (d.decision IS NULL OR d.decision = 'REVERT')",
   18, 4, 6, 4, field=EUR0, options=STAT),
 P("Proposals by type", "bargauge",
   f"SELECT replace(lower(a.action), '_', ' ') AS \"Action\", count(*) AS \"Count\" FROM cp_actions a WHERE {awhere} GROUP BY 1 ORDER BY 2 DESC",
   0, 8, 10, 8, options=BARH("/Count/")),
 P("Proposals by operator", "bargauge",
   f"SELECT a.operator_name AS \"Operator\", count(*) AS \"Count\" FROM cp_actions a WHERE {awhere} GROUP BY 1 ORDER BY 2 DESC",
   10, 8, 14, 8, options=BARH("/Count/")),
 P("All proposals (biggest flagged € first)", "table",
   f"SELECT {STATUS} AS \"Status\", replace(lower(a.action), '_', ' ') AS \"Proposed action\", a.customer_name AS \"Customer\", a.operator_name AS \"Operator\", "
   f"a.contract_id AS \"Contract\", a.flagged_invoice_eur AS \"Flagged €\", a.notice_period_days AS \"Notice (days)\", d.decided_by AS \"Decided by\", "
   f"a.rationale AS \"Why\" FROM cp_actions a {LATEST} WHERE {awhere} ORDER BY a.flagged_invoice_eur DESC",
   0, 16, 24, 14, field={"defaults": {"custom": {"filterable": True}}, "overrides": [unit_over("Flagged €", "currencyEUR"), width_over("Status", 95),
       {"matcher": {"id": "byName", "options": "Status"}, "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
        {"id": "mappings", "value": [{"type": "value", "options": {"pending": {"color": "orange", "text": "⏳ pending"},
                                                                   "approved": {"color": "green", "text": "✔ approved"},
                                                                   "rejected": {"color": "red", "text": "✖ rejected"}}}]}]}]}, options=TABLE),
], [V_CUST, V_OP])

if OUT:
    for name, d in [("cockpit_1_overview", overview), ("cockpit_2_findings", findings), ("cockpit_3_cost_weight", cost),
                    ("cockpit_4_operators", ops), ("cockpit_5_actions", acts)]:
        (OUT / f"{name}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False))
    print("written")
else:
    for s in ALL_SQL:
        s = (s.replace("$__timeFilter(found_at)", "found_at > now() - interval '3 years'")
              .replace("$__timeFilter(service_date)", "service_date > now() - interval '3 years'"))
        for v in ["$customer", "$operator", "$finding", "$material"]:
            col = {"$customer": "customer_name", "$operator": "operator_name", "$finding": "label_family", "$material": "material_stream"}[v]
            s = s.replace(f"IN ({v})", f"IS NOT NULL OR {col} IS NULL")
        print(s + ";")
