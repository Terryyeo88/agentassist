"""tests/test_document_route.py — C1: GET /document/{doc_num} source-invoice route.

The route serves the source invoice PDF for a document number via the offline-safe
``FixtureDocumentProvider`` (INV-<doc_num>.pdf lookup). It is read-only; doc_num is an int
so FastAPI validation rules out any path traversal. A doc_num with no fixture on file is a
flat 404 — the UI's honest "no source document on file" signal.

These tests monkeypatch ``api.app._DOC_PROVIDER`` to a provider over a tmp dir, so they
never depend on the real tests/fixtures/documents contents.

Coverage:
  * G1 — an INV-<n>.pdf present in the tmp dir -> GET /document/<n> -> 200 + application/pdf.
  * G2 — a doc_num with no matching file -> 404.
"""
import pytest
from fastapi.testclient import TestClient

import api.app as app_module
from documents.provider import FixtureDocumentProvider

client = TestClient(app_module.app)


@pytest.fixture
def doc_dir(tmp_path, monkeypatch):
    """A tmp fixtures dir; api.app._DOC_PROVIDER is pinned to a provider over it."""
    monkeypatch.setattr(app_module, "_DOC_PROVIDER", FixtureDocumentProvider(tmp_path))
    return tmp_path


def test_present_invoice_returns_200_pdf(doc_dir):
    """G1: INV-3001.pdf on file -> the route serves it with the PDF media type."""
    (doc_dir / "INV-3001.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    resp = client.get("/document/3001")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content == b"%PDF-1.4\n%%EOF\n"


def test_missing_invoice_returns_404(doc_dir):
    """G2: no INV-<n>.pdf for the requested doc_num -> honest 404."""
    resp = client.get("/document/9999")
    assert resp.status_code == 404
