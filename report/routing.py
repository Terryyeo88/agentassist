"""
report/routing.py — finding-routing layer.
Maps (error_code, vat_group) to an IRAS ASK template reference and the
verbatim Appendix 1 wording category. No I/O; no network; never raises.
"""
from __future__ import annotations

from typing import TypedDict

from report.constants import APPENDIX1_WORDING, TEMPLATE_INDEX


class TemplateRef(TypedDict):
    number: int
    label: str


# VatGroup membership sets used by both route() and appendix1_for().
_ZERO_RATED_VGS: frozenset[str] = frozenset({"ZR", "OS"})
_EXEMPT_VGS: frozenset[str] = frozenset({"ES33", "ESN33"})
_BLOCKED_INPUT_VGS: frozenset[str] = frozenset({"BL", "NR"})
_SR_SALES_VGS: frozenset[str] = frozenset({"SO", "DS"})


def _template_number(
    error_code: str,
    vg: str,
    actively_makes_exempt: bool,
) -> int:
    if error_code == "E1":
        return 2
    if error_code == "E2":
        if vg in _ZERO_RATED_VGS:
            return 3
        if vg in _EXEMPT_VGS:
            return 4 if actively_makes_exempt else 5
        if vg in _BLOCKED_INPUT_VGS:
            return 6
        return 1
    if error_code == "E3":
        if vg in _SR_SALES_VGS:
            return 2
        if vg == "SI":
            return 6
        return 1
    if error_code == "E4":
        if vg == "SO":
            return 2
        if vg == "SI":
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
    """
    Map a finding to an IRAS ASK template reference dict {number, label}.

    Default for E2/EXEMPT is Template 5 (general business with incidental exempt
    supplies), which covers most mid-market SAP B1 clients. Template 4 is for
    financial-services / property businesses that actively make exempt supplies;
    enable it per-client by passing actively_makes_exempt=True from config.
    Unrecognised (error_code, vat_group) pairs fall back to Template 1.
    """
    vg = (vat_group or "").strip().upper()
    n = _template_number(error_code, vg, actively_makes_exempt)
    return {"number": n, "label": TEMPLATE_INDEX[n]}


def _appendix1_key(error_code: str, vg: str) -> str:
    if error_code == "E1":
        return "E1"
    if error_code == "E2":
        if vg in _ZERO_RATED_VGS:
            return "E2_ZR"
        if vg in _EXEMPT_VGS:
            return "E2_EXEMPT"
        if vg == "BL":
            return "E2_BL"
        if vg == "NR":
            return "E2_NR"
        return "UNKNOWN_VATGROUP"
    if error_code == "E3":
        if vg in _SR_SALES_VGS:
            return "E3_SALES"
        if vg == "SI":
            return "E3_PURCHASE"
        return "UNKNOWN_VATGROUP"
    if error_code == "E4":
        if vg == "SO":
            return "E4_SO"
        if vg == "SI":
            return "E4_SI"
        return "UNKNOWN_VATGROUP"
    if error_code == "NO_GST_REG":
        return "NO_GST_REG"
    if error_code == "COMPLETENESS":
        return "COMPLETENESS"
    return "UNKNOWN_VATGROUP"


def appendix1_for(error_code: str, vat_group: str | None) -> str:
    """
    Return the verbatim Appendix 1 wording for a finding.
    Never raises; unresolved (error_code, vat_group) pairs fall back to the
    UNKNOWN_VATGROUP wording ("Wrong classification of supplies made").
    """
    vg = (vat_group or "").strip().upper()
    key = _appendix1_key(error_code, vg)
    return APPENDIX1_WORDING.get(key, APPENDIX1_WORDING["UNKNOWN_VATGROUP"])
