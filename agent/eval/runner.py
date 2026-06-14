"""
agent/eval/runner.py — Replay a scenario through the REAL cage and record responses.

The runner builds the real cage exactly as production does — ``build_options``
wired with the Slice-1 in-process engine server — then sources the scripted agent
stream from a ``FakeTransport`` and drives the actual PreToolUse/PostToolUse hooks
(registry tier check + justification gate + ledger + audit_log). Human-approved
Tier-2 executions are run through the real ``Executor`` + ``make_tier2_handlers``.

Every cage response is recorded as plain data (allow/deny, ledger writes, audit_log
writes, executor outcomes) for the metrics layer to score.

The harness is HOOKS-ONLY: it never calls query()/ClaudeSDKClient and never invokes
the engine chain. The engine invoker is bound to a tripwire that raises if ever
called, proving the eval measures the gate, not a live pipeline.

Hermetic: FakeTransport only, no live model, no SAP, no subprocess, no tokens.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from agent.budget import RunBudget
from agent.eval.scenario import Scenario
from agent.eval.transport import FakeTransport, scenario_to_stream
from agent.executor import Executor, ExecutorError, make_tier2_handlers
from agent.harness import build_options
from agent.ledger import Ledger
from agent.proposals import build_proposal, StagingStore
from agent.registry import get_tier


@dataclass
class AttemptResult:
    """The cage's recorded response to one scripted agent tool-call attempt."""
    tool_name: str
    tool_input: dict
    justification: Optional[str]
    tier: int
    decision: str               # "allow" | "deny"
    reason: Optional[str]
    produced_ledger_entry: bool
    produced_audit_entry: bool
    note: str = ""


@dataclass
class ExecutionRecord:
    """The outcome of one human-approved Tier-2 executor dispatch."""
    action: str
    success: bool
    detail: Optional[str]
    error: Optional[str]
    note: str = ""


@dataclass
class RunRecord:
    """Everything the harness observed for one scenario run."""
    scenario_name: str
    attempts: list[AttemptResult] = field(default_factory=list)
    executions: list[ExecutionRecord] = field(default_factory=list)
    ledger: Ledger = field(default_factory=Ledger)
    audit_log: list[dict] = field(default_factory=list)
    transport: Optional[FakeTransport] = None
    transport_spawned_binary: bool = False


def _never_invoke_engine() -> Any:  # pragma: no cover - tripwire, must never run
    raise AssertionError(
        "engine chain invoked during eval — the harness is hooks-only and must "
        "never run the live review pipeline (no tokens, no chain execution)."
    )


def _pre_event(tool_name: str, tool_input: dict, tool_use_id: str) -> dict[str, Any]:
    """Build a minimal PreToolUseHookInput dict (matches the SDK hook contract)."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": tool_use_id,
        "session_id": "eval-session",
        "transcript_path": "/eval/transcript.jsonl",
        "cwd": "/eval",
    }


def _post_event(tool_name: str, tool_input: dict, tool_use_id: str) -> dict[str, Any]:
    """Build a minimal PostToolUseHookInput dict."""
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": {"ok": True, "eval": True},
        "tool_use_id": tool_use_id,
        "session_id": "eval-session",
        "transcript_path": "/eval/transcript.jsonl",
        "cwd": "/eval",
    }


def _extract_cage(options: Any) -> tuple[Any, Any, list[dict]]:
    """Recover the real (pre_cb, post_cb, audit_log) from build_options' output.

    build_options assembles the hooks internally (via agent.hooks.make_hooks) and
    does not surface the audit_log in its return, but make_hooks attaches the
    audit_log to the PostToolUse callback as a PUBLIC ``.audit_log`` handle. We
    read it off that handle — no closure introspection. Driving these callbacks is
    precisely "the actual PreToolUse/PostToolUse path" the harness must exercise.
    """
    pre_cb = options.hooks["PreToolUse"][0].hooks[0]
    post_cb = options.hooks["PostToolUse"][0].hooks[0]
    audit_log: list[dict] = post_cb.audit_log
    return pre_cb, post_cb, audit_log


async def _replay_attempts(
    scenario: Scenario,
    pre_cb: Any,
    post_cb: Any,
    ledger: Ledger,
    audit_log: list[dict],
    transport: FakeTransport,
) -> list[AttemptResult]:
    """Drive the scripted stream from the FakeTransport through the real hooks."""
    await transport.connect()

    # Map tool_use_id -> the originating Attempt so notes survive the round-trip.
    by_index = list(scenario.attempts)
    results: list[AttemptResult] = []

    idx = 0
    async for message in transport.read_messages():
        for block in message.get("message", {}).get("content", []):
            if block.get("type") != "tool_use":
                continue
            attempt = by_index[idx]
            idx += 1
            tool_name = block["name"]
            tool_input = block["input"]
            tool_use_id = block["id"]

            tier = get_tier(tool_name)
            ledger_before = len(ledger.entries)

            pre_out = await pre_cb(
                _pre_event(tool_name, tool_input, tool_use_id), tool_use_id, {},
            )
            decision = pre_out["hookSpecificOutput"]["permissionDecision"]
            reason = pre_out["hookSpecificOutput"].get("permissionDecisionReason")
            produced_ledger_entry = len(ledger.entries) > ledger_before

            produced_audit_entry = False
            if decision == "allow":
                audit_before = len(audit_log)
                await post_cb(
                    _post_event(tool_name, tool_input, tool_use_id), tool_use_id, {},
                )
                produced_audit_entry = len(audit_log) > audit_before

            results.append(AttemptResult(
                tool_name=tool_name,
                tool_input=tool_input,
                justification=tool_input.get("justification"),
                tier=int(tier),
                decision=decision,
                reason=reason,
                produced_ledger_entry=produced_ledger_entry,
                produced_audit_entry=produced_audit_entry,
                note=attempt.note,
            ))

    await transport.close()
    return results


def _run_executions(
    scenario: Scenario,
    ledger: Ledger,
) -> list[ExecutionRecord]:
    """Stage → approve → execute each human-approved Tier-2 action via the real executor."""
    if not scenario.approved_executions:
        return []

    store = StagingStore()
    handlers = make_tier2_handlers(
        ledger,
        seal_fn=lambda *, proposal, ledger: "eval://bundle/dir",
        emit_fn=lambda *, proposal, ledger: "eval://bundle/report.pdf",
    )
    executor = Executor(staging_store=store, extra_handlers=handlers)

    records: list[ExecutionRecord] = []
    for ex in scenario.approved_executions:
        proposal = build_proposal(
            action=ex.action,
            justification=ex.justification,
            evidence_refs=ex.evidence_refs,
            inputs=ex.inputs,
        )
        store.stage(proposal)
        store.approve(proposal.proposal_id)  # human approval — never the agent
        try:
            result = executor.execute(proposal.proposal_id)
            records.append(ExecutionRecord(
                action=ex.action, success=result.success,
                detail=result.detail, error=None, note=ex.note,
            ))
        except (ExecutorError, NotImplementedError) as exc:  # pragma: no cover
            records.append(ExecutionRecord(
                action=ex.action, success=False, detail=None,
                error=f"{type(exc).__name__}: {exc}", note=ex.note,
            ))
    return records


def run_scenario(scenario: Scenario, *, max_turns: int = 50) -> RunRecord:
    """Replay *scenario* through the real cage and return a RunRecord.

    Builds the real cage (build_options + the Slice-1 engine server), drives the
    scripted attempts through the actual hooks, runs any human-approved Tier-2
    executions through the executor, and records every response.

    Args:
        scenario:  The scripted scenario to replay.
        max_turns: Budget cap wired into build_options (never reached in replay).

    Returns:
        RunRecord with attempts, executions, the sealed ledger, the unsealed
        audit_log, and the FakeTransport (proving no binary was spawned).
    """
    from agent.engine_tool import make_engine_server  # noqa: PLC0415 - lazy SDK use

    ledger = Ledger()
    budget = RunBudget(max_turns=max_turns, max_cost_usd=0.0)

    # Real cage, with the Slice-1 engine server wired in. The invoker is a
    # tripwire: the hooks-only eval path must never run the live chain.
    engine_server = make_engine_server(_never_invoke_engine)
    options = build_options(
        ledger, budget,
        system_prompt="T5.7a eval harness — hermetic cage measurement.",
        engine_server=engine_server,
    )
    pre_cb, post_cb, audit_log = _extract_cage(options)

    transport = FakeTransport(scenario_to_stream(scenario))

    attempts = asyncio.run(
        _replay_attempts(scenario, pre_cb, post_cb, ledger, audit_log, transport)
    )
    executions = _run_executions(scenario, ledger)

    return RunRecord(
        scenario_name=scenario.name,
        attempts=attempts,
        executions=executions,
        ledger=ledger,
        audit_log=audit_log,
        transport=transport,
        transport_spawned_binary=transport.spawned_binary,
    )
