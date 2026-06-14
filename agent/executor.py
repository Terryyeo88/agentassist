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

Public API:
    Executor                — dispatcher with staging store + handler registry
    ExecutionResult         — returned by a successful dispatch
    ExecutorError           — raised for approval-state failures and unknown actions
    make_tier2_handlers     — build approved-only seal/emit handlers bound to a Ledger

Zero anthropic import. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from agent.ledger import Ledger
from agent.proposals import ProposalArtifact, StagingStore
from agent.schemas import Tier


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
) -> dict[str, Callable[[ProposalArtifact], ExecutionResult]]:
    """Build the real seal/emit Tier-2 handlers, bound to *ledger*.

    Pass the returned dict as ``Executor(extra_handlers=...)``; it overrides the
    NotImplemented defaults without editing ``_DEFAULT_HANDLERS``. The Executor
    guarantees these fire ONLY for proposals already in status="approved".

    On execution, each handler:
      1. Appends the Tier-2 execution OUTCOME to the SEALED hash-chained ledger
         (tool_name=action, tier=2, outcome="executed") BEFORE invoking the bound
         callable — so the outcome entry is captured when the bundle is sealed.
      2. Invokes the bound callable as ``fn(proposal=..., ledger=ledger)``. The
         callable performs the real side effect (seal_bundle / emit) and receives
         the ledger so it can seal those entries into the bundle.

    Args:
        ledger:  The agent Ledger that is sealed into the bundle.
        seal_fn: Bound callable performing the bundle seal. Receives the proposal
                 and ledger; returns a value used as ExecutionResult.detail.
        emit_fn: Bound callable performing the final-PDF emit, same contract.

    Returns:
        {"seal_bundle": <handler>, "emit_final_pdf": <handler>}.
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

    return {
        "seal_bundle": _make("seal_bundle", seal_fn),
        "emit_final_pdf": _make("emit_final_pdf", emit_fn),
    }
