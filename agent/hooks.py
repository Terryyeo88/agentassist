"""
agent/hooks.py — SDK PreToolUse / PostToolUse hook callbacks for the Tier-5 cage.

Public API:
    make_hooks(ledger) -> (pre_tool_use_cb, post_tool_use_cb, audit_log)

The returned callbacks implement the HookCallback protocol from claude_agent_sdk.
They are plain async functions; the SDK import is NOT required to call them —
input and output are plain dicts (TypedDicts are dicts at runtime).

PreToolUse gate logic:
    Tier.THREE (unknown tool) → deny "tool-not-found"; ledger entry blocked.
    Tier.ONE  → validate_justification (writes ledger BEFORE return); allow or deny.
    Tier.ZERO → validate_justification (writes ledger BEFORE return); always allow.

PostToolUse:
    Appends to audit_log (a plain list[dict]).  The audit_log is SEPARATE from the
    hash-chained ledger.  The ledger records permission decisions; the audit_log
    records execution outcomes.  Whether execution outcomes belong in the sealed
    chain is a T5.3 decision — flagged here per approved design note.

SDK import is deferred (lazy) inside the function body so agent/ is importable
without claude_agent_sdk present (e.g. in the pure-core test environment).
The # noqa: PLC0415 comments mark each deferred import site explicitly.

Zero live model. Zero live SAP. Zero network I/O.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.justification import validate_justification
from agent.ledger import Ledger
from agent.registry import get_tier
from agent.schemas import Tier

if TYPE_CHECKING:
    from claude_agent_sdk.types import HookContext, HookJSONOutput, HookInput  # noqa: PLC0415


def make_hooks(
    ledger: Ledger,
) -> tuple[Any, Any, list[dict]]:
    """Build (pre_tool_use_cb, post_tool_use_cb, audit_log) bound to *ledger*.

    Args:
        ledger: The Ledger instance to write permission decisions into.

    Returns:
        A tuple of:
            pre_tool_use_cb  — async HookCallback for PreToolUse events
            post_tool_use_cb — async HookCallback for PostToolUse events
            audit_log        — mutable list populated by post_tool_use_cb;
                               each entry is a plain dict with tool_name,
                               tool_input, tool_response, tool_use_id.

    SEALED-CHAIN ROUTING (locked, T5.3):
        audit_log entries are NOT part of the hash-chained ledger.  PostToolUse
        records Tier-0 routine reads (and Tier-1 staging work) here, UNSEALED.
        Tier-2 outcome-bearing executions (seal/emit, post human approval) are
        the ONLY execution outcomes that append to the SEALED hash-chained
        agent-ledger — and that happens in the executor (agent/executor.py::
        make_tier2_handlers), not in this PostToolUse hook (the agent never
        invokes a Tier-2 tool; none exist in the registry).
    """
    audit_log: list[dict] = []

    async def pre_tool_use(
        input: dict[str, Any],
        tool_use_id: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """PreToolUse gate: tier check + justification gate + ledger write."""
        tool_name: str = input["tool_name"]
        tool_input: dict[str, Any] = input.get("tool_input") or {}

        tier = get_tier(tool_name)

        if tier == Tier.THREE:
            # Structurally impossible tool — not in registry.  Write blocked
            # entry directly (validate_justification only handles Tier 0/1).
            blocked_reason = f"tool-not-found: {tool_name!r} is not in the agent registry"
            ledger.append(
                tool_name=tool_name,
                tier=tier,
                justification=None,
                call_params=tool_input,
                outcome="blocked",
                blocked_reason=blocked_reason,
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": blocked_reason,
                }
            }

        # Tier 0 or Tier 1 — delegate to the justification gate.
        # validate_justification writes the ledger entry BEFORE returning.
        justification: str | None = tool_input.get("justification")
        result = validate_justification(
            justification,
            tier,
            tool_name=tool_name,
            call_params=tool_input,
            ledger=ledger,
        )

        if not result.allowed:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": result.blocked_reason,
                }
            }

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }

    async def post_tool_use(
        input: dict[str, Any],
        tool_use_id: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """PostToolUse audit: log execution to audit_log (NOT the sealed ledger).

        Locked routing (T5.3): Tier-0 routine reads (and Tier-1 staging work)
        record their execution here in the separate, UNSEALED audit_log. Only
        Tier-2 post-approval executions append to the sealed hash-chained ledger,
        and that is done by the executor — never by this hook.
        """
        audit_log.append({
            "tool_name": input["tool_name"],
            "tool_input": input.get("tool_input") or {},
            "tool_response": input.get("tool_response"),
            "tool_use_id": tool_use_id or input.get("tool_use_id"),
        })
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
            }
        }

    return pre_tool_use, post_tool_use, audit_log
