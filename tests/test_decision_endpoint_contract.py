"""tests/test_decision_endpoint_contract.py — t-decision-persistence FAILING-FIRST.

BUILD ID: t-decision-persistence. Written BEFORE the implementation; MUST fail today for
the RIGHT reason — the ``POST /decision`` route does not exist yet (404 / not-registered),
and ``agent.decision_store`` (which the endpoint writes through, and which every test
monkeypatches) is absent, so the fixture's setattr raises ModuleNotFoundError. They pass
once both are built to the pinned contract.

HARD INVARIANTS PINNED HERE (three-times rule — prompt + code + THIS test):
  * FROZEN FLAGS — every decision response carries ``validation_status="unvalidated"`` and
    the SAME disclaimer constant the review payload uses; a decision is a recorded human
    adjudication, NEVER a verdict, correction, or write to client data.
  * EXACT KEY SET — the response is EXACTLY ``DECISION_KEYS`` (single-source contract).
  * APPEND-ONLY over HTTP — two POSTs of the same fingerprint chain to length 1 then 2;
    the on-disk chain still ``verify()``s.
  * READ-PATH RE-APPLY — a "Mark known" persists and DEMOTES the matching finding on the
    next GET /review, present-but-demoted (never suppressed), with QUEUE_ITEM_KEYS intact.
  * EMPTY-STORE NO-OP — an empty store leaves GET /review byte-identical and the frozen
    doc-592 KNOWN_ACCEPTED demotion untouched (the store never rewrites the fixture).
  * READ-NEVER-WRITE-ON-SOURCE — no SAP dependency; the store module imports only stdlib +
    agent.decision_ledger (AST scan) — never requests/mcp/executor/anthropic.

SAP off, mock engine, no tokens, hermetic (decisions land only on tmp_path).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.decision_store import load_decision_entries, load_decision_ledger
from api.app import app
from api.viewmodel import DISCLAIMER, QUEUE_ITEM_KEYS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STORE_SRC = _REPO_ROOT / "agent" / "decision_store.py"

_FP = "sha256:" + "a" * 64

#: The single-source response key set the frontend TS mirrors (pinned independently here).
DECISION_KEYS: tuple[str, ...] = (
    "client_id",
    "finding_id",
    "action",
    "disposition",
    "fingerprint",
    "entry_id",
    "entry_hash",
    "reviewer",
    "timestamp",
    "chain_length",
    "validation_status",
    "disclaimer",
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def decisions_root(tmp_path, monkeypatch):
    """Redirect the durable decision store to tmp_path (mirrors seal._AUDIT_ROOT)."""
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path)
    return tmp_path


def _valid_payload(**overrides) -> dict:
    payload = {
        "client_id": "acme",
        "finding_id": "detect:E2:INV-1",
        "fingerprint": _FP,
        "action": "Accept",
        "note": "",
        "reviewer_name": "Collin",
    }
    payload.update(overrides)
    return payload


# ── Happy path — exact key set, frozen flags, chain_length ────────────────────────────

def test_accept_happy_path(client, decisions_root):
    resp = client.post("/decision", json=_valid_payload())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == set(DECISION_KEYS)
    assert body["action"] == "Accept"
    assert body["disposition"] == "ACCEPTED"
    assert body["client_id"] == "acme"
    assert body["chain_length"] == 1
    assert body["validation_status"] == "unvalidated"
    # Same disclaimer constant the review payload uses.
    assert body["disclaimer"] == DISCLAIMER
    assert body["fingerprint"] == _FP
    # §8: reviewer + timestamp are the real ledger facts, surfaced verbatim — not fabricated.
    assert body["reviewer"] == "Collin"                     # the submitted reviewer_name
    [entry] = load_decision_entries("acme", root=decisions_root)
    assert body["reviewer"] == entry["reviewer"]            # matches the persisted record
    assert body["timestamp"] == entry["timestamp"]          # persisted ledger value, not a fresh clock


# ── 422 surface (the pinned rejections in contract B) ────────────────────────────────

@pytest.mark.parametrize(
    "overrides",
    [
        {"action": "Frobnicate"},                          # action not in the vocab
        {"action": "Decline", "note": ""},                 # note required, empty
        {"action": "Not an issue", "note": "   "},         # note required, whitespace
        {"action": "Mark known", "note": ""},              # note required, empty
        {"reviewer_name": ""},                             # reviewer required
        {"reviewer_name": "   "},                          # reviewer whitespace
        {"client_id": "../evil"},                          # traversal / bad client_id
        {"client_id": "Xero Demo"},                        # space + uppercase
        {"fingerprint": ""},                               # empty fingerprint
        {"fingerprint": "abc123"},                         # not sha256:-prefixed
    ],
)
def test_decision_rejects_invalid(client, decisions_root, overrides):
    resp = client.post("/decision", json=_valid_payload(**overrides))
    assert resp.status_code == 422, resp.text


# ── Action → disposition mapping + reason verb preserved verbatim ─────────────────────

@pytest.mark.parametrize(
    "action,disposition",
    [
        ("Decline", "REJECTED"),
        ("Not an issue", "KNOWN_ACCEPTED"),
        ("Mark known", "KNOWN_ACCEPTED"),
    ],
)
def test_action_maps_to_disposition_and_preserves_verb(client, decisions_root, action, disposition):
    resp = client.post("/decision", json=_valid_payload(action=action, note="reviewer rationale"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == action
    assert body["disposition"] == disposition

    # The UI verb is preserved verbatim in the append-only record's reason.
    [entry] = load_decision_entries("acme", root=decisions_root)
    assert entry["disposition"] == disposition
    assert entry["reason"].startswith(f"[{action}]")


# ── Append-not-overwrite over HTTP ───────────────────────────────────────────────────

def test_two_posts_same_fingerprint_append_and_chain_verifies(client, decisions_root):
    r1 = client.post("/decision", json=_valid_payload())
    assert r1.status_code == 200
    assert r1.json()["chain_length"] == 1

    r2 = client.post("/decision", json=_valid_payload(action="Decline", note="changed my mind"))
    assert r2.status_code == 200
    assert r2.json()["chain_length"] == 2

    path = decisions_root / "acme" / "ledger.jsonl"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    load_decision_ledger("acme", root=decisions_root).verify()


# ── Round-trip: Mark known persists and DEMOTES on the next GET /review ───────────────

def test_mark_known_demotes_matching_finding_on_review(client, decisions_root):
    before = client.get("/review/sbodemosg/2024Q3").json()
    # A deterministic, fingerprinted row that is not already demoted.
    target = next(r for r in before["queue"] if r["fingerprint"] and not r["demoted"])
    assert set(target.keys()) == set(QUEUE_ITEM_KEYS)
    fid = target["finding_id"]
    fp = target["fingerprint"]

    resp = client.post("/decision", json={
        "client_id": "sbodemosg",
        "finding_id": fid,
        "fingerprint": fp,
        "action": "Mark known",
        "note": "Standing accepted treatment.",
        "reviewer_name": "Collin",
        "period": "2024Q3",
    })
    assert resp.status_code == 200, resp.text

    after = client.get("/review/sbodemosg/2024Q3").json()
    row = next(r for r in after["queue"] if r["finding_id"] == fid)
    assert row["demoted"] is True, "a persisted Mark known must demote the finding"
    assert "KNOWN_ACCEPTED" in (row["prior_dispositions"] or [])
    # No key churn on either read.
    assert set(row.keys()) == set(QUEUE_ITEM_KEYS)
    # Cardinality preserved — demote never drops.
    assert len(after["queue"]) == len(before["queue"])


# ── Empty-store no-op — byte-identical review + frozen doc-592 untouched ──────────────

def test_empty_store_review_byte_identical_and_doc592_still_demoted(client, decisions_root):
    a = client.get("/review/sbodemosg/2024Q3").json()
    b = client.get("/review/sbodemosg/2024Q3").json()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    doc592 = next(r for r in a["queue"] if r["finding_id"] == "detect:NO_GST_REG:592")
    assert doc592["demoted"] is True, "the frozen fixture's doc-592 demotion must survive an empty store"
    assert "KNOWN_ACCEPTED" in (doc592["prior_dispositions"] or [])


# ── Read-never-write-on-source (a): no SAP dependency ────────────────────────────────

def test_decision_has_no_sap_dependency(client, decisions_root, monkeypatch):
    monkeypatch.delenv("SAP_USERNAME", raising=False)
    monkeypatch.delenv("SAP_PASSWORD", raising=False)
    resp = client.post("/decision", json=_valid_payload())
    assert resp.status_code == 200, resp.text


# ── Read-never-write-on-source (b): AST import scan of the store module ───────────────

def _imported_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                mods.add(node.module)
    return mods


def test_decision_store_imports_stdlib_and_decision_ledger_only():
    assert _STORE_SRC.is_file(), f"decision store source missing: {_STORE_SRC}"
    modules = _imported_modules(_STORE_SRC)
    tops = {m.split(".")[0] for m in modules}

    forbidden = {"anthropic", "claude_agent_sdk", "requests", "httpx", "mcp", "executor"}
    assert tops.isdisjoint(forbidden), f"store leaked forbidden imports: {tops & forbidden}"

    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is not None:
        non_stdlib_tops = tops - set(stdlib)
        assert non_stdlib_tops <= {"agent"}, f"unexpected non-stdlib import: {non_stdlib_tops}"

    # The ONLY first-party dependency permitted is agent.decision_ledger (the pure core).
    for m in modules:
        if m.split(".")[0] == "agent":
            assert m == "agent.decision_ledger", f"store may only import agent.decision_ledger, got {m!r}"
