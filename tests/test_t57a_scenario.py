"""
tests/test_t57a_scenario.py — T5.7a: scenario format + loader.

A scenario is an ordered list of attempted {tool_name, tool_input, justification?}
agent tool-calls, plus optional human-approved Tier-2 executions (NOT agent
attempts) used to exercise sealed-chain routing.

Hermetic: pure data, no model, no SAP, no network.
"""
from __future__ import annotations

import json

from agent.eval.scenario import (
    Attempt,
    Scenario,
    Tier2Execution,
    load_scenario,
    load_scenarios_from_json,
)


def test_attempt_merges_justification_into_input():
    a = Attempt(tool_name="run_review_chain", tool_input={}, justification="j" * 25)
    merged = a.merged_input()
    assert merged["justification"] == "j" * 25
    # original tool_input is not mutated
    assert a.tool_input == {}


def test_attempt_explicit_input_justification_wins_over_field():
    a = Attempt(
        tool_name="run_review_chain",
        tool_input={"justification": "in-input"},
        justification="in-field",
    )
    assert a.merged_input()["justification"] == "in-input"


def test_load_scenario_from_dict():
    spec = {
        "name": "demo",
        "description": "demo scenario",
        "attempts": [
            {"tool_name": "read_ledger", "tool_input": {}},
            {"tool_name": "run_review_chain", "justification": "z" * 30},
        ],
        "approved_executions": [
            {
                "action": "seal_bundle",
                "justification": "human approved seal at close",
                "evidence_refs": ["audit/compile.json"],
                "inputs": {"client_id": "sbodemosg"},
            }
        ],
    }
    sc = load_scenario(spec)
    assert isinstance(sc, Scenario)
    assert sc.name == "demo"
    assert len(sc.attempts) == 2
    assert isinstance(sc.attempts[0], Attempt)
    assert sc.attempts[1].justification == "z" * 30
    assert len(sc.approved_executions) == 1
    assert isinstance(sc.approved_executions[0], Tier2Execution)
    assert sc.approved_executions[0].action == "seal_bundle"


def test_load_scenarios_from_json_file(tmp_path):
    payload = [
        {"name": "a", "description": "", "attempts": []},
        {"name": "b", "description": "", "attempts": [{"tool_name": "read_ledger"}]},
    ]
    p = tmp_path / "scenarios.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    scenarios = load_scenarios_from_json(p)
    assert [s.name for s in scenarios] == ["a", "b"]
    assert scenarios[1].attempts[0].tool_name == "read_ledger"


def test_attempt_defaults_tool_input_empty_dict():
    sc = load_scenario({"name": "n", "description": "", "attempts": [{"tool_name": "read_ledger"}]})
    assert sc.attempts[0].tool_input == {}
