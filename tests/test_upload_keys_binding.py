"""tests/test_upload_keys_binding.py — bind the upload key constants to the live handlers.

WHY THIS FILE EXISTS. The api/app.py response-contract constants are referenced by zero
executable code, so before this test they could drift from the handler bodies with nothing
going red. XERO_UPLOAD_KEYS (now XERO_F5_UPLOAD_KEYS) drifted twice exactly that way —
first through the findings->queue rename, then through recomputed_client_coded_f5_boxes —
and cost one builder a false "the key does not exist" on a stale base.

Each test below runs a branch of POST /review/upload through TestClient and asserts the
response body's TOP-LEVEL KEY SET equals its constant, exactly. The constant can no longer
disagree with the handler; a new response key (or a renamed one) fails loud here until the
matching constant is updated in the same change.

Four branches, four constants (each true of exactly one thing):
  * "extract_upload"     (coverage-only, kill switch OFF) -> UPLOAD_COVERAGE_KEYS   (4 keys)
  * "extract_review"     (kill switch unset = default ON) -> EXTRACT_REVIEW_KEYS    (6 keys)
  * "xero_f5_upload"     (real-format F5 workbook)        -> XERO_F5_UPLOAD_KEYS    (6 keys)
  * "xero_sales_upload"  (real-format sales workbook)     -> XERO_SALES_REVIEW_KEYS (7 keys)

HONEST STATUS: real-Xero-FORMAT over SYNTHETIC fixtures; shape binding only — asserts
nothing about finding accuracy. Hermetic (SAP off, dummy creds, engine dirs -> tmp);
pure stdlib + pytest + fastapi.testclient; no anthropic import.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import (
    app,
    EXTRACT_REVIEW_KEYS,
    UPLOAD_COVERAGE_KEYS,
    XERO_F5_UPLOAD_KEYS,
    XERO_SALES_REVIEW_KEYS,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FROZEN_EXTRACT_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"
_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_SALES_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
    / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
)
_EXTRACT_FLAG = "AGENTASSIST_EXTRACT_ENGINE"

# synth exporter — local importlib load (tests/ is not a package; do NOT import it as a module).
_synth_spec = importlib.util.spec_from_file_location(
    "upload_keys_binding_synth_export",
    Path(__file__).resolve().parent / "synth_extract_export.py",
)
_synth = importlib.util.module_from_spec(_synth_spec)
_synth_spec.loader.exec_module(_synth)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic_engine(tmp_path, monkeypatch):
    """Redirect the engine's PDF dir + bundle audit root to tmp; set dummy SAP creds (the
    engine branches run the FULL review()). Mirrors test_xero_queue_contract.py."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")


def _synthetic_extract_bytes(tmp_path: Path) -> bytes:
    out = tmp_path / "synthetic_export.xlsx"
    _synth.export_xlsx(_FROZEN_EXTRACT_DIR, out)
    return out.read_bytes()


def _post(client: TestClient, content: bytes, filename: str, source: str | None = None):
    # AMENDED (Slice D): optional source; the extract callers state it, Xero callers do not.
    return client.post(
        "/review/upload", files={"file": (filename, content)},
        data={"source": source} if source else None,
    )


def test_coverage_only_branch_binds_to_upload_coverage_keys(
    client, hermetic_engine, tmp_path, monkeypatch
):
    monkeypatch.setenv(_EXTRACT_FLAG, "off")  # engine OFF -> coverage-only body
    resp = _post(client, _synthetic_extract_bytes(tmp_path), "export.xlsx", source="extract")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_kind"] == "extract_upload"
    assert set(body.keys()) == set(UPLOAD_COVERAGE_KEYS), (
        f"extract_upload body keys {sorted(body)} != UPLOAD_COVERAGE_KEYS "
        f"{sorted(UPLOAD_COVERAGE_KEYS)} — update the constant in the same change"
    )


def test_extract_review_branch_binds_to_extract_review_keys(
    client, hermetic_engine, tmp_path, monkeypatch
):
    monkeypatch.delenv(_EXTRACT_FLAG, raising=False)  # default = ON
    resp = _post(client, _synthetic_extract_bytes(tmp_path), "export.xlsx", source="extract")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_kind"] == "extract_review"
    assert set(body.keys()) == set(EXTRACT_REVIEW_KEYS), (
        f"extract_review body keys {sorted(body)} != EXTRACT_REVIEW_KEYS "
        f"{sorted(EXTRACT_REVIEW_KEYS)} — update the constant in the same change"
    )


def test_xero_f5_branch_binds_to_xero_f5_upload_keys(client, hermetic_engine):
    assert _F5_FIXTURE.is_file(), f"committed Xero F5 fixture missing: {_F5_FIXTURE}"
    resp = _post(client, _F5_FIXTURE.read_bytes(), _F5_FIXTURE.name)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_kind"] == "xero_f5_upload"
    assert set(body.keys()) == set(XERO_F5_UPLOAD_KEYS), (
        f"xero_f5_upload body keys {sorted(body)} != XERO_F5_UPLOAD_KEYS "
        f"{sorted(XERO_F5_UPLOAD_KEYS)} — update the constant in the same change"
    )


def test_xero_sales_branch_binds_to_xero_sales_review_keys(client, hermetic_engine):
    assert _SALES_FIXTURE.is_file(), f"committed Xero sales fixture missing: {_SALES_FIXTURE}"
    resp = _post(client, _SALES_FIXTURE.read_bytes(), _SALES_FIXTURE.name)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_kind"] == "xero_sales_upload"
    assert set(body.keys()) == set(XERO_SALES_REVIEW_KEYS), (
        f"xero_sales_upload body keys {sorted(body)} != XERO_SALES_REVIEW_KEYS "
        f"{sorted(XERO_SALES_REVIEW_KEYS)} — update the constant in the same change"
    )


def test_the_four_constants_disagree_where_the_branches_do():
    """The constants are per-branch statements, not restatements of one another."""
    assert set(UPLOAD_COVERAGE_KEYS) < set(EXTRACT_REVIEW_KEYS)
    assert set(UPLOAD_COVERAGE_KEYS) < set(XERO_F5_UPLOAD_KEYS)
    assert set(EXTRACT_REVIEW_KEYS) < set(XERO_SALES_REVIEW_KEYS)
    # F5 is NOT a subset of sales (the box object is F5-only) and vice versa.
    assert not set(XERO_F5_UPLOAD_KEYS) <= set(XERO_SALES_REVIEW_KEYS)
    assert not set(XERO_SALES_REVIEW_KEYS) <= set(XERO_F5_UPLOAD_KEYS)
