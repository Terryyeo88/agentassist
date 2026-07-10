"""documents/legibility.py — per-document legibility gate (T2.14).

Runs BETWEEN ingest() and reconcile() in documents.doc_pass.run_documents_pass.
A document whose extraction is unreliable is routed to "manual review required"
and is NOT fed to reconcile, so no confident-wrong candidate is surfaced from an
unreadable PDF. This closes open item #28 for the born-digital / multimodal
ingestion path — the prerequisite for T2.8 on real (non-seeded) invoices.

What "illegible" means here (the rule — stated once, mechanically, no tax meaning):
  1. KEY FIELD ABSENT (both extraction paths). Either of the two key fields
     (gst_amount, invoice_date) is None. supplier_gst_regno is DELIBERATELY NOT
     a key field: its absence is a legitimate reconcile trigger
     (reg11_supplier_gst_absent), not an illegibility signal (Q2).
  2. MULTIMODAL NULL-COUNT (multimodal/scanned path only). More than
     max_null_fields (default 3) of the 8 extracted fields came back null — a
     low-quality-scan signal. Born-digital PDFs are governed by rule 1 only:
     a text-layer PDF that lost >3 fields is a parse-pattern failure, already
     caught by key-field absence when it matters (Q1).
  3. CALENDAR-INVALID DATE (both paths). invoice_date matched the YYYY-MM-DD
     shape but is not a real calendar date (e.g. 2024-13-45 passes ingest's
     structural regex but is semantically impossible) (Q3). GST-ratio /
     value-correctness plausibility stays OUT of scope — that lives in
     reconcile, behind the deterministic fence.

Surfaces-never-asserts (Invariant 2): the output is a DATA-QUALITY routing
decision, never a tax verdict, never an auto-correction, never a write. It
asserts nothing about GST correctness — only whether the document can be read
reliably enough to reconcile at all.

Honesty discipline: mirrors the 2B/2C full/degraded/unavailable pattern — a
non-legible status MUST carry a non-empty reason (a caveat is surfaced, never
silent); a legible status carries none. It does NOT import feeders.CoverageStatus
(that type is keyed by check-over-whole-run; this is per-DOCUMENT — wrong
granularity, and importing it would dirty this leaf).

Containment: pure stdlib (calendar, re). Imports nothing upward, no anthropic.

Three-times rule (Invariant 7): the rule is stated in this docstring (prompt),
in assess_legibility (code), and in tests/test_documents_legibility.py (test).
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

# Status levels.
LEGIBLE = "legible"
MANUAL_REVIEW_REQUIRED = "manual_review_required"
_LEVELS = frozenset({LEGIBLE, MANUAL_REVIEW_REQUIRED})

# Q1: a multimodal extraction is illegible when MORE THAN this many of the 8
# extracted fields came back null. Applies to the multimodal path only.
MAX_NULL_FIELDS = 3

# Q2: the key fields whose absence routes ANY document to manual review.
# supplier_gst_regno is intentionally excluded (its absence is a reg11 trigger).
KEY_FIELDS = ("gst_amount", "invoice_date")

# The 8 fields ingest() extracts — the denominator for the multimodal null-count.
_ALL_FIELDS = (
    "supplier_name", "supplier_gst_regno", "invoice_number", "invoice_date",
    "total_excl_gst", "gst_rate", "gst_amount", "total_incl_gst",
)

# ingest() emits dates as YYYY-MM-DD via a purely structural regex; this matches
# the same shape so we can test calendar validity of what got through.
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


@dataclass(frozen=True)
class LegibilityStatus:
    """One document's legibility decision: (level, reason).

    level  — LEGIBLE or MANUAL_REVIEW_REQUIRED.
    reason — the data-quality FACT only (no IRAS/tax rationale). MUST be non-empty
             for MANUAL_REVIEW_REQUIRED (surfaced, never silent) and empty for
             LEGIBLE.
    """

    level: str
    reason: str = ""

    def __post_init__(self) -> None:
        if self.level not in _LEVELS:
            raise ValueError(
                f"unknown legibility level {self.level!r} (expected one of {sorted(_LEVELS)})"
            )
        if self.level == LEGIBLE and self.reason:
            raise ValueError(f"a 'legible' status carries no reason; got {self.reason!r}")
        if self.level == MANUAL_REVIEW_REQUIRED and not self.reason:
            raise ValueError("a 'manual_review_required' status must surface a non-empty reason")

    @property
    def needs_manual_review(self) -> bool:
        return self.level == MANUAL_REVIEW_REQUIRED

    def as_coverage_row(self, doc_num: int) -> dict:
        """Project to a coverage-style row for the ungated Deterministic Check
        Coverage surface (Q4/Q6). Reuses the 2B/2C 'unavailable' vocabulary — the
        document's reconcile checks were NOT examined — and puts the DoD phrase
        "manual review required" in the reason so it renders explicitly. Carries
        validation_status="unvalidated" to match the surfaces-never-asserts
        discipline of the candidate stream (the renderer reads only
        check/level/reason; the flag is honest metadata)."""
        return {
            "check": f"Document legibility (doc {doc_num})",
            "level": "unavailable",
            "reason": f"manual review required — {self.reason}",
            "validation_status": "unvalidated",
        }


def _calendar_invalid_date(value: object) -> bool:
    """True iff value matches the YYYY-MM-DD shape but is not a real calendar date.

    A value that does NOT match the shape returns False here (its absence, if any,
    is handled by the key-field rule) — this function only judges values that got
    through ingest's structural regex.
    """
    if not isinstance(value, str):
        return False
    m = _ISO_DATE.match(value)
    if not m:
        return False
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not 1 <= month <= 12:
        return True
    days_in_month = calendar.monthrange(year, month)[1]
    return not 1 <= day <= days_in_month


def assess_legibility(
    extracted,
    *,
    required_fields: tuple[str, ...] = KEY_FIELDS,
    max_null_fields: int = MAX_NULL_FIELDS,
) -> LegibilityStatus:
    """Decide whether an ExtractedInvoice is legible enough to reconcile.

    Args:
        extracted:       An ExtractedInvoice (duck-typed: the 8 field attributes
                         plus .source). Not mutated.
        required_fields: Key fields whose absence forces manual review (Q2 default:
                         gst_amount + invoice_date).
        max_null_fields: Multimodal null-count threshold (Q1 default: 3; illegible
                         when strictly MORE than this many of the 8 fields are null).

    Returns:
        LegibilityStatus(LEGIBLE) when the document can be reconciled reliably,
        else LegibilityStatus(MANUAL_REVIEW_REQUIRED, <reason>) with a non-empty
        reason naming every failing condition. Never raises on a well-formed input.
    """
    reasons: list[str] = []

    # Rule 1 — key field absent (both paths).
    missing = [f for f in required_fields if getattr(extracted, f, None) is None]
    if missing:
        reasons.append(f"key field(s) absent: {', '.join(missing)}")

    # Rule 3 — calendar-invalid date that passed ingest's structural regex.
    if "invoice_date" in required_fields:
        date_value = getattr(extracted, "invoice_date", None)
        if date_value is not None and _calendar_invalid_date(date_value):
            reasons.append(f"invoice_date is not a valid calendar date: {date_value}")

    # Rule 2 — multimodal null-count (multimodal/scanned path only).
    if getattr(extracted, "source", None) == "multimodal":
        null_count = sum(1 for f in _ALL_FIELDS if getattr(extracted, f, None) is None)
        if null_count > max_null_fields:
            reasons.append(
                f"multimodal extraction returned null for {null_count} of "
                f"{len(_ALL_FIELDS)} fields (> {max_null_fields})"
            )

    if reasons:
        return LegibilityStatus(MANUAL_REVIEW_REQUIRED, "; ".join(reasons))
    return LegibilityStatus(LEGIBLE)
