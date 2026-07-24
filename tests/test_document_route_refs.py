"""tests/test_document_route_refs.py — C1 follow-up: GET /document/{doc_ref} string references.

Findings on the Xero path carry a non-numeric DocNum like "BILL-3003" (feeders/xero_f5_reader.py).
The route now takes a STRING ref and selects the fixture by the last run of digits, so both a
bare SAP doc_num and a Xero-style reference resolve to the same INV-<n>.pdf. No digits, or digits
with no matching fixture, is a flat 404 (the UI's honest "no source document on file").

Path-safety: only the extracted digits (parsed to int) reach the provider; the raw string never
builds a filesystem path.

Coverage:
  * R1 — "BILL-3003" -> 200 + application/pdf (serves INV-3003.pdf).
  * R2 — "3003" (bare numeric) -> 200 (unchanged behaviour).
  * R3 — "BILL-XYZ" (no digits) -> 404.
  * R4 — "BILL-9999" (digits parse, no fixture) -> 404.
"""
import pytest
from fastapi.testclient import TestClient

import api.app as app_module
from documents.provider import FixtureDocumentProvider

client = TestClient(app_module.app)


@pytest.fixture
def doc_dir(tmp_path, monkeypatch):
    """A tmp fixtures dir holding INV-3003.pdf; _DOC_PROVIDER is pinned to a provider over it."""
    (tmp_path / "INV-3003.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    monkeypatch.setattr(app_module, "_DOC_PROVIDER", FixtureDocumentProvider(tmp_path))
    return tmp_path


def test_xero_style_ref_serves_matching_fixture(doc_dir):
    """R1: BILL-3003 -> the digits 3003 select INV-3003.pdf."""
    resp = client.get("/document/BILL-3003")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content == b"%PDF-1.4\n%%EOF\n"


def test_bare_numeric_ref_still_works(doc_dir):
    """R2: a bare numeric ref keeps serving the fixture (no regression)."""
    resp = client.get("/document/3003")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")


def test_ref_without_digits_returns_404(doc_dir):
    """R3: no numeric part -> honest 404, provider never consulted for a path."""
    resp = client.get("/document/BILL-XYZ")
    assert resp.status_code == 404


def test_ref_with_digits_but_no_fixture_returns_404(doc_dir):
    """R4: digits parse but no INV-9999.pdf on file -> 404."""
    resp = client.get("/document/BILL-9999")
    assert resp.status_code == 404
