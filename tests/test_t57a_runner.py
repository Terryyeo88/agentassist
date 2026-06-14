"""
tests/test_t57a_runner.py — T5.7a: the runner replays a scenario through the REAL
cage (build_options hooks + registry + justification gate + executor).

The runner builds the real cage (with the Slice-1 engine server wired in), sources
the scripted agent stream from a FakeTransport, and records every cage response:
allow/deny, ledger writes, audit_log writes, and Tier-2 executor outcomes.

Hermetic: FakeTransport only, no live model, no SAP, no subprocess, no tokens.
"""
from __future__ import annotations

from agent.eval.runner import run_scenario, RunRecord
from agent.eval.scenario import Attempt, Scenario, Tier2Execution
from agent.schemas import Tier

GOOD_JUST = "Audit period Q3 2024: running review chain per IRAS ASK step 1.3 to classify invoices."


def test_run_scenario_returns_runrecord_with_no_binary_spawn():
    sc = Scenario(name="empty", description="", attempts=[])
    rec = run_scenario(sc)
    assert isinstance(rec, RunRecord)
    assert rec.scenario_name == "empty"
    assert rec.transport_spawned_binary is False


def test_tier0_read_allowed_and_audit_logged():
    sc = Scenario(name="t0", description="", attempts=[
        Attempt(tool_name="read_sap_invoices", tool_input={}),
    ])
    rec = run_scenario(sc)
    assert len(rec.attempts) == 1
    ar = rec.attempts[0]
    assert ar.tier == Tier.ZERO.value
    assert ar.decision == "allow"
    assert ar.produced_audit_entry is True
    # Tier-0 read appears in the unsealed audit_log
    assert any(e["tool_name"] == "read_sap_invoices" for e in rec.audit_log)


def test_tier1_with_justification_allowed_ledger_entry():
    sc = Scenario(name="t1ok", description="", attempts=[
        Attempt(tool_name="run_review_chain", tool_input={}, justification=GOOD_JUST),
    ])
    rec = run_scenario(sc)
    ar = rec.attempts[0]
    assert ar.tier == Tier.ONE.value
    assert ar.decision == "allow"
    assert rec.ledger.entries[-1].outcome == "allowed"
    rec.ledger.verify()


def test_tier1_without_justification_blocked():
    sc = Scenario(name="t1bad", description="", attempts=[
        Attempt(tool_name="run_review_chain", tool_input={}),
    ])
    rec = run_scenario(sc)
    ar = rec.attempts[0]
    assert ar.decision == "deny"
    assert ar.produced_audit_entry is False  # blocked → never reaches PostToolUse
    assert rec.ledger.entries[-1].outcome == "blocked"


def test_tier3_unknown_tool_denied_tool_not_found():
    sc = Scenario(name="t3", description="", attempts=[
        Attempt(tool_name="delete_everything", tool_input={}),
    ])
    rec = run_scenario(sc)
    ar = rec.attempts[0]
    assert ar.tier == Tier.THREE.value
    assert ar.decision == "deny"
    assert "tool-not-found" in (ar.reason or "").lower()


def test_engine_mcp_tool_resolves_to_tier1_through_real_registry():
    # The Slice-1 engine server is wired into the real cage; its MCP-namespaced
    # name must resolve to Tier-1 and require justification.
    sc = Scenario(name="engine", description="", attempts=[
        Attempt(tool_name="mcp__engine__run_review_chain", tool_input={}, justification=GOOD_JUST),
        Attempt(tool_name="mcp__engine__run_review_chain", tool_input={}),  # no justification
    ])
    rec = run_scenario(sc)
    assert rec.attempts[0].tier == Tier.ONE.value
    assert rec.attempts[0].decision == "allow"
    assert rec.attempts[1].decision == "deny"


def test_approved_tier2_execution_routes_to_sealed_ledger():
    sc = Scenario(
        name="seal",
        description="",
        attempts=[Attempt(tool_name="read_ledger", tool_input={})],
        approved_executions=[
            Tier2Execution(
                action="seal_bundle",
                justification="human approved seal at audit close",
                evidence_refs=["audit/compile.json"],
                inputs={"client_id": "sbodemosg"},
            )
        ],
    )
    rec = run_scenario(sc)
    assert len(rec.executions) == 1
    assert rec.executions[0].action == "seal_bundle"
    assert rec.executions[0].success is True
    # Tier-2 outcome on sealed ledger; NOT in audit_log
    tier2 = [e for e in rec.ledger.entries if e.tier == Tier.TWO.value]
    assert len(tier2) == 1
    assert all(e["tool_name"] != "seal_bundle" for e in rec.audit_log)
    rec.ledger.verify()


def test_engine_invoker_never_called_during_eval():
    # The eval path is hooks-only; the engine chain handler must never fire.
    sc = Scenario(name="noinvoke", description="", attempts=[
        Attempt(tool_name="mcp__engine__run_review_chain", tool_input={}, justification=GOOD_JUST),
    ])
    rec = run_scenario(sc)  # must not raise (invoker is never called)
    assert rec.attempts[0].decision == "allow"
