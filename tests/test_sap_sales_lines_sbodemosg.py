"""
T2.28 — fetch_sales_lines against the FROZEN SBODEMOSG sales extract.

Resolves recon STOP #3 as an executable assertion: the raw sales rows in the
captured SBODEMOSG extract expose the tax code under the field name "VatGroup",
and for a SAP B1 client (empty tax-code mappings) those raw codes are ALREADY
canonical — ES33 / SO / OS / ZR — so normalize is an identity passthrough.

Hermetic: _do_fetch_paginated is monkeypatched to serve the frozen fixtures;
normalize is the identity used for SAP B1 clients.  No live SAP, no
sap_b1_server import.
"""
from __future__ import annotations

import json
from pathlib import Path

import reasoning.sap_lines as _sap_lines_mod
from reasoning.sap_lines import fetch_sales_lines

_EXTRACT = Path(__file__).parent / "fixtures" / "sbodemosg-extract"
_START = "2024-01-01"
_END = "2024-12-31"


def _load(name: str) -> list[dict]:
    return json.loads((_EXTRACT / name).read_text(encoding="utf-8"))


def _identity_norm(raw):
    # SAP B1 client behaviour: empty mappings → normalize returns raw unchanged.
    return str(raw or "").strip()


def _patch_from_fixtures(monkeypatch):
    entity_map = {
        "Invoices": _load("invoices.raw.json"),
        "CreditNotes": _load("credit-notes.raw.json"),
    }

    def _fetch(entity, period_start, period_end):
        return entity_map.get(entity, [])

    monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated", _fetch)
    monkeypatch.setattr(_sap_lines_mod, "_normalize_vat_group", _identity_norm)


class TestSbodemosgSalesExtract:
    def test_raw_vatgroup_field_is_literally_VatGroup(self):
        # The field name recon claim, asserted directly against the fixture.
        for doc in _load("invoices.raw.json"):
            for line in doc.get("DocumentLines", []):
                assert "VatGroup" in line
                break
            break

    def test_fetch_yields_lines_with_canonical_codes(self, monkeypatch):
        _patch_from_fixtures(monkeypatch)
        rows = fetch_sales_lines(_START, _END)
        assert rows, "expected sales lines from the frozen extract"
        codes = {r["vat_group"] for r in rows}
        # The captured extract carries these canonical sales codes verbatim.
        assert "ES33" in codes, f"expected an exempt ES33 line; got {sorted(codes)}"
        assert "SO" in codes, f"expected a standard SO line; got {sorted(codes)}"

    def test_es33_lines_are_exempt_and_unfiltered(self, monkeypatch):
        _patch_from_fixtures(monkeypatch)
        rows = fetch_sales_lines(_START, _END)
        es33 = [r for r in rows if r["vat_group"] == "ES33"]
        assert es33, "ES33 exempt lines must survive (no VatGroup filter)"
        for r in es33:
            assert set(r.keys()) == {
                "doc_num", "doc_type", "doc_date", "card_name", "line_index",
                "vat_group", "line_description", "line_total", "tax_total",
            }
            assert r["doc_type"] in {"sales_invoice", "sales_credit_note"}

    def test_invoice_and_credit_note_doc_types_present(self, monkeypatch):
        _patch_from_fixtures(monkeypatch)
        rows = fetch_sales_lines(_START, _END)
        assert any(r["doc_type"] == "sales_invoice" for r in rows)
        # credit-notes.raw.json has one doc, so a sales_credit_note row exists too.
        assert any(r["doc_type"] == "sales_credit_note" for r in rows)
