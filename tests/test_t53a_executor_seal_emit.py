"""
tests/test_t53a_executor_seal_emit.py — T5.3 Slice 1: Tier-2 seal/emit handlers
(acceptance (b)).

seal_bundle / emit_final_pdf are implemented via the Executor's extra_handlers
ctor arg (NOT by editing _DEFAULT_HANDLERS). They fire ONLY when the proposal
status == "approved" (post human approval). On success the execution OUTCOME is
appended to the SEALED hash-chained agent-ledger and handed to the seal/emit
callable so it is sealed into the bundle.

All hermetic: fake seal_fn / emit_fn, no real bundle, no SAP, no network.
"""
from __future__ import annotations

import pytest

from agent.executor import Executor, ExecutorError, ExecutionResult, make_tier2_handlers
from agent.ledger import Ledger
from agent.proposals import build_proposal, StagingStore
from agent.schemas import Tier


def _make_store_with(action: str, status: str) -> tuple[StagingStore, object]:
    store = StagingStore()
    proposal = build_proposal(
        action=action,
        justification=f"Human-reviewed {action}; sealing the engagement bundle per audit close step.",
        evidence_refs=["audit/compile-output.json", "audit/report.pdf"],
        inputs={"client_id": "sbodemosg", "period": "2024Q3"},
    )
    store.stage(proposal)
    if status == "approved":
        store.approve(proposal.proposal_id)
    elif status == "rejected":
        store.reject(proposal.proposal_id)
    return store, proposal


class TestSealEmitFireOnlyOnApproved:
    def _executor(self, store, ledger, seal_calls, emit_calls):
        def fake_seal(*, proposal, ledger):
            seal_calls.append((proposal.proposal_id, ledger))
            return "audit/sbodemosg/2024Q3/20240930-120000"

        def fake_emit(*, proposal, ledger):
            emit_calls.append((proposal.proposal_id, ledger))
            return "audit/sbodemosg/2024Q3/report.pdf"

        handlers = make_tier2_handlers(ledger, seal_fn=fake_seal, emit_fn=fake_emit)
        return Executor(staging_store=store, extra_handlers=handlers)

    def test_seal_fires_on_approved_and_appends_to_sealed_ledger(self):
        ledger = Ledger()
        store, proposal = _make_store_with("seal_bundle", "approved")
        seal_calls: list = []
        emit_calls: list = []
        executor = self._executor(store, ledger, seal_calls, emit_calls)

        result = executor.execute(proposal.proposal_id)

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        # Outcome appended to the SEALED hash-chained ledger as a Tier-2 entry.
        assert len(ledger.entries) == 1
        entry = ledger.entries[0]
        assert entry.tool_name == "seal_bundle"
        assert entry.tier == Tier.TWO.value
        assert entry.outcome == "executed"
        ledger.verify()  # chain intact
        # The seal callable received the same ledger so it is sealed into the bundle.
        assert seal_calls and seal_calls[0][1] is ledger

    def test_emit_fires_on_approved_and_appends_to_sealed_ledger(self):
        ledger = Ledger()
        store, proposal = _make_store_with("emit_final_pdf", "approved")
        seal_calls: list = []
        emit_calls: list = []
        executor = self._executor(store, ledger, seal_calls, emit_calls)

        executor.execute(proposal.proposal_id)

        assert len(ledger.entries) == 1
        entry = ledger.entries[0]
        assert entry.tool_name == "emit_final_pdf"
        assert entry.tier == Tier.TWO.value
        assert entry.outcome == "executed"
        ledger.verify()
        assert emit_calls and emit_calls[0][1] is ledger

    def test_seal_does_not_fire_on_pending(self):
        ledger = Ledger()
        store, proposal = _make_store_with("seal_bundle", "pending")
        seal_calls: list = []
        executor = self._executor(store, ledger, seal_calls, [])
        with pytest.raises(ExecutorError):
            executor.execute(proposal.proposal_id)
        # No execution, no ledger append.
        assert seal_calls == []
        assert ledger.entries == []

    def test_seal_does_not_fire_on_rejected(self):
        ledger = Ledger()
        store, proposal = _make_store_with("seal_bundle", "rejected")
        seal_calls: list = []
        executor = self._executor(store, ledger, seal_calls, [])
        with pytest.raises(ExecutorError):
            executor.execute(proposal.proposal_id)
        assert seal_calls == []
        assert ledger.entries == []

    def test_default_executor_still_raises_not_implemented(self):
        """_DEFAULT_HANDLERS stays untouched: without extra_handlers, seal is a stub."""
        store, proposal = _make_store_with("seal_bundle", "approved")
        executor = Executor(staging_store=store)  # no extra_handlers
        with pytest.raises(NotImplementedError):
            executor.execute(proposal.proposal_id)
