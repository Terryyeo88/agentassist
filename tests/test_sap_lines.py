"""
Tests for reasoning/sap_lines.py — SAP SI purchase line fetch helper.

All tests use a mocked SAP client (monkeypatching _do_fetch_paginated).
No live SAP instance is contacted.
"""
from __future__ import annotations

import pytest

import reasoning.sap_lines as _sap_lines_mod
from reasoning.sap_lines import (
    LINE_DESCRIPTION_FIELD,
    _extract_si_lines,
    _get_line_description,
    fetch_si_purchase_lines,
)

_START = "2024-07-01"
_END   = "2024-09-30"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(
    doc_num: int,
    card_name: str = "Supplier Co",
    doc_date: str = "2024-07-15",
    lines: list[dict] | None = None,
) -> dict:
    return {
        "DocNum": doc_num,
        "CardName": card_name,
        "DocDate": doc_date + "T00:00:00Z",
        "DocumentLines": lines or [],
    }


def _line(
    vat_group: str = "SI",
    item_desc: str = "Medical Consultation",
    item_code: str = "MED001",
    line_total: float = 100.0,
    tax_total: float = 9.0,
    extra: dict | None = None,
) -> dict:
    d = {
        "VatGroup": vat_group,
        "ItemDescription": item_desc,
        "ItemCode": item_code,
        "LineTotal": line_total,
        "TaxTotal": tax_total,
    }
    if extra:
        d.update(extra)
    return d


def _fake_fetch(entity_map: dict[str, list[dict]]):
    """Return a _do_fetch_paginated replacement that returns canned docs."""
    def _fetch(entity: str, period_start: str, period_end: str) -> list[dict]:
        return entity_map.get(entity, [])
    return _fetch


# ---------------------------------------------------------------------------
# T1 — LINE_DESCRIPTION_FIELD constant
# ---------------------------------------------------------------------------

class TestLineDescriptionField:
    def test_constant_is_ItemDescription(self):
        assert LINE_DESCRIPTION_FIELD == "ItemDescription"

    def test_primary_field_used_when_present(self):
        line = {"ItemDescription": "Medical Consultation", "ItemCode": "MED001"}
        assert _get_line_description(line) == "Medical Consultation"

    def test_legacy_dscription_used_when_primary_absent(self):
        line = {"Dscription": "Legacy Desc", "ItemCode": "X001"}
        assert _get_line_description(line) == "Legacy Desc"

    def test_itemcode_last_resort_when_both_desc_absent(self):
        line = {"ItemCode": "SKU999"}
        assert _get_line_description(line) == "SKU999"

    def test_empty_string_returned_when_all_absent(self):
        assert _get_line_description({}) == ""

    def test_strips_whitespace(self):
        line = {"ItemDescription": "  Dental Check  "}
        assert _get_line_description(line) == "Dental Check"

    def test_primary_takes_precedence_over_legacy(self):
        line = {"ItemDescription": "Primary", "Dscription": "Legacy", "ItemCode": "X"}
        assert _get_line_description(line) == "Primary"

    def test_primary_empty_string_falls_back_to_legacy(self):
        line = {"ItemDescription": "", "Dscription": "Legacy"}
        assert _get_line_description(line) == "Legacy"


# ---------------------------------------------------------------------------
# T2 — SI-only filtering
# ---------------------------------------------------------------------------

class TestSIFiltering:
    def test_si_lines_included(self, monkeypatch):
        docs = [_doc(1, lines=[_line("SI")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        assert len(result) == 1
        assert result[0]["vat_group"] == "SI"

    def test_non_si_lines_excluded(self, monkeypatch):
        docs = [_doc(1, lines=[_line("ZP"), _line("BL"), _line("SO")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        assert result == []

    def test_mixed_lines_only_si_returned(self, monkeypatch):
        docs = [_doc(1, lines=[_line("SI"), _line("ZP"), _line("SI")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        assert len(result) == 2
        assert all(r["vat_group"] == "SI" for r in result)

    def test_empty_vat_group_excluded(self, monkeypatch):
        docs = [_doc(1, lines=[_line("")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        assert fetch_si_purchase_lines(_START, _END) == []

    def test_none_vat_group_excluded(self, monkeypatch):
        docs = [_doc(1, lines=[{**_line(), "VatGroup": None}])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        assert fetch_si_purchase_lines(_START, _END) == []


# ---------------------------------------------------------------------------
# T3 — line_description field populated from ItemDescription
# ---------------------------------------------------------------------------

class TestDescriptionField:
    def test_item_description_used(self, monkeypatch):
        docs = [_doc(1, lines=[_line("SI", item_desc="Clinic Visit")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        assert result[0]["line_description"] == "Clinic Visit"

    def test_description_field_always_present_in_output(self, monkeypatch):
        docs = [_doc(1, lines=[_line("SI")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        assert "line_description" in result[0]


# ---------------------------------------------------------------------------
# T4 — Pagination: more than 20 lines handled correctly
# ---------------------------------------------------------------------------

class TestPagination:
    def test_more_than_20_si_lines_returned(self, monkeypatch):
        # 25 SI lines across 3 documents
        docs = [
            _doc(i, lines=[_line("SI")] * 9)
            for i in range(1, 4)
        ]
        # doc 1: 9 lines, doc 2: 9 lines, doc 3: 9 lines = 27 SI lines
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        assert len(result) == 27

    def test_all_lines_from_multiple_docs_returned(self, monkeypatch):
        docs = [
            _doc(1, lines=[_line("SI", item_desc="Line A1"), _line("SI", item_desc="Line A2")]),
            _doc(2, lines=[_line("SI", item_desc="Line B1")]),
        ]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        assert len(result) == 3
        descs = {r["line_description"] for r in result}
        assert descs == {"Line A1", "Line A2", "Line B1"}


# ---------------------------------------------------------------------------
# T5 — Credit-note lines tagged with correct doc_type
# ---------------------------------------------------------------------------

class TestCreditNoteDocType:
    def test_purchase_invoice_lines_tagged(self, monkeypatch):
        inv_docs = [_doc(10, lines=[_line("SI")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": inv_docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        assert result[0]["doc_type"] == "purchase_invoice"

    def test_purchase_credit_note_lines_tagged(self, monkeypatch):
        cn_docs = [_doc(20, lines=[_line("SI")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": [],
                                         "PurchaseCreditNotes": cn_docs}))
        result = fetch_si_purchase_lines(_START, _END)
        assert result[0]["doc_type"] == "purchase_credit_note"

    def test_both_types_returned_together(self, monkeypatch):
        inv_docs = [_doc(10, lines=[_line("SI", item_desc="Invoice Line")])]
        cn_docs  = [_doc(20, lines=[_line("SI", item_desc="Credit Line")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": inv_docs,
                                         "PurchaseCreditNotes": cn_docs}))
        result = fetch_si_purchase_lines(_START, _END)
        assert len(result) == 2
        types = {r["doc_type"] for r in result}
        assert types == {"purchase_invoice", "purchase_credit_note"}

    def test_credit_note_si_filtering_works(self, monkeypatch):
        cn_docs = [_doc(20, lines=[_line("SI"), _line("ZP")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": [],
                                         "PurchaseCreditNotes": cn_docs}))
        result = fetch_si_purchase_lines(_START, _END)
        assert len(result) == 1
        assert result[0]["doc_type"] == "purchase_credit_note"


# ---------------------------------------------------------------------------
# T6 — (doc_num, line_index) uniqueness
# ---------------------------------------------------------------------------

class TestDocNumLineIndexUniqueness:
    def test_no_duplicate_doc_num_line_index_pairs(self, monkeypatch):
        # Three docs each with two SI lines → 6 pairs, all unique
        docs = [
            _doc(1, lines=[_line("SI"), _line("SI")]),
            _doc(2, lines=[_line("SI"), _line("SI")]),
            _doc(3, lines=[_line("SI"), _line("SI")]),
        ]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        pairs = [(r["doc_num"], r["line_index"]) for r in result]
        assert len(pairs) == len(set(pairs)), f"Duplicate (doc_num, line_index) pairs: {pairs}"

    def test_line_index_is_sequential_per_doc(self, monkeypatch):
        docs = [_doc(1, lines=[_line("SI"), _line("ZP"), _line("SI")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        result = fetch_si_purchase_lines(_START, _END)
        # Original positions: idx=0 (SI), idx=1 (ZP — filtered), idx=2 (SI)
        assert len(result) == 2
        assert result[0]["line_index"] == 0
        assert result[1]["line_index"] == 2

    def test_same_doc_num_in_invoices_and_credit_notes_distinguished_by_type(
        self, monkeypatch
    ):
        # doc_num=5 appears in both PurchaseInvoices and PurchaseCreditNotes.
        # This is realistic (credit notes reference invoice doc nums).
        # line_index=0 in both — pairs are (5,0) and (5,0) but doc_type differs.
        inv_docs = [_doc(5, lines=[_line("SI")])]
        cn_docs  = [_doc(5, lines=[_line("SI")])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": inv_docs,
                                         "PurchaseCreditNotes": cn_docs}))
        result = fetch_si_purchase_lines(_START, _END)
        assert len(result) == 2
        types = {r["doc_type"] for r in result}
        assert types == {"purchase_invoice", "purchase_credit_note"}


# ---------------------------------------------------------------------------
# T7 — Output field completeness
# ---------------------------------------------------------------------------

class TestOutputFields:
    def _get_one(self, monkeypatch, **kwargs) -> dict:
        docs = [_doc(1, lines=[_line("SI", **kwargs)])]
        monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                            _fake_fetch({"PurchaseInvoices": docs,
                                         "PurchaseCreditNotes": []}))
        return fetch_si_purchase_lines(_START, _END)[0]

    def test_all_required_keys_present(self, monkeypatch):
        row = self._get_one(monkeypatch)
        required = {"doc_num", "doc_type", "doc_date", "card_name",
                    "line_index", "vat_group", "line_description",
                    "line_total", "tax_total"}
        assert required <= set(row.keys())

    def test_doc_num_is_int(self, monkeypatch):
        row = self._get_one(monkeypatch)
        assert isinstance(row["doc_num"], int)

    def test_line_total_is_float(self, monkeypatch):
        row = self._get_one(monkeypatch, line_total=75.5)
        assert isinstance(row["line_total"], float)
        assert row["line_total"] == 75.5

    def test_tax_total_is_float(self, monkeypatch):
        row = self._get_one(monkeypatch, tax_total=6.795)
        assert isinstance(row["tax_total"], float)

    def test_doc_date_sliced_to_10_chars(self, monkeypatch):
        row = self._get_one(monkeypatch)
        assert len(row["doc_date"]) == 10

    def test_vat_group_always_si(self, monkeypatch):
        row = self._get_one(monkeypatch)
        assert row["vat_group"] == "SI"


# ---------------------------------------------------------------------------
# T8 — _extract_si_lines unit tests
# ---------------------------------------------------------------------------

class TestExtractSILines:
    def test_extract_from_single_doc(self):
        docs = [_doc(10, lines=[_line("SI", item_desc="Consultation")])]
        result = _extract_si_lines(docs, "purchase_invoice")
        assert len(result) == 1
        assert result[0]["line_description"] == "Consultation"
        assert result[0]["doc_type"] == "purchase_invoice"

    def test_extract_filters_non_si(self):
        docs = [_doc(10, lines=[_line("SI"), _line("ZP"), _line("BL")])]
        result = _extract_si_lines(docs, "purchase_invoice")
        assert len(result) == 1

    def test_extract_empty_doc_list(self):
        assert _extract_si_lines([], "purchase_invoice") == []

    def test_extract_doc_with_no_lines(self):
        docs = [_doc(10, lines=[])]
        assert _extract_si_lines(docs, "purchase_invoice") == []
