"""
tests/test_t55b_demo_wiring.py — T5.5b decision-ledger demo wiring.

Two halves, mock-first and GATED:

  READ (the demoable behaviour): a SEEDED prior-period KNOWN_ACCEPTED entry
  (demo-artifacts/decision-ledger.json) makes the matching CURRENT finding render
  DEMOTED + ANNOTATED in the adjudication panel — yet STILL PRESENT (Invariant 5:
  never suppress). annotate_and_demote runs at view-model time over the panel findings;
  the frozen dossiers.json is NEVER mutated and the F5 boxes stay byte-unchanged.

  WRITE (the capability): record_adjudication is a Tier-2, approved-only executor handler
  that appends an AdjudicationEntry to the DecisionLedger ONLY on human approval. The
  agent never writes the ledger — get_tier("record_adjudication") -> Tier.THREE (absent).
  Built + hermetically tested here; the panel-adjudicate -> append loop is a FOLLOW-ON.

Decision ledger applies to DETERMINISTIC findings only; show_ai_candidates /
VALIDATION_STATUS stay frozen.
"""
from __future__ import annotations

import copy
import json
from dataclasses import fields
from pathlib import Path

import pytest

from agent.decision_ledger import (
    KNOWN_ACCEPTED,
    AdjudicationEntry,
    DecisionLedger,
    compute_finding_fingerprint,
)
from agent.executor import (
    Executor,
    ExecutorError,
    build_adjudication_proposal,
    make_tier2_handlers,
)
from agent.ledger import Ledger
from agent.proposals import StagingStore
from agent.registry import get_tier
from agent.schemas import Tier
from ui.artifacts import (
    VALIDATION_STATUS,
    annotated_adjudication_items,
    load_demo_artifacts,
)

_ARTIFACTS = Path(__file__).resolve().parent / "fixtures" / "demo-artifacts"

# The seeded prior-period adjudication keys on this real, genuinely-unregistered vendor.
_SEED_CODE = "NO_GST_REG"
_SEED_CARD = "Far East Imports"
_SEED_FINDING_ID = "detect:NO_GST_REG:592"


def _load(name: str):
    return json.loads((_ARTIFACTS / name).read_text(encoding="utf-8"))


# ── READ: seeded prior-period KNOWN_ACCEPTED → demoted + annotated, still present ──────

def test_seeded_known_accepted_demotes_matching_finding_still_present():
    arts = load_demo_artifacts()
    items = annotated_adjudication_items(arts)

    # never-suppress / cardinality-preserving: one panel item per dossier.
    assert len(items) == len(arts.dossiers)

    by_fid = {it["finding_id"]: it for it in items}
    target = by_fid[_SEED_FINDING_ID]

    # The recurring KNOWN_ACCEPTED finding renders demoted + annotated, STILL PRESENT.
    assert target["demoted"] is True
    assert target["annotation"]
    assert KNOWN_ACCEPTED in target["prior_dispositions"]


def test_other_counterparties_not_demoted():
    """The fingerprint keys on (error_code, counterparty) — a different NO_GST_REG vendor
    must NOT be demoted by the seed for Far East Imports."""
    arts = load_demo_artifacts()
    items = annotated_adjudication_items(arts)
    by_fid = {it["finding_id"]: it for it in items}

    other = by_fid["detect:NO_GST_REG:605"]  # Acme Associates — not seeded
    assert other["demoted"] is False
    assert other["annotation"] is None
    assert other["prior_dispositions"] == ()


def test_demoted_items_ordered_after_non_demoted():
    arts = load_demo_artifacts()
    items = annotated_adjudication_items(arts)
    demoted_flags = [it["demoted"] for it in items]
    # all non-demoted precede all demoted (stable demote-to-bottom ordering).
    assert demoted_flags == sorted(demoted_flags, key=lambda d: d)


def test_probabilistic_item_untouched_by_decision_ledger():
    """Decision ledger applies to DETERMINISTIC findings only."""
    arts = load_demo_artifacts()
    items = annotated_adjudication_items(arts)
    prob = [it for it in items if it["finding_type"] == "probabilistic"]
    assert prob, "expected the crafted probabilistic candidate in the panel"
    for it in prob:
        assert it["demoted"] is False
        assert it["annotation"] is None


# ── BOX-ISOLATION: compile_output / F5 boxes byte-unchanged through the view path ──────

def test_compile_output_and_f5_boxes_byte_unchanged_through_view():
    arts = load_demo_artifacts()
    before = copy.deepcopy(arts.review_result["compile_output"])
    before_bytes = json.dumps(before, sort_keys=True, ensure_ascii=False)

    annotated_adjudication_items(arts)  # run the annotate-demote view path

    after_bytes = json.dumps(
        arts.review_result["compile_output"], sort_keys=True, ensure_ascii=False
    )
    assert after_bytes == before_bytes
    # F5 boxes specifically.
    assert arts.review_result["compile_output"]["declared_f5_findings"] == \
        before["declared_f5_findings"]


# ── WRITE: record_adjudication — Tier-2, approved-only, agent-absent ───────────────────

def _approved_only_setup():
    decision_ledger = DecisionLedger()
    store = StagingStore()
    handlers = make_tier2_handlers(
        Ledger(),
        seal_fn=lambda **_: None,
        emit_fn=lambda **_: None,
        decision_ledger=decision_ledger,
    )
    executor = Executor(store, extra_handlers=handlers)
    finding = {"payload": {"error_code": _SEED_CODE, "card_name": _SEED_CARD}}
    proposal = build_adjudication_proposal(
        finding=finding,
        disposition=KNOWN_ACCEPTED,
        reviewer="Jane Tan",
        reason="Supplier confirmed not GST-registered; input tax correctly not claimed.",
        period="2024Q3",
    )
    store.stage(proposal)
    return decision_ledger, store, executor, proposal, finding


def test_record_adjudication_appends_only_after_approval():
    decision_ledger, store, executor, proposal, finding = _approved_only_setup()

    # Pending → execute is refused (approved-only).
    with pytest.raises(ExecutorError):
        executor.execute(proposal.proposal_id)
    assert decision_ledger.entries == []

    # Approve → execute appends exactly one AdjudicationEntry, keyed to the fingerprint.
    store.approve(proposal.proposal_id)
    result = executor.execute(proposal.proposal_id)
    assert result.success
    assert len(decision_ledger.entries) == 1
    entry = decision_ledger.entries[0]
    assert entry.fingerprint == compute_finding_fingerprint(finding)
    assert entry.disposition == KNOWN_ACCEPTED
    assert entry.reviewer == "Jane Tan"
    decision_ledger.verify()  # chain intact


def test_record_adjudication_inputs_hash_carries_fingerprint():
    """v0/PROVISIONAL shim: proposal.inputs_hash carries the finding fingerprint."""
    finding = {"payload": {"error_code": _SEED_CODE, "card_name": _SEED_CARD}}
    proposal = build_adjudication_proposal(
        finding=finding,
        disposition=KNOWN_ACCEPTED,
        reviewer="Jane Tan",
        reason="standing treatment",
        period="2024Q3",
    )
    assert proposal.inputs_hash == compute_finding_fingerprint(finding)
    assert proposal.tier == Tier.TWO.value


def test_record_adjudication_absent_from_agent_registry():
    """The agent has no adjudication tool — a ledger WRITE is a human action, Tier-3 absent."""
    assert get_tier("record_adjudication") is Tier.THREE


def test_handlers_omit_record_adjudication_without_decision_ledger():
    """Backward compatible: no decision_ledger -> only seal/emit handlers."""
    handlers = make_tier2_handlers(
        Ledger(), seal_fn=lambda **_: None, emit_fn=lambda **_: None
    )
    assert set(handlers) == {"seal_bundle", "emit_final_pdf"}


# ── Frozen-flag + tripwire guards still hold ──────────────────────────────────────────

def test_frozen_dossiers_do_not_carry_demote_annotation():
    """annotate-demote is computed at view-model time, NEVER baked into dossiers.json."""
    dossiers = _load("dossiers.json")
    for d in dossiers:
        assert "demoted" not in d
        assert "annotation" not in d


def test_decision_ledger_fixture_keys_match_adjudication_entry():
    entries = _load("decision-ledger.json")
    assert entries, "seeded decision-ledger fixture is empty"
    expected = {f.name for f in fields(AdjudicationEntry)}
    for e in entries:
        assert set(e.keys()) == expected


def test_validation_status_frozen_unchanged():
    assert VALIDATION_STATUS == "unvalidated"
