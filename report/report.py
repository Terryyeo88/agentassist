"""
report/report.py — top-level ReportModel builder.

Defines the ReportModel dataclass (the single object consumed by render_pdf)
and the build_report() factory that assembles it from a CompileOutput dict and
a ClientConfig.  No SAP calls, no file I/O, no datetime.now() — all inputs
come from the caller.

The module is the integration layer between enriched chain output and the
renderer: it delegates each section to the appropriate builder in report.sections,
then packages the results into a single typed container.

To route a specific client's exempt findings to Template 4 (financial-services /
property businesses that actively make exempt supplies), add

    actively_makes_exempt_supplies: true

to that client's YAML config and add the corresponding boolean field to ClientConfig
in config/loader.py (one-line addition to the dataclass). Until then, the getattr
default (False) keeps all clients on Template 5 — the correct default for general
businesses with at most incidental exempt supplies. No T1.3 schema change required
to ship T1.4.

Dependencies:
    config.loader   — ClientConfig for per-client flags and reviewer metadata
    report.enrich   — enrich() and EnrichedFinding
    report.sections — one builder function per report section

Exports:
    ReportModel  — dataclass; the only input accepted by render_pdf
    build_report — factory that assembles a ReportModel from chain output
"""
from __future__ import annotations

# from __future__ import annotations makes all annotations strings at parse time,
# enabling lowercase union syntax (dict | None) and forward references on Python < 3.10.

from dataclasses import dataclass
from typing import Any

from config.loader import ClientConfig
from config.source_labels import source_display_name
from report.enrich import EnrichedFinding, enrich
from report.sections import (
    AdjudicationSection,
    AICandidatesSection,
    AnalyticalReviewSection,
    CheckCoverageSection,
    CoverSection,
    CrossFindingSection,
    DeclaredF5Section,
    DocumentDupSection,
    F5BoxSection,
    FindingsSection,
    JudgmentSection,
    LedgerReconSection,
    ListingFindingsSection,
    PartialExemptionSection,
    SchemeStatusSection,
    NotExaminedSection,
    ScopeSection,
    SignatureSection,
    UnifiedCandidatesSection,
    build_ai_candidates_section,
    build_analytical_review_section,
    build_check_coverage_section,
    build_cover_section,
    build_cross_finding_section,
    build_declared_f5_section,
    build_document_dup_section,
    build_f5_box_section,
    build_findings_section,
    build_judgment_section,
    build_adjudication_section,
    build_ledger_recon_section,
    build_not_examined_section,
    build_partial_exemption_section,
    build_scheme_status_section,
    build_scope_section,
    build_signature_section,
    build_unified_candidates_section,
    render_listing_findings_section,
)


@dataclass
class ReportModel:
    """Container for all report sections; the sole input to render_pdf().

    Each field corresponds to one rendered section of the PDF.  The model is
    intentionally flat — the renderer should never reach into CompileOutput or
    ClientConfig directly, so all data transformations happen before this object
    is constructed.

    generated_at, period_start, and period_end are stored as top-level fields
    in addition to their presence inside cover so callers can read report
    metadata without traversing model.cover.*.

    Attributes:
        cover:          Cover page metadata (client name, reviewer, period, timestamp).
        scope:          Section 1 — items examined, FX exclusions, credit notes.
        f5_boxes:       Section 2 — F5 box figures with VatGroup attribution.
        findings:       Section 3 — EnrichedFindings grouped by ASK template.
        cross_findings: Section 4 — documents carrying more than one error code.
        judgment:       Section 5 — reviewer judgment items and AI candidates.
        not_examined:   Section 6 — coverage boundary (out-of-scope items).
        signature:      Declaration and sign-off page content.
        generated_at:   ISO 8601 timestamp string from the chain run's fetched_at.
        period_start:   ISO date string 'YYYY-MM-DD' for the review period start.
        period_end:     ISO date string 'YYYY-MM-DD' for the review period end.
        ai_candidates:  Optional AI-surfaced candidates subsection rendered inside
                        Section 5.  None in legacy callers that predate the AI pass;
                        the renderer treats None as show=False.
    """
    cover: CoverSection
    scope: ScopeSection
    f5_boxes: F5BoxSection
    findings: FindingsSection
    cross_findings: CrossFindingSection
    judgment: JudgmentSection
    not_examined: NotExaminedSection
    signature: SignatureSection
    generated_at: str
    period_start: str
    period_end: str
    # Optional AI-candidates subsection; kept for backward compat — existing tests
    # access model.ai_candidates directly and must continue to pass.
    ai_candidates: AICandidatesSection | None = None
    # Unified candidates subsection merging reasoning + document candidates.
    # None only in legacy callers that predate Prompt 4 — renderer falls back to
    # _ai_candidates_subsection when this is None.
    unified_candidates: UnifiedCandidatesSection | None = None
    # T2.9: declared-vs-computed F5 section.  None when --declared-f5 was not
    # supplied; renderer is a no-op in that case.  Kept as an optional field so
    # existing callers (tests, seal round-trips) remain unaffected.
    declared_f5: DeclaredF5Section | None = None
    # T2.10: listing-level findings (SEQ_GAP + DUP_CLAIM).  None only in legacy
    # callers that predate T2.10 — renderer skips the section when None.
    listing_findings: ListingFindingsSection | None = None
    # T2.16: annual analytical review (TP/TS ratio + quarter boxes for T2.17).
    # None only in legacy callers; renderer skips section when None or show=False.
    analytical_review: AnalyticalReviewSection | None = None
    # T2.12-2C: dedicated deterministic-check data-coverage section (renders 2B's
    # check_coverage). None in legacy callers; empty (show=False) when the chain
    # reader exposed no coverage seam — renderer is a no-op in both cases.
    check_coverage: CheckCoverageSection | None = None
    # T2.24 PR-3: GST control-ledger reconciliation (Signal A + B). None in legacy
    # callers / runs with no gst_ledger; renderer is empty-when-empty in both cases.
    ledger_recon: LedgerReconSection | None = None
    # T2.27: second/Nth reasoning stream(s), keyed by skill_id, each built through
    # the SAME gated AI-candidates builder (show=show_ai_candidates). None when no
    # extra reasoning artefacts were supplied — keeps reg2627-only runs (and their
    # rendered PDFs) byte-identical. The renderer draws each only when its .show is True.
    extra_candidates: "dict[str, AICandidatesSection] | None" = None
    # Prompt I: deterministic partial-exemption / De Minimis section. None in legacy
    # callers; UNGATED (show derives from the check firing, never show_ai_candidates).
    partial_exemption: PartialExemptionSection | None = None
    # Scheme-status contradiction (config-vs-data): declared MES/IGDS participation
    # vs ME/IGDS-coded lines. None in legacy callers; UNGATED like partial_exemption.
    scheme_status: SchemeStatusSection | None = None
    # Same-day duplicate-purchase surfacer (DUP_SAME_DAY). None in legacy callers that
    # predate the check; renderer skips the section when None or status "not_examined".
    document_dup: DocumentDupSection | None = None
    # D-2026-07-20-source-provenance: display label of the data source (from
    # ClientConfig.source_system via config.source_labels). Defaulted so legacy
    # callers that construct ReportModel directly keep the pre-existing SAP wording.
    source_label: str = "SAP B1"
    # #43 signable-render guard (t-xero-signoff): True IFF the source config had
    # show_ai_candidates=True. Gates the report-level UNVALIDATED banner and the
    # SUPPRESSED signature block in render.py. Keys on show_ai_candidates ONLY —
    # never on validation_status: the deterministic working paper is human-signed
    # regardless of T2.11; it is the AI-candidate PREVIEW render that is not
    # signable. Default False → every legacy/committed-config render byte-identical.
    show_ai_candidates: bool = False
    # t-accumulated-sign: the accumulated-review evidence section (non-primary slices'
    # STORED findings + per-source coverage matrix + visible supersession/vintage).
    # None for every per-slice/legacy render → byte-identical output.
    accumulated: "object | None" = None
    # t-decision-render: reviewer adjudications rendered from the decision view passed
    # AS DATA (api builds it; report/ imports nothing from agent/). None for every
    # decision-free/legacy render → byte-identical output. UNGATED (section.show only —
    # human decisions, not reasoning-layer output; never keyed on show_ai_candidates).
    adjudications: AdjudicationSection | None = None


def build_report(
    compile_output: dict[str, Any],
    client_config: ClientConfig,
    *,
    generated_at: str,
    judgment_artefact: dict | None = None,
    document_candidates: list | None = None,
    analytical_review_data: dict | None = None,
    document_legibility_rows: list | None = None,
    extra_judgment_artefacts: dict[str, dict] | None = None,
    partial_exemption_findings: list | None = None,
    scheme_status_findings: list | None = None,
    accumulated=None,
    adjudications: dict | None = None,
) -> ReportModel:
    """Build the full ReportModel from a chain-run CompileOutput dict and a ClientConfig.

    Delegates each report section to its builder in report.sections, stitching
    the results into a ReportModel.  No datetime.now() is called — generated_at
    is provided by the caller (typically the chain's fetched_at timestamp) so
    the rendered timestamp matches when the chain ran, not when the PDF was built.

    Args:
        compile_output:    A CompileOutput dict as returned by
                           report.contract.load_compile_output.  Must contain
                           'period', 'fetch_manifest', 'calculate', 'classify',
                           and 'detect' keys.
        client_config:     ClientConfig for the target client.  Used for reviewer
                           metadata, disclaimer text, and optional feature flags
                           (actively_makes_exempt_supplies, show_ai_candidates).
        generated_at:      ISO 8601 timestamp string to embed in the report cover
                           and model metadata.  Keyword-only to prevent accidental
                           positional mis-ordering.
        judgment_artefact: Optional dict loaded from the AI judgment-candidates
                           artefact (steps/judgment-candidates.json).  When provided
                           and client_config.show_ai_candidates is True, an
                           AI-candidates subsection is appended to Section 5.
                           Defaults to None so all existing callers continue to work.
        document_candidates: Optional list of DocumentCandidate from
                           run_documents_pass().  None means the documents pass did
                           not run and the unified section notes "not examined".
                           Defaults to None so existing callers are unaffected.
        document_legibility_rows: Optional list of coverage-style rows (T2.14) for
                           documents routed to "manual review required" by the
                           legibility gate. Appended to the ungated Deterministic
                           Check Coverage section so a reviewer sees them even when
                           show_ai_candidates is False. Defaults to None (no rows).
        extra_judgment_artefacts: Optional {skill_id: artefact} mapping for a
                           second/Nth reasoning stream (T2.27).  Each artefact is
                           routed through the SAME gated builder
                           (build_ai_candidates_section, show=show_ai_candidates)
                           and exposed on ReportModel.extra_candidates.  Defaults
                           to None so reg2627-only runs are byte-identical.

    Returns:
        ReportModel: A fully populated model ready to be passed to render_pdf().
    """
    # getattr with a default is a forward-compat pattern: allows the flag to be
    # absent from ClientConfig without a breaking schema change.  See module
    # docstring for how to enable Template 4 routing per client.
    actively: bool = getattr(client_config, "actively_makes_exempt_supplies", False)

    enriched: list[EnrichedFinding] = enrich(
        compile_output, actively_makes_exempt=actively
    )

    # Extract period once to avoid repeated dict lookups across field assignments below
    period = compile_output["period"]
    # Same getattr forward-compat pattern as actively_makes_exempt_supplies above
    show_ai: bool = getattr(client_config, "show_ai_candidates", False)

    # T2.9: extract declared_f5_findings so both build_not_examined_section
    # (suppression) and build_declared_f5_section (section data) see the same list.
    df5_findings: list[dict] = list(compile_output.get("declared_f5_findings") or [])
    # T2.10: build listing findings section once so the same object can be
    # passed to both ReportModel and build_not_examined_section for suppression.
    listing_sec = render_listing_findings_section(compile_output)
    # T2.16: build analytical review section once for both ReportModel and
    # build_not_examined_section (suppression when the pass ran).
    analytical_sec = build_analytical_review_section(
        analytical_review_data,
        show=(analytical_review_data is not None),
    )

    # T2.14: the deterministic-check coverage section (2B/2C) is the ungated
    # surface. Append any document-legibility "manual review required" rows here
    # so they render even when show_ai_candidates is False. Reads a COPY of
    # compile_output's rows (build_check_coverage_section) and adds engine-level
    # legibility rows — compile_output / the offline-replay oracle is untouched.
    coverage_sec = build_check_coverage_section(compile_output)
    if document_legibility_rows:
        coverage_sec = CheckCoverageSection(
            rows=[*coverage_sec.rows, *document_legibility_rows]
        )

    # T2.24 PR-3: build the GST control-ledger reconciliation section once so the same
    # object drives both the rendered section AND build_not_examined_section suppression
    # (present the "not reconciled" line only when no gst_ledger was supplied).
    ledger_recon_sec = build_ledger_recon_section(compile_output)

    # T2.27: build each extra reasoning stream through the SAME gated builder, so
    # the show_ai_candidates freeze gate covers every stream identically. None
    # (not an empty dict) when no extra artefacts were supplied — keeps
    # reg2627-only ReportModels byte-identical for existing callers/tests.
    extra_candidates_map: dict | None = None
    if extra_judgment_artefacts:
        extra_candidates_map = {
            skill_id: build_ai_candidates_section(artefact, show=show_ai)
            for skill_id, artefact in extra_judgment_artefacts.items()
        }

    return ReportModel(
        # t-accumulated-sign: pass-through of the accumulated evidence section (None
        # for every per-slice/legacy caller — render byte-identical).
        accumulated=accumulated,
        # t-decision-render: the decision view arrives AS DATA (built in api/ — the
        # accumulated= precedent); the section is built HERE, once, path-agnostically.
        # None for every decision-free/legacy caller — render byte-identical.
        adjudications=(
            build_adjudication_section(adjudications)
            if adjudications is not None else None
        ),
        cover=build_cover_section(
            compile_output, client_config, generated_at=generated_at
        ),
        scope=build_scope_section(compile_output),
        f5_boxes=build_f5_box_section(compile_output),
        findings=build_findings_section(enriched),
        cross_findings=build_cross_finding_section(enriched),
        judgment=build_judgment_section(compile_output, enriched, client_config=client_config),
        not_examined=build_not_examined_section(
            compile_output, client_config,
            declared_f5_findings=df5_findings,
            listing_section=listing_sec,
            analytical_review_section=analytical_sec,
            ledger_recon_section=ledger_recon_sec,
        ),
        signature=build_signature_section(client_config),
        generated_at=generated_at,
        period_start=period["start"],
        period_end=period["end"],
        # Kept for backward compat — existing tests read model.ai_candidates directly.
        ai_candidates=build_ai_candidates_section(
            judgment_artefact, show=show_ai
        ),
        # Unified section merges reasoning + document candidates; renderer uses this
        # when present, falls back to ai_candidates for legacy callers.
        unified_candidates=build_unified_candidates_section(
            judgment_artefact, document_candidates, show=show_ai
        ),
        # T2.9: declared-vs-computed section; no-op when df5_findings is empty.
        declared_f5=build_declared_f5_section(compile_output),
        # T2.10: listing findings section (SEQ_GAP + DUP_CLAIM).
        listing_findings=listing_sec,
        # T2.16: analytical review section; show=False when pass did not run.
        analytical_review=analytical_sec,
        # T2.12-2C: dedicated deterministic-check data-coverage section (2B's
        # check_coverage), plus any T2.14 document-legibility manual-review rows.
        check_coverage=coverage_sec,
        # T2.24 PR-3: GST control-ledger reconciliation (Signal A + B); empty-when-empty.
        ledger_recon=ledger_recon_sec,
        # T2.27: second/Nth reasoning stream(s), gated identically to reg2627.
        extra_candidates=extra_candidates_map,
        # Prompt I: deterministic partial-exemption section; None for legacy callers,
        # show=False when the check produced no finding (renderer no-op either way).
        partial_exemption=(
            build_partial_exemption_section(partial_exemption_findings)
            if partial_exemption_findings is not None else None
        ),
        # Scheme-status contradiction section; None for legacy callers,
        # show=False when the check produced no finding (renderer no-op either way).
        scheme_status=(
            build_scheme_status_section(scheme_status_findings)
            if scheme_status_findings is not None else None
        ),
        # Same-day duplicate-purchase surfacer section; three-state (examined /
        # unavailable / not_examined) derived from compile_output keys. Renderer is a
        # no-op when not_examined with no findings (legacy compile_output).
        document_dup=build_document_dup_section(compile_output),
        # D-2026-07-20-source-provenance: the renderer never reaches into
        # ClientConfig, so the data-source display label rides on the model.
        source_label=source_display_name(
            getattr(client_config, "source_system", None)
        ),
        # #43 guard: carried onto the model so the renderer never reaches into
        # ClientConfig. show_ai was computed above from client_config.show_ai_candidates.
        show_ai_candidates=show_ai,
    )
