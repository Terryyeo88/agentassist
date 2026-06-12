"""
tests/test_t52b_registry.py — T-5: allowed_tools feeds harness with Tier-0/1 only.

Hermetic. No SDK, no SAP, no network.

T-5  allowed_tools() contains ONLY Tier-0 and Tier-1 names; no Tier-2-executing
     tool and no Tier-3 tool is exposed.
"""
from __future__ import annotations

import pytest

from agent.registry import REGISTRY, allowed_tools
from agent.schemas import Tier


class TestT5AllowedToolsSet:
    def test_all_allowed_tools_are_tier_0_or_1(self):
        for spec in allowed_tools():
            assert spec.tier in (Tier.ZERO, Tier.ONE), (
                f"allowed_tools() returned Tier-{spec.tier} tool: {spec.name!r}"
            )

    def test_no_tier2_tool_in_registry(self):
        for spec in REGISTRY.values():
            assert spec.tier != Tier.TWO, (
                f"REGISTRY contains a Tier-2 tool: {spec.name!r} — "
                "Tier-2 is structurally impossible in the registry"
            )

    def test_no_tier3_tool_in_registry(self):
        for spec in REGISTRY.values():
            assert spec.tier != Tier.THREE, (
                f"REGISTRY contains a Tier-3 tool: {spec.name!r}"
            )

    def test_propose_action_is_tier1_not_tier2(self):
        """propose_action is the ONLY path to Tier-2 effects, but it is itself Tier-1."""
        spec = REGISTRY.get("propose_action")
        assert spec is not None
        assert spec.tier == Tier.ONE

    def test_allowed_tools_names_match_registry(self):
        allowed_names = {spec.name for spec in allowed_tools()}
        registry_t01 = {
            name for name, spec in REGISTRY.items()
            if spec.tier in (Tier.ZERO, Tier.ONE)
        }
        assert allowed_names == registry_t01

    def test_harness_allowed_tools_strings_are_registry_names(self):
        """Harness extracts plain strings from ToolSpec.name — same set as registry."""
        from agent.harness import build_options
        from agent.ledger import Ledger
        from agent.budget import RunBudget

        ledger = Ledger()
        budget = RunBudget(max_turns=5, max_cost_usd=0.5)
        options = build_options(ledger, budget)

        allowed_names = {spec.name for spec in allowed_tools()}
        assert set(options.allowed_tools) == allowed_names
