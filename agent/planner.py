"""agent/planner.py — T5.4 check planner: routing over the FIXED v1 registry.

The planner SELECTS the applicable subset of CheckSpec entries for a client from
the frozen v1 registry (agent/registry.CHECK_REGISTRY). It is ROUTING, not
invention: the output is ALWAYS a subset of the registry's check_ids and the
planner can never compose new check logic or emit a check_id the registry does
not define.

Applicability (the gate)
------------------------
A CheckSpec is in-plan iff every name in its ``config_keys`` is a T2.18 scheme
flag that is True on the client profile. Empty ``config_keys`` (the default, and
the case for all 14 current checks) == the check ALWAYS applies. The four flags
are the frozen T2.18 ClientConfig scheme-status booleans (see SCHEME_FLAGS).
This is an applicability gate, NOT report-layer routing (the exempt Template-4/5
split stays in report/routing.py).

Tier model (re-approval discipline)
-----------------------------------
Each plan has a ``plan_fingerprint`` = sha256 over (sorted applicable check_ids +
the four flag values), via the shared public ``compute_inputs_hash`` primitive.
The fingerprint is compared to the prior HUMAN-APPROVED plan for the client
(ApprovedPlanStore, keyed by client_id):

  * no prior approved plan, OR fingerprint differs  -> Tier 2: a PENDING
    ProposalArtifact is built (and staged, if a StagingStore is supplied) for
    human approval. The plan is recorded only on approval (confirm_approved_plan).
  * fingerprint matches the prior approved plan      -> Tier 1: no proposal.

The agent itself never calls ``propose_action`` (an unbacked tool). This module
is plain Python — the same relay-only staging pattern as agent/loop.py and
agent/executor.py.

Hermetic: pure stdlib + intra-agent imports. No anthropic, no SAP, no network.
Status: built + hermetically unit-tested; NOT live/real-client validated (T2.11
gates customer-facing claims). The frozen T2.18 flags and v1 CheckSpec are
untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from agent.proposals import build_proposal, compute_inputs_hash
from agent.registry import CHECK_REGISTRY
from agent.schemas import CheckSpec, ProposalArtifact

# The four T2.18 scheme-status flags a CheckSpec.config_keys may gate on. These
# are the contract field names on config.loader.ClientConfig; the registry's
# config_keys entries are drawn from exactly this set.
SCHEME_FLAGS: tuple[str, ...] = (
    "actively_makes_exempt_supplies",
    "participates_in_mes",
    "participates_in_igds",
    "reverse_charge_applicable",
)

# Action string carried on the Tier-2 proposal so the approval/executor layer can
# route it. The planner never executes the action itself.
PLAN_PROPOSAL_ACTION = "approve_check_plan"


class PlannerError(RuntimeError):
    """Raised when a planner invariant is violated (e.g. a non-registry emit)."""


@dataclass(frozen=True)
class CheckPlan:
    """The applicable subset of registry checks selected for one client/period.

    Attributes:
        client_id:        ClientConfig.client_id this plan was routed for.
        period:           Reporting period label (metadata only — NOT part of the
                          fingerprint, so re-running the same checks in a new
                          period does not force re-approval).
        check_ids:        Applicable check_ids in REGISTRY order, for execution.
                          Provably a subset of the active registry's check_ids.
        plan_fingerprint: "sha256:..." over (sorted check_ids + the four flags) —
                          the re-approval identity of the plan.
    """
    client_id: str
    period: str
    check_ids: tuple[str, ...]
    plan_fingerprint: str


@dataclass(frozen=True)
class PlanResult:
    """The outcome of plan_checks: the plan plus its tier disposition.

    Attributes:
        plan:     The routed CheckPlan.
        tier:     1 if the plan matches the prior approved fingerprint; 2 if this
                  is a first or drifted plan requiring human approval.
        proposal: The PENDING ProposalArtifact when tier == 2, else None.
    """
    plan: CheckPlan
    tier: int
    proposal: Optional[ProposalArtifact]


class ApprovedPlanStore:
    """In-memory record of the last human-approved plan fingerprint per client.

    Keyed by client_id (the tier-escalation compare is per-client). Mirrors the
    CLI-first, in-memory StagingStore pattern. Extract to agent/plan_store.py only
    if this later gains persistence or a second consumer.
    """

    def __init__(self) -> None:
        self._by_client: dict[str, str] = {}

    def get(self, client_id: str) -> Optional[str]:
        """Return the last approved plan_fingerprint for client_id, or None."""
        return self._by_client.get(client_id)

    def record(self, client_id: str, fingerprint: str) -> None:
        """Record (overwrite) the approved plan_fingerprint for client_id."""
        self._by_client[client_id] = fingerprint


def _flag_values(client_config) -> dict[str, bool]:
    """The four T2.18 flags read off the client profile, coerced to bool.

    getattr with a False default keeps the planner robust to a malformed config
    that omits a flag attribute (the flag reads as False == check not admitted).
    """
    return {name: bool(getattr(client_config, name, False)) for name in SCHEME_FLAGS}


def _satisfied_flags(flag_values: Mapping[str, bool]) -> set[str]:
    """The set of flag NAMES that are True — the universe a config_keys gate
    must be a subset of to admit a check."""
    return {name for name, on in flag_values.items() if on}


def _is_applicable(spec: CheckSpec, satisfied: set[str]) -> bool:
    """A check is in-plan iff its config_keys ⊆ the satisfied flags.

    Empty config_keys -> empty set ⊆ anything -> always applies.
    """
    return set(spec.config_keys) <= satisfied


def compute_plan_fingerprint(check_ids, flag_values: Mapping[str, bool]) -> str:
    """Return the re-approval fingerprint for a plan.

    sha256(canonical_json({sorted check_ids, flag values})) via the shared public
    anchoring primitive (agent.proposals.compute_inputs_hash). Sorting the
    check_ids makes the identity order-independent; including the four flag values
    makes any profile change (even one that does not alter the applicable set)
    drift the fingerprint and force re-approval.
    """
    return compute_inputs_hash({
        "check_ids": sorted(check_ids),
        "config": {name: bool(flag_values.get(name, False)) for name in SCHEME_FLAGS},
    })


def _assert_subset(check_ids, registry: Mapping[str, CheckSpec]) -> None:
    """Hard ⊆-registry invariant: the planner can NEVER emit a non-registry id."""
    extraneous = [cid for cid in check_ids if cid not in registry]
    if extraneous:
        raise PlannerError(
            f"planner emitted non-registry check_ids {extraneous!r} — "
            "output must be a subset of the registry"
        )


def plan_checks(
    client_config,
    *,
    period: str = "",
    registry: Optional[Mapping[str, CheckSpec]] = None,
    approved_plan_store: Optional[ApprovedPlanStore] = None,
    staging_store=None,
) -> PlanResult:
    """Route the applicable registry checks for a client and assign a tier.

    The only applicability input is ``client_config`` (the four T2.18 flags);
    run-state coupling is deliberately omitted until a check actually needs it.
    The remaining keyword-only parameters are mechanism, not applicability:

    Args:
        client_config:       Client profile carrying the T2.18 scheme flags and
                             client_id. Missing flag attributes read as False.
        period:              Reporting-period label for the CheckPlan (metadata).
        registry:            Registry to route over; defaults to the frozen v1
                             CHECK_REGISTRY. A test seam — output is asserted ⊆
                             whichever registry is active.
        approved_plan_store: Prior-approved-plan lookup for the tier compare. When
                             None, there is no prior, so every plan is Tier 2.
        staging_store:       If supplied, a Tier-2 proposal is staged (PENDING).

    Returns:
        PlanResult(plan, tier, proposal). proposal is set iff tier == 2.
    """
    reg = CHECK_REGISTRY if registry is None else registry
    flag_values = _flag_values(client_config)
    satisfied = _satisfied_flags(flag_values)

    # Routing: the applicable subset, in REGISTRY order (deterministic execution).
    check_ids = tuple(
        cid for cid, spec in reg.items() if _is_applicable(spec, satisfied)
    )
    _assert_subset(check_ids, reg)

    fingerprint = compute_plan_fingerprint(check_ids, flag_values)
    client_id = getattr(client_config, "client_id", "") or ""
    plan = CheckPlan(
        client_id=client_id,
        period=period,
        check_ids=check_ids,
        plan_fingerprint=fingerprint,
    )

    prior = approved_plan_store.get(client_id) if approved_plan_store is not None else None
    if prior is not None and prior == fingerprint:
        return PlanResult(plan=plan, tier=1, proposal=None)

    # First plan or drift -> Tier-2 proposal (relay-only; the model cannot call
    # propose_action). evidence_refs/justification must be non-empty.
    if prior is None:
        reason = f"first check plan for client {client_id!r}"
    else:
        reason = f"check plan drift for client {client_id!r} (fingerprint changed)"
    evidence_refs = [f"check:{cid}" for cid in check_ids] or [f"client:{client_id}"]
    proposal = build_proposal(
        action=PLAN_PROPOSAL_ACTION,
        justification=(
            f"{reason}: {len(check_ids)} applicable check(s) selected from the "
            f"v1 registry. Human approval anchors the plan fingerprint."
        ),
        evidence_refs=evidence_refs,
        inputs={
            "client_id": client_id,
            "period": period,
            "check_ids": sorted(check_ids),
            "config": flag_values,
            "plan_fingerprint": fingerprint,
        },
    )
    if staging_store is not None:
        staging_store.stage(proposal)
    return PlanResult(plan=plan, tier=2, proposal=proposal)


def confirm_approved_plan(
    approved_plan_store: ApprovedPlanStore,
    plan: CheckPlan,
    proposal: ProposalArtifact,
) -> None:
    """Record a plan as approved — ONLY after its proposal is human-approved.

    Decision (T5.4): the approved plan is recorded on human approval of the
    Tier-2 proposal, never on generation. Raises PlannerError if the proposal is
    not in "approved" status.
    """
    if proposal.status != "approved":
        raise PlannerError(
            f"cannot record plan for client {plan.client_id!r}: proposal status "
            f"is {proposal.status!r}, expected 'approved'"
        )
    approved_plan_store.record(plan.client_id, plan.plan_fingerprint)
