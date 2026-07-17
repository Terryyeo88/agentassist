"""
orchestrator/check_document_dup_window.py — Windowed duplicate-purchase surfacer.

A deterministic surfacer over the NORMALISED purchase records
(``fetch_manifest.records``, the ``_doc_to_record`` shape) that flags when two
purchase invoices share the SAME supplier and the SAME amount and fall 1..N days
apart. It surfaces a review CANDIDATE — it never asserts the documents ARE the
same purchase.

Distinct from ``check_document_dup.detect_same_day_dups`` (DUP_SAME_DAY), which
keys on an EXACT same-day match. This check owns the MULTI-DAY range ONLY:

    1 <= abs(delta_days) <= window_days

DAY-0 IS DELIBERATELY EXCLUDED (load-bearing — read before editing the predicate).
A delta of 0 belongs to DUP_SAME_DAY EXCLUSIVELY. If this check also fired on
day-0 the reviewer would see the same pair twice, under two check names, in
near-identical prose. The two surfacers are complementary and disjoint by
construction; there is deliberately NO dedupe pass anywhere downstream, because
there is nothing to dedupe.

CONSEQUENCE OF THE DISJOINT SPLIT (documented, not a defect): the two checks have
INDEPENDENT failure contracts in the chain (each its own try/except). If
DUP_SAME_DAY throws, day-0 collisions are surfaced by NEITHER check — this check
does NOT backfill a same-day failure. That gap is DISCLOSED, not silent: the
same-day check's own "unavailable" status reports it.

PAIRWISE, NOT TRANSITIVE (load-bearing). A window is not an equivalence relation:
A~B and B~C does not imply A~C (08-01 ~ 08-05 and 08-05 ~ 08-09 both fall inside a
7-day window, but 08-01 vs 08-09 is 8 days — outside). Grouping transitively would
chain arbitrarily far beyond the configured window and report documents together
that the window never related. Each qualifying PAIR therefore yields ONE finding
carrying exactly TWO doc_nums.

WINDOW VALUE (honest status): ``window_days`` is an ARBITRARY CALLER-SUPPLIED
INPUT. This module neither defines nor defaults it — a validated window is
DEFERRED to a worksheet that does not exist yet, and the config loader FAILS LOUD
rather than guess one. Nothing here claims any window is correct.

AMOUNT MATCHING: EXACT only (round(...,2)). There is NO amount tolerance — a cent
apart is NOT a collision. A tolerance is DEFERRED to the same worksheet; do not
add one here.

Honest status: MECHANISM built, NOT accuracy-validated. The over-firing
(false-positive) behaviour is UNTESTABLE with the current corpus — no legitimate
recurring-identical-charge ("must-spare") fixture exists to pin the case
(see tests/fixtures/xero-real-format/FIXTURE_NOTES.md).

Invariants:
    - No ``anthropic`` import (deterministic pure Python).
    - Read-only: the input list and its dicts are never mutated.
    - Returns a list of finding dicts; an empty list means no collisions.
    - Findings use "Consider reviewing whether ..." candidate language; never
      assert a compliance or duplicate verdict, and never use the word
      "duplicate" in reviewer-facing prose.

doc_num TYPE-SAFETY (why there is no sort key here): doc_num is int on the SAP
path but a STRING on Xero ("BILL-3002" — see steps._coerce_doc_num), and may be
None. ``check_document_dup`` needs ``_doc_num_sort_key`` because it orders a group
BY doc_num. This check never compares doc_nums at all: a pair is ordered by DATE
(deltas are >= 1, so the two dates always differ and the order is total), and the
findings list follows input order. Mixed types therefore cannot raise TypeError
here by construction, not by guard.

Public API:
    detect_window_dups(records, window_days) -> list[dict]
"""
from __future__ import annotations

from datetime import date

_CHECK = "DUP_WINDOW"
_NOTE = "candidate for reviewer attention"
_NO_DOC_NUM = "(no DocNum)"


def _parse_iso_date(raw: str):
    """Parse a "YYYY-MM-DD" doc_date, or return None if it is not parseable.

    ``_doc_to_record`` slices SAP's DocDate to 10 chars, so the normal shape is a
    bare ISO date. An unparseable value is treated like a blank key (the record is
    skipped) rather than raised: a single malformed row must not blank the WHOLE
    check for the run via the chain's unavailable contract.
    """
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _render_doc_num(n) -> str:
    """A doc_num as reviewer-facing prose; None renders as "(no DocNum)".

    Never emits a bare "None" — a colliding document carrying no identifier is
    named honestly instead.
    """
    return _NO_DOC_NUM if n is None else str(n)


def _describe(earlier_num, later_num, delta_days: int) -> str:
    """Candidate prose for one qualifying pair. Never says "duplicate"."""
    day_word = "day" if delta_days == 1 else "days"
    return (
        f"Consider reviewing whether DocNums {_render_doc_num(earlier_num)} and "
        f"{_render_doc_num(later_num)} (same supplier, same total, "
        f"{delta_days} {day_word} apart) represent the same purchase entered twice."
    )


def detect_window_dups(records: list[dict], window_days: int) -> list[dict]:
    """Surface same-supplier, same-amount purchase pairs 1..window_days apart.

    Only ``doc_type == "purchase_invoice"`` records are considered. Records whose
    ``card_name`` or ``doc_date`` is blank (or whose date is unparseable) are
    excluded — a blank key cannot identify a document (mirrors DUP_SAME_DAY's
    blank-key skip).

    Args:
        records:     List of normalised InvoiceRecord dicts. Each read dict may
                     carry:
                       doc_num   (int | str | None) — document number/reference
                       doc_type  (str)   — canonical doc-type string
                       doc_date  (str)   — "YYYY-MM-DD"
                       doc_total (float) — document total
                       card_name (str)   — supplier name
        window_days: The INCLUSIVE upper bound on the date delta, in days. An
                     ARBITRARY caller-supplied input — this module asserts nothing
                     about what value is correct. The config loader guarantees it
                     is an int >= 1 before it reaches here.

    Returns:
        List of DUP_WINDOW finding dicts, one per qualifying PAIR, in input order.
        Empty if no pair qualifies. Each finding:
            check        "DUP_WINDOW"
            card_name    supplier name (the shared key)
            doc_total    document total, rounded to 2dp (the shared key)
            doc_dates    ["YYYY-MM-DD", "YYYY-MM-DD"], ascending
            delta_days   int >= 1, the gap between doc_dates
            doc_nums     the two doc_nums, positionally coupled to doc_dates
            description  surfacer statement ("Consider reviewing whether ...")
            note         "candidate for reviewer attention"
        No ``card_code`` / ``num_at_card`` key (this is not DUP_CLAIM).
    """
    if not records:
        return []

    # Project the eligible records once: (card_name, doc_total, parsed_date,
    # raw_date, doc_num). Read-only — nothing in `records` is mutated.
    eligible: list[tuple] = []
    for rec in records:
        if rec.get("doc_type") != "purchase_invoice":
            continue

        card_name = (rec.get("card_name") or "").strip()
        raw_date = (rec.get("doc_date") or "").strip()
        if not card_name or not raw_date:
            continue  # a blank key cannot identify a document

        parsed = _parse_iso_date(raw_date)
        if parsed is None:
            continue  # unparseable date — skip the row, never blank the check

        doc_total = round(float(rec.get("doc_total") or 0), 2)
        eligible.append((card_name, doc_total, parsed, raw_date, rec.get("doc_num")))

    findings: list[dict] = []

    # Pairwise over the eligible projection (i < j), so each pair is considered
    # exactly once and the output order is a deterministic function of the input.
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            a, b = eligible[i], eligible[j]

            if a[0] != b[0] or a[1] != b[1]:
                continue  # different supplier, or a non-exact amount

            delta_days = abs((a[2] - b[2]).days)
            if not (1 <= delta_days <= window_days):
                continue  # day-0 is DUP_SAME_DAY's; beyond the window is nobody's

            # Order the pair by DATE. delta >= 1 guarantees the dates differ, so
            # this is a total order and no doc_num is ever compared.
            earlier, later = (a, b) if a[2] < b[2] else (b, a)

            findings.append({
                "check": _CHECK,
                "card_name": earlier[0],
                "doc_total": earlier[1],
                "doc_dates": [earlier[3], later[3]],
                "delta_days": delta_days,
                "doc_nums": [earlier[4], later[4]],
                "description": _describe(earlier[4], later[4], delta_days),
                "note": _NOTE,
            })

    return findings
