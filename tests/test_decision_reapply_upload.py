"""tests/test_decision_reapply_upload.py — t-decision-persistence FAILING-FIRST.

BUILD ID: t-decision-persistence. Written BEFORE the implementation; MUST fail today for
the RIGHT reason — the Xero upload path does not yet thread persisted decisions through
``serialize_xero_queue``, and both ``POST /decision`` and ``agent.decision_store`` are
absent. Passes once the read-path re-apply is wired to the durable store.

RULE-AUTHOR AMENDMENT (t-b3a2-test-amendment, hand-authored — separation of duties).
B3a-2's "fingerprint-always" enabler makes ``serialize_xero_queue`` compute and emit a
fingerprint on every DETECT row regardless of store contents, so the panel can POST a
first-ever decision. That deliberately RETIRES the former "empty store → fingerprint
None stub" property pinned here. The baseline assertion below is amended accordingly and
is INTENTIONALLY RED until B3a-2 lands the enabler.

RULE-AUTHOR AMENDMENT (t-fingerprint-v1, hand-authored — separation of duties).
The fingerprint key WIDENED from (error_code, counterparty) to
(error_code, counterparty, doc_num) under D-2026-07-24-fingerprint-v1. The v0 pair was
DEGENERATE: two documents from one supplier carrying the same error hashed identically,
so one adjudication swept both. The #46 tripwire below fired exactly as designed — it is
re-pinned to the v1 literal, and the RETIRED v0 literal is recorded in-file (see the
constant block) because it existed nowhere else once this pin was overwritten. The three
hand-built recompute dicts below now carry ``doc_num``.

HARD INVARIANTS PINNED HERE (three-times rule — prompt + code + THIS test):
  * READ-PATH RE-APPLY over the REAL Xero engine path — every detect row carries its
    computed fingerprint (B3a-2 fingerprint-always); an empty store leaves those rows
    UN-DEMOTED (demoted False, prior_dispositions []); after a persisted "Mark known",
    the SAME re-uploaded workbook shows the matching finding demoted + fingerprinted,
    prior_dispositions ["KNOWN_ACCEPTED"]; non-matching rows stay un-demoted.
  * EXACTLY-ONE MATCH (t-fingerprint-v1) — a persisted decision demotes ONE document,
    never every document from that supplier sharing the error code.
  * NEVER-SUPPRESS — the demoted row is still PRESENT (cardinality preserved: demote ≠ drop).
  * FROZEN top-level shape — the Xero body stays EXACTLY {source_kind, validation_status,
    disclaimer, coverage_status, queue}; validation_status "unvalidated" (candidates, not
    verdicts). (Pinned as a NEW literal here; the existing test's literal stays untouched.)
  * #46 MIGRATION TRIPWIRE — one golden v1 fingerprint literal (see below), so a further
    widening of the fingerprint key cannot pass silently.

SCOPE NOTE: fingerprint-always covers ``serialize_xero_queue`` (detect rows). Ledger-recon
rows come from ``serialize_ledger_recon_queue`` (different finding shape, no counterparty)
and are NOT fingerprinted. This fixture is a no-ledger upload, so no recon rows appear in
the queue here; if that ever changes, the baseline loop below must skip un-fingerprinted
recon rows rather than assert over them.

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

# ── #46 MIGRATION TRIPWIRE (deliberate) ──────────────────────────────────────────────
#
# RETIRED v0 LITERAL — recorded here for the migration record, NOT asserted. Under
# FINGERPRINT_KEYS = ("error_code", "counterparty") the E4 / BILL-3002 /
# "OldRate Supplies Pte Ltd" row hashed to:
#
#   sha256:265e9b4e92baa689143df7f1384560a0f337d325105d38c8499c6595c42b159e
#
# That composition EXCLUDED doc_num, which was the defect: every BILL from that supplier
# carrying E4 shared the key, so one adjudication swept all of them. Any decision stored
# under the v0 key is now INERT BY CONSTRUCTION (a v1 key can never equal a v0 key) and is
# surfaced as data via count_superseded_entries — never silently applied forward.
#
# CURRENT v1 GOLDEN — the same row under
# FINGERPRINT_KEYS = ("error_code", "counterparty", "doc_num"), where counterparty is
# sourced from the payload's card_name (the queue exposes it as `vendor`) and doc_num is
# carried str-canonical (str().strip(), NO casefold — document numbers are identifiers).
# Recomputing via compute_finding_fingerprint() can NEVER catch an algorithm change —
# both sides move together. This literal CAN.
_GOLDEN_V1_FINGERPRINT_E4_BILL3002 = (
    "sha256:a6a758ae79fa77c26f3ebf773784074a7bc67f9a8eb7a67e96cec8bfa3c54edf"
)


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


# ── Baseline — empty store: rows are fingerprinted but un-demoted ─────────────────────

def test_baseline_upload_empty_store_stubs(client, hermetic):
    assert _XERO_FIXTURE.is_file(), f"committed Xero fixture missing: {_XERO_FIXTURE}"
    body = _upload(client)

    assert set(body.keys()) == _XERO_TOP_KEYS
    assert body["source_kind"] == "xero_f5_upload"
    assert body["validation_status"] == "unvalidated"

    assert body["queue"], "expected a non-empty queue"
    for row in body["queue"]:
        # t-fingerprint-v1: doc_num joined the key. Passed RAW — the normaliser inside
        # decision_ledger does the canonicalisation, and duplicating it here would hide
        # a regression in the normaliser.
        assert row["fingerprint"] == compute_finding_fingerprint(
            {
                "error_code": row["error_code"],
                "card_name": row["vendor"],
                "doc_num": row["doc_num"],
            }
        ), "fingerprint-always: every detect row carries its computed fingerprint (B3a-2 enabler)"
        assert row["demoted"] is False
        assert row["prior_dispositions"] == []


# ── Re-apply — a persisted Mark known demotes the matching row on re-upload ───────────

def test_mark_known_reapplies_on_reupload(client, hermetic):
    base = _upload(client)["queue"]
    # E4/BILL-3002 is a stable finding the Xero fixture produces (see test_xero_queue_contract).
    target = next(r for r in base if r["error_code"] == "E4")

    # The fingerprint keys on (error_code, counterparty, doc_num); the queue's `vendor` IS
    # the counterparty (flatten_finding_card lifts card_name → vendor), so this reproduces
    # the exact fingerprint the re-upload will compute for the same finding.
    fp = compute_finding_fingerprint(
        {
            "error_code": target["error_code"],
            "card_name": target["vendor"],
            "doc_num": target["doc_num"],
        }
    )

    # #46 tripwire: pin the GOLDEN v1 value, not just the recomputed one. See the constant.
    assert fp == _GOLDEN_V1_FINGERPRINT_E4_BILL3002, (
        "v1 fingerprint composition changed — stored decisions keyed on the old value will "
        "go INERT. Do not just update this literal: record the retired value and decide the "
        "migration posture (open item #46)."
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
    # t-fingerprint-v1: EXACTLY ONE document matches. Under v0 an adjudication on this
    # row swept every document from the same supplier sharing the error code — the
    # sweep-collision this build kills.
    assert len(matched) == 1, (
        f"one adjudication demoted {len(matched)} documents — the fingerprint is "
        "degenerate again"
    )
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
        {
            "error_code": target["error_code"],
            "card_name": target["vendor"],
            "doc_num": target["doc_num"],
        }
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
