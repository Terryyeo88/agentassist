"""tests/test_xero_queue_contract.py — BUILD 2 (A1) failing-first tests: the Xero F5 upload
path emits the SHARED central-screen ``queue: QueueItem[]`` contract (reshape A′), not the
coverage-era flat ``findings`` rows.

These are written BEFORE the implementation and MUST fail today for the RIGHT reason — the
Xero branch still returns the old 5-key ``findings`` body; ``serialize_xero_queue`` does not
exist yet.

WHAT THIS LOCKS (the new-contract twin of the PENDING amendment Terry will author for the OLD
``tests/test_xero_engine_upload.py`` as a SEPARATE commit — that file stays INTACT and untouched
by this build and is the single EXPECTED-RED test on this branch until that amendment lands):
  * the Xero F5 body is RESHAPED to ``{source_kind, validation_status, disclaimer,
    coverage_status, queue}`` — the flat ``findings`` key is REMOVED;
  * ``queue`` rows are full ``QueueItem`` (QUEUE_ITEM_KEYS), built by reusing
    ``serialize_queue_item`` / ``check_reference`` — so E2/E3/E4 carry their REAL registry
    ``iras_basis`` (same citation as SAP), never manufactured, never "—";
  * the SAME finding VALUES the locked test pinned — {(E2,INV-2003),(E3,INV-2002),
    (E4,BILL-3002)} — now read out of ``queue`` (no E1, no DUP_CLAIM/NO_GST_REG/SEQ_GAP);
  * Decision-4 honesty: the dark checks are surfaced ONLY in ``coverage_status`` (degraded/
    unavailable WITH a reason) and NEVER as a fabricated ``queue`` finding;
  * ``finding_id`` uses the SAME semantics as the SAP path (``detect:{code}:{doc_num}``).

HONEST STATUS: real-Xero-FORMAT findings over SYNTHETIC data — CANDIDATES, never verdicts;
validation_status stays "unvalidated"; no ai_candidates; T2.11 unmoved.

Pure stdlib + pytest + fastapi.testclient. No anthropic import. SAP off, no tokens, hermetic.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.registry import CHECK_REGISTRY
from api.app import app
from api.viewmodel import QUEUE_ITEM_KEYS, _IRAS_CAVEAT, serialize_xero_queue

_REPO_ROOT = Path(__file__).resolve().parents[1]

_XERO_FIXTURE = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_XERO_FILENAME = "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"

# The SAME finding VALUES the (now-superseded) locked test pinned — now read out of `queue`.
_EXPECTED_FINDINGS = {("E2", "INV-2003"), ("E3", "INV-2002"), ("E4", "BILL-3002")}
# The dark checks: surfaced ONLY in coverage_status, NEVER as a queue finding.
_DARK_CHECKS = {"NO_GST_REG", "DUP_CLAIM", "SEQ_GAP", "E1"}
_COVERAGE_LEVELS = {"full", "degraded", "unavailable"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic_engine(tmp_path, monkeypatch):
    """Redirect the engine's PDF dir + the bundle's audit root to tmp, and set dummy SAP creds
    (the Xero branch runs the FULL review()). Mirrors test_xero_engine_upload.py's fixture."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")


def _coverage_row(rows: list, check: str) -> dict:
    for row in rows:
        if row["check"] == check:
            return row
    raise AssertionError(f"coverage check {check!r} not in {[r['check'] for r in rows]}")


# ── BT1 — the reshaped queue contract, real registry iras_basis, same values ──

def test_xero_upload_emits_shared_queue_contract(client: TestClient, hermetic_engine):
    assert _XERO_FIXTURE.is_file(), f"committed Xero fixture missing: {_XERO_FIXTURE}"

    resp = client.post("/review/upload", files={"file": (_XERO_FILENAME, _XERO_FIXTURE.read_bytes())})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # RESHAPED body: queue REPLACES findings — EXACTLY these 5 keys, no `findings`.
    assert set(body.keys()) == {
        "source_kind",
        "validation_status",
        "disclaimer",
        "coverage_status",
        "queue",
    }
    assert "findings" not in body
    assert body["source_kind"] == "xero_f5_upload"

    # Frozen flags + honest framing; no AI candidates leak onto this surface.
    assert body["validation_status"] == "unvalidated"
    assert isinstance(body["disclaimer"], str) and "unvalidated" in body["disclaimer"].lower()
    assert "ai_candidates" not in body

    # coverage_status: dark checks surfaced here (never as queue findings).
    rows = body["coverage_status"]
    assert isinstance(rows, list) and rows
    for row in rows:
        assert set(row.keys()) == {"check", "level", "reason"}
        assert row["level"] in _COVERAGE_LEVELS
    assert _coverage_row(rows, "NO_GST_REG")["level"] == "unavailable"
    assert _coverage_row(rows, "DUP_CLAIM")["level"] == "degraded"
    assert _coverage_row(rows, "SEQ_GAP")["level"] == "degraded"

    # queue: full QueueItem rows the shared <ReviewScreen> consumes.
    queue = body["queue"]
    assert isinstance(queue, list) and queue, "expected a non-empty queue"
    for item in queue:
        assert set(item.keys()) == set(QUEUE_ITEM_KEYS), f"queue row keys drifted: {set(item.keys())}"
        assert item["validation_status"] == "unvalidated"
        # candidate framing carried; caveat is the constant (never a bare caveat on the FE).
        assert item["iras_basis_caveat"] == _IRAS_CAVEAT and item["iras_basis_caveat"]
        # E-checks resolve to their REAL registry iras_basis — same citation as SAP, not "—".
        assert item["check_id"] in {"E2", "E3", "E4"}
        assert item["iras_basis"] == CHECK_REGISTRY[item["check_id"]].iras_basis
        assert item["iras_basis"] and item["iras_basis"] != "—"

    # SAME finding VALUES as the locked test, now out of queue.
    assert {(i["error_code"], i["doc_num"]) for i in queue} == _EXPECTED_FINDINGS
    # finding_id: SAP semantics detect:{code}:{doc_num}.
    for i in queue:
        assert i["finding_id"] == f"detect:{i['error_code']}:{i['doc_num']}"


# ── BT2 — Decision-4 honesty: dark checks degrade WITH a reason; queue has NO fabrication ──

def test_absent_companion_sheet_degrades_without_fabricating(client: TestClient, hermetic_engine):
    resp = client.post("/review/upload", files={"file": (_XERO_FILENAME, _XERO_FIXTURE.read_bytes())})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Half 1 — the absent supplier master surfaces as unavailable WITH a non-empty reason.
    no_gst = _coverage_row(body["coverage_status"], "NO_GST_REG")
    assert no_gst["level"] == "unavailable"
    assert no_gst["reason"].strip(), "a non-full coverage status must carry a reason"
    # every non-full status carries a reason (CoverageStatus enforcement, surfaced not silent).
    for row in body["coverage_status"]:
        if row["level"] != "full":
            assert row["reason"].strip()

    # Half 2 — the T2.11-adjacent proof: NO dark check ever appears as a fabricated queue finding.
    queue_checks = {i["check_id"] for i in body["queue"]} | {i["error_code"] for i in body["queue"]}
    assert queue_checks.isdisjoint(_DARK_CHECKS), (
        f"a dark/degraded check was fabricated into the queue: {queue_checks & _DARK_CHECKS}"
    )


# ── finding_id consistency — SAP semantics, identical collision behaviour on both paths ──

def test_serialize_xero_queue_finding_id_semantics():
    """serialize_xero_queue builds finding_id as detect:{code}:{doc_num} (== dossier.py).

    Two issues with the SAME (code, doc_num) collide to the SAME finding_id — this is the
    IDENTICAL behaviour of the SAP path (agent/dossier.py); it is a pre-existing property of
    both paths, deliberately NOT patched only on the Xero side.
    """
    issues = [
        {"error_code": "E2", "doc_num": "INV-1", "card_name": "Acme", "description": "d1",
         "doc_date": "2026-04-01"},
        {"error_code": "E3", "doc_num": "INV-2", "card_name": "Beta", "description": "d2",
         "doc_date": "2026-04-02"},
        # same (code, doc_num) as the first → same finding_id on BOTH paths (documented).
        {"error_code": "E2", "doc_num": "INV-1", "card_name": "Acme", "description": "d1-dup",
         "doc_date": "2026-04-01"},
    ]
    queue = serialize_xero_queue(issues)
    assert [q["finding_id"] for q in queue] == [
        "detect:E2:INV-1", "detect:E3:INV-2", "detect:E2:INV-1",
    ]
    # each row is a full QueueItem with the real registry iras_basis + the constant caveat.
    for q in queue:
        assert set(q.keys()) == set(QUEUE_ITEM_KEYS)
        assert q["iras_basis"] == CHECK_REGISTRY[q["check_id"]].iras_basis
        assert q["iras_basis_caveat"] == _IRAS_CAVEAT
        assert q["validation_status"] == "unvalidated"
