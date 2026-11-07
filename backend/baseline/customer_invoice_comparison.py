"""Compare an operator invoice with customer weights and fixed contract rates.


Uses only the Python standard library. Amounts are currency units, not cents;
weights are net tonnes (kg / 1000). Use the same event scope and VAT basis for
all amounts. Enter contract rates applicable to that event. Each stream has
separate credit and processing weights: the same tonnes can attract both.
Each credit/processing line is rounded half-up to cents before summation.
Imported collection cost and penalties remain unchanged in the comparison.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


CENT = Decimal("0.01")


def number(value, name, signed=False):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not result.is_finite() or (not signed and result < 0):
        raise ValueError(f"{name} must be finite" +
                         (" and nonnegative" if not signed else ""))
    return result


def money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate(data):
    """Return JSON-ready results; monetary values are exact decimal strings."""
    invoice = number(data["operator_total_invoice"],
                     "operator_total_invoice", signed=True)
    collection = number(data["collection_cost"], "collection_cost")
    penalties = number(data["penalties"], "penalties")
    for name, amount in (("operator_total_invoice", invoice), ("collection_cost", collection), ("penalties", penalties)):
        if amount != money(amount):
            raise ValueError(f"{name} must have at most two decimal places")
    streams = data["streams"]
    if not isinstance(streams, list) or not streams:
        raise ValueError("streams must be a nonempty list")
    credit = Decimal(0)
    processing = Decimal(0)
    lines = []
    for stream in streams:
        name = stream["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each stream requires a nonempty name")
        values = {key: number(stream[key], f"{name}.{key}") for key in (
            "credit_weight_t", "credit_rate_per_t", "processing_weight_t", "processing_fee_per_t")}
        material_credit = money(
            values["credit_weight_t"] * values["credit_rate_per_t"])
        processing_cost = money(
            values["processing_weight_t"] * values["processing_fee_per_t"])
        credit += material_credit
        processing += processing_cost
        lines.append({"name": name, **{key: str(value) for key, value in values.items()},
                      "material_credit": str(material_credit), "processing_cost": str(processing_cost)})
    net = credit - collection - processing - penalties
    expected = -net
    difference = invoice - expected
    amounts = dict(operator_total_invoice=invoice, collection_cost=collection,
                   penalties=penalties, material_credit=credit, processing_cost=processing,
                   net_material_contribution=net, expected_customer_cost=expected,
                   invoice_difference=difference)
    return {"event_id": data.get("event_id", ""), "currency": data.get("currency", "EUR"),
            "streams": lines, **{key: format(money(value), ".2f") for key, value in amounts.items()},
            "comparison": "operator_higher" if difference > 0 else "operator_lower" if difference < 0 else "equal",
            "interpretation": "Difference = operator invoice minus customer estimate. Collection cost and penalties are imported unchanged; a difference is a review signal, not proof of an incorrect operator weight."}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "input", type=Path, help="JSON invoice, customer weights and contract rates")
    parser.add_argument("--out", type=Path, help="Optional result JSON path")
    args = parser.parse_args()
    if args.out and args.out.resolve() == args.input.resolve():
        parser.error("Input and output paths must differ")
    try:
        data = json.loads(args.input.read_text(
            encoding="utf-8-sig"), parse_float=Decimal)
        result = calculate(data)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
        parser.error(str(exc))
    for label, key in (("Material credit", "material_credit"), ("Processing cost", "processing_cost"),
                       ("Collection cost", "collection_cost"), ("Penalties", "penalties"),
                       ("Expected customer cost", "expected_customer_cost"),
                       ("Operator invoice", "operator_total_invoice"), ("Invoice difference", "invoice_difference")):
        print(f"{label:24s} {result['currency']} {result[key]}")
    print(result["interpretation"])
    if args.out:
        print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
