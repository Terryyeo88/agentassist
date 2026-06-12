"""
agent/executor.py — Deterministic Tier-2 executor framework.

The executor fires ONLY after a human approves a ProposalArtifact. It
dispatches to registered action handlers based on proposal.action.

Handler contract:
    handler(proposal: ProposalArtifact) -> ExecutionResult
    Handlers are plain Python functions. They may raise NotImplementedError
    for deferred actions (T5.3), or ExecutorError for hard failures.

Built-in handlers:
    test_noop       — hermetic test handler; always succeeds; no side effects.
    seal_bundle     — DEFERRED to T5.3 (NotImplemented stub).
    emit_final_pdf  — DEFERRED to T5.3 (NotImplemented stub).

Real seal/emit handlers are explicitly deferred to T5.3. The stubs are
documented here so T5.3 knows exactly where to fill them in.

Public API:
    Executor                — dispatcher with staging store + handler registry
    ExecutionResult         — returned by a successful dispatch
    ExecutorError           — raised for approval-state failures and unknown actions

Zero anthropic import. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

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
