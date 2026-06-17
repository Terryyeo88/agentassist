"""T5.4 — Check planner: routing over the FIXED v1 CheckSpec registry (hermetic).

The planner SELECTS the applicable subset of registry CheckSpec entries for a
client; it never composes new check logic. The invariants under test:

  (a) With every real CheckSpec carrying config_keys=[], every registry check is
      in the plan, in registry order — the applicability gate drops NOTHING today.
  (b) A SYNTHETIC CheckSpec config_keys=["participates_in_mes"] is included iff
      the client flag is True — proves the gate can actually EXCLUDE (the
      mechanism), distinct from (a) which proves it excludes nothing now.
  (c) Output is ALWAYS ⊆ the active registry's check_ids — even on malformed
      config; the planner can NEVER emit a non-registry check_id.
  (d) Tier model: first plan → Tier-2 ProposalArtifact → human approval → record →
      identical re-plan → Tier 1 → mutate one flag → fingerprint differs → Tier 2.

Hermetic: no live model, no SAP, no tokens, no network.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent.planner import (
    ApprovedPlanStore,
    CheckPlan,
    PlanResult,
    compute_plan_fingerprint,
    confirm_approved_plan,
    plan_checks,
    SCHEME_FLAGS,
)
from agent.proposals import StagingStore
from agent.registry import CHECK_REGISTRY
from agent.schemas import CheckSpec, Tier
from config.loader import ClientConfig


_REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _cfg(**overrides) -> ClientConfig:
    """A fully-defaulted ClientConfig (all four T2.18 scheme flags default False)."""
    defaults = dict(
        client_id="testclient",
        client_name="Test Client Pte Ltd",
        gst_registration_number="M90000001A",
        applicable_gst_rate=0.09,
        service_layer_url="https://10.0.0.1:50000/b1s/v2",
        company_db="TESTDB",
        username="sap_user",
        password="HUNTER2_TEST",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.10,
        reviewer_name="Jane Tan",
        firm_name="Tan & Associates",
    )
    defaults.update(overrides)
    return ClientConfig(**defaults)


_SYNTH_MES = CheckSpec(
    check_id="SYNTH_MES",
    display_name="Synthetic MES-gated check (test only)",
    iras_basis="TEST — not a real check",
    inputs_needed=["sales_invoices"],
    finding_type="deterministic",
    finding_schema={},
    config_keys=["participates_in_mes"],
)


def _registry_with_synth() -> dict[str, CheckSpec]:
    """The real registry plus one MES-gated synthetic check."""
    reg = dict(CHECK_REGISTRY)
    reg[_SYNTH_MES.check_id] = _SYNTH_MES
    return reg


# ---------------------------------------------------------------------------
# (a) all real config_keys=[] → every registry check in the plan, registry order
# ---------------------------------------------------------------------------

class TestUnconditionalRegistry:
    def test_every_registry_check_is_in_the_plan(self):
        result = plan_checks(_cfg())
        assert set(result.plan.check_ids) == set(CHECK_REGISTRY.keys())

    def test_plan_preserves_registry_order(self):
        result = plan_checks(_cfg())
        assert result.plan.check_ids == tuple(CHECK_REGISTRY.keys())

    def test_flags_on_do_not_drop_any_unconditional_check(self):
        # All four flags True still yields every check — none are gated today.
        result = plan_checks(_cfg(
            actively_makes_exempt_supplies=True,
            participates_in_mes=True,
            participates_in_igds=True,
            reverse_charge_applicable=True,
        ))
        assert set(result.plan.check_ids) == set(CHECK_REGISTRY.keys())


# ---------------------------------------------------------------------------
# (b) SYNTHETIC config_keys=["participates_in_mes"] — included iff flag True
# ---------------------------------------------------------------------------

class TestApplicabilityMechanism:
    def test_synthetic_check_excluded_when_flag_false(self):
        result = plan_checks(_cfg(participates_in_mes=False),
                             registry=_registry_with_synth())
        assert "SYNTH_MES" not in result.plan.check_ids
        # every other (unconditional) check is still present
        assert set(CHECK_REGISTRY.keys()) <= set(result.plan.check_ids)

    def test_synthetic_check_included_when_flag_true(self):
        result = plan_checks(_cfg(participates_in_mes=True),
                             registry=_registry_with_synth())
        assert "SYNTH_MES" in result.plan.check_ids

    def test_other_flags_do_not_admit_the_mes_gated_check(self):
        # A different flag True must NOT satisfy a participates_in_mes gate.
        result = plan_checks(_cfg(participates_in_igds=True),
                             registry=_registry_with_synth())
        assert "SYNTH_MES" not in result.plan.check_ids


# ---------------------------------------------------------------------------
# (c) output ⊆ registry — including on malformed config
# ---------------------------------------------------------------------------

class TestSubsetInvariant:
    def test_output_subset_of_registry(self):
        result = plan_checks(_cfg())
        assert set(result.plan.check_ids) <= set(CHECK_REGISTRY.keys())

    def test_subset_holds_on_config_missing_flag_attributes(self):
        # A bare object with no scheme-flag attributes must not crash; missing
        # flags read as False; output still ⊆ registry.
        class Bare:
            client_id = "bare"
        result = plan_checks(Bare())
        assert set(result.plan.check_ids) <= set(CHECK_REGISTRY.keys())
        assert set(result.plan.check_ids) == set(CHECK_REGISTRY.keys())

    def test_subset_holds_on_garbage_flag_values(self):
        # Non-bool truthy/garbage values are coerced; never escapes the registry.
        class Garbage:
            client_id = "garbage"
            participates_in_mes = "yes"
            participates_in_igds = object()
            actively_makes_exempt_supplies = None
            reverse_charge_applicable = 0
        result = plan_checks(Garbage(), registry=_registry_with_synth())
        assert set(result.plan.check_ids) <= set(_registry_with_synth().keys())

    def test_subset_holds_against_injected_synth_registry(self):
        reg = _registry_with_synth()
        result = plan_checks(_cfg(participates_in_mes=True), registry=reg)
        assert set(result.plan.check_ids) <= set(reg.keys())


# ---------------------------------------------------------------------------
# (d) Tier model: first=T2 → approve → record → same=T1 → drift=T2
# ---------------------------------------------------------------------------

class TestTierModel:
    def test_first_plan_is_tier_2_and_stages_a_proposal(self):
        approved = ApprovedPlanStore()
        staging = StagingStore()
        result = plan_checks(_cfg(), approved_plan_store=approved,
                             staging_store=staging)
        assert result.tier == 2
        assert result.proposal is not None
        assert result.proposal.tier == Tier.TWO.value
        assert result.proposal.status == "pending"
        assert len(staging.list_pending()) == 1

    def test_full_lifecycle_first_approve_same_drift(self):
        approved = ApprovedPlanStore()
        staging = StagingStore()
        cfg = _cfg()

        # 1. First plan → Tier 2, proposal staged.
        first = plan_checks(cfg, approved_plan_store=approved, staging_store=staging)
        assert first.tier == 2
        assert approved.get(cfg.client_id) is None  # NOT recorded on generation

        # 2. Human approves the proposal, then the plan is recorded.
        staging.approve(first.proposal.proposal_id)
        confirm_approved_plan(approved, first.plan, first.proposal)
        assert approved.get(cfg.client_id) == first.plan.plan_fingerprint

        # 3. Identical re-plan → Tier 1, no new proposal.
        same = plan_checks(cfg, approved_plan_store=approved, staging_store=staging)
        assert same.tier == 1
        assert same.proposal is None
        assert same.plan.plan_fingerprint == first.plan.plan_fingerprint

        # 4. Mutate one flag → fingerprint differs → Tier 2 again.
        drifted = plan_checks(_cfg(participates_in_mes=True),
                              approved_plan_store=approved, staging_store=staging)
        assert drifted.tier == 2
        assert drifted.proposal is not None
        assert drifted.plan.plan_fingerprint != first.plan.plan_fingerprint

    def test_record_rejected_only_on_approved_status(self):
        approved = ApprovedPlanStore()
        result = plan_checks(_cfg(), approved_plan_store=approved)
        # proposal is still "pending" — confirm must refuse to record.
        with pytest.raises(Exception):
            confirm_approved_plan(approved, result.plan, result.proposal)
        assert approved.get(result.plan.client_id) is None

    def test_no_store_treats_every_plan_as_first(self):
        # Without an approved-plan store there is no prior → always Tier 2.
        result = plan_checks(_cfg())
        assert result.tier == 2


# ---------------------------------------------------------------------------
# Fingerprint determinism + composition
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_fingerprint_is_sha256_prefixed(self):
        result = plan_checks(_cfg())
        assert result.plan.plan_fingerprint.startswith("sha256:")

    def test_fingerprint_is_order_independent_over_check_ids(self):
        flags = {f: False for f in SCHEME_FLAGS}
        a = compute_plan_fingerprint(["E1", "E2", "NO_GST_REG"], flags)
        b = compute_plan_fingerprint(["NO_GST_REG", "E2", "E1"], flags)
        assert a == b

    def test_fingerprint_changes_when_a_flag_changes(self):
        flags_off = {f: False for f in SCHEME_FLAGS}
        flags_mes = {**flags_off, "participates_in_mes": True}
        same_ids = ["E1", "E2"]
        assert (compute_plan_fingerprint(same_ids, flags_off)
                != compute_plan_fingerprint(same_ids, flags_mes))

    def test_identical_inputs_produce_identical_fingerprint(self):
        assert plan_checks(_cfg()).plan.plan_fingerprint == plan_checks(_cfg()).plan.plan_fingerprint


# ---------------------------------------------------------------------------
# Import-scan / layering purity
# ---------------------------------------------------------------------------

class TestPurity:
    def test_planner_lives_in_agent_package(self):
        assert (_REPO_ROOT / "agent" / "planner.py").is_file()

    def test_orchestrator_does_not_import_planner_or_agent(self):
        orch = _REPO_ROOT / "orchestrator"
        src = "\n".join(
            f.read_text(encoding="utf-8") for f in sorted(orch.rglob("*.py"))
        )
        assert "agent.planner" not in src and "from agent" not in src and \
            "import agent" not in src, (
            "orchestrator/ must not import agent/ (layer-separation invariant)."
        )

    def test_planner_does_not_import_anthropic_or_sap(self):
        src = (_REPO_ROOT / "agent" / "planner.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        joined = " ".join(imported)
        assert "anthropic" not in joined, "planner must not import anthropic (hermetic)."
        assert "requests" not in joined and "httpx" not in joined, (
            "planner must not import a network client (hermetic)."
        )
