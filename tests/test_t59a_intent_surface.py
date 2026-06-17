"""T5.9a — Intent surface: bounded menu + dispatch (hermetic).

The intent surface is Invariant 6 made into a product front door: a FIXED menu of
intents, each mapping to a tier-classified action SEQUENCE, plus a deterministic
DISPATCH that routes a (validated) intent + EXPLICITLY-BOUND params to its
sequence. Dispatch routes to EXISTING tier-classified registry actions; it can
NEVER grant an out-of-tier capability or emit a non-menu intent. The invariants
under test:

  (a) Each menu intent dispatches to its DECLARED registry sequence (and only it).
  (b) A non-menu intent is REJECTED (IntentError), never dispatched — the
      ⊆-menu invariant, the T5.9 twin of the planner's ⊆-registry.
  (c) A missing required param yields a structured NEEDS_CLARIFICATION result,
      never a guessed client_id / period.
  (d) Dispatch grants NO out-of-tier authority: every dispatched action resolves
      to its EXISTING registered tier via get_tier; the surface adds none.

NO natural-language classifier here (that's T5.9b) and NO chat UI (T5.9b/c).
INTENT_MENU is v0/PROVISIONAL. Hermetic: no live model, no SAP, no tokens.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent.intent import (
    INTENT_MENU,
    DispatchResult,
    IntentError,
    IntentSpec,
    NeedsClarification,
    dispatch,
)
from agent.registry import REGISTRY, get_tier
from agent.schemas import Tier

_REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Menu integrity — the fixed surface is well-formed
# ---------------------------------------------------------------------------

class TestMenuIntegrity:
    def test_menu_is_nonempty_and_specs_are_intentspecs(self):
        assert INTENT_MENU
        for name, spec in INTENT_MENU.items():
            assert isinstance(spec, IntentSpec)
            assert spec.intent == name  # the key is the spec's own name

    def test_every_sequence_action_is_a_registered_tool(self):
        # Every action a menu intent declares must be a real registry tool, so
        # get_tier resolves a real tier (never THREE = absent/structurally
        # impossible). This is the build-time twin of the planner's ⊆-registry.
        for spec in INTENT_MENU.values():
            assert spec.sequence, f"{spec.intent} has an empty sequence"
            for action in spec.sequence:
                assert action in REGISTRY, (
                    f"{spec.intent} routes to {action!r} which is not a registered "
                    "tool — the surface may not invent an action"
                )
                assert get_tier(action) is not Tier.THREE

    def test_expected_v0_menu_present(self):
        assert set(INTENT_MENU) == {
            "RUN_REVIEW",
            "SHOW_LEDGER",
            "SHOW_PROPOSALS",
            "SHOW_PRIOR_ADJUDICATIONS",
        }


# ---------------------------------------------------------------------------
# (a) Each menu intent dispatches to its declared sequence
# ---------------------------------------------------------------------------

class TestDispatchRoutesDeclaredSequence:
    def test_run_review_dispatches_to_run_review_chain(self):
        res = dispatch("RUN_REVIEW", {"client_id": "sbodemosg", "period": "2024-Q1"})
        assert isinstance(res, DispatchResult)
        assert res.intent == "RUN_REVIEW"
        assert res.sequence == ("run_review_chain",)
        assert res.params == {"client_id": "sbodemosg", "period": "2024-Q1"}

    def test_show_ledger_dispatches_to_read_ledger(self):
        res = dispatch("SHOW_LEDGER", {"client_id": "sbodemosg"})
        assert isinstance(res, DispatchResult)
        assert res.sequence == ("read_ledger",)

    def test_show_proposals_dispatches_to_read_proposals(self):
        # T5.9a1: SHOW_PROPOSALS now routes to the dedicated pending-proposals read,
        # NOT read_ledger (the justification ledger). See test_t59a1_menu_correction.
        res = dispatch("SHOW_PROPOSALS", {"client_id": "sbodemosg"})
        assert isinstance(res, DispatchResult)
        assert res.sequence == ("read_proposals",)

    def test_show_prior_adjudications_dispatches_to_read_decision_ledger(self):
        # T5.9a1: SHOW_PRIOR_ADJUDICATIONS now routes to the T5.5 decision ledger,
        # NOT read_prior_period_treatment. See test_t59a1_menu_correction.
        res = dispatch(
            "SHOW_PRIOR_ADJUDICATIONS",
            {"client_id": "sbodemosg", "period": "2024-Q1"},
        )
        assert isinstance(res, DispatchResult)
        assert res.sequence == ("read_decision_ledger",)

    def test_dispatch_result_sequence_equals_declared_spec_sequence(self):
        # Dispatch routes to EXACTLY the declared sequence — no more, no fewer.
        for name, spec in INTENT_MENU.items():
            params = {p: "x" for p in spec.required_params}
            res = dispatch(name, params)
            assert isinstance(res, DispatchResult)
            assert res.sequence == spec.sequence


# ---------------------------------------------------------------------------
# (b) ⊆-menu invariant — a non-menu intent is rejected, never dispatched
# ---------------------------------------------------------------------------

class TestSubsetMenuInvariant:
    @pytest.mark.parametrize(
        "bogus",
        ["DELETE_LEDGER", "seal_bundle", "run_review_chain", "", "run_review",
         "RUN_REVIEW ", "SHOW_LEDGERX"],
    )
    def test_non_menu_intent_is_rejected(self, bogus):
        with pytest.raises(IntentError):
            dispatch(bogus, {"client_id": "sbodemosg", "period": "2024-Q1"})

    def test_a_real_tool_name_is_not_an_intent(self):
        # A registered TOOL is not a menu INTENT — the surface routes intents,
        # never raw tools. (run_review_chain is a Tier-1 action, not an intent.)
        assert "run_review_chain" not in INTENT_MENU
        with pytest.raises(IntentError):
            dispatch("run_review_chain", {"client_id": "c", "period": "p"})


# ---------------------------------------------------------------------------
# (c) Missing required params -> NEEDS_CLARIFICATION, never a guess
# ---------------------------------------------------------------------------

class TestNeedsClarification:
    def test_missing_period_yields_needs_clarification(self):
        res = dispatch("RUN_REVIEW", {"client_id": "sbodemosg"})
        assert isinstance(res, NeedsClarification)
        assert res.intent == "RUN_REVIEW"
        assert res.missing_params == ("period",)

    def test_missing_client_id_yields_needs_clarification(self):
        res = dispatch("RUN_REVIEW", {"period": "2024-Q1"})
        assert isinstance(res, NeedsClarification)
        assert res.missing_params == ("client_id",)

    def test_empty_params_lists_all_required_in_order(self):
        res = dispatch("RUN_REVIEW", {})
        assert isinstance(res, NeedsClarification)
        assert res.missing_params == ("client_id", "period")

    def test_blank_or_whitespace_value_counts_as_missing(self):
        # An identity-bearing slot present-but-blank is NOT a value; the surface
        # must ask, not run the review for an empty client.
        res = dispatch("RUN_REVIEW", {"client_id": "   ", "period": "2024-Q1"})
        assert isinstance(res, NeedsClarification)
        assert res.missing_params == ("client_id",)

    def test_never_guesses_a_default_client_or_period(self):
        # The whole point: a miss never silently becomes a DispatchResult with a
        # fabricated client/period.
        res = dispatch("SHOW_PRIOR_ADJUDICATIONS", {"client_id": "sbodemosg"})
        assert isinstance(res, NeedsClarification)
        assert "period" in res.missing_params

    def test_clarification_message_names_the_missing_slots(self):
        res = dispatch("RUN_REVIEW", {})
        assert isinstance(res, NeedsClarification)
        assert "client_id" in res.message and "period" in res.message

    def test_extra_params_are_ignored_not_an_error(self):
        # Surplus params don't block dispatch; only the required set gates.
        res = dispatch("SHOW_LEDGER", {"client_id": "c", "noise": "z"})
        assert isinstance(res, DispatchResult)


# ---------------------------------------------------------------------------
# (d) No out-of-tier authority — tiers come from the registry, never the surface
# ---------------------------------------------------------------------------

class TestNoTierEscalation:
    def test_dispatch_tiers_match_get_tier_for_each_action(self):
        for name, spec in INTENT_MENU.items():
            params = {p: "x" for p in spec.required_params}
            res = dispatch(name, params)
            assert isinstance(res, DispatchResult)
            expected = tuple(int(get_tier(a)) for a in spec.sequence)
            assert res.tiers == expected

    def test_run_review_is_tier_1_show_actions_are_tier_0(self):
        run = dispatch("RUN_REVIEW", {"client_id": "c", "period": "p"})
        assert run.tiers == (int(Tier.ONE),)
        for intent in ("SHOW_LEDGER", "SHOW_PROPOSALS"):
            res = dispatch(intent, {"client_id": "c"})
            assert res.tiers == (int(Tier.ZERO),)

    def test_surface_never_emits_tier_2_or_3(self):
        # The product surface dispatches only to Tier-0/1 registered actions —
        # never a Tier-2 effect (that stays behind propose_action + human
        # approval) and never a Tier-3 (absent) action.
        for name, spec in INTENT_MENU.items():
            params = {p: "x" for p in spec.required_params}
            res = dispatch(name, params)
            assert isinstance(res, DispatchResult)
            assert all(t in (int(Tier.ZERO), int(Tier.ONE)) for t in res.tiers)


# ---------------------------------------------------------------------------
# Purity / layering
# ---------------------------------------------------------------------------

class TestPurity:
    def test_intent_surface_lives_in_agent_package(self):
        assert (_REPO_ROOT / "agent" / "intent.py").is_file()

    def test_orchestrator_does_not_import_intent_or_agent(self):
        orch = _REPO_ROOT / "orchestrator"
        src = "\n".join(
            f.read_text(encoding="utf-8") for f in sorted(orch.rglob("*.py"))
        )
        assert "agent.intent" not in src and "from agent" not in src and \
            "import agent" not in src, (
            "orchestrator/ must not import agent/ (layer-separation invariant)."
        )

    def test_intent_does_not_import_anthropic_or_sap_or_sdk(self):
        src = (_REPO_ROOT / "agent" / "intent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        joined = " ".join(imported)
        assert "anthropic" not in joined, "intent surface must not import anthropic."
        assert "claude_agent_sdk" not in joined, "intent surface holds no SDK."
        assert "requests" not in joined and "httpx" not in joined, (
            "intent surface must not import a network client (hermetic)."
        )
