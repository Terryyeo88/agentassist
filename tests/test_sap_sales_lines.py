"""
T2.28 — tests for reasoning/sap_lines.py :: fetch_sales_lines.

fetch_sales_lines is the SALES analog of fetch_si_purchase_lines: it fetches
"Invoices" + "CreditNotes" via the SAME plain paginated helper (NO credit-note
sign-flip) and emits the same 9-key shape.  Two differences from the purchase
fetcher, both asserted here:
  1. It does NOT hardcode / filter vat_group — every sales line is emitted,
     carrying its OWN VatGroup (so a downstream reasoning SkillSpec can select
     ES33/ESN33 etc.).
  2. vat_group is the CANONICAL code produced by the normalize seam
     (normalize_vat_group / effective_tax_code_mappings), not the raw string.

All tests are hermetic: _do_fetch_paginated and the normalize seam are
monkeypatched; no live SAP, no sap_b1_server import.
"""
from __future__ import annotations

from pathlib import Path

import reasoning.sap_lines as _sap_lines_mod
from reasoning.sap_lines import (
    _extract_sales_lines,
    fetch_sales_lines,
)

_START = "2024-07-01"
_END = "2024-09-30"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(doc_num: int, card_name: str = "Customer Co",
         doc_date: str = "2024-07-15", lines: list[dict] | None = None) -> dict:
    return {
        "DocNum": doc_num,
        "CardName": card_name,
        "DocDate": doc_date + "T00:00:00Z",
        "DocumentLines": lines or [],
    }


def _line(vat_group: str = "SO", item_desc: str = "Consulting services",
          item_code: str = "SVC001", line_total: float = 100.0,
          tax_total: float = 9.0, extra: dict | None = None) -> dict:
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


def _fake_fetch(entity_map: dict[str, list[dict]], *, record: list | None = None):
    """Return a _do_fetch_paginated replacement returning canned docs per entity.

    When `record` is given, each requested entity name is appended to it so a
    test can assert which entities were fetched (and via which helper path).
    """
    def _fetch(entity: str, period_start: str, period_end: str) -> list[dict]:
        if record is not None:
            record.append(entity)
        return entity_map.get(entity, [])
    return _fetch


def _identity_norm(raw):
    """Identity normalize — SAP B1 behaviour (empty mappings)."""
    return str(raw or "").strip()


def _patch(monkeypatch, entity_map, *, record=None, norm=_identity_norm):
    monkeypatch.setattr(_sap_lines_mod, "_do_fetch_paginated",
                        _fake_fetch(entity_map, record=record))
    monkeypatch.setattr(_sap_lines_mod, "_normalize_vat_group", norm)


# ---------------------------------------------------------------------------
# T1 — sales entities fetched + doc_type tagging
# ---------------------------------------------------------------------------

class TestSalesEntities:
    def test_fetches_invoices_and_credit_notes(self, monkeypatch):
        record: list[str] = []
        _patch(monkeypatch, {"Invoices": [_doc(1, lines=[_line()])],
                             "CreditNotes": [_doc(2, lines=[_line()])]},
               record=record)
        fetch_sales_lines(_START, _END)
        assert record == ["Invoices", "CreditNotes"]

    def test_invoice_lines_tagged_sales_invoice(self, monkeypatch):
        _patch(monkeypatch, {"Invoices": [_doc(1, lines=[_line()])], "CreditNotes": []})
        result = fetch_sales_lines(_START, _END)
        assert result[0]["doc_type"] == "sales_invoice"

    def test_credit_note_lines_tagged_sales_credit_note(self, monkeypatch):
        _patch(monkeypatch, {"Invoices": [], "CreditNotes": [_doc(2, lines=[_line()])]})
        result = fetch_sales_lines(_START, _END)
        assert result[0]["doc_type"] == "sales_credit_note"

    def test_both_types_returned_together(self, monkeypatch):
        _patch(monkeypatch, {"Invoices": [_doc(1, lines=[_line(item_desc="Inv")])],
                             "CreditNotes": [_doc(2, lines=[_line(item_desc="CN")])]})
        result = fetch_sales_lines(_START, _END)
        assert {r["doc_type"] for r in result} == {"sales_invoice", "sales_credit_note"}


# ---------------------------------------------------------------------------
# T2 — NO vat_group filter: every line emitted, carrying its own code
# ---------------------------------------------------------------------------

class TestNoVatGroupFilter:
    def test_es33_and_so_both_emitted(self, monkeypatch):
        # The acceptance line: an ES33 (exempt) and an SO (standard) line must
        # BOTH survive — the fetcher filters nothing; the skill does.
        docs = [_doc(1, lines=[_line("ES33", item_desc="Financial service"),
                               _line("SO", item_desc="Widget sale")])]
        _patch(monkeypatch, {"Invoices": docs, "CreditNotes": []})
        result = fetch_sales_lines(_START, _END)
        assert len(result) == 2
        assert {r["vat_group"] for r in result} == {"ES33", "SO"}

    def test_empty_vat_group_line_is_still_emitted(self, monkeypatch):
        # Unlike the purchase fetcher (which drops non-SI), the sales fetcher
        # emits every line — an empty VatGroup becomes vat_group "".
        docs = [_doc(1, lines=[_line("")])]
        _patch(monkeypatch, {"Invoices": docs, "CreditNotes": []})
        result = fetch_sales_lines(_START, _END)
        assert len(result) == 1
        assert result[0]["vat_group"] == ""

    def test_all_of_mixed_codes_emitted(self, monkeypatch):
        docs = [_doc(1, lines=[_line("SO"), _line("ZR"), _line("OS"), _line("ES33")])]
        _patch(monkeypatch, {"Invoices": docs, "CreditNotes": []})
        result = fetch_sales_lines(_START, _END)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# T3 — vat_group is the NORMALIZED canonical code (routed through the seam)
# ---------------------------------------------------------------------------

class TestVatGroupNormalized:
    def test_vat_group_routed_through_normalize_seam(self, monkeypatch):
        # A non-identity normalize proves the fetcher emits the normalized code,
        # not the raw string — i.e. it is not hardcoded and not raw-passthrough.
        def _norm(raw):
            return {"XSVC": "ES33"}.get(str(raw or "").strip(), str(raw or "").strip())
        docs = [_doc(1, lines=[_line("XSVC")])]
        _patch(monkeypatch, {"Invoices": docs, "CreditNotes": []}, norm=_norm)
        result = fetch_sales_lines(_START, _END)
        assert result[0]["vat_group"] == "ES33"

    def test_identity_normalize_preserves_canonical_sap_codes(self, monkeypatch):
        # SAP B1 clients have empty mappings → normalize is identity, so already-
        # canonical codes (ES33/ESN33/SO) pass through unchanged.
        docs = [_doc(1, lines=[_line("ES33"), _line("ESN33")])]
        _patch(monkeypatch, {"Invoices": docs, "CreditNotes": []})
        result = fetch_sales_lines(_START, _END)
        assert {r["vat_group"] for r in result} == {"ES33", "ESN33"}


# ---------------------------------------------------------------------------
# T4 — plain credit-note helper: NO sign-flip
# ---------------------------------------------------------------------------

class TestNoCreditNoteSignFlip:
    def test_credit_note_totals_pass_through_unchanged(self, monkeypatch):
        # The purchase fetcher uses the PLAIN paginated helper for credit notes
        # (no netting). The sales fetcher must too: a CN line_total of 100.0 is
        # emitted as +100.0, never -100.0.
        cn_docs = [_doc(2, lines=[_line("SO", line_total=100.0, tax_total=9.0)])]
        _patch(monkeypatch, {"Invoices": [], "CreditNotes": cn_docs})
        result = fetch_sales_lines(_START, _END)
        assert result[0]["line_total"] == 100.0
        assert result[0]["tax_total"] == 9.0

    def test_credit_notes_fetched_via_do_fetch_paginated_entity(self, monkeypatch):
        # Proves the plain _do_fetch_paginated("CreditNotes") path is used — NOT
        # the sign-flipping _fetch_credit_notes_paginated helper.
        record: list[str] = []
        _patch(monkeypatch, {"Invoices": [], "CreditNotes": [_doc(2, lines=[_line()])]},
               record=record)
        fetch_sales_lines(_START, _END)
        assert "CreditNotes" in record


# ---------------------------------------------------------------------------
# T5 — 9-key output shape + types (parallel to the purchase fetcher)
# ---------------------------------------------------------------------------

class TestOutputShape:
    def _one(self, monkeypatch, **line_kw) -> dict:
        docs = [_doc(1, lines=[_line(**line_kw)])]
        _patch(monkeypatch, {"Invoices": docs, "CreditNotes": []})
        return fetch_sales_lines(_START, _END)[0]

    def test_all_nine_keys_present(self, monkeypatch):
        row = self._one(monkeypatch)
        required = {"doc_num", "doc_type", "doc_date", "card_name", "line_index",
                    "vat_group", "line_description", "line_total", "tax_total"}
        assert set(row.keys()) == required

    def test_doc_num_is_int(self, monkeypatch):
        assert isinstance(self._one(monkeypatch)["doc_num"], int)

    def test_totals_are_float(self, monkeypatch):
        row = self._one(monkeypatch, line_total=75.5, tax_total=6.795)
        assert isinstance(row["line_total"], float)
        assert isinstance(row["tax_total"], float)
        assert row["line_total"] == 75.5

    def test_doc_date_sliced_to_10(self, monkeypatch):
        assert len(self._one(monkeypatch)["doc_date"]) == 10

    def test_line_description_from_item_description(self, monkeypatch):
        row = self._one(monkeypatch, item_desc="Advisory fee")
        assert row["line_description"] == "Advisory fee"

    def test_line_index_sequential_no_filter_gaps(self, monkeypatch):
        # No filtering → line_index runs 0,1,2 contiguously even across codes.
        docs = [_doc(1, lines=[_line("SO"), _line(""), _line("ES33")])]
        _patch(monkeypatch, {"Invoices": docs, "CreditNotes": []})
        result = fetch_sales_lines(_START, _END)
        assert [r["line_index"] for r in result] == [0, 1, 2]


# ---------------------------------------------------------------------------
# T6 — _extract_sales_lines unit (direct, with injected normalize)
# ---------------------------------------------------------------------------

class TestExtractSalesLinesUnit:
    def test_direct_extract_with_injected_normalize(self):
        docs = [_doc(10, lines=[_line("ES33", item_desc="Interest income")])]
        result = _extract_sales_lines(docs, "sales_invoice", normalize=_identity_norm)
        assert len(result) == 1
        assert result[0]["vat_group"] == "ES33"
        assert result[0]["doc_type"] == "sales_invoice"
        assert result[0]["line_description"] == "Interest income"

    def test_direct_extract_empty(self):
        assert _extract_sales_lines([], "sales_invoice", normalize=_identity_norm) == []


# ---------------------------------------------------------------------------
# T7 — Import + box isolation
# ---------------------------------------------------------------------------

class TestIsolation:
    def _src(self) -> str:
        import reasoning.sap_lines as mod
        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_sap_lines_has_no_anthropic_import(self):
        src = self._src()
        assert "import anthropic" not in src
        assert "from anthropic" not in src

    def test_sap_lines_has_no_orchestrator_or_audit_bundle_import(self):
        src = self._src()
        assert "import orchestrator" not in src
        assert "import audit_bundle" not in src

    def test_fetch_sales_lines_not_wired_into_chain_or_review(self):
        # fetch_sales_lines is a passive line_source, not yet consumed by any
        # pass — so run_chain / F5 boxes / gates are byte-identical. Assert it is
        # referenced by NO deterministic-path or review-composition module.
        repo = Path(_sap_lines_mod.__file__).resolve().parent.parent
        for rel in ("orchestrator/chain.py", "engine/review.py", "run_agent.py"):
            src = (repo / rel).read_text(encoding="utf-8")
            assert "fetch_sales_lines" not in src, (
                f"fetch_sales_lines unexpectedly wired into {rel}"
            )
