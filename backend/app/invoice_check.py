"""Check a waste company's invoice against what the ESP32 board MEASURED (pickups) and the customer's prices (materials).

Per line type:
  LIFT_FEE         one lift per pickup the board saw. A billed lift with no emptying that day = NO_LIFT,
                   the same day billed twice = DUPLICATE. Unit price vs the customer's cost per lift = WRONG_PRICE.
  PROCESSING,      tonnes billed vs tonnes measured for that compactor in the period (more than 4 % apart =
  MATERIAL_CREDIT, WEIGHT_MISMATCH). Unit price vs the customer's price per tonne (processing when you pay,
  HAULAGE          credit when they pay you); haulage has no contract price here, so only the weight is checked.
  SURCHARGE,       the sensor cannot prove or disprove these -> NO_EVIDENCE: ask the waste company for proof.
  PENALTY, OTHER
Money is in the customer's terms: difference = amount - expected, + = charged too much (or credited too little).
The result only SUGGESTS (APPROVE / CHECK); a person decides (invoice_decisions)."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update

from app.db import compactors, invoice_lines, invoices, materials, pickups

WEIGHT_TOLERANCE = 0.04      # 4 %: normal difference between two scales
PRICE_TOLERANCE = 0.01       # 1 %
ROUNDING_EUR = 0.05          # cents from rounding tonnes / amounts on an invoice are not an overcharge
WEIGHT_TYPES = {"PROCESSING", "MATERIAL_CREDIT", "HAULAGE"}
NO_EVIDENCE_TYPES = {"SURCHARGE", "PENALTY", "OTHER"}
LINE_TYPES = ["LIFT_FEE", *sorted(WEIGHT_TYPES), *sorted(NO_EVIDENCE_TYPES)]


def _day(t):
    if isinstance(t, datetime):
        return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date()
    return t if isinstance(t, date) else date.fromisoformat(str(t)[:10])


def _tonnes(q, unit):
    return (q or 0) / 1000 if (unit or "t").lower() == "kg" else (q or 0)


def check(conn, invoice_id: str) -> dict:
    """Check every line, store the result on the lines and the invoice, return the invoice summary."""
    inv = conn.execute(select(invoices).where(invoices.c.invoice_id == invoice_id)).mappings().first()
    lines = [dict(r) for r in conn.execute(select(invoice_lines).where(invoice_lines.c.invoice_id == invoice_id)
                                           .order_by(invoice_lines.c.line_no)).mappings()]
    comps = {c["id"]: dict(c) for c in conn.execute(select(compactors).where(compactors.c.customer_name == inv["customer_name"])).mappings()}
    mats = {m["name"]: dict(m) for m in conn.execute(select(materials)).mappings()}
    start = datetime.combine(_day(inv["period_from"]), datetime.min.time(), timezone.utc)
    end = datetime.combine(_day(inv["period_to"]) + timedelta(days=1), datetime.min.time(), timezone.utc)
    measured = conn.execute(select(pickups.c.compactor_id, pickups.c.done_at, pickups.c.kg_collected).where(
        pickups.c.status == "done", pickups.c.compactor_id.in_(list(comps) or [""]),
        pickups.c.done_at >= start, pickups.c.done_at < end)).mappings().all()
    lifts_on = defaultdict(int)                      # (compactor, day) -> lifts the board saw
    lifts_in_period, t_measured = defaultdict(int), defaultdict(float)
    for m in measured:
        lifts_on[(m["compactor_id"], _day(m["done_at"]))] += 1
        lifts_in_period[m["compactor_id"]] += 1
        t_measured[m["compactor_id"]] += (m["kg_collected"] or 0) / 1000

    results = {}                                     # line id -> (status list, expected, reason list)
    used_on, used_any, billed_lifts = defaultdict(int), defaultdict(int), defaultdict(float)
    weight_groups = defaultdict(list)
    for ln in lines:
        st, why, amount, cid = [], [], ln["amount_eur"] or 0, ln["compactor_id"]
        expected = amount
        if ln["line_type"] in NO_EVIDENCE_TYPES:
            results[ln["id"]] = (["NO_EVIDENCE"], 0.0, ["the sensor cannot prove this charge — ask the waste company for proof"])
            continue
        if cid not in comps:
            results[ln["id"]] = (["UNKNOWN_COMPACTOR"], 0.0, [f"compactor '{cid}' is not one of this customer's"])
            continue
        mat = mats.get(comps[cid]["material"], {})
        if ln["line_type"] == "LIFT_FEE":
            n = round(ln["quantity"] or 1)
            unit = ln["unit_price_eur"] if ln["unit_price_eur"] is not None else amount / max(n, 1)
            billed_lifts[cid] += n
            if ln["service_date"] is not None:            # match the billed lifts to the board's emptyings that day
                key = (cid, _day(ln["service_date"]))
                free = lifts_on[key] - used_on[key]
                ok = min(n, max(free, 0))
                if ok < n:
                    st.append("DUPLICATE" if used_on[key] > 0 else "NO_LIFT")
                    why.append(f"{n - ok} lift(s) billed on {key[1]} but the board saw {lifts_on[key]} emptying(s) that day")
                used_on[key] += ok
                used_any[cid] += ok
            else:                                         # no date: count against all lifts in the period
                free = lifts_in_period[cid] - used_any[cid]
                ok = min(n, max(free, 0))
                if ok < n:
                    st.append("NO_LIFT")
                    why.append(f"{n - ok} more lift(s) billed than the board saw in the period ({lifts_in_period[cid]})")
                used_any[cid] += ok
            price = mat.get("lift_fee_eur")
            if price is not None and abs(unit - price) > PRICE_TOLERANCE * max(price, 1):
                st.append("WRONG_PRICE")
                why.append(f"{unit:.2f} € per lift instead of your price {price:.2f} €")
            else:
                price = unit
            expected = ok * price
            results[ln["id"]] = (st or ["OK"], expected, why)
        else:
            weight_groups[(cid, ln["line_type"])].append(ln)

    for (cid, typ), group in weight_groups.items():          # weight lines: all lines of one type + compactor together
        mat = mats.get(comps[cid]["material"], {})
        p_t = (mat.get("price_eur_per_kg") or 0) * 1000       # + they pay you, - you pay them
        contract = {"MATERIAL_CREDIT": p_t if p_t > 0 else None, "PROCESSING": -p_t if p_t < 0 else None}.get(typ)
        billed_t = sum(_tonnes(ln["quantity"], ln["unit"]) for ln in group)
        meas_t = t_measured[cid]
        weight_off = meas_t == 0 or abs(billed_t - meas_t) > WEIGHT_TOLERANCE * meas_t
        for ln in group:
            st, why, amount = [], [], ln["amount_eur"] or 0
            q = _tonnes(ln["quantity"], ln["unit"])
            share = q / billed_t if billed_t else 1 / len(group)
            unit = abs(amount) / q if q else abs(ln["unit_price_eur"] or 0)
            if weight_off:
                st.append("WEIGHT_MISMATCH")
                why.append(f"{billed_t:.2f} t billed for {cid}, the board measured {meas_t:.2f} t in the period")
            price = unit
            if contract is not None and abs(unit - contract) > PRICE_TOLERANCE * max(contract, 1):
                st.append("WRONG_PRICE")
                why.append(f"{unit:.2f} € per t instead of your price {contract:.2f} €")
                price = contract
            sign = -1 if amount < 0 or typ == "MATERIAL_CREDIT" else 1
            expected = sign * meas_t * share * price
            results[ln["id"]] = (st or ["OK"], expected, why)

    over = unverified = 0.0
    n_ok = 0
    for ln in lines:
        st, expected, why = results[ln["id"]]
        amount = ln["amount_eur"] or 0
        diff = round(amount - expected, 2) if st != ["NO_EVIDENCE"] else round(amount, 2)
        if st == ["OK"]:
            n_ok, diff = n_ok + 1, round(amount - expected, 2)
            if abs(diff) < ROUNDING_EUR:
                diff = 0.0
        if st == ["NO_EVIDENCE"]:
            unverified += max(amount, 0)
        elif diff > 0:
            over += diff
        conn.execute(update(invoice_lines).where(invoice_lines.c.id == ln["id"]).values(
            check_status="+".join(st), expected_eur=round(expected, 2), difference_eur=diff, check_reason="; ".join(why) or None))

    notes = []
    printed, summed = inv["total_eur"], round(sum(ln["amount_eur"] or 0 for ln in lines), 2)
    if abs(printed - summed) > 0.01:
        notes.append(f"the lines add up to {summed:.2f} €, the invoice says {printed:.2f} €")
        over += max(printed - summed, 0)
    not_billed = {c: lifts_in_period[c] - used_any[c] for c in comps if lifts_in_period[c] - used_any[c] > 0 and billed_lifts[c] > 0}
    if not_billed:
        notes.append("not billed (in your favour): " + ", ".join(f"{n} lift(s) of {c}" for c, n in not_billed.items()))
    problems = len(lines) - n_ok
    suggestion = "APPROVE" if problems == 0 and abs(printed - summed) <= 0.01 else "CHECK"
    head = (f"{problems} of {len(lines)} line(s) need a look" if problems else f"all {len(lines)} line(s) match the board's measurement")
    summary = "; ".join([head] + ([f"{over:.2f} € charged too much"] if over > 0.005 else [])
                        + ([f"{unverified:.2f} € without sensor evidence"] if unverified > 0.005 else []) + notes)
    vals = dict(checked_at=datetime.now(timezone.utc), suggestion=suggestion, overcharged_eur=round(over, 2),
                unverified_eur=round(unverified, 2), lines_ok=n_ok, lines_total=len(lines), summary=summary)
    conn.execute(update(invoices).where(invoices.c.invoice_id == invoice_id).values(**vals))
    return {"invoice_id": invoice_id, **vals}


def draft_from_measurement(conn, customer: str, operator: str, period_from: date, period_to: date) -> list[dict]:
    """The invoice the waste company SHOULD send: one lift line per measured emptying + the weight lines.
    Handy for the demo (and for the customer): load it, change a number, see the check catch it."""
    comps = {c["id"]: dict(c) for c in conn.execute(select(compactors).where(
        compactors.c.customer_name == customer, compactors.c.operator_name == operator)).mappings()}
    mats = {m["name"]: dict(m) for m in conn.execute(select(materials)).mappings()}
    start = datetime.combine(period_from, datetime.min.time(), timezone.utc)
    end = datetime.combine(period_to + timedelta(days=1), datetime.min.time(), timezone.utc)
    rows = conn.execute(select(pickups.c.compactor_id, pickups.c.done_at, pickups.c.kg_collected).where(
        pickups.c.status == "done", pickups.c.compactor_id.in_(list(comps) or [""]), pickups.c.done_at >= start,
        pickups.c.done_at < end).order_by(pickups.c.done_at)).mappings().all()
    lines, kg = [], defaultdict(float)
    for r in rows:
        mat = mats.get(comps[r["compactor_id"]]["material"], {})
        fee = mat.get("lift_fee_eur") or 0
        lines.append({"line_type": "LIFT_FEE", "compactor_id": r["compactor_id"], "service_date": str(_day(r["done_at"])),
                      "quantity": 1, "unit": "lift", "unit_price_eur": fee, "amount_eur": round(fee, 2)})
        kg[r["compactor_id"]] += r["kg_collected"] or 0
    for cid, k in kg.items():
        p_t = (mats.get(comps[cid]["material"], {}).get("price_eur_per_kg") or 0) * 1000
        t = round(k / 1000, 3)
        if p_t > 0:
            lines.append({"line_type": "MATERIAL_CREDIT", "compactor_id": cid, "service_date": None, "quantity": t, "unit": "t",
                          "unit_price_eur": p_t, "amount_eur": round(-t * p_t, 2)})
        elif p_t < 0:
            lines.append({"line_type": "PROCESSING", "compactor_id": cid, "service_date": None, "quantity": t, "unit": "t",
                          "unit_price_eur": -p_t, "amount_eur": round(-t * p_t, 2)})
    return lines
