"""agent/dispatch_exec.py — T5.9d dispatch-execution: run a routed intent.

The intent router (``agent.intent.dispatch``) returns a ``DispatchResult`` carrying
an intent's tier-classified action SEQUENCE + the registry-read tiers — but it does
NOT execute anything. This module is the EXECUTION layer: ``execute_intent`` takes a
classified intent + explicitly-bound params and actually RUNS the Tier-0 read(s) /
RUN_REVIEW over the FROZEN demo artifacts, returning a serialisable
``ExecutionResult``.

What this is — and is NOT
-------------------------
* PURE + framework-free. Stdlib + ``agent.*`` only. No ``anthropic``, no
  ``streamlit``, no ``fastapi``, no SAP, no network, no ``orchestrator``/``ui``
  import. SAP stays OFF; the engine is the FROZEN mock; no tokens, no live chain.
* NO SURFACE WIRING. The production surface is React (Lane C1); this module is
  surfaced later by the React API's ``POST /command`` (Lane C2), NOT by Streamlit.
  ``ExecutionResult`` is therefore a plain serialisable record (``to_dict`` →
  JSON-able), with NO rendering logic here — C2 returns it unchanged.
* Decoupled from the demo UI BY DESIGN. ``ui/`` is the Streamlit lane and may be
  replaced by React; so this module owns its OWN frozen-artifact loader
  (``load_frozen_artifacts``) and its OWN frozen engine (``FrozenEngine``) rather
  than importing ``ui.artifacts`` / ``ui.engine_seam``. The artifact loader is a
  deliberate ~10-line twin of ``ui.artifacts.load_demo_artifacts`` reading the same
  frozen JSON; ``FrozenEngine`` is a twin of ``ui.engine_seam.MockEngine``.

Execution routes (one per menu intent)
--------------------------------------
* ``SHOW_LEDGER``              → ``read_ledger`` over the frozen justification ledger.
* ``SHOW_PROPOSALS``          → ``read_proposals`` over the frozen staging store
  (rehydrated to ProposalArtifacts so the REAL read tool runs, not a re-projection).
* ``SHOW_PRIOR_ADJUDICATIONS`` → ``read_decision_ledger`` LIST-ALL. The v0 menu gap
  (the intent declares client_id/period, but the decision ledger has NO client field
  — its only axis is the per-finding fingerprint) is honoured by listing ALL
  adjudications and flagging it in ``notes``. NO client/period→fingerprint mapping is
  fabricated (see ``agent/intent.py`` lines documenting the same gap).
* ``RUN_REVIEW``              → invoke the FROZEN engine; return frozen dossiers + an
  F5 summary. No live chain, no SAP. T6.3 Slice 2 also attaches a data-derived facet
  menu (``available_facets``) over the canonical findings and applies optional,
  surface-supplied, VIEW-ONLY filters (validated against the real domain, box-isolated,
  never silently empty) — see ``agent/facets.py`` and ``execute_intent(filters=...)``.

Identity slots are NEVER guessed: a blank ``client_id``/``period`` yields the
router's ``NeedsClarification`` passed straight through (outcome
``needs_clarification``), never a fabricated default.

Status: built + hermetically unit-tested over frozen artifacts; surfaced at C2;
NOT live / accuracy validated (T2.11 gates customer-facing claims).
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from agent.decision_ledger import DecisionLedger
from agent.facets import (
    NotInDomain,
    apply_filters,
    compute_facets,
    finding_facet_specs,
)
from agent.intent import DispatchResult, NeedsClarification, dispatch
from agent.proposals import StagingStore
from agent.read_tools import read_decision_ledger, read_ledger, read_proposals
from agent.schemas import ProposalArtifact

# Frozen demo artifacts produced once by tests/fixtures/demo_artifacts_builder.py.
# Owned here (not imported from ui/) so dispatch-execution stays decoupled from the
# Streamlit lane — see module docstring.
DEMO_ARTIFACTS_DIR: Path = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "demo-artifacts"
)

# ExecutionResult.outcome values.
OUTCOME_EXECUTED: str = "executed"
OUTCOME_NEEDS_CLARIFICATION: str = "needs_clarification"

# T6.3 Slice 2 — filter_rejection.reason values. A filter rejection is NEVER an
# exception and NEVER a silent empty set: the underlying review/read still stands
# (its full, unfiltered rows + F5 boxes), and the rejection carries enough to
# re-prompt against the REAL options (the ⊆-menu twin of NeedsClarification).
FILTER_NOT_IN_DOMAIN: str = "not_in_domain"
FILTER_UNKNOWN_FACET: str = "unknown_facet"
FILTER_UNSUPPORTED_INTENT: str = "unsupported_intent"

# The honest, code-visible flag for the SHOW_PRIOR_ADJUDICATIONS menu gap.
_MENU_GAP_NOTE: str = (
    "SHOW_PRIOR_ADJUDICATIONS menu gap (v0/PROVISIONAL): the decision ledger has no "
    "client field — its only query axis is the per-finding fingerprint — so the bound "
    "client_id/period do NOT filter it. Executed as LIST-ALL (every adjudication, "
    "oldest first); no client/period->fingerprint mapping is fabricated. See "
    "agent/intent.py."
)


@dataclass(frozen=True)
class FrozenArtifacts:
    """The frozen artifact surfaces ``execute_intent`` runs its reads over.

    A Lane-A-owned twin of ``ui.artifacts.DemoArtifacts`` (same frozen JSON), kept
    here so this module needs no ``ui`` import. ``decision_ledger`` holds the seeded
    prior-period adjudications (empty when no fixture is present).
    """
    review_result: dict
    dossiers: list[dict]
    proposals: list[dict]
    ledger: list[dict]
    decision_ledger: list[dict] = field(default_factory=list)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_frozen_artifacts(
    artifacts_dir: Path | str = DEMO_ARTIFACTS_DIR,
) -> FrozenArtifacts:
    """Load the frozen review_result / dossiers / proposals / ledger / decision-ledger."""
    d = Path(artifacts_dir)
    return FrozenArtifacts(
        review_result=_read_json(d / "review_result.json", {}),
        dossiers=_read_json(d / "dossiers.json", []),
        proposals=_read_json(d / "proposals.json", []),
        ledger=_read_json(d / "ledger.json", []),
        decision_ledger=_read_json(d / "decision-ledger.json", []),
    )


class FrozenEngine:
    """Frozen mock engine for RUN_REVIEW: returns the frozen ReviewResult verbatim.

    A Lane-A-owned twin of ``ui.engine_seam.MockEngine`` — no SAP, no model, no
    tokens, no live chain. Kept here (not imported from ``ui``) so dispatch-execution
    stays decoupled from the Streamlit lane; this module is surfaced at C2/React.
    """

    name = "frozen"

    def __init__(self, review_result: dict) -> None:
        self._review_result = review_result

    def review(
        self, client_config: Any = None, period: Any = None, inputs: Any = None
    ) -> dict:
        """Return the frozen ReviewResult dict. Arguments are ignored (mock)."""
        return self._review_result


@dataclass(frozen=True)
class ExecutionResult:
    """A serialisable record of one executed (or clarification-needing) intent.

    No rendering logic: C2 (the React API) returns ``to_dict()`` as JSON unchanged.

    Attributes:
        intent:   The menu intent executed (or the one needing clarification).
        outcome:  ``OUTCOME_EXECUTED`` or ``OUTCOME_NEEDS_CLARIFICATION``.
        sequence: The intent's registry sequence (empty on clarification).
        tiers:    Per-action tiers READ from the registry (empty on clarification).
        params:   The bound params (normalised to a dict).
        data:     Intent-specific structured payload:
                    * SHOW_LEDGER              -> {"ledger": [...]}
                    * SHOW_PROPOSALS          -> {"proposals": [...]}
                    * SHOW_PRIOR_ADJUDICATIONS -> {"adjudications": [...]}
                    * RUN_REVIEW              -> {"review_result", "dossiers",
                                                  "f5_summary", "available_facets",
                                                  "findings", "remaining_facets",
                                                  "applied_filters",
                                                  "filter_rejection"}
                    * needs_clarification     -> {"missing_params": [...],
                                                  "message": str}
                  A non-findings intent given a (non-empty) ``filters`` arg also
                  carries a ``filter_rejection`` (unsupported-intent) in ``data``;
                  its rows stay unfiltered. ``filter_rejection`` is ``None`` when no
                  filter was rejected. See T6.3 Slice 2.
        notes:    Honest flags (e.g. the SHOW_PRIOR_ADJUDICATIONS menu-gap note).
    """
    intent: str
    outcome: str
    sequence: tuple[str, ...]
    tiers: tuple[int, ...]
    params: dict
    data: dict
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Return a plain-dict view (JSON-serialisable; tuples become lists)."""
        return asdict(self)


def _f5_summary(review_result: dict) -> dict:
    """Project the F5 box totals + gate results out of a ReviewResult (read-only).

    The F5 boxes live at ``compile_output.calculate.boxes``; the deterministic gate
    results at top-level ``gate_results``. NOTHING is recomputed — this only reads.
    """
    compile_output = (review_result or {}).get("compile_output") or {}
    calculate = compile_output.get("calculate") or {}
    return {
        "boxes": calculate.get("boxes") or {},
        "gate_results": review_result.get("gate_results") or {},
        "status": review_result.get("status"),
    }


def _build_staging_store(proposals: list[dict]) -> StagingStore:
    """Rehydrate a StagingStore of ProposalArtifacts from frozen proposal dicts.

    ``read_proposals`` reads a LIVE StagingStore and projects each ProposalArtifact
    to a dict view; the frozen artifact is that serialised view. We rehydrate it so
    the REAL read tool runs over a real store — rather than re-deriving its
    projection by hand (which would no longer be "running the read"). Pure: builds a
    fresh store, never touches the frozen list.
    """
    store = StagingStore()
    for p in proposals:
        store.stage(
            ProposalArtifact(
                proposal_id=p["proposal_id"],
                action=p["action"],
                tier=p["tier"],
                justification=p["justification"],
                evidence_refs=list(p.get("evidence_refs") or []),
                inputs_hash=p["inputs_hash"],
                status=p["status"],
                created_at=p["created_at"],
            )
        )
    return store


def _unsupported_intent_rejection(intent: str, filters: Mapping[str, Any]) -> dict:
    """Structured rejection for a `filters` arg on a non-findings intent.

    Explicit, not silently ignored: the underlying read still returns its rows
    unfiltered (findings facets are the only facetable collection this slice).
    """
    return {
        "reason": FILTER_UNSUPPORTED_INTENT,
        "requested_filters": dict(filters),
        "message": (
            f"filters are not supported for intent {intent!r} in this slice "
            "(findings facets only); the underlying read returned its rows "
            "unfiltered."
        ),
    }


def _findings_view(
    full_findings: list, filters: Mapping[str, Any]
) -> tuple[list, dict, dict, dict, Optional[dict]]:
    """The pure, view-only filter step over the canonical findings.

    Computes the full filter menu over *full_findings*, then — only when *filters*
    is non-empty — validates and narrows. Returns
    ``(view_rows, available_facets, remaining_facets, applied_filters, rejection)``:

    * ``available_facets`` — the full menu (domains + counts) over the FULL findings,
      whether or not a filter was passed.
    * No filter        → ``view_rows`` = the full findings; ``remaining`` = the full
      menu; ``applied`` = ``{}``; ``rejection`` = ``None``.
    * Valid filter     → ``view_rows`` = the narrowed subset; ``remaining`` recomputed
      over the subset; ``applied`` = the echoed filters; ``rejection`` = ``None``.
    * Invalid VALUE    → the full (unfiltered) findings still stand; ``applied`` =
      ``{}``; ``rejection`` carries the facet, bad value + the REAL domain.
    * Unknown facet NAME → the full findings still stand; ``rejection`` carries the
      requested filters + the real available facet names (NEVER an exception to the
      surface — the dispatch seam turns the engine's ValueError into a structured
      rejection).

    PURE / VIEW-ONLY: reads the findings, recomputes no finding and no F5 box.
    """
    specs = finding_facet_specs()
    available = compute_facets(full_findings, specs)
    if not filters:
        return full_findings, available, available, {}, None

    try:
        result = apply_filters(full_findings, filters, specs)
    except ValueError:  # an undeclared facet NAME — caller used a non-facetable field
        rejection = {
            "reason": FILTER_UNKNOWN_FACET,
            "requested_filters": dict(filters),
            "available_facets": sorted(available),
            "message": (
                "one or more filter facets are not facetable for findings; "
                f"available facets: {sorted(available)}."
            ),
        }
        return full_findings, available, available, {}, rejection

    if isinstance(result, NotInDomain):
        rejection = {
            "reason": FILTER_NOT_IN_DOMAIN,
            "facet": result.facet_name,
            "value": result.value,
            "domain": list(result.domain),
            "requested_filters": dict(filters),
            "message": (
                f"value {result.value!r} is not in the {result.facet_name!r} "
                f"domain; real values: {list(result.domain)}."
            ),
        }
        return full_findings, available, available, {}, rejection

    narrowed, remaining = result
    return narrowed, available, remaining, dict(filters), None


def execute_intent(
    intent: str,
    params: Mapping[str, str],
    *,
    artifacts: FrozenArtifacts,
    engine: Optional[Any] = None,
    filters: Optional[Mapping[str, Any]] = None,
) -> ExecutionResult:
    """Route an intent + bound params, then EXECUTE its reads over frozen artifacts.

    Routing is delegated to ``agent.intent.dispatch`` (so the ⊆-MENU invariant and
    the never-guess identity contract are reused verbatim):

      * a non-menu intent raises ``IntentError`` (from ``dispatch``);
      * a missing/blank required param yields ``NeedsClarification`` -> returned as
        an ExecutionResult with outcome ``needs_clarification`` (execution skipped);
      * otherwise the intent's reads run and a fully-populated ExecutionResult is
        returned with outcome ``executed``.

    Args:
        intent:    A menu intent key (e.g. "SHOW_LEDGER").
        params:    Explicitly-bound params; identity slots are never guessed.
        artifacts: The frozen artifact surfaces to read over.
        engine:    Optional engine for RUN_REVIEW (anything with ``review(...)``);
                   defaults to a ``FrozenEngine`` over ``artifacts.review_result``.
        filters:   Optional, surface-supplied findings facet filters
                   (``{facet_name: value | [values]}``). A VIEW parameter — NOT
                   identity, NOT classifier-extracted. RUN_REVIEW always runs the
                   full (box-isolated) review FIRST, then narrows only the returned
                   findings view; an invalid value or non-findings intent yields a
                   structured filter rejection (never a silent empty, never an
                   exception) while the full rows + F5 boxes still stand. Findings
                   only this slice (proposals / ledger facets are deferred).

    Raises:
        IntentError: if ``intent`` is not in INTENT_MENU (propagated from dispatch).
        NotImplementedError: if a menu intent has no executor here (a guard for
            future menu growth — should be unreachable for the v0 menu).
    """
    filters = dict(filters or {})  # a VIEW parameter; empty by default
    routed = dispatch(intent, params)  # raises IntentError for a non-menu intent

    if isinstance(routed, NeedsClarification):
        return ExecutionResult(
            intent=routed.intent,
            outcome=OUTCOME_NEEDS_CLARIFICATION,
            sequence=(),
            tiers=(),
            params=dict(params),
            data={
                "missing_params": list(routed.missing_params),
                "message": routed.message,
            },
        )

    assert isinstance(routed, DispatchResult)  # the only other dispatch outcome

    notes: tuple[str, ...] = ()
    if routed.intent == "SHOW_LEDGER":
        data: dict = {"ledger": read_ledger(artifacts.ledger)}
    elif routed.intent == "SHOW_PROPOSALS":
        store = _build_staging_store(artifacts.proposals)
        data = {"proposals": read_proposals(store)}
    elif routed.intent == "SHOW_PRIOR_ADJUDICATIONS":
        decision_ledger = DecisionLedger.from_entries(artifacts.decision_ledger)
        # Menu gap: list-all (fingerprint=None); the bound params do not filter.
        data = {"adjudications": read_decision_ledger(decision_ledger, fingerprint=None)}
        notes = (_MENU_GAP_NOTE,)
    elif routed.intent == "RUN_REVIEW":
        eng = engine if engine is not None else FrozenEngine(artifacts.review_result)
        # Deep-copy so the returned payload is ISOLATED from the frozen source — a
        # caller mutating it can never bleed back into the F5 boxes / gate results.
        # The FULL review runs (box-isolated) BEFORE the view step; the F5 summary is
        # computed here, once, over the full result and is NEVER touched by filtering.
        review_result = copy.deepcopy(eng.review())
        full_findings = copy.deepcopy(artifacts.dossiers)
        f5_summary = _f5_summary(review_result)
        # Separated, pure VIEW step over the findings ONLY — recomputes no box.
        view_rows, available, remaining, applied, rejection = _findings_view(
            full_findings, filters
        )
        data = {
            "review_result": review_result,
            "dossiers": full_findings,          # the full canonical findings (unchanged)
            "f5_summary": f5_summary,
            "available_facets": available,      # the full filter menu (always)
            "findings": view_rows,              # the VIEW rows (narrowed when filtered)
            "remaining_facets": remaining,      # recomputed over the view
            "applied_filters": applied,         # echo ({} when none / rejected)
            "filter_rejection": rejection,      # None unless a filter was rejected
        }
    else:  # pragma: no cover - dispatch guarantees a known menu intent
        raise NotImplementedError(
            f"intent {routed.intent!r} is in INTENT_MENU but has no executor in "
            "agent/dispatch_exec.py — add one when the menu grows"
        )

    # Non-findings intents do not support facet filters this slice: surface a
    # structured rejection (explicit, not silently ignored) while the underlying
    # read's rows above still stand, unfiltered.
    if filters and routed.intent != "RUN_REVIEW":
        data["filter_rejection"] = _unsupported_intent_rejection(routed.intent, filters)

    return ExecutionResult(
        intent=routed.intent,
        outcome=OUTCOME_EXECUTED,
        sequence=routed.sequence,
        tiers=routed.tiers,
        params=routed.params,
        data=data,
        notes=notes,
    )
