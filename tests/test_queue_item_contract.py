"""tests/test_queue_item_contract.py — D-47: the QueueItem contract, BOUND.

A live crash reached a user: _serialize_document_candidates re-implemented a projection
that already exists (viewmodel.serialize_queue_item) and violated the declared contract
in frontend/src/api.ts — completeness/iras_basis_caveat/inputs_hash emitted null on
non-nullable fields; FindingDetail read completeness.satisfied and unmounted the tree.
Two projections of one shape with nothing binding them — the XERO_UPLOAD_KEYS family.

T1 is the binding: EVERY queue row (deterministic, ledger-recon and document alike)
must satisfy EVERY non-nullable field of the api.ts QueueItem interface. The set below
is the M1 measurement (parsed from api.ts with brace balancing, confirmed by Terry).

D-47: finding_type derives from extraction_source — "deterministic" for born_digital
(D-46's ungated rendering rests on exactly this), "probabilistic" for model-assisted.

Hermetic: store roots under tmp_path; committed 2026Q2 corpus fixtures only.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agent.review_store as review_store
import api.app as app_module
from agent.registry import CHECK_REGISTRY
from api.viewmodel import _IRAS_CAVEAT

client = TestClient(app_module.app)

_REPO = Path(__file__).resolve().parent.parent
_F5 = _REPO / "tests" / "fixtures" / "xero-demo-2026Q2" / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_LEDGER = _REPO / "tests" / "fixtures" / "xero-demo-2026Q2" / "AgentAssist_-_Account_Transactions.xlsx"
_DOCS = _REPO / "tests" / "fixtures" / "xero-demo-2026Q2" / "source_documents"

_FOUR = ("gst_amount_mismatch", "correct_period", "total_inconsistency", "reg11_supplier_gst_absent")

# M1 — the api.ts QueueItem fields whose declared type does NOT include null.
_NON_NULLABLE = (
    "finding_id", "check_id", "finding_type", "group", "iras_basis_caveat", "demoted",
    "prior_dispositions", "candidate_framing_text", "completeness", "inputs_hash",
    "validation_status",
)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(review_store, "_REVIEWS_ROOT", tmp_path / "reviews")
    return tmp_path


def _upload(with_docs: bool, roots) -> dict:
    files = [("file", (_F5.name, _F5.read_bytes())),
             ("ledger", (_LEDGER.name, _LEDGER.read_bytes()))]
    data = {}
    if with_docs:
        rid = client.post("/review-session", json={"label": "contract"}).json()["review_id"]
        for p in sorted(_DOCS.glob("*.pdf")):
            files.append(("documents", (p.name, p.read_bytes())))
        data["review_id"] = rid
    return client.post("/review/upload", files=files, data=data).json()


def _doc_rows(body):
    return {r["error_code"]: r for r in body["queue"] if r["error_code"] in _FOUR}


# ── T1: THE BINDING TEST — every row, every non-nullable field ───────────────────────

def test_t1_every_queue_row_satisfies_every_non_nullable_field(roots):
    body = _upload(True, roots)
    assert len(body["queue"]) >= 16
    violations = [
        (str(row.get("error_code")), str(row.get("doc_num")), field)
        for row in body["queue"]
        for field in _NON_NULLABLE
        if row.get(field) is None
    ]
    assert violations == [], f"non-nullable contract violations (row, doc, field): {violations}"


# ── T2: completeness is the real shape with real values ──────────────────────────────

def test_t2_document_completeness_is_the_real_shape(roots):
    row = _doc_rows(_upload(True, roots))["gst_amount_mismatch"]
    assert row["completeness"] == {
        "required": ["line_item", "source_document"],
        "present": ["line_item", "source_document"],
        "missing": [],
        "satisfied": True,
    }


# ── T3: the caveat constant, by reference ────────────────────────────────────────────

def test_t3_caveat_is_the_shared_constant(roots):
    for check, row in _doc_rows(_upload(True, roots)).items():
        assert row["iras_basis_caveat"] == _IRAS_CAVEAT, check


# ── T4: display_name and iras_basis come from CHECK_REGISTRY ─────────────────────────

def test_t4_registry_resolution(roots):
    rows = _doc_rows(_upload(True, roots))
    for check in _FOUR:
        spec = CHECK_REGISTRY[check]
        assert rows[check]["display_name"] == spec.display_name, check
        assert rows[check]["iras_basis"] == spec.iras_basis, check


# ── T5: vendor and doc_date carry the BOOKS' values (C2 prints) ──────────────────────

def test_t5_books_vendor_and_date(roots):
    rows = _doc_rows(_upload(True, roots))
    assert rows["gst_amount_mismatch"]["vendor"] == "OldRate Supplies Pte Ltd"
    assert rows["gst_amount_mismatch"]["doc_date"] == "2026-04-22"
    assert rows["reg11_supplier_gst_absent"]["vendor"] == "NoReg Trading"
    assert rows["correct_period"]["vendor"] == "Bras Basah Print Pte Ltd"


# ── T6: D-47 — finding_type derives from extraction_source ───────────────────────────

def test_t6_finding_type_follows_extraction_source():
    from documents.reconcile import DocumentCandidate

    def cand(source):
        return DocumentCandidate(
            doc_num="BILL-3002", check_id="gst_amount_mismatch", severity="MEDIUM",
            message="Consider reviewing whether …", extracted_value=1.0,
            listing_value=2.0, extraction_source=source, determinability="J+",
        )

    born = app_module._serialize_document_candidates([cand("born_digital")])
    multi = app_module._serialize_document_candidates([cand("multimodal")])
    assert born[0]["finding_type"] == "deterministic"
    assert multi[0]["finding_type"] == "probabilistic"


# ── T8: every OTHER row is byte-identical — this build changes document rows only ────

def test_t8_other_rows_are_untouched(roots):
    with_docs = _upload(True, roots)
    without = _upload(False, roots)
    others = [r for r in with_docs["queue"] if r["error_code"] not in _FOUR]
    assert others == without["queue"], "non-document rows must be byte-identical"
