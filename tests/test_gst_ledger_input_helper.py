"""
PR-3 (fork d) — the shared gst_ledger assembly helper. FAILING-FIRST.

build_gst_ledger_input is extracted from run_agent.py (a CLI entrypoint) into a shared
module ``gst_ledger_input`` that BOTH the CLI and the web layer import — the web layer
must never import from run_agent.py. The helper calls only feeder leaves
(load_gst_ledger / parse_declared_return / parse_not_included).
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_FIX = _REPO / "tests" / "fixtures" / "xero-real-format"
_F5 = _FIX / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_LEDGER = _FIX / "AgentAssist_-_Account_Transactions.xlsx"


def _top_import_modules(py_file: Path) -> set:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    mods: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
    return mods


class TestSharedModuleExists:
    def test_importable_from_shared_module(self):
        from gst_ledger_input import build_gst_ledger_input  # noqa: F401
        assert callable(build_gst_ledger_input)

    def test_run_agent_reuses_the_shared_helper(self):
        # CLI/web parity: run_agent must expose the SAME callable, not a divergent copy.
        import gst_ledger_input
        import run_agent
        assert run_agent.build_gst_ledger_input is gst_ledger_input.build_gst_ledger_input


class TestReturnShape:
    def test_returns_lines_declared_boxes_not_included(self):
        from gst_ledger_input import build_gst_ledger_input
        from feeders.xero_f5_reader import parse_review_period

        period = parse_review_period(_F5)
        out = build_gst_ledger_input(_LEDGER, _F5, period)
        assert set(out.keys()) == {"lines", "declared_boxes", "not_included"}
        assert isinstance(out["lines"], list)
        assert set(out["declared_boxes"].keys()) == {"output_tax", "input_tax"}


class TestImportIsolation:
    def test_helper_calls_only_feeder_leaves_no_engine_or_sdk(self):
        # The shared module must not drag anthropic/agent/engine/orchestrator/reasoning
        # into whatever imports it (the web layer relies on this).
        mods = _top_import_modules(_REPO / "gst_ledger_input.py")
        forbidden = {"anthropic", "agent", "engine", "orchestrator", "reasoning", "documents"}
        assert not (mods & forbidden), f"shared helper imports forbidden module(s): {mods & forbidden}"

    def test_api_app_does_not_import_run_agent(self):
        # The web layer must not import the CLI entrypoint.
        mods = _top_import_modules(_REPO / "api" / "app.py")
        assert "run_agent" not in mods
