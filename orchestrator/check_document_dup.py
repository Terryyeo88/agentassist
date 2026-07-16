"""
orchestrator/check_document_dup.py — Same-day duplicate-purchase surfacer.

A deterministic surfacer over the NORMALISED purchase records
(``fetch_manifest.records``, the ``_doc_to_record`` shape) that flags when two or
more purchase invoices share the SAME supplier, the SAME amount, and the SAME day.
It surfaces a review CANDIDATE — it never asserts the documents ARE duplicates.

Distinct from ``check_listing.detect_dup_claims`` (DUP_CLAIM): that check keys on
the vendor's reference (``CardCode, NumAtCard, DocTotal``) over the LISTING surface
and cannot fire on the Xero path (no listing surface, no NumAtCard). This surfacer
keys on ``(card_name, DocTotal, DocDate)`` over the normalised DOCUMENTS surface,
which is populated on both the SAP and Xero paths. The two are complementary.

Match key (PINNED — see the build worksheet):
    (card_name, round(float(doc_total), 2), doc_date)
EXACT, SAME-DAY only. There is NO date window and NO amount tolerance — a different
day, or a different amount, is NOT a collision. A nonzero window / tolerance is
DEFERRED to a future worksheet-derived config; do not add one here.

Honest status: BUILT, NOT accuracy-validated. Same-day only pending a worksheet-
derived window. The over-firing (false-positive) behaviour is UNTESTABLE with the
current corpus — no legitimate recurring-identical-charge fixture exists to pin the
must-spare case (see tests/fixtures/xero-real-format/FIXTURE_NOTES.md).

Invariants:
    - No ``anthropic`` import (deterministic pure Python).
    - Read-only: the input list is never mutated.
    - Returns a list of finding dicts; an empty list means no collisions.
    - Findings use "Consider reviewing whether ..." candidate language; never
      assert a compliance or duplicate verdict.

Public API:
    detect_same_day_dups(records) -> list[dict]
"""
from __future__ import annotations

_CHECK = "DUP_SAME_DAY"
_NOTE = "candidate for reviewer attention"
_NO_DOC_NUM = "(no DocNum)"


def _doc_num_sort_key(n):
    """Total, type-safe ordering key for a doc_num of ANY type — never raises.

    doc_num is int on the SAP path but a STRING on the Xero path (a non-numeric
    reference like "BILL-3002" — see steps._coerce_doc_num), and a group can mix
    them (some numeric refs → int, some non-numeric → str). A bare ``sorted`` over a
    mixed group raises ``TypeError`` (int vs str, or None vs int), which would blank
    the WHOLE check for that run via the chain's unavailable contract — a reachable
    Xero failure. This key partitions by a type rank FIRST so values of different
    kinds are never compared to each other:
        numeric (int/float) → rank 0, ordered by value (SAP path unchanged);
        string              → rank 1, ordered lexically, after all numerics;
        None                → rank 2, last.
    """
    if n is None:
        return (2, "")
    if isinstance(n, bool):
        return (0, int(n))  # bool is an int subclass; normalise to its int value
    if isinstance(n, (int, float)):
        return (0, n)
    return (1, str(n))


def _format_doc_nums(doc_nums: list) -> str:
    """Human-readable join: '501 and 502'; '502, 507 and 510'.

    A None doc_num (a colliding document carrying no identifier) renders as
    ``(no DocNum)`` so the prose never reads a bare 'None'.
    """
    strs = [(_NO_DOC_NUM if n is None else str(n)) for n in doc_nums]
    if len(strs) == 1:
        return strs[0]
    return f"{', '.join(strs[:-1])} and {strs[-1]}"


def detect_same_day_dups(records: list[dict]) -> list[dict]:
    """Surface same-supplier, same-amount, same-day purchase collisions.

    Only ``doc_type == "purchase_invoice"`` records are considered. Records whose
    ``card_name`` or ``doc_date`` is blank are excluded (a blank key cannot
    identify a document — mirrors DUP_CLAIM's blank-NumAtCard skip).

    Args:
        records: List of normalised InvoiceRecord dicts. Each read dict may carry:
                   doc_num   (int)   — document number
                   doc_type  (str)   — canonical doc-type string
                   doc_date  (str)   — "YYYY-MM-DD"
                   doc_total (float) — document total
                   card_name (str)   — supplier/customer name

    Returns:
        List of DUP_SAME_DAY finding dicts. Empty if no collisions. Each finding:
            check        "DUP_SAME_DAY"
            card_name    supplier name (the shared key)
            doc_total    document total, rounded to 2dp (the shared key)
            doc_date     "YYYY-MM-DD" (the shared key)
            doc_nums     sorted list of the colliding doc_num values
            description  surfacer statement ("Consider reviewing whether ...")
            note         "candidate for reviewer attention"
        No ``num_at_card`` / ``card_code`` key (distinct from DUP_CLAIM).
    """
    if not records:
        return []

    # key → list of doc_num sharing (card_name, round(doc_total,2), doc_date)
    key_to_docs: dict[tuple, list] = {}

    for rec in records:
        if rec.get("doc_type") != "purchase_invoice":
            continue

        card_name = (rec.get("card_name") or "").strip()
        doc_date = (rec.get("doc_date") or "").strip()
        if not card_name or not doc_date:
            continue  # a blank key cannot identify a document

        doc_total = round(float(rec.get("doc_total") or 0), 2)
        key = (card_name, doc_total, doc_date)
        key_to_docs.setdefault(key, []).append(rec.get("doc_num"))

    findings: list[dict] = []

    for (card_name, doc_total, doc_date), doc_nums in key_to_docs.items():
        if len(doc_nums) < 2:
            continue
        sorted_nums = sorted(doc_nums, key=_doc_num_sort_key)
        findings.append({
            "check": _CHECK,
            "card_name": card_name,
            "doc_total": doc_total,
            "doc_date": doc_date,
            "doc_nums": sorted_nums,
            "description": (
                f"Consider reviewing whether DocNums {_format_doc_nums(sorted_nums)} "
                f"(same supplier, same total, same day) represent the same purchase "
                f"entered twice."
            ),
            "note": _NOTE,
        })

    return findings
