#!/usr/bin/env python3
"""
scripts/check_listing_reference.py — Independent reference implementations
for T2.10 listing-level compliance checks.

These functions implement SEQ_GAP and DUP_CLAIM detection independently of
orchestrator/check_listing.py.  There is NO shared helper between this module
and the production module.  The test suite asserts that both implementations
produce identical output on the same input; any divergence is a bug.

IRAS basis:
    SEQ_GAP  — ASK Annual Review Guide §10.1(c)(i)
    DUP_CLAIM — ASK Annual Review Guide §10.1(d)(i)

SAP field assumptions (same as orchestrator/check_listing.py):
    Series    (int) — numbering series; VERIFY SAP FIELD
    Cancelled (str) — "tYES" for cancelled docs; VERIFY SAP FIELD
    NumAtCard (str) — vendor invoice reference; VERIFY SAP FIELD

No anthropic import.  No orchestrator import.  Pure Python.

Public API:
    ref_detect_seq_gaps(records)    -> list[dict]
    ref_detect_dup_claims(records)  -> list[dict]
"""
from __future__ import annotations

_SEQ_GAP_BASIS = "IRAS ASK Annual Review Guide §10.1(c)(i)"
_DUP_CLAIM_BASIS = "IRAS ASK Annual Review Guide §10.1(d)(i)"


def ref_detect_seq_gaps(
    period_records: list[dict],
    all_records: list[dict],
) -> list[dict]:
    """Reference implementation of SEQ_GAP detection.

    Independently re-implements the production algorithm.
    No shared helpers with orchestrator/check_listing.py.

    A DocNum is flagged only when:
      (1) absent from all_records (company-wide, any period, any status), AND
      (2) falls within [min_active, max_active] from period_records.

    Returns same output schema as detect_seq_gaps().
    """
    if not period_records:
        return []

    # Build company-wide existence set by series (no helper shared with production)
    company_nums: dict[int, set[int]] = {}
    for r in all_records:
        n = r.get("DocNum")
        s = r.get("Series")
        if not isinstance(n, int) or n <= 0:
            continue
        if not isinstance(s, int):
            continue
        company_nums.setdefault(s, set()).add(n)

    # Period active (non-cancelled) defines the range to inspect
    active_period: dict[int, set[int]] = {}
    for r in period_records:
        c = r.get("Cancelled") or ""
        if c not in ("", "tNO", "N", "n", "false", "False", None):
            continue  # cancelled — skip for range determination
        n = r.get("DocNum")
        s = r.get("Series")
        if not isinstance(n, int) or n <= 0:
            continue
        if not isinstance(s, int):
            continue
        active_period.setdefault(s, set()).add(n)

    output: list[dict] = []

    for series in sorted(active_period):
        live = active_period[series]
        if len(live) < 2:
            continue
        lo = min(live)
        hi = max(live)
        known = company_nums.get(series, set())

        for missing in range(lo + 1, hi):
            if missing in known:
                continue  # issued somewhere in company history — not a gap
            output.append({
                "check": "SEQ_GAP",
                "series": series,
                "gap_doc_num": missing,
                "series_min": lo,
                "series_max": hi,
                "description": (
                    f"DocNum {missing} (Series {series}) is absent from all company "
                    f"records and falls within the reviewed-period active range "
                    f"[{lo}, {hi}]. "
                    "Consider reviewing whether this document was voided, deleted, "
                    "or never issued."
                ),
                "basis": _SEQ_GAP_BASIS,
                "note": "candidate for reviewer attention",
            })

    return output


def ref_detect_dup_claims(records: list[dict]) -> list[dict]:
    """Reference implementation of DUP_CLAIM detection.

    Independently re-implements the production algorithm.
    No shared helpers with orchestrator/check_listing.py.

    Returns same output schema as detect_dup_claims().
    """
    if not records:
        return []

    # Build occurrence table: (card_code, num_at_card, doc_total) -> [DocNums]
    occurrences: dict[tuple, list[int]] = {}

    for r in records:
        vendor_ref = (r.get("NumAtCard") or "").strip()
        if not vendor_ref:
            continue  # blank ref excluded
        dn = r.get("DocNum")
        cc = (r.get("CardCode") or "").strip()
        amt = round(float(r.get("DocTotal") or 0), 2)
        key = (cc, vendor_ref, amt)
        occurrences.setdefault(key, []).append(dn)

    result: list[dict] = []

    for (cc, vendor_ref, amt), doc_nums in occurrences.items():
        if len(doc_nums) < 2:
            continue
        first_occurrence = doc_nums[0]
        for later in doc_nums[1:]:
            result.append({
                "check": "DUP_CLAIM",
                "doc_num": later,
                "duplicate_of": first_occurrence,
                "card_code": cc,
                "num_at_card": vendor_ref,
                "doc_total": amt,
                "description": (
                    f"DocNum {later} appears to be a duplicate of DocNum {first_occurrence}: "
                    f"same vendor ({cc}), same vendor reference "
                    f"({vendor_ref!r}), same total ({amt:.2f}). "
                    "Consider reviewing whether input tax was claimed twice "
                    "on the same supplier invoice."
                ),
                "basis": _DUP_CLAIM_BASIS,
                "note": "candidate for reviewer attention",
            })

    return result
