"""T5.9d — Dispatch-execution: the pure execution layer behind the intent router.

The intent router (agent/intent.py::dispatch) classifies a (validated) intent +
explicitly-bound params and returns its tier-classified action SEQUENCE — but it
does NOT execute anything. This slice adds agent/dispatch_exec.py::execute_intent,
a pure, framework-free executor that actually RUNS the Tier-0 read(s) / RUN_REVIEW
over the FROZEN demo artifacts and returns a serialisable ExecutionResult.

No surface wiring here (the production surface is React; this module is surfaced at
Lane C2's POST /command, not Streamlit). SAP stays off; the engine is the frozen
mock; no tokens, no live chain. The invariants under test:

  (a) Each menu intent EXECUTES and returns the REAL frozen rows (not a re-derived
      projection): SHOW_LEDGER → the justification ledger; SHOW_PROPOSALS → the
      PENDING staging queue; SHOW_PRIOR_ADJUDICATIONS → the decision ledger
      (list-all; honest menu-gap flag); RUN_REVIEW → the frozen engine output
      (frozen dossiers + F5 summary), no SAP / no live chain.
  (b) A blank identity slot (client_id / period) passes the router's
      NeedsClarification straight through — the executor never guesses.
  (c) An unknown intent is rejected (IntentError) — the ⊆-MENU invariant holds
      through the executor.
  (d) BOX ISOLATION: the F5 boxes + gate results are byte-identical before/after
      execution — RUN_REVIEW is a read, it never recomputes or mutates them.
  (e) PURITY: agent/dispatch_exec.py imports no anthropic / streamlit / fastapi /
      SAP / network module, and does not reach into orchestrator/ or ui/.
  (f) The ExecutionResult is JSON-serialisable unchanged (so C2 can return it).

Hermetic: frozen artifacts only, no live model, no SAP, no tokens.
"""
from __future__ import annotations

import ast
import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from agent.dispatch_exec import (
    DEMO_ARTIFACTS_DIR,
    ExecutionResult,
    FrozenEngine,
    execute_intent,
    load_frozen_artifacts,
)
from agent.intent import IntentError

# A doc-592 anchor from the seeded decision-ledger fixture (KNOWN_ACCEPTED).
_DOC592_FINGERPRINT = (
    "sha256:3d87ffc03f96938b1dbf236e133515595b514b099397deabae8e8ec1d15ed715"
)


@pytest.fixture
def artifacts():
    return load_frozen_artifacts()


# --------------------------------------------------------------------------- #
# (a) each intent executes and returns the REAL frozen rows
# --------------------------------------------------------------------------- #

def test_show_ledger_executes_returns_frozen_ledger_rows(artifacts):
    result = execute_intent("SHOW_LEDGER", {"client_id": "ACME"}, artifacts=artifacts)
    assert result.outcome == "executed"
    assert result.sequence == ("read_ledger",)
    assert result.tiers == (0,)  # read_ledger is Tier-0
    rows = result.data["ledger"]
    # Real rows, same cardinality as the frozen ledger, same chain order.
    assert len(rows) == len(artifacts.ledger)
    assert rows[0]["entry_id"] == artifacts.ledger[0]["entry_id"]
    assert rows[0]["tool_name"] == artifacts.ledger[0]["tool_name"]
    assert set(rows[0]) == {
        "entry_id", "tool_name", "tier", "outcome",
        "justification", "blocked_reason", "timestamp",
    }


def test_show_proposals_executes_returns_pending_queue(artifacts):
    result = execute_intent("SHOW_PROPOSALS", {"client_id": "ACME"}, artifacts=artifacts)
    assert result.outcome == "executed"
    assert result.sequence == ("read_proposals",)
    rows = result.data["proposals"]
    # All frozen proposals are pending; the read returns them all, in store order.
    assert len(rows) == len(artifacts.proposals)
    assert all(r["status"] == "pending" for r in rows)
    assert rows[0]["proposal_id"] == artifacts.proposals[0]["proposal_id"]


def test_show_prior_adjudications_listall_returns_seeded_doc592(artifacts):
    result = execute_intent(
        "SHOW_PRIOR_ADJUDICATIONS",
        {"client_id": "ACME", "period": "2024Q2"},
        artifacts=artifacts,
    )
    assert result.outcome == "executed"
    assert result.sequence == ("read_decision_ledger",)
    rows = result.data["adjudications"]
    # List-all returns the one seeded prior adjudication: doc-592 KNOWN_ACCEPTED.
    assert len(rows) == len(artifacts.decision_ledger)
    entry = rows[0]
    assert entry["disposition"] == "KNOWN_ACCEPTED"
    assert entry["fingerprint"] == _DOC592_FINGERPRINT
    assert entry["reviewer"] == "Prior-Period Reviewer"
    # The menu-gap (no client/period axis) is flagged honestly, not silently dropped.
    assert result.notes, "expected the SHOW_PRIOR_ADJUDICATIONS menu-gap note"
    assert any("list-all" in n.lower() for n in result.notes)


def test_show_prior_adjudications_does_not_filter_by_bound_params(artifacts):
    """The bound client_id/period gate dispatch but do NOT filter the ledger.

    Honest menu-gap behaviour: a different (non-2024Q2) period still returns the
    same list-all rows — the executor fabricates no client/period->fingerprint map.
    """
    a = execute_intent(
        "SHOW_PRIOR_ADJUDICATIONS", {"client_id": "ACME", "period": "2024Q2"},
        artifacts=artifacts,
    )
    b = execute_intent(
        "SHOW_PRIOR_ADJUDICATIONS", {"client_id": "OTHER", "period": "2099Q4"},
        artifacts=artifacts,
    )
    assert a.data["adjudications"] == b.data["adjudications"]


def test_run_review_returns_frozen_engine_output(artifacts):
    result = execute_intent(
        "RUN_REVIEW", {"client_id": "ACME", "period": "2024Q4"}, artifacts=artifacts
    )
    assert result.outcome == "executed"
    assert result.sequence == ("run_review_chain",)
    assert result.tiers == (1,)  # run_review_chain is Tier-1 (staging)
    # Frozen engine output: review_result + dossiers verbatim, no live chain / no SAP.
    assert result.data["review_result"] == artifacts.review_result
    assert result.data["dossiers"] == artifacts.dossiers
    f5 = result.data["f5_summary"]
    assert f5["boxes"] == artifacts.review_result["compile_output"]["calculate"]["boxes"]
    assert f5["gate_results"] == artifacts.review_result["gate_results"]


def test_run_review_uses_injected_frozen_engine(artifacts):
    """An explicitly injected FrozenEngine drives RUN_REVIEW (parity, no SAP)."""
    engine = FrozenEngine(artifacts.review_result)
    result = execute_intent(
        "RUN_REVIEW", {"client_id": "ACME", "period": "2024Q4"},
        artifacts=artifacts, engine=engine,
    )
    assert result.data["review_result"] == artifacts.review_result


# --------------------------------------------------------------------------- #
# (b) NeedsClarification passthrough — never guess client_id / period
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "intent, params, missing",
    [
        ("SHOW_LEDGER", {"client_id": "   "}, ["client_id"]),
        ("SHOW_LEDGER", {}, ["client_id"]),
        ("RUN_REVIEW", {"client_id": "ACME", "period": ""}, ["period"]),
        ("SHOW_PRIOR_ADJUDICATIONS", {}, ["client_id", "period"]),
    ],
)
def test_needs_clarification_passthrough(artifacts, intent, params, missing):
    result = execute_intent(intent, params, artifacts=artifacts)
    assert result.outcome == "needs_clarification"
    assert result.data["missing_params"] == missing
    assert "data" in asdict(result) and result.data["message"]
    # No execution happened: no rows surfaced.
    assert "ledger" not in result.data and "review_result" not in result.data


# --------------------------------------------------------------------------- #
# (c) ⊆-MENU invariant holds through the executor
# --------------------------------------------------------------------------- #

def test_unknown_intent_raises(artifacts):
    with pytest.raises(IntentError):
        execute_intent("DROP_TABLES", {"client_id": "ACME"}, artifacts=artifacts)


def test_raw_tool_name_is_not_an_intent(artifacts):
    with pytest.raises(IntentError):
        execute_intent("read_ledger", {"client_id": "ACME"}, artifacts=artifacts)


# --------------------------------------------------------------------------- #
# (d) BOX ISOLATION — F5 boxes + gate results byte-identical before/after
# --------------------------------------------------------------------------- #

def test_box_isolation_byte_identical_across_all_intents(artifacts):
    boxes_before = copy.deepcopy(
        artifacts.review_result["compile_output"]["calculate"]["boxes"]
    )
    gates_before = copy.deepcopy(artifacts.review_result["gate_results"])

    execute_intent("RUN_REVIEW", {"client_id": "A", "period": "P"}, artifacts=artifacts)
    execute_intent("SHOW_LEDGER", {"client_id": "A"}, artifacts=artifacts)
    execute_intent("SHOW_PROPOSALS", {"client_id": "A"}, artifacts=artifacts)
    execute_intent(
        "SHOW_PRIOR_ADJUDICATIONS", {"client_id": "A", "period": "P"}, artifacts=artifacts
    )

    assert artifacts.review_result["compile_output"]["calculate"]["boxes"] == boxes_before
    assert artifacts.review_result["gate_results"] == gates_before


def test_run_review_result_is_isolated_from_source(artifacts):
    """Mutating the returned review_result must not bleed into the frozen source."""
    result = execute_intent(
        "RUN_REVIEW", {"client_id": "A", "period": "P"}, artifacts=artifacts
    )
    result.data["review_result"]["compile_output"]["calculate"]["boxes"]["box_8_net_gst"] = -999
    assert (
        artifacts.review_result["compile_output"]["calculate"]["boxes"]["box_8_net_gst"]
        != -999
    )


# --------------------------------------------------------------------------- #
# (e) PURITY — AST import scan; orchestrator/ + ui/ not reached
# --------------------------------------------------------------------------- #

_BANNED_IMPORT_ROOTS = {
    "anthropic", "streamlit", "fastapi", "requests", "httpx", "urllib",
    "socket", "aiohttp", "orchestrator", "ui",
    # SAP / Service Layer surfaces
    "sap", "sap_client", "service_layer",
}


def _module_path() -> Path:
    import agent.dispatch_exec as m
    return Path(m.__file__)


def test_dispatch_exec_imports_are_pure():
    tree = ast.parse(_module_path().read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
    leaked = roots & _BANNED_IMPORT_ROOTS
    assert not leaked, f"dispatch_exec.py leaked banned imports: {sorted(leaked)}"


def test_dispatch_exec_source_mentions_no_sap_network():
    src = _module_path().read_text(encoding="utf-8").lower()
    for needle in ("import anthropic", "import streamlit", "import fastapi", "service_layer"):
        assert needle not in src


# --------------------------------------------------------------------------- #
# (f) serialisable unchanged
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "intent, params",
    [
        ("SHOW_LEDGER", {"client_id": "A"}),
        ("SHOW_PROPOSALS", {"client_id": "A"}),
        ("SHOW_PRIOR_ADJUDICATIONS", {"client_id": "A", "period": "P"}),
        ("RUN_REVIEW", {"client_id": "A", "period": "P"}),
        ("SHOW_LEDGER", {}),  # needs_clarification path
    ],
)
def test_execution_result_is_json_serialisable(artifacts, intent, params):
    result = execute_intent(intent, params, artifacts=artifacts)
    assert isinstance(result, ExecutionResult)
    blob = json.dumps(result.to_dict())
    assert json.loads(blob)["intent"] == result.intent
