"""
report/sections.py — pure-data section builders.

Each builder returns a typed dataclass representing one section of the PDF
report.  No PDF rendering, no I/O, no network calls — all builders are pure
transformations of CompileOutput dicts and EnrichedFindings into structured
data that render.py can consume without any further business logic.

Data flow:
    CompileOutput dict  ──▶  build_*_section()  ──▶  *Section dataclass
    list[EnrichedFinding] ──▶  build_findings_section()  ──▶  FindingsSection
                               build_cross_finding_section()  ──▶  CrossFindingSection
                               build_judgment_section()  ──▶  JudgmentSection

The section dataclasses intentionally mirror the PDF section structure (cover,
scope, F5 boxes, findings, cross-findings, judgment, not-examined, signature,
AI candidates) so that render.py's section renderers have a 1:1 model to read
from without making any data decisions.

Dependencies:
    report.constants — DISCLAIMER_TEXT, NOT_EXAMINED_ITEMS
    report.enrich    — EnrichedFinding
    report.routing   — TemplateRef

Exports:
    One dataclass and one builder per report section (see section dataclasses
    and builder functions below).
"""
from __future__ import annotations

# from __future__ import annotations makes all annotations strings at parse time,
# enabling lowercase generic hints and str | None union syntax on Python < 3.10.

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from report.constants import DISCLAIMER_TEXT, NOT_EXAMINED_ITEMS
from report.enrich import EnrichedFinding
from report.routing import TemplateRef

# ── Severity sort order ───────────────────────────────────────────────────────

# Maps severity strings to integer sort keys; used as the primary sort key
# wherever findings are ordered HIGH → MEDIUM → LOW within a group.
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
    """Data for the report cover page.

    All fields are plain strings so the renderer can embed them directly into
    Paragraph flowables without further transformation.

    Attributes:
        client_name:              Display name of the SAP B1 client entity.
        gst_registration_number:  GST registration number, or empty string if not
                                  configured.
        period_start:             ISO date 'YYYY-MM-DD' for the review period start.
        period_end:               ISO date 'YYYY-MM-DD' for the review period end.
        generated_at:             ISO 8601 timestamp from the chain's fetched_at.
        reviewer_name:            Name of the practitioner of record.
        firm_name:                Name of the reviewer's firm.
    """
    client_name: str
    gst_registration_number: str
    period_start: str
    period_end: str
    generated_at: str
    reviewer_name: str
    firm_name: str


@dataclass
class ScopeSection:
    """Data for Section 1 — Scope (items examined, FX exclusions, credit notes).

    Attributes:
        period_start:          ISO date for the review period start.
        period_end:            ISO date for the review period end.
        items_examined:        Document-type → count from FetchManifest records.
                               Keys are doc_type strings (e.g. 'invoice',
                               'purchase_invoice'); values are total counts.
        fx_excluded:           List of FX invoice dicts from calculate's
                               fx_invoices_requiring_conversion.  Each dict
                               contains doc_num, doc_date, card_name, currency,
                               doc_total, and type.
        credit_notes_applied:  List of credit note adjustment dicts from calculate's
                               credit_notes_applied.  Each dict contains doc_num,
                               doc_date, card_name, type, vat_group,
                               line_total_applied, and tax_total_applied.
    """
    period_start: str
    period_end: str
    items_examined: dict[str, int]   # doc_type → count from FetchManifest
    fx_excluded: list[dict]          # fx_invoices_requiring_conversion
    credit_notes_applied: list[dict]


@dataclass
class F5BoxAttribution:
    """One row in the F5 box table: a named box with its SGD value and contributing VatGroups.

    Attributes:
        box_name:   Internal box key, e.g. 'box_1_standard_rated_sales'.
        box_value:  Computed SGD amount for this box (already rounded to 2 dp).
        vat_groups: VatGroup codes from _BOX_VATGROUPS that were actually seen
                    in the period's vatgroup_inventory.  Codes present in the
                    static mapping but absent from the inventory are excluded so
                    the renderer shows only codes with actual transactions.
    """
    box_name: str
    box_value: float
    vat_groups: list[str]   # filtered to VatGroups present in vatgroup_inventory


@dataclass
class F5BoxSection:
    """Data for Section 2 — F5 box figures.

    Attributes:
        boxes:       Raw box-name → SGD value dict from calculate output.
        attribution: Ordered list of F5BoxAttribution rows, one per box in
                     _BOX_VATGROUPS insertion order (matching the F5 form order).
    """
    boxes: dict[str, float]
    attribution: list[F5BoxAttribution]


@dataclass
class FindingsGroup:
    """A single ASK template's worth of findings, sorted and ready for rendering.

    Attributes:
        template_ref: The TemplateRef for this group (number + label).  Taken
                      from the first finding in the group; all findings in the
                      group share the same template number by construction.
        findings:     Findings sorted HIGH → MEDIUM → LOW, then doc_num ascending.
                      COMPLETENESS (doc_num=None) sorts after all numbered docs.
    """
    template_ref: TemplateRef
    findings: list[EnrichedFinding]   # sorted HIGH→MEDIUM→LOW then doc_num asc


@dataclass
class FindingsSection:
    """Data for Section 3 — all findings grouped by ASK template.

    Attributes:
        groups:          One FindingsGroup per ASK template that has at least one
                         finding, in ascending template-number order.
        total_findings:  Total count of all EnrichedFindings across all groups.
    """
    groups: list[FindingsGroup]
    total_findings: int


@dataclass
class CrossFindingEntry:
    """One document that carries more than one distinct error code.

    Attributes:
        doc_num:      SAP B1 document number.
        error_codes:  Sorted list of distinct error codes found on this document.
        findings:     All EnrichedFindings for this document (unsorted; renderer
                      may display all or just summary fields).
    """
    doc_num: int
    error_codes: list[str]    # sorted
    findings: list[EnrichedFinding]


@dataclass
class CrossFindingSection:
    """Doc_nums appearing under more than one distinct error_code."""
    multi_error_docs: list[CrossFindingEntry]


@dataclass
class JudgmentGroup:
    """One judgment item requiring a reviewer decision, with the affected doc_nums.

    Attributes:
        group_id:          Machine-readable slug, e.g. 'export-evidence'.
        display_title:     Human-readable heading for the rendered subsection.
        judgment_question: Guidance paragraph telling the reviewer what to assess.
        doc_nums:          Sorted list of SAP B1 document numbers the reviewer
                           must act on for this judgment item.
    """
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
    """Data for Section 6 — coverage boundary items.

    Attributes:
        items: Ordered list of out-of-scope description strings.  Starts with
               the standard NOT_EXAMINED_ITEMS from constants, then appends
               any deduplicated anomalies and a custom VatGroups note if
               applicable.  Order is preserved from NOT_EXAMINED_ITEMS so
               higher-risk exclusions appear first.
    """
    items: list[str]   # NOT_EXAMINED_ITEMS + anomalies + custom_vat_groups note


@dataclass
class AICandidateRow:
    """One AI-surfaced Reg 26/27 candidate line for the candidates table.

    Attributes:
        doc_num:            SAP B1 document number.
        line_index:         0-based index of the line within the document.
        doc_date:           Document date as ISO string 'YYYY-MM-DD'.
        card_name:          Business partner name.
        line_description:   Free-text line description from the document.
        suspected_category: Model's classification of the expense category.
        confidence:         Model's self-reported confidence level string.
        phrasing:           Verbatim reviewer-prompt text from the judgment artefact.
    """
    doc_num: int
    line_index: int
    doc_date: str
    card_name: str
    line_description: str
    suspected_category: str
    confidence: str
    phrasing: str    # verbatim from the judgment artefact


@dataclass
class AICandidatesSection:
    """AI-surfaced Reg 26/27 candidates, optionally rendered in Section 5.

    show=False  → render nothing (flag is OFF).
    show=True, status="disabled"
                → same (no artefact was produced).
    show=True, status="ok", candidate_count >= 1
                → render the candidates table.
    show=True, status="ok", candidate_count == 0
                → render "No AI-surfaced candidates".
    show=True, status="errored"
                → render "AI candidate pass did not complete".
    """
    show: bool
    status: str              # "ok" | "errored" | "disabled"
    candidates: list[AICandidateRow]
    disclaimer: str
    candidate_count: int


@dataclass
class SignatureSection:
    """Data for the declaration and sign-off page.

    Attributes:
        reviewer_name:           Name of the practitioner of record.
        firm_name:               Name of the reviewer's firm.
        gst_registration_number: Reviewer's firm GST registration number, or
                                 empty string if not configured.
        disclaimer:              Verbatim disclaimer text from DISCLAIMER_TEXT
                                 in report.constants.
    """
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
    """Build the CoverSection from chain output and client config.

    Args:
        compile_output: CompileOutput dict; only the 'period' key is read.
        client_config:  ClientConfig (or duck-typed object).  Fields are read
                        via getattr with empty-string defaults so missing
                        attributes degrade gracefully rather than raising.
        generated_at:   ISO 8601 timestamp string; keyword-only to prevent
                        accidental positional mis-ordering.

    Returns:
        CoverSection: Populated with client metadata and period dates.
    """
    period = compile_output["period"]
    return CoverSection(
        # getattr with "" default: allows ClientConfig fields to be optional
        # without requiring a schema change when new fields are added.
        client_name=getattr(client_config, "client_name", ""),
        gst_registration_number=getattr(client_config, "gst_registration_number", ""),
        period_start=period["start"],
        period_end=period["end"],
        generated_at=generated_at,
        reviewer_name=getattr(client_config, "reviewer_name", ""),
        firm_name=getattr(client_config, "firm_name", ""),
    )


def build_scope_section(compile_output: dict[str, Any]) -> ScopeSection:
    """Build the ScopeSection from chain output.

    Derives the items_examined count by tallying doc_type values across all
    FetchManifest records using Counter — one tally per record, not per document,
    so split records are counted separately.

    Args:
        compile_output: CompileOutput dict; reads 'period', 'fetch_manifest',
                        and 'calculate' keys.

    Returns:
        ScopeSection: Populated with period dates, document-type counts, FX
            exclusions, and credit note adjustments.
    """
    period = compile_output["period"]
    records = compile_output["fetch_manifest"]["records"]
    # Counter produces {doc_type: count} in one pass over the records list
    items_examined: dict[str, int] = dict(Counter(r["doc_type"] for r in records))
    return ScopeSection(
        period_start=period["start"],
        period_end=period["end"],
        items_examined=items_examined,
        fx_excluded=compile_output["calculate"]["fx_invoices_requiring_conversion"],
        credit_notes_applied=compile_output["calculate"]["credit_notes_applied"],
    )


def build_f5_box_section(compile_output: dict[str, Any]) -> F5BoxSection:
    """Build the F5BoxSection with per-box VatGroup attribution.

    For each F5 box, filters the static VatGroup list in _BOX_VATGROUPS to only
    the codes present in the period's vatgroup_inventory.  This ensures the
    report shows only codes with actual transactions rather than every code that
    could theoretically contribute to the box.

    Args:
        compile_output: CompileOutput dict; reads 'calculate' (boxes) and
                        'classify' (vatgroup_inventory) keys.

    Returns:
        F5BoxSection: Boxes dict plus one F5BoxAttribution per box in F5 form order.
    """
    boxes: dict[str, float] = compile_output["calculate"]["boxes"]
    inventory: dict[str, Any] = compile_output["classify"]["vatgroup_inventory"]

    attribution: list[F5BoxAttribution] = []
    for box_name in _BOX_VATGROUPS:
        raw_vgs = _BOX_VATGROUPS[box_name]
        # Keep only codes seen in the period; avoids showing unused codes in the report
        filtered = [vg for vg in raw_vgs if vg in inventory]
        attribution.append(F5BoxAttribution(
            box_name=box_name,
            box_value=boxes.get(box_name, 0.0),
            vat_groups=filtered,
        ))

    return F5BoxSection(boxes=boxes, attribution=attribution)


def build_findings_section(findings: list[EnrichedFinding]) -> FindingsSection:
    """Group and sort EnrichedFindings by ASK template for Section 3.

    Groups findings by template number (from each finding's template_ref),
    sorts within each group HIGH → MEDIUM → LOW then doc_num ascending, and
    orders the groups by ascending template number.

    Args:
        findings: Flat list of EnrichedFindings from report.enrich.enrich().

    Returns:
        FindingsSection: Groups in template-number order, each internally sorted,
            plus the total findings count across all groups.
    """
    # defaultdict(list) accumulates findings per template number in one pass
    groups_by_template: dict[int, list[EnrichedFinding]] = defaultdict(list)
    for f in findings:
        groups_by_template[f.template_ref["number"]].append(f)

    result_groups: list[FindingsGroup] = []
    for n in sorted(groups_by_template):
        sorted_findings = sorted(
            groups_by_template[n],
            key=lambda f: (
                _SEV_ORDER.get(f.severity, 2),
                # float("inf") sorts None doc_nums (e.g. COMPLETENESS) after all
                # numbered documents within each severity band
                f.doc_num if f.doc_num is not None else float("inf"),
            ),
        )
        result_groups.append(FindingsGroup(
            # All findings in the group share the same template number, so the
            # first finding's template_ref is representative of the whole group.
            template_ref=sorted_findings[0].template_ref,
            findings=sorted_findings,
        ))

    return FindingsSection(groups=result_groups, total_findings=len(findings))


def build_cross_finding_section(findings: list[EnrichedFinding]) -> CrossFindingSection:
    """Identify documents carrying more than one distinct error code.

    Builds a set of error codes per doc_num in one pass, then filters to only
    those with two or more distinct codes.  Period-level findings (doc_num=None,
    e.g. COMPLETENESS) are excluded — they are not tied to a specific document.

    Args:
        findings: Flat list of EnrichedFindings from report.enrich.enrich().

    Returns:
        CrossFindingSection: Entries sorted by doc_num ascending, each containing
            the sorted error codes and all related findings.
    """
    # defaultdict(set) accumulates distinct error codes per doc_num in one pass
    doc_errors: dict[int, set[str]] = defaultdict(set)
    doc_finding_map: dict[int, list[EnrichedFinding]] = defaultdict(list)

    for f in findings:
        # Skip period-level findings (COMPLETENESS) which have no document number
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
        # Only include documents with two or more distinct error codes
        if len(error_codes) > 1
    ]

    return CrossFindingSection(
        multi_error_docs=sorted(entries, key=lambda e: e.doc_num)
    )


def build_judgment_section(
    compile_output: dict[str, Any],
    findings: list[EnrichedFinding],
) -> JudgmentSection:
    """Build Section 5 judgment groups from findings requiring reviewer decisions.

    Produces up to four judgment groups, each covering a class of finding that
    cannot be resolved automatically and requires professional assessment:
      1. Export evidence (E1) — FX sales potentially mis-coded as local.
      2. Exemption qualification (E2/ES33/ESN33) — supplies claiming exempt status.
      3. Business purpose / Reg 26-27 (E2/BL) — blocked input tax expenses.
      4. Supplier registration (NO_GST_REG) — input tax from unregistered suppliers.

    Groups with no affected doc_nums are omitted so empty sections never appear.

    Args:
        compile_output: CompileOutput dict (currently unused; reserved for future
                        judgment triggers sourced directly from chain output).
        findings:       Flat list of EnrichedFindings from report.enrich.enrich().

    Returns:
        JudgmentSection: Only populated groups (those with at least one doc_num).
    """
    groups: list[JudgmentGroup] = []

    # 1. Export evidence — E1: FX sales coded as local standard-rated.
    # Set comprehension deduplicates doc_nums before sorting; a doc can have
    # multiple E1 lines but should appear only once in the judgment list.
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
    """Build Section 6 — coverage boundary from constants plus run-specific additions.

    Starts with the standard NOT_EXAMINED_ITEMS list (copied, not mutated),
    then appends two types of run-specific additions:
      * Deduplicated anomalies from the chain run (unknown VatGroup codes).
      * A note about client-specific VatGroup codes if any are configured.

    Args:
        compile_output: CompileOutput dict; reads 'deduplicated_anomalies' if
                        present (absent in older chain runs; defaults to []).
        client_config:  ClientConfig; reads 'custom_vat_groups' via getattr.

    Returns:
        NotExaminedSection: Items list in display order (standard items first,
            run-specific additions appended).
    """
    # Copy to avoid mutating the module-level constant across calls
    items: list[str] = list(NOT_EXAMINED_ITEMS)

    # Surface any deduplicated anomalies (unknown VatGroups).
    # .get() with default guards against older chain runs that lack this key.
    for anomaly in compile_output.get("deduplicated_anomalies", []):
        items.append(
            f"Anomaly — doc_num={anomaly['doc_num']}: {anomaly['issue']}"
        )

    # Custom VatGroups note if client has any.
    custom_vgs: dict = getattr(client_config, "custom_vat_groups", {}) or {}
    if custom_vgs:
        # Sorted for stable output order regardless of dict insertion order
        codes = ", ".join(sorted(custom_vgs.keys()))
        items.append(
            f"Client-specific VatGroup code(s) ({codes}) are mapped via client "
            "configuration but have not been independently verified against IRAS guidance."
        )

    return NotExaminedSection(items=items)


def build_signature_section(client_config: Any) -> SignatureSection:
    """Build the SignatureSection from client config.

    Args:
        client_config: ClientConfig; fields read via getattr with empty-string
                       defaults so missing attributes degrade gracefully.

    Returns:
        SignatureSection: Reviewer metadata plus the verbatim DISCLAIMER_TEXT
            from report.constants.
    """
    return SignatureSection(
        reviewer_name=getattr(client_config, "reviewer_name", ""),
        firm_name=getattr(client_config, "firm_name", ""),
        gst_registration_number=getattr(client_config, "gst_registration_number", ""),
        # DISCLAIMER_TEXT is used verbatim — must not be reformatted here
        disclaimer=DISCLAIMER_TEXT,
    )


def build_ai_candidates_section(
    judgment_artefact: dict | None,
    *,
    show: bool,
) -> AICandidatesSection:
    """Build the optional AI-candidates subsection for Section 5.

    When show=False the section is built with status="disabled" so the renderer
    can skip it unconditionally without reading the artefact.  When show=True
    the artefact is examined; a missing artefact (None) produces status="errored"
    so the renderer shows the placeholder line.

    AI candidates are NEVER included in deterministic finding totals; this
    section is purely additive and visually separate.

    Args:
        judgment_artefact: Dict loaded from the AI judgment-candidates artefact
                           (steps/judgment-candidates.json), or None if the pass
                           did not run or the file is missing.
        show:              Feature flag from client_config.show_ai_candidates.
                           Keyword-only to prevent accidental positional errors.

    Returns:
        AICandidatesSection: Fully populated regardless of show/status so the
            renderer never needs to handle None.
    """
    if not show:
        return AICandidatesSection(
            show=False, status="disabled", candidates=[], disclaimer="",
            candidate_count=0,
        )

    if judgment_artefact is None:
        return AICandidatesSection(
            show=True, status="errored", candidates=[], disclaimer="",
            candidate_count=0,
        )

    # Guard against None status in a malformed or partially-written artefact
    status: str = str(judgment_artefact.get("status") or "errored")
    disclaimer: str = str(judgment_artefact.get("disclaimer") or "")

    if status != "ok":
        return AICandidatesSection(
            show=True, status=status, candidates=[], disclaimer=disclaimer,
            candidate_count=0,
        )

    raw_candidates: list = judgment_artefact.get("candidates") or []
    # Defensive str()/int() conversions throughout: AI-generated JSON may have
    # numeric fields as strings or None, so coerce rather than trust the types.
    candidates: list[AICandidateRow] = [
        AICandidateRow(
            doc_num=int(c.get("doc_num") or 0),
            line_index=int(c.get("line_index") or 0),
            doc_date=str(c.get("doc_date") or ""),
            card_name=str(c.get("card_name") or ""),
            line_description=str(c.get("line_description") or ""),
            suspected_category=str(c.get("suspected_category") or ""),
            confidence=str(c.get("confidence") or ""),
            phrasing=str(c.get("phrasing") or ""),
        )
        for c in raw_candidates
    ]
    return AICandidatesSection(
        show=True,
        status="ok",
        candidates=candidates,
        disclaimer=disclaimer,
        candidate_count=len(candidates),
    )
