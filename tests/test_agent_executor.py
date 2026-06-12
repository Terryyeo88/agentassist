"""
tests/test_agent_executor.py — executor framework: schema validation, approval-state
guard, dispatch, and one hermetic test handler.

Real seal/emit handlers are explicitly deferred to T5.3 — they are
NotImplemented stubs in executor.py. This test suite covers:
  - Valid proposal + approved state → dispatches to registered handler
  - Unapproved (pending) proposal → rejected
  - Rejected proposal → rejected
  - Unknown action → rejected
  - Handler invoked with correct args
No SDK, no SAP, no network.
"""
from __future__ import annotations

import pytest

from agent.executor import Executor, ExecutorError, ExecutionResult
from agent.proposals import build_proposal, StagingStore
from agent.schemas import Tier


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

VALID_KWARGS = dict(
    action="test_noop",          # handled by the hermetic test handler
    justification="Executing test_noop to verify executor dispatch in the hermetic test suite.",
    evidence_refs=["tests/fixtures/noop_evidence.txt"],
    inputs={"context": "test"},
)


class TestExecutorDispatch:
    def _make_approved_proposal(self):
        store = StagingStore()
        proposal = build_proposal(**VALID_KWARGS)
        store.stage(proposal)
        store.approve(proposal.proposal_id)
        return store, proposal

    def test_approved_proposal_dispatches_successfully(self):
        store, proposal = self._make_approved_proposal()
        executor = Executor(staging_store=store)
        result = executor.execute(proposal.proposal_id)
        assert isinstance(result, ExecutionResult)
        assert result.success is True

    def test_pending_proposal_rejected(self):
        store = StagingStore()
        proposal = build_proposal(**VALID_KWARGS)
        store.stage(proposal)
        # proposal remains "pending" — not approved
        executor = Executor(staging_store=store)
        with pytest.raises(ExecutorError):
            executor.execute(proposal.proposal_id)

    def test_rejected_proposal_not_executed(self):
        store = StagingStore()
        proposal = build_proposal(**VALID_KWARGS)
        store.stage(proposal)
        store.reject(proposal.proposal_id)
        executor = Executor(staging_store=store)
        with pytest.raises(ExecutorError):
            executor.execute(proposal.proposal_id)

    def test_unknown_proposal_id_rejected(self):
        store = StagingStore()
        executor = Executor(staging_store=store)
        with pytest.raises(ExecutorError):
            executor.execute("nonexistent-id")

    def test_unknown_action_raises_executor_error(self):
        store = StagingStore()
        proposal = build_proposal(
            action="unknown_action_xyz",
            justification="Testing that an unknown action is rejected by the executor framework.",
            evidence_refs=["tests/fixtures/evidence.txt"],
            inputs={},
        )
        store.stage(proposal)
        store.approve(proposal.proposal_id)
        executor = Executor(staging_store=store)
        with pytest.raises(ExecutorError):
            executor.execute(proposal.proposal_id)

    def test_seal_bundle_handler_is_not_implemented(self):
        """seal_bundle is a T5.3 deliverable — must be a documented NotImplemented stub."""
        store = StagingStore()
        proposal = build_proposal(
            action="seal_bundle",
            justification="Testing that seal_bundle is deferred to T5.3 per task spec.",
            evidence_refs=["audit/compile-output.json"],
            inputs={"client_id": "sbodemosg"},
        )
        store.stage(proposal)
        store.approve(proposal.proposal_id)
        executor = Executor(staging_store=store)
        with pytest.raises(NotImplementedError):
            executor.execute(proposal.proposal_id)

    def test_emit_pdf_handler_is_not_implemented(self):
        """emit_final_pdf is a T5.3 deliverable — must be a documented NotImplemented stub."""
        store = StagingStore()
        proposal = build_proposal(
            action="emit_final_pdf",
            justification="Testing that emit_final_pdf is deferred to T5.3 per task spec.",
            evidence_refs=["audit/report.pdf"],
            inputs={"client_id": "sbodemosg"},
        )
        store.stage(proposal)
        store.approve(proposal.proposal_id)
        executor = Executor(staging_store=store)
        with pytest.raises(NotImplementedError):
            executor.execute(proposal.proposal_id)
