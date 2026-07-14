"""Failing-first tests for the Xero→reasoning sales-line adapter (Prompt E Phase 2).

Four targets (three-times rule: prompt + code + test):

  (i)   ADAPTER CONTRACT — feeders/xero_sales_lines.py projects the reader's chain-shaped
        sales documents into reasoning 9-key line dicts: line_description passthrough,
        doc_type/"line_index" synthesized, vat_group taken AS-IS from the reader (already
        canonical via the client YAML — the adapter must NOT re-normalize), doc_num the
        reader's InvoiceNumber STRING preserved verbatim.
  (ii)  A-RELAX doc_num — reasoning_pass.validate_candidate becomes type-preserving:
        numeric → int (SAP path unchanged, int stays int), non-numeric → str ("INV-2001"
        survives verbatim through the pass AND the sealed artefact in the same run).
        The SAP fingerprint (measurement.py) is untouched.
  (iii) EXEMPT CANDIDATE ON XERO — a crafted tmp fixture (committed export untouched)
        with an ES33-mapped line + commercial-property description surfaces a candidate
        through the REAL reader → adapter → run_exempt_pass (hermetic fake LLM).
  (iv)  BOX-ISOLATION — runtime proof on the upload path: review() over the real Xero
        reader with vs without sales_line_source produces byte-identical deterministic
        core (calculate/classify/detect/gates).

HONEST RUNG: real-FORMAT over synthetic Xero, NOT real-client-validated; exempt skill now
runs on Xero over synthetic data only.

No anthropic (llm_call always injected; committed fixture has no exempt-coded line so the
upload-path exempt pass never reaches an LLM). No live SAP.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from feeders.xero_sales_lines import xero_sales_lines
from feeders.xero_sales_reader import XeroSalesInvoiceChainReader

from config.loader import load_client_config
from reasoning.exempt import EXEMPT_SPEC, run_exempt_pass, _build_user_message
from reasoning.reasoning_pass import validate_candidate
from tests.synth_xero_sales_export import _row, write_csv

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
FIXTURE_XLSX = _FIXTURE_DIR / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"

PERIOD_START = "2026-04-01"
PERIOD_END = "2026-06-30"
PERIOD = {"start": PERIOD_START, "end": PERIOD_END}


def _cfg():
    return load_client_config("xero_sales_demo", check_connectivity=False)


def _reader(source=FIXTURE_XLSX):
    cfg = _cfg()
    return XeroSalesInvoiceChainReader(
        source,
        tax_code_mappings=cfg.effective_tax_code_mappings,
        out_of_scope_codes=cfg.out_of_scope_codes,
    )


def _raw_candidate(doc_num, vg="ES33", cat="commercial_property") -> dict:
    return {
        "doc_num": doc_num, "doc_type": "sales_invoice", "doc_date": "2026-04-05",
        "card_name": "CUST", "line_index": 0, "vat_group": vg,
        "line_description": "OFFICE UNIT LEASE Q3", "line_total": 1000.0,
        "tax_total": 0.0, "suspected_category": cat, "reasoning": "desc-vs-code",
        "phrasing": "Consider reviewing whether this is commercial property",
        "confidence": "high",
    }


# ---------------------------------------------------------------------------
# (i) ADAPTER CONTRACT over the committed fixture
# ---------------------------------------------------------------------------

class TestAdapterContract:
    def _lines(self):
        return xero_sales_lines(_reader(), PERIOD_START, PERIOD_END)

    def test_nine_key_shape_and_types(self):
        lines = self._lines()
        assert lines, "adapter must yield lines from the committed fixture"
        expected = {"doc_num", "doc_type", "doc_date", "card_name", "line_index",
                    "vat_group", "line_description", "line_total", "tax_total"}
        for ln in lines:
            assert set(ln.keys()) == expected
            assert isinstance(ln["doc_num"], str)          # InvoiceNumber string
            assert isinstance(ln["line_index"], int)       # synthesized
            assert isinstance(ln["line_total"], float)
            assert isinstance(ln["tax_total"], float)
            assert len(ln["doc_date"]) == 10

    def test_doc_num_is_invoice_number_string_verbatim(self):
        nums = {ln["doc_num"] for ln in self._lines()}
        assert nums == {"INV-2001", "INV-2002", "INV-2003"}

    def test_doc_type_synthesized_sales_invoice(self):
        assert {ln["doc_type"] for ln in self._lines()} == {"sales_invoice"}

    def test_line_index_enumerates_within_document(self):
        inv1 = [ln for ln in self._lines() if ln["doc_num"] == "INV-2001"]
        assert [ln["line_index"] for ln in inv1] == [0, 1]

    def test_line_description_passthrough_verbatim(self):
        inv1 = [ln for ln in self._lines() if ln["doc_num"] == "INV-2001"]
        assert [ln["line_description"] for ln in inv1] == \
            ["Consulting services", "Support retainer"]

    def test_vat_group_taken_as_is_not_renormalized(self):
        # The reader already resolved TaxType -> canonical code via the client YAML;
        # the adapter must carry that value byte-for-byte (no second normalize).
        reader = _reader()
        docs = {d["DocNum"]: d for d in
                reader.fetch_invoices("Invoices", PERIOD_START, PERIOD_END)}
        lines = xero_sales_lines(reader, PERIOD_START, PERIOD_END)
        for ln in lines:
            src = docs[ln["doc_num"]]["DocumentLines"][ln["line_index"]]
            assert ln["vat_group"] == src["VatGroup"]


# ---------------------------------------------------------------------------
# (ii) A-RELAX doc_num — type-preserving; SAP int untouched; str seals verbatim
# ---------------------------------------------------------------------------

class TestARelaxDocNum:
    def test_non_numeric_str_preserved(self):
        out = validate_candidate(EXEMPT_SPEC, _raw_candidate("INV-2001"))
        assert out["doc_num"] == "INV-2001"
        assert isinstance(out["doc_num"], str)

    def test_int_stays_int(self):
        out = validate_candidate(EXEMPT_SPEC, _raw_candidate(9001))
        assert out["doc_num"] == 9001
        assert isinstance(out["doc_num"], int)

    def test_numeric_str_coerces_to_int(self):
        out = validate_candidate(EXEMPT_SPEC, _raw_candidate("123"))
        assert out["doc_num"] == 123
        assert isinstance(out["doc_num"], int)

    def test_reg2627_sap_path_unchanged_int(self):
        # The locked reg2627 test (test_reasoning_reg2627.py:547) pins int output;
        # mirror it here against the single-arg wrapper to prove a-relax kept it.
        from reasoning.reg2627 import _validate_candidate
        raw = _raw_candidate(3001, vg="SI", cat="medical_expenses")
        out = _validate_candidate(raw)
        assert isinstance(out["doc_num"], int)

    def test_str_and_int_through_pass_and_seal_same_run(self, tmp_path, monkeypatch):
        """SAP-style int and Xero-style str doc_nums in ONE artefact: the int stays
        int, "INV-2001" survives verbatim through the pass AND the sealed JSON."""
        lines = [
            {"doc_num": "INV-2001", "doc_type": "sales_invoice", "doc_date": "2026-04-05",
             "card_name": "A", "line_index": 0, "vat_group": "ES33",
             "line_description": "OFFICE UNIT LEASE Q3", "line_total": 1000.0,
             "tax_total": 0.0},
            {"doc_num": 9001, "doc_type": "sales_invoice", "doc_date": "2026-04-06",
             "card_name": "B", "line_index": 0, "vat_group": "ESN33",
             "line_description": "INSURANCE BROKERAGE COMMISSION", "line_total": 500.0,
             "tax_total": 0.0},
        ]

        def _fake(model, system, messages, max_tokens):
            arr = [
                _raw_candidate("INV-2001"),
                {**_raw_candidate(9001, vg="ESN33", cat="intermediary_fee"),
                 "line_description": "INSURANCE BROKERAGE COMMISSION"},
            ]
            return {"content": json.dumps(arr), "input_tokens": 1, "output_tokens": 1}

        art = run_exempt_pass(PERIOD, line_source=lambda: lines, llm_call=_fake)
        assert art["status"] == "ok"
        by_type = {type(c["doc_num"]): c["doc_num"] for c in art["candidates"]}
        assert by_type[str] == "INV-2001"
        assert by_type[int] == 9001

        # Seal it and read the bundle key back: "INV-2001" verbatim in the JSON.
        import audit_bundle.seal as _seal_mod
        from audit_bundle.seal import seal_bundle
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        compile_output = json.loads(
            (Path(__file__).parent / "fixtures" / "chain-run-sample.json")
            .read_text(encoding="utf-8"))
        pdf = tmp_path / "d.pdf"
        pdf.write_bytes(b"%PDF dummy")
        bundle = seal_bundle(
            client_config=_cfg(), period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=compile_output,
            gate_results={"all_passed": True, "gates": []},
            report_pdf_path=pdf,
            run_started_at="2026-07-14T00:00:00+00:00",
            run_completed_at="2026-07-14T00:00:10+00:00",
            extra_reasoning_artefacts={"exempt-supply": art},
        )
        sealed = json.loads(
            (bundle / "steps" / "exempt-supply-candidates.json").read_bytes())
        nums = [c["doc_num"] for c in sealed["candidates"]]
        assert "INV-2001" in nums and 9001 in nums

    def test_measurement_fingerprint_untouched(self):
        # Constraint (a): do not weaken the SAP fingerprint.
        src = (Path(__file__).parent.parent / "reasoning" / "measurement.py") \
            .read_text(encoding="utf-8")
        assert 'int(line["doc_num"])' in src


# ---------------------------------------------------------------------------
# (iii) EXEMPT CANDIDATE on a crafted ES33 Xero line (tmp fixture; committed untouched)
# ---------------------------------------------------------------------------

class TestExemptCandidateOnXero:
    def test_crafted_es33_line_surfaces_candidate(self, tmp_path):
        rows = [_row("Demo Tenant Pte Ltd", "INV-9001", "2026-04-15",
                     "Regulation 33 Exempt Supplies", "12000", "0", "12000",
                     description="OFFICE UNIT LEASE Q3")]
        src = write_csv(tmp_path / "es33.csv", rows)
        reader = _reader(src)
        adapter_lines = xero_sales_lines(reader, PERIOD_START, PERIOD_END)
        assert [ln["vat_group"] for ln in adapter_lines] == ["ES33"]

        def _fake(model, system, messages, max_tokens):
            # Echo the (single) forwarded line back as a candidate.
            sent = json.loads(messages[0]["content"].split("Lines:\n", 1)[1]
                              .split("\n\nReturn a JSON array", 1)[0])
            c = {**sent[0], "suspected_category": "commercial_property",
                 "reasoning": "office lease coded exempt",
                 "phrasing": "Consider reviewing whether this office lease is commercial property",
                 "confidence": "high"}
            return {"content": json.dumps([c]), "input_tokens": 1, "output_tokens": 1}

        art = run_exempt_pass(
            PERIOD, line_source=lambda: adapter_lines, llm_call=_fake)
        assert art["status"] == "ok"
        assert art["input_summary"]["exempt_sales_lines_examined"] == 1
        assert art["candidate_count"] == 1
        cand = art["candidates"][0]
        assert cand["doc_num"] == "INV-9001"          # str, verbatim
        assert cand["vat_group"] == "ES33"
        assert cand["line_description"] == "OFFICE UNIT LEASE Q3"
        assert cand["phrasing"].startswith("Consider reviewing whether")

    def test_committed_fixture_untouched_and_exempt_free(self):
        # The committed export stays byte-identical (no crafted line added to it),
        # and it carries no exempt-coded line — the tmp-fixture route is required.
        lines = xero_sales_lines(_reader(), PERIOD_START, PERIOD_END)
        assert not [ln for ln in lines if ln["vat_group"] in ("ES33", "ESN33")]


# ---------------------------------------------------------------------------
# (iv) BOX-ISOLATION — runtime with/without sales_line_source on the upload path
# ---------------------------------------------------------------------------

class TestBoxIsolationRuntime:
    def _review(self, tmp_path, with_adapter: bool):
        import audit_bundle.seal as _seal_mod
        from engine.review import ReviewInputs, review
        reader = _reader()
        kwargs = {}
        if with_adapter:
            kwargs["sales_line_source"] = (
                lambda: xero_sales_lines(reader, PERIOD_START, PERIOD_END))
        inputs = ReviewInputs(line_source=lambda: [], provider=None, reader=reader,
                              **kwargs)
        with patch.object(_seal_mod, "_AUDIT_ROOT", tmp_path / f"audit-{with_adapter}"), \
             patch("engine.review._REPORTS_DIR", tmp_path / f"reports-{with_adapter}"):
            return review(_cfg(), PERIOD, inputs)

    def test_deterministic_core_byte_identical(self, tmp_path):
        r_without = self._review(tmp_path, with_adapter=False)
        r_with = self._review(tmp_path, with_adapter=True)
        assert r_without.status == r_with.status == "completed"
        for key in ("calculate", "classify", "detect"):
            assert json.dumps(r_without.compile_output[key], sort_keys=True) == \
                   json.dumps(r_with.compile_output[key], sort_keys=True), key
        assert json.dumps(r_without.gate_results, sort_keys=True) == \
               json.dumps(r_with.gate_results, sort_keys=True)

    def test_exempt_pass_ran_clean_without_llm(self, tmp_path):
        # Committed fixture has no ES33/ESN33 line -> the pass returns a clean ok
        # artefact WITHOUT any LLM call (deterministic, no token spend, no key).
        r = self._review(tmp_path, with_adapter=True)
        assert r.exempt_artefact is not None
        assert r.exempt_artefact["status"] == "ok"
        assert r.exempt_artefact["candidate_count"] == 0


# ---------------------------------------------------------------------------
# Wiring + three-times prompt text
# ---------------------------------------------------------------------------

class TestWiringAndPrompt:
    def test_api_sales_branch_passes_sales_line_source(self):
        src = (Path(__file__).parent.parent / "api" / "app.py").read_text(encoding="utf-8")
        sales_fn = src.split("def _xero_sales_review_response", 1)[1]
        assert "sales_line_source=" in sales_fn.split("def ", 1)[0]

    def test_exempt_prompt_documents_int_or_str(self):
        msg = _build_user_message(PERIOD, [])
        assert "doc_num (int)" not in msg
        assert "doc_num (int or str" in msg
