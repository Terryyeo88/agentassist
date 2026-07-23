"""
agent/upload_dossiers.py — hermetic case-file dossiers for the UPLOAD review paths
(t-dossier-xero, D-2026-07-23-dossier-xero).

Generates per-finding DossierArtifacts from an upload's ReviewResult by running the
REAL ``run_casefile_loop`` with a deterministic template transport — NO model call,
NO network, NO tokens, ever, on this path. The candidate framing is an AUTHORED
template derived from the check's CHECK_REGISTRY ``display_name`` (Terry R6:
authored-not-model is CORRECT for the default path, not a compromise — consistent
with no-tax-semantics-on-model-inference). It is candidate-shaped, asserts no
verdict, and must pass ``agent.lint.lint_framing`` (pinned in tests).

CAGE: the loop stages PENDING proposals only — nothing here approves, seals, or
emits, and nothing writes outside the in-memory StagingStore/Ledger. Read-never-
write-on-source holds trivially (pure function over the ReviewResult).

BOUNDED WORK (Terry R2): ``_MAX_DOSSIER_FINDINGS`` caps the per-request loop. A
pathological finding count skips generation entirely (``capped=True``) — the caller
surfaces an honest degraded ``coverage_status`` row; queue rows keep their defaults.
Never a hang, never a silent truncation.

R5 (Option 1, value-only): ``dossier_queue_fields`` renders completeness ``missing``
entries as REASON-SUFFIXED PLAIN STRINGS so a reviewer can tell a source limitation
("not gatherable on this source") from a malfunction ("gathering failed"). The
qualifier currently fires for ZERO finding types on the wired upload paths (E2/E3/E4
have no agent-gathered slots) — pinned before it is needed, per Terry's condition.

Zero anthropic import. Zero SDK import. Stdlib + agent/ only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from agent.budget import RunBudget
from agent.dossier import DossierArtifact, extract_findings
from agent.ledger import Ledger
from agent.lint import lint_framing
from agent.loop import (
    FramingEvent,
    LoopContext,
    ResultEvent,
    run_casefile_loop,
)
from agent.loop_context import AbsentDocumentProvider
from agent.proposals import ProposalArtifact, StagingStore
from agent.registry import CHECK_REGISTRY

# Bounded-work cap (Terry R2). At the measured ~0.2 ms/finding a full cap costs
# ~0.2 s on the upload request; anything above it is a pathological export and the
# caller degrades honestly instead. Module-level so tests can shrink it.
_MAX_DOSSIER_FINDINGS = 1000

# The agent-gathered slots (agent/completeness.py AGENT_GATHERED_INPUTS) that no
# UPLOADED export can supply today: uploads carry no supplier master and no source
# PDFs. A missing slot in this set is a SOURCE LIMITATION, not a malfunction.
UNGATHERABLE_ON_UPLOAD = frozenset({"supplier_catalog", "document_pdfs"})

_NOT_GATHERABLE_REASON = (
    "not gatherable on this source (an uploaded export carries no surface for it)"
)
_GATHERING_FAILED_REASON = "gathering failed"


def _framing_text(finding: Any) -> str:
    """Deterministic candidate framing from the check's registry display_name (R6).

    AUTHORED, not model-generated: the only tax language is the registry's own
    display_name — nothing is inferred. Candidate-shaped by construction ("appears",
    "candidate", "consider reviewing") and lint-pinned in tests; if a future
    display_name ever tripped ``lint_framing``, the loop would hold that dossier
    back from staging rather than voice it (the lint is the backstop).
    """
    payload = getattr(finding, "payload", None) or {}
    doc_num = payload.get("doc_num", "?")
    check_id = getattr(finding, "check_id", "?")
    spec = CHECK_REGISTRY.get(check_id)
    display = spec.display_name if spec is not None else check_id
    return (
        f"Document {doc_num} ({check_id} - {display}) appears to be a candidate "
        "for reviewer attention; consider reviewing the GST treatment for this "
        "item. This is a candidate, not a verdict."
    )


class _TemplateTransport:
    """AgentTransport that yields ONLY the authored framing + a zero-cost result.

    No reads are scripted: the wired upload paths (Xero F5 / Xero sales) produce
    only findings whose required slots are engine-seeded, so there is nothing to
    gather. A finding that DOES need an agent-gathered slot (none on these paths
    today) honestly comes out incomplete — never fabricated.
    """

    def gather(self, prompt: str, finding: Any, evidence_sink: dict) -> Iterable:
        yield FramingEvent(text=_framing_text(finding))
        yield ResultEvent(cost_usd=0.0)


@dataclass(frozen=True)
class UploadDossiers:
    """Outcome of generate_upload_dossiers: dossiers keyed by finding_id, the
    PENDING-only proposals, and whether the bounded-work cap fired."""
    dossiers: dict[str, DossierArtifact]
    proposals: list[ProposalArtifact]
    capped: bool


def generate_upload_dossiers(review_result: Any) -> UploadDossiers:
    """Run the hermetic case-file loop over an upload's ReviewResult.

    Pure function over the ReviewResult: builds an upload-shaped LoopContext
    (AbsentDocumentProvider, empty vendor catalog, empty prior-period store — the
    honest surfaces an uploaded export has), runs the REAL ``run_casefile_loop``
    with the template transport, and returns the dossiers + PENDING proposals.
    Over the cap → ``capped=True`` with nothing generated (caller degrades
    honestly).
    """
    findings = extract_findings(review_result)
    if len(findings) > _MAX_DOSSIER_FINDINGS:
        return UploadDossiers(dossiers={}, proposals=[], capped=True)

    ctx = LoopContext(
        provider=AbsentDocumentProvider(),
        vendor_catalog={},
        prior_period_store={},
    )
    ledger = Ledger()
    result = run_casefile_loop(
        invoke_review=lambda: review_result,
        transport=_TemplateTransport(),
        ctx=ctx,
        ledger=ledger,
        budget=RunBudget(max_turns=10_000, max_cost_usd=1_000.0),
        store=StagingStore(),
        max_attempts_per_finding=1,
    )
    dossiers = {d.finding_id: d for d in result.dossiers}
    return UploadDossiers(
        dossiers=dossiers, proposals=list(result.proposals), capped=False
    )


def dossier_queue_fields(dossier: DossierArtifact) -> dict:
    """Project a DossierArtifact onto the three EXISTING QueueItem fields.

    Value-only: candidate_framing_text / completeness / inputs_hash are already in
    QUEUE_ITEM_KEYS (the Xero rows previously carried ""/empty/"-" defaults).
    Completeness ``missing`` entries become reason-suffixed PLAIN STRINGS (R5
    Option 1) distinguishing a source limitation from a malfunction; ``required``/
    ``present`` stay bare slot names and the frontend Completeness type
    (missing: string[]) is untouched.
    """
    completeness = dict(dossier.completeness or {})
    missing = []
    for slot in completeness.get("missing") or []:
        reason = (
            _NOT_GATHERABLE_REASON
            if slot in UNGATHERABLE_ON_UPLOAD
            else _GATHERING_FAILED_REASON
        )
        missing.append(f"{slot} - {reason}")
    completeness["missing"] = missing
    return {
        "candidate_framing_text": dossier.candidate_framing_text,
        "completeness": completeness,
        "inputs_hash": dossier.inputs_hash,
    }
