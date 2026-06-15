"""
report/routing.py — finding-routing layer.

Maps (error_code, vat_group) pairs to an IRAS ASK template reference and the
verbatim Appendix 1 wording category.  No I/O; no network; never raises.

This module is the single source of truth for which ASK template section owns a
given finding type.  It is intentionally kept separate from report.constants
(which stores the wording strings) and from report.enrich (which calls it) so
that routing rules can be changed independently of the data they look up or the
aggregation logic that invokes them.

Routing overview:
    E1                  → Template 2 (standard-rated supplies)
    E2 / ZR, OS or ZP   → Template 3 (zero-rated supplies)
    E2 / ES33 or ESN33  → Template 4 or 5 (exempt supplies; flag-controlled)
    E2 / BL or NR       → Template 6 (input tax)
    E3 / SR or DS       → Template 2
    E3 / TX             → Template 6
    E4 / SR             → Template 2
    E4 / TX             → Template 6
    NO_GST_REG          → Template 6
    COMPLETENESS        → Template 1
    unrecognised        → Template 1 (safe fallback)

Dependencies:
    report.constants — APPENDIX1_WORDING and TEMPLATE_INDEX lookup tables

Exports:
    TemplateRef    — TypedDict: {number: int, label: str}
    route          — map (error_code, vat_group) → TemplateRef
    appendix1_for  — map (error_code, vat_group) → verbatim Appendix 1 string
"""
from __future__ import annotations

# from __future__ import annotations makes all annotations strings at parse time,
# enabling str | None union syntax on Python < 3.10.

from typing import TypedDict

from report.constants import APPENDIX1_WORDING, TEMPLATE_INDEX


class TemplateRef(TypedDict):
    """Typed dict identifying one IRAS ASK template section.

    Attributes:
        number: ASK template number in the range 1–7.
        label:  Full section heading string from TEMPLATE_INDEX, e.g.
                'Template 2 — Step 3A: Standard-rated Supplies and Output Tax'.
    """
    number: int
    label: str


# Frozen sets used by both _template_number and _appendix1_key for membership
# tests.  frozenset gives O(1) lookup and is immutable, preventing accidental
# mutation in either routing function.
_ZERO_RATED_VGS: frozenset[str] = frozenset({"ZR", "OS", "ZP"})
_EXEMPT_VGS: frozenset[str] = frozenset({"ES33", "ESN33"})
_BLOCKED_INPUT_VGS: frozenset[str] = frozenset({"BL", "NR"})
_SR_SALES_VGS: frozenset[str] = frozenset({"SR", "DS"})


def _template_number(
    error_code: str,
    vg: str,
    actively_makes_exempt: bool,
) -> int:
    """Resolve the ASK template number for a normalised (error_code, vat_group) pair.

    This is the core dispatch table for template routing.  Each branch maps
    directly to an IRAS ASK template as described in the module docstring.

    Args:
        error_code:           Finding type string, e.g. 'E1', 'E2', 'NO_GST_REG'.
        vg:                   VatGroup code already normalised to uppercase with
                              leading/trailing whitespace stripped.
        actively_makes_exempt: When True, E2/EXEMPT findings route to Template 4
                              (businesses that actively make exempt supplies) instead
                              of Template 5 (general businesses with incidental
                              exempt supplies).

    Returns:
        int: ASK template number 1–7.  Unrecognised (error_code, vg) pairs return
            1 as a safe fallback so the finding still appears in the report.
    """
    if error_code == "E1":
        return 2
    if error_code == "E2":
        if vg in _ZERO_RATED_VGS:
            return 3
        if vg in _EXEMPT_VGS:
            # Template 4 for businesses that actively make exempt supplies;
            # Template 5 for general businesses with incidental exempt supplies.
            return 4 if actively_makes_exempt else 5
        if vg in _BLOCKED_INPUT_VGS:
            return 6
        # E2 with an unrecognised VatGroup falls to Template 1 (analytical review)
        # rather than being silently dropped — the reviewer still needs to see it.
        return 1
    if error_code == "E3":
        if vg in _SR_SALES_VGS:
            return 2
        if vg == "TX":
            return 6
        return 1
    if error_code == "E4":
        if vg == "SR":
            return 2
        if vg == "TX":
            return 6
        return 1
    if error_code == "NO_GST_REG":
        return 6
    if error_code == "COMPLETENESS":
        return 1
    return 1  # unrecognised


def route(
    error_code: str,
    vat_group: str | None,
    *,
    actively_makes_exempt: bool = False,
) -> TemplateRef:
    """Map a finding to an IRAS ASK template reference dict {number, label}.

    Default for E2/EXEMPT is Template 5 (general business with incidental exempt
    supplies), which covers most mid-market SAP B1 clients. Template 4 is for
    financial-services / property businesses that actively make exempt supplies;
    enable it per-client by passing actively_makes_exempt=True from config.
    Unrecognised (error_code, vat_group) pairs fall back to Template 1.

    Args:
        error_code:           Finding type string, e.g. 'E1', 'E2', 'NO_GST_REG'.
        vat_group:            SAP VatGroup code, or None for findings not tied to
                              a specific line code (e.g. COMPLETENESS).
        actively_makes_exempt: Forwarded to _template_number to control Template 4
                              vs 5 routing for E2/EXEMPT findings.  Keyword-only
                              to prevent accidental positional mis-ordering.

    Returns:
        TemplateRef: Dict with 'number' (int 1–7) and 'label' (full heading string).
    """
    # Normalise vat_group to uppercase with no surrounding whitespace so callers
    # need not pre-process the value before calling route().
    vg = (vat_group or "").strip().upper()
    n = _template_number(error_code, vg, actively_makes_exempt)
    return {"number": n, "label": TEMPLATE_INDEX[n]}


def _appendix1_key(error_code: str, vg: str) -> str:
    """Resolve the APPENDIX1_WORDING lookup key for a normalised (error_code, vg) pair.

    The key space is a superset of error_code alone: E2, E3, and E4 each branch
    by VatGroup because they map to different Appendix 1 category strings depending
    on whether the finding is on the output side (sales) or input side (purchases).

    Args:
        error_code: Finding type string, already validated upstream.
        vg:         VatGroup code normalised to uppercase with whitespace stripped.

    Returns:
        str: A key from APPENDIX1_WORDING, or 'UNKNOWN_VATGROUP' if the
            (error_code, vg) combination has no defined mapping.  The caller
            always gets a valid key — 'UNKNOWN_VATGROUP' is guaranteed to exist
            in APPENDIX1_WORDING.
    """
    if error_code == "E1":
        return "E1"
    if error_code == "E2":
        if vg in _ZERO_RATED_VGS:
            return "E2_ZR"
        if vg in _EXEMPT_VGS:
            # Both ES33 and ESN33 share the same Appendix 1 wording ("E2_EXEMPT")
            # regardless of whether they route to Template 4 or 5.
            return "E2_EXEMPT"
        if vg == "BL":
            return "E2_BL"
        if vg == "NR":
            return "E2_NR"
        # E2 with an unrecognised VatGroup: use the generic classification key
        return "UNKNOWN_VATGROUP"
    if error_code == "E3":
        if vg in _SR_SALES_VGS:
            return "E3_SALES"
        if vg == "TX":
            return "E3_PURCHASE"
        return "UNKNOWN_VATGROUP"
    if error_code == "E4":
        if vg == "SR":
            return "E4_SO"
        if vg == "TX":
            return "E4_SI"
        return "UNKNOWN_VATGROUP"
    if error_code == "NO_GST_REG":
        return "NO_GST_REG"
    if error_code == "COMPLETENESS":
        return "COMPLETENESS"
    # Unrecognised error_code: fall back to a defined key rather than raising
    return "UNKNOWN_VATGROUP"


def appendix1_for(error_code: str, vat_group: str | None) -> str:
    """Return the verbatim Appendix 1 wording for a finding.

    Never raises; unresolved (error_code, vat_group) pairs fall back to the
    UNKNOWN_VATGROUP wording ("Wrong classification of supplies made").

    Args:
        error_code: Finding type string, e.g. 'E1', 'E2', 'NO_GST_REG'.
        vat_group:  SAP VatGroup code, or None for period-level findings.

    Returns:
        str: Verbatim Appendix 1 category string from APPENDIX1_WORDING.
            Always returns a non-empty string — the UNKNOWN_VATGROUP fallback
            is the last line of defence if both the key lookup and the get()
            default miss.
    """
    # Normalise for the same reason as route(): callers pass raw values from
    # chain output which may have mixed case or surrounding whitespace.
    vg = (vat_group or "").strip().upper()
    key = _appendix1_key(error_code, vg)
    return APPENDIX1_WORDING.get(key, APPENDIX1_WORDING["UNKNOWN_VATGROUP"])
