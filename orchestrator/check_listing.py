"""
orchestrator/check_listing.py — Listing-level compliance checks (T2.10).

Two checks over the SALES supplies listing (SEQ_GAP) and PURCHASES listing
(DUP_CLAIM).  Both checks emit findings for human review.  Neither halts the
chain, mutates data, or asserts a compliance verdict.

IRAS basis:
    SEQ_GAP  — ASK Annual Review Guide §10.1(c)(i)
               "Invoices not in running sequences"
    DUP_CLAIM — ASK Annual Review Guide §10.1(d)(i)
               "Processing the same invoice more than once"

SAP field assumptions (verified against SBODEMOSG 2026-06-09):

    Series (int)
        CONFIRMED: standard SAP B1 OData integer field on Invoices and
        PurchaseInvoices.  SBODEMOSG uses Series=1 for sales, Series=6 for
        purchases.

    Cancelled (str)
        CONFIRMED (tNO): SAP B1 YNGroupEnum value "tNO" for non-cancelled docs.
        "tYES" is the expected cancelled value per SAP convention; not observable
        in SBODEMOSG (no cancelled invoices in demo DB).

    NumAtCard (str)
        CONFIRMED PRESENT, UNIVERSALLY NULL in SBODEMOSG: field exists on
        PurchaseInvoices but is 0% populated in the demo database.  DUP_CLAIM
        will return empty findings on SBODEMOSG; requires client NumAtCard
        population to function (AP data-quality precondition).

Invariants:
    - No `anthropic` import (deterministic pure Python).
    - Both functions are read-only: input lists are never mutated.
    - Both return lists of finding dicts; an empty list means no findings.
    - Findings use "candidate" / "consider reviewing" language; never assert
      a compliance verdict.

Public API:
    detect_seq_gaps(period_records, all_records)  -> list[dict]
    detect_dup_claims(records)                    -> list[dict]
"""
from __future__ import annotations

_SEQ_GAP_BASIS = "IRAS ASK Annual Review Guide §10.1(c)(i)"
_DUP_CLAIM_BASIS = "IRAS ASK Annual Review Guide §10.1(d)(i)"

# Value of Cancelled field for cancelled SAP B1 documents.
# VERIFY SAP FIELD: SAP B1 YNGroupEnum uses "tYES"/"tNO"; some OData
# endpoints may return "Y"/"N".  The check treats any truthy non-empty
# value other than "tNO", "N", "n", "false", "False" as cancelled.
_CANCELLED_FALSY = frozenset({"tNO", "N", "n", "false", "False", "", None})


def _is_cancelled(cancelled_val) -> bool:
    return cancelled_val not in _CANCELLED_FALSY


# ---------------------------------------------------------------------------
# SEQ_GAP — invoice sequence gap detection
# ---------------------------------------------------------------------------

def detect_seq_gaps(
    period_records: list[dict],
    all_records: list[dict],
) -> list[dict]:
    """Detect truly-absent DocNum slots within the reviewed period's active range.

    A slot is a SEQ_GAP candidate ONLY when BOTH conditions hold:
      1. Its integer value falls strictly within [min_active, max_active] for
         its Series, where that range is defined by active (non-cancelled)
         documents in period_records.
      2. The DocNum is absent from all_records — the company-wide population
         across ALL periods, including cancelled and out-of-period documents.

    A DocNum present in all_records (any period, any status) is NOT a gap —
    the slot was issued.  This prevents flagging earlier-period invoices that
    happen to fall within the reviewed period's DocNum range.

    Args:
        period_records: Document records for the reviewed period.  Each dict
                        must contain:
                          DocNum    (int) — document number
                          Series    (int) — numbering series identifier
                          Cancelled (str) — "tYES" → cancelled
        all_records:    Company-wide document population (all periods, all
                        statuses).  Same field schema as period_records.
                        Used solely to determine whether a DocNum was ever
                        issued anywhere.

    Returns:
        List of SEQ_GAP finding dicts.  Empty if no truly-absent gaps found.
        Each finding contains:
            check           "SEQ_GAP"
            series          series identifier
            gap_doc_num     the missing DocNum
            series_min      smallest active DocNum in period for this series
            series_max      largest active DocNum in period for this series
            description     human-readable finding statement
            basis           IRAS citation
            note            "candidate for reviewer attention"
    """
    if not period_records:
        return []

    # Company-wide known set: any DocNum present here (any period, any status)
    # occupies its slot and is never a gap.
    all_known_by_series: dict[int, set[int]] = {}
    for rec in all_records:
        doc_num = rec.get("DocNum")
        series = rec.get("Series")
        if not isinstance(doc_num, int) or doc_num <= 0:
            continue
        if not isinstance(series, int):
            continue
        all_known_by_series.setdefault(series, set()).add(doc_num)

    # Period active set (non-cancelled only) defines the range per series.
    period_active_by_series: dict[int, set[int]] = {}
    for rec in period_records:
        if _is_cancelled(rec.get("Cancelled")):
            continue
        doc_num = rec.get("DocNum")
        series = rec.get("Series")
        if not isinstance(doc_num, int) or doc_num <= 0:
            continue
        if not isinstance(series, int):
            continue
        period_active_by_series.setdefault(series, set()).add(doc_num)

    findings: list[dict] = []

    for series, active_nums in sorted(period_active_by_series.items()):
        if len(active_nums) < 2:
            continue
        series_min = min(active_nums)
        series_max = max(active_nums)
        known_in_series = all_known_by_series.get(series, set())

        for gap_num in range(series_min + 1, series_max):
            if gap_num in known_in_series:
                continue
            findings.append({
                "check": "SEQ_GAP",
                "series": series,
                "gap_doc_num": gap_num,
                "series_min": series_min,
                "series_max": series_max,
                "description": (
                    f"DocNum {gap_num} (Series {series}) is absent from all company "
                    f"records and falls within the reviewed-period active range "
                    f"[{series_min}, {series_max}]. "
                    "Consider reviewing whether this document was voided, deleted, "
                    "or never issued."
                ),
                "basis": _SEQ_GAP_BASIS,
                "note": "candidate for reviewer attention",
            })

    return findings


# ---------------------------------------------------------------------------
# DUP_CLAIM — duplicate input-tax claim detection
# ---------------------------------------------------------------------------

def detect_dup_claims(records: list[dict]) -> list[dict]:
    """Detect duplicate input-tax claims in the purchases listing.

    A duplicate is defined as two or more purchase documents sharing the
    same (CardCode, NumAtCard, DocTotal) key — meaning the same supplier
    invoice (identified by the vendor's reference number) was entered into
    SAP more than once with the same total amount.

    Recurring identical charges from the same vendor with DIFFERENT
    NumAtCard values (e.g. monthly standing charges) are NOT duplicates.

    Documents with blank or None NumAtCard are excluded from detection
    because a blank vendor reference cannot identify a specific invoice.

    Args:
        records: List of purchase document records.  Each dict must contain:
                   DocNum    (int)   — SAP document number
                   CardCode  (str)   — vendor business partner code
                   NumAtCard (str)   — vendor's invoice reference number
                   DocTotal  (float) — full document total (inclusive of tax)

    Returns:
        List of DUP_CLAIM finding dicts.  Empty if no duplicates found.
        Each finding contains:
            check           "DUP_CLAIM"
            doc_num         SAP DocNum of this duplicate occurrence
            duplicate_of    DocNum of the first occurrence
            card_code       vendor CardCode
            num_at_card     vendor invoice reference
            doc_total       document total (the matched amount)
            description     human-readable finding statement
            basis           IRAS citation
            note            "candidate for reviewer attention"
    """
    if not records:
        return []

    # key → list of DocNums that share the same (CardCode, NumAtCard, DocTotal)
    key_to_docs: dict[tuple, list[int]] = {}

    for rec in records:
        num_at_card = (rec.get("NumAtCard") or "").strip()
        if not num_at_card:
            continue  # blank vendor ref cannot identify a specific invoice

        doc_num = rec.get("DocNum")
        card_code = (rec.get("CardCode") or "").strip()
        doc_total = round(float(rec.get("DocTotal") or 0), 2)

        key = (card_code, num_at_card, doc_total)
        key_to_docs.setdefault(key, []).append(doc_num)

    findings: list[dict] = []

    for (card_code, num_at_card, doc_total), doc_nums in key_to_docs.items():
        if len(doc_nums) < 2:
            continue
        first = doc_nums[0]
        for dup in doc_nums[1:]:
            findings.append({
                "check": "DUP_CLAIM",
                "doc_num": dup,
                "duplicate_of": first,
                "card_code": card_code,
                "num_at_card": num_at_card,
                "doc_total": doc_total,
                "description": (
                    f"DocNum {dup} appears to be a duplicate of DocNum {first}: "
                    f"same vendor ({card_code}), same vendor reference "
                    f"({num_at_card!r}), same total ({doc_total:.2f}). "
                    "Consider reviewing whether input tax was claimed twice "
                    "on the same supplier invoice."
                ),
                "basis": _DUP_CLAIM_BASIS,
                "note": "candidate for reviewer attention",
            })

    return findings
