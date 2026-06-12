"""
tests/test_t52b_approve_cli.py — T-6: approval CLI over StagingStore + Executor.

Hermetic. No SDK, no SAP, no network.

T-6  Approval CLI functions: list pending, show by id, approve by id (triggers
     executor dispatch to hermetic test_noop handler), reject by id; invalid id
     handled; state transitions correct.
"""
from __future__ import annotations

import pytest

from agent.proposals import StagingStore, build_proposal
from agent.executor import Executor, ExecutorError
from agent.schemas import Tier


def _make_proposal(action: str = "test_noop") -> object:
    return build_proposal(
        action=action,
        justification="Sealing Q3 2024 audit bundle after full chain review per IRAS ASK Step 1.",
        evidence_refs=["steps/calculate.json", "gates.json"],
        inputs={"period": "2024-Q3", "client": "testclient"},
    )


class TestT6ApproveCLI:
    def setup_method(self):
        self.store = StagingStore()
        self.executor = Executor(self.store)

    # --- list_pending ---

    def test_list_pending_empty(self):
        from agent.approve_cli import list_pending
        result = list_pending(self.store)
        assert result == []

    def test_list_pending_shows_staged_proposals(self):
        from agent.approve_cli import list_pending

        p = _make_proposal()
        self.store.stage(p)
        result = list_pending(self.store)
        assert len(result) == 1
        assert result[0]["proposal_id"] == p.proposal_id
        assert result[0]["status"] == "pending"

    def test_list_pending_excludes_approved(self):
        from agent.approve_cli import list_pending

        p = _make_proposal()
        self.store.stage(p)
        self.store.approve(p.proposal_id)
        result = list_pending(self.store)
        assert result == []

    # --- show ---

    def test_show_returns_proposal_dict(self):
        from agent.approve_cli import show_proposal

        p = _make_proposal()
        self.store.stage(p)
        result = show_proposal(self.store, p.proposal_id)
        assert result["proposal_id"] == p.proposal_id
        assert result["action"] == "test_noop"

    def test_show_invalid_id_returns_none(self):
        from agent.approve_cli import show_proposal

        result = show_proposal(self.store, "00000000-0000-0000-0000-000000000000")
        assert result is None

    # --- approve → executor dispatch ---

    def test_approve_transitions_status(self):
        from agent.approve_cli import approve_proposal

        p = _make_proposal()
        self.store.stage(p)
        result = approve_proposal(self.store, self.executor, p.proposal_id)
        assert result["status"] == "approved"
        assert result["execution"]["success"] is True

    def test_approve_dispatches_test_noop(self):
        from agent.approve_cli import approve_proposal

        p = _make_proposal(action="test_noop")
        self.store.stage(p)
        result = approve_proposal(self.store, self.executor, p.proposal_id)
        assert result["execution"]["action"] == "test_noop"
        assert "test_noop executed successfully" in result["execution"]["detail"]

    def test_approve_invalid_id_raises(self):
        from agent.approve_cli import approve_proposal

        with pytest.raises(KeyError):
            approve_proposal(self.store, self.executor, "00000000-0000-0000-0000-000000000000")

    # --- reject ---

    def test_reject_transitions_status(self):
        from agent.approve_cli import reject_proposal

        p = _make_proposal()
        self.store.stage(p)
        result = reject_proposal(self.store, p.proposal_id)
        assert result["status"] == "rejected"

    def test_reject_invalid_id_raises(self):
        from agent.approve_cli import reject_proposal

        with pytest.raises(KeyError):
            reject_proposal(self.store, "00000000-0000-0000-0000-000000000000")

    # --- state transitions ---

    def test_double_approve_executor_allows(self):
        """Approving an already-approved proposal re-executes (executor checks approved status)."""
        from agent.approve_cli import approve_proposal

        p = _make_proposal()
        self.store.stage(p)
        approve_proposal(self.store, self.executor, p.proposal_id)
        # Already approved — executor will accept it again (status stays "approved")
        result = approve_proposal(self.store, self.executor, p.proposal_id)
        assert result["status"] == "approved"

    def test_execute_rejected_raises(self):
        """Trying to execute a rejected proposal raises ExecutorError."""
        p = _make_proposal()
        self.store.stage(p)
        self.store.reject(p.proposal_id)
        with pytest.raises(ExecutorError):
            self.executor.execute(p.proposal_id)

    def test_list_pending_after_multiple_stages(self):
        from agent.approve_cli import list_pending

        p1 = _make_proposal()
        p2 = _make_proposal()
        self.store.stage(p1)
        self.store.stage(p2)
        pending = list_pending(self.store)
        assert len(pending) == 2
        ids = {item["proposal_id"] for item in pending}
        assert p1.proposal_id in ids
        assert p2.proposal_id in ids
