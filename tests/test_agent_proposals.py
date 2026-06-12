"""
tests/test_agent_proposals.py — T-8: ProposalArtifact schema round-trips and validation.

No SDK, no SAP, no network.
"""
from __future__ import annotations

import json

import pytest

from agent.proposals import (
    build_proposal,
    validate_proposal,
    ProposalValidationError,
    StagingStore,
)
from agent.schemas import Tier


# ---------------------------------------------------------------------------
# T-8  ProposalArtifact schema: valid round-trips; missing required field rejected
# ---------------------------------------------------------------------------

VALID_KWARGS = dict(
    action="seal_bundle",
    justification="All five gates passed; audit chain complete for sbodemosg Q3 2024. Sealing for reviewer handoff.",
    evidence_refs=["audit/sbodemosg/2024-07-01_2024-09-30/compile-output.json"],
    inputs={"client_id": "sbodemosg", "period": {"start": "2024-07-01", "end": "2024-09-30"}},
)


class TestProposalArtifactRoundTrip:
    def test_build_produces_valid_artifact(self):
        artifact = build_proposal(**VALID_KWARGS)
        assert artifact.tier == Tier.TWO.value
        assert artifact.status == "pending"
        assert artifact.proposal_id  # non-empty
        assert artifact.created_at   # non-empty ISO string
        assert artifact.inputs_hash.startswith("sha256:")

    def test_json_round_trip(self):
        artifact = build_proposal(**VALID_KWARGS)
        data = json.loads(json.dumps(artifact.__dict__))
        assert data["action"] == "seal_bundle"
        assert data["tier"] == 2
        assert data["status"] == "pending"
        assert data["inputs_hash"].startswith("sha256:")

    def test_two_proposals_with_same_inputs_have_same_inputs_hash(self):
        a = build_proposal(**VALID_KWARGS)
        b = build_proposal(**VALID_KWARGS)
        assert a.inputs_hash == b.inputs_hash

    def test_two_proposals_have_different_ids(self):
        a = build_proposal(**VALID_KWARGS)
        b = build_proposal(**VALID_KWARGS)
        assert a.proposal_id != b.proposal_id

    def test_validate_passes_on_valid_artifact(self):
        artifact = build_proposal(**VALID_KWARGS)
        validate_proposal(artifact)  # must not raise

    def test_evidence_refs_preserved(self):
        artifact = build_proposal(**VALID_KWARGS)
        assert artifact.evidence_refs == VALID_KWARGS["evidence_refs"]


class TestProposalMissingFieldRejected:
    def test_missing_action_rejected(self):
        kwargs = {**VALID_KWARGS}
        kwargs.pop("action")
        with pytest.raises((TypeError, ProposalValidationError)):
            build_proposal(**kwargs)

    def test_missing_justification_rejected(self):
        kwargs = {**VALID_KWARGS}
        kwargs.pop("justification")
        with pytest.raises((TypeError, ProposalValidationError)):
            build_proposal(**kwargs)

    def test_empty_justification_rejected(self):
        with pytest.raises(ProposalValidationError):
            build_proposal(**{**VALID_KWARGS, "justification": ""})

    def test_empty_evidence_refs_rejected(self):
        with pytest.raises(ProposalValidationError):
            build_proposal(**{**VALID_KWARGS, "evidence_refs": []})

    def test_wrong_tier_rejected(self):
        artifact = build_proposal(**VALID_KWARGS)
        artifact.tier = Tier.ONE.value  # tamper to Tier 1
        with pytest.raises(ProposalValidationError):
            validate_proposal(artifact)


class TestStagingStore:
    def test_store_and_list_pending(self):
        store = StagingStore()
        a = build_proposal(**VALID_KWARGS)
        store.stage(a)
        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].proposal_id == a.proposal_id

    def test_approve_transitions_status(self):
        store = StagingStore()
        a = build_proposal(**VALID_KWARGS)
        store.stage(a)
        store.approve(a.proposal_id)
        assert store.get(a.proposal_id).status == "approved"

    def test_reject_transitions_status(self):
        store = StagingStore()
        a = build_proposal(**VALID_KWARGS)
        store.stage(a)
        store.reject(a.proposal_id)
        assert store.get(a.proposal_id).status == "rejected"

    def test_approved_not_in_pending(self):
        store = StagingStore()
        a = build_proposal(**VALID_KWARGS)
        store.stage(a)
        store.approve(a.proposal_id)
        assert len(store.list_pending()) == 0

    def test_get_unknown_id_returns_none(self):
        store = StagingStore()
        assert store.get("nonexistent-id") is None
