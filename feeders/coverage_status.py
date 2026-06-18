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


def derive_coverage_statuses(coverage, *, company_wide_population_present: bool) -> list:
    """Map an ``ExtractCoverage`` (value-population-aware) onto the three in-scope checks.

    Args:
        coverage: an ``ExtractCoverage`` (duck-typed: ``is_covered(surface, field)``,
                  which is True only when the column is BOTH present AND populated).
        company_wide_population_present: whether the company-wide listing surface carried
                  any rows — SEQ_GAP needs it to distinguish "issued in another period"
                  from "never issued anywhere".

    Returns:
        list[CoverageStatus] — one per in-scope check (DUP_CLAIM, NO_GST_REG, SEQ_GAP).
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

    return statuses
