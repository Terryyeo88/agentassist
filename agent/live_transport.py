"""
agent/live_transport.py — LiveAgentTransport: the live-model AgentTransport adapter.

This is the live, token-burning ``agent.loop.AgentTransport`` implementation
(architecture A, T5.3f). Per finding, ``gather`` builds the T5.3e MCP reads server
bound to the per-finding ``evidence_sink``, wires it into hook-bearing
``ClaudeAgentOptions`` via ``build_options(reads_server=…)``, and runs ONE
``claude_agent_sdk.query()``. The model calls the read tools IN-TURN; the SDK runs the
handlers, which write the gathered evidence into the sink. ``gather`` yields only
``FramingEvent`` (the candidate framing text) and ``ResultEvent`` (the per-turn COGS);
the reads do NOT come back as events — they are in the sink the DRIVER reads after the
turn. The live counterpart of the hermetic fakes: same contract, different source.

RELAY-ONLY (invoke-never-perform). The adapter only runs the turn and translates the
text/cost out of the stream; it executes no tool itself, seals/emits nothing, and adds
no Tier-2 surface. Reads are gated Tier-0 by the cage hooks (hook-bearing options); the
plain-Python DRIVER disposes (completeness, lint, staging, re-entry).

Opt-in + token-burning. The live path is gated behind the ``AGENT_LIVE_TRANSPORT`` env
var via ``make_live_transport`` so it can never run by accident; the supervised T5.3-V
run sets it. The class is inert until ``gather`` runs a query().

SDK confinement. ``claude_agent_sdk`` is imported only at query time (``_resolve_query``)
and inside ``build_options`` / ``make_read_tools_server`` (both deferred); the
translation logic is pure and SDK-import-free (structural, by message/block type name).
``agent/__init__`` does not import this module, so importing ``agent`` /
``agent.live_transport`` stays SDK-free and the eval hermetic gate is untouched — this
module lives in core, not eval.

Hermetic in tests: ``gather`` calls an injected ``query_fn``; the T5.3c tests pass a
fake async generator of SDK-shaped messages — no live model, no binary, no tokens.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Iterable, List, Optional

from agent.budget import RunBudget
from agent.harness import build_options
from agent.ledger import Ledger
from agent.loop import AgentEvent, Finding, FramingEvent, ResultEvent
from agent.read_tools_server import make_read_tools_server

#: Env var that opts in to the live, token-burning transport. Unless it is exactly
#: "1", ``make_live_transport`` refuses to build one — the live path cannot run by
#: accident. The supervised T5.3-V run sets it explicitly.
LIVE_OPT_IN_ENV: str = "AGENT_LIVE_TRANSPORT"


def _resolve_query() -> Callable[..., Any]:
    """Return the real ``claude_agent_sdk.query`` (deferred import; SDK confined here)."""
    from claude_agent_sdk import query  # noqa: PLC0415 - deferred SDK import (confined)

    return query


# --------------------------------------------------------------------------- #
# Pure translation: SDK message -> loop AgentEvents (no SDK import needed).
# --------------------------------------------------------------------------- #

def _translate(message: Any) -> List[AgentEvent]:
    """Map one SDK message to zero or more loop AgentEvents. Relay-only, pure.

    Recognised by structural type name so this stays SDK-import-free:
      * an assistant message's ``TextBlock``s -> ``FramingEvent`` (candidate framing);
      * a ``ResultMessage`` -> ``ResultEvent`` (``cost_usd`` from ``total_cost_usd``,
        the priceable per-turn COGS field; ``usage`` carried for the audit trail).

    The model's read ``ToolUseBlock``s are NOT translated — the SDK runs the MCP read
    handlers in-turn (they write the evidence_sink), so reads flow through the sink, not
    events. ThinkingBlock / ToolResultBlock / user / system messages are ignored.
    """
    events: List[AgentEvent] = []

    content = getattr(message, "content", None)
    if isinstance(content, list):
        for block in content:
            if type(block).__name__ == "TextBlock":
                events.append(FramingEvent(text=getattr(block, "text", "")))
            # ToolUseBlock (reads) -> handled in-turn by the SDK, written to the sink.
            # ThinkingBlock / ToolResultBlock / ServerTool* -> not loop events.

    if type(message).__name__ == "ResultMessage":
        events.append(ResultEvent(
            cost_usd=float(getattr(message, "total_cost_usd", 0.0) or 0.0),
            usage=dict(getattr(message, "usage", {}) or {}),
        ))

    return events


# --------------------------------------------------------------------------- #
# The adapter
# --------------------------------------------------------------------------- #

class LiveAgentTransport:
    """Drive a real model via ``claude_agent_sdk.query()``, gathering evidence in-turn.

    Implements ``agent.loop.AgentTransport``: ``gather(prompt, finding, evidence_sink)``
    builds the per-finding reads server bound to *evidence_sink*, runs ONE ``query()``
    (the SDK runs the read handlers, filling the sink), and yields ``FramingEvent`` +
    ``ResultEvent`` for that one turn.

    Args:
        ctx:           Run-wide LoopContext the reads resolve against (provider /
                       catalogs). Bound into the per-finding reads server.
        ledger:        Ledger the hook-bearing options write Tier-0 read gate decisions
                       into (the reads are gated by the SDK hooks on this path).
        budget:        RunBudget; ``max_turns`` maps into the options.
        system_prompt: The audit-agent instructions — must tell the model to call the
                       read tools with the finding's doc_num/card_name/key + the
                       evidence_slot (the T5.3e handlers have no finding fallback).
        query_fn:      Injection seam for hermetic testing; defaults to the real
                       ``claude_agent_sdk.query``. Tests pass a fake async generator of
                       SDK-shaped messages, so no token is spent and no binary spawns.
    """

    #: Class-level invariant mirroring the eval transports: the adapter itself never
    #: spawns a binary — ``query()`` / the CLI owns any subprocess.
    SPAWNS_BINARY: bool = False

    def __init__(
        self,
        *,
        ctx: Any,
        ledger: Ledger,
        budget: RunBudget,
        system_prompt: str = "",
        query_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._ctx = ctx
        self._ledger = ledger
        self._budget = budget
        self._system_prompt = system_prompt
        self._query_fn = query_fn  # resolved lazily so the SDK import stays deferred
        self.seen_prompts: List[str] = []

    def gather(
        self, prompt: str, finding: "Finding", evidence_sink: dict
    ) -> Iterable[AgentEvent]:
        """Run one ``query()`` for *finding*, filling *evidence_sink* in-turn.

        Builds the reads server bound to *evidence_sink* and hook-bearing options, runs
        one ``query()`` (the SDK runs the read handlers, which write the sink), and
        yields the turn's ``FramingEvent`` + ``ResultEvent``. One ``gather`` call == one
        loop turn. The async ``query()`` is drained via ``asyncio.run`` (the driver is
        plain sync Python — no enclosing event loop).
        """
        self.seen_prompts.append(prompt)
        reads_server = make_read_tools_server(self._ctx, evidence_sink)
        options = build_options(
            self._ledger, self._budget,
            system_prompt=self._system_prompt, reads_server=reads_server,
        )
        for event in asyncio.run(self._collect(prompt, options)):
            yield event

    async def _collect(self, prompt: str, options: Any) -> List[AgentEvent]:
        """Drive one ``query()`` and collect its translated events (one turn)."""
        query = self._query_fn or _resolve_query()
        events: List[AgentEvent] = []
        saw_result = False
        async for message in query(prompt=prompt, options=options):
            events.extend(_translate(message))
            if type(message).__name__ == "ResultMessage":
                saw_result = True
        if not saw_result:
            # Every turn must advance the budget; if the model produced no
            # ResultMessage, emit a zero-cost, non-blocking ResultEvent so the loop's
            # budget.increment never starves.
            events.append(ResultEvent(cost_usd=0.0))
        return events


def make_live_transport(
    *,
    ctx: Any,
    ledger: Ledger,
    budget: RunBudget,
    system_prompt: str = "",
    query_fn: Optional[Callable[..., Any]] = None,
) -> LiveAgentTransport:
    """Build a ``LiveAgentTransport`` — ONLY when the live opt-in is explicitly set.

    Guards the live, token-burning path behind ``AGENT_LIVE_TRANSPORT=1`` so it can
    never run by accident: the supervised T5.3-V run sets the env var; everything else
    (including CI) leaves it unset and gets a ``RuntimeError``. The translation/wiring
    unit tests construct ``LiveAgentTransport`` directly with an injected ``query_fn``;
    this factory exists to make the LIVE entry point opt-in.

    Raises:
        RuntimeError: if ``AGENT_LIVE_TRANSPORT`` is not exactly "1".
    """
    if os.environ.get(LIVE_OPT_IN_ENV) != "1":
        raise RuntimeError(
            f"Live transport is opt-in: set {LIVE_OPT_IN_ENV}=1 to enable the "
            "token-burning live-model path (used only by the supervised T5.3-V run)."
        )
    return LiveAgentTransport(
        ctx=ctx, ledger=ledger, budget=budget,
        system_prompt=system_prompt, query_fn=query_fn,
    )
