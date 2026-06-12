"""
agent/proposals.py — ProposalArtifact construction, validation, and staging store.

Public API:
    build_proposal(action, justification, evidence_refs, inputs) -> ProposalArtifact
    validate_proposal(artifact)  — raises ProposalValidationError on invalid artifact
    ProposalValidationError      — validation failure
    StagingStore                 — in-memory pending/approved/rejected proposal store

The inputs_hash is sha256( canonical_json(inputs) ) so the proposal is anchored
to the specific run state at proposal time. This reuses the same hash primitives
as audit_bundle.canonical — sha256 + canonical JSON.

Zero anthropic import. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from agent.schemas import ProposalArtifact, Tier


class ProposalValidationError(ValueError):
    """Raised when a ProposalArtifact fails schema validation."""


def _canonical_json(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_proposal(
    *,
    action: str,
    justification: str,
    evidence_refs: list,
    inputs: dict,
) -> ProposalArtifact:
    """Build and return a validated ProposalArtifact.

    Args:
        action:        What the executor should perform (e.g. "seal_bundle").
        justification: Why this action is being proposed. Must be non-empty.
        evidence_refs: List of evidence pointers (file paths, doc nums). Must be non-empty.
        inputs:        Dict of inputs the proposal depends on; hashed for anchoring.

    Returns:
        ProposalArtifact with status="pending".

    Raises:
        ProposalValidationError: If justification is empty or evidence_refs is empty.
    """
    if not justification or not justification.strip():
        raise ProposalValidationError("justification must be non-empty")
    if not evidence_refs:
        raise ProposalValidationError("evidence_refs must be non-empty")

    inputs_hash = _sha256_bytes(_canonical_json(inputs))
    artifact = ProposalArtifact(
        proposal_id=str(uuid.uuid4()),
        action=action,
        tier=Tier.TWO.value,
        justification=justification,
        evidence_refs=list(evidence_refs),
        inputs_hash=inputs_hash,
        status="pending",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return artifact


def validate_proposal(artifact: ProposalArtifact) -> None:
    """Validate a ProposalArtifact schema. Raises ProposalValidationError on failure.

    Checks:
        - tier must be Tier.TWO.value (2)
        - justification must be non-empty
        - evidence_refs must be non-empty
        - status must be one of pending/approved/rejected
        - inputs_hash must start with "sha256:"
    """
    if artifact.tier != Tier.TWO.value:
        raise ProposalValidationError(
            f"ProposalArtifact.tier must be {Tier.TWO.value}, got {artifact.tier}"
        )
    if not artifact.justification or not artifact.justification.strip():
        raise ProposalValidationError("ProposalArtifact.justification must be non-empty")
    if not artifact.evidence_refs:
        raise ProposalValidationError("ProposalArtifact.evidence_refs must be non-empty")
    if artifact.status not in ("pending", "approved", "rejected"):
        raise ProposalValidationError(
            f"ProposalArtifact.status must be pending/approved/rejected, got {artifact.status!r}"
        )
    if not artifact.inputs_hash.startswith("sha256:"):
        raise ProposalValidationError(
            f"ProposalArtifact.inputs_hash must start with 'sha256:', got {artifact.inputs_hash!r}"
        )


class StagingStore:
    """In-memory store for pending/approved/rejected proposals.

    CLI-first approval mechanism: stage → list_pending → approve/reject by ID.
    Rich UI is deferred; the mechanism is not.
    """

    def __init__(self) -> None:
        self._store: dict[str, ProposalArtifact] = {}

    def stage(self, artifact: ProposalArtifact) -> None:
        """Stage a proposal. Validates before storing."""
        validate_proposal(artifact)
        self._store[artifact.proposal_id] = artifact

    def get(self, proposal_id: str) -> Optional[ProposalArtifact]:
        """Return the proposal with the given ID, or None if not found."""
        return self._store.get(proposal_id)

    def list_pending(self) -> list[ProposalArtifact]:
        """Return all proposals with status='pending'."""
        return [a for a in self._store.values() if a.status == "pending"]

    def approve(self, proposal_id: str) -> ProposalArtifact:
        """Approve a pending proposal. Raises KeyError if not found."""
        artifact = self._store[proposal_id]
        artifact.status = "approved"
        return artifact

    def reject(self, proposal_id: str) -> ProposalArtifact:
        """Reject a pending proposal. Raises KeyError if not found."""
        artifact = self._store[proposal_id]
        artifact.status = "rejected"
        return artifact
