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

from typing import TYPE_CHECKING, Any, Optional

from agent.budget import RunBudget
from agent.hooks import make_hooks
from agent.ledger import Ledger
from agent.registry import allowed_tools

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions, McpSdkServerConfig  # noqa: PLC0415


def build_options(
    ledger: Ledger,
    budget: RunBudget,
    *,
    system_prompt: str = "",
    engine_server: "Optional[McpSdkServerConfig]" = None,
    attach_hooks: bool = True,
) -> "ClaudeAgentOptions":
    """Assemble and return a ClaudeAgentOptions instance for one agent run.

    Args:
        ledger:        The Ledger instance hooks will write permission decisions into.
        budget:        RunBudget; max_turns maps to ClaudeAgentOptions.max_turns.
        system_prompt: Optional system prompt string.  Passed as-is to the SDK;
                       the T5.3 caller is expected to supply the domain-specific
                       audit-agent instructions here.
        engine_server: Optional in-process MCP server (from
                       agent.engine_tool.make_engine_server) exposing the single
                       atomic engine tool.  When provided, it is wired into
                       mcp_servers and its qualified tool name
                       (mcp__engine__run_review_chain) is appended to
                       allowed_tools.  When None (default) no engine tool is
                       wired — build_options behaviour is unchanged.
        attach_hooks:  When True (default) the PreToolUse/PostToolUse ledger hooks
                       are wired — unchanged behaviour for every existing caller.
                       When False the returned options carry NO hooks
                       (``hooks=None``); make_hooks is not called.  This is for
                       the live case-file loop, whose plain-Python driver is the
                       SOLE gate (it justification-gates and executes Tier-0 reads
                       itself) — attaching the SDK hooks too would double-write the
                       ledger and muddy the COGS / sealed-chain accounting.

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

    tool_names = [spec.name for spec in allowed_tools()]

    mcp_servers: dict[str, Any] = {}
    if engine_server is not None:
        # Wire the single atomic engine tool. Its MCP-namespaced name is added to
        # allowed_tools; the registry's MCP-aware get_tier resolves it to Tier 1.
        from agent.engine_tool import (  # noqa: PLC0415
            ENGINE_SERVER_NAME,
            ENGINE_TOOL_QUALIFIED,
        )
        mcp_servers[ENGINE_SERVER_NAME] = engine_server
        tool_names.append(ENGINE_TOOL_QUALIFIED)

    # Hooks are wired only when requested. The hook-free path (attach_hooks=False)
    # leaves the ledger untouched here — the live loop's driver is the sole gate.
    hooks_arg = None
    if attach_hooks:
        pre_cb, post_cb, _audit_log = make_hooks(ledger)
        hooks_arg = {
            "PreToolUse": [HookMatcher(hooks=[pre_cb])],
            "PostToolUse": [HookMatcher(hooks=[post_cb])],
        }

    return ClaudeAgentOptions(
        allowed_tools=tool_names,
        mcp_servers=mcp_servers,
        hooks=hooks_arg,
        max_turns=budget.max_turns,
        system_prompt=system_prompt or None,
    )
