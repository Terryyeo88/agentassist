"""agent/intent.py — T5.9a intent surface: a bounded menu + deterministic dispatch.

The intent surface is the product's front door, and it is Invariant 6 made into a
surface: a FIXED menu of intents (INTENT_MENU), each declaring a tier-classified
action SEQUENCE, plus a deterministic ``dispatch`` that routes a (validated) intent
+ EXPLICITLY-BOUND params to that sequence. "The menu is the cage at the product
layer."

What this is NOT
----------------
This is ROUTING, not authority. Dispatch routes to EXISTING tier-classified
registry actions; it can NEVER grant an out-of-tier capability or emit a non-menu
intent. There is no natural-language classifier here (that is T5.9b) and no chat
UI (T5.9b/c). The menu is v0/PROVISIONAL.

Two structural guarantees (the T5.9 twins of the planner's ⊆-registry)
----------------------------------------------------------------------
* ⊆-MENU, build-time: every action a menu intent declares is a real
  ``agent.registry`` tool, asserted at import (``_assert_menu_well_formed``). A
  menu intent can never name a non-existent / structurally-impossible action.
* ⊆-MENU, dispatch-time: ``dispatch`` asserts ``intent in INTENT_MENU`` and
  rejects anything else with ``IntentError`` — a raw tool name is not an intent.
* NO TIER ESCALATION: ``DispatchResult.tiers`` is READ from ``registry.get_tier``
  per action at dispatch time; the surface never assigns a tier. The product
  surface therefore dispatches only to the Tier-0/1 actions the registry already
  defines — never a Tier-2 effect (that stays behind ``propose_action`` + human
  approval), never a Tier-3 (absent) action.

Identity-bearing slots
----------------------
The surface NEVER guesses ``client_id`` / ``period``. A missing (or blank)
required param yields a structured ``NeedsClarification`` result — never a guessed
default, never a silently-fabricated client. The caller binds params explicitly.

Hermetic: pure stdlib + ``agent.registry`` / ``agent.schemas``. No anthropic, no
SDK, no SAP, no network. Status: built + hermetically unit-tested; NOT live /
accuracy validated (T2.11 gates customer-facing claims).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Union

from agent.registry import get_tier
from agent.schemas import Tier


class IntentError(RuntimeError):
    """Raised when an intent-surface invariant is violated.

    Twin of ``agent.planner.PlannerError``: a non-menu intent (the ⊆-menu
    breach) or a malformed menu raises this rather than dispatching.
    """


@dataclass(frozen=True)
class IntentSpec:
    """One menu intent → its tier-classified action sequence + required params.

    Attributes:
        intent:          The menu key (UPPER_SNAKE). The registry of intents is
                         keyed by this exact string.
        sequence:        Registered tool names, in execution order. EVERY name
                         must be in ``agent.registry.REGISTRY`` (asserted at
                         import) so ``get_tier`` resolves a real tier — the
                         surface invents no action.
        required_params: Identity-bearing slots the caller MUST bind for this
                         intent (e.g. ("client_id", "period")). A miss yields
                         NeedsClarification, never a guessed default.
        description:     One-line human-facing label for the menu entry.
    """
    intent: str
    sequence: tuple[str, ...]
    required_params: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class DispatchResult:
    """A successful route: the intent's sequence + the registry-read tiers.

    Attributes:
        intent:   The dispatched menu intent.
        sequence: The intent's declared registered-tool sequence (verbatim).
        tiers:    int tier per action, READ from ``get_tier`` at dispatch time.
                  The surface never assigns a tier; this mirrors the registry.
        params:   The bound params (the caller's mapping, normalised to a dict).
    """
    intent: str
    sequence: tuple[str, ...]
    tiers: tuple[int, ...]
    params: dict[str, str]


@dataclass(frozen=True)
class NeedsClarification:
    """A structured "ask, don't guess" result for missing required params.

    NOT an exception — a missing identity-bearing slot is an expected outcome of
    the front door, not an error. The surface returns this instead of fabricating
    a client_id / period.

    Attributes:
        intent:         The (valid, menu) intent the caller asked for.
        missing_params: Required params absent or blank, in declared order.
        message:        Human-facing prompt naming the missing slots.
    """
    intent: str
    missing_params: tuple[str, ...]
    message: str


# ---------------------------------------------------------------------------
# INTENT_MENU — the fixed v0/PROVISIONAL product surface
#
# v0/PROVISIONAL: the exact set of intents and their required params is not a
# frozen contract — it is the demo-critical starting menu. Every sequence element
# is a registered Tier-0/1 tool (see _assert_menu_well_formed).
#
# T5.9a1 resolved a conflation: SHOW_PROPOSALS now routes to the dedicated Tier-0
# read_proposals (the pending-proposals queue), NOT read_ledger (the justification
# ledger); SHOW_PRIOR_ADJUDICATIONS now routes to the Tier-0 read_decision_ledger
# (the T5.5 decision ledger of human adjudications), NOT read_prior_period_treatment
# (a per-key prior-period treatment store). All four intents now dispatch honestly.
#
# v0/PROVISIONAL menu gap (flag for the menu owner): SHOW_PRIOR_ADJUDICATIONS still
# declares required_params=("client_id", "period") — the user-facing intent is
# naturally client/period-scoped — but read_decision_ledger's only query axis is the
# per-finding FINGERPRINT (the T5.5 ledger carries no client field). The two do not
# yet reconcile: the bound client_id/period do not map onto a fingerprint. The
# eventual fix is a client/period -> findings -> fingerprints lookup (or an explicit
# fingerprint slot on the intent). Documented here so the mismatch is EXPLICIT, not
# silent; the surface still routes honestly to the correct tool.
# ---------------------------------------------------------------------------

INTENT_MENU_STATUS: str = "v0/PROVISIONAL"

_INTENTS: list[IntentSpec] = [
    IntentSpec(
        intent="RUN_REVIEW",
        sequence=("run_review_chain",),
        required_params=("client_id", "period"),
        description="Run the full deterministic GST review for a client/period.",
    ),
    IntentSpec(
        intent="SHOW_LEDGER",
        sequence=("read_ledger",),
        required_params=("client_id",),
        description="Show the current justification-ledger entries for a client.",
    ),
    IntentSpec(
        intent="SHOW_PROPOSALS",
        sequence=("read_proposals",),
        required_params=("client_id",),
        description="Show the staged Tier-2 proposals awaiting human approval.",
    ),
    IntentSpec(
        intent="SHOW_PRIOR_ADJUDICATIONS",
        sequence=("read_decision_ledger",),
        required_params=("client_id", "period"),
        description="Show how findings were adjudicated in a prior period.",
    ),
]

INTENT_MENU: dict[str, IntentSpec] = {spec.intent: spec for spec in _INTENTS}


def _assert_menu_well_formed(menu: Mapping[str, IntentSpec]) -> None:
    """Build-time ⊆-MENU invariant: every menu action is a real registry tool.

    ``get_tier`` returns ``Tier.THREE`` for any name absent from the registry, so
    asserting ``get_tier(action) is not Tier.THREE`` proves the action exists and
    carries a real tier — the surface can never declare a non-existent or
    structurally-impossible (Tier-3) action. Also asserts the key == the spec's
    own ``intent`` and that no sequence is empty.
    """
    for key, spec in menu.items():
        if spec.intent != key:
            raise IntentError(
                f"menu key {key!r} != spec.intent {spec.intent!r}"
            )
        if not spec.sequence:
            raise IntentError(f"intent {key!r} declares an empty action sequence")
        for action in spec.sequence:
            if get_tier(action) is Tier.THREE:
                raise IntentError(
                    f"intent {key!r} routes to {action!r}, which is not a "
                    "registered tool — the surface may not invent an action"
                )


_assert_menu_well_formed(INTENT_MENU)


def _missing_params(spec: IntentSpec, params: Mapping[str, str]) -> tuple[str, ...]:
    """Required params that are absent or present-but-blank, in declared order.

    A whitespace-only identity slot is NOT a value: dispatching RUN_REVIEW for an
    empty client_id would silently run the review for no client. So blank counts
    as missing and the surface asks rather than guesses.
    """
    missing: list[str] = []
    for name in spec.required_params:
        value = params.get(name)
        if value is None or not str(value).strip():
            missing.append(name)
    return tuple(missing)


def dispatch(
    intent: str, params: Mapping[str, str]
) -> Union[DispatchResult, NeedsClarification]:
    """Route a menu intent + explicitly-bound params to its action sequence.

    Deterministic router. Two outcomes only:

      * required params all bound  -> DispatchResult routing to the intent's
        declared registered-tool sequence, with per-action tiers READ from
        ``get_tier`` (the surface assigns none).
      * a required param missing/blank -> NeedsClarification (ask, never guess).

    Raises:
        IntentError: if ``intent`` is not in INTENT_MENU (the ⊆-MENU invariant —
            a non-menu intent, or a raw tool name, is rejected, never dispatched).
    """
    spec = INTENT_MENU.get(intent)
    if spec is None:
        raise IntentError(
            f"unknown intent {intent!r} — not in INTENT_MENU "
            f"({sorted(INTENT_MENU)}); the surface routes only menu intents"
        )

    missing = _missing_params(spec, params)
    if missing:
        joined = ", ".join(missing)
        return NeedsClarification(
            intent=intent,
            missing_params=missing,
            message=(
                f"{intent} needs {joined} before it can run. Please provide "
                f"{joined} — the surface will not guess an identity-bearing slot."
            ),
        )

    tiers = tuple(int(get_tier(action)) for action in spec.sequence)
    return DispatchResult(
        intent=intent,
        sequence=spec.sequence,
        tiers=tiers,
        params=dict(params),
    )
