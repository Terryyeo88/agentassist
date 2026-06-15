"""
tests/test_t53e_mcp_reads_server.py — T5.3e: MCP-backed Tier-0 reads server.

Architecture A foundation: the three Tier-0 reads are exposed as MCP @tool handlers
so a live model can call them (allowed_tools is only a permission filter — tools enter
the model's schema via MCP). Each handler is ctx-bound (the model cannot re-point the
source), records its result into an evidence_sink, returns the result to the model, and
is gated Tier-0 by the existing hooks.

Hermetic: handlers invoked DIRECTLY with a mock ctx — no live model, no claude binary,
no tokens. This is the component only; the loop is NOT yet rewired to gather in-turn.
"""
from __future__ import annotations

import asyncio
import json
import subprocess

from agent.budget import RunBudget
from agent.harness import build_options
from agent.ledger import Ledger
from agent.loop import LoopContext
from agent.read_tools_server import (
    READS_SERVER_NAME,
    READ_TOOLS_QUALIFIED,
    make_read_tools,
    make_read_tools_server,
)
from agent.registry import _strip_mcp_prefix, get_tier
from agent.schemas import Tier


# --------------------------------------------------------------------------- #
# Hermetic mock ctx
# --------------------------------------------------------------------------- #

class _FakeProvider:
    def __init__(self, mapping):
        self._m = dict(mapping)

    def get_document(self, doc_num):
        return self._m.get(int(doc_num))


def _ctx(docs=None, catalog=None, store=None):
    return LoopContext(
        provider=_FakeProvider(docs or {958: "/tmp/INV-958.pdf"}),
        vendor_catalog=dict(catalog or {
            "Mama Shop Supplies": {"gst_registered": False, "gst_reg_no": None},
        }),
        prior_period_store=dict(store or {
            "NO_GST_REG:Mama Shop Supplies": {"treatment": "disallowed", "period": "2024Q2"},
        }),
    )


def _handlers(ctx, sink):
    """Map tool name -> async handler from the (testable) SdkMcpTool list."""
    return {t.name: t.handler for t in make_read_tools(ctx, sink)}


def _call(handler, args):
    return asyncio.run(handler(args))


def _text(result):
    """Parse the JSON text payload out of an MCP tool result."""
    return json.loads(result["content"][0]["text"])


# --------------------------------------------------------------------------- #
# Handlers: evidence returned + recorded into the sink
# --------------------------------------------------------------------------- #

class TestHandlersReturnAndRecord:
    def test_get_source_document_hit_records_and_returns(self):
        sink = {}
        h = _handlers(_ctx(), sink)["get_source_document"]
        out = _text(_call(h, {"doc_num": 958, "evidence_slot": "document_pdfs"}))
        assert out["found"] is True
        assert out["result"] == "/tmp/INV-958.pdf"
        assert sink["document_pdfs"] == "/tmp/INV-958.pdf"

    def test_get_source_document_miss_is_structured_not_found(self):
        sink = {}
        h = _handlers(_ctx(docs={}), sink)["get_source_document"]
        out = _text(_call(h, {"doc_num": 999, "evidence_slot": "document_pdfs"}))
        assert out["found"] is False
        assert out["result"] is None
        assert sink["document_pdfs"] is None

    def test_vendor_gst_status_records_dict(self):
        sink = {}
        h = _handlers(_ctx(), sink)["read_vendor_gst_status"]
        out = _text(_call(h, {"card_name": "Mama Shop Supplies",
                              "evidence_slot": "supplier_catalog"}))
        assert out["found"] is True
        assert out["result"]["gst_registered"] is False
        assert sink["supplier_catalog"]["card_name"] == "Mama Shop Supplies"

    def test_vendor_gst_status_miss(self):
        sink = {}
        h = _handlers(_ctx(), sink)["read_vendor_gst_status"]
        out = _text(_call(h, {"card_name": "Unknown Co", "evidence_slot": "supplier_catalog"}))
        assert out["found"] is False
        assert out["result"]["found"] is False

    def test_prior_period_treatment_records(self):
        sink = {}
        h = _handlers(_ctx(), sink)["read_prior_period_treatment"]
        out = _text(_call(h, {"key": "NO_GST_REG:Mama Shop Supplies",
                              "evidence_slot": "prior_treatment"}))
        assert out["found"] is True
        assert out["result"]["treatment"] == "disallowed"
        assert sink["prior_treatment"]["treatment"] == "disallowed"

    def test_no_slot_records_under_tool_name(self):
        # Mirrors _run_finding: a read without evidence_slot is enrichment, kept under
        # the tool name via setdefault.
        sink = {}
        h = _handlers(_ctx(), sink)["read_prior_period_treatment"]
        _call(h, {"key": "NO_GST_REG:Mama Shop Supplies"})
        assert "read_prior_period_treatment" in sink
        assert sink["read_prior_period_treatment"]["treatment"] == "disallowed"


# --------------------------------------------------------------------------- #
# Read-only + ctx-bound
# --------------------------------------------------------------------------- #

class TestReadOnlyAndBound:
    def test_no_subprocess_spawned(self, monkeypatch):
        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("reads server spawned a subprocess")

        monkeypatch.setattr(subprocess, "Popen", _boom)
        monkeypatch.setattr(subprocess, "run", _boom)
        sink = {}
        _call(_handlers(_ctx(), sink)["get_source_document"],
              {"doc_num": 958, "evidence_slot": "document_pdfs"})
        assert sink["document_pdfs"] == "/tmp/INV-958.pdf"

    def test_sources_not_mutated(self):
        ctx = _ctx()
        before_catalog = dict(ctx.vendor_catalog)
        before_store = dict(ctx.prior_period_store)
        _call(_handlers(ctx, {})["read_vendor_gst_status"],
              {"card_name": "Mama Shop Supplies", "evidence_slot": "supplier_catalog"})
        assert ctx.vendor_catalog == before_catalog
        assert ctx.prior_period_store == before_store

    def test_ctx_is_closure_bound(self):
        # A server built for ctx_a reads ctx_a even though ctx_b exists with a
        # different mapping — the model cannot re-point the source.
        ctx_a = _ctx(docs={958: "/A/INV-958.pdf"})
        ctx_b = _ctx(docs={958: "/B/INV-958.pdf"})  # noqa: F841 - exists but must be ignored
        out = _text(_call(_handlers(ctx_a, {})["get_source_document"],
                          {"doc_num": 958, "evidence_slot": "document_pdfs"}))
        assert out["result"] == "/A/INV-958.pdf"


# --------------------------------------------------------------------------- #
# Tier-0 gating + build_options wiring
# --------------------------------------------------------------------------- #

class TestTierAndWiring:
    def test_namespaced_names_resolve_tier0(self):
        for bare in ("get_source_document", "read_vendor_gst_status",
                     "read_prior_period_treatment"):
            q = f"mcp__{READS_SERVER_NAME}__{bare}"
            assert _strip_mcp_prefix(q) == bare
            assert get_tier(q) == Tier.ZERO

    def test_qualified_names_constant_matches_tools(self):
        names = {t.name for t in make_read_tools(_ctx(), {})}
        assert names == {"get_source_document", "read_vendor_gst_status",
                         "read_prior_period_treatment"}
        assert set(READ_TOOLS_QUALIFIED) == {
            f"mcp__{READS_SERVER_NAME}__{n}" for n in names
        }

    def test_build_options_wires_reads_server(self):
        ledger, budget = Ledger(), RunBudget(max_turns=5, max_cost_usd=0.5)
        srv = make_read_tools_server(_ctx(), {})
        options = build_options(ledger, budget, reads_server=srv)
        assert READS_SERVER_NAME in options.mcp_servers
        for q in READ_TOOLS_QUALIFIED:
            assert q in options.allowed_tools

    def test_build_options_default_unchanged(self):
        ledger, budget = Ledger(), RunBudget(max_turns=5, max_cost_usd=0.5)
        options = build_options(ledger, budget)
        assert READS_SERVER_NAME not in options.mcp_servers
        for q in READ_TOOLS_QUALIFIED:
            assert q not in options.allowed_tools


def test_import_agent_does_not_load_sdk():
    import sys
    import importlib

    for m in ("claude_agent_sdk", "agent", "agent.read_tools_server"):
        sys.modules.pop(m, None)
    importlib.import_module("agent")
    importlib.import_module("agent.read_tools_server")
    assert "claude_agent_sdk" not in sys.modules
