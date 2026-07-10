"""tests/test_documents_legibility_e2e.py — T2.14 end-to-end illegible-PDF proof.

The merged T2.14 gate (`documents/legibility.py`) is unit-proven on hand-built
`ExtractedInvoice` objects. This file closes the remaining linkage: a genuinely
illegible BORN-DIGITAL PDF, run through the real `ingest()` regex path, produces
the field shape the gate keys on and lands as a manual-review coverage row on the
ungated surface — end to end, hermetically.

Scope (Terry-approved leans):
  Q1 — a synthetic born-digital reportlab PDF is the accepted born-digital proxy;
       the image-only-scan case stays OUT of scope.
  Q2 — the multimodal null-count branch stays on constructed inputs (no e2e, no
       mock, no live call) — reportlab always emits a text layer, so these
       fixtures always route born-digital.
  Q3 — fixtures are generated at test time into tmp_path; no committed binary.
  Q4 — two illegible fixtures (missing-key-field + calendar-invalid-date) plus a
       legible control.

Test-only: no production file is touched; the gate/chain/report machinery is
consumed exactly as it ships on master (PR #96, 6988a30).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pdfplumber
import pytest

from config.loader import ClientConfig
from documents.doc_pass import run_documents_pass
from documents.ingest import _has_text_layer, ingest
from documents.legibility import assess_legibility
from documents.provider import FixtureDocumentProvider
from report.render import render_check_coverage_section, render_pdf
from report.report import build_report

# ---------------------------------------------------------------------------
# Load the NEW generator by file path (mirrors conftest's fixture-gen pattern;
# no assumption that `tests` is an importable package). RED until the file
# exists — exec_module raises FileNotFoundError at collection.
# ---------------------------------------------------------------------------
_GEN_PATH = Path(__file__).parent / "fixtures" / "documents" / "generate_illegible_invoices.py"
_spec = importlib.util.spec_from_file_location("generate_illegible_invoices", _GEN_PATH)
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)

# ---------------------------------------------------------------------------
# Shared constants / builders
# ---------------------------------------------------------------------------
_CHAIN_FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"
_PS = "2024-07-01"
_PE = "2024-09-30"


def _line_item(doc_num: int, *, tax_total: float = 350.0) -> dict:
    return dict(
        doc_num=doc_num,
        doc_type="purchase_invoice",
        doc_date="2024-07-15",
        card_name="TechSupply Solutions Pte Ltd",
        line_index=0,
        vat_group="SI",
        line_description="Services rendered",
        line_total=5000.0,
        tax_total=tax_total,
    )


def _make_cfg(**overrides) -> ClientConfig:
    base = dict(
        client_id="sbodemosg",
        client_name="SBODEMOSG Demo",
        gst_registration_number="M12345678X",
        applicable_gst_rate=0.07,
        service_layer_url="https://fake",
        company_db="SBODEMOSG",
        username="manager",
        password="manager",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.1,
        reviewer_name="Terry Yeo",
        firm_name="AgentAssist Pte Ltd",
    )
    base.update(overrides)
    return ClientConfig(**base)


# ---------------------------------------------------------------------------
# Routing guard — pins the born-digital premise (a future reportlab change that
# dropped the text layer would reroute to multimodal and silently break this).
# ---------------------------------------------------------------------------

def test_generated_pdfs_route_born_digital(tmp_path):
    for draw in (
        _gen.draw_missing_gst_amount,
        _gen.draw_calendar_invalid_date,
        _gen.draw_legible_control,
    ):
        pdf = draw(tmp_path)
        assert _has_text_layer(pdf) is True
        assert ingest(pdf).source == "born_digital"


# ---------------------------------------------------------------------------
# Missing-key-field (gst_amount) — key-field-absence branch, end to end
# ---------------------------------------------------------------------------

def test_missing_gst_amount_e2e(tmp_path):
    pdf = _gen.draw_missing_gst_amount(tmp_path, doc_num=4001)

    extracted = ingest(pdf)
    assert extracted.source == "born_digital"
    assert extracted.gst_amount is None            # the state the gate keys on
    assert extracted.invoice_date == "2024-07-15"  # other key field present + valid

    status = assess_legibility(extracted)
    assert status.needs_manual_review is True
    assert "gst_amount" in status.reason

    rows: list = []
    cands = run_documents_pass(
        [_line_item(4001)], FixtureDocumentProvider(tmp_path), _PS, _PE, legibility_rows=rows
    )
    assert cands == []                              # zero reconcile candidates
    assert len(rows) == 1                           # exactly one manual-review row
    assert rows[0]["level"] == "unavailable"
    assert "manual review required" in rows[0]["reason"].lower()
    assert "4001" in rows[0]["check"]
    assert rows[0]["validation_status"] == "unvalidated"


# ---------------------------------------------------------------------------
# Calendar-invalid date (2024-13-45) — the open-item-#28 motivating case
# ---------------------------------------------------------------------------

def test_calendar_invalid_date_e2e(tmp_path):
    pdf = _gen.draw_calendar_invalid_date(tmp_path, doc_num=4002)

    extracted = ingest(pdf)
    assert extracted.source == "born_digital"
    # regex-passing (non-None) but not a real calendar date
    assert extracted.invoice_date == "2024-13-45"

    status = assess_legibility(extracted)
    assert status.needs_manual_review is True
    assert "2024-13-45" in status.reason

    rows: list = []
    cands = run_documents_pass(
        [_line_item(4002)], FixtureDocumentProvider(tmp_path), _PS, _PE, legibility_rows=rows
    )
    assert cands == []
    assert len(rows) == 1
    assert "4002" in rows[0]["check"]
    assert "manual review required" in rows[0]["reason"].lower()


# ---------------------------------------------------------------------------
# Legible control — proves the generator does NOT spuriously trip the gate and
# that reconcile still runs over its output.
# ---------------------------------------------------------------------------

def test_legible_control_e2e(tmp_path):
    pdf = _gen.draw_legible_control(tmp_path, doc_num=4003)

    extracted = ingest(pdf)
    assert extracted.source == "born_digital"
    assert extracted.gst_amount == pytest.approx(900.0)
    assert extracted.invoice_date == "2024-07-15"
    assert assess_legibility(extracted).needs_manual_review is False

    rows: list = []
    cands = run_documents_pass(
        [_line_item(4003, tax_total=840.0)],  # pdf 900 vs record 840 → mismatch
        FixtureDocumentProvider(tmp_path), _PS, _PE, legibility_rows=rows,
    )
    assert rows == []                              # zero manual-review rows
    assert len(cands) == 1
    assert cands[0].check_id == "gst_amount_mismatch"


# ---------------------------------------------------------------------------
# Surface: the manual-review row renders in the ACTUAL PDF, ungated
# ---------------------------------------------------------------------------

def test_manual_review_row_renders_in_pdf(tmp_path):
    pdf = _gen.draw_missing_gst_amount(tmp_path, doc_num=4001)
    rows: list = []
    run_documents_pass(
        [_line_item(4001)], FixtureDocumentProvider(tmp_path), _PS, _PE, legibility_rows=rows
    )
    assert rows and rows[0]["validation_status"] == "unvalidated"

    raw = json.loads(_CHAIN_FIXTURE.read_text(encoding="utf-8"))
    cfg = _make_cfg()  # show_ai_candidates defaults to False
    model = build_report(raw, cfg, generated_at=_GENERATED_AT, document_legibility_rows=rows)

    # gated candidate stream OFF, coverage surface renders the row
    assert model.unified_candidates.show is False
    text = render_check_coverage_section(model.check_coverage)
    assert "manual review required" in text.lower()
    assert "4001" in text

    # and it appears in the rendered PDF itself
    out = tmp_path / "report.pdf"
    render_pdf(model, out)
    with pdfplumber.open(out) as doc:
        pdf_text = "\n".join((p.extract_text() or "") for p in doc.pages)
    assert "manual review required" in pdf_text.lower()
    assert "4001" in pdf_text
