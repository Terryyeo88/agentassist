"""
tests/test_t53a_engine_tool.py — T5.3 Slice 1: engine-tool atomicity (acceptance (a)).

The full GST review pipeline (engine.review.review) is exposed to the agent as
ONE atomic MCP tool. The agent can invoke review() whole; it CANNOT reach
run_chain / gates / seal_bundle internals — there is no sub-step tool.

All hermetic: a fake invoke_review callable, no live model, no SDK subprocess,
no SAP, no network.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agent.budget import RunBudget
from agent.ledger import Ledger
from agent.schemas import Tier
from engine.review import GateHalt, ReviewResult


def _run(coro):
    return asyncio.run(coro)


def _completed_result() -> ReviewResult:
    from pathlib import Path
    return ReviewResult(
        status="completed",
        compile_output={"summary": {"findings": 2}},
        gate_results={"all_passed": True, "gates": []},
        reasoning_artefact={"status": "ok"},
        document_candidates=[{"doc_num": 101}],
        analytical_review_data=None,
        report_pdf_path=Path("/tmp/report.pdf"),
        bundle_dir=Path("/tmp/bundle"),
        run_started_at="2026-06-14T00:00:00+00:00",
        run_completed_at="2026-06-14T00:01:00+00:00",
        gate_failure=None,
    )


def _halted_result() -> ReviewResult:
    return ReviewResult(
        status="halted",
        compile_output=None,
        gate_results=None,
        reasoning_artefact=None,
        document_candidates=None,
        analytical_review_data=None,
        report_pdf_path=None,
        bundle_dir=None,
        run_started_at="2026-06-14T00:00:00+00:00",
        run_completed_at=None,
        gate_failure=GateHalt(message="gate X failed", checked={"k": 1}),
    )


# Sub-step internals the agent must NEVER be able to call as a tool.
_FORBIDDEN_SUBSTEP_NAMES = {
    "run_chain", "classify", "calculate", "detect", "compile",
    "seal_bundle", "render_pdf", "build_report",
}


class TestEngineToolAtomicity:
    def test_serialise_completed_result_is_json_round_trippable(self):
        from agent.engine_tool import serialise_review_result
        d = serialise_review_result(_completed_result())
        # Paths serialised to str; round-trips through JSON.
        s = json.dumps(d)
        back = json.loads(s)
        assert back["status"] == "completed"
        assert back["report_pdf_path"].endswith("report.pdf")
        assert back["bundle_dir"].endswith("bundle")
        assert back["gate_failure"] is None
        assert back["compile_output"] == {"summary": {"findings": 2}}

    def test_serialise_halted_result_carries_gate_failure(self):
        from agent.engine_tool import serialise_review_result
        d = serialise_review_result(_halted_result())
        json.dumps(d)  # must not raise
        assert d["status"] == "halted"
        assert d["report_pdf_path"] is None
        assert d["bundle_dir"] is None
        assert d["gate_failure"] == {"message": "gate X failed", "checked": {"k": 1}}

    def test_engine_server_exposes_exactly_one_tool(self):
        from agent.engine_tool import make_engine_tool, ENGINE_TOOL_NAME

        calls = {"n": 0}

        def invoke_review():
            calls["n"] += 1
            return _completed_result()

        engine_tool = make_engine_tool(invoke_review)
        # The single atomic tool carries the canonical name.
        assert engine_tool.name == ENGINE_TOOL_NAME

    def test_engine_tool_handler_invokes_review_whole_and_returns_serialised(self):
        from agent.engine_tool import make_engine_tool

        calls = {"n": 0}

        def invoke_review():
            calls["n"] += 1
            return _completed_result()

        engine_tool = make_engine_tool(invoke_review)
        out = _run(engine_tool.handler({"justification": "Run the full atomic review chain for Q3 per audit step."}))

        assert calls["n"] == 1
        # MCP tool result shape: {"content": [{"type": "text", "text": <json>}]}
        text = out["content"][0]["text"]
        payload = json.loads(text)
        assert payload["status"] == "completed"
        assert payload["compile_output"] == {"summary": {"findings": 2}}

    def test_no_substep_tool_is_reachable(self):
        """Neither the registry nor the engine server may expose any sub-step tool."""
        from agent.registry import REGISTRY
        from agent.engine_tool import make_engine_tool, ENGINE_TOOL_NAME

        for forbidden in _FORBIDDEN_SUBSTEP_NAMES:
            assert forbidden not in REGISTRY, f"sub-step {forbidden!r} must not be a registry tool"

        # The engine tool itself is the whole-pipeline tool, not a sub-step.
        engine_tool = make_engine_tool(lambda: _completed_result())
        assert engine_tool.name == ENGINE_TOOL_NAME
        assert engine_tool.name not in _FORBIDDEN_SUBSTEP_NAMES

    def test_build_options_wires_engine_server_when_provided(self):
        from agent.harness import build_options
        from agent.engine_tool import make_engine_server, ENGINE_SERVER_NAME, ENGINE_TOOL_QUALIFIED

        ledger = Ledger()
        budget = RunBudget(max_turns=5, max_cost_usd=0.5)
        server = make_engine_server(lambda: _completed_result())
        options = build_options(ledger, budget, engine_server=server)

        # mcp_servers carries the engine server under its name.
        assert ENGINE_SERVER_NAME in options.mcp_servers
        assert options.mcp_servers[ENGINE_SERVER_NAME]["type"] == "sdk"
        # The qualified MCP tool name is in allowed_tools exactly once.
        assert options.allowed_tools.count(ENGINE_TOOL_QUALIFIED) == 1

    def test_build_options_without_engine_server_is_unchanged(self):
        """Backward-compat: default build_options wires no MCP engine tool."""
        from agent.harness import build_options
        from agent.engine_tool import ENGINE_TOOL_QUALIFIED

        ledger = Ledger()
        budget = RunBudget(max_turns=5, max_cost_usd=0.5)
        options = build_options(ledger, budget)

        assert ENGINE_TOOL_QUALIFIED not in options.allowed_tools
        # No mcp engine wiring by default.
        assert not options.mcp_servers

    def test_engine_tool_qualified_name_gates_as_tier1(self):
        """The MCP-namespaced engine tool resolves to its Tier-1 registry contract."""
        from agent.registry import get_tier
        from agent.engine_tool import ENGINE_TOOL_QUALIFIED

        assert get_tier(ENGINE_TOOL_QUALIFIED) == Tier.ONE
