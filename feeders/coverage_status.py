"""feeders/coverage_status.py — per-check DATA-COVERAGE status (T2.12 slice 2B).

Maps the extract-feeder coverage seam (``ExtractCoverage``) onto a per-check status that
flows into the working paper, so a reviewer never signs a SILENTLY-partial review. Three
distinguishable levels, mirroring the string-enum precedent of ``reasoning_status`` /
``documents_status`` (report/sections.py):

    full              — the check's source fields are present AND populated.
    degraded(reason)  — the check ran but UNDER-DETECTS (a source field is absent/empty).
    unavailable       — the check CANNOT run at all (a load-bearing field is absent/empty);
                        it is not run in a degraded variant.

Discipline (mirrors ``AbsentDocumentProvider``'s honesty, NOT its shape): this surfaces
the DATA-COVERAGE fact and asserts no compliance verdict. A ``reason`` states the coverage
fact ONLY (e.g. "NumAtCard absent — DUP_CLAIM under-detects"); it carries NO IRAS rationale
— the tax basis is the reviewer's to source. A non-``full`` status MUST carry a non-empty
reason (a caveat is surfaced, never silent); a ``full`` status carries none. ``full`` ≠
``degraded`` ≠ ``unavailable`` ≠ a bare ran-clean-zero-findings (None) — all stay distinct.

Pure stdlib; no SAP, no anthropic, imports nothing upward (feeders is a leaf).
"""
from __future__ import annotations

from dataclasses import dataclass

from feeders import extract_schema as schema

# Status levels (string-enum precedent: reasoning_status / documents_status).
FULL = "full"
DEGRADED = "degraded"
UNAVAILABLE = "unavailable"
LEVELS = frozenset({FULL, DEGRADED, UNAVAILABLE})


@dataclass(frozen=True)
class CoverageStatus:
    """One check's data-coverage status: ``(check, level, reason)``.

    ``check``  — the check identifier (e.g. "DUP_CLAIM", "NO_GST_REG", "SEQ_GAP").
    ``level``  — one of ``LEVELS``.
    ``reason`` — data-coverage caveat. MUST be non-empty for degraded/unavailable
                 (surfaced, never silent) and empty for full. NO IRAS rationale.
    """

    check: str
    level: str
    reason: str = ""

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"unknown coverage level {self.level!r} (expected one of {sorted(LEVELS)})")
        if self.level == FULL and self.reason:
            raise ValueError(f"a 'full' status carries no reason; got {self.reason!r}")
        if self.level != FULL and not self.reason:
            raise ValueError(f"a {self.level!r} status must surface a non-empty reason")

    def as_dict(self) -> dict:
        """JSON-safe projection for the compile output / working paper."""
        return {"check": self.check, "level": self.level, "reason": self.reason}


# Data-coverage caveats — the FACT only, no IRAS rationale.
_DUP_CLAIM_DEGRADED = "NumAtCard absent or unpopulated — DUP_CLAIM under-detects."
_NO_GST_REG_UNAVAILABLE = (
    "FederalTaxID absent — NO_GST_REG cannot run; require supplier-master sheet at onboarding."
)
_SEQ_GAP_DEGRADED = "company-wide document population absent — SEQ_GAP limited to within-period."

# T2.12-2B-ext-1: the line-level E-checks (E1–E4) and the documents-surface line fields each
# is LOAD-BEARING on (PR #66 check→field map §B). These fields are always-present in a complete
# export, so their coverage was previously IMPLICIT-full; ext-1 makes it EXPLICIT through the
# SAME mechanism. Scope is E1–E4 ONLY (CardCode and computed_boxes/declared_B descoped per
# Terry's ruling: no in-scope home / not an export field). When a line field is absent or
# unpopulated the E-check still RUNS over the documents surface but UNDER-DETECTS → DEGRADED
# (NOT unavailable), mirroring DUP_CLAIM←NumAtCard. The reason names the specific missing
# field(s) — the coverage FACT only, no IRAS rationale.
_ECHECK_LINE_FIELDS: dict[str, tuple[str, ...]] = {
    "E1": ("VatGroup", "LineTotal"),
    "E2": ("VatGroup", "TaxTotal"),
    "E3": ("VatGroup", "LineTotal", "TaxTotal"),
    "E4": ("VatGroup", "LineTotal", "TaxTotal"),
}

# T2.12-2B-ext-3: the four document-pre-pass (T2.8) checks, keyed on the document_pdfs
# surface (PR #66 check→field map §A/§B). Unlike the line fields, document_pdfs is NOT a
# COVERAGE_FIELDS (surface, field) pair — the PDF provider is an engine-level seam
# (engine/review.py Phase 3, inputs.provider) the ChainReader does not carry. The signal is
# therefore a CHECK-KEYED bool (mirroring SEQ_GAP's company-wide population bool), not an
# is_covered probe. All four share one PDF-ingest gate (run_documents_pass skips a doc_num
# whose provider returns None, so reconcile is never reached), so when document_pdfs is
# absent NONE can run → UNAVAILABLE (cannot-run, the NO_GST_REG pattern — not degraded). The
# provider is binary; there is no present-but-sparse middle state representable here.
_DOC_PREPASS_CHECKS: tuple[str, ...] = (
    "gst_amount_mismatch",
    "correct_period",
    "total_inconsistency",
    "reg11_supplier_gst_absent",
)


def _doc_unavailable_reason(check: str) -> str:
    """Coverage FACT only (no IRAS rationale) for an absent document_pdfs surface."""
    return (
        f"source documents (document_pdfs) absent — {check} cannot run; "
        "supply source-document PDFs at onboarding."
    )


def derive_coverage_statuses(
    coverage,
    *,
    company_wide_population_present: bool,
    document_pdfs_present: bool = False,
) -> list:
    """Map an ``ExtractCoverage`` (value-population-aware) onto the in-scope checks.

    Args:
        coverage: an ``ExtractCoverage`` (duck-typed: ``is_covered(surface, field)``,
                  which is True only when the column is BOTH present AND populated).
        company_wide_population_present: whether the company-wide listing surface carried
                  any rows — SEQ_GAP needs it to distinguish "issued in another period"
                  from "never issued anywhere".
        document_pdfs_present: whether a source-document (PDF) surface is available for the
                  document-pre-pass checks (ext-3). NOT a COVERAGE_FIELDS pair — the PDF
                  provider is an engine-level seam, so this is a check-keyed bool like
                  ``company_wide_population_present``. Defaults to ``False`` (the honest
                  "absent unless declared present"): the extract feeder is a listing-only
                  export with no PDF surface, so its reader passes ``False`` and the four
                  document checks are reported ``unavailable``.

    Returns:
        list[CoverageStatus] — the three locked 2B cases (DUP_CLAIM, NO_GST_REG, SEQ_GAP)
        FIRST and in order, then the four line-level E-checks (E1–E4) appended by ext-1,
        then the four document-pre-pass checks appended by ext-3.
    """
    statuses: list = []

    # NumAtCard absent/empty → DUP_CLAIM under-detects (still runs) → degraded.
    if coverage.is_covered(schema.LISTING_SHEET, "NumAtCard"):
        statuses.append(CoverageStatus("DUP_CLAIM", FULL))
    else:
        statuses.append(CoverageStatus("DUP_CLAIM", DEGRADED, _DUP_CLAIM_DEGRADED))

    # FederalTaxID absent/empty → NO_GST_REG cannot run → unavailable (NOT a degraded run).
    if coverage.is_covered(schema.BUSINESS_PARTNERS_SHEET, "FederalTaxID"):
        statuses.append(CoverageStatus("NO_GST_REG", FULL))
    else:
        statuses.append(CoverageStatus("NO_GST_REG", UNAVAILABLE, _NO_GST_REG_UNAVAILABLE))

    # Company-wide population absent → SEQ_GAP limited to within-period → degraded.
    if company_wide_population_present:
        statuses.append(CoverageStatus("SEQ_GAP", FULL))
    else:
        statuses.append(CoverageStatus("SEQ_GAP", DEGRADED, _SEQ_GAP_DEGRADED))

    # ext-1: E1–E4 over the documents surface, population-aware via the SAME is_covered
    # predicate. full when every load-bearing line field is covered; degraded (under-detects)
    # naming the missing field(s) otherwise.
    for check, fields in _ECHECK_LINE_FIELDS.items():
        missing = [f for f in fields if not coverage.is_covered(schema.DOCUMENTS_SHEET, f)]
        if not missing:
            statuses.append(CoverageStatus(check, FULL))
        else:
            reason = f"{'/'.join(missing)} absent or unpopulated — {check} under-detects."
            statuses.append(CoverageStatus(check, DEGRADED, reason))

    # ext-3: the four document-pre-pass checks, keyed on the document_pdfs surface bool.
    # present → full; absent → unavailable (cannot-run, shared PDF-ingest gate). All four
    # are identical at this granularity (binary provider, no present-but-sparse middle state).
    for check in _DOC_PREPASS_CHECKS:
        if document_pdfs_present:
            statuses.append(CoverageStatus(check, FULL))
        else:
            statuses.append(CoverageStatus(check, UNAVAILABLE, _doc_unavailable_reason(check)))

    return statuses
