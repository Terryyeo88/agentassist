"""
agent/live_transport.py — LiveAgentTransport: the live-model AgentTransport adapter.

This is the live, token-burning ``agent.loop.AgentTransport`` implementation. It
translates a ``claude_agent_sdk.query()`` message stream into the case-file loop's
AgentEvents (``ToolUseEvent`` / ``FramingEvent`` / ``ResultEvent``) so
``run_casefile_loop`` can drive a real model. It is the live counterpart of the
hermetic eval transports (``FakeTransport`` / ``ScriptedLoopTransport``) — the only
difference is the SOURCE of the events (a real SDK stream vs a scripted list).

RELAY-ONLY (invoke-never-perform). The adapter ONLY translates: it executes no
tool, seals or emits nothing, and adds no Tier-2 surface. The DRIVER
(``run_casefile_loop``) plus the cage hooks gate and execute everything; the model's
tool *requests* are surfaced as ``ToolUseEvent``s for the driver to dispose. The
adapter is a translator, not an actor.

Opt-in + token-burning. The live path is gated behind the ``AGENT_LIVE_TRANSPORT``
env var via ``make_live_transport`` so it can never run by accident; the supervised
T5.3-V run sets it. The class itself is inert until ``stream()`` runs a query().

SDK confinement. The ``claude_agent_sdk`` import is DEFERRED to the point of a live
query (``_resolve_query``); the translation logic is pure and SDK-import-free
(structural, by message/block type name). ``agent/__init__`` does not import this
module, so importing ``agent`` stays SDK-free and the eval hermetic gate
(``agent/eval`` source scan) is untouched — this module lives in core, not eval.

Hook-free vs hook-bearing ``ClaudeAgentOptions`` is the CALLER's choice (deferred to
T5.3-V): the adapter passes the injected options through to ``query()`` verbatim.

Hermetic in tests: ``stream()`` calls an injected ``query_fn``; the T5.3c tests pass
a fake async generator of SDK-shaped messages — no live model, no binary, no tokens.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Iterable, List, Optional

from agent.loop import AgentEvent, Finding, FramingEvent, ResultEvent, ToolUseEvent

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
      * an assistant message's ``content`` blocks:
          - ``ToolUseBlock``  -> ``ToolUseEvent`` (name + input passed through verbatim,
            carrying the model's ``justification`` + ``evidence_slot``);
          - ``TextBlock``     -> ``FramingEvent`` (candidate framing text);
          - anything else (``ThinkingBlock`` / ``ToolResultBlock`` / server blocks) is
            ignored — it is not a loop event.
      * a ``ResultMessage`` -> ``ResultEvent`` (``cost_usd`` from ``total_cost_usd``,
        the priceable per-turn COGS field; ``usage`` carried for the audit trail).
      * every other message type (user/system/stream events) -> ignored.
    """
    events: List[AgentEvent] = []

    content = getattr(message, "content", None)
    if isinstance(content, list):
        for block in content:
            kind = type(block).__name__
            if kind == "ToolUseBlock":
                events.append(ToolUseEvent(
                    tool_name=getattr(block, "name", ""),
                    tool_input=dict(getattr(block, "input", {}) or {}),
                ))
            elif kind == "TextBlock":
                events.append(FramingEvent(text=getattr(block, "text", "")))
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
    """Drive a real model via ``claude_agent_sdk.query()`` and yield loop AgentEvents.

    Implements the ``agent.loop.AgentTransport`` Protocol: ``stream(prompt, finding)``
    yields the AgentEvents for ONE turn (one ``query()`` call). The driver drains the
    iterable as a single turn, increments the budget by ``turns=1``, and reads the
    single ``ResultEvent.cost_usd`` as that turn's COGS.

    Args:
        options:  ``ClaudeAgentOptions`` to pass to ``query()`` (built by the caller via
                  ``agent.harness.build_options``). Passed through verbatim — the
                  hook-free vs hook-bearing choice is the caller's (T5.3-V).
        query_fn: Injection seam for hermetic testing; defaults to the real
                  ``claude_agent_sdk.query``. Tests pass a fake async generator of
                  SDK-shaped messages, so no token is spent and no binary spawns.
    """

    #: Class-level invariant mirroring the eval transports: the adapter itself never
    #: spawns a binary — ``query()`` / the CLI owns any subprocess. The adapter only
    #: translates the resulting stream.
    SPAWNS_BINARY: bool = False

    def __init__(
        self,
        options: Any,
        *,
        query_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._options = options
        self._query_fn = query_fn  # resolved lazily so the SDK import stays deferred
        self.seen_prompts: List[str] = []

    def stream(self, prompt: str, finding: "Finding") -> Iterable[AgentEvent]:
        """Run one ``query()`` for *finding* and yield the translated AgentEvents.

        One ``stream()`` call == one loop turn. The async ``query()`` is drained to
        completion (the driver is plain sync Python, so ``asyncio.run`` is safe — there
        is no enclosing event loop) and the collected events are yielded in order.
        """
        self.seen_prompts.append(prompt)
        for event in asyncio.run(self._collect(prompt)):
            yield event

    async def _collect(self, prompt: str) -> List[AgentEvent]:
        """Drive one ``query()`` and collect its translated events (one turn)."""
        query = self._query_fn or _resolve_query()
        events: List[AgentEvent] = []
        saw_result = False
        async for message in query(prompt=prompt, options=self._options):
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
    options: Any,
    *,
    query_fn: Optional[Callable[..., Any]] = None,
) -> LiveAgentTransport:
    """Build a ``LiveAgentTransport`` — ONLY when the live opt-in is explicitly set.

    Guards the live, token-burning path behind ``AGENT_LIVE_TRANSPORT=1`` so it can
    never run by accident: the supervised T5.3-V run sets the env var; everything else
    (including CI) leaves it unset and gets a ``RuntimeError``. The relay/translation
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
    return LiveAgentTransport(options, query_fn=query_fn)
