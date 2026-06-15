"""
tests/test_t53d_hookfree_options.py — T5.3d: hook-free build_options option.

`build_options(..., attach_hooks=False)` returns ClaudeAgentOptions with NO
PreToolUse/PostToolUse hooks, so the live case-file loop's driver is the SOLE gate
(the ledger does not double-write: driver gate + SDK hook). The default
(`attach_hooks=True`) is unchanged — every existing caller stays byte-identical.

Hermetic: build_options assembles options only; it never calls query(). No live
model, no binary, no tokens.
"""
from __future__ import annotations

from agent.budget import RunBudget
from agent.harness import build_options
from agent.ledger import Ledger
from agent.registry import REGISTRY


def _ledger_budget():
    return Ledger(), RunBudget(max_turns=5, max_cost_usd=0.5)


def test_attach_hooks_false_yields_no_hooks():
    ledger, budget = _ledger_budget()
    options = build_options(ledger, budget, attach_hooks=False)
    # SDK-canonical "no hooks" is None (ClaudeAgentOptions.hooks default).
    assert options.hooks is None


def test_default_keeps_both_hooks_present():
    ledger, budget = _ledger_budget()
    options = build_options(ledger, budget)  # default attach_hooks=True
    assert options.hooks is not None
    assert "PreToolUse" in options.hooks
    assert "PostToolUse" in options.hooks
    assert len(options.hooks["PreToolUse"][0].hooks) >= 1
    assert len(options.hooks["PostToolUse"][0].hooks) >= 1


def test_attach_hooks_true_explicit_matches_default():
    ledger, budget = _ledger_budget()
    options = build_options(ledger, budget, attach_hooks=True)
    assert "PreToolUse" in options.hooks
    assert "PostToolUse" in options.hooks


def test_hookfree_options_still_populate_tools_and_turns():
    # The hook-free path changes ONLY hooks — everything else is unchanged.
    ledger, budget = _ledger_budget()
    options = build_options(ledger, budget, attach_hooks=False)
    assert options.max_turns == 5
    assert options.allowed_tools  # non-empty
    for name in options.allowed_tools:
        assert name in REGISTRY


def test_attach_hooks_is_keyword_only():
    # Must be keyword-only so existing positional callers cannot be reordered.
    ledger, budget = _ledger_budget()
    try:
        build_options(ledger, budget, "sys-prompt", None, False)  # positional 5th arg
    except TypeError:
        return
    raise AssertionError("attach_hooks should be keyword-only (positional call must fail)")
