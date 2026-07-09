"""tests/test_xero_sales_upload.py — inbound Xero SALES-INVOICE upload: end-to-end router +
engine smoke (the STEP-5 render smoke for the xero_sales option-3 slice).

Posts the committed synthetic Xero sales-invoice fixture to POST /review/upload and asserts the
router takes the xero_sales branch, the engine review COMPLETES, and the response surfaces:
  * coverage_status with the honestly-degraded/unavailable checks (NO_GST_REG unavailable,
    DUP_CLAIM/SEQ_GAP degraded) — the SAME seam the F5/extract paths use, and
  * the VISIBLE out-of-scope-lines note (the "No Tax" line on INV-2003), never silent.

HONEST STATUS: real-Xero-FORMAT over SYNTHETIC data — candidates, never verdicts;
validation_status stays "unvalidated"; no ai_candidates. Hermetic (SAP off, no tokens): the
engine PDF dir + audit root are redirected to tmp and dummy SAP creds are set, mirroring
tests/test_xero_queue_contract.py's fixture.

Pure stdlib + pytest + fastapi.testclient. No anthropic import.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app, OUT_OF_SCOPE_KEYS, XERO_SALES_REVIEW_KEYS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
    / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
)
_FILENAME = "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"

_COVERAGE_LEVELS = {"full", "degraded", "unavailable"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hermetic_engine(tmp_path, monkeypatch):
    """Redirect the engine's PDF dir + bundle audit root to tmp; set dummy SAP creds (the branch
    runs the FULL review()). Mirrors test_xero_queue_contract.py's hermetic fixture."""
    monkeypatch.setattr("engine.review._REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr("audit_bundle.seal._AUDIT_ROOT", tmp_path / "audit")
    monkeypatch.setenv("SAP_USERNAME", "dummy")
    monkeypatch.setenv("SAP_PASSWORD", "dummy")


def _coverage_row(rows: list, check: str) -> dict:
    for row in rows:
        if row["check"] == check:
            return row
    raise AssertionError(f"coverage check {check!r} not in {[r['check'] for r in rows]}")


def test_xero_sales_upload_routes_completes_and_surfaces_coverage(client, hermetic_engine):
    assert _FIXTURE.is_file(), f"committed Xero sales fixture missing: {_FIXTURE}"

    resp = client.post(f"/review/upload?filename={_FILENAME}", content=_FIXTURE.read_bytes())
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Routed to the xero_sales branch with the documented response shape.
    assert body["source_kind"] == "xero_sales_upload"
    assert set(body.keys()) == set(XERO_SALES_REVIEW_KEYS)
    assert body["config_scope"] == "xero_sales_demo"

    # Honest framing + frozen flags.
    assert body["validation_status"] == "unvalidated"
    assert "ai_candidates" not in body

    # coverage_status: same honest-degrade seam; every non-full row carries a reason.
    rows = body["coverage_status"]
    assert isinstance(rows, list) and rows
    for row in rows:
        assert set(row.keys()) == {"check", "level", "reason"}
        assert row["level"] in _COVERAGE_LEVELS
        if row["level"] != "full":
            assert row["reason"].strip()
    assert _coverage_row(rows, "NO_GST_REG")["level"] == "unavailable"
    assert _coverage_row(rows, "DUP_CLAIM")["level"] == "degraded"
    assert _coverage_row(rows, "SEQ_GAP")["level"] == "degraded"

    # queue is a list (the clean synthetic fixture yields no E-check findings — that is fine).
    assert isinstance(body["queue"], list)

    # The VISIBLE out-of-scope-lines note (the "No Tax" line), never silent.
    oos = body["out_of_scope"]
    assert set(oos.keys()) == set(OUT_OF_SCOPE_KEYS)
    assert oos["count"] == 1
    assert oos["by_code"] == {"NO TAX": 1}
    assert oos["reason"].strip()
