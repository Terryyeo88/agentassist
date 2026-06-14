"""
agent/engine_tool.py — Engine seam exposed to the agent as ONE atomic MCP tool.

T5.3 Slice 1 (plumbing). Bridges engine.review.review() into the agent cage as a
single in-process MCP tool. The agent invokes the whole review pipeline; it can
NEVER reach run_chain / gates / seal_bundle internals — there is no sub-step tool.

Public API:
    serialise_review_result(result) -> dict   — JSON-safe ReviewResult dict
    make_engine_tool(invoke_review) -> SdkMcpTool
    make_engine_server(invoke_review) -> McpSdkServerConfig
    ENGINE_SERVER_NAME / ENGINE_TOOL_NAME / ENGINE_TOOL_QUALIFIED

Naming: the engine tool realises the existing Tier-1 `run_review_chain` registry
contract. Exposed via the SDK as `mcp__engine__run_review_chain`; the registry's
MCP-aware get_tier() resolves that back to Tier 1 so the justification gate
applies (the agent must justify invoking the chain).

The SDK import is DEFERRED inside the factory functions so agent/ stays importable
without claude-agent-sdk present (pure-core test environments). engine/ is never
imported at module top either — only inside the bound invoker the caller supplies.

Zero SDK at import. Zero live SAP. Zero network I/O.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool
    from engine.review import ReviewResult

# Canonical names. The engine tool is the realisation of the Tier-1
# `run_review_chain` registry entry — same contract, exposed over MCP.
ENGINE_SERVER_NAME: str = "engine"
ENGINE_TOOL_NAME: str = "run_review_chain"
ENGINE_TOOL_QUALIFIED: str = f"mcp__{ENGINE_SERVER_NAME}__{ENGINE_TOOL_NAME}"

# Input schema for the atomic tool. `justification` is consumed by the PreToolUse
# justification gate (Tier-1 contract); the handler itself runs the whole pipeline.
_ENGINE_TOOL_INPUT_SCHEMA: dict[str, Any] = {"justification": str}

_ENGINE_TOOL_DESCRIPTION: str = (
    "Invoke the full deterministic GST review pipeline as ONE atomic tool "
    "(fetch -> classify -> calculate -> detect -> compile -> report -> seal, all "
    "gates included). Returns a serialised ReviewResult. The agent cannot reach "
    "any sub-step; this is the only engine entry point. Justification required."
)


def serialise_review_result(result: "ReviewResult") -> dict:
    """Return a JSON-safe dict for a ReviewResult.

    Path fields are stringified; the GateHalt (a dataclass) is flattened. All
    other fields are already plain JSON-friendly values produced by the engine.
    """
    def _p(p: Any) -> str | None:
        return str(p) if p is not None else None

    gate_failure: dict | None = None
    if result.gate_failure is not None:
        gate_failure = {
            "message": result.gate_failure.message,
            "checked": result.gate_failure.checked,
        }

    return {
        "status": result.status,
        "compile_output": result.compile_output,
        "gate_results": result.gate_results,
        "reasoning_artefact": result.reasoning_artefact,
        "document_candidates": result.document_candidates,
        "analytical_review_data": result.analytical_review_data,
        "report_pdf_path": _p(result.report_pdf_path),
        "bundle_dir": _p(result.bundle_dir),
        "run_started_at": result.run_started_at,
        "run_completed_at": result.run_completed_at,
        "gate_failure": gate_failure,
    }


def make_engine_tool(invoke_review: Callable[[], "ReviewResult"]) -> "SdkMcpTool":
    """Build the single atomic engine MCP tool bound to *invoke_review*.

    Args:
        invoke_review: Zero-arg callable returning a ReviewResult. The caller
                       binds client_config + ReviewInputs server-side; the agent
                       never supplies them, preserving atomicity and keeping
                       write-bearing inputs out of the model's reach.

    Returns:
        An SdkMcpTool named ENGINE_TOOL_NAME whose handler runs the whole
        pipeline and returns the serialised ReviewResult as MCP text content.
    """
    from claude_agent_sdk import tool  # noqa: PLC0415 - deferred SDK import

    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        result = invoke_review()
        payload = serialise_review_result(result)
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    return tool(ENGINE_TOOL_NAME, _ENGINE_TOOL_DESCRIPTION, _ENGINE_TOOL_INPUT_SCHEMA)(_handler)


def make_engine_server(invoke_review: Callable[[], "ReviewResult"]) -> "McpSdkServerConfig":
    """Build an in-process MCP server exposing exactly the one atomic engine tool."""
    from claude_agent_sdk import create_sdk_mcp_server  # noqa: PLC0415 - deferred SDK import

    return create_sdk_mcp_server(
        name=ENGINE_SERVER_NAME,
        version="1.0.0",
        tools=[make_engine_tool(invoke_review)],
    )
