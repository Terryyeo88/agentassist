"""
tests/test_t57a_hermetic.py — T5.7a acceptance: the harness is fully hermetic.

Asserts:
  * Running the WHOLE adversarial basket spawns NO subprocess (no CLI binary).
  * The eval package never calls query()/ClaudeSDKClient against a real transport
    (FakeTransport only) — verified by source scan AND by a Popen tripwire.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import agent.eval as eval_pkg

_FORBIDDEN_LIVE = {"query", "ClaudeSDKClient"}


def test_basket_spawns_no_subprocess(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - only fires on a containment breach
        raise AssertionError("eval harness attempted to spawn a subprocess (binary spawn)")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)

    from agent.eval.report import run_basket

    report = run_basket()
    assert report.all_passed is True


def test_eval_source_has_no_real_transport_query():
    # The harness drives the REAL hooks directly; it must never open a live SDK
    # stream. query()/ClaudeSDKClient are the only ways to do so. Use the AST (not
    # a substring scan) so prose mentions in docstrings don't trip the check, and
    # iterating our own FakeTransport via `async for` stays allowed.
    pkg_dir = Path(eval_pkg.__file__).parent
    offenders = []
    for py in pkg_dir.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name in _FORBIDDEN_LIVE:
                    offenders.append((py.name, name))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_LIVE:
                        offenders.append((py.name, alias.name))
    assert offenders == [], f"live-transport usage found in eval pkg: {offenders}"


def test_fake_transport_is_the_only_transport_used():
    from agent.eval.transport import FakeTransport
    from agent.eval.runner import run_scenario
    from agent.eval.scenario import Attempt, Scenario

    rec = run_scenario(Scenario(name="t", description="", attempts=[
        Attempt(tool_name="read_ledger", tool_input={}),
    ]))
    assert type(rec.transport).__name__ == "FakeTransport"
    assert isinstance(rec.transport, FakeTransport)
