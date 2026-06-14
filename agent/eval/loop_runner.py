"""
agent/eval/loop_runner.py — Drive the REAL Slice-2 case-file loop hermetically.

The cage-invariant basket (runner.py) measures the GATE over scripted attempts.
The loop-quality metrics (T5.7b) instead need the actual gather→act→verify loop to
RUN and produce dossiers + candidate framing, which the metrics then score. This
module drives ``agent.loop.run_casefile_loop`` over a scripted, hermetic transport.

  * ``ScriptedLoopTransport`` — an AgentTransport (agent.loop.AgentTransport) that
    replays a scripted list of AgentEvents per finding, supporting bounded re-entry
    (turn 1 incomplete → turn 2 complete) via a per-finding queue. It never imports
    or touches the SDK — the loop driver consumes plain AgentEvents, not SDK
    messages — so the loop eval is even more hermetic than the cage eval.
  * ``LoopScenario`` — plain data describing one loop run: the (canned) review
    result, the per-finding scripts, and the hermetic Tier-0 read sources.
  * ``run_loop_scenario`` — build a fresh ledger/budget/store, run the loop, and
    return a ``LoopRunRecord`` carrying the resulting outcomes/dossiers.

Hermetic: no SDK, no live model, no SAP, no subprocess, no tokens.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

from agent.budget import RunBudget
from agent.ledger import Ledger
from agent.loop import (
    AgentEvent,
    CaseFileResult,
    Finding,
    FindingOutcome,
    LoopContext,
    ResultEvent,
    run_casefile_loop,
)
from agent.proposals import StagingStore


class _FakeProvider:
    """Minimal DocumentProvider: doc_num -> path|None (read-only, in-memory)."""

    def __init__(self, mapping: dict | None = None) -> None:
        self._m = dict(mapping or {})

    def get_document(self, doc_num: int):
        return self._m.get(int(doc_num))


class ScriptedLoopTransport:
    """Replays a scripted AgentEvent stream per finding (no SDK, no binary, no tokens).

    Args:
        scripts: finding_id -> list of turns; each turn is a list of AgentEvents.
                 Successive ``stream`` calls for the same finding pop the next turn,
                 supporting bounded re-entry (turn 1 incomplete, turn 2 complete).

    Attributes:
        seen_prompts:   prompts the driver passed in (for inspection).
        spawned_binary: always False — this transport never launches a process.
    """

    #: Class-level invariant mirroring agent.eval.transport.FakeTransport.
    SPAWNS_BINARY: bool = False

    def __init__(self, scripts: dict[str, list[list[AgentEvent]]]) -> None:
        self._queues = {fid: deque(turns) for fid, turns in scripts.items()}
        self.seen_prompts: list[str] = []
        self.spawned_binary: bool = False

    def stream(self, prompt: str, finding: "Finding") -> Iterable[AgentEvent]:
        self.seen_prompts.append(prompt)
        queue = self._queues.get(finding.finding_id)
        if not queue:
            # No script left: an empty turn (no reads, no framing) costing nothing.
            yield ResultEvent(cost_usd=0.0)
            return
        for event in queue.popleft():
            yield event


@dataclass
class LoopScenario:
    """One scripted case-file loop run (plain data).

    Attributes:
        name:               Stable scenario name (used in the scorecard).
        description:        Human-readable description.
        review_result:      The (canned) ReviewResult dict the engine tool returns.
        scripts:            finding_id -> list of turns (each a list of AgentEvents).
        provider_docs:      doc_num -> path for the hermetic document provider.
        vendor_catalog:     card_name -> vendor GST record.
        prior_period_store: key -> prior-period treatment record.
        max_attempts_per_finding / max_turns / max_cost_usd: loop bounds.
    """
    name: str
    description: str
    review_result: dict
    scripts: dict = field(default_factory=dict)
    provider_docs: dict = field(default_factory=dict)
    vendor_catalog: dict = field(default_factory=dict)
    prior_period_store: dict = field(default_factory=dict)
    max_attempts_per_finding: int = 3
    max_turns: int = 50
    max_cost_usd: float = 1.0


@dataclass
class LoopRunRecord:
    """Everything observed for one loop scenario run."""
    scenario_name: str
    result: CaseFileResult
    ledger: Ledger
    store: StagingStore
    transport: ScriptedLoopTransport

    @property
    def outcomes(self) -> list[FindingOutcome]:
        """The per-finding outcomes the loop produced."""
        return self.result.outcomes


def _invoke(review_result: Any):
    """Bind a zero-arg invoke_review returning the canned review result."""
    def _f() -> Any:
        return review_result
    return _f


def run_loop_scenario(scenario: LoopScenario) -> LoopRunRecord:
    """Run the real case-file loop for *scenario* and return a LoopRunRecord.

    Builds a fresh ledger / budget / staging store, drives
    ``agent.loop.run_casefile_loop`` over a ScriptedLoopTransport, and returns the
    resulting outcomes (with their dossiers + candidate framing) for the
    loop-quality metrics to score.
    """
    ledger = Ledger()
    budget = RunBudget(max_turns=scenario.max_turns, max_cost_usd=scenario.max_cost_usd)
    store = StagingStore()
    transport = ScriptedLoopTransport(scenario.scripts)
    ctx = LoopContext(
        provider=_FakeProvider(scenario.provider_docs),
        vendor_catalog=dict(scenario.vendor_catalog),
        prior_period_store=dict(scenario.prior_period_store),
    )
    result = run_casefile_loop(
        invoke_review=_invoke(scenario.review_result),
        transport=transport,
        ctx=ctx,
        ledger=ledger,
        budget=budget,
        store=store,
        max_attempts_per_finding=scenario.max_attempts_per_finding,
    )
    return LoopRunRecord(
        scenario_name=scenario.name,
        result=result,
        ledger=ledger,
        store=store,
        transport=transport,
    )
