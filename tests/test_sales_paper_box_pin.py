"""tests/test_sales_paper_box_pin.py -- the SALES signed paper's box-row PDF-text pin
(D-2026-07-26-box-capability, R8/A7) FAILING-FIRST.

WHY THIS FILE EXISTS: tests/test_sign_upload_sales.py carried NO PDF-text pin, which
is how a signed paper stating a fabricated statutory figure (Box 5/7 = 0.00 over a
source with no purchase side; Box 8 derived from the fabricated Box 7) passed CI.
This NEW file adds the missing pin. R8 named test_sign_upload_sales.py as the pin's
home; that file is LOCKED (append-only tests/ boundary), so the pin lives here and
its placement is flagged in Terry's hand-amendment package.

FAILS TODAY (the A7 proof): today's master renders "Taxable purchases 0.00" /
"Input tax and refunds claimed 0.00" on the sales paper and no marker exists, so
P1's positive marker assertions go red against the pre-build render. After the
build, boxes 5/7 carry the marker, Box 3 stays a genuine 0.00 figure, and Box 8
renders its figure marked derived-from-incomplete NAMING Box 7 (R4 -- no bound, no
direction).

A8: the marker wording must clear every negative paper pin under BOTH extraction
libraries (pdfplumber AND pdfminer) -- asserted in P3 over the enumerated literals.

HERMETIC: mirrors tests/test_sign_upload_sales.py's fixture pattern (tmp dirs, fresh
per-call audit subdir, dummy SAP creds, committed ES33-free sales fixture -> the
exempt pass short-circuits with NO model call). No anthropic import. Does NOT edit
any existing test file.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

import audit_bundle.seal as _seal
from api.app import app

_UPLOAD_SEQ = itertools.count()
_REPO_ROOT = Path(__file__).resolve().parents[1]

_SALES_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
    / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
)
_SALES_FILENAME = "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"

# A8 -- every negative paper pin enumerated (their home files are LOCKED; this build
# passes them by wording choice):
#   * test_report_redesign_severity_removed.py (pdfminer, full-PDF): "Severity",
#     "HIGH", "MEDIUM", "LOW" must not appear;
#   * test_decision_render.py _BANNED_PAPER_LITERALS (T4/T6/T7 homes:
#     test_t58_mock_engine.py / test_accumulated_sign.py): "AI-Surfaced Candidates",
#     "AI-surfaced candidates", "Signature suppressed", "Do not sign";
#   * test_decision_render.py _BANNED_VERBS: "Not an issue", "Mark known";
#   * test_decision_render.py silent-paper pin: "adjudication" absent when the
#     decision store is empty (this fixture's store IS empty).
_NEGATIVE_PINS = (
    "Severity", "HIGH", "MEDIUM", "LOW",
    "AI-Surfaced Candidates", "AI-surfaced candidates",
    "Signature suppressed", "Do not sign",
    "Not an issue", "Mark known",
    "adjudication",
)


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


def _bump_audit() -> None:
    _seal._AUDIT_ROOT = _seal._AUDIT_ROOT.parent / f"audit-{next(_UPLOAD_SEQ)}"


def _sign_sales(client: TestClient) -> dict:
    _bump_audit()
    resp = client.post(
        "/sign/upload",
        data={"reviewer_name": "Collin Tan", "firm_name": ""},
        files={"file": (_SALES_FILENAME, _SALES_FIXTURE.read_bytes())},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _plumber_text(pdf_path: str) -> str:
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(pdf_path) as pdf:
        raw = " ".join((page.extract_text() or "") for page in pdf.pages)
    return " ".join(raw.split())


def _miner_text(pdf_path: str) -> str:
    high_level = pytest.importorskip("pdfminer.high_level")
    return " ".join(high_level.extract_text(str(pdf_path)).split())


# -- P1 (A2/A7) -- THE pin: box rows on the sales signed paper ------------------------


def test_p1_sales_paper_box_rows(client, hermetic):
    """Boxes 5/7 marked unavailable (no figure); Box 3 a genuine 0.00 FIGURE; Box 8
    its figure marked derived-from-incomplete NAMING Box 7; sales-side figures intact.

    FAILS TODAY: the pre-build paper renders 'Taxable purchases 0.00' and no marker.
    """
    body = _sign_sales(client)
    text = _plumber_text(body["working_paper_path"])

    # Structurally-unknowable boxes: marker, never a figure (summary AND breakdown).
    assert "Taxable purchases (Box 5) Not available from this source" in text
    assert "Input tax claimed (Box 7) Not available from this source" in text
    assert "Taxable purchases Not available from this source" in text
    assert "Input tax and refunds claimed Not available from this source" in text
    assert "Taxable purchases (Box 5) 0.00" not in text
    assert "Taxable purchases 0.00" not in text
    assert "Input tax claimed (Box 7) 0.00" not in text
    assert "Input tax and refunds claimed 0.00" not in text

    # Box 3 is KNOWABLE and genuinely zero on this fixture -- it stays a FIGURE.
    assert "Exempt supplies 0.00" in text

    # Box 8: figure rendered, marked derived from an incomplete input, NAMING Box 7,
    # claiming no bound and no direction (R4).
    assert "(refunded) 2,070.00" in text
    assert "Derived from an incomplete input: Box 7" in text
    assert "Input tax and refunds claimed is not available from this source" in text

    # Sales-side figures untouched.
    assert "Standard-rated supplies (Box 1) 23,000.00" in text
    assert "Zero-rated supplies 5,000.00" in text
    assert "Total value of taxable supplies 28,000.00" in text
    assert "Output tax due (Box 6) 2,070.00" in text


# -- P2 -- the paper GLOSSES the seal (additive), never contradicts it ----------------


def test_p2_paper_glosses_seal_never_contradicts(client, hermetic):
    """The sealed bundle keeps the raw computed zeros for Box 5/7 while the paper
    marks them unavailable -- every sealed figure accounted for, interpretation added
    (the D-2026-07-24-decision-render ADDITIVE shape, not the DEAD filter)."""
    body = _sign_sales(client)
    sealed = json.loads(
        (Path(body["bundle_dir"]) / "compile-output.json").read_text(encoding="utf-8")
    )
    boxes = sealed["calculate"]["boxes"]
    assert boxes["box_5_taxable_purchases"] == 0.0
    assert boxes["box_7_input_tax"] == 0.0
    assert boxes["box_8_net_gst"] == 2070.0
    assert sealed["box_capability"]["declared_sides"] == ["sales"]

    text = _plumber_text(body["working_paper_path"])
    # The paper still renders all 8 box ROWS (suppression is the DEAD shape).
    for label_fragment in (
        "Standard-rated supplies", "Zero-rated supplies", "Exempt supplies",
        "Total value of taxable supplies", "Taxable purchases",
        "Output tax due", "Input tax and refunds claimed", "Net GST to be paid",
    ):
        assert label_fragment in text, f"all 8 rows stay on the paper: {label_fragment}"


# -- P3 (A8) -- wording clears every negative pin under BOTH extractors ---------------


def test_p3_wording_clears_negative_pins_both_extractors(client, hermetic):
    body = _sign_sales(client)
    for extract in (_plumber_text, _miner_text):
        text = extract(body["working_paper_path"])
        for banned in _NEGATIVE_PINS:
            assert banned not in text, (
                f"marker wording must not introduce the banned literal {banned!r} "
                f"(extractor: {extract.__name__})"
            )


# -- P4 -- response contract untouched ------------------------------------------------


def test_p4_response_contract_unchanged(client, hermetic):
    """The render change is paper-only: the 7-key sign response and its values are
    byte-identical in shape (no new key, source_kind unchanged)."""
    from api.app import SIGN_UPLOAD_KEYS

    body = _sign_sales(client)
    assert set(body.keys()) == set(SIGN_UPLOAD_KEYS)
    assert body["source_kind"] == "xero_sales_signed"
    assert body["validation_status"] == "unvalidated"
