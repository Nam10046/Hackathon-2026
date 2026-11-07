"""Generate the Customer Value Cockpit pages for Grafana (simple version).

    python grafana/make_cockpit_pages.py            # writes grafana/dashboards/cockpit_*.json

Design rules: one fixed menu (same order on every page, current page included), max ~5 panels per page,
plain-language names instead of codes, every panel title says what you are looking at.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "compactor-pg"}
TIME = {"from": "2025-10-01T00:00:00Z", "to": "2026-10-15T00:00:00Z"}

PAGES = [  # (uid, menu label)
    ("value-cockpit", "1 Overview"), ("cockpit-findings", "2 Problems found"), ("cockpit-cost", "3 Cost & weight"),
    ("cockpit-operators", "4 Waste companies"), ("cockpit-actions", "5 Decisions"),
]
LIVE_PAGES = [  # the live product, fed only by the ESP32 edge node (grafana/make_live_pages.py)
    ("smart-compactor", "Site now"), ("live-pickups", "Pickups"), ("live-money", "Money & CO₂"), ("edge-live", "Devices"),
]

# plain-language names for the codes in the data
PROBLEM = {
    "COST_PER_T_HIGH": "Very high cost per tonne", "PREMATURE_UNJUSTIFIED": "Emptied too early",
    "DELAYED_COLLECTION": "Emptied too late (overflow risk)", "WEIGHT_DISCREPANCY": "Our scale and truck scale disagree",
    "CONTAMINATION_VALUE_LOSS": "Dirty load lost its value", "REJECTED_LOAD": "Load rejected",
    "OUTDATED_TARIFF": "Old price on invoice", "DUPLICATE_LINE": "Charged twice", "WRONG_SURCHARGE": "Wrong extra fee",
    "WEIGHT_BASIS_MISMATCH": "Invoice tonnes differ from truck scale", "UNMATCHED_LINE": "Charge without a lift",
    "MISSING_LINE": "Charge or credit missing", "UNINVOICED_COLLECTION": "Lift never invoiced",
}
ACTION = {
    "DISPUTE_INVOICE": "Ask the operator to correct the invoice", "REQUEST_WEIGHBRIDGE_DATA": "Ask for the weight tickets",
    "RENEGOTIATE_CONTRACT": "Renegotiate the price", "TENDER_OR_SWITCH_OPERATOR": "Get offers from other waste companies",
}
MATERIAL = {"cardboard": "Cardboard", "mixed_waste": "Mixed waste", "plastic_film": "Plastic film", "biowaste": "Bio waste",
            "paper": "Paper", "mixed_plastic": "Mixed plastic"}


def case(col, mapping):
    return "CASE " + col + " " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in mapping.items()) + f" ELSE {col} END"


PROB, ACT, MAT = case("label_family", PROBLEM), case("a.action", ACTION), case("material_stream", MATERIAL)
LATEST = ("LEFT JOIN (SELECT ad.* FROM action_decisions ad JOIN (SELECT action_id, MAX(id) AS max_id FROM action_decisions "
          "GROUP BY action_id) m ON m.max_id = ad.id) d ON d.action_id = a.action_id")
OPEN = "(d.decision IS NULL OR d.decision = 'REVERT')"
SQL = []


def menu_text(current_uid):
    """The page menu as its own line (a text panel), so filters can never squeeze it.
    Two parts: the LIVE product (ESP32 data only) and the ANALYSIS of the Europress history (dataset)."""
    def items(pages):
        return " · ".join(f"**● {label}**" if uid == current_uid else f"[{label}](/d/{uid})" for uid, label in pages)
    return (f"🟢 **Live (ESP32):** {items(LIVE_PAGES)} &nbsp;&nbsp;|&nbsp;&nbsp; 📊 **Analysis (Europress history):** {items(PAGES)}"
            " &nbsp;·&nbsp; [Approve decisions ↗](http://localhost:8000/cockpit)")


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
        for t in p["targets"]:
            SQL.append(t["rawSql"])
        out.append(p)
    return {"uid": uid, "title": title, "tags": ["europress-cockpit"], "timezone": "browser", "schemaVersion": 39, "version": 3,
            "refresh": "1m", "time": TIME, "graphTooltip": 1, "editable": True, "links": [],
            "description": "SYNTHETIC DATA (Europress dataset v1.0.1). Proposals need human approval.",
            "panels": out, "templating": {"list": list(variables)}}


def P(title, typ, sql, x, y, w, h, fmt="table", field=None, options=None, desc=""):
    field = field or {"defaults": {}, "overrides": []}
    if typ == "bargauge":
        field["defaults"]["color"] = {"mode": "fixed", "fixedColor": "#5794F2"}
    return {"title": title, "description": desc, "type": typ, "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [{"refId": "A", "datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True, "rawSql": sql}],
            "fieldConfig": field, "options": options or {}}


STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "none", "graphMode": "none",
        "textMode": "value", "justifyMode": "center", "wideLayout": True}
EUR = {"defaults": {"unit": "currencyEUR", "decimals": 0}, "overrides": []}
EUR1 = {"defaults": {"unit": "currencyEUR", "decimals": 1}, "overrides": []}   # big totals: €6.1M, not €6M
BAR = lambda f: {"orientation": "horizontal", "displayMode": "basic", "valueMode": "text", "showUnfilled": True,  # noqa: E731
                 "namePlacement": "left", "sizing": "auto", "reduceOptions": {"calcs": ["lastNotNull"], "fields": f, "values": True}}
TABLE = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}


def o_unit(n, u): return {"matcher": {"id": "byName", "options": n}, "properties": [{"id": "unit", "value": u}]}
def o_width(n, w): return {"matcher": {"id": "byName", "options": n}, "properties": [{"id": "custom.width", "value": w}]}
def o_colour(n, steps):
    return {"matcher": {"id": "byName", "options": n}, "properties": [
        {"id": "custom.cellOptions", "value": {"type": "color-text"}},
        {"id": "thresholds", "value": {"mode": "absolute", "steps": steps}}]}


V_CUST = var("customer", "Customer", "SELECT DISTINCT customer_name FROM cp_collections WHERE customer_name IS NOT NULL ORDER BY 1")
V_OP = var("operator", "Waste company", "SELECT DISTINCT operator_name FROM cp_collections WHERE operator_name IS NOT NULL ORDER BY 1")
V_PROB = var("problem", "Problem", f"SELECT DISTINCT {PROB} AS __text, label_family AS __value FROM cp_flags ORDER BY 1")
V_MAT = var("material", "Material", f"SELECT DISTINCT {MAT} AS __text, material_stream AS __value FROM cp_collections WHERE material_stream IS NOT NULL ORDER BY 1")

# ------------------------------------------------------------------ 1 OVERVIEW
overview = page("value-cockpit", "1 Overview",
"""### One year of waste service for 52 customers (synthetic data)
Customers **paid** the waste companies the amount on the left and **got money back** for recyclables. Our system checked every lift and invoice line and found **issues** (the same problem on the same compactor counted once) with **money worth checking**. A person decides what to do — see *5 Decisions*.""",
[
    P("Paid for waste service", "stat", "SELECT round(sum(collection_cost_eur + processing_cost_eur + penalties_eur)::numeric) AS v FROM cp_collections",
      0, 3, 5, 4, field=EUR1, options=STAT, desc="Collection, treatment and penalty charges under the customer–operator contracts (hypothetical prices)."),
    P("Money back for recyclables", "stat", "SELECT round(sum(material_credit_eur)::numeric) AS v FROM cp_collections",
      5, 3, 5, 4, field=EUR1, options=STAT, desc="Material credits for cardboard and plastic."),
    P("Issues found", "stat", "SELECT count(*) AS v FROM cp_issues",
      10, 3, 5, 4, options=STAT, desc="Same problem on the same compactor = one issue (it may repeat on many lifts)."),
    P("Money worth checking", "stat", "SELECT round(sum(eur_at_stake)::numeric) AS v FROM cp_flags",
      15, 3, 5, 4, field=EUR, options=STAT, desc="Estimated euros behind all problems found. To check — not a proven saving."),
    P("Decisions waiting", "stat", f"SELECT count(*) AS v FROM cp_actions a {LATEST} WHERE {OPEN}",
      20, 3, 4, 4, options=STAT, desc="Proposals no person has approved or rejected yet."),
    P("Which problems cost the most?", "bargauge",
      f"SELECT {PROB} AS \"Problem\", round(sum(eur_at_stake)::numeric) AS \"EUR\" FROM cp_flags GROUP BY 1 HAVING sum(eur_at_stake) > 0 ORDER BY 2 DESC",
      0, 7, 12, 11, field=EUR, options=BAR("/EUR/")),
    P("Which customers have the most to check?", "bargauge",
      "SELECT customer_name AS \"Customer\", round(sum(eur_at_stake)::numeric) AS \"EUR\" FROM cp_flags WHERE customer_name IS NOT NULL "
      "GROUP BY 1 ORDER BY 2 DESC LIMIT 10", 12, 7, 12, 11, field=EUR, options=BAR("/EUR/")),
])

# ------------------------------------------------------------------ 2 PROBLEMS FOUND
fw = "customer_name IN ($customer) AND operator_name IN ($operator) AND label_family IN ($problem)"
findings = page("cockpit-findings", "2 Problems found",
"""### Issues: the same problem on the same compactor, counted once
Pick a **customer**, **waste company** or **problem** at the top. **Times seen** = on how many lifts or invoice lines it happened. **Found by**: *AI model* or *rules*. **Likely cause**: operator, device, logistics, billing, data entry or normal noise.
The lower table lists every single record. It is a **difference to check, not an accusation** — the cause can also be a sensor or missing data.""",
[
    P("How many issues of each problem?", "bargauge",
      f"SELECT {PROB} AS \"Problem\", count(*) AS \"Issues\" FROM cp_issues WHERE {fw} GROUP BY 1 ORDER BY 2 DESC",
      0, 3, 8, 13, options=BAR("/Issues/")),
    P("Issues — biggest euros first", "table",
      f"SELECT customer_name AS \"Customer\", site_name AS \"Site\", {PROB} AS \"Problem\", times_seen AS \"Times seen\", "
      f"to_char(last_seen, 'YYYY-MM-DD') AS \"Last seen\", eur_at_stake AS \"Euros\", "
      f"CASE WHEN detected_by LIKE '%model%' OR detected_by LIKE '%(ML)%' THEN 'AI model' ELSE 'rules' END AS \"Found by\", "
      f"initcap(replace(COALESCE(side, ''), '_', ' ')) AS \"Likely cause\" "
      f"FROM cp_issues WHERE {fw} ORDER BY eur_at_stake DESC, times_seen DESC LIMIT 1000",
      8, 3, 16, 13, field={"defaults": {"custom": {"filterable": True}}, "overrides": [o_unit("Euros", "currencyEUR"),
          o_width("Times seen", 95), o_width("Last seen", 100), o_width("Euros", 90), o_width("Found by", 90), o_width("Likely cause", 110)]}, options=TABLE),
    P("Every single record (one row per lift or invoice line)", "table",
      f"SELECT to_char(found_at, 'YYYY-MM-DD') AS \"Date\", customer_name AS \"Customer\", {PROB} AS \"Problem\", "
      f"COALESCE(NULLIF(calculation, ''), NULLIF(evidence, ''), explanation) AS \"What the data shows\", likely_cause AS \"Likely cause\", "
      f"eur_at_stake AS \"Euros\", entity_id AS \"Record\" FROM cp_flags WHERE {fw} AND $__timeFilter(found_at) "
      "ORDER BY eur_at_stake DESC NULLS LAST, found_at DESC LIMIT 1000",
      0, 16, 24, 12, field={"defaults": {"custom": {"filterable": True}}, "overrides": [o_unit("Euros", "currencyEUR"),
          o_width("Date", 100), o_width("Problem", 230), o_width("Euros", 90), o_width("Record", 190)]}, options=TABLE),
], [V_CUST, V_OP, V_PROB])

# ------------------------------------------------------------------ 3 COST & WEIGHT
cw = "customer_name IN ($customer) AND material_stream IN ($material)"
cost = page("cockpit-cost", "3 Cost & weight",
"""### Who pays too much per tonne — and does our scale agree with the truck's?
**€ per tonne** = total collection euros ÷ total tonnes collected. *Times normal* compares it with similar contracts: **1.5** means paying 50 % more.
Bottom table: lifts where **our scale** and the **waste company's truck scale** disagree by more than 10 % — the reason independent weighing matters.""",
[
    P("€ per tonne vs normal, by material", "table",
      f"SELECT {MAT} AS \"Material\", round((sum(collection_cost_eur) / NULLIF(sum(mass_kg) / 1000, 0))::numeric) AS \"Paid € / t\", "
      "round(avg(benchmark_eur_per_t)::numeric) AS \"Normal € / t\", "
      "round((sum(collection_cost_eur) / NULLIF(sum(mass_kg) / 1000, 0) / NULLIF(avg(benchmark_eur_per_t), 0))::numeric, 1) AS \"Times normal\" "
      f"FROM cp_collections WHERE collection_cost_eur_per_t IS NOT NULL AND {cw} GROUP BY 1 ORDER BY 4 DESC",
      0, 3, 10, 9, field={"defaults": {}, "overrides": [o_colour("Times normal", [{"color": "text", "value": None},
          {"color": "orange", "value": 1.3}, {"color": "red", "value": 2}])]}, options=TABLE),
    P("Sites that pay the most per tonne", "table",
      f"SELECT customer_name AS \"Customer\", site_name AS \"Site\", {MAT} AS \"Material\", "
      "round((sum(collection_cost_eur) / NULLIF(sum(mass_kg) / 1000, 0))::numeric) AS \"Paid € / t\", "
      "round((sum(collection_cost_eur) / NULLIF(sum(mass_kg) / 1000, 0) / NULLIF(avg(benchmark_eur_per_t), 0))::numeric, 1) AS \"Times normal\" "
      f"FROM cp_collections WHERE collection_cost_eur_per_t IS NOT NULL AND {cw} GROUP BY 1, 2, 3 HAVING count(*) >= 5 ORDER BY 5 DESC NULLS LAST LIMIT 100",
      10, 3, 14, 9, field={"defaults": {"custom": {"filterable": True}}, "overrides": [o_colour("Times normal", [{"color": "text", "value": None},
          {"color": "orange", "value": 1.3}, {"color": "red", "value": 2}])]}, options=TABLE),
    P("Our scale vs truck scale: lifts that differ by more than 10 %", "table",
      f"SELECT to_char(service_date, 'YYYY-MM-DD') AS \"Date\", customer_name AS \"Customer\", operator_name AS \"Waste company\", "
      "round(device_estimated_collected_kg::numeric) AS \"Our scale (kg)\", round(weighbridge_net_kg::numeric) AS \"Truck scale (kg)\", "
      "round((100.0 * (weighbridge_net_kg - device_estimated_collected_kg) / NULLIF(device_estimated_collected_kg, 0))::numeric) AS \"Difference %\" "
      "FROM cp_collections WHERE weighbridge_net_kg IS NOT NULL AND device_estimated_collected_kg > 200 "
      f"AND abs(weighbridge_net_kg - device_estimated_collected_kg) > 0.1 * device_estimated_collected_kg AND {cw} "
      "AND $__timeFilter(service_date) ORDER BY abs(weighbridge_net_kg - device_estimated_collected_kg) DESC LIMIT 500",
      0, 12, 24, 12, field={"defaults": {"custom": {"filterable": True}}, "overrides": [o_unit("Difference %", "percent")]}, options=TABLE),
], [V_CUST, V_MAT])

# ------------------------------------------------------------------ 4 WASTE COMPANIES
ow = "operator_name IN ($operator)"
ops = page("cockpit-operators", "4 Waste companies",
"""### How each waste company performs (fictional companies)
**On time** and **tickets shared**: higher is better. **Invoice errors**: lower is better. Use these as facts for contract talks, not as blame —
some differences come from sensors or missing data.""",
[
    P("On time — share of lifts that came as planned", "bargauge",
      f"SELECT replace(operator_name, ' (fictional)', '') AS \"Waste company\", round((100 * avg(on_time_rate))::numeric) AS \"%\" FROM cp_scorecard WHERE {ow} GROUP BY 1 ORDER BY 2 DESC",
      0, 3, 8, 8, field={"defaults": {"unit": "percent", "min": 0, "max": 100}, "overrides": []}, options=BAR("/%/")),
    P("Tickets shared — truck weight sent to the customer within 7 days", "bargauge",
      f"SELECT replace(operator_name, ' (fictional)', '') AS \"Waste company\", round((100 * avg(weighbridge_shared_7d_rate))::numeric) AS \"%\" FROM cp_scorecard WHERE {ow} GROUP BY 1 ORDER BY 2 DESC",
      8, 3, 8, 8, field={"defaults": {"unit": "percent", "min": 0, "max": 100}, "overrides": []}, options=BAR("/%/")),
    P("Invoice errors — lines that differ from the contract", "bargauge",
      f"SELECT replace(operator_name, ' (fictional)', '') AS \"Waste company\", round((100 * avg(discrepant_line_rate))::numeric, 1) AS \"%\" FROM cp_scorecard WHERE {ow} GROUP BY 1 ORDER BY 2 DESC",
      16, 3, 8, 8, field={"defaults": {"unit": "percent", "min": 0, "decimals": 1}, "overrides": []}, options=BAR("/%/")),
    P("Details per region", "table",
      "SELECT operator_name AS \"Waste company\", region_code AS \"Region\", round((100 * avg(on_time_rate))::numeric) AS \"On time %\", "
      "round((100 * avg(missed_visit_rate))::numeric, 1) AS \"Missed visits %\", round((100 * avg(weighbridge_shared_7d_rate))::numeric) AS \"Tickets shared %\", "
      "round(avg(billing_overcharge_pct)::numeric, 1) AS \"Overcharged %\", round((100 * avg(discrepant_line_rate))::numeric, 1) AS \"Invoice errors %\", "
      "round(avg(weight_bias_pct) FILTER (WHERE weight_bias_status = 'MEASURED')::numeric, 1) AS \"Weight vs our scale % (measured)\", "
      "round((100.0 * count(*) FILTER (WHERE weight_bias_status = 'MEASURED') / count(*))::numeric) AS \"Months with weight evidence %\" "
      f"FROM cp_scorecard WHERE {ow} GROUP BY 1, 2 ORDER BY 1, 2", 0, 11, 24, 10, options=TABLE),
], [V_OP])

# ------------------------------------------------------------------ 5 DECISIONS
aw = "a.customer_name IN ($customer) AND a.operator_name IN ($operator)"
acts = page("cockpit-actions", "5 Decisions",
"""### What the system proposes — a person decides
Each row is one proposal, decided **only with data known on its decision date**. **Expected €** = chance it works × money × time left − effort (an estimate, with a low–high range).
Proposal values overlap, so **do not add them up as savings**. To decide, click **Approve decisions ↗** in the menu: open the evidence and calculation, then approve or reject with your name. Decisions are saved and can be undone.""",
[
    P("Waiting", "stat", f"SELECT count(*) AS v FROM cp_actions a {LATEST} WHERE ({aw}) AND {OPEN}", 0, 3, 6, 4, options=STAT),
    P("Approved", "stat", f"SELECT count(*) AS v FROM cp_actions a {LATEST} WHERE ({aw}) AND d.decision = 'APPROVE'", 6, 3, 6, 4, options=STAT),
    P("Rejected", "stat", f"SELECT count(*) AS v FROM cp_actions a {LATEST} WHERE ({aw}) AND d.decision = 'REJECT'", 12, 3, 6, 4, options=STAT),
    P("Invoice euros behind waiting proposals", "stat", f"SELECT round(sum(a.flagged_invoice_eur)::numeric) AS v FROM cp_actions a {LATEST} WHERE ({aw}) AND {OPEN}",
      18, 3, 6, 4, field=EUR, options=STAT),
    P("All proposals (biggest euros first)", "table",
      "SELECT COALESCE(CASE d.decision WHEN 'APPROVE' THEN 'approved' WHEN 'REJECT' THEN 'rejected' END, 'waiting') AS \"Status\", "
      f"{ACT} AS \"Proposal\", a.customer_name AS \"Customer\", a.operator_name AS \"Waste company\", "
      f"round(a.expected_value_eur::numeric) AS \"Expected €\", round(a.ev_low_eur::numeric) || ' … ' || round(a.ev_high_eur::numeric) AS \"Range €\", "
      f"a.flagged_invoice_eur AS \"Invoice € flagged\", a.calculation AS \"Calculation\", "
      f"d.decided_by AS \"Decided by\" FROM cp_actions a {LATEST} WHERE {aw} ORDER BY a.expected_value_eur DESC NULLS LAST, a.flagged_invoice_eur DESC",
      0, 7, 24, 18, field={"defaults": {"custom": {"filterable": True}}, "overrides": [o_unit("Expected €", "currencyEUR"), o_unit("Invoice € flagged", "currencyEUR"), o_width("Status", 100),
          o_width("Expected €", 100), o_width("Range €", 110), o_width("Invoice € flagged", 120),
          {"matcher": {"id": "byName", "options": "Status"}, "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
           {"id": "mappings", "value": [{"type": "value", "options": {"waiting": {"color": "orange"}, "approved": {"color": "green"},
                                                                      "rejected": {"color": "red"}}}]}]}]}, options=TABLE),
], [V_CUST, V_OP])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sql":   # print every query with filters set to "all", for testing
        for s in SQL:
            s = (s.replace("$__timeFilter(found_at)", "TRUE").replace("$__timeFilter(service_date)", "TRUE")
                  .replace("${__url_time_range}", ""))
            for v in ["$customer", "$operator", "$problem", "$material"]:
                s = s.replace(f"IN ({v})", "IS NOT NULL OR TRUE")
            print(s + ";")
    else:
        out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
        for name, d in [("cockpit_1_overview", overview), ("cockpit_2_findings", findings), ("cockpit_3_cost_weight", cost),
                        ("cockpit_4_operators", ops), ("cockpit_5_actions", acts)]:
            (out / f"{name}.json").write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written to {out}")
