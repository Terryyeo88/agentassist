"""T5.9a1 — Menu correction: honest routing for SHOW_PROPOSALS + SHOW_PRIOR_ADJUDICATIONS.

T5.9a shipped four v0 intents, but two routed to the WRONG tool:
  * SHOW_PROPOSALS -> read_ledger (the justification ledger is NOT the pending-
    proposals queue), and
  * SHOW_PRIOR_ADJUDICATIONS -> read_prior_period_treatment (a per-key prior-period
    store, NOT the T5.5 decision ledger).

This slice registers the two semantically-correct Tier-0 reads and rewires those two
intents so all four dispatch honestly. The invariants under test:

  (a) get_tier("read_proposals") == get_tier("read_decision_ledger") == Tier.ZERO.
  (b) SHOW_PROPOSALS dispatches to ("read_proposals",); SHOW_PRIOR_ADJUDICATIONS to
      ("read_decision_ledger",).
  (c) SHOW_LEDGER and SHOW_PROPOSALS now resolve to DIFFERENT tools (conflation gone),
      and SHOW_PRIOR_ADJUDICATIONS no longer shares read_prior_period_treatment.
  (d) menu-integrity (_assert_menu_well_formed) still holds — every action is a real
      registry tool.
  (e) read_proposals lists PENDING from a StagingStore; read_decision_ledger returns
      adjudications by fingerprint (and lists all when fingerprint omitted).

Hermetic: no live model, no SAP, no tokens. INTENT_MENU remains v0/PROVISIONAL.
"""
from __future__ import annotations

from agent.decision_ledger import DecisionLedger
from agent.intent import INTENT_MENU, DispatchResult, _assert_menu_well_formed, dispatch
from agent.proposals import StagingStore, build_proposal
from agent.read_tools import read_decision_ledger, read_proposals
from agent.registry import REGISTRY, get_tier
from agent.schemas import Tier


# ---------------------------------------------------------------------------
# (a) Both new reads are registered at Tier 0
# ---------------------------------------------------------------------------

class TestNewReadsAreTierZero:
    def test_read_proposals_is_registered_tier_zero(self):
        assert "read_proposals" in REGISTRY
        assert get_tier("read_proposals") is Tier.ZERO

    def test_read_decision_ledger_is_registered_tier_zero(self):
        assert "read_decision_ledger" in REGISTRY
        assert get_tier("read_decision_ledger") is Tier.ZERO


# ---------------------------------------------------------------------------
# (b) The two conflated intents now route to the correct, dedicated tools
# ---------------------------------------------------------------------------

class TestRewiredRouting:
    def test_show_proposals_dispatches_to_read_proposals(self):
        res = dispatch("SHOW_PROPOSALS", {"client_id": "sbodemosg"})
        assert isinstance(res, DispatchResult)
        assert res.sequence == ("read_proposals",)

    def test_show_prior_adjudications_dispatches_to_read_decision_ledger(self):
        res = dispatch(
            "SHOW_PRIOR_ADJUDICATIONS",
            {"client_id": "sbodemosg", "period": "2024-Q1"},
        )
        assert isinstance(res, DispatchResult)
        assert res.sequence == ("read_decision_ledger",)


# ---------------------------------------------------------------------------
# (c) Conflation is gone — distinct intents resolve to distinct tools
# ---------------------------------------------------------------------------

class TestConflationResolved:
    def test_show_ledger_and_show_proposals_resolve_to_different_tools(self):
        ledger = dispatch("SHOW_LEDGER", {"client_id": "c"})
        proposals = dispatch("SHOW_PROPOSALS", {"client_id": "c"})
        assert isinstance(ledger, DispatchResult)
        assert isinstance(proposals, DispatchResult)
        assert ledger.sequence == ("read_ledger",)
        assert proposals.sequence == ("read_proposals",)
        assert ledger.sequence != proposals.sequence

    def test_show_prior_adjudications_no_longer_uses_prior_period_treatment(self):
        res = dispatch(
            "SHOW_PRIOR_ADJUDICATIONS",
            {"client_id": "c", "period": "p"},
        )
        assert isinstance(res, DispatchResult)
        assert res.sequence != ("read_prior_period_treatment",)
        assert res.sequence == ("read_decision_ledger",)


# ---------------------------------------------------------------------------
# (d) Menu-integrity still holds — every action is a real registry tool
# ---------------------------------------------------------------------------

class TestMenuIntegrityHolds:
    def test_assert_menu_well_formed_does_not_raise(self):
        _assert_menu_well_formed(INTENT_MENU)  # must not raise

    def test_every_rewired_action_is_a_registered_tool(self):
        for spec in INTENT_MENU.values():
            for action in spec.sequence:
                assert action in REGISTRY
                assert get_tier(action) is not Tier.THREE


# ---------------------------------------------------------------------------
# (e) The new reads are honest, pure Tier-0 reads over their real sources
# ---------------------------------------------------------------------------

class TestReadProposalsListsPending:
    def test_lists_only_pending_proposals(self):
        store = StagingStore()
        p1 = build_proposal(
            action="seal_bundle",
            justification="needed",
            evidence_refs=["doc-1"],
            inputs={"a": 1},
        )
        p2 = build_proposal(
            action="emit_report",
            justification="needed",
            evidence_refs=["doc-2"],
            inputs={"b": 2},
        )
        store.stage(p1)
        store.stage(p2)
        store.approve(p2.proposal_id)  # no longer pending

        views = read_proposals(store)
        ids = {v["proposal_id"] for v in views}
        assert ids == {p1.proposal_id}
        assert views[0]["action"] == "seal_bundle"
        assert views[0]["status"] == "pending"

    def test_empty_store_returns_empty_list(self):
        assert read_proposals(StagingStore()) == []


class TestReadDecisionLedgerByFingerprint:
    def test_returns_adjudications_for_a_fingerprint(self):
        ledger = DecisionLedger()
        ledger.append(fingerprint="sha256:aaa", disposition="ACCEPTED", reviewer="r1")
        ledger.append(fingerprint="sha256:bbb", disposition="REJECTED", reviewer="r2")

        rows = read_decision_ledger(ledger, fingerprint="sha256:aaa")
        assert len(rows) == 1
        assert rows[0]["fingerprint"] == "sha256:aaa"
        assert rows[0]["disposition"] == "ACCEPTED"
        assert rows[0]["reviewer"] == "r1"

    def test_omitted_fingerprint_lists_all_entries(self):
        ledger = DecisionLedger()
        ledger.append(fingerprint="sha256:aaa", disposition="ACCEPTED", reviewer="r1")
        ledger.append(fingerprint="sha256:bbb", disposition="REJECTED", reviewer="r2")

        rows = read_decision_ledger(ledger)
        assert len(rows) == 2
        assert {r["fingerprint"] for r in rows} == {"sha256:aaa", "sha256:bbb"}

    def test_unknown_fingerprint_returns_empty_list(self):
        ledger = DecisionLedger()
        ledger.append(fingerprint="sha256:aaa", disposition="ACCEPTED", reviewer="r1")
        assert read_decision_ledger(ledger, fingerprint="sha256:zzz") == []

    def test_empty_ledger_returns_empty_list(self):
        assert read_decision_ledger(DecisionLedger()) == []
