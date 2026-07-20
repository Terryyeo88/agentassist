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
from typing import Any, Literal

from config.source_labels import source_display_name
from report.constants import NOT_EXAMINED_ITEMS, disclaimer_text_for
from report.enrich import EnrichedFinding
from report.routing import TemplateRef


def _source_label(client_config: Any, long: bool = False) -> str:
    """Display label for the config's data source; missing/None -> SAP (the
    ClientConfig default) so duck-typed test configs and legacy callers keep the
    exact pre-D-2026-07-20 wording (invariant-auditor caveats 1-2)."""
    return source_display_name(
        getattr(client_config, "source_system", None), long=long
    )

# ── Severity sort order ───────────────────────────────────────────────────────

# Maps severity strings to integer sort keys; used as the primary sort key
# wherever findings are ordered HIGH → MEDIUM → LOW within a group.
_SEV_ORDER: dict[str, int] = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


# ── Static F5 box → contributing VatGroup codes ───────────────────────────────
# Source: F5_BOX_MAPPING in sap_b1_server.py (lt_box / tt_box routing).
# Derived boxes (box_4, box_8) carry no direct VatGroup contribution.

_BOX_VATGROUPS: dict[str, list[str]] = {
    "box_1_standard_rated_sales": ["SR", "DS"],
    "box_2_zero_rated_sales":     ["ZR"],
    "box_3_exempt_sales":         ["ES33", "ESN33"],
    "box_4_total_sales":          [],   # derived: box_1 + box_2 + box_3
    "box_5_taxable_purchases":    ["TX", "ZP", "IM", "IGDS", "ME"],
    "box_6_output_tax":           ["SR", "DS"],
    "box_7_input_tax":            ["TX", "IM", "IGDS"],
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
class ReviewCandidateRow:
    """One row in the unified AI-Surfaced Candidates table.

    Adapts both reasoning candidates (basis="description analysis") and document
    candidates (basis="invoice cross-reference") into a common view, so a single
    table can present candidates from both mechanisms with a mandatory per-row
    basis tag.
    """
    doc_num: int
    basis: Literal["description analysis", "invoice cross-reference"]
    finding: str         # suspected_category for reasoning; check_id for document
    message: str         # "Consider reviewing whether…" reviewer prompt
    determinability: str  # "J+" or "D+ (conditional on extraction)"
    validation_status: str = "unvalidated"


@dataclass
class UnifiedCandidatesSection:
    """Unified AI-Surfaced Candidates for Review — Section 5 subsection.

    Merges reasoning (description analysis) and document cross-reference candidates
    into a single table, gated by the show_ai_candidates flag.

    show=False                             → render nothing; rest of report byte-identical.
    show=True, candidates                  → render unified table.
    show=True, no candidates               → render "No candidates surfaced."
    reasoning_status == "not_examined"     → append note for reasoning pass.
    reasoning_status == "errored"          → append note that reasoning did not complete.
    documents_status == "not_examined"     → append note for source documents.
    """
    show: bool
    candidates: list[ReviewCandidateRow]
    reasoning_status: str   # "ok" | "errored" | "not_examined"
    documents_status: str   # "ok" | "not_examined"
    disclaimer: str


@dataclass
class DeclaredF5Section:
    """Data for the optional Declared-vs-Computed F5 section.

    findings is empty when the chain ran without --declared-f5; in that case
    the renderer is a no-op and Section 6 retains its "not examined" placeholder.
    When findings are present the renderer shows the Check A / Check B findings
    and Section 6 suppresses the placeholder line.

    Attributes:
        findings: Raw finding dicts from compile_output["declared_f5_findings"].
                  Each dict carries at minimum "check" ("A" or "B"), "box",
                  "delta", and "finding_type".  Check A dicts also carry "rule"
                  and "description"; Check B primary dicts carry "declared",
                  "computed", "direction", and "hypothesis".
    """
    findings: list[dict]


@dataclass
class ListingFindingsSection:
    """Data for T2.10 listing-level check results (SEQ_GAP + DUP_CLAIM).

    Attributes:
        seq_gap_findings:   SEQ_GAP finding dicts from listing_findings in
                            CompileOutput.  Empty list means no gaps detected
                            (status "examined") or the pass was skipped/failed.
        dup_claim_findings: DUP_CLAIM finding dicts.  Empty list means no
                            duplicates detected or NumAtCard was unpopulated.
        status:             Execution state of the listing pass, kept distinct so the
                            report never reads a thrown pass as a clean one (tfix):
                              "examined"     — the checks RAN (findings may be empty);
                              "unavailable"  — the checks could NOT run (threw);
                              "not_examined" — the pass was never run (legacy
                                               compile_output with no listing_findings key).
        reason:             Execution-fact caveat; non-empty ONLY for "unavailable"
                            (mirrors 2B's non-empty-reason discipline). No IRAS rationale.
    """
    seq_gap_findings: list[dict]
    dup_claim_findings: list[dict]
    status: str = "examined"
    reason: str = ""


@dataclass
class DocumentDupSection:
    """Data for the same-day duplicate-purchase surfacer (DUP_SAME_DAY).

    Distinct from ListingFindingsSection: this surfacer keys on
    (card_name, doc_total, doc_date) over the normalised purchase records, not on
    the vendor reference over the listing surface. Its execution state mirrors the
    listing section's three-state model so a thrown pass never reads as a clean one.

    Attributes:
        findings: DUP_SAME_DAY finding dicts from document_dup_findings in
                  CompileOutput. Empty list means no same-day collisions detected
                  (status "examined") or the pass was skipped/failed.
        status:   Execution state of the surfacer, kept distinct so the report never
                  reads a thrown pass as a clean one:
                    "examined"     — the check RAN (findings may be empty);
                    "unavailable"  — the check could NOT run (threw);
                    "not_examined" — the check was never run (legacy compile_output
                                     with no document_dup_findings key).
        reason:   Execution-fact caveat; non-empty ONLY for "unavailable". No IRAS rationale.
    """
    findings: list[dict]
    status: str = "examined"
    reason: str = ""


@dataclass
class LedgerReconSection:
    """Data for the T2.24 "GST Control-Ledger Reconciliation" section (PR-3 render).

    Two independent sub-signals, each carrying its own three-state execution status
    (mirrors ListingFindingsSection — examined / unavailable / not_examined — NOT the
    simpler declared-F5 present-or-not model):

      * recon (Signal A): ledger-derived GST vs the RETURN's declared boxes — per-side
        divergence dicts.
      * drop (Signal B): GST posted to the 820 control account that dropped from the F5
        report ("Transactions not included") — dropped-posting dicts.

    Each finding dict already carries a candidate-framed ``description`` + ``recommendation``
    (built by orchestrator.check_gst_ledger_recon); this section formats them and asserts
    nothing. ``None`` findings + an ``unavailable`` status means the check could not run.
    """

    recon_findings: list[dict]
    recon_status: str = "not_examined"
    recon_reason: str = ""
    drop_findings: list[dict] = field(default_factory=list)
    drop_status: str = "not_examined"
    drop_reason: str = ""


@dataclass
class CheckCoverageSection:
    """Data for the T2.12-2C dedicated "Deterministic Check Coverage" section.

    Renders 2B's per-check data-coverage status (``compile_output["check_coverage"]``)
    so a reviewer can SEE that a review was silently-partial and never unknowingly
    sign it. This is a DEDICATED sibling surface — NOT the listing-completeness
    section (``check_coverage`` spans NO_GST_REG, which is a GST-registration check,
    not a listing check), NOT the show_ai_candidates-gated probabilistic surface,
    NOT Section 6 (binary suppression). It reuses tfix #63's three-state vocabulary
    (full / degraded / unavailable) + the non-empty-reason-only-for-non-full
    discipline 2B established.

    Attributes:
        rows: One ``{check, level, reason}`` dict per deterministic check, copied
              from ``compile_output["check_coverage"]`` (the projection of
              feeders.CoverageStatus.as_dict()). ``level`` is one of full/degraded/
              unavailable; ``reason`` is the data-coverage FACT only (no IRAS
              rationale) and is non-empty for degraded/unavailable, empty for full.
              Empty list when the chain reader exposed no coverage seam (live SAP /
              frozen replay) — the renderer is then a no-op.
    """
    rows: list[dict]

    @property
    def show(self) -> bool:
        """True when there is at least one per-check coverage row to render."""
        return bool(self.rows)


@dataclass
class AnalyticalReviewSection:
    """Data for the optional Annual Analytical Review section (T2.16).

    show=False or data=None → renderer is a no-op; rest of report byte-identical.
    show=True               → renders FY quarter table, totals, ratio, findings.

    Attributes:
        show:                 True when --analytical-review flag was supplied.
        fy_start:             ISO date string — first day of the financial year.
        fy_end:               ISO date string — last day of the financial year.
        quarter_boxes:        list[QuarterBoxes] (4 entries, chronological).
        fy_box_4:             Financial-year Total Supplies (Box 4), as str(Decimal).
        fy_box_5:             Financial-year Taxable Purchases (Box 5), as str(Decimal).
        ratio:                TP/TS ratio str(Decimal rounded to 4dp), or None when
                              fy_box_4 == 0.
        findings:             list of TP_TS_RATIO finding dicts (empty when ratio ≤ 1.2).
        fluctuation_findings: list[FluctuationFinding] — QoQ movement candidates per
                              ASK §1.3a.  Empty when not run or no findings.
    """
    show: bool
    fy_start: str
    fy_end: str
    quarter_boxes: list
    fy_box_4: str
    fy_box_5: str
    ratio: str | None
    findings: list[dict]
    fluctuation_findings: list


@dataclass
class PartialExemptionSection:
    """Data for the deterministic partial-exemption / De Minimis section (Prompt I).

    show=False (no findings) → renderer is a no-op; rest of report byte-identical.
    show=True                → renders the computed De Minimis position (given the
                               coded figures) + the TX-RE informational note.

    UNGATED like the analytical review: show derives from whether the check fired,
    NEVER from show_ai_candidates — this is a deterministic finding, not an AI
    candidate.

    Attributes:
        show:     True when the check produced a finding.
        findings: list of PARTIAL_EXEMPTION_DE_MINIMIS finding dicts (0 or 1 today).
    """
    show: bool
    findings: list[dict]


@dataclass
class SchemeStatusSection:
    """Data for the deterministic scheme-status contradiction section.

    A CONFIG-vs-DATA surface: the client's declared scheme participation
    (participates_in_mes / participates_in_igds) disagrees with the ME/IGDS
    codes present on their lines. The finding wording carries BOTH hypotheses
    (stale configuration vs lines coded to a scheme not participated in) and
    asserts neither.

    show=False (no findings) → renderer is a no-op; rest of report byte-identical.
    show=True                → renders the contradiction candidate(s).

    UNGATED like the partial-exemption section: show derives from whether the
    check fired, NEVER from show_ai_candidates — this is a deterministic
    finding, not an AI candidate.

    Attributes:
        show:     True when the check produced at least one finding.
        findings: list of SCHEME_STATUS_CONTRADICTION finding dicts (0-2 today).
    """
    show: bool
    findings: list[dict]


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


# ── Not-examined suppression markers (T2.10) ─────────────────────────────────
# Lowercase substrings that uniquely identify the SEQ_GAP and DUP_CLAIM items
# in NOT_EXAMINED_ITEMS.  When the respective findings are present, the matching
# item is removed from the Not-Examined section so the report does not claim a
# check was "not performed" when it was in fact run and produced output.
_SEQ_GAP_NE_MARKER = "sequence gap detection"
_DUP_CLAIM_NE_MARKER = "duplicate input-tax claims"

# tfix: distinct caveat shown when the listing pass THREW (status "unavailable").
# Keeps the could-not-run state separate from both the static "not performed" lines
# (never-run) and a clean run.  States the EXECUTION fact only — no IRAS rationale.
_LISTING_UNAVAILABLE_ITEM = (
    "Invoice listing completeness checks (sequence gap detection and duplicate "
    "input-tax claims) could not run: {reason}"
)

# T2.24 PR-3: prefix uniquely identifying the 820 control-ledger reconciliation line
# in NOT_EXAMINED_ITEMS. Suppressed when the recon was PERFORMED (a gst_ledger was
# supplied → status examined or unavailable); kept when never run (not_examined).
_LEDGER_RECON_NE_PREFIX = "GST control-account ledger reconciliation"


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
    client_config: Any = None,
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
        client_config:  Optional ClientConfig; source_system drives the data-source
                        label in the judgment prose. None (legacy two-arg callers)
                        defaults to the SAP label — pre-existing call shapes render
                        byte-identical text.

    Returns:
        JudgmentSection: Only populated groups (those with at least one doc_num).
    """
    source_label = _source_label(client_config)
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
                "For each FX sales invoice coded as standard-rated (SR/DS): confirm "
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
                f"is correct and that no input tax has been claimed against it in {source_label}."
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
                # The SAP-mechanism nouns (UDF / FederalTaxID) deliberately stay
                # unchanged on ALL sources — open item #44, rule-author ruling M3.
                f"Note: if your {source_label} instance stores GST registration numbers in a "
                "User Defined Field (UDF) rather than the standard FederalTaxID field, "
                "these findings may be false positives requiring UDF-to-FederalTaxID mapping."
            ),
            doc_nums=ngr_docs,
        ))

    return JudgmentSection(groups=groups)


def build_declared_f5_section(compile_output: dict[str, Any]) -> DeclaredF5Section:
    """Build the DeclaredF5Section from chain compile output.

    Reads declared_f5_findings from compile_output, defaulting to an empty list
    when the key is absent (older chain runs or runs without --declared-f5).

    Args:
        compile_output: CompileOutput dict; reads 'declared_f5_findings' if
                        present (absent when --declared-f5 was not supplied).

    Returns:
        DeclaredF5Section: Populated with findings (may be empty).
    """
    findings = list(compile_output.get("declared_f5_findings") or [])
    return DeclaredF5Section(findings=findings)


# Prefix of the NOT_EXAMINED_ITEMS entry that is suppressed when
# declared-vs-computed checks ran.  Matched via startswith() so that
# minor wording edits in constants.py do not silently break suppression.
_DECL_F5_NOT_EXAMINED_PREFIX: str = "Declared-vs-computed F5 comparison"

# Prefix of the NOT_EXAMINED_ITEMS entry that is suppressed when the
# analytical-review pass ran (--analytical-review flag supplied).
_ANALYTICAL_REVIEW_NE_PREFIX: str = "Annual analytical review"

# Prefix of the NOT_EXAMINED_ITEMS entry that is suppressed when the
# partial-exemption De Minimis check ran. Suppression keys on the
# actively_makes_exempt_supplies CONFIG FLAG (did the check RUN), never on
# whether findings exist: flag on + De Minimis passes means the position WAS
# computed, so the "not computed" line must still be suppressed. The permanent
# apportionment item is never suppressed.
_PARTIAL_EXEMPTION_NE_PREFIX: str = "Partial-exemption De Minimis position"


def render_listing_findings_section(
    compile_output: dict[str, Any],
) -> "ListingFindingsSection":
    """Build T2.10 listing findings from chain output (distinct from T2.9 function).

    Reads compile_output["listing_findings"] (SEQ_GAP + DUP_CLAIM dicts produced
    by orchestrator.check_listing after gate_5) and partitions them into two typed
    lists, AND derives the pass execution state (tfix) so the report keeps three
    states distinct — examined / unavailable / not_examined:

      * ``listing_checks_status.level == "unavailable"`` (chain set it because the
        listing checks THREW) → status "unavailable" (could not run);
      * else ``"listing_findings"`` key present (the chain ran the pass; findings may
        be []) → status "examined";
      * else the key is absent (legacy compile_output predating the listing pass)
        → status "not_examined".

    The execution state is DERIVED from existing compile_output keys — it is read,
    never written — so this stays read-only over compile_output and the offline-replay
    oracle (which serialises compile_output) is byte-unaffected.

    Args:
        compile_output: CompileOutput dict; reads 'listing_findings' +
                        'listing_checks_status' (both optional keys).

    Returns:
        ListingFindingsSection: partitioned findings plus the derived status/reason.
            Never None; always safe to read.
    """
    chain_status: dict = compile_output.get("listing_checks_status") or {}
    if chain_status.get("level") == "unavailable":
        status, reason = "unavailable", str(chain_status.get("reason") or "")
    elif "listing_findings" in compile_output:
        status, reason = "examined", ""
    else:
        status, reason = "not_examined", ""

    raw: list[dict] = compile_output.get("listing_findings") or []
    return ListingFindingsSection(
        seq_gap_findings=[f for f in raw if f.get("check") == "SEQ_GAP"],
        dup_claim_findings=[f for f in raw if f.get("check") == "DUP_CLAIM"],
        status=status,
        reason=reason,
    )


def build_document_dup_section(
    compile_output: dict[str, Any],
) -> "DocumentDupSection":
    """Build the same-day duplicate-purchase surfacer section from chain output.

    Reads compile_output["document_dup_findings"] (DUP_SAME_DAY dicts produced by
    orchestrator.check_document_dup after the listing checks) and derives the pass
    execution state, mirroring render_listing_findings_section — examined /
    unavailable / not_examined:

      * ``document_dup_status.level == "unavailable"`` (chain set it because the
        check THREW) → status "unavailable" (could not run);
      * else ``"document_dup_findings"`` key present (the chain ran the check;
        findings may be []) → status "examined";
      * else the key is absent (legacy compile_output) → status "not_examined".

    The execution state is DERIVED from existing compile_output keys — read, never
    written — so this stays read-only over compile_output and the offline-replay
    oracle (which serialises compile_output) is byte-unaffected by this builder.

    Args:
        compile_output: CompileOutput dict; reads 'document_dup_findings' +
                        'document_dup_status' (both optional keys).

    Returns:
        DocumentDupSection: findings plus the derived status/reason. Never None.
    """
    chain_status: dict = compile_output.get("document_dup_status") or {}
    if chain_status.get("level") == "unavailable":
        status, reason = "unavailable", str(chain_status.get("reason") or "")
    elif "document_dup_findings" in compile_output:
        status, reason = "examined", ""
    else:
        status, reason = "not_examined", ""

    raw: list[dict] = compile_output.get("document_dup_findings") or []
    return DocumentDupSection(
        findings=list(raw),
        status=status,
        reason=reason,
    )


def _derive_recon_state(
    compile_output: dict[str, Any], findings_key: str, status_key: str
) -> tuple[str, str, list[dict]]:
    """Derive (status, reason, findings) for one T2.24 sub-signal, read-only.

    Mirrors render_listing_findings_section's three-state derivation and keeps
    ``None`` (could-not-run) / ``[]`` (examined-clean) / absent-key (never-run) distinct:
      * chain status ``level == "unavailable"``      → ("unavailable", reason, [])
      * findings key present and not None (a list)    → ("examined", "", findings)
      * else (key absent, or None with no status)     → ("not_examined", "", [])
    """
    chain_status: dict = compile_output.get(status_key) or {}
    if chain_status.get("level") == "unavailable":
        return "unavailable", str(chain_status.get("reason") or ""), []
    findings = compile_output.get(findings_key)
    if findings is not None:
        return "examined", "", list(findings)
    return "not_examined", "", []


def build_ledger_recon_section(compile_output: dict[str, Any]) -> "LedgerReconSection":
    """Build the T2.24 GST Control-Ledger Reconciliation section from chain output.

    PURE / read-only over ``compile_output`` (reads ``ledger_recon_findings`` /
    ``ledger_recon_status`` for Signal A and ``not_included_findings`` /
    ``not_included_status`` for Signal B). Derives each sub-signal's execution state
    independently — a run can have Signal A examined while Signal B was never supplied.
    Emits nothing itself; the renderer decides what (if anything) to show.
    """
    recon_status, recon_reason, recon_findings = _derive_recon_state(
        compile_output, "ledger_recon_findings", "ledger_recon_status"
    )
    drop_status, drop_reason, drop_findings = _derive_recon_state(
        compile_output, "not_included_findings", "not_included_status"
    )
    return LedgerReconSection(
        recon_findings=recon_findings,
        recon_status=recon_status,
        recon_reason=recon_reason,
        drop_findings=drop_findings,
        drop_status=drop_status,
        drop_reason=drop_reason,
    )


def build_check_coverage_section(
    compile_output: dict[str, Any],
) -> "CheckCoverageSection":
    """Build the dedicated deterministic-check coverage section (T2.12-2C).

    Reads ``compile_output["check_coverage"]`` — the per-check data-coverage status
    list emitted by ``orchestrator.chain._emit_check_coverage`` (2B), shaped
    ``[{"check", "level", "reason"}, ...]``. Each row is COPIED (read-only over
    compile_output, so the offline-replay oracle is byte-unaffected) and normalised
    to the ``{check, level, reason}`` keys the renderer reads. Rows whose source data
    was present AND populated carry ``level == "full"`` and an empty reason; degraded/
    unavailable rows carry the data-coverage fact as a non-empty reason (never silent).

    Readers WITHOUT the coverage seam (live SapChainReader, frozen-replay reader) emit
    no ``check_coverage`` key, so this returns an empty section and the renderer is a
    no-op — the report is byte-identical on those paths.

    Args:
        compile_output: CompileOutput dict; reads the optional 'check_coverage' key.
                        Imports nothing from feeders/ — consumes the plain-dict
                        projection only (the report layer stays feeders-pure).

    Returns:
        CheckCoverageSection: one row per deterministic check; empty (show=False)
            when the key is absent or empty. Never None.
    """
    raw: list[dict] = compile_output.get("check_coverage") or []
    rows = [
        {
            "check": str(r.get("check", "")),
            "level": str(r.get("level", "")),
            "reason": str(r.get("reason", "") or ""),
        }
        for r in raw
    ]
    return CheckCoverageSection(rows=rows)


def build_analytical_review_section(
    analytical_review_data: dict | None,
    *,
    show: bool,
) -> AnalyticalReviewSection:
    """Build the AnalyticalReviewSection from the T2.16 pass output.

    When show=False the section is built with empty/placeholder values so the
    renderer can skip it unconditionally.  When show=True the pass data is
    consumed; a None data dict produces a degenerate section with no content.

    Args:
        analytical_review_data: Dict returned by run_analytical_review_pass(),
                                or None when the pass did not run.
        show:                   True when --analytical-review was supplied.
                                Keyword-only to prevent positional mis-ordering.

    Returns:
        AnalyticalReviewSection: Fully populated; renderer never receives None.
    """
    if not show or analytical_review_data is None:
        return AnalyticalReviewSection(
            show=False,
            fy_start="", fy_end="",
            quarter_boxes=[], fy_box_4="0", fy_box_5="0",
            ratio=None, findings=[], fluctuation_findings=[],
        )
    return AnalyticalReviewSection(
        show=True,
        fy_start=analytical_review_data.get("fy_start", ""),
        fy_end=analytical_review_data.get("fy_end", ""),
        quarter_boxes=list(analytical_review_data.get("quarter_boxes") or []),
        fy_box_4=str(analytical_review_data.get("fy_box_4", "0")),
        fy_box_5=str(analytical_review_data.get("fy_box_5", "0")),
        ratio=analytical_review_data.get("ratio"),
        findings=list(analytical_review_data.get("findings") or []),
        fluctuation_findings=list(analytical_review_data.get("fluctuation_findings") or []),
    )


def build_partial_exemption_section(findings: list[dict] | None) -> PartialExemptionSection:
    """Build the deterministic partial-exemption section (Prompt I).

    show derives ONLY from whether the check fired (findings non-empty) — never
    from show_ai_candidates; this is an UNGATED deterministic surface like the
    analytical review.

    Args:
        findings: run_partial_exemption_check() output (0 or 1 finding), or None
                  for legacy callers.

    Returns:
        PartialExemptionSection: Fully populated; renderer never receives None
            from build_report (a None ReportModel field means a legacy caller).
    """
    findings = list(findings or [])
    return PartialExemptionSection(show=bool(findings), findings=findings)


def build_scheme_status_section(findings: list[dict] | None) -> SchemeStatusSection:
    """Build the deterministic scheme-status contradiction section.

    show derives ONLY from whether the check fired (findings non-empty) — never
    from show_ai_candidates; this is an UNGATED deterministic surface like the
    partial-exemption section.

    Args:
        findings: run_scheme_status_check() output (0-2 findings), or None for
                  legacy callers.

    Returns:
        SchemeStatusSection: Fully populated; renderer never receives None from
            build_report (a None ReportModel field means a legacy caller).
    """
    findings = list(findings or [])
    return SchemeStatusSection(show=bool(findings), findings=findings)


def build_not_examined_section(
    compile_output: dict[str, Any],
    client_config: Any,
    *,
    declared_f5_findings: list[dict] | None = None,
    listing_section: "ListingFindingsSection | None" = None,
    analytical_review_section: "AnalyticalReviewSection | None" = None,
    ledger_recon_section: "LedgerReconSection | None" = None,
) -> NotExaminedSection:
    """Build Section 6 — coverage boundary from constants plus run-specific additions.

    Starts with the standard NOT_EXAMINED_ITEMS list (copied, not mutated),
    then appends two types of run-specific additions:
      * Deduplicated anomalies from the chain run (unknown VatGroup codes).
      * A note about client-specific VatGroup codes if any are configured.

    When declared_f5_findings is non-empty the "Declared-vs-computed F5
    comparison" placeholder is suppressed — the checks ran, so the item is no
    longer out of scope.  The match uses startswith(_DECL_F5_NOT_EXAMINED_PREFIX)
    so minor wording edits in constants.py do not silently reintroduce the item.

    When analytical_review_section.show is True the "Annual analytical review"
    placeholder is suppressed — the pass ran and the section is in the report.

    When client_config.actively_makes_exempt_supplies is True the
    "Partial-exemption De Minimis position" placeholder is suppressed — the
    check RAN (the config flag gates it), whether or not it produced a finding.
    The permanent "Partial-exemption input tax apportionment" item is never
    suppressed.

    Args:
        compile_output:              CompileOutput dict; reads 'deduplicated_anomalies'
                                     if present (absent in older chain runs; defaults []).
        client_config:               ClientConfig; reads 'custom_vat_groups' via getattr.
        declared_f5_findings:        Optional list of findings from run_declared_f5_checks.
                                     Keyword-only to prevent accidental positional errors.
                                     When non-empty the "Declared-vs-computed" item is
                                     removed from Section 6.  Defaults to None (no
                                     suppression — backward-compatible with callers that
                                     do not supply the argument).
        listing_section:             Optional ListingFindingsSection from
                                     render_listing_findings_section.  When seq_gap_findings
                                     is non-empty, the "sequence gap detection" Not-Examined
                                     item is suppressed independently.  When dup_claim_findings
                                     is non-empty, the "duplicate input-tax claims" item is
                                     suppressed independently.  Defaults to None.
        analytical_review_section:   Optional AnalyticalReviewSection from
                                     build_analytical_review_section.  When show=True
                                     the "Annual analytical review" Not-Examined item is
                                     suppressed.  Defaults to None (no suppression).

    Returns:
        NotExaminedSection: Items list in display order (standard items first,
            run-specific additions appended).
    """
    suppress_decl_f5: bool = bool(declared_f5_findings)
    suppress_analytical_review: bool = bool(
        analytical_review_section and analytical_review_section.show
    )
    # Keys on the CONFIG FLAG (the check ran), never on whether findings exist:
    # flag on + De Minimis passes = the position WAS computed → still suppress.
    suppress_partial_exemption: bool = bool(
        getattr(client_config, "actively_makes_exempt_supplies", False)
    )

    # Data-source label substituted into the {source_label}-templated entries
    # (.replace, not .format — brace-safe against literal parens/braces in items).
    source_label = _source_label(client_config)

    items: list[str] = []
    for item in NOT_EXAMINED_ITEMS:
        if suppress_decl_f5 and item.startswith(_DECL_F5_NOT_EXAMINED_PREFIX):
            continue
        if suppress_analytical_review and item.startswith(_ANALYTICAL_REVIEW_NE_PREFIX):
            continue
        if suppress_partial_exemption and item.startswith(_PARTIAL_EXEMPTION_NE_PREFIX):
            continue
        items.append(item.replace("{source_label}", source_label))

    # T2.10 + tfix: the SEQ_GAP/DUP_CLAIM not-examined lines are driven by the listing
    # pass EXECUTION STATE, so the report keeps three states distinct and never claims a
    # check was "not performed" when it was in fact run (the clean-run mislabel, BUG 2):
    #   * "examined"     — BOTH checks ran (they share one try; findings may be empty),
    #                      so neither "not performed" line applies → suppress both. The
    #                      findings (or the "no findings" note) are shown by the listing
    #                      section renderer.
    #   * "unavailable"  — the checks THREW (could not run). Drop the static "not
    #                      performed" lines and surface a DISTINCT "could not run" caveat
    #                      so a reviewer never reads a thrown pass as a never-run one.
    #   * "not_examined" — legacy compile_output with no listing pass → keep the static
    #                      lines (the historical behaviour).
    # listing_section is None (legacy direct callers) keeps the static lines unchanged.
    if listing_section is not None and listing_section.status in ("examined", "unavailable"):
        # The pass ran (examined) or threw (unavailable) — either way the static "not
        # performed" lines no longer hold, so drop both.
        items = [
            i for i in items
            if _SEQ_GAP_NE_MARKER not in i.lower()
            and _DUP_CLAIM_NE_MARKER not in i.lower()
        ]
        if listing_section.status == "unavailable":
            # Replace them with a DISTINCT could-not-run caveat (not the static never-run
            # line), so a reviewer never reads a thrown pass as a never-run one.
            items.append(_LISTING_UNAVAILABLE_ITEM.format(reason=listing_section.reason))

    # T2.24 PR-3: the 820 control-ledger reconciliation not-examined line is driven by
    # whether the recon was PERFORMED (a gst_ledger was supplied). recon_status
    # "examined"/"unavailable" → it ran (findings shown in the ledger-recon section, or an
    # honest caveat there), so drop the static "not reconciled" line. "not_examined" (no
    # gst_ledger supplied) → keep the static line (the historical, honest default).
    if ledger_recon_section is not None and ledger_recon_section.recon_status in (
        "examined", "unavailable"
    ):
        items = [i for i in items if not i.startswith(_LEDGER_RECON_NE_PREFIX)]

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
        SignatureSection: Reviewer metadata plus the approved legal disclaimer —
            DISCLAIMER_TEXT byte-identical for SAP sources (and legacy configs
            without source_system); name-swapped only, never paraphrased, for
            non-SAP sources (disclaimer_text_for).
    """
    return SignatureSection(
        reviewer_name=getattr(client_config, "reviewer_name", ""),
        firm_name=getattr(client_config, "firm_name", ""),
        gst_registration_number=getattr(client_config, "gst_registration_number", ""),
        # Name-swap only — the approved legal language is never reformatted here.
        disclaimer=disclaimer_text_for(_source_label(client_config, long=True)),
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


def build_unified_candidates_section(
    judgment_artefact: dict | None,
    document_candidates: list | None,
    *,
    show: bool,
) -> UnifiedCandidatesSection:
    """Build the unified AI-Surfaced Candidates subsection for Section 5.

    Adapts reasoning candidates (from judgment_artefact) and document candidates
    (from run_documents_pass()) into ReviewCandidateRow items in one list.  The
    per-row basis tag is mandatory — it distinguishes Reg 26/27 description
    analysis from invoice cross-reference, keeping the unified section honest
    when the two mechanisms have different validation states.

    Args:
        judgment_artefact:   Reasoning artefact dict, or None if not run.
        document_candidates: List of DocumentCandidate from run_documents_pass(),
                             or None if the documents pass did not run.
                             (Typed as list to avoid importing documents/ here.)
        show:                Feature flag; keyword-only.

    Returns:
        UnifiedCandidatesSection: show=False short-circuits with no candidates.
    """
    if not show:
        return UnifiedCandidatesSection(
            show=False, candidates=[],
            reasoning_status="not_examined", documents_status="not_examined",
            disclaimer="",
        )

    rows: list[ReviewCandidateRow] = []

    # ── Reasoning candidates ──────────────────────────────────────────────────
    if judgment_artefact is None:
        reasoning_status = "not_examined"
    else:
        status: str = str(judgment_artefact.get("status") or "errored")
        reasoning_status = status
        if status == "ok":
            for c in (judgment_artefact.get("candidates") or []):
                rows.append(ReviewCandidateRow(
                    doc_num=int(c.get("doc_num") or 0),
                    basis="description analysis",
                    finding=str(c.get("suspected_category") or ""),
                    message=str(c.get("phrasing") or ""),
                    determinability="J+",
                    validation_status="unvalidated",
                ))

    # ── Document cross-reference candidates ──────────────────────────────────
    if document_candidates is None:
        documents_status = "not_examined"
    else:
        documents_status = "ok"
        for cand in document_candidates:
            rows.append(ReviewCandidateRow(
                doc_num=cand.doc_num,
                basis="invoice cross-reference",
                finding=cand.check_id,
                message=cand.message,
                determinability=cand.determinability,
                validation_status="unvalidated",
            ))

    disclaimer = str((judgment_artefact or {}).get("disclaimer") or "")

    return UnifiedCandidatesSection(
        show=True,
        candidates=rows,
        reasoning_status=reasoning_status,
        documents_status=documents_status,
        disclaimer=disclaimer,
    )
