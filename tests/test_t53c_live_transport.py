"""
tests/test_t53c_live_transport.py — T5.3c/T5.3f: the live-model AgentTransport adapter.

LiveAgentTransport implements the arch-A ``gather(prompt, finding, evidence_sink)``
contract: per finding it builds the T5.3e MCP reads server bound to the sink, wires it
into hook-bearing options via ``build_options(reads_server=…)``, runs ONE
``claude_agent_sdk.query()`` (the SDK runs the read handlers in-turn, filling the sink),
and yields only FramingEvent (text) + ResultEvent (cost). Reads do NOT come back as
events — they flow through the sink, read by the DRIVER after the turn.

These tests drive the adapter with a MOCKED async ``query()`` — no live model, no
binary, no tokens. The sink-FILLING by real handlers is covered by the T5.3e reads-
server tests and the loop fakes (test_t53b / test_t57b / test_t53f); here we assert the
translation (text/cost only), the reads-server WIRING, relay-only, and the opt-in gate.
"""
from __future__ import annotations

import subprocess

import claude_agent_sdk as sdk
import pytest

import agent.live_transport as lt_mod
from agent.budget import RunBudget
from agent.dossier import Finding
from agent.ledger import Ledger
from agent.live_transport import (
    LIVE_OPT_IN_ENV,
    LiveAgentTransport,
    make_live_transport,
)
from agent.loop import FramingEvent, LoopContext, ResultEvent
from agent.read_tools_server import READ_TOOLS_QUALIFIED, READS_SERVER_NAME


# --------------------------------------------------------------------------- #
# Helpers: a fake async query() yielding SDK-shaped messages (no tokens).
# --------------------------------------------------------------------------- #

def _fake_query(messages, captured=None):
    """Return an async query_fn replaying *messages*; records options into *captured*."""
    async def _q(*, prompt, options):  # noqa: ANN001 - mirrors the SDK signature
        if captured is not None:
            captured["options"] = options
            captured["prompt"] = prompt
        for msg in messages:
            yield msg
    return _q


def _assistant(*blocks):
    return sdk.AssistantMessage(content=list(blocks), model="fake-model")


def _result(cost=0.0, usage=None):
    return sdk.ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
        num_turns=1, session_id="sess", total_cost_usd=cost, usage=usage or {},
    )


def _finding():
    return Finding(
        finding_id="doc:gst_amount_mismatch:958", check_id="gst_amount_mismatch",
        finding_type="probabilistic", source="test", payload={"doc_num": 958},
    )


def _transport(messages, *, captured=None, ctx=None):
    return LiveAgentTransport(
        ctx=ctx or LoopContext(), ledger=Ledger(),
        budget=RunBudget(max_turns=4, max_cost_usd=1.0),
        system_prompt="audit agent", query_fn=_fake_query(messages, captured),
    )


def _gather_events(messages, *, captured=None, sink=None):
    """Drive one gather over a mocked query and return the yielded AgentEvents."""
    t = _transport(messages, captured=captured)
    return list(t.gather("prompt", _finding(), sink if sink is not None else {}))


# --------------------------------------------------------------------------- #
# Mapping: SDK message/block -> AgentEvent (text + cost only)
# --------------------------------------------------------------------------- #

class TestMapping:
    def test_text_block_maps_to_framing_event(self):
        events = _gather_events([
            _assistant(sdk.TextBlock(text="candidate for review: doc 958.")),
            _result(),
        ])
        fr = [e for e in events if isinstance(e, FramingEvent)]
        assert len(fr) == 1
        assert fr[0].text == "candidate for review: doc 958."

    def test_result_message_maps_to_result_event_cost(self):
        events = _gather_events([_result(cost=0.0123, usage={"input_tokens": 900})])
        res = [e for e in events if isinstance(e, ResultEvent)]
        assert len(res) == 1
        assert res[0].cost_usd == pytest.approx(0.0123)
        assert res[0].usage == {"input_tokens": 900}

    def test_none_total_cost_is_zero(self):
        events = _gather_events([_result(cost=None)])
        res = [e for e in events if isinstance(e, ResultEvent)]
        assert len(res) == 1 and res[0].cost_usd == 0.0

    def test_tool_use_block_is_not_emitted_as_event(self):
        # Reads are run in-turn by the SDK handlers (they fill the sink); the adapter
        # does NOT relay them as events.
        ti = {"doc_num": 958, "evidence_slot": "document_pdfs"}
        events = _gather_events([
            _assistant(sdk.ToolUseBlock(id="t1", name="get_source_document", input=ti)),
            _result(),
        ])
        # Only the ResultEvent survives — no ToolUseEvent/FramingEvent from the read.
        assert [type(e).__name__ for e in events] == ["ResultEvent"]

    def test_thinking_tool_result_user_system_messages_are_ignored(self):
        events = _gather_events([
            _assistant(
                sdk.ThinkingBlock(thinking="internal", signature="sig"),
                sdk.ToolResultBlock(tool_use_id="t1", content="ignored"),
            ),
            sdk.UserMessage(content="tool result text"),
            sdk.SystemMessage(subtype="init", data={}),
            _result(cost=0.001),
        ])
        assert [type(e).__name__ for e in events] == ["ResultEvent"]

    def test_one_turn_accumulates_framing_then_result(self):
        events = _gather_events([
            _assistant(sdk.TextBlock(text="a candidate for reviewer attention.")),
            _result(cost=0.009),
        ])
        assert [type(e).__name__ for e in events] == ["FramingEvent", "ResultEvent"]

    def test_missing_result_message_yields_synthetic_zero_cost_event(self):
        events = _gather_events([_assistant(sdk.TextBlock(text="framing only"))])
        res = [e for e in events if isinstance(e, ResultEvent)]
        assert len(res) == 1 and res[0].cost_usd == 0.0


# --------------------------------------------------------------------------- #
# gather wires the reads server bound to the per-finding sink
# --------------------------------------------------------------------------- #

class TestReadsServerWiring:
    def test_gather_wires_reads_server_into_options(self):
        captured = {}
        list(_gather_events([_result()], captured=captured))
        options = captured["options"]
        assert READS_SERVER_NAME in options.mcp_servers
        for q in READ_TOOLS_QUALIFIED:
            assert q in options.allowed_tools

    def test_reads_server_is_bound_to_the_drivers_sink(self, monkeypatch):
        # The per-finding sink the driver passes to gather must be the one bound into
        # the reads server (so the real handlers fill it in-turn).
        seen = {}

        def _spy(ctx, evidence_sink):
            seen["sink_id"] = id(evidence_sink)
            return "SENTINEL_SERVER"

        monkeypatch.setattr(lt_mod, "make_read_tools_server", _spy)
        driver_sink = {}
        captured = {}
        t = _transport([_result()], captured=captured)
        list(t.gather("p", _finding(), driver_sink))
        assert seen["sink_id"] == id(driver_sink)
        assert captured["options"].mcp_servers[READS_SERVER_NAME] == "SENTINEL_SERVER"

    def test_hook_bearing_options(self):
        # Arch A uses hook-bearing options (attach_hooks default True).
        captured = {}
        list(_gather_events([_result()], captured=captured))
        assert captured["options"].hooks is not None
        assert "PreToolUse" in captured["options"].hooks


# --------------------------------------------------------------------------- #
# Relay-only: the adapter runs the turn + translates; it never escalates.
# --------------------------------------------------------------------------- #

class TestRelayOnly:
    def test_gather_spawns_no_subprocess(self, monkeypatch):
        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("live transport attempted to spawn a subprocess")

        monkeypatch.setattr(subprocess, "Popen", _boom)
        monkeypatch.setattr(subprocess, "run", _boom)
        events = _gather_events([_assistant(sdk.TextBlock(text="ok")), _result(cost=0.001)])
        assert any(isinstance(e, ResultEvent) for e in events)

    def test_no_tier2_or_seal_emit_surface(self):
        t = _transport([_result()])
        public = {m for m in dir(t) if not m.startswith("_")}
        assert public == {"gather", "seen_prompts", "SPAWNS_BINARY"}
        assert t.SPAWNS_BINARY is False
        for forbidden in ("seal", "emit", "approve", "execute", "stream"):
            assert not hasattr(t, forbidden)


# --------------------------------------------------------------------------- #
# Opt-in gate
# --------------------------------------------------------------------------- #

class TestOptInGate:
    def _kwargs(self):
        return dict(ctx=LoopContext(), ledger=Ledger(),
                    budget=RunBudget(max_turns=2, max_cost_usd=0.5))

    def test_factory_refuses_without_env(self, monkeypatch):
        monkeypatch.delenv(LIVE_OPT_IN_ENV, raising=False)
        with pytest.raises(RuntimeError, match=LIVE_OPT_IN_ENV):
            make_live_transport(**self._kwargs())

    def test_factory_builds_with_opt_in(self, monkeypatch):
        monkeypatch.setenv(LIVE_OPT_IN_ENV, "1")
        t = make_live_transport(query_fn=_fake_query([_result()]), **self._kwargs())
        assert isinstance(t, LiveAgentTransport)

    def test_factory_rejects_non_one_values(self, monkeypatch):
        monkeypatch.setenv(LIVE_OPT_IN_ENV, "true")
        with pytest.raises(RuntimeError):
            make_live_transport(**self._kwargs())


def test_import_agent_live_transport_does_not_load_sdk():
    import importlib
    import sys

    for m in ("claude_agent_sdk", "agent", "agent.live_transport"):
        sys.modules.pop(m, None)
    importlib.import_module("agent")
    importlib.import_module("agent.live_transport")
    assert "claude_agent_sdk" not in sys.modules
