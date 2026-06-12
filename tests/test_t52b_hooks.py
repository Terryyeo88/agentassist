"""
tests/test_t52b_hooks.py — T-1…T-4, T-8: hooks, harness, ledger ordering.

All hermetic: synthetic hook events + mocked SDK. No live model, no live SAP,
no network.

T-1  PreToolUse on an unknown/forbidden tool → deny "tool-not-found"
T-2  PreToolUse on a Tier-1 tool with missing/trivial justification → deny
T-3  PreToolUse on a Tier-1 tool with valid justification → allow AND ledger
     entry appended BEFORE allow (ordering invariant)
T-4  PreToolUse on a Tier-0 tool → allow; PostToolUse logs the call
T-8  Mocked-SDK loop wiring: build_options + direct hook invocation drives a
     scripted sequence and produces expected ledger+allow/deny outcomes in order
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent.ledger import Ledger
from agent.schemas import Tier
from agent.budget import RunBudget


# ---------------------------------------------------------------------------
# Helpers: synthetic hook input constructors
# ---------------------------------------------------------------------------

def _pre(tool_name: str, tool_input: dict | None = None) -> dict[str, Any]:
    """Build a minimal PreToolUseHookInput dict."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "tool_use_id": "test-uid-001",
        "session_id": "test-session",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/tmp",
    }


def _post(tool_name: str, tool_input: dict | None = None,
          tool_response: Any = "ok") -> dict[str, Any]:
    """Build a minimal PostToolUseHookInput dict."""
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "tool_response": tool_response,
        "tool_use_id": "test-uid-001",
        "session_id": "test-session",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/tmp",
    }


_CONTEXT = {"signal": None}


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# T-1: unknown tool → deny "tool-not-found"
# ---------------------------------------------------------------------------

class TestT1UnknownToolDenied:
    def test_unknown_tool_returns_deny(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, _post_cb, _audit_log = make_hooks(ledger)

        result = _run(pre_cb(_pre("totally_unknown_tool"), "uid-1", _CONTEXT))

        specific = result["hookSpecificOutput"]
        assert specific["hookEventName"] == "PreToolUse"
        assert specific["permissionDecision"] == "deny"
        assert "tool-not-found" in specific.get("permissionDecisionReason", "").lower()

    def test_unknown_tool_ledger_entry_blocked(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, _post_cb, _audit_log = make_hooks(ledger)

        _run(pre_cb(_pre("totally_unknown_tool"), "uid-1", _CONTEXT))

        assert len(ledger.entries) == 1
        entry = ledger.entries[0]
        assert entry.outcome == "blocked"
        assert entry.tool_name == "totally_unknown_tool"
        assert entry.blocked_reason is not None
        assert "tool-not-found" in entry.blocked_reason.lower()

    def test_unknown_tool_ledger_chain_valid(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, _post_cb, _audit_log = make_hooks(ledger)
        _run(pre_cb(_pre("ghost_tool"), "uid-1", _CONTEXT))
        ledger.verify()  # must not raise


# ---------------------------------------------------------------------------
# T-2: Tier-1 tool, missing or trivial justification → deny
# ---------------------------------------------------------------------------

class TestT2Tier1BadJustification:
    @pytest.mark.parametrize("justification", [
        None,
        "",
        "   ",
        "too short",   # < 20 chars
        "x" * 19,      # exactly 19 chars — still too short
    ])
    def test_missing_trivial_justification_denied(self, justification):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, _post_cb, _audit_log = make_hooks(ledger)
        tool_input = {} if justification is None else {"justification": justification}

        result = _run(pre_cb(_pre("run_review_chain", tool_input), "uid-2", _CONTEXT))

        specific = result["hookSpecificOutput"]
        assert specific["permissionDecision"] == "deny"
        assert specific.get("permissionDecisionReason")

    def test_trivial_justification_ledger_blocked(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, _post_cb, _audit_log = make_hooks(ledger)
        _run(pre_cb(_pre("run_review_chain", {"justification": "bad"}), "uid-2", _CONTEXT))

        assert len(ledger.entries) == 1
        assert ledger.entries[0].outcome == "blocked"


# ---------------------------------------------------------------------------
# T-3: Tier-1 tool with valid justification → allow + ledger appended BEFORE
# ---------------------------------------------------------------------------

class TestT3Tier1ValidJustification:
    GOOD_JUSTIFICATION = "Audit period Q3 2024: running review chain to classify all invoices above threshold per IRAS ASK Step 1.3."

    def test_valid_justification_allowed(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, _post_cb, _audit_log = make_hooks(ledger)
        result = _run(pre_cb(
            _pre("run_review_chain", {"justification": self.GOOD_JUSTIFICATION}),
            "uid-3", _CONTEXT,
        ))

        specific = result["hookSpecificOutput"]
        assert specific["permissionDecision"] == "allow"

    def test_valid_justification_ledger_entry_before_return(self):
        """The ledger entry is appended BEFORE the hook returns 'allow'."""
        from agent.hooks import make_hooks

        ledger = Ledger()
        ledger_len_at_hook_return: list[int] = []

        # Wrap pre_cb to capture ledger length at the moment the result is produced
        original_pre_cb = None

        async def observing_pre(inp, uid, ctx):
            nonlocal original_pre_cb
            result = await original_pre_cb(inp, uid, ctx)
            ledger_len_at_hook_return.append(len(ledger.entries))
            return result

        pre_cb, _post_cb, _audit_log = make_hooks(ledger)
        original_pre_cb = pre_cb

        _run(observing_pre(
            _pre("run_review_chain", {"justification": self.GOOD_JUSTIFICATION}),
            "uid-3", _CONTEXT,
        ))

        # Ledger MUST have been written by the time the hook returns
        assert len(ledger.entries) == 1
        assert ledger_len_at_hook_return[0] == 1
        assert ledger.entries[0].outcome == "allowed"

    def test_valid_justification_ledger_chain_valid(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, _post_cb, _audit_log = make_hooks(ledger)
        _run(pre_cb(
            _pre("run_review_chain", {"justification": self.GOOD_JUSTIFICATION}),
            "uid-3", _CONTEXT,
        ))
        ledger.verify()


# ---------------------------------------------------------------------------
# T-4: Tier-0 tool → allow; PostToolUse logs the call
# ---------------------------------------------------------------------------

class TestT4Tier0AndPostToolUse:
    def test_tier0_pre_allowed(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, _post_cb, _audit_log = make_hooks(ledger)
        result = _run(pre_cb(_pre("read_sap_invoices"), "uid-4", _CONTEXT))

        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_tier0_pre_ledger_allowed_entry(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, _post_cb, _audit_log = make_hooks(ledger)
        _run(pre_cb(_pre("read_sap_invoices"), "uid-4", _CONTEXT))

        assert len(ledger.entries) == 1
        assert ledger.entries[0].outcome == "allowed"
        assert ledger.entries[0].tier == Tier.ZERO.value

    def test_post_tool_use_logs_to_audit(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, post_cb, audit_log = make_hooks(ledger)

        # First fire PreToolUse to simulate the allow path
        _run(pre_cb(_pre("read_sap_invoices"), "uid-4", _CONTEXT))
        assert len(audit_log) == 0  # pre doesn't write to audit_log

        # Then fire PostToolUse
        _run(post_cb(_post("read_sap_invoices", tool_response={"rows": []}), "uid-4", _CONTEXT))

        assert len(audit_log) == 1
        entry = audit_log[0]
        assert entry["tool_name"] == "read_sap_invoices"

    def test_post_tool_use_returns_valid_shape(self):
        from agent.hooks import make_hooks

        ledger = Ledger()
        pre_cb, post_cb, audit_log = make_hooks(ledger)
        result = _run(post_cb(_post("read_sap_invoices"), "uid-4", _CONTEXT))

        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


# ---------------------------------------------------------------------------
# T-8: Mocked-SDK loop wiring — build_options + direct hook invocation
# ---------------------------------------------------------------------------

class TestT8MockedSDKLoop:
    """
    Scripted sequence through build_options hooks without a live model or SDK subprocess.
    Flow:
      1. Tier-0 read_sap_invoices → allow + ledger[0] allowed
      2. PostToolUse for read_sap_invoices → audit_log[0]
      3. Tier-1 run_review_chain with valid justification → allow + ledger[1] allowed
      4. Tier-1 run_review_chain with trivial justification → deny + ledger[2] blocked
      5. Unknown tool → deny + ledger[3] blocked
    Assert ordering: ledger entries appear in the above sequence.
    """

    GOOD_JUST = "Running full review chain for Q3 2024 per IRAS ASK audit protocol engagement step 1.3."

    def test_loop_wiring_sequence(self):
        from agent.harness import build_options

        ledger = Ledger()
        budget = RunBudget(max_turns=20, max_cost_usd=1.0)
        options = build_options(ledger, budget, system_prompt="You are an audit agent.")

        # Extract hooks from options
        assert "PreToolUse" in options.hooks
        assert "PostToolUse" in options.hooks
        pre_matchers = options.hooks["PreToolUse"]
        post_matchers = options.hooks["PostToolUse"]
        assert len(pre_matchers) >= 1
        assert len(pre_matchers[0].hooks) >= 1
        pre_cb = pre_matchers[0].hooks[0]
        post_cb = post_matchers[0].hooks[0]

        # Step 1: Tier-0 allow
        r1 = _run(pre_cb(_pre("read_sap_invoices"), "u1", _CONTEXT))
        assert r1["hookSpecificOutput"]["permissionDecision"] == "allow"

        # Step 2: PostToolUse
        _run(post_cb(_post("read_sap_invoices"), "u1", _CONTEXT))

        # Step 3: Tier-1 valid justification → allow
        r3 = _run(pre_cb(_pre("run_review_chain", {"justification": self.GOOD_JUST}), "u3", _CONTEXT))
        assert r3["hookSpecificOutput"]["permissionDecision"] == "allow"

        # Step 4: Tier-1 trivial justification → deny
        r4 = _run(pre_cb(_pre("run_review_chain", {"justification": "x"}), "u4", _CONTEXT))
        assert r4["hookSpecificOutput"]["permissionDecision"] == "deny"

        # Step 5: Unknown tool → deny
        r5 = _run(pre_cb(_pre("__nonexistent__"), "u5", _CONTEXT))
        assert r5["hookSpecificOutput"]["permissionDecision"] == "deny"

        # Ledger ordering: 3 pre-tool entries (step 1, 3, 4, 5); PostToolUse goes to audit_log
        assert len(ledger.entries) == 4
        assert ledger.entries[0].tool_name == "read_sap_invoices"
        assert ledger.entries[0].outcome == "allowed"
        assert ledger.entries[1].tool_name == "run_review_chain"
        assert ledger.entries[1].outcome == "allowed"
        assert ledger.entries[2].tool_name == "run_review_chain"
        assert ledger.entries[2].outcome == "blocked"
        assert ledger.entries[3].tool_name == "__nonexistent__"
        assert ledger.entries[3].outcome == "blocked"

        # Chain must verify throughout
        ledger.verify()

    def test_allowed_tools_in_options(self):
        """allowed_tools in options contains only Tier-0/1 names (T-5 coverage)."""
        from agent.harness import build_options
        from agent.registry import REGISTRY
        from agent.schemas import Tier

        ledger = Ledger()
        budget = RunBudget(max_turns=5, max_cost_usd=0.5)
        options = build_options(ledger, budget)

        # All names in options.allowed_tools must be in REGISTRY and Tier 0 or 1
        for name in options.allowed_tools:
            assert name in REGISTRY, f"{name!r} not in REGISTRY"
            assert REGISTRY[name].tier in (Tier.ZERO, Tier.ONE), (
                f"{name!r} is Tier {REGISTRY[name].tier}, expected 0 or 1"
            )

    def test_max_turns_wired_from_budget(self):
        from agent.harness import build_options

        ledger = Ledger()
        budget = RunBudget(max_turns=7, max_cost_usd=0.5)
        options = build_options(ledger, budget)

        assert options.max_turns == 7
