"""
tests/test_agent_registry.py — T-1, T-2, T-6: registry tier lookup and tool-set invariants.

No SDK, no SAP, no network. All assertions are against the in-process registry.
"""
from __future__ import annotations

import pytest

from agent.schemas import Tier
from agent.registry import REGISTRY, get_tier, allowed_tools


# ---------------------------------------------------------------------------
# T-1  Known Tier-0 and Tier-1 tools resolve correct tiers
# ---------------------------------------------------------------------------

class TestKnownTierResolution:
    TIER_ZERO_TOOLS = [
        "read_sap_invoices",
        "read_sap_purchase_invoices",
        "read_ledger",
        "read_kb_slice",
    ]
    TIER_ONE_TOOLS = [
        "run_review_chain",
        "run_reg2627_pass",
        "draft_report_section",
        "propose_action",
    ]

    @pytest.mark.parametrize("name", TIER_ZERO_TOOLS)
    def test_tier_zero_tools_resolve(self, name):
        assert get_tier(name) == Tier.ZERO

    @pytest.mark.parametrize("name", TIER_ONE_TOOLS)
    def test_tier_one_tools_resolve(self, name):
        assert get_tier(name) == Tier.ONE

    def test_all_registered_tools_have_valid_tier(self):
        for spec in REGISTRY.values():
            assert spec.tier in (Tier.ZERO, Tier.ONE), (
                f"{spec.name!r} has unexpected tier {spec.tier}"
            )


# ---------------------------------------------------------------------------
# T-2  Forbidden / unknown tool → Tier.THREE (tool-not-found)
# ---------------------------------------------------------------------------

class TestForbiddenUnknownTool:
    def test_unknown_tool_returns_tier_three(self):
        assert get_tier("nonexistent_tool") == Tier.THREE

    def test_sap_write_tool_absent(self):
        # SAP write tools must be absent from the registry, not denied
        for sap_write in ("create_invoice", "patch_invoice", "delete_invoice",
                          "sap_write", "write_sap"):
            assert get_tier(sap_write) == Tier.THREE, (
                f"{sap_write!r} should be absent (Tier 3 by absence)"
            )

    def test_git_tool_absent(self):
        for git_op in ("git_push", "git_commit", "git_write"):
            assert get_tier(git_op) == Tier.THREE

    def test_iras_filing_tool_absent(self):
        assert get_tier("file_iras_return") == Tier.THREE

    def test_empty_string_tool_absent(self):
        assert get_tier("") == Tier.THREE


# ---------------------------------------------------------------------------
# T-6  Registry contains NO Tier-2-executing tool; propose_action is Tier 1
# ---------------------------------------------------------------------------

class TestNoTierTwoExecutor:
    def test_no_tier_two_tool_in_registry(self):
        """The agent registry must never contain a Tier-2-executing tool.

        The only path to Tier-2 effects is propose_action (Tier 1) → human
        approves → deterministic executor fires. The agent never executes
        Tier 2 itself, even after approval.
        """
        for spec in REGISTRY.values():
            assert spec.tier != Tier.TWO, (
                f"{spec.name!r} is registered at Tier 2 — this violates the "
                "invariant that the agent never holds a Tier-2-executing tool"
            )

    def test_propose_action_is_tier_one(self):
        """propose_action must be Tier 1 — agent emits proposal, executor fires on approval."""
        assert get_tier("propose_action") == Tier.ONE

    def test_allowed_tools_excludes_tier_two(self):
        tools = allowed_tools()
        tiers = {spec.tier for spec in tools}
        assert Tier.TWO not in tiers

    def test_allowed_tools_excludes_tier_three(self):
        tools = allowed_tools()
        tiers = {spec.tier for spec in tools}
        assert Tier.THREE not in tiers
