"""
tests/test_agent_checkspec.py — T-10: every existing check expresses as a CheckSpec entry.

CheckSpec is v0/PROVISIONAL. It is not wired into any consumer. check_id and
iras_basis will be reconciled against Collin's canonical IRAS VatGroup remap
and T2.18 config_keys when those land. Collin ratifies the schema before
building deterministic checks against it. This test proves the schema CAN
express all current checks; it does not freeze the schema as a contract.

No SDK, no SAP, no network.
"""
from __future__ import annotations

from agent.schemas import CheckSpec
from agent.registry import CHECK_REGISTRY


# ---------------------------------------------------------------------------
# T-10  All existing checks express as CheckSpec entries in CHECK_REGISTRY
# ---------------------------------------------------------------------------

# Canonical IDs of all checks that must be representable in the CheckSpec schema.
# Source of truth: Phase 1 R3 recon.
EXPECTED_CHECK_IDS = frozenset({
    # E1–E4: from sap_b1_server.py / orchestrator classify step
    "E1",
    "E2",
    "E3",
    "E4",
    # detect step (sap_b1_server.py)
    "NO_GST_REG",
    "COMPLETENESS",
    # listing checks (orchestrator/check_listing.py)
    "SEQ_GAP",
    "DUP_CLAIM",
    # declared-F5 checks (orchestrator/check_declared_f5.py)
    "declared_A",
    "declared_B",
    # document reconciliation checks (documents/reconcile.py)
    "gst_amount_mismatch",
    "correct_period",
    "total_inconsistency",
    "reg11_supplier_gst_absent",
})


class TestCheckSpecProofOfFit:
    def test_all_expected_check_ids_in_registry(self):
        registered_ids = set(CHECK_REGISTRY.keys())
        missing = EXPECTED_CHECK_IDS - registered_ids
        assert not missing, (
            f"These checks are not represented in CHECK_REGISTRY: {sorted(missing)}"
        )

    def test_registry_entries_are_checkspec_instances(self):
        for check_id, spec in CHECK_REGISTRY.items():
            assert isinstance(spec, CheckSpec), (
                f"CHECK_REGISTRY[{check_id!r}] is {type(spec).__name__}, expected CheckSpec"
            )

    def test_all_specs_have_non_empty_check_id(self):
        for check_id, spec in CHECK_REGISTRY.items():
            assert spec.check_id == check_id, (
                f"spec.check_id={spec.check_id!r} doesn't match registry key {check_id!r}"
            )
            assert spec.check_id.strip()

    def test_all_specs_have_display_name(self):
        for check_id, spec in CHECK_REGISTRY.items():
            assert spec.display_name.strip(), f"{check_id!r} missing display_name"

    def test_all_specs_have_iras_basis(self):
        for check_id, spec in CHECK_REGISTRY.items():
            assert spec.iras_basis.strip(), f"{check_id!r} missing iras_basis"

    def test_all_specs_have_inputs_needed(self):
        for check_id, spec in CHECK_REGISTRY.items():
            assert isinstance(spec.inputs_needed, list), (
                f"{check_id!r} inputs_needed must be a list"
            )
            assert len(spec.inputs_needed) > 0, f"{check_id!r} has empty inputs_needed"

    def test_all_specs_have_valid_finding_type(self):
        valid_types = {"deterministic", "probabilistic"}
        for check_id, spec in CHECK_REGISTRY.items():
            assert spec.finding_type in valid_types, (
                f"{check_id!r} finding_type={spec.finding_type!r} not in {valid_types}"
            )

    def test_document_checks_are_probabilistic(self):
        """Document checks operate on PDF-extracted values — probabilistic by nature."""
        probabilistic = {
            "gst_amount_mismatch",
            "correct_period",
            "total_inconsistency",
            "reg11_supplier_gst_absent",
        }
        for check_id in probabilistic:
            assert CHECK_REGISTRY[check_id].finding_type == "probabilistic", (
                f"{check_id!r} should be probabilistic (PDF-derived values)"
            )

    def test_listing_and_detect_checks_are_deterministic(self):
        deterministic = {"E1", "E2", "E3", "E4", "NO_GST_REG", "COMPLETENESS",
                         "SEQ_GAP", "DUP_CLAIM", "declared_A", "declared_B"}
        for check_id in deterministic:
            assert CHECK_REGISTRY[check_id].finding_type == "deterministic", (
                f"{check_id!r} should be deterministic"
            )

    def test_checkspec_is_ratified_v1(self):
        """Smoke-test that the registry exports the ratified v1 contract marker.

        T5.2c graduated CheckSpec from v0/PROVISIONAL to v1: reconciled against the
        real check implementations and frozen as the coordination contract T5.4
        consumes (config_keys added as an applicability gate; iras_basis /
        finding_schema matched to reality). Collin co-owns CheckSpec and ratifies
        the contract at merge. See tests/test_t52c_checkspec_finalisation.py.
        """
        import agent.registry as reg_mod
        assert hasattr(reg_mod, "CHECKSPEC_STATUS"), (
            "agent/registry.py must export CHECKSPEC_STATUS to signal the contract version"
        )
        assert reg_mod.CHECKSPEC_STATUS == "v1"
