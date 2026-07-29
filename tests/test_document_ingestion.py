"""tests/test_document_ingestion.py — T-E(1): source-document ingestion (D-36..D-39, D-42).

Documents upload alongside a Xero export, persist under the review session, and are
served back through a NEW review-scoped route. The four document checks DO NOT run;
coverage stays "unavailable" for all four and the response key set is unchanged —
this file pins both (T4) so T-E(1) cannot quietly become T-E(2).

Store shape (D-36, extending review_store — not a new store):
    reviews/<rid>/documents/<sha256>.pdf        content-hash naming, the
    reviews/<rid>/documents/document_map.json   uploads/<sha256><suffix> idiom
Reference = filename STEM (D-2026-07-29 / #51): BILL-3002.pdf -> "BILL-3002".

Routes: GET /review/{rid}/document/{doc_ref} (D-42) resolves the FULL reference
through document_map.json. GET /document/{doc_ref} is UNTOUCHED as D-34 left it (T8).

Hermetic: every store root under tmp_path; no network, no SAP, no tokens.
"""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import agent.review_store as review_store
import api.app as app_module

client = TestClient(app_module.app)

_REPO = Path(__file__).resolve().parent.parent
_F5 = _REPO / "tests" / "fixtures" / "xero-real-format" / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_SAP_3005 = _REPO / "tests" / "fixtures" / "documents" / "INV-3005.pdf"

_PDF_A = b"%PDF-1.4\n% te1 doc A\n%%EOF\n"
_PDF_B = b"%PDF-1.4\n% te1 doc B (different)\n%%EOF\n"

_HONEST_404 = {"detail": "No source document on file"}


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    """Redirect the review store to tmp; every test gets a fresh reviews/ tree."""
    monkeypatch.setattr(review_store, "_REVIEWS_ROOT", tmp_path / "reviews")
    return tmp_path / "reviews"


@pytest.fixture
def rid(store_root):
    return client.post("/review-session", json={"label": "te1"}).json()["review_id"]


def _upload(files_or_none, rid_or_none):
    files = [("file", (_F5.name, _F5.read_bytes()))]
    for name, body in (files_or_none or []):
        files.append(("documents", (name, body)))
    data = {"review_id": rid_or_none} if rid_or_none else {}
    return client.post("/review/upload", files=files, data=data)


# ── T1 / T2: documents land content-hashed with a stem-keyed map ─────────────────────

def test_t1_documents_land_hashed_with_map(store_root, rid):
    resp = _upload([("BILL-3002.pdf", _PDF_A), ("INV-2001.pdf", _PDF_B)], rid)
    assert resp.status_code == 200, resp.text
    docs = store_root / rid / "documents"
    sha_a = hashlib.sha256(_PDF_A).hexdigest()
    sha_b = hashlib.sha256(_PDF_B).hexdigest()
    assert (docs / f"{sha_a}.pdf").read_bytes() == _PDF_A
    assert (docs / f"{sha_b}.pdf").read_bytes() == _PDF_B
    doc_map = json.loads((docs / "document_map.json").read_text(encoding="utf-8"))
    assert doc_map == {"BILL-3002": sha_a, "INV-2001": sha_b}


def test_t2_reference_is_the_filename_stem(store_root, rid):
    _upload([("BILL-3002.pdf", _PDF_A)], rid)
    doc_map = json.loads(
        (store_root / rid / "documents" / "document_map.json").read_text(encoding="utf-8")
    )
    assert "BILL-3002" in doc_map          # the exact stem key (D-2026-07-29 / #51)
    assert "BILL-3002.pdf" not in doc_map


# ── T3: documents without review_id -> honest 422, never a silent drop ───────────────

def test_t3_documents_without_review_id_422(store_root):
    resp = _upload([("BILL-3002.pdf", _PDF_A)], None)
    assert resp.status_code == 422
    assert "review_id" in resp.json()["detail"]
    # and nothing was written anywhere
    assert not list(store_root.rglob("*.pdf")) if store_root.exists() else True


# ── T4: no documents -> byte-identical behaviour to today ────────────────────────────

def test_t4_no_documents_is_todays_behaviour(store_root, rid):
    plain = _upload(None, rid)
    assert plain.status_code == 200
    body = plain.json()
    assert set(body.keys()) == set(app_module.XERO_F5_UPLOAD_KEYS)
    dark = {r["check"]: r for r in body["coverage_status"]
            if r["check"] in ("gst_amount_mismatch", "correct_period",
                              "total_inconsistency", "reg11_supplier_gst_absent")}
    assert set(dark) == {"gst_amount_mismatch", "correct_period",
                         "total_inconsistency", "reg11_supplier_gst_absent"}
    for check, row in dark.items():
        assert row["level"] == "unavailable"
        assert row["reason"] == (
            f"source documents (document_pdfs) absent — {check} cannot run; "
            "supply source-document PDFs at onboarding."
        )
    # queue unchanged: the frozen fixture's three findings
    assert {(i["error_code"], i["doc_num"]) for i in body["queue"]} == {
        ("E3", "INV-2002"), ("E4", "BILL-3002"), ("E2", "INV-2003")}


# ── T5 / T6 / T7: the review-scoped route (D-42) ─────────────────────────────────────

def test_t5_review_scoped_route_serves_the_uploaded_bytes(store_root, rid):
    _upload([("BILL-3002.pdf", _PDF_A)], rid)
    resp = client.get(f"/review/{rid}/document/BILL-3002")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert hashlib.sha256(resp.content).hexdigest() == hashlib.sha256(_PDF_A).hexdigest()


def test_t6_unmapped_reference_is_the_same_honest_404(store_root, rid):
    _upload([("BILL-3002.pdf", _PDF_A)], rid)
    resp = client.get(f"/review/{rid}/document/BILL-9999")
    assert resp.status_code == 404
    assert resp.json() == _HONEST_404


def test_t7_unknown_review_id_leaks_nothing(store_root, rid):
    _upload([("BILL-3002.pdf", _PDF_A)], rid)
    resp = client.get("/review/r_000000000000/document/BILL-3002")
    assert resp.status_code == 404
    assert resp.json() == _HONEST_404
    malformed = client.get("/review/NOT..VALID/document/BILL-3002")
    assert malformed.status_code == 404


# ── T8: the OLD route is untouched (D-34 posture preserved) ──────────────────────────

def test_t8_old_route_untouched(store_root, rid):
    _upload([("BILL-3002.pdf", _PDF_A)], rid)
    old = client.get("/document/BILL-3002")
    assert old.status_code == 404
    assert old.json() == _HONEST_404
    sap = client.get("/document/3005")
    assert sap.status_code == 200
    assert hashlib.sha256(sap.content).hexdigest() == hashlib.sha256(
        _SAP_3005.read_bytes()).hexdigest()


# ── T9: caps (D-39) -> honest 413 naming the limit ───────────────────────────────────

def test_t9_caps_give_honest_413(store_root, rid, monkeypatch):
    monkeypatch.setattr(app_module, "_DOC_MAX_FILE_BYTES", 64)
    monkeypatch.setattr(app_module, "_DOC_MAX_TOTAL_BYTES", 100)
    monkeypatch.setattr(app_module, "_DOC_MAX_COUNT", 2)

    big = _upload([("BILL-3002.pdf", b"%PDF" + b"x" * 100)], rid)
    assert big.status_code == 413
    assert "per-file" in big.json()["detail"]

    total = _upload([("A.pdf", b"%PDF" + b"x" * 50), ("B.pdf", b"%PDF" + b"y" * 50)], rid)
    assert total.status_code == 413
    assert "total" in total.json()["detail"]

    count = _upload([("A.pdf", b"%PDF1"), ("B.pdf", b"%PDF2"), ("C.pdf", b"%PDF3")], rid)
    assert count.status_code == 413
    assert "count" in count.json()["detail"]


# ── T10: path safety — asserted on the FILESYSTEM, not the status ────────────────────

def test_t10_path_safety_nothing_written_outside_the_review_dir(store_root, rid, tmp_path):
    for evil in ("..\\evil.pdf", "../evil.pdf", "a/b.pdf", "a\\b.pdf", "..pdf..\\..\\x.pdf"):
        resp = _upload([(evil, _PDF_A)], rid)
        assert resp.status_code == 422, f"{evil!r}: expected rejection, got {resp.status_code}"
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    inside = [p for p in written if (tmp_path / "reviews" / rid) in p.parents]
    assert written == inside or all(
        (tmp_path / "reviews") in p.parents for p in written
    ), f"files written outside the reviews tree: {[str(p) for p in written if (tmp_path / 'reviews') not in p.parents]}"
    docs_dir = store_root / rid / "documents"
    stray = [p for p in (docs_dir.rglob("*") if docs_dir.exists() else [])
             if p.is_file() and p.suffix == ".pdf"]
    assert stray == [], f"rejected filenames must write nothing: {stray}"
