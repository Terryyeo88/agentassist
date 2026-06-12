"""
agent/ledger.py — Append-only hash-chained justification ledger.

Reuses audit_bundle.canonical primitives (canonical_json, sha256_bytes) for the
hash chain — same construction as the T1.5 audit bundle, not reinvented.

Hash chain construction:
    genesis prev_hash = "sha256:" + "0" * 64
    entry_hash[n] = sha256_bytes(
        canonical_json(entry_fields_without_hash) + b"|" + prev_hash.encode()
    )

verify() re-derives each entry_hash and checks both the hash and the chain link.
Any tamper (field mutation, entry deletion) breaks the chain and raises
LedgerVerificationError.

Public API:
    Ledger                  — in-memory append-only ledger
    LedgerVerificationError — raised by verify() on chain break or hash mismatch

Zero anthropic import. Stdlib only (hashlib, json, uuid, datetime).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
import uuid

from agent.schemas import LedgerEntry, Tier

_GENESIS_HASH = "sha256:" + "0" * 64


def _canonical_json(obj: dict) -> bytes:
    """Deterministic JSON bytes — same rules as audit_bundle.canonical.canonical_json."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _compute_entry_hash(entry_fields: dict, prev_hash: str) -> str:
    """Compute entry_hash = sha256( canonical_json(fields) + b"|" + prev_hash )."""
    payload = _canonical_json(entry_fields) + b"|" + prev_hash.encode("utf-8")
    return _sha256_bytes(payload)


def _entry_fields_without_hash(entry: LedgerEntry) -> dict:
    """Return the entry fields that are inputs to entry_hash (excludes entry_hash itself)."""
    return {
        "blocked_reason": entry.blocked_reason,
        "call_params": entry.call_params,
        "entry_id": entry.entry_id,
        "justification": entry.justification,
        "outcome": entry.outcome,
        "prev_hash": entry.prev_hash,
        "tier": entry.tier,
        "timestamp": entry.timestamp,
        "tool_name": entry.tool_name,
    }


class LedgerVerificationError(Exception):
    """Raised by Ledger.verify() when the hash chain is broken or a hash mismatches."""


class Ledger:
    """Append-only in-memory hash-chained justification ledger.

    Entries are never deleted or reordered. verify() re-derives every
    entry_hash and checks the chain; any mutation raises LedgerVerificationError.
    """

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def append(
        self,
        *,
        tool_name: str,
        tier: Tier,
        justification: Optional[str],
        call_params: dict,
        outcome: str,
        blocked_reason: Optional[str],
        timestamp: Optional[str] = None,
    ) -> LedgerEntry:
        """Append a new entry and return it.

        The entry_hash is computed deterministically from all fields (excluding
        entry_hash itself) and the previous entry's hash, chaining the ledger.
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        prev_hash = self.entries[-1].entry_hash if self.entries else _GENESIS_HASH

        # Build fields dict first so entry_hash can be computed over them
        fields = {
            "blocked_reason": blocked_reason,
            "call_params": call_params,
            "entry_id": str(uuid.uuid4()),
            "justification": justification,
            "outcome": outcome,
            "prev_hash": prev_hash,
            "tier": tier.value if isinstance(tier, Tier) else int(tier),
            "timestamp": ts,
            "tool_name": tool_name,
        }
        entry_hash = _compute_entry_hash(fields, prev_hash)

        entry = LedgerEntry(
            entry_id=fields["entry_id"],
            tool_name=fields["tool_name"],
            tier=fields["tier"],
            justification=fields["justification"],
            call_params=fields["call_params"],
            outcome=fields["outcome"],
            blocked_reason=fields["blocked_reason"],
            timestamp=fields["timestamp"],
            prev_hash=fields["prev_hash"],
            entry_hash=entry_hash,
        )
        self.entries.append(entry)
        return entry

    def verify(self) -> None:
        """Re-derive every entry_hash and verify the chain.

        Raises LedgerVerificationError if any entry_hash is wrong or if the
        prev_hash chain is broken (including entries deleted from the middle).
        """
        prev_hash = _GENESIS_HASH
        for i, entry in enumerate(self.entries):
            fields = _entry_fields_without_hash(entry)
            expected_hash = _compute_entry_hash(fields, prev_hash)
            if entry.entry_hash != expected_hash:
                raise LedgerVerificationError(
                    f"entry[{i}] entry_hash mismatch: "
                    f"stored={entry.entry_hash!r}, expected={expected_hash!r}"
                )
            if entry.prev_hash != prev_hash:
                raise LedgerVerificationError(
                    f"entry[{i}] prev_hash chain broken: "
                    f"stored={entry.prev_hash!r}, expected={prev_hash!r}"
                )
            prev_hash = entry.entry_hash

    @classmethod
    def from_entries(cls, entries: list[dict]) -> "Ledger":
        """Reconstruct a Ledger from a list of serialised entry dicts.

        Used to reload a ledger from a sealed steps/agent-ledger.json and run
        verify() on the reconstructed object.  Each dict must have all
        LedgerEntry fields; unrecognised extra keys are ignored.

        Args:
            entries: List of dicts, each matching the LedgerEntry field set.

        Returns:
            A Ledger whose .entries list mirrors the input; ready for verify().
        """
        ledger = cls()
        for d in entries:
            ledger.entries.append(LedgerEntry(
                entry_id=d["entry_id"],
                tool_name=d["tool_name"],
                tier=d["tier"],
                justification=d["justification"],
                call_params=d["call_params"],
                outcome=d["outcome"],
                blocked_reason=d["blocked_reason"],
                timestamp=d["timestamp"],
                prev_hash=d["prev_hash"],
                entry_hash=d["entry_hash"],
            ))
        return ledger
