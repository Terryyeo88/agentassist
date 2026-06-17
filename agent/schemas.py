"""
agent/schemas.py — Pure dataclass/enum schema definitions for the T5.2a enforcement core.

No logic. No imports outside stdlib. Zero anthropic import.

Data model:

    Tier            — action-tier classification enum (0/1/2; 3 = absent)
    ToolSpec        — registry entry for a single agent tool
    CheckSpec       — v1 ratified registry entry for a compliance check
    LedgerEntry     — one hash-chained justification ledger entry
    ProposalArtifact — Tier-2 proposal waiting for human approval
    RunBudget       — per-run turn/cost cap with over-budget signal

Invariant: this file has no side-effects on import. No network, no disk I/O,
no anthropic.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class Tier(enum.IntEnum):
    """Action-tier classification for agent tools.

    Tier 0 (ZERO)  — Observe: read-only, autonomous; every call logged.
    Tier 1 (ONE)   — Work in staging: mandatory justification; PreToolUse hook
                     writes justification to ledger BEFORE execution and blocks
                     if absent or trivial.
    Tier 2 (TWO)   — Propose and hold: agent emits a ProposalArtifact; human
                     approves; DETERMINISTIC EXECUTOR fires. Agent never executes
                     Tier 2 itself — propose_action at Tier 1 is the only path.
    Tier 3 (THREE) — Structurally impossible: these tools DO NOT EXIST in the
                     registry. get_tier() returns THREE for any unknown name so
                     callers can treat "absent" and "forbidden" uniformly.
    """
    ZERO  = 0
    ONE   = 1
    TWO   = 2
    THREE = 3


@dataclass(frozen=True)
class ToolSpec:
    """Registry entry for a single agent tool.

    Attributes:
        name:        Canonical tool name used in LedgerEntry and registry lookups.
        tier:        Tier classification — only ZERO or ONE in the initial registry.
        description: Human-readable description for dossiers and audit trails.
    """
    name: str
    tier: Tier
    description: str


@dataclass(frozen=True)
class CheckSpec:
    """v1 registry entry for a compliance check (T5.2c — ratified coordination contract).

    Reconciled against the real check implementations and frozen as the contract
    T5.4 consumes. check_id, iras_basis, inputs_needed, and finding_schema match
    the live checks; config_keys is the additive applicability field. Collin
    co-owns CheckSpec and ratifies the contract at merge.

    Attributes:
        check_id:       Canonical check identifier ("E1", "SEQ_GAP", …).
        display_name:   Human-readable name for dossiers and reports.
        iras_basis:     IRAS citation or standard reference.
        inputs_needed:  Data sources required to run this check.
        finding_type:   "deterministic" or "probabilistic" (PDF-derived checks).
        finding_schema: Informational field-name map. Not validated at runtime.
        config_keys:    APPLICABILITY gate — the T2.18 ClientConfig scheme flags
                        (actively_makes_exempt_supplies, participates_in_mes,
                        participates_in_igds, reverse_charge_applicable) that must
                        be True for this check to RUN for a given client. Empty
                        list (the default) == the check always applies. This is an
                        applicability gate, NOT routing: report-layer routing (e.g.
                        the exempt Template-4/5 split) stays in report/routing.py
                        and must never move here, or the planner would drop a check
                        for clients that lack the flag. All 14 current checks are
                        unconditional ([]); the field is reserved for future
                        scheme-specific (MES/IGDS/reverse-charge) checks.
    """
    check_id: str
    display_name: str
    iras_basis: str
    inputs_needed: list
    finding_type: str
    finding_schema: dict = field(default_factory=dict)
    config_keys: list = field(default_factory=list)


@dataclass
class LedgerEntry:
    """One entry in the append-only hash-chained justification ledger.

    Attributes:
        entry_id:      UUID4 string — unique per entry.
        tool_name:     Name of the tool called or blocked.
        tier:          Tier.value (int) for JSON-stable serialisation.
        justification: The justification text, or None for Tier-0 calls.
        call_params:   Sanitised call parameters — must never contain credentials.
        outcome:       "allowed" or "blocked".
        blocked_reason: Why the call was blocked, or None.
        timestamp:     ISO-8601 UTC string.
        prev_hash:     "sha256:000…" sentinel for the genesis entry; prior
                       entry's entry_hash for all subsequent entries.
        entry_hash:    sha256( canonical_json(entry_without_hash) + "|" + prev_hash ).
    """
    entry_id: str
    tool_name: str
    tier: int
    justification: Optional[str]
    call_params: dict
    outcome: str
    blocked_reason: Optional[str]
    timestamp: str
    prev_hash: str
    entry_hash: str


@dataclass
class ProposalArtifact:
    """Tier-2 proposal artifact awaiting human approval.

    The agent (Tier 1) emits this via propose_action. A human reviews the
    justification + evidence, then approves or rejects via the staging store.
    On approval, the DETERMINISTIC EXECUTOR (plain Python) performs the action.
    The agent never executes Tier 2 itself.

    Attributes:
        proposal_id:   UUID4 string — unique; used for staging store lookup.
        action:        What the executor should do (e.g. "seal_bundle").
        tier:          Always Tier.TWO.value = 2.
        justification: Why this action is proposed.
        evidence_refs: Pointers to supporting evidence (file paths, doc nums).
        inputs_hash:   sha256( canonical_json(inputs dict) ) — anchors the
                       proposal to the specific run state.
        status:        "pending" | "approved" | "rejected".
        created_at:    ISO-8601 UTC string.
    """
    proposal_id: str
    action: str
    tier: int
    justification: str
    evidence_refs: list
    inputs_hash: str
    status: str
    created_at: str
