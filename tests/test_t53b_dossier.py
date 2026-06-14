"""
tests/test_t53b_dossier.py — T5.3 Slice 2: DossierArtifact schema, finding
extraction, and inputs_hash anchoring.

A DossierArtifact carries, per finding: finding_id, check_id, finding_type, an
evidence map, candidate_framing_text, a completeness block {required/present/
satisfied}, and an inputs_hash anchored via the same primitive build_proposal uses
(``compute_inputs_hash``) so the dossier and the proposal that stages it share one
hash.

``extract_findings`` flattens a ReviewResult into a uniform finding list across
compile_output (deterministic), document_candidates (probabilistic), and the
reasoning_artefact (probabilistic).

Hermetic: hand-built ReviewResult dict, no SDK, no model, no SAP, no network.
"""
from __future__ import annotations

from agent.dossier import (
    DossierArtifact,
    Finding,
    build_dossier,
    dossier_inputs,
    extract_findings,
)
from agent.proposals import build_proposal, compute_inputs_hash


def _review_result_dict() -> dict:
    """A minimal serialised ReviewResult with >=1 deterministic + >=1 probabilistic finding."""
    return {
        "status": "completed",
        "compile_output": {
            "detect": {
                "issues": [
                    {
                        "severity": "HIGH", "error_code": "NO_GST_REG", "doc_num": 605,
                        "card_name": "Mama Shop Supplies", "description": "no GST reg no",
                        "recommendation": "Review whether input tax is claimable.",
                    },
                ],
            },
        },
        "reasoning_artefact": {
            "status": "ok",
            "candidates": [
                {
                    "doc_num": 712, "card_name": "Acme Pte Ltd", "suspected_category": "entertainment",
                    "reasoning": "client entertainment", "phrasing": "Consider reviewing whether ...",
                    "confidence": "low",
                },
            ],
        },
        "document_candidates": [
            {
                "doc_num": 958, "check_id": "gst_amount_mismatch", "severity": "MEDIUM",
                "message": "PDF GST differs from SAP line", "extracted_value": 74.0,
                "listing_value": 70.0, "determinability": "born_digital",
            },
        ],
    }


class TestExtractFindings:
    def test_extracts_deterministic_and_probabilistic(self):
        findings = extract_findings(_review_result_dict())
        kinds = {f.finding_type for f in findings}
        assert "deterministic" in kinds
        assert "probabilistic" in kinds

    def test_deterministic_finding_from_detect_issue(self):
        findings = extract_findings(_review_result_dict())
        det = [f for f in findings if f.finding_type == "deterministic"]
        assert det and det[0].check_id == "NO_GST_REG"
        assert det[0].payload["doc_num"] == 605

    def test_probabilistic_finding_from_document_candidate(self):
        findings = extract_findings(_review_result_dict())
        doc = [f for f in findings if f.source == "document_candidates"]
        assert doc and doc[0].check_id == "gst_amount_mismatch"
        assert doc[0].finding_type == "probabilistic"

    def test_finding_ids_are_unique(self):
        findings = extract_findings(_review_result_dict())
        ids = [f.finding_id for f in findings]
        assert len(ids) == len(set(ids))

    def test_halted_result_yields_no_findings(self):
        findings = extract_findings({"status": "halted", "compile_output": None,
                                     "reasoning_artefact": None, "document_candidates": None})
        assert findings == []


class TestDossierAnchoring:
    def test_inputs_hash_matches_build_proposal(self):
        finding = Finding(
            finding_id="detect:NO_GST_REG:605", check_id="NO_GST_REG",
            finding_type="deterministic", source="compile_output.detect",
            payload={"doc_num": 605},
        )
        evidence = {
            "purchase_invoices": {"doc_num": 605},
            "supplier_catalog": {"found": True, "gst_registered": False},
        }
        framing = "Invoice 605 appears to be a candidate for review."
        completeness = {"required": ["purchase_invoices", "supplier_catalog"],
                        "present": ["purchase_invoices", "supplier_catalog"],
                        "missing": [], "satisfied": True}

        inputs = dossier_inputs(finding, evidence, framing, completeness)
        dossier = build_dossier(finding, evidence, framing, completeness)

        # The dossier's inputs_hash is anchored via the SAME primitive build_proposal uses.
        assert dossier.inputs_hash == compute_inputs_hash(inputs)

        proposal = build_proposal(
            action="attach_dossier",
            justification="Human-reviewable dossier for NO_GST_REG on doc 605, staged for review.",
            evidence_refs=["compile_output.detect:605"],
            inputs=inputs,
        )
        # Dossier and the proposal that stages it share one anchoring hash.
        assert dossier.inputs_hash == proposal.inputs_hash

    def test_build_dossier_carries_all_fields(self):
        finding = Finding(
            finding_id="doc:gst_amount_mismatch:958", check_id="gst_amount_mismatch",
            finding_type="probabilistic", source="document_candidates",
            payload={"doc_num": 958},
        )
        evidence = {"document_pdfs": "/tmp/INV-958.pdf", "sap_listing": {"doc_num": 958}}
        completeness = {"required": ["document_pdfs", "sap_listing"],
                        "present": ["document_pdfs", "sap_listing"],
                        "missing": [], "satisfied": True}
        dossier = build_dossier(finding, evidence, "appears to be a candidate", completeness)
        assert isinstance(dossier, DossierArtifact)
        assert dossier.finding_id == "doc:gst_amount_mismatch:958"
        assert dossier.check_id == "gst_amount_mismatch"
        assert dossier.finding_type == "probabilistic"
        assert dossier.evidence == evidence
        assert dossier.completeness["satisfied"] is True
        assert dossier.inputs_hash.startswith("sha256:")
