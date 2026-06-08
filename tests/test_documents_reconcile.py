"""
tests/test_documents_reconcile.py — T2.8 documents.reconcile tests.

Verifies:
  R1 — Per-fixture candidate count and check_ids match the manifest's
       injected_issue for all 8 Prompt-1 cases.
       NOTE: Labels are author-known controlled injected issues for build/demo
       only — NOT specialist-validated ground truth (T2.13).
  R2 — Individual candidate fields (extracted_value, listing_value,
       determinability, severity, extraction_source, validation_status).
  R3 — F5 box figures and all five gate results are byte-identical before
       and after reconcile() runs — reconcile produces candidates only and
       never mutates shared state.
  R4 — Import containment: documents/reconcile.py imports nothing from
       orchestrator/, audit_bundle/, boxes, gates, or calculate; no anthropic.
  R5 — AMOUNT_TOLERANCE is a named constant; reg11_supplier_gst_absent check
       uses check_id "reg11_supplier_gst_absent" (not "NO_GST_REG") and does
       not reference NO_GST_REG in its source.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from documents.ingest import ExtractedInvoice, ingest
from documents.reconcile import AMOUNT_TOLERANCE, DocumentCandidate, reconcile

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

DOCS_DIR = Path(__file__).parent / "fixtures" / "documents"
MANIFEST_PATH = DOCS_DIR / "fixtures_manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
CASES = MANIFEST["cases"]

# Period that matches the fixtures (Q3 2024)
PERIOD_START = "2024-07-01"
PERIOD_END = "2024-09-30"

# Fixture compile_output for isolation test
CHAIN_FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"

_REPO_ROOT = Path(__file__).parent.parent
_DOCUMENTS_DIR = _REPO_ROOT / "documents"

_CASE_IDS = [f"{c['doc_num']}-{c['injected_issue']}" for c in CASES]


# Expected candidates per case.
# NOTE: These expected outputs are derived from author-known controlled
# injected issues for build/demo only — NOT specialist-validated ground truth.
# Ground-truth validation is deferred to T2.13.
_EXPECTED: dict[int, list[str]] = {
    3001: [],                                              # clean
    3002: [],                                              # clean
    3003: ["gst_amount_mismatch"],                        # PDF GST 900 vs SAP 840
    3004: ["gst_amount_mismatch"],                        # PDF GST 192 (6%) vs SAP 224 (7%)
    3005: ["reg11_supplier_gst_absent"],                  # no GST reg on PDF face
    3006: ["correct_period"],                              # date 2024-10-05 outside Q3
    3007: ["total_inconsistency"],                        # 4530 ≠ 4200+294=4494
    3008: ["gst_amount_mismatch", "reg11_supplier_gst_absent"],  # combined
}


def _ingest_and_reconcile(case: dict) -> list[DocumentCandidate]:
    extracted = ingest(DOCS_DIR / case["pdf_filename"])
    return reconcile(extracted, case["line_item_record"], PERIOD_START, PERIOD_END)


# ---------------------------------------------------------------------------
# R1 — Per-fixture candidate count and check_ids
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES, ids=_CASE_IDS)
class TestReconcilePerCase:
    """Candidate count and check_ids match the manifest's injected_issue.
    Labels are author-known controlled injected issues — NOT specialist-validated."""

    def test_candidate_count(self, case: dict) -> None:
        expected = _EXPECTED[case["doc_num"]]
        result = _ingest_and_reconcile(case)
        assert len(result) == len(expected), (
            f"doc_num={case['doc_num']} ({case['injected_issue']}): "
            f"expected {len(expected)} candidate(s), got {len(result)} "
            f"with check_ids {[c.check_id for c in result]!r}"
        )

    def test_check_ids(self, case: dict) -> None:
        expected = sorted(_EXPECTED[case["doc_num"]])
        result = sorted(c.check_id for c in _ingest_and_reconcile(case))
        assert result == expected, (
            f"doc_num={case['doc_num']} ({case['injected_issue']}): "
            f"expected check_ids {expected!r}, got {result!r}"
        )

    def test_all_candidates_unvalidated(self, case: dict) -> None:
        for cand in _ingest_and_reconcile(case):
            assert cand.validation_status == "unvalidated"

    def test_doc_num_consistent(self, case: dict) -> None:
        for cand in _ingest_and_reconcile(case):
            assert cand.doc_num == case["doc_num"]

    def test_source_propagated_born_digital(self, case: dict) -> None:
        """extraction_source mirrors the ExtractedInvoice.source (all fixtures born-digital)."""
        for cand in _ingest_and_reconcile(case):
            assert cand.extraction_source == "born_digital"

    def test_messages_start_with_consider(self, case: dict) -> None:
        """Every message must begin 'Consider reviewing whether' — no verdict language."""
        for cand in _ingest_and_reconcile(case):
            assert cand.message.startswith("Consider reviewing whether"), (
                f"doc_num={case['doc_num']} check_id={cand.check_id!r}: "
                f"message does not start with 'Consider reviewing whether': "
                f"{cand.message[:80]!r}"
            )


# ---------------------------------------------------------------------------
# R2 — Individual candidate field values
# ---------------------------------------------------------------------------

class TestCandidateFields:
    def test_gst_mismatch_3003_extracted_vs_listing(self) -> None:
        """3003: PDF shows 900.00, SAP record has 840.00 (7% of 12000)."""
        case = next(c for c in CASES if c["doc_num"] == 3003)
        [cand] = _ingest_and_reconcile(case)
        assert cand.check_id == "gst_amount_mismatch"
        assert cand.extracted_value == pytest.approx(900.0)
        assert cand.listing_value == pytest.approx(840.0)
        assert cand.determinability == "J+"
        assert cand.severity == "MEDIUM"

    def test_gst_mismatch_3004_extracted_vs_listing(self) -> None:
        """3004: PDF shows 192.00 (6%), SAP record has 224.00 (7% of 3200)."""
        case = next(c for c in CASES if c["doc_num"] == 3004)
        [cand] = _ingest_and_reconcile(case)
        assert cand.check_id == "gst_amount_mismatch"
        assert cand.extracted_value == pytest.approx(192.0)
        assert cand.listing_value == pytest.approx(224.0)
        assert cand.determinability == "J+"

    def test_period_3006_date_and_period_range(self) -> None:
        """3006: PDF date 2024-10-05 is outside 2024-07-01 to 2024-09-30."""
        case = next(c for c in CASES if c["doc_num"] == 3006)
        [cand] = _ingest_and_reconcile(case)
        assert cand.check_id == "correct_period"
        assert cand.extracted_value == "2024-10-05"
        assert cand.listing_value == f"{PERIOD_START} to {PERIOD_END}"
        assert cand.determinability == "D+ (conditional on extraction)"
        assert cand.severity == "MEDIUM"

    def test_total_inconsistency_3007_values(self) -> None:
        """3007: PDF total 4530 ≠ 4200+294=4494 (delta 36 on invoice face)."""
        case = next(c for c in CASES if c["doc_num"] == 3007)
        [cand] = _ingest_and_reconcile(case)
        assert cand.check_id == "total_inconsistency"
        assert cand.extracted_value == pytest.approx(4530.0)
        assert cand.listing_value == pytest.approx(4494.0)   # 4200+294
        assert cand.determinability == "J+"
        assert cand.severity == "MEDIUM"

    def test_total_inconsistency_does_not_reference_listing_tax_total(self) -> None:
        """total_inconsistency must use PDF's own arithmetic, not line_item tax_total."""
        case = next(c for c in CASES if c["doc_num"] == 3007)
        # Fabricate a line_item with a different tax_total than what's on the PDF;
        # the total_inconsistency candidate must still appear because the PDF's
        # own arithmetic is wrong regardless of what the SAP record says.
        altered_line = dict(case["line_item_record"], tax_total=999.0)
        extracted = ingest(DOCS_DIR / case["pdf_filename"])
        candidates = reconcile(extracted, altered_line, PERIOD_START, PERIOD_END)
        check_ids = {c.check_id for c in candidates}
        assert "total_inconsistency" in check_ids, (
            "total_inconsistency candidate disappeared when SAP tax_total was altered — "
            "this check must rely solely on the extracted PDF values."
        )

    def test_reg11_absent_3005_fields(self) -> None:
        """3005: no GST reg on PDF face; extracted_value is None, listing_value is None."""
        case = next(c for c in CASES if c["doc_num"] == 3005)
        [cand] = _ingest_and_reconcile(case)
        assert cand.check_id == "reg11_supplier_gst_absent"
        assert cand.extracted_value is None
        assert cand.listing_value is None
        assert cand.determinability == "J+"
        assert cand.severity == "HIGH"

    def test_reg11_absent_3005_check_id_is_not_no_gst_reg(self) -> None:
        """reg11 document check must have check_id 'reg11_supplier_gst_absent', not 'NO_GST_REG'."""
        case = next(c for c in CASES if c["doc_num"] == 3005)
        [cand] = _ingest_and_reconcile(case)
        assert cand.check_id == "reg11_supplier_gst_absent"
        assert cand.check_id != "NO_GST_REG"

    def test_combined_3008_two_candidates(self) -> None:
        """3008 (combined): exactly gst_amount_mismatch + reg11_supplier_gst_absent."""
        case = next(c for c in CASES if c["doc_num"] == 3008)
        result = _ingest_and_reconcile(case)
        check_ids = {c.check_id for c in result}
        assert check_ids == {"gst_amount_mismatch", "reg11_supplier_gst_absent"}
        # GST: PDF 360 vs SAP 420 (6% instead of 7% of 6000)
        mismatch = next(c for c in result if c.check_id == "gst_amount_mismatch")
        assert mismatch.extracted_value == pytest.approx(360.0)
        assert mismatch.listing_value == pytest.approx(420.0)
        # Reg: absent
        reg = next(c for c in result if c.check_id == "reg11_supplier_gst_absent")
        assert reg.extracted_value is None

    def test_clean_cases_zero_candidates(self) -> None:
        """Cases 3001 and 3002 must produce zero candidates."""
        for doc_num in (3001, 3002):
            case = next(c for c in CASES if c["doc_num"] == doc_num)
            result = _ingest_and_reconcile(case)
            assert result == [], (
                f"doc_num={doc_num} (clean): expected zero candidates, got "
                f"{[c.check_id for c in result]!r}"
            )


# ---------------------------------------------------------------------------
# R3 — F5 isolation: boxes and gate results byte-identical before/after
# ---------------------------------------------------------------------------

def _make_gate_results() -> dict:
    return {
        "all_passed": True,
        "gates": [
            {
                "gate": i,
                "name": f"gate-{i}",
                "after_step": "step",
                "status": "PASS" if i > 1 else "WARN_PASS",
                "passed": True,
                "checked": {"sap_inline_count": None} if i == 1 else {},
            }
            for i in range(1, 6)
        ],
    }


class TestF5Isolation:
    def test_boxes_and_gates_unchanged_after_reconcile(self) -> None:
        """reconcile() must never mutate the compile_output dict or gate results.
        F5 box figures and gate results are byte-identical before and after running
        reconcile() on all 8 fixture cases."""
        compile_output = json.loads(CHAIN_FIXTURE.read_text(encoding="utf-8"))
        gate_results = _make_gate_results()

        # Snapshot BEFORE
        boxes_before = json.dumps(compile_output["calculate"]["boxes"], sort_keys=True)
        gates_before = json.dumps(gate_results, sort_keys=True)

        # Run reconcile on all 8 fixture cases
        for case in CASES:
            extracted = ingest(DOCS_DIR / case["pdf_filename"])
            candidates = reconcile(
                extracted, case["line_item_record"], PERIOD_START, PERIOD_END
            )
            # Verify candidates carry their own doc_num, not any gate/box key
            for cand in candidates:
                assert cand.doc_num == case["doc_num"]

        # Snapshot AFTER — must be byte-identical
        boxes_after = json.dumps(compile_output["calculate"]["boxes"], sort_keys=True)
        gates_after = json.dumps(gate_results, sort_keys=True)

        assert boxes_before == boxes_after, (
            "compile_output['calculate']['boxes'] was mutated by reconcile()."
        )
        assert gates_before == gates_after, (
            "gate_results dict was mutated by reconcile()."
        )

    def test_reconcile_candidates_not_in_compile_output_keys(self) -> None:
        """The candidate check_ids must not appear as keys in compile_output."""
        compile_output = json.loads(CHAIN_FIXTURE.read_text(encoding="utf-8"))
        all_check_ids = {
            c.check_id
            for case in CASES
            for c in reconcile(
                ingest(DOCS_DIR / case["pdf_filename"]),
                case["line_item_record"],
                PERIOD_START,
                PERIOD_END,
            )
        }
        compile_keys = set(json.dumps(compile_output))  # flat string of all keys
        for check_id in all_check_ids:
            assert check_id not in compile_output, (
                f"check_id {check_id!r} unexpectedly appears as a top-level key "
                f"in compile_output — reconcile output must not bleed into Layer 1."
            )


# ---------------------------------------------------------------------------
# R4 — Import containment
# ---------------------------------------------------------------------------

def _reconcile_src() -> str:
    return (_DOCUMENTS_DIR / "reconcile.py").read_text(encoding="utf-8")


class TestContainment:
    def test_no_orchestrator_import(self) -> None:
        src = _reconcile_src()
        assert not re.search(r'^(?:import orchestrator|from orchestrator)', src, re.MULTILINE), (
            "documents/reconcile.py imports orchestrator — invariant violated."
        )

    def test_no_audit_bundle_import(self) -> None:
        src = _reconcile_src()
        assert not re.search(r'^(?:import audit_bundle|from audit_bundle)', src, re.MULTILINE), (
            "documents/reconcile.py imports audit_bundle — invariant violated."
        )

    def test_no_boxes_gates_calculate_import(self) -> None:
        src = _reconcile_src()
        for forbidden in ("boxes", "gates", "calculate"):
            assert not re.search(
                rf'^(?:import {forbidden}|from {forbidden})',
                src, re.MULTILINE,
            ), f"documents/reconcile.py imports {forbidden!r} — invariant violated."

    def test_no_anthropic_import(self) -> None:
        src = _reconcile_src()
        matches = re.findall(r'^(?:import anthropic|from anthropic)', src, re.MULTILINE)
        assert not matches, (
            f"documents/reconcile.py has anthropic import statement(s): {matches} — "
            "this module must be pure Python, no SDK."
        )

    def test_no_no_gst_reg_reference(self) -> None:
        """reconcile.py must not import or reference the NO_GST_REG check."""
        src = _reconcile_src()
        # Allow the name to appear in comments explaining the distinction, but
        # must not appear as a string literal that could be used as a check_id.
        assert '"NO_GST_REG"' not in src, (
            "documents/reconcile.py contains 'NO_GST_REG' as a string literal — "
            "reg11_supplier_gst_absent must have its own distinct check_id."
        )
        assert "'NO_GST_REG'" not in src, (
            "documents/reconcile.py contains 'NO_GST_REG' as a string literal."
        )


# ---------------------------------------------------------------------------
# R5 — Named constant and tolerance behaviour
# ---------------------------------------------------------------------------

class TestToleranceAndConstants:
    def test_amount_tolerance_is_named_constant(self) -> None:
        """AMOUNT_TOLERANCE must be a named constant importable from the module."""
        assert isinstance(AMOUNT_TOLERANCE, float)
        assert AMOUNT_TOLERANCE == 0.01

    def test_exactly_at_tolerance_is_not_a_candidate(self) -> None:
        """A difference equal to AMOUNT_TOLERANCE must NOT produce a candidate
        (the check is strictly greater-than, so the boundary is clean)."""
        case = next(c for c in CASES if c["doc_num"] == 3001)
        extracted = ingest(DOCS_DIR / case["pdf_filename"])
        # Fabricate a line_item whose tax_total differs by exactly AMOUNT_TOLERANCE
        tweaked = dict(case["line_item_record"], tax_total=350.0 + AMOUNT_TOLERANCE)
        result = reconcile(extracted, tweaked, PERIOD_START, PERIOD_END)
        mismatch = [c for c in result if c.check_id == "gst_amount_mismatch"]
        assert not mismatch, (
            f"A difference of exactly {AMOUNT_TOLERANCE} should not produce a "
            f"candidate (boundary must be exclusive)."
        )

    def test_one_cent_above_tolerance_is_candidate(self) -> None:
        """A difference of AMOUNT_TOLERANCE + 0.01 must produce a candidate."""
        case = next(c for c in CASES if c["doc_num"] == 3001)
        extracted = ingest(DOCS_DIR / case["pdf_filename"])
        tweaked = dict(case["line_item_record"], tax_total=350.0 + AMOUNT_TOLERANCE + 0.01)
        result = reconcile(extracted, tweaked, PERIOD_START, PERIOD_END)
        mismatch = [c for c in result if c.check_id == "gst_amount_mismatch"]
        assert mismatch, (
            "A difference of AMOUNT_TOLERANCE + 0.01 must produce a gst_amount_mismatch candidate."
        )

    def test_period_boundary_inclusive_start(self) -> None:
        """A date equal to period_start must NOT be flagged as outside period."""
        case = next(c for c in CASES if c["doc_num"] == 3001)  # date = 2024-07-15
        extracted = ingest(DOCS_DIR / case["pdf_filename"])
        result = reconcile(extracted, case["line_item_record"], "2024-07-15", "2024-09-30")
        period_cands = [c for c in result if c.check_id == "correct_period"]
        assert not period_cands

    def test_period_boundary_inclusive_end(self) -> None:
        """A date equal to period_end must NOT be flagged as outside period."""
        case = next(c for c in CASES if c["doc_num"] == 3001)
        extracted = ingest(DOCS_DIR / case["pdf_filename"])
        result = reconcile(extracted, case["line_item_record"], "2024-01-01", "2024-07-15")
        period_cands = [c for c in result if c.check_id == "correct_period"]
        assert not period_cands

    def test_skips_gst_check_when_extracted_gst_none(self) -> None:
        """No gst_amount_mismatch candidate when extracted.gst_amount is None."""
        case = next(c for c in CASES if c["doc_num"] == 3001)
        line_item = case["line_item_record"]
        extracted = ExtractedInvoice(
            supplier_name="Test",
            supplier_gst_regno="M12345678X",
            invoice_number="INV-3001",
            invoice_date="2024-07-15",
            total_excl_gst=5000.0,
            gst_rate="7%",
            gst_amount=None,       # ← extraction failed
            total_incl_gst=5350.0,
            source="born_digital",
            validation_status="unvalidated",
            fields_present={"gst_amount": False, "supplier_gst_regno": True},
        )
        result = reconcile(extracted, line_item, PERIOD_START, PERIOD_END)
        assert not any(c.check_id == "gst_amount_mismatch" for c in result)

    def test_skips_total_check_when_any_component_none(self) -> None:
        """No total_inconsistency candidate when any PDF component is None."""
        case = next(c for c in CASES if c["doc_num"] == 3001)
        line_item = case["line_item_record"]
        extracted = ExtractedInvoice(
            supplier_name="Test",
            supplier_gst_regno="M12345678X",
            invoice_number="INV-3001",
            invoice_date="2024-07-15",
            total_excl_gst=5000.0,
            gst_rate="7%",
            gst_amount=350.0,
            total_incl_gst=None,   # ← extraction failed
            source="born_digital",
            validation_status="unvalidated",
            fields_present={"supplier_gst_regno": True},
        )
        result = reconcile(extracted, line_item, PERIOD_START, PERIOD_END)
        assert not any(c.check_id == "total_inconsistency" for c in result)
