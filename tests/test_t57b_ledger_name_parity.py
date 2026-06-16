"""
tests/test_t57b_ledger_name_parity.py — T5.7b: hermetic fakes ledger read names
must match the LIVE namespaced shape (mcp__reads__<tool>).

Round-2 evidence (exploration-notes/live-loop-run-round2/{runA-opus,runB-sonnet}/raw/
ledger.json) showed the LIVE loop writes Tier-0 read ledger entries NAMESPACED — the
SDK PreToolUse hook records ``input["tool_name"]`` verbatim, which is
``mcp__reads__<tool>`` (the in-process MCP server prefix). The hermetic gather-fakes,
however, wrote the BARE ``<tool>`` name, so the fake-based tests never exercised the
namespaced→bare resolution that actually ships. This module pins the fakes to the live
shape WITHOUT disturbing T5.3g: slot lookups still resolve on the BARE name.

Anchoring (per Terry's refinement): the expected names are pinned to an INDEPENDENT
production value — the round-2 ledger.json literals, cross-checked against the shipping
``READ_TOOLS_QUALIFIED`` constant — NOT to ``qualified_read_name()``'s own output, so
this proves the fakes match production rather than matching themselves.

Hermetic: in-memory fakes — no SDK, no binary, no tokens, no SAP.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

from agent.budget import RunBudget
from agent.eval.loop_runner import LoopScenario, run_loop_scenario
from agent.ledger import Ledger
from agent.loop import (
    FramingEvent,
    LoopContext,
    ResultEvent,
    ToolUseEvent,
    run_casefile_loop,
)
from agent.proposals import StagingStore
from agent.schemas import Tier

# Independent production anchor: the EXACT ledger ``tool_name`` strings the live loop
# wrote in the round-2 evidence (…/runA-opus/raw/ledger.json l.18/33/48). Hard-coded so
# the parity assertion does not depend on any helper under test.
LIVE_LEDGER_READ_NAMES: dict[str, str] = {
    "get_source_document": "mcp__reads__get_source_document",
    "read_vendor_gst_status": "mcp__reads__read_vendor_gst_status",
    "read_prior_period_treatment": "mcp__reads__read_prior_period_treatment",
}

_CLEAN_FRAMING = (
    "The invoice PDF GST amount appears to differ from the SAP line; flagged as a "
    "candidate for reviewer attention."
)


def _load_fx():
    spec = importlib.util.spec_from_file_location(
        "t57b_agent_loop_fx", pathlib.Path(__file__).parent / "fixtures" / "agent_loop.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tier0_reads(ledger: Ledger) -> list:
    """All Tier-0 read ledger entries (excludes the Tier-1 propose_action + COGS)."""
    return [
        e for e in ledger.entries
        if e.tier == Tier.ZERO.value and e.tool_name != "budget_increment"
    ]


# --------------------------------------------------------------------------- #
# Fake #2 — tests/fixtures/agent_loop.py::FakeTransport (exercises all 3 reads)
# --------------------------------------------------------------------------- #

def _run_fixtures_loop():
    fx = _load_fx()
    ledger = Ledger()
    budget = RunBudget(max_turns=20, max_cost_usd=1.0)
    store = StagingStore()
    ctx = LoopContext(
        provider=fx.FakeProvider({958: "/tmp/INV-958.pdf"}),
        vendor_catalog=fx.default_vendor_catalog(),
        prior_period_store=fx.default_prior_period_store(),
    )
    transport = fx.FakeTransport(scripts=fx.golden_scripts(), ctx=ctx, ledger=ledger)
    result = run_casefile_loop(
        invoke_review=lambda: fx.canned_review_result(),
        transport=transport, ctx=ctx, ledger=ledger, budget=budget, store=store,
    )
    return result, ledger


def test_fixtures_fake_ledgers_namespaced_read_names():
    # (a) PARITY: every Tier-0 read entry the fake wrote carries the live namespaced
    # name. Fails today — the fake writes the BARE name.
    _result, ledger = _run_fixtures_loop()
    reads = _tier0_reads(ledger)
    names = {e.tool_name for e in reads}
    assert names == set(LIVE_LEDGER_READ_NAMES.values()), (
        f"fake read ledger names {names} != live namespaced names "
        f"{set(LIVE_LEDGER_READ_NAMES.values())}"
    )
    assert all(n.startswith("mcp__reads__") for n in names)


def test_fixtures_fake_slot_binding_still_bare():
    # (b) T5.3g GUARD: the namespaced ledger entry must NOT change slot binding — the
    # dossier evidence is still keyed by the BARE canonical slots, populated non-null.
    result, _ledger = _run_fixtures_loop()
    evidence_by_finding = {o.finding_id: o.dossier.evidence for o in result.outcomes}
    # NO_GST_REG → supplier_catalog (read_vendor_gst_status); doc → document_pdfs.
    no_gst = evidence_by_finding["detect:NO_GST_REG:605"]
    doc = evidence_by_finding["doc:gst_amount_mismatch:958"]
    assert no_gst.get("supplier_catalog") is not None
    assert doc.get("document_pdfs") is not None


# --------------------------------------------------------------------------- #
# Fake #1 — agent/eval/loop_runner.py::ScriptedLoopTransport
# --------------------------------------------------------------------------- #

def _single_doc_review() -> dict:
    return {
        "status": "completed",
        "compile_output": {"detect": {"issues": []}},
        "reasoning_artefact": {"status": "ok", "candidates": []},
        "document_candidates": [{
            "doc_num": 958, "check_id": "gst_amount_mismatch", "severity": "MEDIUM",
            "message": "Invoice PDF GST (74.00) differs from SAP line (70.00).",
            "extracted_value": 74.0, "listing_value": 70.0,
            "determinability": "born_digital",
        }],
        "bundle_dir": "audit/sbodemosg/2024Q3/seal-001", "gate_failure": None,
    }


def _run_loop_runner_scenario():
    scenario = LoopScenario(
        name="t57b-parity-doc",
        description="single doc finding; read get_source_document.",
        review_result=_single_doc_review(),
        scripts={"doc:gst_amount_mismatch:958": [[
            ToolUseEvent(
                tool_name="get_source_document",
                tool_input={"justification": "Read the source PDF to support the case file.",
                            "doc_num": 958, "evidence_slot": "document_pdfs"},
            ),
            FramingEvent(text=_CLEAN_FRAMING),
            ResultEvent(cost_usd=0.01),
        ]]},
        provider_docs={958: "/tmp/INV-958.pdf"},
    )
    return run_loop_scenario(scenario)


def test_loop_runner_fake_ledgers_namespaced_read_name():
    # (a) PARITY for the eval loop-runner fake. Fails today — bare name.
    rec = _run_loop_runner_scenario()
    reads = _tier0_reads(rec.ledger)
    assert reads, "expected at least one Tier-0 read ledger entry"
    assert all(e.tool_name == LIVE_LEDGER_READ_NAMES["get_source_document"] for e in reads)


def test_loop_runner_fake_slot_binding_still_bare():
    # (b) T5.3g GUARD: document_pdfs slot still populated despite namespaced ledger name.
    rec = _run_loop_runner_scenario()
    doc = {o.finding_id: o.dossier.evidence for o in rec.outcomes}["doc:gst_amount_mismatch:958"]
    assert doc.get("document_pdfs") is not None


# --------------------------------------------------------------------------- #
# Helper unit — qualified_read_name() matches the shipping constant
# --------------------------------------------------------------------------- #

def test_qualified_read_name_matches_production_constant():
    # Lazy import so the parity tests above still COLLECT (and fail for the right
    # reason) before the helper exists.
    from agent.read_tools_server import (  # noqa: PLC0415
        READ_TOOL_NAMES,
        READ_TOOLS_QUALIFIED,
        qualified_read_name,
    )
    # Anchored on the round-2 literals (independent of the helper's own formatting).
    for bare, live in LIVE_LEDGER_READ_NAMES.items():
        assert qualified_read_name(bare) == live
    # …and equals the shipping qualified-names constant for every read.
    assert {qualified_read_name(n) for n in READ_TOOL_NAMES} == set(READ_TOOLS_QUALIFIED)
