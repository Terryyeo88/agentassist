"""tests/test_decision_reapply_upload.py — t-decision-persistence FAILING-FIRST.

BUILD ID: t-decision-persistence. Written BEFORE the implementation; MUST fail today for
the RIGHT reason — the Xero upload path does not yet thread persisted decisions through
``serialize_xero_queue`` (rows carry ``fingerprint=None`` / ``demoted=False`` regardless of
the store), and both ``POST /decision`` and ``agent.decision_store`` are absent. Passes once
the read-path re-apply is wired to the durable store.

HARD INVARIANTS PINNED HERE (three-times rule — prompt + code + THIS test):
  * READ-PATH RE-APPLY over the REAL Xero engine path — an empty store leaves the Xero
    upload queue at today's stub (fingerprint None / demoted False); after a persisted
    "Mark known", the SAME re-uploaded workbook shows the matching finding demoted +
    fingerprinted, prior_dispositions ["KNOWN_ACCEPTED"]; non-matching rows carry a
    fingerprint (non-empty store) but stay un-demoted.
  * NEVER-SUPPRESS — the demoted row is still PRESENT (cardinality preserved: demote ≠ drop).
  * FROZEN top-level shape — the Xero body stays EXACTLY {source_kind, validation_status,
    disclaimer, coverage_status, queue}; validation_status "unvalidated" (candidates, not
    verdicts). (Pinned as a NEW literal here; the existing test's literal stays untouched.)

Mirrors tests/test_xero_queue_contract.py's hermetic_engine fixture (redirects the engine
PDF dir + audit root to tmp + dummy SAP creds), PLUS a decision-store redirect. SAP off,
mock engine, no tokens, hermetic.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from agent.decision_ledger import compute_finding_fingerprint
from api.app import app

# Each upload gets its OWN audit root: seal's run_ts has seconds resolution, so two
# uploads in the same second would collide on one read-only bundle dir (PermissionError
# on Windows). Pre-existing engine property, sidestepped per-call here — never patched
# in the engine (box-isolation).
_UPLOAD_SEQ = itertools.count()

_REPO_ROOT = Path(__file__).resolve().parents[1]
_XERO_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_XERO_FILENAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

# The Xero upload runs under the xero_demo client config; the store keys on that client_id.
_XERO_CLIENT_ID = "xero_demo"
_XERO_TOP_KEYS = {"source_kind", "validation_status", "disclaimer", "coverage_status", "queue"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Engine PDF dir + audit root + decision store all redirected to tmp; dummy SAP creds."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    return tmp_path


def _upload(client: TestClient) -> dict:
    # Fresh audit subdir per upload (see _UPLOAD_SEQ note). The hermetic fixture's
    # monkeypatch teardown still restores the real _AUDIT_ROOT after the test.
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"
    resp = client.post(
        "/review/upload", files={"file": (_XERO_FILENAME, _XERO_FIXTURE.read_bytes())}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Baseline — empty store leaves the queue at today's stub ───────────────────────────

def test_baseline_upload_empty_store_stubs(client, hermetic):
    assert _XERO_FIXTURE.is_file(), f"committed Xero fixture missing: {_XERO_FIXTURE}"
    body = _upload(client)

    assert set(body.keys()) == _XERO_TOP_KEYS
    assert body["source_kind"] == "xero_f5_upload"
    assert body["validation_status"] == "unvalidated"

    assert body["queue"], "expected a non-empty queue"
    for row in body["queue"]:
        assert row["fingerprint"] is None, "empty store → no fingerprint (stub behaviour)"
        assert row["demoted"] is False
        assert row["prior_dispositions"] == []


# ── Re-apply — a persisted Mark known demotes the matching row on re-upload ───────────

def test_mark_known_reapplies_on_reupload(client, hermetic):
    base = _upload(client)["queue"]
    # E4/BILL-3002 is a stable finding the Xero fixture produces (see test_xero_queue_contract).
    target = next(r for r in base if r["error_code"] == "E4")

    # The fingerprint keys on (error_code, counterparty); the queue's `vendor` IS the
    # counterparty (flatten_finding_card lifts card_name → vendor), so this reproduces the
    # exact fingerprint the re-upload will compute for the same finding.
    fp = compute_finding_fingerprint(
        {"error_code": target["error_code"], "card_name": target["vendor"]}
    )

    resp = client.post("/decision", json={
        "client_id": _XERO_CLIENT_ID,
        "finding_id": target["finding_id"],
        "fingerprint": fp,
        "action": "Mark known",
        "note": "Standing accepted treatment for this supplier.",
        "reviewer_name": "Collin",
    })
    assert resp.status_code == 200, resp.text

    re = _upload(client)["queue"]

    # The marked-known finding is demoted + fingerprinted + carries the prior disposition.
    matched = [r for r in re if r["fingerprint"] == fp]
    assert matched, "the marked-known finding must carry its fingerprint after re-upload"
    for r in matched:
        assert r["demoted"] is True
        assert "KNOWN_ACCEPTED" in (r["prior_dispositions"] or [])

    # Non-empty store: every row now carries a fingerprint; non-matching rows stay un-demoted.
    for r in re:
        assert r["fingerprint"] is not None, "non-empty store → fingerprint populated on every row"
        if r["fingerprint"] != fp:
            assert r["demoted"] is False

    # Never-suppress: cardinality preserved — the demoted row is still present.
    assert len(re) == len(base)
    assert any(r["finding_id"] == target["finding_id"] for r in re)


# ── Frozen top-level shape holds on both the baseline and the re-apply read ───────────

def test_xero_top_level_shape_unchanged_after_reapply(client, hermetic):
    base = _upload(client)
    assert set(base.keys()) == _XERO_TOP_KEYS

    target = next(r for r in base["queue"] if r["error_code"] == "E4")
    fp = compute_finding_fingerprint(
        {"error_code": target["error_code"], "card_name": target["vendor"]}
    )
    client.post("/decision", json={
        "client_id": _XERO_CLIENT_ID,
        "finding_id": target["finding_id"],
        "fingerprint": fp,
        "action": "Mark known",
        "note": "Standing accepted treatment.",
        "reviewer_name": "Collin",
    })

    after = _upload(client)
    assert set(after.keys()) == _XERO_TOP_KEYS
    assert after["validation_status"] == "unvalidated"
