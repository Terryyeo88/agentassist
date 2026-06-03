"""
report/report.py — top-level ReportModel builder.

To route a specific client's exempt findings to Template 4 (financial-services /
property businesses that actively make exempt supplies), add

    actively_makes_exempt_supplies: true

to that client's YAML config and add the corresponding boolean field to ClientConfig
in config/loader.py (one-line addition to the dataclass). Until then, the getattr
default (False) keeps all clients on Template 5 — the correct default for general
businesses with at most incidental exempt supplies. No T1.3 schema change required
to ship T1.4.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.loader import ClientConfig
from report.enrich import EnrichedFinding, enrich
from report.sections import (
    AICandidatesSection,
    CoverSection,
    CrossFindingSection,
    F5BoxSection,
    FindingsSection,
    JudgmentSection,
    NotExaminedSection,
    ScopeSection,
    SignatureSection,
    build_ai_candidates_section,
    build_cover_section,
    build_cross_finding_section,
    build_f5_box_section,
    build_findings_section,
    build_judgment_section,
    build_not_examined_section,
    build_scope_section,
    build_signature_section,
)


@dataclass
class ReportModel:
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
    # Optional AI-candidates subsection; None only in legacy callers that have
    # not been updated — the renderer treats None as show=False.
    ai_candidates: AICandidatesSection | None = None


def build_report(
    compile_output: dict[str, Any],
    client_config: ClientConfig,
    *,
    generated_at: str,
    judgment_artefact: dict | None = None,
) -> ReportModel:
    """
    Build the full ReportModel from a chain-run CompileOutput dict and a ClientConfig.

    generated_at is provided by the caller (typically the chain's fetched_at
    timestamp) — this function never calls datetime.now().

    judgment_artefact: the judgment-candidates artefact dict from the reasoning
    pass (steps/judgment-candidates.json).  Optional; defaults to None so all
    existing callers continue to work.  When provided and cfg.show_ai_candidates
    is True, an AI-candidates subsection is appended to Section 5.
    """
    # Source the exempt routing flag without requiring a T1.3 schema change.
    # See module docstring for how to enable Template 4 routing per client.
    actively: bool = getattr(client_config, "actively_makes_exempt_supplies", False)

    enriched: list[EnrichedFinding] = enrich(
        compile_output, actively_makes_exempt=actively
    )

    period = compile_output["period"]
    show_ai: bool = getattr(client_config, "show_ai_candidates", False)

    return ReportModel(
        cover=build_cover_section(
            compile_output, client_config, generated_at=generated_at
        ),
        scope=build_scope_section(compile_output),
        f5_boxes=build_f5_box_section(compile_output),
        findings=build_findings_section(enriched),
        cross_findings=build_cross_finding_section(enriched),
        judgment=build_judgment_section(compile_output, enriched),
        not_examined=build_not_examined_section(compile_output, client_config),
        signature=build_signature_section(client_config),
        generated_at=generated_at,
        period_start=period["start"],
        period_end=period["end"],
        ai_candidates=build_ai_candidates_section(
            judgment_artefact, show=show_ai
        ),
    )
