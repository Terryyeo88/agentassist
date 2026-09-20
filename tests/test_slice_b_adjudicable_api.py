"""Slice B — every row on the Xero demo path is adjudicable, end to end (G-4).

Before this build, 7 of the 16 rows on the committed 2026Q2 demo corpus carried
``fingerprint: None`` — the four document checks plus the three ledger-recon rows — so their
Accept / Decline / Not-an-issue / Mark-known buttons were disabled. This file drives the real
API and pins that a decision on each new family RECORDS, RE-APPLIES on re-upload, and RENDERS
on the signed working paper.

NO GOLDEN LITERAL IS AUTHORED HERE. The E-check byte-identity pin (B2) recomputes through the
UNTOUCHED ``compute_finding_fingerprint`` rather than hardcoding values, so it proves the
dispatch left that family alone without the agent minting a pin it could later move. Terry's
own golden at tests/test_decision_reapply_upload.py:97 remains the independent literal.

Hermetic: engine PDF dir, audit root and decision store all redirected to tmp; dummy SAP
creds; no tokens; SAP off. Mirrors tests/test_b3a2_fingerprint_always_uploads.py.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.decision_ledger import compute_family_fingerprint, compute_finding_fingerprint
from api.app import app

_UPLOAD_SEQ = itertools.count()
_REPO_ROOT = Path(__file__).resolve().parents[1]
_FX = _REPO_ROOT / "tests" / "fixtures" / "xero-demo-2026Q2"
_F5 = _FX / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_LEDGER = _FX / "AgentAssist_-_Account_Transactions.xlsx"
_DOCS = sorted((_FX / "source_documents").glob("*.pdf"))

_EXPECTED_ROWS = 16
_DOC_CHECKS = {
    "gst_amount_mismatch",
    "correct_period",
    "total_inconsistency",
    "reg11_supplier_gst_absent",
}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setattr("agent.decision_store._DECISIONS_ROOT", tmp_path / "decisions")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")
    return tmp_path


def _fresh_audit(monkeypatch, tmp_path):
    """Per-upload audit subdir — seal.run_ts collides when two uploads land in one second."""
    monkeypatch.setattr(
        "audit_bundle.seal._AUDIT_ROOT", tmp_path / f"audit-{next(_UPLOAD_SEQ)}"
    )


def _upload(client, review_id=None, with_docs=True):
    files = [
        ("file", (_F5.name, _F5.read_bytes())),
        ("ledger", (_LEDGER.name, _LEDGER.read_bytes())),
    ]
    if with_docs:
        for p in _DOCS:
            files.append(("documents", (p.name, p.read_bytes())))
    data = {"review_id": review_id} if review_id else {}
    resp = client.post("/review/upload", files=files, data=data)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _session(client):
    return client.post("/review-session", json={"label": "sliceB"}).json()["review_id"]


def _by_prefix(queue, prefix):
    return [r for r in queue if str(r.get("finding_id", "")).startswith(prefix)]


def _row(queue, finding_id):
    hits = [r for r in queue if r["finding_id"] == finding_id]
    assert hits, f"{finding_id} not in queue: {[r['finding_id'] for r in queue]}"
    return hits[0]


# --------------------------------------------------------------------------- B1 + B2

def test_b1_every_demo_row_carries_a_fingerprint(client, hermetic, monkeypatch):
    """G-4 closed: all 16 rows adjudicable, none left with a dead button."""
    _fresh_audit(monkeypatch, hermetic)
    queue = _upload(client, _session(client))["queue"]
    assert len(queue) == _EXPECTED_ROWS

    missing = [r["finding_id"] for r in queue if not r.get("fingerprint")]
    assert missing == [], f"rows still un-fingerprinted: {missing}"
    for r in queue:
        assert isinstance(r["fingerprint"], str) and r["fingerprint"].startswith("sha256:")

    # And the three families that were null before are all actually present.
    assert len(_by_prefix(queue, "doccheck:")) == 4
    assert len(_by_prefix(queue, "ledger_recon:ledger_recon_divergence:")) == 2
    assert len(_by_prefix(queue, "ledger_recon:not_included_gst_drop:")) == 1


def test_b1_fingerprints_are_pairwise_distinct_across_the_whole_queue(client, hermetic,
                                                                     monkeypatch):
    _fresh_audit(monkeypatch, hermetic)
    queue = _upload(client, _session(client))["queue"]
    fps = [r["fingerprint"] for r in queue]
    assert len(set(fps)) == len(fps), "two rows share a fingerprint — one decision would sweep both"


def test_b2_existing_e_check_fingerprints_are_byte_identical(client, hermetic, monkeypatch):
    """Invariant (a). Recomputed through the UNTOUCHED function, not a hardcoded literal."""
    _fresh_audit(monkeypatch, hermetic)
    queue = _upload(client, _session(client))["queue"]
    detect = _by_prefix(queue, "detect:")
    assert len(detect) == 9

    for r in detect:
        expected = compute_finding_fingerprint(
            {"error_code": r["error_code"], "card_name": r["vendor"], "doc_num": r["doc_num"]}
        )
        assert r["fingerprint"] == expected, f"{r['finding_id']} moved"


def test_b2_no_version_bump(client, hermetic, monkeypatch):
    from agent.decision_ledger import FINGERPRINT_KEYS, FINGERPRINT_VERSION

    assert FINGERPRINT_VERSION == "v1"
    assert FINGERPRINT_KEYS == ("error_code", "counterparty", "doc_num")


# --------------------------------------------------------------------------- family keying

def test_document_rows_key_on_check_counterparty_and_document(client, hermetic, monkeypatch):
    _fresh_audit(monkeypatch, hermetic)
    queue = _upload(client, _session(client))["queue"]
    for r in _by_prefix(queue, "doccheck:"):
        assert r["check_id"] in _DOC_CHECKS
        assert r["fingerprint"] == compute_family_fingerprint(
            {"error_code": r["error_code"], "card_name": r["vendor"], "doc_num": r["doc_num"]}
        )


def test_signal_a_rows_key_on_side_and_the_run_period(client, hermetic, monkeypatch):
    """The period comes from the authoritative run period, so the two sides differ and neither
    carries forward to another quarter."""
    _fresh_audit(monkeypatch, hermetic)
    body = _upload(client, _session(client))
    rows = _by_prefix(body["queue"], "ledger_recon:ledger_recon_divergence:")
    assert {r["finding_id"].rsplit(":", 1)[-1] for r in rows} == {"output", "input"}
    assert rows[0]["fingerprint"] != rows[1]["fingerprint"]

    period = body["recomputed_client_coded_f5_boxes"]["period"]
    for r in rows:
        side = r["finding_id"].rsplit(":", 1)[-1]
        assert r["fingerprint"] == compute_family_fingerprint(
            {"finding_type": "ledger_recon_divergence", "error_code": "LEDGER_RECON",
             "side": side},
            period=period,
        )


def test_signal_b_row_keys_on_its_journal_reference(client, hermetic, monkeypatch):
    _fresh_audit(monkeypatch, hermetic)
    queue = _upload(client, _session(client))["queue"]
    row = _by_prefix(queue, "ledger_recon:not_included_gst_drop:")[0]
    reference = row["finding_id"].rsplit(":", 1)[-1]
    assert row["fingerprint"] == compute_family_fingerprint(
        {"finding_type": "not_included_gst_drop", "error_code": "NOT_INCLUDED",
         "reference": reference}
    )


def test_ledger_fingerprints_are_disjoint_from_detect_fingerprints(client, hermetic, monkeypatch):
    _fresh_audit(monkeypatch, hermetic)
    queue = _upload(client, _session(client))["queue"]
    ledger = {r["fingerprint"] for r in _by_prefix(queue, "ledger_recon:")}
    detect = {r["fingerprint"] for r in _by_prefix(queue, "detect:")}
    docs = {r["fingerprint"] for r in _by_prefix(queue, "doccheck:")}
    assert ledger.isdisjoint(detect)
    assert docs.isdisjoint(detect)
    assert docs.isdisjoint(ledger)


# --------------------------------------------------------------------------- B7: re-apply

_TARGETS = [
    ("doccheck:gst_amount_mismatch:BILL-3002", "Mark known", "standing treatment"),
    ("ledger_recon:not_included_gst_drop:#14", "Decline", "disputed journal"),
    ("ledger_recon:ledger_recon_divergence:output", "Not an issue", "known timing difference"),
]


def test_b7_decisions_on_all_three_new_families_record_and_reapply(client, hermetic, monkeypatch):
    """The whole point of a fingerprint: a decision must come BACK on the next read."""
    _fresh_audit(monkeypatch, hermetic)
    rid = _session(client)
    first = _upload(client, rid)["queue"]
    assert len(first) == _EXPECTED_ROWS

    for finding_id, action, note in _TARGETS:
        row = _row(first, finding_id)
        resp = client.post("/decision", json={
            "client_id": "xero_demo", "finding_id": finding_id,
            "fingerprint": row["fingerprint"], "action": action, "note": note,
            "reviewer_name": "Slice B Test", "period": "2026Q2",
        })
        assert resp.status_code == 200, f"{finding_id}: {resp.text}"

    _fresh_audit(monkeypatch, hermetic)
    second = _upload(client, rid)["queue"]

    # Row count must NEVER shrink — demote, never drop.
    assert len(second) == _EXPECTED_ROWS, "a decision removed a row"

    for finding_id, _action, _note in _TARGETS:
        row = _row(second, finding_id)
        assert row["prior_dispositions"], f"{finding_id} did not re-apply"
        assert row["fingerprint"] == _row(first, finding_id)["fingerprint"], (
            f"{finding_id} fingerprint moved between runs — a decision would orphan"
        )


def test_b7_known_accepted_demotes_but_keeps_the_row(client, hermetic, monkeypatch):
    _fresh_audit(monkeypatch, hermetic)
    rid = _session(client)
    first = _upload(client, rid)["queue"]
    target = "ledger_recon:ledger_recon_divergence:input"
    row = _row(first, target)
    assert client.post("/decision", json={
        "client_id": "xero_demo", "finding_id": target, "fingerprint": row["fingerprint"],
        "action": "Mark known", "note": "recurring", "reviewer_name": "Slice B Test",
    }).status_code == 200

    _fresh_audit(monkeypatch, hermetic)
    second = _upload(client, rid)["queue"]
    after = _row(second, target)
    assert after["demoted"] is True
    assert "KNOWN_ACCEPTED" in (after["prior_dispositions"] or [])
    assert len(second) == _EXPECTED_ROWS


def test_b7_a_decision_does_not_leak_onto_a_sibling_row(client, hermetic, monkeypatch):
    """The anti-sweep property: deciding the output side must not touch the input side."""
    _fresh_audit(monkeypatch, hermetic)
    rid = _session(client)
    first = _upload(client, rid)["queue"]
    row = _row(first, "ledger_recon:ledger_recon_divergence:output")
    client.post("/decision", json={
        "client_id": "xero_demo", "finding_id": row["finding_id"],
        "fingerprint": row["fingerprint"], "action": "Mark known", "note": "n",
        "reviewer_name": "Slice B Test",
    })

    _fresh_audit(monkeypatch, hermetic)
    second = _upload(client, rid)["queue"]
    assert _row(second, "ledger_recon:ledger_recon_divergence:output")["prior_dispositions"]
    assert not _row(second, "ledger_recon:ledger_recon_divergence:input")["prior_dispositions"]
    for r in _by_prefix(second, "doccheck:"):
        assert not r["prior_dispositions"], f"{r['finding_id']} was swept"


# --------------------------------------------------------------------------- B9: boundaries

def test_b9_f5_boxes_and_gates_are_byte_identical_with_and_without_decisions(
    client, hermetic, monkeypatch
):
    """BOX-ISOLATION. Adjudication is a reviewer's opinion; it must move no number."""
    import json

    _fresh_audit(monkeypatch, hermetic)
    rid = _session(client)
    before = _upload(client, rid)
    boxes_before = json.dumps(before["recomputed_client_coded_f5_boxes"], sort_keys=True)
    coverage_before = json.dumps(before["coverage_status"], sort_keys=True)

    row = _row(before["queue"], "doccheck:total_inconsistency:BILL-3010")
    client.post("/decision", json={
        "client_id": "xero_demo", "finding_id": row["finding_id"],
        "fingerprint": row["fingerprint"], "action": "Decline", "note": "n",
        "reviewer_name": "Slice B Test",
    })

    _fresh_audit(monkeypatch, hermetic)
    after = _upload(client, rid)
    assert json.dumps(after["recomputed_client_coded_f5_boxes"], sort_keys=True) == boxes_before
    assert json.dumps(after["coverage_status"], sort_keys=True) == coverage_before


# --------------------------------------------------------------------------- B8: signed paper

def _pdf_text(path: str) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages)


def test_b8_signed_paper_renders_the_new_families_adjudications(client, hermetic, monkeypatch):
    """A decision that records but never reaches the paper is only half-wired.

    Pins all three new families in the signed working paper, including a REJECTED one — a
    set-aside decision demotes a finding, it never removes it.
    """
    _fresh_audit(monkeypatch, hermetic)
    rid = _session(client)
    queue = _upload(client, rid)["queue"]

    for finding_id, action, note in _TARGETS:
        row = _row(queue, finding_id)
        assert client.post("/decision", json={
            "client_id": "xero_demo", "finding_id": finding_id,
            "fingerprint": row["fingerprint"], "action": action, "note": note,
            "reviewer_name": "Slice B Signer", "period": "2026Q2",
        }).status_code == 200

    _fresh_audit(monkeypatch, hermetic)
    files = [
        ("file", (_F5.name, _F5.read_bytes())),
        ("ledger", (_LEDGER.name, _LEDGER.read_bytes())),
    ]
    resp = client.post("/sign/upload", files=files, data={
        "reviewer_name": "Slice B Signer", "firm_name": "Slice B Firm", "review_id": rid,
    })
    assert resp.status_code == 200, resp.text
    text = _pdf_text(resp.json()["working_paper_path"])

    # The adjudication section exists and names the reviewer of record.
    assert "Reviewer adjudications" in text
    assert "Slice B Signer" in text

    # All three dispositions render. REJECTED (the Decline) must still appear.
    assert "REJECTED" in text, "a declined finding vanished from the paper"
    assert "KNOWN_ACCEPTED" in text

    # The footer is intact — nothing about this build touches the paper's framing.
    assert "Working paper" in text and "not an IRAS submission" in text

    # And no accuracy claim crept in.
    assert "IRAS-approved" not in text


def test_b9_response_key_set_is_unchanged(client, hermetic, monkeypatch):
    _fresh_audit(monkeypatch, hermetic)
    body = _upload(client, _session(client))
    assert set(body) == {
        "source_kind", "validation_status", "disclaimer", "coverage_status", "queue",
        "recomputed_client_coded_f5_boxes",
    }
