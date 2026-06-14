"""
agent/eval/transport.py — FakeTransport: a hermetic, scripted SDK transport.

FakeTransport is a concrete subclass of the SDK ``Transport`` ABC that replays a
pre-scripted agent message stream WITHOUT spawning a CLI binary and WITHOUT
consuming tokens. It is the ONLY transport the eval harness ever uses, satisfying
the T5.7a acceptance: "no query() against a real transport anywhere; FakeTransport
only".

The scripted stream is a list of raw SDK-shaped message dicts — exactly the shape
the real CLI emits and the SDK's message_parser consumes (an ``assistant`` message
carrying ``tool_use`` content blocks). ``scenario_to_stream`` builds that stream
from a Scenario's attempts.

The SDK import is DEFERRED inside ``FakeTransport`` construction so this module can
be imported in a pure-core environment; instantiation requires the SDK (which the
agent layer is allowed to use lazily).

Zero binary spawn. Zero tokens. Zero network I/O.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from agent.eval.scenario import Scenario


def _transport_base() -> type:
    """Return the SDK Transport ABC (deferred import keeps agent/ pure-importable)."""
    from claude_agent_sdk import Transport  # noqa: PLC0415 - deferred SDK import

    return Transport


# FakeTransport genuinely subclasses the SDK Transport ABC, so the base must be
# resolved when this CLASS is defined — it cannot be deferred into a method like
# the rest of agent/ defers the SDK. This is confined to agent/eval/ (SDK-dependent
# measurement infra); the cage CORE (agent/__init__ imports nothing, agent.hooks /
# harness / engine_tool all defer the SDK) stays importable without the SDK, since
# nothing in core imports agent.eval. Per merge-gates.md, agent/ MAY use the SDK.
_TransportBase = _transport_base()


class FakeTransport(_TransportBase):  # type: ignore[valid-type,misc]
    """A scripted, hermetic Transport that never spawns a process.

    Args:
        messages: Raw SDK-shaped message dicts to replay, in order.

    Attributes:
        spawned_binary: Always False — proves no CLI binary was ever launched.
        connected:      True between connect() and close().
    """

    #: Class-level invariant: this transport never spawns a binary.
    SPAWNS_BINARY: bool = False

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages: list[dict[str, Any]] = list(messages)
        self._writes: list[str] = []
        self.spawned_binary: bool = False
        self.connected: bool = False

    async def connect(self) -> None:
        """Mark ready. No subprocess, no network — nothing is spawned."""
        self.connected = True

    async def write(self, data: str) -> None:
        """Record outbound control data (e.g. hook responses); no I/O performed."""
        self._writes.append(data)

    async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Yield the scripted messages in order."""
        for msg in self._messages:
            yield msg

    async def close(self) -> None:
        """Tear down. No resources to release."""
        self.connected = False

    def is_ready(self) -> bool:
        """True once connected; never depends on a live process."""
        return self.connected

    async def end_input(self) -> None:
        """No-op: there is no stdin to close."""
        return None


def scenario_to_stream(scenario: Scenario) -> list[dict[str, Any]]:
    """Build the raw scripted agent stream for a Scenario's attempts.

    Each attempt becomes one ``assistant`` message carrying a single ``tool_use``
    content block, mirroring the raw shape the CLI emits and the SDK parses. The
    attempt's justification convenience is applied to the tool input.
    """
    stream: list[dict[str, Any]] = []
    for i, attempt in enumerate(scenario.attempts):
        stream.append({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "fake-eval-model",
                "content": [{
                    "type": "tool_use",
                    "id": f"toolu_eval_{i}",
                    "name": attempt.tool_name,
                    "input": attempt.merged_input(),
                }],
            },
            "session_id": "eval-session",
        })
    return stream
