"""
agent/harness.py — Assembles ClaudeAgentOptions for the Tier-5 cage.

Public API:
    build_options(ledger, budget, *, system_prompt="") -> ClaudeAgentOptions

Wires:
    - allowed_tools  : Tier-0 + Tier-1 tool names from registry (no Tier-2/3)
    - hooks          : PreToolUse + PostToolUse callbacks from agent.hooks
    - max_turns      : budget.max_turns
    - system_prompt  : caller-supplied string (empty default)

Does NOT run a live query.  The claude_agent_sdk import is DEFERRED inside
build_options() so agent/ is importable without the SDK installed (pure-core
test environments).  # noqa: PLC0415 marks the deferred import site.

Zero live model. Zero live SAP. Zero network I/O.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.budget import RunBudget
from agent.hooks import make_hooks
from agent.ledger import Ledger
from agent.registry import allowed_tools

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions  # noqa: PLC0415


def build_options(
    ledger: Ledger,
    budget: RunBudget,
    *,
    system_prompt: str = "",
) -> "ClaudeAgentOptions":
    """Assemble and return a ClaudeAgentOptions instance for one agent run.

    Args:
        ledger:        The Ledger instance hooks will write permission decisions into.
        budget:        RunBudget; max_turns maps to ClaudeAgentOptions.max_turns.
        system_prompt: Optional system prompt string.  Passed as-is to the SDK;
                       the T5.3 caller is expected to supply the domain-specific
                       audit-agent instructions here.

    Returns:
        ClaudeAgentOptions with:
            allowed_tools  = Tier-0 + Tier-1 tool names (from registry)
            hooks          = {PreToolUse: [HookMatcher(hooks=[pre_cb])],
                              PostToolUse: [HookMatcher(hooks=[post_cb])]}
            max_turns      = budget.max_turns
            system_prompt  = system_prompt (or None when empty)

    Note:
        build_options does NOT call query().  Call it in the T5.3 agent loop:
            options = build_options(ledger, budget, system_prompt=PROMPT)
            async for msg in query(prompt=..., options=options):
                ...
    """
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher  # noqa: PLC0415

    pre_cb, post_cb, _audit_log = make_hooks(ledger)

    tool_names = [spec.name for spec in allowed_tools()]

    return ClaudeAgentOptions(
        allowed_tools=tool_names,
        hooks={
            "PreToolUse": [HookMatcher(hooks=[pre_cb])],
            "PostToolUse": [HookMatcher(hooks=[post_cb])],
        },
        max_turns=budget.max_turns,
        system_prompt=system_prompt or None,
    )
