"""
PR-3 — ledger-recon on the web upload path (hop 2). FAILING-FIRST.

Migrates POST /review/upload to MULTIPART: a required primary .xlsx + an OPTIONAL
ledger .xlsx (the Xero 820 account-transactions export). When the primary routes to
the Xero F5 handler AND a ledger is supplied, the T2.24 ledger-recon findings are
assembled (fork b: F5 path only) and merged into the queue via
serialize_ledger_recon_queue. Omitting the ledger is a clean no-op. A genuinely
unreadable ledger is an honest 422 (#87 rule). Sales/extract paths ignore a ledger.

These use the committed xero-real-format pair (F5 + Account_Transactions) the T2.24
recon tests use; SAP is off (dummy creds satisfy the loader; no SAP call is made).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.viewmodel import QUEUE_ITEM_KEYS

_REPO = Path(__file__).resolve().parents[1]
_FIX = _REPO / "tests" / "fixtures" / "xero-real-format"
_F5 = _FIX / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
_LEDGER = _FIX / "AgentAssist_-_Account_Transactions.xlsx"

_LEDGER_CODES = {"LEDGER_RECON", "NOT_INCLUDED"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic_engine(tmp_path, monkeypatch):
    """Redirect the engine PDF dir + audit root to tmp, set dummy SAP creds (DEBT-9;
    no SAP call is made on the Xero path)."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")


def _synth_extract_xlsx(tmp_path) -> bytes:
    """A synthetic (NON-Xero) extract .xlsx, built like the other upload tests."""
    spec = importlib.util.spec_from_file_location(
        "lru_synth_export", _REPO / "tests" / "synth_extract_export.py"
    )
    synth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(synth)
    out = tmp_path / "synthetic_export.xlsx"
    synth.export_xlsx(_REPO / "tests" / "fixtures" / "sbodemosg-extract", out)
    return out.read_bytes()


def _ledger_rows(queue: list[dict]) -> list[dict]:
    return [r for r in queue if r.get("error_code") in _LEDGER_CODES]


# ── F5 + ledger (multipart) → ledger-recon rows in the queue ──────────────────────────

class TestF5WithLedger:
    def test_f5_plus_ledger_surfaces_ledger_recon_rows(self, client, hermetic_engine):
        assert _F5.is_file() and _LEDGER.is_file(), "committed xero-real-format fixtures missing"
        resp = client.post(
            "/review/upload",
            files={
                "file": (_F5.name, _F5.read_bytes()),
                "ledger": (_LEDGER.name, _LEDGER.read_bytes()),
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_kind"] == "xero_f5_upload"
        assert body["validation_status"] == "unvalidated"
        ledger_rows = _ledger_rows(body["queue"])
        assert ledger_rows, "ledger-recon rows must appear when a ledger is supplied"
        for row in ledger_rows:
            assert set(row.keys()) == set(QUEUE_ITEM_KEYS), "ledger rows must satisfy the contract"
            assert row["validation_status"] == "unvalidated"


# ── F5 alone (no ledger) → clean no-op (no ledger-recon rows) ─────────────────────────

class TestF5NoLedgerIsNoOp:
    def test_f5_alone_has_no_ledger_recon_rows(self, client, hermetic_engine):
        resp = client.post("/review/upload", files={"file": (_F5.name, _F5.read_bytes())})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_kind"] == "xero_f5_upload"
        assert _ledger_rows(body["queue"]) == [], "no ledger → no ledger-recon rows"


# ── bad ledger file → honest 422 (#87 rule) ───────────────────────────────────────────

class TestBadLedgerIs422:
    def test_unreadable_ledger_is_422(self, client, hermetic_engine):
        resp = client.post(
            "/review/upload",
            files={
                "file": (_F5.name, _F5.read_bytes()),
                "ledger": ("ledger.xlsx", b"garbage-not-a-workbook"),
            },
        )
        assert resp.status_code == 422, resp.text

    def test_non_xlsx_ledger_is_422(self, client, hermetic_engine):
        resp = client.post(
            "/review/upload",
            files={
                "file": (_F5.name, _F5.read_bytes()),
                "ledger": ("ledger.txt", b"not xlsx"),
            },
        )
        assert resp.status_code == 422, resp.text


# ── sales/extract paths ignore a supplied ledger (even a bad one) ─────────────────────

class TestNonF5IgnoresLedger:
    def test_extract_primary_ignores_ledger(self, client, tmp_path, monkeypatch):
        # A non-Xero-F5 primary never assembles a ledger → the ledger (even garbage)
        # is ignored, not parsed → no 422, no ledger-recon rows.
        monkeypatch.setenv("AGENTASSIST_EXTRACT_ENGINE", "0")
        resp = client.post(
            "/review/upload",
            files={
                "file": ("export.xlsx", _synth_extract_xlsx(tmp_path)),
                "ledger": ("ledger.xlsx", b"garbage-would-422-if-parsed"),
            },
            data={"source": "extract"},   # AMENDED (Slice D): extract must be stated
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_kind"] == "extract_upload"
        assert "queue" not in body or _ledger_rows(body.get("queue", [])) == []


# ── multipart request shape: primary is REQUIRED ──────────────────────────────────────

class TestMultipartShape:
    def test_missing_primary_file_is_rejected(self, client):
        # No 'file' part at all → the multipart contract rejects it (422), not a 500.
        resp = client.post("/review/upload", files={"ledger": ("ledger.xlsx", b"x")})
        assert resp.status_code == 422, resp.text

    def test_non_xlsx_primary_is_422(self, client):
        resp = client.post("/review/upload", files={"file": ("export.txt", b"not a workbook")})
        assert resp.status_code == 422, resp.text
