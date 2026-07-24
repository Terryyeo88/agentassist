"""tests/test_decision_store.py — t-decision-persistence FAILING-FIRST unit tests.

BUILD ID: t-decision-persistence. These tests are written BEFORE the implementation and
MUST fail today for the RIGHT reason: ``agent.decision_store`` does not exist yet, so the
top-level import raises ModuleNotFoundError. They pass once the module is built to the
pinned contract.

HARD INVARIANTS PINNED HERE (the three-times rule — prompt + code + THIS test):
  * APPEND-ONLY / tamper-evident — a change of mind APPENDS a second line; line 1 is left
    BYTE-identical; the on-disk hash chain survives a reload and ``verify()`` catches any
    tamper (mirrors the in-memory DecisionLedger invariant, now durable on disk).
  * PATH-TRAVERSAL GUARD — a client_id that is not ``^[a-z0-9_]+$`` is a ValueError; a
    store path can never escape the decisions root.
  * DISPOSITION VOCABULARY is structural — an unknown disposition propagates ValueError
    from ``DecisionLedger.append`` (never silently written).
  * BOTH addressing modes work — the monkeypatchable module constant ``_DECISIONS_ROOT``
    AND an explicit ``root=`` parameter (mirrors ``audit_bundle.seal._AUDIT_ROOT``).

Pure stdlib + pytest + agent.decision_ledger. No anthropic, no SAP, no network. Hermetic.
"""
from __future__ import annotations

import json

import pytest

import agent.decision_store as decision_store
from agent.decision_ledger import (
    ACCEPTED,
    KNOWN_ACCEPTED,
    REJECTED,
    DecisionLedgerVerificationError,
)
from agent.decision_store import (
    append_decision,
    ledger_path,
    load_decision_entries,
    load_decision_ledger,
)

_FP_A = "sha256:" + "a" * 64
_FP_B = "sha256:" + "b" * 64

#: The dataclasses.asdict shape append_decision returns / persists (one JSON line).
#: t-fingerprint-v1 (hand-authored): fingerprint_version is the 10th key. It records the
#: algorithm the entry's fingerprint was computed under; ABSENT == v0 by definition.
_ENTRY_KEYS = {
    "entry_id",
    "fingerprint",
    "fingerprint_version",
    "disposition",
    "reviewer",
    "reason",
    "period",
    "timestamp",
    "prev_hash",
    "entry_hash",
}


# ── ledger_path — addressing (both modes) + traversal guard ──────────────────────────

def test_ledger_path_uses_root_param(tmp_path):
    assert ledger_path("acme", root=tmp_path) == tmp_path / "acme" / "ledger.jsonl"


def test_ledger_path_uses_module_constant_when_no_root(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_store, "_DECISIONS_ROOT", tmp_path)
    assert ledger_path("acme") == tmp_path / "acme" / "ledger.jsonl"


# ── append_decision — creates the file, round-trips, both addressing modes ────────────

def test_append_creates_one_line_file_and_round_trips_via_root(tmp_path):
    entry = append_decision(
        "acme",
        fingerprint=_FP_A,
        disposition=ACCEPTED,
        reviewer="Collin",
        reason="reviewed",
        period="2024Q3",
        root=tmp_path,
    )
    path = tmp_path / "acme" / "ledger.jsonl"
    assert path.is_file()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    # The returned dict is the full serialized-entry shape.
    assert set(entry) == _ENTRY_KEYS
    assert entry["fingerprint"] == _FP_A
    assert entry["disposition"] == ACCEPTED
    assert entry["reviewer"] == "Collin"

    # Round-trips through the loader byte-for-byte.
    [loaded] = load_decision_entries("acme", root=tmp_path)
    assert loaded == entry


def test_append_uses_module_constant_when_no_root(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_store, "_DECISIONS_ROOT", tmp_path)
    append_decision("acme", fingerprint=_FP_A, disposition=ACCEPTED, reviewer="Collin")
    assert (tmp_path / "acme" / "ledger.jsonl").is_file()
    assert len(load_decision_entries("acme")) == 1


# ── APPEND-ONLY / hash-chain (the load-bearing durability invariant) ──────────────────

def test_change_of_mind_appends_second_line_first_line_byte_identical(tmp_path):
    append_decision("acme", fingerprint=_FP_A, disposition=ACCEPTED, reviewer="Collin",
                    root=tmp_path)
    path = tmp_path / "acme" / "ledger.jsonl"
    before = path.read_text(encoding="utf-8")

    # Same fingerprint, DIFFERENT disposition — a genuine change of mind.
    append_decision("acme", fingerprint=_FP_A, disposition=REJECTED, reviewer="Collin",
                    root=tmp_path)
    after = path.read_text(encoding="utf-8")

    # Append-only: the whole prior file is an exact byte prefix of the new file.
    assert after.startswith(before)
    lines = after.splitlines()
    assert len(lines) == 2
    # Line 1 is untouched byte-for-byte.
    assert lines[0] == before.splitlines()[0]


def test_second_entry_prev_hash_chains_from_first(tmp_path):
    append_decision("acme", fingerprint=_FP_A, disposition=ACCEPTED, reviewer="Collin",
                    root=tmp_path)
    append_decision("acme", fingerprint=_FP_A, disposition=REJECTED, reviewer="Collin",
                    root=tmp_path)
    entries = load_decision_entries("acme", root=tmp_path)
    assert len(entries) == 2
    assert entries[1]["prev_hash"] == entries[0]["entry_hash"]


def test_ledger_verifies_after_disk_round_trip(tmp_path):
    for disp in (ACCEPTED, REJECTED, KNOWN_ACCEPTED, ACCEPTED):
        append_decision("acme", fingerprint=_FP_A, disposition=disp, reviewer="Collin",
                        root=tmp_path)
    # The chain survives a full serialize → disk → deserialize round-trip.
    load_decision_ledger("acme", root=tmp_path).verify()


def test_tampered_stored_line_breaks_verify(tmp_path):
    append_decision("acme", fingerprint=_FP_A, disposition=ACCEPTED, reviewer="Collin",
                    root=tmp_path)
    append_decision("acme", fingerprint=_FP_B, disposition=REJECTED, reviewer="Collin",
                    root=tmp_path)
    path = tmp_path / "acme" / "ledger.jsonl"

    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["disposition"] = REJECTED  # silently rewrite a stored disposition
    lines[0] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(DecisionLedgerVerificationError):
        load_decision_ledger("acme", root=tmp_path).verify()


# ── Absent store — clean empty, verifies ─────────────────────────────────────────────

def test_absent_file_loads_empty_and_verifies(tmp_path):
    assert load_decision_entries("nobody", root=tmp_path) == []
    led = load_decision_ledger("nobody", root=tmp_path)
    assert led.entries == []
    led.verify()  # an empty chain is valid


# ── Path-traversal guard — invalid client_id is a ValueError everywhere ───────────────

@pytest.mark.parametrize("bad", ["../evil", "Xero Demo", "UPPER", ""])
def test_append_rejects_invalid_client_id(tmp_path, bad):
    with pytest.raises(ValueError):
        append_decision(bad, fingerprint=_FP_A, disposition=ACCEPTED, reviewer="Collin",
                        root=tmp_path)


def test_ledger_path_and_load_reject_traversal_client_id(tmp_path):
    with pytest.raises(ValueError):
        ledger_path("../evil", root=tmp_path)
    with pytest.raises(ValueError):
        load_decision_entries("../evil", root=tmp_path)


# ── Disposition vocabulary is structural — bad disposition propagates ValueError ──────

def test_invalid_disposition_propagates_value_error(tmp_path):
    with pytest.raises(ValueError):
        append_decision("acme", fingerprint=_FP_A, disposition="MAYBE", reviewer="Collin",
                        root=tmp_path)
