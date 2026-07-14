"""Failing-first tests for the Xero sales reader's per-line description emit (Prompt D Phase 2).

Locks (three-times rule — prompt + code + test):

  1. VERBATIM EMIT — each sales line carries ``line_description`` (str), the export's
     ``Description`` column value passed through verbatim (matching the reasoning-contract
     key name exactly, so the Prompt-E adapter is a straight passthrough).
  2. TOLERANT DEFAULT — a blank Description cell → ``""``; an export with NO Description
     column at all parses without crashing → ``""``.
  3. APPEND-ONLY — the pre-existing line keys (VatGroup / LineTotal / TaxTotal) are
     untouched beside the new key.
  4. BOX-ISOLATION — F5 boxes are byte-identical with and without the new key:
     calculate_f5_return over the real reader vs. a wrapper that strips
     ``line_description`` from every line produces identical JSON.

HONEST RUNG (T2.11): line_description emit is real-FORMAT over synthetic Xero, NOT
real-client-validated; field is INERT until the Prompt E adapter wires sales_line_source —
the exempt skill does NOT run on Xero yet.

Pure stdlib + pytest (+ openpyxl lazily in the fixture builder). No anthropic.
"""
from __future__ import annotations

import copy
import csv
import sys
from pathlib import Path

from feeders.xero_sales_reader import XeroSalesInvoiceChainReader

from config.loader import load_client_config
from tests.synth_xero_sales_export import COLUMNS, DEMO_ROWS, write_csv

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
FIXTURE_XLSX = _FIXTURE_DIR / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
FIXTURE_CSV = _FIXTURE_DIR / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.csv"

PERIOD_START = "2026-04-01"
PERIOD_END = "2026-06-30"


def _reader(source=FIXTURE_XLSX):
    cfg = load_client_config("xero_sales_demo", check_connectivity=False)
    return XeroSalesInvoiceChainReader(
        source,
        tax_code_mappings=cfg.effective_tax_code_mappings,
        out_of_scope_codes=cfg.out_of_scope_codes,
    )


def _by_docnum(docs):
    return {str(d.get("DocNum")): d for d in docs}


# ---------------------------------------------------------------------------
# 1. VERBATIM EMIT — fixture Description values flow through, per line, in order.
# ---------------------------------------------------------------------------


def test_line_description_carried_verbatim_csv_and_xlsx():
    for source in (FIXTURE_XLSX, FIXTURE_CSV):
        sales = _by_docnum(_reader(source).fetch_invoices("Invoices", PERIOD_START, PERIOD_END))
        # INV-2001 is multi-line: both descriptions, in first-seen row order.
        descs = [ln["line_description"] for ln in sales["INV-2001"]["DocumentLines"]]
        assert descs == ["Consulting services", "Support retainer"], f"source={source}"
        # Single-line invoices carry theirs verbatim too.
        assert sales["INV-2002"]["DocumentLines"][0]["line_description"] == "Export goods"
        assert sales["INV-2003"]["DocumentLines"][0]["line_description"] == "Advisory"


def test_line_description_is_str_on_every_line():
    for doc in _reader().fetch_invoices("Invoices", PERIOD_START, PERIOD_END):
        for line in doc["DocumentLines"]:
            assert isinstance(line["line_description"], str)


# ---------------------------------------------------------------------------
# 2. TOLERANT DEFAULT — blank cell and missing column both yield "".
# ---------------------------------------------------------------------------


def test_blank_description_cell_falls_back_to_empty_string(tmp_path):
    rows = [dict(DEMO_ROWS[2])]  # INV-2002, single line
    rows[0]["Description"] = ""
    src = write_csv(tmp_path / "blank-desc.csv", rows)
    sales = _by_docnum(_reader(src).fetch_invoices("Invoices", PERIOD_START, PERIOD_END))
    assert sales["INV-2002"]["DocumentLines"][0]["line_description"] == ""


def test_missing_description_column_tolerated(tmp_path):
    """A description-less export (no Description column at all) must not crash."""
    cols = [c for c in COLUMNS if c != "Description"]
    src = tmp_path / "no-desc-col.csv"
    with src.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in DEMO_ROWS:
            writer.writerow({c: row.get(c, "") for c in cols})
    sales = _by_docnum(_reader(src).fetch_invoices("Invoices", PERIOD_START, PERIOD_END))
    assert set(sales) == {"INV-2001", "INV-2002", "INV-2003"}
    for doc in sales.values():
        for line in doc["DocumentLines"]:
            assert line["line_description"] == ""


# ---------------------------------------------------------------------------
# 3. APPEND-ONLY — pre-existing keys untouched beside the new one.
# ---------------------------------------------------------------------------


def test_existing_line_keys_untouched():
    sales = _by_docnum(_reader().fetch_invoices("Invoices", PERIOD_START, PERIOD_END))
    for line in sales["INV-2001"]["DocumentLines"]:
        assert set(line.keys()) >= {"VatGroup", "LineTotal", "TaxTotal", "line_description"}
        assert line["LineTotal"] == 10000.0
        assert line["TaxTotal"] == 900.0


# ---------------------------------------------------------------------------
# 4. BOX-ISOLATION — F5 boxes byte-identical with/without the new key.
# ---------------------------------------------------------------------------


class _StrippingReader:
    """Delegating wrapper that removes line_description from every fetched line —
    the with/without comparison surface for the box-isolation proof."""

    def __init__(self, inner):
        self._inner = inner

    def fetch_invoices(self, entity, period_start, period_end):
        docs = copy.deepcopy(self._inner.fetch_invoices(entity, period_start, period_end))
        for doc in docs:
            for line in doc.get("DocumentLines", []):
                line.pop("line_description", None)
        return docs

    def fetch_credit_notes(self, entity_type, period_start, period_end):
        return self._inner.fetch_credit_notes(entity_type, period_start, period_end)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_f5_boxes_byte_identical_with_and_without_line_description():
    import sap_b1_server  # noqa: PLC0415 — path inserted at module top

    reader = _reader()
    with_key = sap_b1_server.calculate_f5_return(
        PERIOD_START, PERIOD_END, reader=reader
    )
    without_key = sap_b1_server.calculate_f5_return(
        PERIOD_START, PERIOD_END, reader=_StrippingReader(_reader())
    )
    assert with_key == without_key, (
        "F5 output changed when line_description was stripped — the key is NOT inert"
    )
