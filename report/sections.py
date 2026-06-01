"""
report/sections.py — pure-data section builders.
Each builder returns a dataclass; no PDF, no I/O, no network.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from report.constants import DISCLAIMER_TEXT, NOT_EXAMINED_ITEMS
from report.enrich import EnrichedFinding
from report.routing import TemplateRef

# ── Severity sort order ───────────────────────────────────────────────────────

_SEV_ORDER: dict[str, int] = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


# ── Static F5 box → contributing VatGroup codes ───────────────────────────────
# Source: F5_BOX_MAPPING in sap_b1_server.py (lt_box / tt_box routing).
# Derived boxes (box_4, box_8) carry no direct VatGroup contribution.

_BOX_VATGROUPS: dict[str, list[str]] = {
    "box_1_standard_rated_sales": ["SO", "DS"],
    "box_2_zero_rated_sales":     ["ZR"],
    "box_3_exempt_sales":         ["ES33", "ESN33"],
    "box_4_total_sales":          [],   # derived: box_1 + box_2 + box_3
    "box_5_taxable_purchases":    ["SI", "ZP", "IM", "IGDS", "ME"],
    "box_6_output_tax":           ["SO", "DS"],
    "box_7_input_tax":            ["SI", "IM", "IGDS"],
    "box_8_net_gst":              [],   # derived: box_6 - box_7
}


# ── Section dataclasses ───────────────────────────────────────────────────────

@dataclass
class CoverSection:
    client_name: str
    gst_registration_number: str
    period_start: str
    period_end: str
    generated_at: str
    reviewer_name: str
    firm_name: str


@dataclass
class ScopeSection:
    period_start: str
    period_end: str
    items_examined: dict[str, int]   # doc_type → count from FetchManifest
    fx_excluded: list[dict]          # fx_invoices_requiring_conversion
    credit_notes_applied: list[dict]


@dataclass
class F5BoxAttribution:
    box_name: str
    box_value: float
    vat_groups: list[str]   # filtered to VatGroups present in vatgroup_inventory


@dataclass
class F5BoxSection:
    boxes: dict[str, float]
    attribution: list[F5BoxAttribution]


@dataclass
class FindingsGroup:
    template_ref: TemplateRef
    findings: list[EnrichedFinding]   # sorted HIGH→MEDIUM→LOW then doc_num asc


@dataclass
class FindingsSection:
    groups: list[FindingsGroup]
    total_findings: int


@dataclass
class CrossFindingEntry:
    doc_num: int
    error_codes: list[str]    # sorted
    findings: list[EnrichedFinding]


@dataclass
class CrossFindingSection:
    """Doc_nums appearing under more than one distinct error_code."""
    multi_error_docs: list[CrossFindingEntry]


@dataclass
class JudgmentGroup:
    group_id: str             # e.g. "export-evidence"
    display_title: str        # human label for rendering, e.g. "Export Evidence"
    judgment_question: str
    doc_nums: list[int]       # DocNums the reviewer must act on


@dataclass
class JudgmentSection:
    """Data-driven groups for reviewer judgment. Only groups with doc_nums are included."""
    groups: list[JudgmentGroup]


@dataclass
class NotExaminedSection:
    items: list[str]   # NOT_EXAMINED_ITEMS + anomalies + custom_vat_groups note


@dataclass
class SignatureSection:
    reviewer_name: str
    firm_name: str
    gst_registration_number: str
    disclaimer: str


# ── Builder functions ─────────────────────────────────────────────────────────

def build_cover_section(
    compile_output: dict[str, Any],
    client_config: Any,
    *,
    generated_at: str,
) -> CoverSection:
    period = compile_output["period"]
    return CoverSection(
        client_name=getattr(client_config, "client_name", ""),
        gst_registration_number=getattr(client_config, "gst_registration_number", ""),
        period_start=period["start"],
        period_end=period["end"],
        generated_at=generated_at,
        reviewer_name=getattr(client_config, "reviewer_name", ""),
        firm_name=getattr(client_config, "firm_name", ""),
    )


def build_scope_section(compile_output: dict[str, Any]) -> ScopeSection:
    period = compile_output["period"]
    records = compile_output["fetch_manifest"]["records"]
    items_examined: dict[str, int] = dict(Counter(r["doc_type"] for r in records))
    return ScopeSection(
        period_start=period["start"],
        period_end=period["end"],
        items_examined=items_examined,
        fx_excluded=compile_output["calculate"]["fx_invoices_requiring_conversion"],
        credit_notes_applied=compile_output["calculate"]["credit_notes_applied"],
    )


def build_f5_box_section(compile_output: dict[str, Any]) -> F5BoxSection:
    boxes: dict[str, float] = compile_output["calculate"]["boxes"]
    inventory: dict[str, Any] = compile_output["classify"]["vatgroup_inventory"]

    attribution: list[F5BoxAttribution] = []
    for box_name in _BOX_VATGROUPS:
        raw_vgs = _BOX_VATGROUPS[box_name]
        filtered = [vg for vg in raw_vgs if vg in inventory]
        attribution.append(F5BoxAttribution(
            box_name=box_name,
            box_value=boxes.get(box_name, 0.0),
            vat_groups=filtered,
        ))

    return F5BoxSection(boxes=boxes, attribution=attribution)


def build_findings_section(findings: list[EnrichedFinding]) -> FindingsSection:
    groups_by_template: dict[int, list[EnrichedFinding]] = defaultdict(list)
    for f in findings:
        groups_by_template[f.template_ref["number"]].append(f)

    result_groups: list[FindingsGroup] = []
    for n in sorted(groups_by_template):
        sorted_findings = sorted(
            groups_by_template[n],
            key=lambda f: (
                _SEV_ORDER.get(f.severity, 2),
                f.doc_num if f.doc_num is not None else float("inf"),
            ),
        )
        result_groups.append(FindingsGroup(
            template_ref=sorted_findings[0].template_ref,
            findings=sorted_findings,
        ))

    return FindingsSection(groups=result_groups, total_findings=len(findings))


def build_cross_finding_section(findings: list[EnrichedFinding]) -> CrossFindingSection:
    doc_errors: dict[int, set[str]] = defaultdict(set)
    doc_finding_map: dict[int, list[EnrichedFinding]] = defaultdict(list)

    for f in findings:
        if f.doc_num is not None:
            doc_errors[f.doc_num].add(f.error_code)
            doc_finding_map[f.doc_num].append(f)

    entries = [
        CrossFindingEntry(
            doc_num=doc_num,
            error_codes=sorted(error_codes),
            findings=doc_finding_map[doc_num],
        )
        for doc_num, error_codes in doc_errors.items()
        if len(error_codes) > 1
    ]

    return CrossFindingSection(
        multi_error_docs=sorted(entries, key=lambda e: e.doc_num)
    )


def build_judgment_section(
    compile_output: dict[str, Any],
    findings: list[EnrichedFinding],
) -> JudgmentSection:
    groups: list[JudgmentGroup] = []

    # 1. Export evidence — E1: FX sales coded as local standard-rated.
    e1_docs = sorted({f.doc_num for f in findings if f.error_code == "E1" and f.doc_num is not None})
    if e1_docs:
        groups.append(JudgmentGroup(
            group_id="export-evidence",
            display_title="Export Evidence",
            judgment_question=(
                "For each FX sales invoice coded as standard-rated (SO/DS): confirm "
                "the supply is a genuine overseas or export sale. If so, the correct "
                "VatGroup is ZR (zero-rated supply) per IRAS s21(3). Reclassification "
                "requires a correcting entry and evidence of export (bill of lading, "
                "air waybill, export permit, or equivalent)."
            ),
            doc_nums=e1_docs,
        ))

    # 2. Exemption qualification — E2 on ES33/ESN33.
    exempt_docs = sorted({
        f.doc_num for f in findings
        if f.error_code == "E2"
        and f.vat_group in {"ES33", "ESN33"}
        and f.doc_num is not None
    })
    if exempt_docs:
        groups.append(JudgmentGroup(
            group_id="exemption-qualification",
            display_title="Exemption Qualification",
            judgment_question=(
                "For each ES33/ESN33 supply carrying GST: confirm the supply genuinely "
                "qualifies as exempt (i.e., relates to financial services or the "
                "sale/rental of residential properties per IRAS 4th Schedule). "
                "If not, the supply is standard-rated and the VatGroup must be corrected."
            ),
            doc_nums=exempt_docs,
        ))

    # 3. Business purpose / Reg 26-27 — E2 on BL (blocked input).
    bl_docs = sorted({
        f.doc_num for f in findings
        if f.error_code == "E2" and f.vat_group == "BL" and f.doc_num is not None
    })
    if bl_docs:
        groups.append(JudgmentGroup(
            group_id="business-purpose-reg26-27",
            display_title="Business Purpose (Reg 26/27)",
            judgment_question=(
                "For each BL-coded expense carrying GST (disallowed under GST (General) "
                "Regulations 26 and 27): confirm the GST charge on the supplier invoice "
                "is correct and that no input tax has been claimed against it in SAP B1."
            ),
            doc_nums=bl_docs,
        ))

    # 4. Supplier registration — NO_GST_REG.
    ngr_docs = sorted({
        f.doc_num for f in findings
        if f.error_code == "NO_GST_REG" and f.doc_num is not None
    })
    if ngr_docs:
        groups.append(JudgmentGroup(
            group_id="supplier-registration",
            display_title="Supplier Registration",
            judgment_question=(
                "For each supplier with input tax claims but no GST registration number "
                "on record: verify the supplier's current GST registration status with IRAS. "
                "Note: if your SAP B1 instance stores GST registration numbers in a "
                "User Defined Field (UDF) rather than the standard FederalTaxID field, "
                "these findings may be false positives requiring UDF-to-FederalTaxID mapping."
            ),
            doc_nums=ngr_docs,
        ))

    return JudgmentSection(groups=groups)


def build_not_examined_section(
    compile_output: dict[str, Any],
    client_config: Any,
) -> NotExaminedSection:
    items: list[str] = list(NOT_EXAMINED_ITEMS)

    # Surface any deduplicated anomalies (unknown VatGroups).
    for anomaly in compile_output.get("deduplicated_anomalies", []):
        items.append(
            f"Anomaly — doc_num={anomaly['doc_num']}: {anomaly['issue']}"
        )

    # Custom VatGroups note if client has any.
    custom_vgs: dict = getattr(client_config, "custom_vat_groups", {}) or {}
    if custom_vgs:
        codes = ", ".join(sorted(custom_vgs.keys()))
        items.append(
            f"Client-specific VatGroup code(s) ({codes}) are mapped via client "
            "configuration but have not been independently verified against IRAS guidance."
        )

    return NotExaminedSection(items=items)


def build_signature_section(client_config: Any) -> SignatureSection:
    return SignatureSection(
        reviewer_name=getattr(client_config, "reviewer_name", ""),
        firm_name=getattr(client_config, "firm_name", ""),
        gst_registration_number=getattr(client_config, "gst_registration_number", ""),
        disclaimer=DISCLAIMER_TEXT,
    )
