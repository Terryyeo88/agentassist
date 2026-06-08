"""
tests/test_document_fixtures.py — T2.8 document-ingestion fixture substrate tests.

Verifies:
  T1 — All 8 PDFs exist in tests/fixtures/documents/.
  T2 — Every PDF has a non-empty extractable text layer (via pdfplumber).
  T3 — Every PDF contains all IRAS para 7.1.4 keyword particulars.
  T4 — fixtures_manifest.json exists and has the required header disclaimer.
  T5 — Manifest lists all cases with doc_num, pdf_filename, injected_issue.
  T6 — Every case's line_item_record matches the sap_lines.py output shape.
  T7 — Generator is reproducible: re-running produces byte-identical PDFs.
  T8 — All five injected-issue types are represented across the case set.
  T9 — No network, no SAP, no anthropic import required (source inspection).

pdfplumber is required for T2/T3.  Install with: pip install pdfplumber
If not installed, T2/T3 are skipped with a clear message.

Nothing in this file modifies any existing file.  The generator is called
via its public generate() function with a temporary directory for T7.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DOCS_DIR      = Path(__file__).parent / "fixtures" / "documents"
MANIFEST_PATH = DOCS_DIR / "fixtures_manifest.json"
GENERATOR     = DOCS_DIR / "generate_invoices.py"

# Expected DocNums — changing these intentionally is a breaking change
EXPECTED_DOC_NUMS = [3001, 3002, 3003, 3004, 3005, 3006, 3007, 3008]

# IRAS para 7.1.4 keyword particulars that must appear in every PDF's text layer
REQUIRED_KEYWORDS = [
    "TAX INVOICE",    # para 7.1.4(a) — the words "tax invoice"
    "Subtotal",       # para 7.1.4(g) — amount excluding GST
    "GST",            # para 7.1.4(h)/(i) — rate and amount
    "TOTAL",          # para 7.1.4(j) — total including GST
]

# Fields required in every line_item_record (matches sap_lines.py output shape)
_LINE_ITEM_FIELDS = frozenset({
    "doc_num", "doc_type", "doc_date", "card_name", "line_index",
    "vat_group", "line_description", "line_total", "tax_total",
})

# All five issue types (plus "none") must be represented
EXPECTED_ISSUE_TYPES = {
    "none",
    "gst_amount_mismatch",
    "supplier_gst_reg_absent",
    "date_outside_period",
    "total_inconsistency",
    "combined",
}


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _load_generator():
    """Import generate_invoices.py as a module without adding it to sys.path."""
    spec = importlib.util.spec_from_file_location("generate_invoices", GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# T1 — PDFs exist
# ---------------------------------------------------------------------------

class TestPDFsExist:
    def test_generator_script_present(self):
        assert GENERATOR.exists(), f"Generator script not found: {GENERATOR}"

    def test_manifest_present(self):
        assert MANIFEST_PATH.exists(), f"Manifest not found: {MANIFEST_PATH}"

    @pytest.mark.parametrize("doc_num", EXPECTED_DOC_NUMS)
    def test_pdf_exists(self, doc_num: int):
        pdf_path = DOCS_DIR / f"INV-{doc_num}.pdf"
        assert pdf_path.exists(), f"PDF not found: {pdf_path}"
        assert pdf_path.stat().st_size > 0, f"PDF is empty: {pdf_path}"


# ---------------------------------------------------------------------------
# T2/T3 — Extractable text layer (pdfplumber required)
# ---------------------------------------------------------------------------

pdfplumber = pytest.importorskip(
    "pdfplumber",
    reason="pdfplumber not installed — run: pip install pdfplumber",
)


def _extract_text(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return " ".join(p.extract_text() or "" for p in pdf.pages)


class TestTextLayer:
    @pytest.mark.parametrize("doc_num", EXPECTED_DOC_NUMS)
    def test_non_empty_text_layer(self, doc_num: int):
        """T2 — every PDF must have a non-empty extractable text layer."""
        pdf_path = DOCS_DIR / f"INV-{doc_num}.pdf"
        text = _extract_text(pdf_path)
        assert len(text.strip()) > 50, (
            f"INV-{doc_num}.pdf: text layer is empty or too short "
            f"(got {len(text)} chars) — PDF may be image-only or corrupt."
        )

    @pytest.mark.parametrize("doc_num", EXPECTED_DOC_NUMS)
    def test_iras_particulars_present(self, doc_num: int):
        """T3 — every PDF must contain IRAS para 7.1.4 keyword particulars."""
        pdf_path = DOCS_DIR / f"INV-{doc_num}.pdf"
        text = _extract_text(pdf_path)
        missing = [kw for kw in REQUIRED_KEYWORDS if kw not in text]
        assert not missing, (
            f"INV-{doc_num}.pdf missing IRAS para 7.1.4 keywords: {missing}"
        )

    @pytest.mark.parametrize("doc_num", EXPECTED_DOC_NUMS)
    def test_invoice_number_in_text(self, doc_num: int):
        """Every PDF must contain its own invoice number."""
        pdf_path = DOCS_DIR / f"INV-{doc_num}.pdf"
        text = _extract_text(pdf_path)
        assert f"INV-{doc_num}" in text, (
            f"INV-{doc_num}.pdf does not contain its own invoice number."
        )


# ---------------------------------------------------------------------------
# T4/T5/T6 — Manifest structure
# ---------------------------------------------------------------------------

class TestManifest:
    def test_disclaimer_present(self):
        """T4 — manifest header must contain the T2.13 disclaimer."""
        m = _load_manifest()
        desc = m.get("_meta", {}).get("description", "")
        assert "NOT specialist-validated ground truth" in desc, (
            "Manifest _meta.description is missing the T2.13 disclaimer. "
            f"Got: {desc!r}"
        )

    def test_join_key_declared(self):
        m = _load_manifest()
        assert m["_meta"]["join_key"] == "doc_num"

    def test_case_count(self):
        """T5 — manifest must have exactly 8 cases."""
        m = _load_manifest()
        assert len(m["cases"]) == len(EXPECTED_DOC_NUMS), (
            f"Expected {len(EXPECTED_DOC_NUMS)} cases, got {len(m['cases'])}."
        )

    def test_all_doc_nums_present(self):
        """T5 — all expected DocNums must appear in the manifest."""
        m = _load_manifest()
        manifest_nums = [c["doc_num"] for c in m["cases"]]
        assert set(manifest_nums) == set(EXPECTED_DOC_NUMS), (
            f"DocNum mismatch. Expected {EXPECTED_DOC_NUMS}, got {manifest_nums}."
        )

    def test_each_case_has_required_fields(self):
        """T5 — each case must have doc_num, pdf_filename, and injected_issue."""
        m = _load_manifest()
        for case in m["cases"]:
            for field in ("doc_num", "pdf_filename", "injected_issue",
                          "injected_issue_detail", "line_item_record"):
                assert field in case, (
                    f"Case doc_num={case.get('doc_num')} missing field: {field}"
                )

    def test_pdf_filenames_match_doc_nums(self):
        """T5 — pdf_filename must be INV-<doc_num>.pdf."""
        m = _load_manifest()
        for case in m["cases"]:
            expected = f"INV-{case['doc_num']}.pdf"
            assert case["pdf_filename"] == expected, (
                f"DocNum {case['doc_num']}: expected filename {expected!r}, "
                f"got {case['pdf_filename']!r}."
            )

    def test_line_item_record_shape(self):
        """T6 — every line_item_record must match the sap_lines.py output shape."""
        m = _load_manifest()
        for case in m["cases"]:
            rec = case["line_item_record"]
            missing = _LINE_ITEM_FIELDS - set(rec.keys())
            assert not missing, (
                f"DocNum {case['doc_num']}: line_item_record missing fields: "
                f"{sorted(missing)}"
            )

    def test_line_item_vat_group_is_si(self):
        """T6 — all line_item_records must have vat_group='SI' (sap_lines.py contract)."""
        m = _load_manifest()
        for case in m["cases"]:
            rec = case["line_item_record"]
            assert rec["vat_group"] == "SI", (
                f"DocNum {case['doc_num']}: vat_group must be 'SI', "
                f"got {rec['vat_group']!r}."
            )

    def test_line_item_doc_type_is_purchase_invoice(self):
        """T6 — all records are purchase invoices."""
        m = _load_manifest()
        for case in m["cases"]:
            rec = case["line_item_record"]
            assert rec["doc_type"] == "purchase_invoice", (
                f"DocNum {case['doc_num']}: unexpected doc_type {rec['doc_type']!r}."
            )

    def test_line_item_numeric_fields_are_floats(self):
        """T6 — line_total and tax_total must be floats (sap_lines.py casts them)."""
        m = _load_manifest()
        for case in m["cases"]:
            rec = case["line_item_record"]
            assert isinstance(rec["line_total"], float), (
                f"DocNum {case['doc_num']}: line_total must be float."
            )
            assert isinstance(rec["tax_total"], float), (
                f"DocNum {case['doc_num']}: tax_total must be float."
            )


# ---------------------------------------------------------------------------
# T7 — Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_generator_produces_byte_identical_pdfs(self):
        """T7 — re-running generate() into a fresh tempdir produces
        SHA-256-identical PDFs to the committed fixtures."""
        gen = _load_generator()

        # Hash the committed PDFs
        originals: dict[str, str] = {}
        for doc_num in EXPECTED_DOC_NUMS:
            pdf_path = DOCS_DIR / f"INV-{doc_num}.pdf"
            originals[f"INV-{doc_num}.pdf"] = hashlib.sha256(
                pdf_path.read_bytes()
            ).hexdigest()

        # Re-generate into a temp directory
        with tempfile.TemporaryDirectory() as tmp:
            gen.generate(Path(tmp))
            for filename, orig_hash in originals.items():
                regen_bytes = (Path(tmp) / filename).read_bytes()
                regen_hash = hashlib.sha256(regen_bytes).hexdigest()
                assert orig_hash == regen_hash, (
                    f"{filename}: re-generated PDF differs from committed fixture. "
                    f"committed={orig_hash[:12]}… regen={regen_hash[:12]}…"
                )


# ---------------------------------------------------------------------------
# T8 — Issue coverage
# ---------------------------------------------------------------------------

class TestIssueCoverage:
    def test_all_injected_issue_types_present(self):
        """T8 — the case set must cover all five injected-issue types (+ none)."""
        m = _load_manifest()
        observed = {c["injected_issue"] for c in m["cases"]}
        missing = EXPECTED_ISSUE_TYPES - observed
        assert not missing, (
            f"Missing injected_issue types in fixture set: {sorted(missing)}"
        )

    def test_at_least_two_clean_cases(self):
        """T8 — at least 2 clean cases so negatives are not a single point."""
        m = _load_manifest()
        clean = [c for c in m["cases"] if c["injected_issue"] == "none"]
        assert len(clean) >= 2, (
            f"Need at least 2 clean cases; found {len(clean)}."
        )

    def test_date_outside_period_case_has_october_date(self):
        """T8 — the date_outside_period case must have a date after 2024-09-30."""
        m = _load_manifest()
        oob = [c for c in m["cases"] if c["injected_issue"] == "date_outside_period"]
        assert oob, "No date_outside_period case found."
        for case in oob:
            rec_date = case["line_item_record"]["doc_date"]
            assert rec_date > "2024-09-30", (
                f"date_outside_period case doc_date {rec_date!r} is not "
                "after the Q3 2024 period end 2024-09-30."
            )


# ---------------------------------------------------------------------------
# T9 — Source inspection: no forbidden imports in generator
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    def test_generator_has_no_anthropic_import(self):
        """T9 — the generator must not import anthropic."""
        src = GENERATOR.read_text(encoding="utf-8")
        assert "import anthropic" not in src, (
            "generate_invoices.py must not import anthropic."
        )
        assert "from anthropic" not in src, (
            "generate_invoices.py must not import from anthropic."
        )

    def test_generator_has_no_sap_import(self):
        """T9 — the generator must not import any SAP client module."""
        src = GENERATOR.read_text(encoding="utf-8")
        for forbidden in ("sap_b1_server", "sap_b1_client", "SAPClient",
                          "SAPB1Client", "mcp_servers"):
            assert forbidden not in src, (
                f"generate_invoices.py must not reference {forbidden!r}."
            )

    def test_generator_has_no_network_calls(self):
        """T9 — the generator must not import requests, httpx, or urllib."""
        src = GENERATOR.read_text(encoding="utf-8")
        for forbidden in ("import requests", "import httpx", "import urllib"):
            assert forbidden not in src, (
                f"generate_invoices.py must not contain {forbidden!r}."
            )
