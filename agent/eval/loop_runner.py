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
    ToolUseEvent,
    run_casefile_loop,
)
from agent.proposals import StagingStore
from agent.read_tools import (
    get_source_document,
    read_prior_period_treatment,
    read_vendor_gst_status,
)
from agent.read_tools_server import canonical_slot, qualified_read_name
from agent.schemas import Tier


class _FakeProvider:
    """Minimal DocumentProvider: doc_num -> path|None (read-only, in-memory)."""

    def __init__(self, mapping: dict | None = None) -> None:
        self._m = dict(mapping or {})

    def get_document(self, doc_num: int):
        return self._m.get(int(doc_num))


def _apply_scripted_read(event: ToolUseEvent, finding: Finding, ctx: LoopContext,
                         sink: dict, ledger: Ledger) -> None:
    """Execute a scripted Tier-0 read against *ctx* and write it into *sink*.

    Hermetic simulation of architecture A: the live path's MCP read handler executes
    the read via ctx and writes the sink in-turn; here the fake does the same against
    the same ``read_tools`` functions. Per constraint B the fake also writes the Tier-0
    read ledger entry (the SDK PreToolUse hook does this on the live path); the loop
    driver writes none for reads.
    """
    name = event.tool_name
    ti = event.tool_input
    payload = finding.payload or {}
    if name == "get_source_document":
        value: Any = get_source_document(ctx.provider, int(ti.get("doc_num", payload.get("doc_num"))))
    elif name == "read_vendor_gst_status":
        value = read_vendor_gst_status(ctx.vendor_catalog, ti.get("card_name", payload.get("card_name")))
    elif name == "read_prior_period_treatment":
        key = ti.get("key") or f"{finding.check_id}:{payload.get('card_name')}"
        value = read_prior_period_treatment(ctx.prior_period_store, key)
    else:
        value = None
    # T5.3g: the slot is CODE-DEFINED (canonical_slot), resolved on the BARE name.
    sink[canonical_slot(name)] = value
    # T5.7b: ledger the read under the LIVE namespaced name (the SDK hook records the
    # mcp__reads__<tool> form); slot binding above still uses the bare name.
    ledger.append(
        tool_name=qualified_read_name(name), tier=Tier.ZERO, justification=None,
        call_params={k: v for k, v in ti.items() if k != "justification"},
        outcome="allowed", blocked_reason=None,
    )


class ScriptedLoopTransport:
    """Gathers scripted evidence into the sink per finding (no SDK, no binary, no tokens).

    Architecture A (T5.3f): each scripted turn lists the reads the model performs (as
    ``ToolUseEvent``s) plus its ``FramingEvent``/``ResultEvent``. ``gather`` EXECUTES the
    scripted reads against the bound ctx and writes the results into the driver's
    ``evidence_sink`` (mirroring the live MCP handlers), ledgers them Tier-0, and yields
    only the framing + cost. A scripted ``propose_action`` is IGNORED — staging is now
    driver-decided. Successive ``gather`` calls for the same finding pop the next turn,
    supporting bounded re-entry.

    Args:
        scripts: finding_id -> list of turns; each turn is a list of AgentEvents.
        ctx:     LoopContext the scripted reads resolve against.
        ledger:  Ledger the fake writes Tier-0 read entries into (constraint B).
    """

    #: Class-level invariant mirroring agent.eval.transport.FakeTransport.
    SPAWNS_BINARY: bool = False

    def __init__(self, scripts: "dict[str, list[list[AgentEvent]]]",
                 ctx: LoopContext, ledger: Ledger) -> None:
        self._queues = {fid: deque(turns) for fid, turns in scripts.items()}
        self._ctx = ctx
        self._ledger = ledger
        self.seen_prompts: list[str] = []
        self.spawned_binary: bool = False

    def gather(self, prompt: str, finding: "Finding", evidence_sink: dict) -> Iterable[AgentEvent]:
        self.seen_prompts.append(prompt)
        queue = self._queues.get(finding.finding_id)
        if not queue:
            # No script left: an empty turn (no reads, no framing) costing nothing.
            yield ResultEvent(cost_usd=0.0)
            return
        for event in queue.popleft():
            if isinstance(event, ToolUseEvent):
                if event.tool_name == "propose_action":
                    continue  # staging is driver-decided now; ignore scripted propose
                _apply_scripted_read(event, finding, self._ctx, evidence_sink, self._ledger)
            else:
                yield event  # FramingEvent / ResultEvent


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
    ctx = LoopContext(
        provider=_FakeProvider(scenario.provider_docs),
        vendor_catalog=dict(scenario.vendor_catalog),
        prior_period_store=dict(scenario.prior_period_store),
    )
    transport = ScriptedLoopTransport(scenario.scripts, ctx, ledger)
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
