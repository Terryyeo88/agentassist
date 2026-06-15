"""
agent/loop.py — the case-file loop DRIVER (plain Python: gather -> act -> verify).

T5.3 Slice 2 (behavior). This is the live loop the cage was built to hold.

NON-NEGOTIABLE INVARIANT: the loop DRIVER is plain Python — the model is invoked
WITHIN it, never drives it. ``run_casefile_loop`` is a deterministic Python function.
For each finding it invokes the model once per attempt (via an injected
``AgentTransport``); the model proposes evidence reads and a candidate framing, and
the DRIVER disposes — it executes the gated tools, runs the CODE-DEFINED completeness
checklist, lints the framing, increments the budget, and decides loop termination.
The model never decides when the loop ends; the deterministic checklist and the
RunBudget do.

Phases (per finding) — ARCHITECTURE A (T5.3f), in-turn evidence:
  * gather (Tier 0): call review() via the bound engine invoker (Tier-1, gated) ONCE
    up front so the deterministic deliverable is in hand regardless of what the agent
    layer does (Invariant 7). Per finding the driver seeds the engine-provided slots
    from the finding payload into a per-finding ``evidence_sink``, then hands the sink
    to ``transport.gather`` — the model calls the T5.3e MCP read tools IN-TURN (source
    PDF, vendor GST status, prior-period treatment) and the SDK handlers write the
    agent-gathered slots into the sink. Reads are gated Tier-0 by the hooks (live) /
    ledgered by the fake (hermetic); the DRIVER does not execute reads.
  * verify (CODE-DEFINED): the driver runs the completeness checklist keyed to
    CheckSpec.inputs_needed against the sink, and lints the framing. Complete +
    lint-clean -> the DRIVER stages (act, below); incomplete -> re-enter gather,
    bounded by RunBudget / max_attempts_per_finding.
  * act (Tier 1) — DRIVER-DECIDED: when (and only when) the code-defined completeness
    and the lint pass, the DRIVER stages the dossier. It writes the Tier-1
    ``propose_action`` justification to the ledger BEFORE staging, then stages a PENDING
    ProposalArtifact. The model cannot call ``propose_action`` (an unbacked tool — see
    the T5.3-probe), so the deterministic driver, not the model, decides staging.

Invoke-never-perform: the agent has no Tier-2 tool. The loop can ONLY ever stage a
PENDING proposal; it never seals or emits. Sealing the final reviewed bundle is the
Slice-1 Tier-2 handler, fired by the deterministic executor AFTER a human approves —
outside this loop. Every read PDF is UNTRUSTED input.

Budget: each turn's cost (ResultEvent.cost_usd, the priceable cost-per-review COGS
field) is fed to ``RunBudget.increment`` and written to the ledger. A
``BudgetExceededSignal`` is caught here and routed non-blocking — the deterministic
deliverable still ships (Invariant 7).

The SDK is NOT imported here. The loop consumes an ``AgentTransport`` abstraction; the
hermetic fakes fill the sink directly, and the live ``LiveAgentTransport`` runs
``claude_agent_sdk.query`` with the T5.3e reads server behind the same interface
(opt-in, token-burning, not required for the hermetic acceptance).

Zero anthropic import. Zero SDK import. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Protocol

from agent.budget import BudgetExceededSignal, RunBudget
from agent.completeness import engine_seeded_slots, evaluate_completeness
from agent.dossier import (
    DossierArtifact,
    Finding,
    build_dossier,
    dossier_inputs,
    extract_findings,
)
from agent.justification import validate_justification
from agent.ledger import Ledger
from agent.lint import LintResult, lint_framing
from agent.proposals import ProposalArtifact, StagingStore, build_proposal
from agent.registry import CHECK_REGISTRY
from agent.schemas import Tier

# Driver-supplied justification for the engine-tool (run_review_chain) invocation at
# gather. The model does not justify the engine call in the loop — the driver does, as
# a deterministic gather step; the entry is logged Tier-1 for the audit trail.
_GATHER_JUSTIFICATION: str = (
    "Gather the deterministic GST review findings (full atomic chain) so the agent "
    "layer can assemble per-finding case files for human review."
)


# ---------------------------------------------------------------------------
# Agent stream events + transport abstraction
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolUseEvent:
    """The model requests a tool. The DRIVER gates and executes it; the model never does.

    For a Tier-0 read, ``tool_input`` carries the read args plus an ``evidence_slot``
    naming which completeness slot the result fills. For ``propose_action`` it carries
    ``justification`` (+ optional ``action`` / ``evidence_refs``).
    """
    tool_name: str
    tool_input: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FramingEvent:
    """The model's candidate framing text for the current finding."""
    text: str


@dataclass(frozen=True)
class ResultEvent:
    """End of one model turn, carrying the priceable cost (COGS) and raw usage."""
    cost_usd: float = 0.0
    usage: dict = field(default_factory=dict)


AgentEvent = Any  # ToolUseEvent | FramingEvent | ResultEvent


class AgentTransport(Protocol):
    """Runs one model turn for one finding, gathering evidence IN-TURN (arch A).

    ``gather`` runs the turn for *finding* and POPULATES *evidence_sink* with the
    reads the model performed — live: the SDK runs the T5.3e MCP read handlers, which
    write the sink in-turn; hermetic: the fake writes the sink directly. It yields only
    ``FramingEvent`` (candidate framing) and ``ResultEvent`` (per-turn COGS); reads do
    NOT come back as events. The transport is a RELAY — the plain-Python DRIVER
    disposes: it runs budget, the CODE-DEFINED completeness over the sink, the lint,
    driver-decided staging, and bounded re-entry. The model never decides termination.
    """

    def gather(
        self, prompt: str, finding: "Finding", evidence_sink: dict
    ) -> Iterable[AgentEvent]:
        ...


# ---------------------------------------------------------------------------
# Loop context + result
# ---------------------------------------------------------------------------

@dataclass
class LoopContext:
    """Hermetic data sources the Tier-0 dossier reads resolve against (read-only).

    Attributes:
        provider:           DocumentProvider-like (get_document(doc_num) -> path|None).
        vendor_catalog:     card_name -> vendor GST record (for read_vendor_gst_status).
        prior_period_store: key -> prior-period treatment record.
    """
    provider: Any = None
    vendor_catalog: dict = field(default_factory=dict)
    prior_period_store: dict = field(default_factory=dict)


@dataclass
class FindingOutcome:
    """Per-finding outcome of the loop."""
    finding_id: str
    check_id: str
    status: str  # "staged" | "incomplete" | "skipped"
    dossier: Optional[DossierArtifact] = None
    proposal: Optional[ProposalArtifact] = None
    attempts: int = 0
    lint: Optional[LintResult] = None
    reason: Optional[str] = None


@dataclass
class CaseFileResult:
    """Full result of one case-file loop run.

    The deterministic deliverable (review_result + deterministic_bundle_dir) is always
    present on a completed review, even when the agent layer is cut short by budget.
    """
    review_status: str
    deterministic_bundle_dir: Optional[str]
    review_result: Any
    outcomes: list[FindingOutcome]
    dossiers: list[DossierArtifact]
    proposals: list[ProposalArtifact]
    agent_layer_complete: bool
    budget_exceeded: bool
    cost_usd_used: float


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

# Driver-supplied justification for the DRIVER-DECIDED staging step (arch A). The
# model does not (and cannot) call propose_action — an unbacked tool (T5.3-probe).
# When the code-defined completeness and the lint pass, the DRIVER stages, writing
# this Tier-1 justification to the ledger under the registered ``propose_action``
# contract BEFORE staging, preserving "justification written to ledger before staging".
_STAGE_JUSTIFICATION: str = (
    "Stage the human-reviewable dossier for reviewer approval: the code-defined "
    "completeness checklist is satisfied and the candidate framing passed the "
    "language-lint. Pending reviewer approval; no compliance determination is made."
)


def _seed_engine_inputs(finding: Finding) -> dict:
    """Seed the evidence map with the engine-provided input slots for this check.

    The deterministic engine already consumed these inputs to emit the finding, so the
    finding payload IS the engine-provided evidence for each engine-seeded slot.
    """
    evidence: dict = {}
    for slot in engine_seeded_slots(finding.check_id):
        evidence[slot] = finding.payload
    return evidence


def _record_cost(ledger: Ledger, budget: RunBudget, cost_usd: float) -> None:
    """Write the running cost into the ledger — the auditable cost-per-review COGS field."""
    ledger.append(
        tool_name="budget_increment",
        tier=Tier.ZERO,
        justification=None,
        call_params={
            "cost_usd": cost_usd,
            "cost_usd_used": budget.cost_usd_used,
            "turns_used": budget.turns_used,
        },
        outcome="allowed",
        blocked_reason=None,
    )


def build_prompt(finding: Finding) -> str:
    """Build the per-finding gather prompt (honest; ignored by the hermetic FakeTransport).

    A live transport would send this to the model; it instructs candidate framing and
    evidence gathering. It is intentionally minimal here — the system prompt carries the
    cage rules; this names the finding under review.
    """
    return (
        "Assemble a human-review case file for the following deterministic finding. "
        "Gather supporting evidence with the read-only tools, then write candidate "
        "framing (never a compliance verdict) and propose staging the dossier.\n"
        f"finding_id={finding.finding_id} check_id={finding.check_id} "
        f"type={finding.finding_type}\npayload={finding.payload}"
    )


def _run_finding(
    finding: Finding,
    *,
    transport: AgentTransport,
    ctx: LoopContext,
    ledger: Ledger,
    budget: RunBudget,
    store: StagingStore,
    max_attempts: int,
) -> FindingOutcome:
    """Drive gather -> verify -> (driver-decided) act for one finding. Plain Python.

    Arch A: the model gathers evidence IN-TURN — ``transport.gather`` fills the
    per-finding ``evidence_sink`` (live: SDK runs the MCP read handlers; hermetic: the
    fake writes it) and yields only framing + cost. The DRIVER then runs the
    code-defined completeness over the sink, lints the framing, and — when both pass —
    stages a PENDING dossier itself. The driver never executes reads (no double-run).
    """
    last_dossier: Optional[DossierArtifact] = None
    last_lint: Optional[LintResult] = None
    attempts = 0

    while attempts < max_attempts:
        attempts += 1
        # The sink is the evidence map: seed engine-provided slots, then let the
        # transport gather the agent slots IN-TURN.
        evidence = _seed_engine_inputs(finding)
        framing_text = ""
        turn_cost = 0.0

        for event in transport.gather(build_prompt(finding), finding, evidence):
            if isinstance(event, FramingEvent):
                framing_text = event.text
            elif isinstance(event, ResultEvent):
                turn_cost = float(event.cost_usd)
            # Reads do NOT come back as events — they filled `evidence` (the sink).

        # Budget: increment from this turn's cost, record COGS to the ledger.
        # On over-budget the cost is still recorded, then the signal propagates.
        try:
            budget.increment(turns=1, cost_usd=turn_cost)
            _record_cost(ledger, budget, turn_cost)
        except BudgetExceededSignal:
            _record_cost(ledger, budget, turn_cost)
            raise

        # verify (CODE-DEFINED) over the gathered sink + framing lint.
        completeness = evaluate_completeness(finding.check_id, evidence)
        lint = lint_framing(framing_text)
        last_dossier = build_dossier(finding, evidence, framing_text, completeness)
        last_lint = lint

        if completeness["satisfied"] and lint.passed:
            # act (Tier 1) — DRIVER-DECIDED staging.
            proposal = _stage_dossier(finding, last_dossier, store, ledger)
            return FindingOutcome(
                finding_id=finding.finding_id, check_id=finding.check_id,
                status="staged", dossier=last_dossier, proposal=proposal,
                attempts=attempts, lint=lint,
            )
        # else: incomplete or unclean framing — re-enter gather (bounded by
        # max_attempts AND RunBudget).

    return FindingOutcome(
        finding_id=finding.finding_id, check_id=finding.check_id,
        status="incomplete", dossier=last_dossier, proposal=None,
        attempts=attempts, lint=last_lint, reason="max_attempts_exhausted",
    )


def _stage_dossier(
    finding: Finding,
    dossier: DossierArtifact,
    store: StagingStore,
    ledger: Ledger,
) -> ProposalArtifact:
    """Stage the dossier as a PENDING ProposalArtifact — DRIVER-DECIDED (arch A).

    The DRIVER triggers staging when the code-defined completeness + lint pass (the
    model cannot call ``propose_action`` — an unbacked tool). The Tier-1 staging
    justification is written to the ledger under the registered ``propose_action``
    contract BEFORE staging, preserving "justification written to ledger BEFORE
    staging". The proposal anchors to the SAME inputs as the dossier (shared
    inputs_hash). This is still the ONLY Tier-2 path: a human approves the PENDING
    proposal; the loop never seals or emits.
    """
    validate_justification(
        _STAGE_JUSTIFICATION, Tier.ONE,
        tool_name="propose_action", call_params={"action": "attach_dossier"},
        ledger=ledger,
    )
    inputs = dossier_inputs(
        finding, dossier.evidence, dossier.candidate_framing_text, dossier.completeness
    )
    evidence_refs = [f"finding:{finding.finding_id}"] + [
        f"evidence:{slot}" for slot in sorted(dossier.evidence)
    ]
    proposal = build_proposal(
        action="attach_dossier",
        justification=_STAGE_JUSTIFICATION,
        evidence_refs=evidence_refs,
        inputs=inputs,
    )
    store.stage(proposal)  # status="pending"
    return proposal


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_casefile_loop(
    *,
    invoke_review: Callable[[], Any],
    transport: AgentTransport,
    ctx: LoopContext,
    ledger: Ledger,
    budget: RunBudget,
    store: StagingStore,
    max_attempts_per_finding: int = 3,
) -> CaseFileResult:
    """Run the case-file loop and return a CaseFileResult.

    Args:
        invoke_review: Zero-arg callable returning a ReviewResult (the bound engine
                       tool). Called ONCE up front so the deterministic deliverable is
                       captured before any agent-layer work (Invariant 7).
        transport:     AgentTransport streaming the model's per-finding turns.
        ctx:           LoopContext with the hermetic Tier-0 read sources.
        ledger:        Hash-chained ledger; gate decisions + COGS entries are appended.
        budget:        RunBudget; each turn's cost is incremented and written to ledger.
        store:         StagingStore receiving the PENDING dossier proposals.
        max_attempts_per_finding: Re-entry bound per finding (also bounded by budget).

    Returns:
        CaseFileResult. The deterministic deliverable is always present on a completed
        review; ``agent_layer_complete`` is False if budget cut the agent layer short.
    """
    # --- gather: produce the deterministic deliverable up front (Tier-1, gated) ---
    validate_justification(
        _GATHER_JUSTIFICATION, Tier.ONE,
        tool_name="run_review_chain", call_params={}, ledger=ledger,
    )
    review_result = invoke_review()
    review_status = _attr(review_result, "status", "completed")
    bundle_dir = _attr(review_result, "bundle_dir", None)
    deterministic_bundle_dir = str(bundle_dir) if bundle_dir is not None else None

    outcomes: list[FindingOutcome] = []
    agent_layer_complete = True

    if review_status == "completed":
        try:
            for finding in extract_findings(review_result):
                if finding.check_id not in CHECK_REGISTRY:
                    # No registered completeness checklist — cannot CODE-verify; record
                    # and skip (non-blocking). A CheckSpec for this finding is future work.
                    outcomes.append(FindingOutcome(
                        finding_id=finding.finding_id, check_id=finding.check_id,
                        status="skipped", reason="no_registered_checkspec",
                    ))
                    continue
                outcomes.append(_run_finding(
                    finding, transport=transport, ctx=ctx, ledger=ledger,
                    budget=budget, store=store, max_attempts=max_attempts_per_finding,
                ))
        except BudgetExceededSignal:
            # Invariant 7: agent layer is non-blocking. The deterministic deliverable
            # (review_result, sealed bundle) is already in hand and still ships.
            agent_layer_complete = False

    dossiers = [o.dossier for o in outcomes if o.status == "staged" and o.dossier]
    proposals = [o.proposal for o in outcomes if o.status == "staged" and o.proposal]

    return CaseFileResult(
        review_status=review_status,
        deterministic_bundle_dir=deterministic_bundle_dir,
        review_result=review_result,
        outcomes=outcomes,
        dossiers=dossiers,
        proposals=proposals,
        agent_layer_complete=agent_layer_complete,
        budget_exceeded=budget.over_budget,
        cost_usd_used=budget.cost_usd_used,
    )


def _attr(obj: Any, name: str, default: Any) -> Any:
    """Read *name* from a ReviewResult object or serialised dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
