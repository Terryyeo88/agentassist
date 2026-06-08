"""
tests/test_documents_ingest.py — T2.8 documents.ingest package tests.

Verifies:
  I1 — born-digital path: every field extracted from the 8 Prompt 1 fixture PDFs
       matches the manifest pdf_values (exact for numerics, normalised for dates).
  I2 — multimodal routing: _extract_multimodal() is called only when no text
       layer exists; the born-digital path never invokes it and never imports
       the anthropic SDK.
  I3 — import invariants:
         • orchestrator/ has no import of documents/ or anthropic.
         • documents/ has no import of orchestrator/, audit_bundle/, or
           boxes/gates/calculate paths.
         • documents/ingest.py has no module-level anthropic import.

pdfplumber is required.  If not installed, all tests fail with ImportError.
No live API calls are made — multimodal path is tested with mocks only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from documents.ingest import ExtractedInvoice, ingest

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

DOCS_DIR = Path(__file__).parent / "fixtures" / "documents"
MANIFEST_PATH = DOCS_DIR / "fixtures_manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
CASES = MANIFEST["cases"]

_CASE_IDS = [f"{c['doc_num']}-{c['injected_issue']}" for c in CASES]

_REPO_ROOT = Path(__file__).parent.parent
_ORCHESTRATOR_DIR = _REPO_ROOT / "orchestrator"
_DOCUMENTS_DIR = _REPO_ROOT / "documents"


def _read_sources(directory: Path) -> str:
    return "\n".join(
        f.read_text(encoding="utf-8")
        for f in sorted(directory.rglob("*.py"))
    )


# ---------------------------------------------------------------------------
# I1 — Born-digital extraction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES, ids=_CASE_IDS)
class TestBornDigitalExtraction:
    """For each fixture PDF ingest() produces an ExtractedInvoice that matches
    the manifest's pdf_values and line_item_record entries exactly."""

    def test_source_is_born_digital(self, case: dict) -> None:
        result = ingest(DOCS_DIR / case["pdf_filename"])
        assert result.source == "born_digital"

    def test_validation_status_unvalidated(self, case: dict) -> None:
        result = ingest(DOCS_DIR / case["pdf_filename"])
        assert result.validation_status == "unvalidated"

    def test_supplier_name(self, case: dict) -> None:
        """Supplier name matches the SAP card_name (vendor on the AP invoice)."""
        result = ingest(DOCS_DIR / case["pdf_filename"])
        assert result.supplier_name == case["line_item_record"]["card_name"]

    def test_supplier_gst_regno(self, case: dict) -> None:
        """GST reg matches pdf_values.supplier_gst_reg (None when absent)."""
        result = ingest(DOCS_DIR / case["pdf_filename"])
        expected = case["pdf_values"]["supplier_gst_reg"]
        assert result.supplier_gst_regno == expected

    def test_invoice_number(self, case: dict) -> None:
        result = ingest(DOCS_DIR / case["pdf_filename"])
        assert result.invoice_number == case["pdf_values"]["invoice_num"]

    def test_invoice_date(self, case: dict) -> None:
        """Date is normalised YYYY-MM-DD and matches the PDF face value."""
        result = ingest(DOCS_DIR / case["pdf_filename"])
        assert result.invoice_date == case["pdf_values"]["date"]

    def test_total_excl_gst(self, case: dict) -> None:
        result = ingest(DOCS_DIR / case["pdf_filename"])
        assert result.total_excl_gst == pytest.approx(case["pdf_values"]["excl_gst"])

    def test_gst_rate(self, case: dict) -> None:
        """GST rate label matches exactly (e.g. '7%', '6%' for injected cases)."""
        result = ingest(DOCS_DIR / case["pdf_filename"])
        assert result.gst_rate == case["pdf_values"]["gst_rate_label"]

    def test_gst_amount(self, case: dict) -> None:
        """GST amount is the PDF face value (differs from SAP record for mismatch cases)."""
        result = ingest(DOCS_DIR / case["pdf_filename"])
        assert result.gst_amount == pytest.approx(case["pdf_values"]["gst_amount"])

    def test_total_incl_gst(self, case: dict) -> None:
        """Total incl. GST is the PDF face value (may not equal excl+gst for inconsistency case)."""
        result = ingest(DOCS_DIR / case["pdf_filename"])
        assert result.total_incl_gst == pytest.approx(case["pdf_values"]["total"])

    def test_fields_present_tracks_gst_reg(self, case: dict) -> None:
        """fields_present['supplier_gst_regno'] is False when reg absent from PDF."""
        result = ingest(DOCS_DIR / case["pdf_filename"])
        expected = case["pdf_values"]["supplier_gst_reg"] is not None
        assert result.fields_present["supplier_gst_regno"] == expected

    def test_fields_present_all_numeric_true(self, case: dict) -> None:
        """All numeric fields are present for every fixture PDF."""
        result = ingest(DOCS_DIR / case["pdf_filename"])
        for key in ("total_excl_gst", "gst_rate", "gst_amount", "total_incl_gst"):
            assert result.fields_present[key] is True, (
                f"doc_num={case['doc_num']}: fields_present[{key!r}] is False"
            )


# ---------------------------------------------------------------------------
# I2 — Multimodal routing
# ---------------------------------------------------------------------------

class TestMultimodalRouting:
    def test_born_digital_fixture_never_calls_multimodal(self) -> None:
        """Born-digital fixture must not trigger _extract_multimodal."""
        pdf_path = DOCS_DIR / "INV-3001.pdf"
        with patch("documents.ingest._extract_multimodal") as mock_multi:
            result = ingest(pdf_path)
        mock_multi.assert_not_called()
        assert result.source == "born_digital"

    def test_no_text_layer_routes_to_multimodal(self) -> None:
        """When _has_text_layer returns False, _extract_multimodal is called."""
        pdf_path = DOCS_DIR / "INV-3001.pdf"
        mock_result = ExtractedInvoice(
            supplier_name="Mock Supplier Pte Ltd",
            supplier_gst_regno=None,
            invoice_number="INV-9999",
            invoice_date="2024-01-01",
            total_excl_gst=100.0,
            gst_rate="7%",
            gst_amount=7.0,
            total_incl_gst=107.0,
            source="multimodal",
            validation_status="unvalidated",
            fields_present={},
        )
        with patch("documents.ingest._has_text_layer", return_value=False), \
             patch("documents.ingest._extract_multimodal", return_value=mock_result) as mock_multi:
            result = ingest(pdf_path)
        mock_multi.assert_called_once_with(pdf_path)
        assert result.source == "multimodal"

    def test_born_digital_path_does_not_import_anthropic(self) -> None:
        """Running the born-digital path must not cause the anthropic SDK to be loaded."""
        saved = sys.modules.pop("anthropic", None)
        try:
            result = ingest(DOCS_DIR / "INV-3001.pdf")
            assert result.source == "born_digital"
            assert "anthropic" not in sys.modules, (
                "anthropic was imported by the born-digital path. "
                "It must only be imported inside _extract_multimodal()."
            )
        finally:
            if saved is not None:
                sys.modules["anthropic"] = saved

    def test_multimodal_result_has_correct_source(self) -> None:
        """ExtractedInvoice returned from multimodal path carries source='multimodal'."""
        mock_result = ExtractedInvoice(
            supplier_name=None,
            supplier_gst_regno=None,
            invoice_number=None,
            invoice_date=None,
            total_excl_gst=None,
            gst_rate=None,
            gst_amount=None,
            total_incl_gst=None,
            source="multimodal",
            validation_status="unvalidated",
            fields_present={},
        )
        with patch("documents.ingest._has_text_layer", return_value=False), \
             patch("documents.ingest._extract_multimodal", return_value=mock_result):
            result = ingest(DOCS_DIR / "INV-3001.pdf")
        assert result.source == "multimodal"
        assert result.validation_status == "unvalidated"


# ---------------------------------------------------------------------------
# I3 — Import invariants
# ---------------------------------------------------------------------------

class TestImportInvariants:
    def test_orchestrator_does_not_import_documents(self) -> None:
        """orchestrator/ must not import the documents package."""
        src = _read_sources(_ORCHESTRATOR_DIR)
        assert "import documents" not in src, (
            "orchestrator/ imports documents — invariant violated."
        )
        assert "from documents" not in src, (
            "orchestrator/ imports from documents — invariant violated."
        )

    def test_orchestrator_does_not_import_anthropic(self) -> None:
        """orchestrator/ must not import anthropic (T2.7 layer-separation invariant)."""
        src = _read_sources(_ORCHESTRATOR_DIR)
        assert "import anthropic" not in src, (
            "orchestrator/ has module-level anthropic import — invariant violated."
        )
        assert "from anthropic" not in src, (
            "orchestrator/ imports from anthropic — invariant violated."
        )

    def test_documents_does_not_import_orchestrator_or_audit_bundle(self) -> None:
        """documents/ must not import orchestrator/ or audit_bundle/."""
        src = _read_sources(_DOCUMENTS_DIR)
        for forbidden in ("orchestrator", "audit_bundle"):
            # Check for actual import statements, not docstring mentions.
            matches = re.findall(
                rf'^(?:import {forbidden}|from {forbidden})',
                src,
                re.MULTILINE,
            )
            assert not matches, (
                f"documents/ contains import of {forbidden!r} — invariant violated: {matches}"
            )

    def test_documents_does_not_import_boxes_gates_calculate(self) -> None:
        """documents/ must not import boxes, gates, or calculate helpers."""
        src = _read_sources(_DOCUMENTS_DIR)
        for forbidden in ("from boxes", "import boxes", "from gates", "import gates",
                          "from calculate", "import calculate"):
            assert forbidden not in src, (
                f"documents/ contains forbidden reference {forbidden!r}."
            )

    def test_documents_ingest_anthropic_import_is_deferred(self) -> None:
        """documents/ingest.py must have no module-level anthropic import."""
        src = (_DOCUMENTS_DIR / "ingest.py").read_text(encoding="utf-8")
        module_level = re.findall(r'^(?:import anthropic|from anthropic)', src, re.MULTILINE)
        assert not module_level, (
            f"documents/ingest.py has module-level anthropic import(s): {module_level}. "
            "The import must be deferred inside _extract_multimodal()."
        )
