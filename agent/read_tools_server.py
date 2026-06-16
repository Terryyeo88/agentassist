"""
agent/read_tools_server.py — the three Tier-0 reads exposed as MCP tools.

Architecture A foundation (T5.3e). The T5.3-probe proved that ``allowed_tools`` is a
permission FILTER, not a tool definition — a tool enters the live model's schema only
via MCP. The three Tier-0 dossier reads (`get_source_document`, `read_vendor_gst_status`,
`read_prior_period_treatment`) were registry entries by NAME only, so a live model could
never call them. This module backs them with MCP ``@tool`` handlers so the model CAN call
them and receive evidence in-turn.

``make_read_tools_server(ctx, evidence_sink)`` mirrors ``agent/engine_tool.py``:
  * each handler reuses the existing ``agent/read_tools.py`` read function (read logic is
    NOT reimplemented) against the ``ctx``-bound source — the model supplies only the
    lookup key + ``evidence_slot``, never the source, so it cannot re-point a read at a
    different client/store (ctx is closure-bound, like ``invoke_review`` binds config);
  * the result is recorded into ``evidence_sink`` keyed by ``evidence_slot`` (or, with no
    slot, under the tool name via ``setdefault`` — mirroring ``loop._run_finding``), the
    seam the loop-rewire will read in-turn-gathered evidence from;
  * the result is returned to the model as MCP text content; a source miss (``None`` /
    ``found=False``) is surfaced as a structured ``found: False`` payload, not an error.

RELAY/OBSERVE-ONLY: the handlers READ via ctx and return evidence — they write nothing,
mutate no source, seal/emit nothing, add no Tier-2 surface. The namespaced names
(`mcp__reads__<name>`) resolve to Tier 0 via the registry's ``_strip_mcp_prefix`` +
``get_tier``, so the existing PreToolUse hook gates them as Tier-0 reads (allow + ledger).
Architecture A uses HOOK-BEARING options (the T5.3d hook-free path is not used here).

SCOPE: this is the reads SERVER only. ``run_casefile_loop`` is NOT yet rewired to consume
``evidence_sink`` in-turn (the between-turns ``_execute_read`` path still stands) — that is
the follow-on loop-rewire build, then the live T5.3-V run.

The SDK import is DEFERRED inside the factory functions (mirroring ``engine_tool.py``), so
``agent/`` stays importable without the SDK; ``agent/__init__`` does not import this module.

Zero SDK at import. Zero writes. Zero network beyond whatever the injected provider does.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agent.completeness import READ_TOOL_SLOT
from agent.read_tools import (
    get_source_document,
    read_prior_period_treatment,
    read_vendor_gst_status,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool

    from agent.loop import LoopContext

#: In-process MCP server name. The three reads are exposed as mcp__reads__<bare-name>;
#: the registry's MCP-aware get_tier() resolves each back to its Tier-0 registry entry.
READS_SERVER_NAME: str = "reads"

#: Bare tool names (== the Tier-0 registry entries they realise).
READ_TOOL_NAMES: tuple[str, ...] = (
    "get_source_document",
    "read_vendor_gst_status",
    "read_prior_period_treatment",
)

#: Qualified names to append to allowed_tools when the server is wired.
READ_TOOLS_QUALIFIED: tuple[str, ...] = tuple(
    f"mcp__{READS_SERVER_NAME}__{n}" for n in READ_TOOL_NAMES
)

#: bare read name -> SDK-facing qualified name, DERIVED from the shipping
#: READ_TOOLS_QUALIFIED constant (not re-formatted) so the two cannot drift.
_QUALIFIED_BY_BARE: dict[str, str] = dict(zip(READ_TOOL_NAMES, READ_TOOLS_QUALIFIED))


def qualified_read_name(bare_name: str) -> str:
    """The SDK-facing MCP name a Tier-0 read is LEDGERED under (``mcp__reads__<bare>``).

    On the live path the SDK delivers this namespaced name to the PreToolUse hook,
    which records it verbatim (see round-2 ledger.json). The hermetic gather-fakes bind
    against THIS helper so their ledger entries match production. It is the single
    source of truth for the read-name namespace, mirroring how ``canonical_slot`` is the
    SSOT for slots — and slot lookups continue to resolve on the BARE name, never this.

    The mapping is derived from ``READ_TOOLS_QUALIFIED`` (the constant appended to
    ``allowed_tools``); a name outside the registry tuple falls back to the same
    ``mcp__<server>__<tool>`` shape so the helper is total.
    """
    return _QUALIFIED_BY_BARE.get(bare_name) or f"mcp__{READS_SERVER_NAME}__{bare_name}"

# Model-facing input schemas. The model passes ONLY the finding's identifier — it does
# NOT name the evidence slot (T5.3g: the slot is bound in code, not by the model). Tier-0
# reads need no justification (the PreToolUse hook always allows Tier-0 + logs).
_DOC_SCHEMA: dict[str, Any] = {"doc_num": int}
_VENDOR_SCHEMA: dict[str, Any] = {"card_name": str}
_PRIOR_SCHEMA: dict[str, Any] = {"key": str}

# Enrichment reads fill no required completeness slot; they record under a stable key.
_ENRICHMENT_SLOT: dict[str, str] = {"read_prior_period_treatment": "prior_period_treatment"}


def canonical_slot(tool_name: str) -> str:
    """The deterministic sink slot a read fills — CODE-DEFINED, never model-supplied.

    Required completeness slots come from ``READ_TOOL_SLOT`` (sourced from
    ``CheckSpec.inputs_needed``); enrichment reads get a stable key. This is the single
    source of truth the live handlers AND the hermetic fakes both bind against.
    """
    return READ_TOOL_SLOT.get(tool_name) or _ENRICHMENT_SLOT[tool_name]


def _payload(tool_name: str, slot: Any, found: bool, result: Any) -> dict[str, Any]:
    """Build the MCP text-content result returned to the model."""
    body = {"tool": tool_name, "evidence_slot": slot, "found": found, "result": result}
    return {"content": [{"type": "text", "text": json.dumps(body)}]}


def make_read_tools(
    ctx: "LoopContext",
    evidence_sink: dict,
) -> "list[SdkMcpTool]":
    """Build the three Tier-0 read tools bound to *ctx* and *evidence_sink*.

    The testable unit (mirrors ``engine_tool.make_engine_tool``): returns the
    ``SdkMcpTool`` list so handlers can be invoked directly in hermetic tests.
    ``make_read_tools_server`` wraps these into an in-process MCP server.

    Args:
        ctx:           LoopContext whose ``provider`` / ``vendor_catalog`` /
                       ``prior_period_store`` the reads resolve against. Bound in the
                       handler closures — the model never supplies the source.
        evidence_sink: Dict the handlers record results into (keyed by ``evidence_slot``,
                       or the tool name when no slot is given).
    """
    from claude_agent_sdk import tool  # noqa: PLC0415 - deferred SDK import

    async def _get_source_document(args: dict[str, Any]) -> dict[str, Any]:
        slot = canonical_slot("get_source_document")
        path = get_source_document(ctx.provider, int(args["doc_num"]))
        evidence_sink[slot] = path
        return _payload("get_source_document", slot, path is not None, path)

    async def _read_vendor_gst_status(args: dict[str, Any]) -> dict[str, Any]:
        slot = canonical_slot("read_vendor_gst_status")
        rec = read_vendor_gst_status(ctx.vendor_catalog, args["card_name"])
        evidence_sink[slot] = rec
        return _payload("read_vendor_gst_status", slot, bool(rec.get("found")), rec)

    async def _read_prior_period_treatment(args: dict[str, Any]) -> dict[str, Any]:
        slot = canonical_slot("read_prior_period_treatment")
        rec = read_prior_period_treatment(ctx.prior_period_store, args["key"])
        evidence_sink[slot] = rec
        return _payload("read_prior_period_treatment", slot, bool(rec.get("found")), rec)

    return [
        tool("get_source_document",
             "Fetch the source invoice PDF for a finding's doc_num (read-only). Provide "
             "the finding's doc_num. Returns found=false when no PDF is available.",
             _DOC_SCHEMA)(_get_source_document),
        tool("read_vendor_gst_status",
             "Look up a vendor's GST-registration status by card_name (read-only). "
             "Provide the finding's card_name.",
             _VENDOR_SCHEMA)(_read_vendor_gst_status),
        tool("read_prior_period_treatment",
             "Look up how a finding key was treated in a prior period (read-only). "
             "Provide the finding's key.",
             _PRIOR_SCHEMA)(_read_prior_period_treatment),
    ]


def make_read_tools_server(
    ctx: "LoopContext",
    evidence_sink: dict,
) -> "McpSdkServerConfig":
    """Build an in-process MCP server exposing the three Tier-0 reads.

    Args:
        ctx:           LoopContext the reads resolve against (closure-bound).
        evidence_sink: Dict the handlers record results into (see ``make_read_tools``).
                       The loop-rewire reads in-turn-gathered evidence from here.

    Returns:
        An McpSdkServerConfig named ``READS_SERVER_NAME`` with the three read tools.
    """
    from claude_agent_sdk import create_sdk_mcp_server  # noqa: PLC0415 - deferred SDK import

    return create_sdk_mcp_server(
        name=READS_SERVER_NAME,
        version="1.0.0",
        tools=make_read_tools(ctx, evidence_sink),
    )
