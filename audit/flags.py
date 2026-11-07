"""Refinements of the Task-B invoice rules (baseline B2) that remove false positives with explainable checks.

1. UNINVOICED_COLLECTION: a job whose reference never appears on an invoice is NOT uninvoiced when the same
   contract has, on the same service date, invoice lines carrying an unknown job reference that is a typo of
   this job's reference (two digits swapped, one digit changed, or a stray letter such as a trailing "X").
   Matching is one-to-one: each mistyped reference explains at most one job, so a second lift on the same day
   stays flagged unless it has its own typo line. Rental lines (no job reference) never explain a lift.
2. OUTDATED_TARIFF: a line whose amount differs from the recomputation is only an outdated tariff if its unit
   price equals a price of a superseded version of the same contract. Other differences are recomputation noise.
"""
from __future__ import annotations

from pathlib import Path

import re

import numpy as np
import pandas as pd


def _core(ref: str) -> str:
    return re.sub(r"[^0-9]", "", ref.split("-")[-1]) if isinstance(ref, str) and ref else ""


def is_typo_of(job_ref: str, line_ref: str) -> bool:
    """Same operator prefix; digits equal up to one changed digit or two swapped digits; letters ignored."""
    if not (isinstance(line_ref, str) and line_ref) or job_ref.rsplit("-", 1)[0] != line_ref.rsplit("-", 1)[0]:
        return False
    if line_ref == job_ref:
        return False                      # an identical reference is a normal match, not a typo
    a, b = _core(job_ref), _core(line_ref)
    if len(a) != len(b) or a == "":
        return False
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    return len(diff) == 0 or len(diff) == 1 or (len(diff) == 2 and sorted(a) == sorted(b))


def _old_prices(cv: pd.DataFrame) -> dict:
    cents_cols = [c for c in cv.columns if c.endswith("_cents") or c.endswith("_cents_per_t")]
    old = {}
    for c, g in cv.sort_values("version_no").groupby("contract_id"):
        vals = set()
        for _, row in g.iloc[:-1].iterrows():
            vals |= {round(float(row[k]) / 100, 2) for k in cents_cols if pd.notna(row[k])}
        old[c] = vals
    return old


def reconcile_uninvoiced(f: pd.DataFrame, b1: pd.DataFrame, b1l, unk: pd.DataFrame) -> pd.DataFrame:
    """One row per UNINVOICED flag with the decision and its evidence.

    BILLED_UNDER_TYPO: exactly one candidate typo reference on the same contract and day, that candidate fits
      no other flagged job, and (when expected charges are given) its lines include a line type the job was expected
      to carry. NEEDS_REVIEW: ambiguous (several candidates, or one candidate fitting several jobs) - stays flagged.
      UNINVOICED: no candidate - stays flagged."""
    b1i = b1.drop_duplicates("collection_id").set_index("collection_id")
    exp_types = b1l.groupby("operator_job_ref").line_type.apply(set).to_dict() if b1l is not None else None
    lines = unk.groupby(["contract_id", "sd", "operator_job_ref"])
    ltypes = lines.line_type.apply(set).to_dict()
    lids = lines.invoice_line_id.apply(lambda s: ";".join(sorted(s))).to_dict()
    jobs = []
    for cid in f.loc[f.label_family == "UNINVOICED_COLLECTION", "entity_id"]:
        r = b1i.loc[cid]
        day = pd.Timestamp(r.service_date).strftime("%Y-%m-%d")
        cands = [k[2] for k in ltypes if k[0] == r.contract_id and k[1] == day and is_typo_of(r.operator_job_ref, k[2])]
        if exp_types is not None:
            cands = [c for c in cands if ltypes[(r.contract_id, day, c)] & exp_types.get(r.operator_job_ref, set())]
        jobs.append((cid, r.contract_id, day, r.operator_job_ref, cands))
    fit = {}
    for _, c, d, _, cands in jobs:
        for x in cands:
            fit[(c, d, x)] = fit.get((c, d, x), 0) + 1
    rows = []
    for cid, c, d, ref, cands in jobs:
        if len(cands) == 1 and fit[(c, d, cands[0])] == 1:
            rows.append((cid, ref, "BILLED_UNDER_TYPO", cands[0], lids[(c, d, cands[0])]))
        elif cands:
            rows.append((cid, ref, "NEEDS_REVIEW", ";".join(cands), ""))
        else:
            rows.append((cid, ref, "UNINVOICED", "", ""))
    return pd.DataFrame(rows, columns=["collection_id", "job_ref", "decision", "matched_invoice_ref", "matched_invoice_line_ids"])


def refine_flags(pub: Path, b1: pd.DataFrame, flags: pd.DataFrame, b1l: pd.DataFrame | None = None) -> pd.DataFrame:
    il = pd.read_parquet(pub / "finance" / "invoice_lines.parquet").merge(
        pd.read_parquet(pub / "finance" / "invoices.parquet", columns=["invoice_id", "contract_id"]), on="invoice_id")
    cv = pd.read_parquet(pub / "reference" / "contract_versions.parquet")
    il["sd"] = pd.to_datetime(il.service_date).dt.strftime("%Y-%m-%d")
    known = set(b1.operator_job_ref)
    unk = il[il.operator_job_ref.notna() & (il.operator_job_ref != "") & ~il.operator_job_ref.isin(known)]
    typo_refs = unk.groupby(["contract_id", "sd"]).operator_job_ref.apply(lambda s: sorted(set(s))).to_dict()
    b1i = b1.drop_duplicates("collection_id").set_index("collection_id")

    f = flags.copy()
    drop = pd.Series(False, index=f.index)
    audit = reconcile_uninvoiced(f, b1, b1l, unk)
    cleared = set(audit.loc[audit.decision == "BILLED_UNDER_TYPO", "collection_id"])
    drop.loc[(f.label_family == "UNINVOICED_COLLECTION") & f.entity_id.isin(cleared)] = True
    refine_flags.last_audit = audit

    o = f.label_family == "OUTDATED_TARIFF"
    old = _old_prices(cv)
    li = il.set_index("invoice_line_id")
    sel = f.loc[o, "entity_id"]
    is_old = [round(float(li.loc[e, "unit_price_eur"]), 2) in old.get(li.loc[e, "contract_id"], set()) for e in sel]
    drop.loc[f.index[o][~np.array(is_old, dtype=bool)]] = True
    return f[~drop].reset_index(drop=True)


def attach_expected(il: pd.DataFrame, b1: pd.DataFrame, b1l: pd.DataFrame) -> pd.DataFrame:
    """Expected (contract-recomputed) amount for every invoice line, with the job reference resolved the SAME way
    the Task-B detector resolves it: a reference that is not a known job is mapped to the job of the same contract
    and service day whose reference it is a typo of (or, as the detector does, the first job that day).
    Adds: resolved_ref, ref_note, exp. Requires columns contract_id, service_date, operator_job_ref, line_type."""
    il = il.copy()
    known = set(b1.operator_job_ref)
    b = b1.assign(sd=pd.to_datetime(b1.service_date).dt.strftime("%Y-%m-%d"))
    by_day = b.groupby(["contract_id", "sd"]).operator_job_ref.apply(list).to_dict()
    sd = pd.to_datetime(il.service_date).dt.strftime("%Y-%m-%d")
    res, note = [], []
    for ref, c, d in zip(il.operator_job_ref, il.contract_id, sd):
        if not isinstance(ref, str) or ref == "" or ref in known:
            res.append(ref); note.append("")
            continue
        cands = by_day.get((c, d), [])
        typo = [j for j in cands if is_typo_of(j, ref)]
        pick = typo[0] if len(typo) == 1 else (cands[0] if cands else None)
        res.append(pick if pick else ref)
        note.append(f"reference {ref} resolved to job {pick} (same contract and day)" if pick else "no lift matches this reference")
    il["resolved_ref"], il["ref_note"] = res, note
    exp = b1l.groupby(["operator_job_ref", "line_type"]).amount_eur.sum()
    il["exp"] = [exp.get((r, t), 0.0) for r, t in zip(il.resolved_ref, il.line_type)]
    return il


def line_delta_and_explanation(il: pd.DataFrame) -> pd.DataFrame:
    """Euro delta of a flagged line and a plain-language calculation, from columns family, amount_eur, exp."""
    il = il.copy()
    fam, amt, exp = il.family, il.amount_eur, il.exp
    il["delta"] = np.where(fam.isin(["DUPLICATE_LINE", "UNMATCHED_LINE"]), amt,
                           np.where(fam.isin(["WRONG_SURCHARGE", "WEIGHT_BASIS_MISMATCH", "OUTDATED_TARIFF"]), amt - exp, 0.0))
    txt = []
    for f, a, e, n, lt in zip(fam, amt, exp, il.ref_note, il.line_type):
        pre = (n + ". ") if n else ""
        if f == "DUPLICATE_LINE":
            txt.append(f"{pre}A {lt} line for this lift was already billed (the payable charge, {e:.2f} EUR under the contract). "
                       f"This extra line is not payable: delta = its full amount {a:.2f} EUR.")
        elif f == "UNMATCHED_LINE":
            if n.startswith("reference"):
                txt.append(f"{pre}That lift has no {lt} charge under the contract, so this line matches nothing payable: "
                           f"delta = its full amount {a:.2f} EUR.")
            else:
                txt.append(f"No recorded lift of this contract matches this line: delta = its full amount {a:.2f} EUR.")
        elif f in ("WRONG_SURCHARGE", "WEIGHT_BASIS_MISMATCH", "OUTDATED_TARIFF"):
            why = {"WRONG_SURCHARGE": "surcharge quantity or rate differs from the contract",
                   "WEIGHT_BASIS_MISMATCH": "invoiced tonnage differs from the weighbridge/device mass used in the recomputation",
                   "OUTDATED_TARIFF": "unit price matches a superseded contract version"}[f]
            txt.append(f"{pre}{why}: billed {a:.2f} EUR - contract-recomputed {e:.2f} EUR = {a - e:+.2f} EUR.")
        else:
            txt.append("")
    il["calculation"] = txt
    return il
