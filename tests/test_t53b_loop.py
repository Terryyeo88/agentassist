"""
tests/test_t53b_loop.py — T5.3 Slice 2: full case-file loop over FakeTransport.

Drives the plain-Python loop (gather -> act -> verify) end to end with a hermetic
FakeTransport replaying a scripted agent stream. Asserts the acceptance behaviour:

  * dossiers land in the StagingStore as PENDING proposals (one per completed finding);
  * the hash-chained ledger verify()s after the run;
  * the RunBudget is incremented from each turn's cost;
  * the cost-per-review COGS field is written into the ledger;
  * incomplete dossiers re-enter gather (bounded), then complete on a later turn;
  * NOTHING is sealed or emitted by the loop (no Tier-2 execution outcomes).

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
from agent.schemas import Tier


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
    def _f():
        return review_dict
    return _f


class TestFullLoopHappyPath:
    def _run(self):
        ledger = Ledger()
        budget = RunBudget(max_turns=20, max_cost_usd=1.0)
        store = StagingStore()
        ctx = _ctx()
        transport = fx.FakeTransport(scripts=fx.golden_scripts(), ctx=ctx, ledger=ledger)
        result = run_casefile_loop(
            invoke_review=_invoke(fx.canned_review_result()),
            transport=transport, ctx=ctx, ledger=ledger, budget=budget, store=store,
        )
        return result, ledger, budget, store

    def test_both_findings_staged_as_pending_proposals(self):
        result, _ledger, _budget, store = self._run()
        # One dossier + one pending proposal per completed finding (2 total).
        assert len(result.dossiers) == 2
        assert len(result.proposals) == 2
        pending = store.list_pending()
        assert len(pending) == 2
        assert all(p.status == "pending" for p in pending)
        assert {o.status for o in result.outcomes} == {"staged"}

    def test_dossier_and_proposal_share_inputs_hash(self):
        result, _ledger, _budget, _store = self._run()
        by_finding = {o.finding_id: o for o in result.outcomes}
        for outcome in by_finding.values():
            assert outcome.dossier.inputs_hash == outcome.proposal.inputs_hash
            assert outcome.dossier.completeness["satisfied"] is True

    def test_ledger_verifies_after_run(self):
        _result, ledger, _budget, _store = self._run()
        ledger.verify()  # chain intact across gate + COGS entries
        assert len(ledger.entries) > 0

    def test_budget_incremented_and_cost_in_ledger(self):
        result, ledger, budget, _store = self._run()
        # Two completed turns at 0.012 + 0.009 = 0.021.
        assert budget.turns_used == 2
        assert abs(budget.cost_usd_used - 0.021) < 1e-9
        assert abs(result.cost_usd_used - 0.021) < 1e-9
        # The COGS field is written to the ledger (auditable cost-per-review).
        cogs = [e for e in ledger.entries if e.tool_name == "budget_increment"]
        assert len(cogs) == 2
        assert any("cost_usd_used" in e.call_params for e in cogs)
        assert cogs[-1].call_params["cost_usd_used"] == budget.cost_usd_used

    def test_nothing_sealed_or_emitted_by_loop(self):
        result, ledger, _budget, _store = self._run()
        # The loop has no seal/emit path: no Tier-2 execution outcome in the ledger.
        assert all(e.tier != Tier.TWO.value for e in ledger.entries)
        assert result.deterministic_bundle_dir == "audit/sbodemosg/2024Q3/seal-001"
        assert result.agent_layer_complete is True

    def test_engine_tool_invocation_is_gated_tier1(self):
        _result, ledger, _budget, _store = self._run()
        gather = [e for e in ledger.entries if e.tool_name == "run_review_chain"]
        assert len(gather) == 1
        assert gather[0].tier == Tier.ONE.value
        assert gather[0].outcome == "allowed"


class TestReEntryOnIncompleteDossier:
    def test_incomplete_first_turn_re_enters_then_completes(self):
        ledger = Ledger()
        budget = RunBudget(max_turns=20, max_cost_usd=1.0)
        store = StagingStore()
        scripts = {
            "detect:NO_GST_REG:605": fx.incomplete_then_complete_no_gst_reg(),
            # gst_amount_mismatch completes first turn.
            "doc:gst_amount_mismatch:958": [fx.golden_turn_doc_mismatch()],
        }
        ctx = _ctx()
        transport = fx.FakeTransport(scripts=scripts, ctx=ctx, ledger=ledger)
        result = run_casefile_loop(
            invoke_review=_invoke(fx.canned_review_result()),
            transport=transport, ctx=ctx, ledger=ledger, budget=budget, store=store,
        )
        no_gst = [o for o in result.outcomes if o.check_id == "NO_GST_REG"][0]
        # Took two attempts (turn 1 incomplete, turn 2 complete).
        assert no_gst.attempts == 2
        assert no_gst.status == "staged"
        # Both turns' cost counted (0.004 + 0.012).
        cogs = [e for e in ledger.entries if e.tool_name == "budget_increment"]
        no_gst_cost = 0.004 + 0.012
        doc_cost = 0.009
        assert abs(budget.cost_usd_used - (no_gst_cost + doc_cost)) < 1e-9
        assert len(cogs) == 3  # 2 turns for NO_GST_REG + 1 for the doc finding
        ledger.verify()


class TestHaltedReviewProducesNoDossiers:
    def test_halted_review_yields_deterministic_deliverable_only(self):
        ledger = Ledger()
        budget = RunBudget(max_turns=20, max_cost_usd=1.0)
        store = StagingStore()
        ctx = _ctx()
        transport = fx.FakeTransport(scripts={}, ctx=ctx, ledger=ledger)
        result = run_casefile_loop(
            invoke_review=_invoke(fx.halted_review_result()),
            transport=transport, ctx=ctx, ledger=ledger, budget=budget, store=store,
        )
        assert result.review_status == "halted"
        assert result.dossiers == []
        assert store.list_pending() == []
