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
from report.enrich import EnrichedFinding, enrich
from report.sections import (
    AICandidatesSection,
    CoverSection,
    CrossFindingSection,
    DeclaredF5Section,
    F5BoxSection,
    FindingsSection,
    JudgmentSection,
    NotExaminedSection,
    ScopeSection,
    SignatureSection,
    UnifiedCandidatesSection,
    build_ai_candidates_section,
    build_cover_section,
    build_cross_finding_section,
    build_declared_f5_section,
    build_f5_box_section,
    build_findings_section,
    build_judgment_section,
    build_not_examined_section,
    build_scope_section,
    build_signature_section,
    build_unified_candidates_section,
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


def build_report(
    compile_output: dict[str, Any],
    client_config: ClientConfig,
    *,
    generated_at: str,
    judgment_artefact: dict | None = None,
    document_candidates: list | None = None,
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

    return ReportModel(
        cover=build_cover_section(
            compile_output, client_config, generated_at=generated_at
        ),
        scope=build_scope_section(compile_output),
        f5_boxes=build_f5_box_section(compile_output),
        findings=build_findings_section(enriched),
        cross_findings=build_cross_finding_section(enriched),
        judgment=build_judgment_section(compile_output, enriched),
        not_examined=build_not_examined_section(
            compile_output, client_config, declared_f5_findings=df5_findings
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
    )
