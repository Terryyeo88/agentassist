"""
tests/test_t58_artifact_contract.py — T5.8 schema-stability tripwire (T5.3h coordination).

T5.8 runs in parallel with t5.3h-loop-context. The DossierArtifact / ProposalArtifact /
ReviewResult schemas already exist; this test FREEZES their serialised field shape so
that if t5.3h changes any field, the change fails CI on its PR — an explicit re-pin
event, not a silent break.

Two layers of pinning:
  1. The dataclass field-NAME sets (dataclasses.fields) — robust to Path/callable fields
     that cannot be JSON-serialised.
  2. The frozen demo-artifact JSON keys (tests/fixtures/demo-artifacts/*.json) match the
     same field sets — proving the artifacts the UI loads share the contract shape.

If a contract field is intentionally added/removed, update the FROZEN_* sets here AND
regenerate the demo artifacts (python -m tests.fixtures.demo_artifacts_builder). That
edit is the deliberate re-pin.
"""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from agent.dossier import DossierArtifact, Finding
from agent.ledger import LedgerEntry
from agent.executor import ExecutionResult
from agent.schemas import ProposalArtifact
from engine.review import GateHalt, ReviewInputs, ReviewResult

_ARTIFACTS = Path(__file__).resolve().parent / "fixtures" / "demo-artifacts"

# ── Frozen field-name sets (the contract shapes T5.8 pins for T5.3h) ──────────────
FROZEN_REVIEW_RESULT = {
    "status", "compile_output", "gate_results", "reasoning_artefact",
    "document_candidates", "analytical_review_data", "report_pdf_path",
    "bundle_dir", "run_started_at", "run_completed_at", "gate_failure",
}
FROZEN_REVIEW_INPUTS = {"line_source", "provider", "declared_f5", "analytical_review"}
FROZEN_GATE_HALT = {"message", "checked"}
FROZEN_DOSSIER = {
    "finding_id", "check_id", "finding_type", "evidence",
    "candidate_framing_text", "completeness", "inputs_hash",
}
FROZEN_FINDING = {"finding_id", "check_id", "finding_type", "source", "payload"}
FROZEN_PROPOSAL = {
    "proposal_id", "action", "tier", "justification", "evidence_refs",
    "inputs_hash", "status", "created_at",
}
FROZEN_LEDGER_ENTRY = {
    "entry_id", "tool_name", "tier", "justification", "call_params",
    "outcome", "blocked_reason", "timestamp", "prev_hash", "entry_hash",
}
FROZEN_EXECUTION_RESULT = {"proposal_id", "action", "success", "detail"}


def _field_names(cls) -> set[str]:
    return {f.name for f in fields(cls)}


@pytest.mark.parametrize("cls,frozen", [
    (ReviewResult, FROZEN_REVIEW_RESULT),
    (ReviewInputs, FROZEN_REVIEW_INPUTS),
    (GateHalt, FROZEN_GATE_HALT),
    (DossierArtifact, FROZEN_DOSSIER),
    (Finding, FROZEN_FINDING),
    (ProposalArtifact, FROZEN_PROPOSAL),
    (LedgerEntry, FROZEN_LEDGER_ENTRY),
    (ExecutionResult, FROZEN_EXECUTION_RESULT),
])
def test_contract_field_set_is_frozen(cls, frozen):
    """The dataclass field-name set must match the frozen contract shape.

    A diff here means t5.3h (or anyone) changed a shared contract field — re-pin
    deliberately by updating the FROZEN_* set and the demo fixtures together.
    """
    assert _field_names(cls) == frozen, (
        f"{cls.__name__} field set changed: {_field_names(cls) ^ frozen}"
    )


def _load(name: str):
    return json.loads((_ARTIFACTS / name).read_text(encoding="utf-8"))


def test_frozen_review_result_keys_match_contract():
    rr = _load("review_result.json")
    assert set(rr.keys()) == FROZEN_REVIEW_RESULT


def test_frozen_dossier_keys_match_contract():
    dossiers = _load("dossiers.json")
    assert dossiers, "demo dossiers fixture is empty"
    for d in dossiers:
        assert set(d.keys()) == FROZEN_DOSSIER


def test_frozen_proposal_keys_match_contract():
    proposals = _load("proposals.json")
    assert proposals, "demo proposals fixture is empty"
    for p in proposals:
        assert set(p.keys()) == FROZEN_PROPOSAL


def test_frozen_ledger_keys_match_contract():
    ledger = _load("ledger.json")
    assert ledger, "demo ledger fixture is empty"
    for e in ledger:
        assert set(e.keys()) == FROZEN_LEDGER_ENTRY
