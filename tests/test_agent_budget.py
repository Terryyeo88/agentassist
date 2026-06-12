"""
tests/test_agent_budget.py — T-9: RunBudget accounting and over-budget routing.

No SDK, no SAP, no network.
"""
from __future__ import annotations

import pytest

from agent.budget import RunBudget, BudgetExceededSignal


class TestRunBudgetNormal:
    def test_initial_state(self):
        b = RunBudget(max_turns=10, max_cost_usd=1.00)
        assert b.turns_used == 0
        assert b.cost_usd_used == 0.0
        assert b.over_budget is False

    def test_increment_turns_under_cap_passes(self):
        b = RunBudget(max_turns=5, max_cost_usd=1.00)
        for _ in range(5):
            b.increment(turns=1, cost_usd=0.0)
        assert b.turns_used == 5
        assert b.over_budget is False

    def test_increment_cost_under_cap_passes(self):
        b = RunBudget(max_turns=10, max_cost_usd=1.00)
        b.increment(turns=1, cost_usd=0.99)
        assert b.cost_usd_used == pytest.approx(0.99)
        assert b.over_budget is False

    def test_zero_cost_increment_ok(self):
        b = RunBudget(max_turns=10, max_cost_usd=1.00)
        b.increment(turns=1, cost_usd=0.0)
        assert b.over_budget is False

    def test_multiple_increments_accumulate(self):
        b = RunBudget(max_turns=10, max_cost_usd=2.00)
        b.increment(turns=1, cost_usd=0.50)
        b.increment(turns=1, cost_usd=0.50)
        assert b.turns_used == 2
        assert b.cost_usd_used == pytest.approx(1.00)


class TestRunBudgetExceeded:
    def test_exceeding_max_turns_raises_signal(self):
        b = RunBudget(max_turns=3, max_cost_usd=10.00)
        b.increment(turns=1, cost_usd=0.0)
        b.increment(turns=1, cost_usd=0.0)
        b.increment(turns=1, cost_usd=0.0)
        with pytest.raises(BudgetExceededSignal) as exc_info:
            b.increment(turns=1, cost_usd=0.0)
        assert "turns" in str(exc_info.value).lower() or exc_info.value.reason

    def test_exceeding_max_cost_raises_signal(self):
        b = RunBudget(max_turns=100, max_cost_usd=0.50)
        b.increment(turns=1, cost_usd=0.49)
        with pytest.raises(BudgetExceededSignal) as exc_info:
            b.increment(turns=1, cost_usd=0.02)
        assert exc_info.value.reason  # must carry a reason

    def test_over_budget_flag_set_on_signal(self):
        b = RunBudget(max_turns=1, max_cost_usd=10.00)
        b.increment(turns=1, cost_usd=0.0)
        try:
            b.increment(turns=1, cost_usd=0.0)
        except BudgetExceededSignal:
            pass
        assert b.over_budget is True

    def test_signal_routes_to_non_blocking_path(self):
        """BudgetExceededSignal must be catchable and must carry enough info
        to route to the non-blocking path (invariant 7: agent failure is
        non-blocking to the deterministic deliverable)."""
        b = RunBudget(max_turns=1, max_cost_usd=10.00)
        b.increment(turns=1, cost_usd=0.0)

        caught = False
        try:
            b.increment(turns=1, cost_usd=0.0)
        except BudgetExceededSignal as sig:
            caught = True
            # Signal must carry a reason so the caller can log + route
            assert sig.reason
            assert b.over_budget is True
        assert caught, "BudgetExceededSignal was not raised"

    def test_at_exact_cap_does_not_raise(self):
        """Reaching exactly max_turns is allowed; exceeding it raises."""
        b = RunBudget(max_turns=3, max_cost_usd=10.00)
        b.increment(turns=3, cost_usd=0.0)
        assert b.turns_used == 3
        assert b.over_budget is False
        # One more turn should trigger
        with pytest.raises(BudgetExceededSignal):
            b.increment(turns=1, cost_usd=0.0)

    def test_cost_at_exact_cap_does_not_raise(self):
        b = RunBudget(max_turns=100, max_cost_usd=1.00)
        b.increment(turns=1, cost_usd=1.00)
        assert b.over_budget is False
        with pytest.raises(BudgetExceededSignal):
            b.increment(turns=1, cost_usd=0.001)
