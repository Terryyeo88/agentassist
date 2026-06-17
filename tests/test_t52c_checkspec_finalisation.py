"""
tests/test_t52c_checkspec_finalisation.py — T5.2c: CheckSpec v0/PROVISIONAL → v1.

Graduates the CheckSpec registry to the frozen coordination contract T5.4 consumes.
This is RECONCILE-TO-REALITY + ADD config_keys, not a redesign. The assertions here
are the failing-test-first gate for:

  (a) config_keys present on every CheckSpec; default [] == "always applies".
      config_keys is an APPLICABILITY gate (does this check run for this client),
      NOT routing. All 14 existing checks are unconditional, so all == [].
      (E2 Template-4/5 routing stays a report-layer concern — report/routing.py —
      and must NOT leak into config_keys, or the planner would drop E2 for
      non-exempt clients.)
  (b) the round-2-validated slot contract is intact: NO_GST_REG keeps
      supplier_catalog and the document checks keep document_pdfs, and every
      agent-gathered slot still has a reader.
  (c) CHECKSPEC_STATUS flipped to "v1".
  (d) every CheckSpec check_id resolves to a real implemented check.
  (e) the one inputs_needed correction (E3 also fires on purchase TX lines).
  (f) finding_schema reconciled to the real emitted finding fields (E1-E4 encode
      the enriched detect shape that extract_findings reads at the loop boundary).

No SDK, no SAP, no network.
"""
from __future__ import annotations

import agent.registry as reg_mod
from agent.completeness import AGENT_GATHERED_INPUTS, READ_TOOL_SLOT
from agent.registry import CHECK_REGISTRY
from agent.schemas import CheckSpec

# The 14 checks, each backed by a real implementation (source of truth: Phase 1 recon).
#   E1-E4, NO_GST_REG, COMPLETENESS  -> mcp-servers/custom/sap_b1_server.py
#   SEQ_GAP, DUP_CLAIM               -> orchestrator/check_listing.py
#   declared_A, declared_B          -> orchestrator/check_declared_f5.py
#   gst_amount_mismatch, correct_period,
#   total_inconsistency, reg11_supplier_gst_absent -> documents/reconcile.py
REAL_CHECK_IDS = frozenset({
    "E1", "E2", "E3", "E4", "NO_GST_REG", "COMPLETENESS",
    "SEQ_GAP", "DUP_CLAIM", "declared_A", "declared_B",
    "gst_amount_mismatch", "correct_period", "total_inconsistency",
    "reg11_supplier_gst_absent",
})


# --------------------------------------------------------------------------- #
# (c) status flipped to v1
# --------------------------------------------------------------------------- #

def test_checkspec_status_is_v1():
    assert reg_mod.CHECKSPEC_STATUS == "v1"


# --------------------------------------------------------------------------- #
# (a) config_keys: present on the schema and on every entry; applicability gate
# --------------------------------------------------------------------------- #

def test_checkspec_schema_has_config_keys_default_empty():
    spec = CheckSpec(
        check_id="X", display_name="x", iras_basis="x",
        inputs_needed=["a"], finding_type="deterministic",
    )
    assert spec.config_keys == [], "config_keys must default to [] (== always applies)"


def test_every_check_has_config_keys_list():
    for check_id, spec in CHECK_REGISTRY.items():
        assert isinstance(spec.config_keys, list), (
            f"{check_id!r} config_keys must be a list"
        )


def test_all_existing_checks_are_unconditional():
    # Every one of the 14 current checks applies to every GST-registered client.
    # config_keys is an applicability gate; none of the current checks is gated.
    # E2 included: its exempt Template-4/5 routing is a report-layer concern, NOT
    # applicability — E2 must run for every client or non-exempt clients lose it.
    for check_id, spec in CHECK_REGISTRY.items():
        assert spec.config_keys == [], (
            f"{check_id!r} config_keys must be [] — no current check is scheme-gated"
        )


# --------------------------------------------------------------------------- #
# (d) every check_id resolves to a real implemented check (closed set)
# --------------------------------------------------------------------------- #

def test_registry_check_ids_match_real_checks_exactly():
    registered = set(CHECK_REGISTRY.keys())
    assert registered == set(REAL_CHECK_IDS), (
        f"registry drift: extra={sorted(registered - REAL_CHECK_IDS)}, "
        f"missing={sorted(REAL_CHECK_IDS - registered)}"
    )


# --------------------------------------------------------------------------- #
# (b) slot contract — the round-2-validated load-bearing bindings survive
# --------------------------------------------------------------------------- #

def test_no_gst_reg_keeps_supplier_catalog_slot():
    spec = CHECK_REGISTRY["NO_GST_REG"]
    assert "supplier_catalog" in spec.inputs_needed, (
        "NO_GST_REG must keep supplier_catalog or the live-validated completeness "
        "path dies (read_vendor_gst_status -> supplier_catalog)"
    )
    assert READ_TOOL_SLOT["read_vendor_gst_status"] == "supplier_catalog"


def test_document_checks_keep_document_pdfs_slot():
    for check_id in ("gst_amount_mismatch", "correct_period",
                     "total_inconsistency", "reg11_supplier_gst_absent"):
        assert "document_pdfs" in CHECK_REGISTRY[check_id].inputs_needed, (
            f"{check_id!r} must keep document_pdfs (get_source_document slot)"
        )
    assert READ_TOOL_SLOT["get_source_document"] == "document_pdfs"


def test_every_agent_gathered_slot_still_has_reader():
    # The same guard as T5.3g — re-asserted under the v1 contract.
    assert set(READ_TOOL_SLOT.values()) >= set(AGENT_GATHERED_INPUTS)


def test_agent_gathered_slots_only_on_expected_checks():
    # Exactly these checks bind an agent-gathered slot; no others.
    bind = {
        cid: sorted(set(spec.inputs_needed) & AGENT_GATHERED_INPUTS)
        for cid, spec in CHECK_REGISTRY.items()
        if set(spec.inputs_needed) & AGENT_GATHERED_INPUTS
    }
    assert bind == {
        "NO_GST_REG": ["supplier_catalog"],
        "gst_amount_mismatch": ["document_pdfs"],
        "correct_period": ["document_pdfs"],
        "total_inconsistency": ["document_pdfs"],
        "reg11_supplier_gst_absent": ["document_pdfs"],
    }


# --------------------------------------------------------------------------- #
# (e) inputs_needed correction — E3 also fires on purchase TX lines
# --------------------------------------------------------------------------- #

def test_e3_inputs_include_purchase_invoices():
    spec = CHECK_REGISTRY["E3"]
    assert "sales_invoices" in spec.inputs_needed
    assert "purchase_invoices" in spec.inputs_needed, (
        "E3 fires on purchase TX lines too (sap_b1_server._classify_line); "
        "inputs_needed must list purchase_invoices"
    )


# --------------------------------------------------------------------------- #
# (f) finding_schema reconciled to the real emitted finding fields
# --------------------------------------------------------------------------- #

def test_e1_e4_encode_enriched_detect_shape():
    # extract_findings (agent/dossier.py) reads E1-E4 from compile_output.detect.issues
    # — the enriched detect shape, identical fields to NO_GST_REG.
    enriched = {"severity", "error_code", "doc_num", "doc_date",
                "card_name", "description", "recommendation"}
    for cid in ("E1", "E2", "E3", "E4"):
        fields = set(CHECK_REGISTRY[cid].finding_schema)
        assert enriched <= fields, f"{cid!r} finding_schema missing {enriched - fields}"


def test_detect_checks_finding_schema_has_severity_recommendation():
    for cid in ("NO_GST_REG", "COMPLETENESS"):
        fields = set(CHECK_REGISTRY[cid].finding_schema)
        assert {"severity", "recommendation", "doc_date"} <= fields, (
            f"{cid!r} finding_schema missing severity/recommendation/doc_date"
        )


def test_listing_checks_finding_schema_reconciled():
    seq = set(CHECK_REGISTRY["SEQ_GAP"].finding_schema)
    assert {"series_min", "series_max", "note"} <= seq, (
        f"SEQ_GAP finding_schema missing {{series_min, series_max, note}}: {seq}"
    )
    dup = set(CHECK_REGISTRY["DUP_CLAIM"].finding_schema)
    assert {"card_code", "doc_total", "note"} <= dup, (
        f"DUP_CLAIM finding_schema missing {{card_code, doc_total, note}}: {dup}"
    )


def test_declared_b_finding_schema_reconciled():
    fields = set(CHECK_REGISTRY["declared_B"].finding_schema)
    assert {"direction", "tolerance_applied", "hypothesis"} <= fields, (
        f"declared_B finding_schema missing reconciled fields: {fields}"
    )


def test_document_candidate_finding_schema_reconciled():
    for cid in ("gst_amount_mismatch", "correct_period",
                "total_inconsistency", "reg11_supplier_gst_absent"):
        fields = set(CHECK_REGISTRY[cid].finding_schema)
        assert {"doc_num", "extraction_source", "validation_status"} <= fields, (
            f"{cid!r} finding_schema missing DocumentCandidate fields: {fields}"
        )
