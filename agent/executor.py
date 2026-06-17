"""
agent/executor.py — Deterministic Tier-2 executor framework.

The executor fires ONLY after a human approves a ProposalArtifact. It
dispatches to registered action handlers based on proposal.action.

Handler contract:
    handler(proposal: ProposalArtifact) -> ExecutionResult
    Handlers are plain Python functions. They may raise NotImplementedError
    for deferred actions (T5.3), or ExecutorError for hard failures.

Built-in handlers (_DEFAULT_HANDLERS, intentionally left as-is):
    test_noop       — hermetic test handler; always succeeds; no side effects.
    seal_bundle     — NotImplemented stub (default).
    emit_final_pdf  — NotImplemented stub (default).

Real Tier-2 handlers (T5.3 Slice 1) are supplied via ``make_tier2_handlers`` and
passed through the ``extra_handlers`` ctor arg — the defaults are NOT edited, so
an Executor built without extra_handlers still raises NotImplementedError for
seal/emit. SEALED-CHAIN DECISION (locked): a Tier-2 execution outcome
(seal/emit, post human approval) APPENDS to the SEALED hash-chained agent-ledger
and is handed to the bound seal/emit callable so it is sealed into the bundle.
Tier-0 routine reads stay in the separate, unsealed audit_log (agent/hooks.py).

Decision-ledger WRITE (T5.5b): when a ``decision_ledger`` is passed to
``make_tier2_handlers``, a third Tier-2 handler ``record_adjudication`` is added. It
appends an ``AdjudicationEntry`` to the append-only DecisionLedger ONLY for an
APPROVED proposal — the agent never writes the ledger (get_tier("record_adjudication")
-> Tier.THREE, structurally absent). This slice builds + hermetically tests the
handler; the live panel-adjudicate -> append loop is a FOLLOW-ON.

Public API:
    Executor                  — dispatcher with staging store + handler registry
    ExecutionResult           — returned by a successful dispatch
    ExecutorError             — raised for approval-state failures and unknown actions
    make_tier2_handlers       — build approved-only seal/emit (+ optional adjudication) handlers
    build_adjudication_proposal — build a record_adjudication ProposalArtifact (v0 shim)
    RECORD_ADJUDICATION_ACTION  — the record_adjudication action name

Zero anthropic import. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from agent.decision_ledger import DecisionLedger, compute_finding_fingerprint
from agent.ledger import Ledger
from agent.proposals import ProposalArtifact, StagingStore, build_proposal
from agent.schemas import Tier

#: The action name for a decision-ledger adjudication write. Deliberately ABSENT from
#: agent.registry, so get_tier() -> Tier.THREE: a ledger write is a human action.
RECORD_ADJUDICATION_ACTION = "record_adjudication"


@dataclass
class ExecutionResult:
    """Result of a successful executor dispatch.

    Attributes:
        proposal_id: The proposal that was executed.
        action:      The action that was performed.
        success:     Always True for a completed ExecutionResult.
        detail:      Optional human-readable detail from the handler.
    """
    proposal_id: str
    action: str
    success: bool = True
    detail: Optional[str] = None


class ExecutorError(RuntimeError):
    """Raised by Executor.execute() for approval-state failures and unknown actions."""


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------

def _handle_test_noop(proposal: ProposalArtifact) -> ExecutionResult:
    """Hermetic test handler — no side effects. Returns success immediately."""
    return ExecutionResult(
        proposal_id=proposal.proposal_id,
        action=proposal.action,
        success=True,
        detail="test_noop executed successfully (hermetic test handler)",
    )


def _handle_seal_bundle(proposal: ProposalArtifact) -> ExecutionResult:
    # T5.3 deliverable — seal the audit bundle after human approval.
    # Inputs expected in proposal: client_id, period, compile_output path.
    raise NotImplementedError(
        "seal_bundle handler is deferred to T5.3. "
        "Implement in executor.py when the T5.3 case-file builder is built."
    )


def _handle_emit_final_pdf(proposal: ProposalArtifact) -> ExecutionResult:
    # T5.3 deliverable — emit the final signed PDF after human approval.
    raise NotImplementedError(
        "emit_final_pdf handler is deferred to T5.3. "
        "Implement in executor.py when the T5.3 case-file builder is built."
    )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

_DEFAULT_HANDLERS: dict[str, Callable] = {
    "test_noop": _handle_test_noop,
    "seal_bundle": _handle_seal_bundle,
    "emit_final_pdf": _handle_emit_final_pdf,
}


class Executor:
    """Deterministic Tier-2 executor.

    Validates approval state, looks up the action handler, and dispatches.
    The agent never calls execute() — only the CLI approval path does, after
    a human reviews and approves the proposal.

    Args:
        staging_store: The StagingStore holding proposals.
        extra_handlers: Additional action → handler mappings (for T5.3 extension).
    """

    def __init__(
        self,
        staging_store: StagingStore,
        extra_handlers: Optional[dict[str, Callable]] = None,
    ) -> None:
        self._store = staging_store
        self._handlers: dict[str, Callable] = {**_DEFAULT_HANDLERS}
        if extra_handlers:
            self._handlers.update(extra_handlers)

    def execute(self, proposal_id: str) -> ExecutionResult:
        """Dispatch an approved proposal to its handler.

        Args:
            proposal_id: ID of the proposal to execute.

        Returns:
            ExecutionResult from the handler.

        Raises:
            ExecutorError: If the proposal is not found, is not approved,
                           or the action has no registered handler.
            NotImplementedError: Propagated from deferred T5.3 handlers.
        """
        artifact = self._store.get(proposal_id)
        if artifact is None:
            raise ExecutorError(f"No proposal found with id={proposal_id!r}")

        if artifact.status != "approved":
            raise ExecutorError(
                f"Proposal {proposal_id!r} has status={artifact.status!r}; "
                "only 'approved' proposals may be executed"
            )

        handler = self._handlers.get(artifact.action)
        if handler is None:
            raise ExecutorError(
                f"No handler registered for action={artifact.action!r}. "
                "Register the handler in Executor._handlers or pass via extra_handlers."
            )

        return handler(artifact)


# ---------------------------------------------------------------------------
# Tier-2 handlers (T5.3 Slice 1) — seal / emit, approved-only, sealed-chain
# ---------------------------------------------------------------------------

def make_tier2_handlers(
    ledger: Ledger,
    *,
    seal_fn: Callable[..., object],
    emit_fn: Callable[..., object],
    decision_ledger: Optional[DecisionLedger] = None,
) -> dict[str, Callable[[ProposalArtifact], ExecutionResult]]:
    """Build the real seal/emit Tier-2 handlers, bound to *ledger*.

    Pass the returned dict as ``Executor(extra_handlers=...)``; it overrides the
    NotImplemented defaults without editing ``_DEFAULT_HANDLERS``. The Executor
    guarantees these fire ONLY for proposals already in status="approved".

    On execution, each seal/emit handler:
      1. Appends the Tier-2 execution OUTCOME to the SEALED hash-chained ledger
         (tool_name=action, tier=2, outcome="executed") BEFORE invoking the bound
         callable — so the outcome entry is captured when the bundle is sealed.
      2. Invokes the bound callable as ``fn(proposal=..., ledger=ledger)``. The
         callable performs the real side effect (seal_bundle / emit) and receives
         the ledger so it can seal those entries into the bundle.

    If *decision_ledger* is supplied, a third handler ``record_adjudication`` is added
    (T5.5b). It appends an ``AdjudicationEntry`` to the append-only DecisionLedger —
    that append IS the durable side effect (parity with seal/emit's append-before-act:
    the action's record lands on a hash-chained, verify()-able ledger). It fires ONLY
    for an approved proposal (Executor-enforced). The agent never writes it.

    Args:
        ledger:          The agent Ledger that is sealed into the bundle.
        seal_fn:         Bound callable performing the bundle seal. Receives the proposal
                         and ledger; returns a value used as ExecutionResult.detail.
        emit_fn:         Bound callable performing the final-PDF emit, same contract.
        decision_ledger: Optional DecisionLedger; when given, adds record_adjudication.

    Returns:
        {"seal_bundle", "emit_final_pdf"} (+ "record_adjudication" if decision_ledger).
    """

    def _make(action: str, fn: Callable[..., object]) -> Callable[[ProposalArtifact], ExecutionResult]:
        def _handler(proposal: ProposalArtifact) -> ExecutionResult:
            # Sealed-chain decision: record the Tier-2 execution outcome on the
            # hash-chained ledger before the side effect seals it into the bundle.
            ledger.append(
                tool_name=action,
                tier=Tier.TWO,
                justification=proposal.justification,
                call_params={
                    "proposal_id": proposal.proposal_id,
                    "evidence_refs": proposal.evidence_refs,
                    "inputs_hash": proposal.inputs_hash,
                },
                outcome="executed",
                blocked_reason=None,
            )
            detail = fn(proposal=proposal, ledger=ledger)
            return ExecutionResult(
                proposal_id=proposal.proposal_id,
                action=proposal.action,
                success=True,
                detail=None if detail is None else str(detail),
            )

        return _handler

    handlers: dict[str, Callable[[ProposalArtifact], ExecutionResult]] = {
        "seal_bundle": _make("seal_bundle", seal_fn),
        "emit_final_pdf": _make("emit_final_pdf", emit_fn),
    }
    if decision_ledger is not None:
        handlers[RECORD_ADJUDICATION_ACTION] = _make_adjudication_handler(decision_ledger)
    return handlers


def _make_adjudication_handler(
    decision_ledger: DecisionLedger,
) -> Callable[[ProposalArtifact], ExecutionResult]:
    """Build the approved-only record_adjudication handler bound to *decision_ledger*.

    The handler decodes the v0/PROVISIONAL adjudication shim carried on the
    schema-pinned ProposalArtifact (see ``build_adjudication_proposal``) and appends
    one AdjudicationEntry. The DecisionLedger is itself append-only + hash-chained, so
    the append is the durable, verify()-able record of the human's decision.
    """

    def _handler(proposal: ProposalArtifact) -> ExecutionResult:
        payload = _decode_adjudication_payload(proposal)
        entry = decision_ledger.append(
            fingerprint=proposal.inputs_hash,
            disposition=payload["disposition"],
            reviewer=payload["reviewer"],
            reason=proposal.justification,
            period=payload.get("period"),
        )
        return ExecutionResult(
            proposal_id=proposal.proposal_id,
            action=proposal.action,
            success=True,
            detail=f"adjudication recorded: {entry.disposition}",
        )

    return _handler


# ---------------------------------------------------------------------------
# record_adjudication proposal shim (T5.5b — v0/PROVISIONAL)
# ---------------------------------------------------------------------------
#
# TODO(panel-write follow-on): ProposalArtifact is schema-pinned (T5.8 tripwire), so the
# adjudication fields are OVERLOADED onto existing fields:
#     inputs_hash    = the finding fingerprint        (anchor)
#     evidence_refs  = [{disposition, reviewer, period}]
#     justification  = the reviewer's reason
# The panel-adjudicate -> append follow-on should give record_adjudication a properly
# TYPED carrier (e.g. an AdjudicationProposal) rather than overloading ProposalArtifact.

def build_adjudication_proposal(
    *,
    finding: object,
    disposition: str,
    reviewer: str,
    reason: str,
    period: Optional[str] = None,
) -> ProposalArtifact:
    """Build a validated record_adjudication ProposalArtifact for *finding* (v0 shim).

    The proposal's ``inputs_hash`` is set to the finding's deterministic fingerprint so
    the executor handler keys the AdjudicationEntry on the same value
    ``annotate_and_demote`` reads. The disposition/reviewer/period ride in
    ``evidence_refs[0]`` and the reason rides in ``justification`` (see module TODO).
    """
    fingerprint = compute_finding_fingerprint(finding)
    proposal = build_proposal(
        action=RECORD_ADJUDICATION_ACTION,
        justification=reason,
        evidence_refs=[{
            "disposition": disposition,
            "reviewer": reviewer,
            "period": period,
        }],
        inputs={"fingerprint": fingerprint},
    )
    # v0 shim: overload inputs_hash to BE the fingerprint (the canonical anchor), so the
    # handler and annotate_and_demote agree without re-deriving from overloaded fields.
    proposal.inputs_hash = fingerprint
    return proposal


def _decode_adjudication_payload(proposal: ProposalArtifact) -> dict:
    """Decode the v0 adjudication shim from a record_adjudication proposal."""
    refs = proposal.evidence_refs or []
    if not refs or not isinstance(refs[0], dict):
        raise ExecutorError(
            "record_adjudication proposal must carry evidence_refs[0] = "
            "{disposition, reviewer, period}"
        )
    payload = refs[0]
    if "disposition" not in payload or "reviewer" not in payload:
        raise ExecutorError(
            "record_adjudication payload missing required disposition/reviewer"
        )
    return payload
