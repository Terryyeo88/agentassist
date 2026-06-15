"""
tests/test_t53b_budget_nonblocking.py — T5.3 Slice 2: budget-exceeded is non-blocking.

Invariant 7: an agent that hits its RunBudget cap fails into the NON-BLOCKING path —
the deterministic deliverable (the engine's sealed bundle, captured at gather) still
ships. BudgetExceededSignal is caught by the loop driver, never inside the seal call
(there is no seal call in the loop at all).

The priceable cost-per-review COGS field is still written to the ledger up to and
including the over-budget turn.

Hermetic: FakeTransport, in-memory fakes — no SDK, no binary, no tokens, no SAP.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

from agent.budget import RunBudget
from agent.ledger import Ledger
from agent.loop import LoopContext, run_casefile_loop
from agent.proposals import StagingStore


def _load_fx():
    spec = importlib.util.spec_from_file_location(
        "t53b_agent_loop_fx", pathlib.Path(__file__).parent / "fixtures" / "agent_loop.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fx = _load_fx()


def _ctx():
    return LoopContext(
        provider=fx.FakeProvider({958: "/tmp/INV-958.pdf"}),
        vendor_catalog=fx.default_vendor_catalog(),
        prior_period_store=fx.default_prior_period_store(),
    )


def _invoke(review_dict):
    return lambda: review_dict


def _run(budget):
    ledger = Ledger()
    store = StagingStore()
    ctx = _ctx()
    transport = fx.FakeTransport(scripts=fx.golden_scripts(), ctx=ctx, ledger=ledger)
    result = run_casefile_loop(
        invoke_review=_invoke(fx.canned_review_result()),
        transport=transport, ctx=ctx, ledger=ledger, budget=budget, store=store,
    )
    return result, ledger, store


class TestBudgetExceededMidRun:
    def test_partial_progress_then_nonblocking(self):
        # First finding costs 0.012 (stages); second costs 0.009 -> 0.021 > 0.015 (exceeds).
        budget = RunBudget(max_turns=20, max_cost_usd=0.015)
        result, ledger, store = _run(budget)

        assert budget.over_budget is True
        assert result.budget_exceeded is True
        assert result.agent_layer_complete is False
        # One finding staged before the cap; the second was cut off non-blocking.
        assert len(store.list_pending()) == 1
        # Deterministic deliverable STILL produced (captured at gather, ships regardless).
        assert result.review_status == "completed"
        assert result.deterministic_bundle_dir == "audit/sbodemosg/2024Q3/seal-001"
        # COGS recorded up to and including the over-budget turn.
        cogs = [e for e in ledger.entries if e.tool_name == "budget_increment"]
        assert len(cogs) == 2
        ledger.verify()


class TestBudgetExceededOnFirstFinding:
    def test_no_dossiers_but_deterministic_deliverable_ships(self):
        # First finding's turn (0.012) alone exceeds the 0.01 cap.
        budget = RunBudget(max_turns=20, max_cost_usd=0.01)
        result, ledger, store = _run(budget)

        assert result.budget_exceeded is True
        assert result.agent_layer_complete is False
        assert result.dossiers == []
        assert store.list_pending() == []
        # The deterministic deliverable is unaffected by the agent-layer failure.
        assert result.review_status == "completed"
        assert result.deterministic_bundle_dir == "audit/sbodemosg/2024Q3/seal-001"
        # The over-budget turn's cost was still recorded before the signal propagated.
        cogs = [e for e in ledger.entries if e.tool_name == "budget_increment"]
        assert len(cogs) == 1
        ledger.verify()


class TestBudgetExceededByTurns:
    def test_turn_cap_routes_nonblocking(self):
        budget = RunBudget(max_turns=1, max_cost_usd=100.0)
        result, _ledger, store = _run(budget)
        # Turn cap of 1: first finding consumes the turn; second exceeds.
        assert result.budget_exceeded is True
        assert result.agent_layer_complete is False
        assert len(store.list_pending()) == 1
        assert result.deterministic_bundle_dir == "audit/sbodemosg/2024Q3/seal-001"
