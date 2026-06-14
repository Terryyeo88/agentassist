"""
tests/test_t53b_completeness.py — T5.3 Slice 2: CODE-DEFINED completeness checklist.

The verify step of the case-file loop is a CODE-DEFINED completeness checklist
keyed to ``CheckSpec.inputs_needed`` per finding type — NEVER model self-
assessment.  These tests run the checklist as a pure function with NO model in
the loop:

  * golden pass  — a dossier whose evidence covers every required input slot →
    satisfied=True.
  * missing-slot fail — drop one required slot → satisfied=False and the missing
    slot is named.

The required set is driven directly by the CheckSpec registry; if the registry's
inputs_needed changes, the checklist changes with it (no duplicated literals).

Hermetic: pure dict inputs, no SDK, no model, no SAP, no network.
"""
from __future__ import annotations

import pytest

from agent.completeness import (
    AGENT_GATHERED_INPUTS,
    engine_seeded_slots,
    evaluate_completeness,
    required_inputs,
)
from agent.registry import CHECK_REGISTRY


class TestRequiredInputsTrackRegistry:
    def test_required_inputs_equal_checkspec_inputs_needed(self):
        # The checklist is DRIVEN BY CheckSpec.inputs_needed — not a hand-copied list.
        for check_id, spec in CHECK_REGISTRY.items():
            assert required_inputs(check_id) == list(spec.inputs_needed)

    def test_unknown_check_id_raises(self):
        with pytest.raises(ValueError):
            evaluate_completeness("NOT_A_CHECK", {})


class TestCompletenessGoldenPass:
    def test_no_gst_reg_all_slots_present_is_satisfied(self):
        # NO_GST_REG.inputs_needed == ["purchase_invoices", "supplier_catalog"].
        evidence = {
            "purchase_invoices": {"doc_num": 605},
            "supplier_catalog": {"found": True, "gst_registered": False},
        }
        result = evaluate_completeness("NO_GST_REG", evidence)
        assert result["required"] == ["purchase_invoices", "supplier_catalog"]
        assert set(result["present"]) == {"purchase_invoices", "supplier_catalog"}
        assert result["satisfied"] is True
        assert result["missing"] == []

    def test_probabilistic_document_check_satisfied(self):
        # gst_amount_mismatch.inputs_needed == ["document_pdfs", "sap_listing"].
        evidence = {
            "document_pdfs": "/tmp/INV-605.pdf",
            "sap_listing": {"doc_num": 605, "tax_total": 70.0},
        }
        result = evaluate_completeness("gst_amount_mismatch", evidence)
        assert result["satisfied"] is True


class TestCompletenessMissingSlotFails:
    def test_missing_supplier_catalog_is_unsatisfied(self):
        evidence = {"purchase_invoices": {"doc_num": 605}}  # supplier_catalog absent
        result = evaluate_completeness("NO_GST_REG", evidence)
        assert result["satisfied"] is False
        assert result["missing"] == ["supplier_catalog"]
        assert "supplier_catalog" not in result["present"]

    def test_present_but_none_value_does_not_count(self):
        # A slot present with a None value is NOT evidence — completeness is structural
        # presence of a non-null value, not the model asserting "done".
        evidence = {
            "purchase_invoices": {"doc_num": 605},
            "supplier_catalog": None,
        }
        result = evaluate_completeness("NO_GST_REG", evidence)
        assert result["satisfied"] is False
        assert "supplier_catalog" in result["missing"]


class TestInputTaxonomy:
    def test_agent_gathered_inputs_map_to_tier0_reads(self):
        # The two slots an agent must gather via Tier-0 reads.
        assert AGENT_GATHERED_INPUTS == {"supplier_catalog", "document_pdfs"}

    def test_engine_seeded_slots_exclude_agent_gathered(self):
        # NO_GST_REG: purchase_invoices is engine-seeded; supplier_catalog is not.
        seeded = engine_seeded_slots("NO_GST_REG")
        assert "purchase_invoices" in seeded
        assert "supplier_catalog" not in seeded
