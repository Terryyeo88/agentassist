"""
tests/test_t53g_slot_contract.py — T5.3g: deterministic evidence-slot binding + hardening.

The T5.3-V live run showed the model invents its own slot names. The slot a read fills
is a correctness-critical, deterministic property of the (check, tool) pair — it must
NOT be a string the model copies. T5.3g binds it in code (READ_TOOL_SLOT), removes
evidence_slot from the model-facing schema, suppresses leaked built-ins via an
allow/deny list, and adds a model pin.

Hermetic: handlers invoked directly with a mock ctx; option WIRING asserted with a
mocked query — no live model, no binary, no tokens.
"""
from __future__ import annotations

import asyncio

from agent.budget import RunBudget
from agent.completeness import AGENT_GATHERED_INPUTS, READ_TOOL_SLOT
from agent.dossier import Finding
from agent.ledger import Ledger
from agent.loop import LoopContext, run_casefile_loop
from agent.proposals import StagingStore
from agent.read_tools_server import (
    READ_TOOLS_QUALIFIED,
    canonical_slot,
    make_read_tools,
)


class _FakeProvider:
    def __init__(self, mapping):
        self._m = {int(k): v for k, v in mapping.items()}

    def get_document(self, doc_num):
        return self._m.get(int(doc_num))


def _ctx():
    return LoopContext(
        provider=_FakeProvider({3001: "/tmp/INV-3001.pdf"}),
        vendor_catalog={"Mama Shop Supplies": {"gst_registered": False, "gst_reg_no": None}},
        prior_period_store={"NO_GST_REG:Mama Shop Supplies": {"treatment": "disallowed"}},
    )


def _handlers(ctx, sink):
    return {t.name: t.handler for t in make_read_tools(ctx, sink)}


def _call(h, args):
    return asyncio.run(h(args))


# --------------------------------------------------------------------------- #
# The guard: every agent-gathered slot must have a reader (fails loudly on drift)
# --------------------------------------------------------------------------- #

def test_every_agent_gathered_slot_has_a_reader():
    # If a future CheckSpec adds an AGENT_GATHERED slot with no reader, THIS must fail
    # — config drift breaks loudly, never silently misses completeness.
    assert set(READ_TOOL_SLOT.values()) >= set(AGENT_GATHERED_INPUTS), (
        f"agent-gathered slots with no reader: "
        f"{set(AGENT_GATHERED_INPUTS) - set(READ_TOOL_SLOT.values())}"
    )


# --------------------------------------------------------------------------- #
# Slot is deterministic in code; the model supplies no slot
# --------------------------------------------------------------------------- #

def test_evidence_slot_removed_from_model_schema():
    tools = {t.name: t for t in make_read_tools(_ctx(), {})}
    for name, t in tools.items():
        assert "evidence_slot" not in t.input_schema, f"{name} still exposes evidence_slot"


def test_reads_write_canonical_slot_regardless_of_args():
    sink = {}
    h = _handlers(_ctx(), sink)
    _call(h["get_source_document"], {"doc_num": 3001})
    _call(h["read_vendor_gst_status"], {"card_name": "Mama Shop Supplies"})
    _call(h["read_prior_period_treatment"], {"key": "NO_GST_REG:Mama Shop Supplies"})
    assert sink["document_pdfs"] == "/tmp/INV-3001.pdf"          # canonical, not "source_document"
    assert sink["supplier_catalog"]["found"] is True            # canonical, not "vendor_gst_status"
    assert sink["prior_period_treatment"]["found"] is True      # enrichment slot
    # canonical_slot is the single source of truth.
    assert canonical_slot("get_source_document") == "document_pdfs"
    assert canonical_slot("read_vendor_gst_status") == "supplier_catalog"


# --------------------------------------------------------------------------- #
# build_options: allowlist + disallowed_tools + model wiring
# --------------------------------------------------------------------------- #

def test_build_options_tool_allowlist_replaces_allowed_tools():
    from agent.harness import build_options
    ledger, budget = Ledger(), RunBudget(max_turns=4, max_cost_usd=1.0)
    opts = build_options(ledger, budget, tool_allowlist=list(READ_TOOLS_QUALIFIED),
                         disallowed_tools=["ToolSearch"], model="some-model")
    assert set(opts.allowed_tools) == set(READ_TOOLS_QUALIFIED)
    assert "ToolSearch" in opts.disallowed_tools
    assert opts.model == "some-model"
    # the leaked built-in is not in the allowlist
    assert "ToolSearch" not in opts.allowed_tools


def test_build_options_defaults_unchanged():
    from agent.harness import build_options
    from agent.registry import REGISTRY
    ledger, budget = Ledger(), RunBudget(max_turns=4, max_cost_usd=1.0)
    opts = build_options(ledger, budget)
    assert opts.model is None
    assert list(opts.disallowed_tools) == []
    # default allowed_tools is the registry-derived list (existing callers unchanged)
    assert any(n in REGISTRY for n in opts.allowed_tools)


# --------------------------------------------------------------------------- #
# Live transport threads allowlist + disallow + model into its options
# --------------------------------------------------------------------------- #

def test_live_transport_gather_hardens_options():
    import claude_agent_sdk as sdk
    from agent.live_transport import LiveAgentTransport

    captured = {}

    def _fake_query(captured):
        async def _q(*, prompt, options):
            captured["options"] = options
            yield sdk.ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                                    is_error=False, num_turns=1, session_id="s",
                                    total_cost_usd=0.0, usage={})
        return _q

    t = LiveAgentTransport(ctx=_ctx(), ledger=Ledger(),
                           budget=RunBudget(max_turns=4, max_cost_usd=1.0),
                           system_prompt="p", model="pinned-x",
                           query_fn=_fake_query(captured))
    finding = Finding(finding_id="doc:gst_amount_mismatch:3001", check_id="gst_amount_mismatch",
                      finding_type="probabilistic", source="t", payload={"doc_num": 3001})
    list(t.gather("p", finding, {}))
    opts = captured["options"]
    assert set(opts.allowed_tools) == set(READ_TOOLS_QUALIFIED)
    assert "ToolSearch" in opts.disallowed_tools
    assert opts.model == "pinned-x"


# --------------------------------------------------------------------------- #
# End-to-end: with the slot bound in code, the model only supplies the id and
# completeness is satisfied -> a PENDING is staged.
# --------------------------------------------------------------------------- #

class _SlotlessGatherFake:
    """Calls the canonical reads via the real handlers (model supplies no slot)."""

    def __init__(self, ctx):
        self._ctx = ctx

    def gather(self, prompt, finding, evidence_sink):
        from agent.loop import FramingEvent, ResultEvent
        handlers = _handlers(self._ctx, evidence_sink)
        if finding.check_id == "gst_amount_mismatch":
            _call(handlers["get_source_document"], {"doc_num": finding.payload["doc_num"]})
        elif finding.check_id == "NO_GST_REG":
            _call(handlers["read_vendor_gst_status"], {"card_name": finding.payload["card_name"]})
        yield FramingEvent(text="candidate for review: please verify the flagged values.")
        yield ResultEvent(cost_usd=0.001)


def test_completeness_satisfied_and_pending_staged_without_model_slot():
    ctx = _ctx()
    review = {
        "status": "completed",
        "compile_output": {"detect": {"issues": []}},
        "document_candidates": [{
            "doc_num": 3001, "check_id": "gst_amount_mismatch", "severity": "MEDIUM",
            "message": "x", "extracted_value": 74.0, "listing_value": 70.0,
            "determinability": "born_digital",
        }],
        "bundle_dir": "crafted/none",
    }
    ledger, budget, store = Ledger(), RunBudget(max_turns=10, max_cost_usd=1.0), StagingStore()
    result = run_casefile_loop(
        invoke_review=lambda: review, transport=_SlotlessGatherFake(ctx), ctx=ctx,
        ledger=ledger, budget=budget, store=store,
    )
    assert len(store.list_pending()) == 1
    assert {o.status for o in result.outcomes} == {"staged"}
    assert result.outcomes[0].dossier.evidence["document_pdfs"] == "/tmp/INV-3001.pdf"
