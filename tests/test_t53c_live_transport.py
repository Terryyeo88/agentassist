"""
tests/test_t53c_live_transport.py — T5.3c: the live-model AgentTransport adapter.

LiveAgentTransport translates a claude_agent_sdk.query() message stream into the
case-file loop's AgentEvents (ToolUseEvent / FramingEvent / ResultEvent). These
tests drive it with a MOCKED async query() — a fake async generator of SDK-shaped
messages — so there is NO live model, NO claude binary, and NO token spend.

Asserts:
  * ToolUseBlock        -> ToolUseEvent (tool_name + tool_input incl. evidence_slot);
  * TextBlock           -> FramingEvent (candidate framing text);
  * ResultMessage       -> ResultEvent (cost_usd from total_cost_usd; usage carried);
  * ThinkingBlock / ToolResultBlock / UserMessage / SystemMessage -> ignored;
  * one stream() call == one turn: events accumulate across messages, one ResultEvent;
  * RELAY-ONLY: the adapter spawns no subprocess, executes no read tool, and exposes
    no Tier-2 / seal / emit surface — it only translates;
  * LiveAgentTransport satisfies the AgentTransport Protocol: run_casefile_loop accepts
    it and drives a finding to a PENDING proposal, with nothing sealed or emitted;
  * make_live_transport refuses to build unless AGENT_LIVE_TRANSPORT=1 (opt-in gate).

Hermetic: mocked SDK stream, in-memory fakes — no SDK query(), no binary, no tokens.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import claude_agent_sdk as sdk
import pytest

from agent.budget import RunBudget
from agent.dossier import Finding
from agent.ledger import Ledger
from agent.live_transport import (
    LIVE_OPT_IN_ENV,
    LiveAgentTransport,
    make_live_transport,
)
from agent.loop import (
    FramingEvent,
    LoopContext,
    ResultEvent,
    ToolUseEvent,
    run_casefile_loop,
)
from agent.proposals import StagingStore
from agent.schemas import Tier


# --------------------------------------------------------------------------- #
# Helpers: a fake async query() yielding SDK-shaped messages (no tokens).
# --------------------------------------------------------------------------- #

def _fake_query(messages):
    """Return an async query_fn replaying *messages* (mirrors claude_agent_sdk.query)."""
    async def _q(*, prompt, options):  # noqa: ANN001 - mirrors the SDK signature
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
        finding_id="x", check_id="gst_amount_mismatch",
        finding_type="probabilistic", source="test", payload={},
    )


def _stream_events(messages):
    """Drive one stream() over a mocked query and return the yielded AgentEvents."""
    lt = LiveAgentTransport(options=object(), query_fn=_fake_query(messages))
    return list(lt.stream("prompt", _finding()))


# --------------------------------------------------------------------------- #
# Mapping: SDK message/block -> AgentEvent
# --------------------------------------------------------------------------- #

class TestMapping:
    def test_tool_use_block_maps_to_tool_use_event(self):
        ti = {"justification": "Read the source PDF to support the case file.",
              "doc_num": 958, "evidence_slot": "document_pdfs"}
        events = _stream_events([
            _assistant(sdk.ToolUseBlock(id="t1", name="get_source_document", input=ti)),
            _result(),
        ])
        tues = [e for e in events if isinstance(e, ToolUseEvent)]
        assert len(tues) == 1
        assert tues[0].tool_name == "get_source_document"
        # tool_input passes through verbatim, incl. evidence_slot + justification.
        assert tues[0].tool_input["evidence_slot"] == "document_pdfs"
        assert tues[0].tool_input["doc_num"] == 958
        assert tues[0].tool_input["justification"].startswith("Read the source PDF")

    def test_text_block_maps_to_framing_event(self):
        events = _stream_events([
            _assistant(sdk.TextBlock(text="Flagged as a candidate for review.")),
            _result(),
        ])
        fr = [e for e in events if isinstance(e, FramingEvent)]
        assert len(fr) == 1
        assert fr[0].text == "Flagged as a candidate for review."

    def test_result_message_maps_to_result_event_cost(self):
        events = _stream_events([_result(cost=0.0123, usage={"input_tokens": 900})])
        res = [e for e in events if isinstance(e, ResultEvent)]
        assert len(res) == 1
        assert res[0].cost_usd == pytest.approx(0.0123)
        assert res[0].usage == {"input_tokens": 900}

    def test_none_total_cost_is_zero(self):
        # A ResultMessage with total_cost_usd=None must not crash the budget path.
        events = _stream_events([_result(cost=None)])
        res = [e for e in events if isinstance(e, ResultEvent)]
        assert len(res) == 1 and res[0].cost_usd == 0.0

    def test_thinking_tool_result_user_system_messages_are_ignored(self):
        events = _stream_events([
            _assistant(
                sdk.ThinkingBlock(thinking="internal", signature="sig"),
                sdk.ToolResultBlock(tool_use_id="t1", content="ignored"),
            ),
            sdk.UserMessage(content="tool result text"),
            sdk.SystemMessage(subtype="init", data={}),
            _result(cost=0.001),
        ])
        # Only the ResultEvent survives — no framing/tool-use from ignored blocks.
        assert [type(e).__name__ for e in events] == ["ResultEvent"]

    def test_one_turn_accumulates_across_messages_in_order(self):
        ti_read = {"justification": "Read the PDF to support the case file.",
                   "doc_num": 958, "evidence_slot": "document_pdfs"}
        ti_prop = {"justification": "Stage the dossier for reviewer approval.",
                   "action": "attach_dossier"}
        events = _stream_events([
            _assistant(sdk.ToolUseBlock(id="t1", name="get_source_document", input=ti_read)),
            _assistant(
                sdk.TextBlock(text="A candidate for reviewer attention."),
                sdk.ToolUseBlock(id="t2", name="propose_action", input=ti_prop),
            ),
            _result(cost=0.009),
        ])
        # Order preserved across the two assistant messages; exactly one ResultEvent.
        assert [type(e).__name__ for e in events] == [
            "ToolUseEvent", "FramingEvent", "ToolUseEvent", "ResultEvent",
        ]
        assert sum(isinstance(e, ResultEvent) for e in events) == 1

    def test_missing_result_message_yields_synthetic_zero_cost_event(self):
        # Every turn must advance the budget; a stream with no ResultMessage still
        # yields a zero-cost ResultEvent so the loop's budget.increment never starves.
        events = _stream_events([_assistant(sdk.TextBlock(text="framing only"))])
        res = [e for e in events if isinstance(e, ResultEvent)]
        assert len(res) == 1 and res[0].cost_usd == 0.0


# --------------------------------------------------------------------------- #
# Relay-only: the adapter translates; it never executes or escalates.
# --------------------------------------------------------------------------- #

class TestRelayOnly:
    def test_stream_spawns_no_subprocess(self, monkeypatch):
        def _boom(*a, **k):  # pragma: no cover - only fires on a containment breach
            raise AssertionError("live transport attempted to spawn a subprocess")

        monkeypatch.setattr(subprocess, "Popen", _boom)
        monkeypatch.setattr(subprocess, "run", _boom)
        events = _stream_events([
            _assistant(sdk.TextBlock(text="ok")), _result(cost=0.001),
        ])
        assert any(isinstance(e, ResultEvent) for e in events)

    def test_stream_executes_no_read_tool(self, monkeypatch):
        # The adapter only RELAYS read REQUESTS as events; the driver executes reads.
        # If the adapter executed a read itself, these tripwires would fire.
        import agent.read_tools as rt

        def _boom(*a, **k):  # pragma: no cover
            raise AssertionError("live transport executed a Tier-0 read itself")

        monkeypatch.setattr(rt, "get_source_document", _boom)
        monkeypatch.setattr(rt, "read_vendor_gst_status", _boom)
        monkeypatch.setattr(rt, "read_prior_period_treatment", _boom)
        ti = {"justification": "Read the PDF to support the case file.",
              "doc_num": 958, "evidence_slot": "document_pdfs"}
        events = _stream_events([
            _assistant(sdk.ToolUseBlock(id="t1", name="get_source_document", input=ti)),
            _result(cost=0.001),
        ])
        # The read surfaced as an event; nothing was executed.
        assert any(isinstance(e, ToolUseEvent) for e in events)

    def test_no_tier2_or_seal_emit_surface(self):
        lt = LiveAgentTransport(options=object(), query_fn=_fake_query([_result()]))
        public = {m for m in dir(lt) if not m.startswith("_")}
        # The only public surface is the translator: stream + inspection state.
        assert public == {"stream", "seen_prompts", "SPAWNS_BINARY"}
        assert lt.SPAWNS_BINARY is False
        for forbidden in ("seal", "emit", "approve", "execute", "run_tool"):
            assert not hasattr(lt, forbidden)


# --------------------------------------------------------------------------- #
# Protocol conformance: the loop accepts it and drives to a PENDING proposal.
# --------------------------------------------------------------------------- #

def _load_fx():
    spec = importlib.util.spec_from_file_location(
        "t53c_agent_loop_fx", pathlib.Path(__file__).parent / "fixtures" / "agent_loop.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestSatisfiesProtocolDrivesLoop:
    def _single_doc_review(self, fx):
        # canned review with the deterministic detect issue removed -> exactly one
        # (probabilistic) finding: doc:gst_amount_mismatch:958.
        review = fx.canned_review_result()
        review["compile_output"]["detect"]["issues"] = []
        return review

    def _doc_messages(self):
        read_ti = {
            "justification": "Reading the source invoice PDF to support the "
                             "gst_amount_mismatch case file.",
            "doc_num": 958, "evidence_slot": "document_pdfs",
        }
        prop_ti = {
            "justification": "Stage the human-reviewable dossier for this finding "
                             "pending reviewer approval.",
            "action": "attach_dossier",
        }
        return [
            _assistant(sdk.ToolUseBlock(id="t1", name="get_source_document", input=read_ti)),
            _assistant(
                sdk.TextBlock(text="The invoice PDF GST amount appears to differ from "
                                   "the SAP line; flagged as a candidate for review."),
                sdk.ToolUseBlock(id="t2", name="propose_action", input=prop_ti),
            ),
            _result(cost=0.009, usage={"input_tokens": 700, "output_tokens": 90}),
        ]

    def test_loop_accepts_adapter_and_stages_pending(self):
        fx = _load_fx()
        ledger = Ledger()
        budget = RunBudget(max_turns=20, max_cost_usd=1.0)
        store = StagingStore()
        transport = LiveAgentTransport(
            options=object(), query_fn=_fake_query(self._doc_messages()),
        )
        ctx = LoopContext(
            provider=fx.FakeProvider({958: "/tmp/INV-958.pdf"}),
            vendor_catalog=fx.default_vendor_catalog(),
            prior_period_store=fx.default_prior_period_store(),
        )
        result = run_casefile_loop(
            invoke_review=(lambda r=self._single_doc_review(fx): r),
            transport=transport, ctx=ctx, ledger=ledger, budget=budget, store=store,
        )
        # Exactly one PENDING proposal; nothing sealed or emitted.
        pending = store.list_pending()
        assert len(pending) == 1 and pending[0].status == "pending"
        assert len(result.proposals) == 1
        assert {o.status for o in result.outcomes} == {"staged"}
        # cost_usd flowed from ResultMessage.total_cost_usd into the budget COGS.
        assert budget.cost_usd_used == pytest.approx(0.009)
        # No Tier-2 execution outcome anywhere in the ledger.
        assert all(e.tier != Tier.TWO.value for e in ledger.entries)
        ledger.verify()
        # The driver passed the per-finding prompt through the adapter.
        assert transport.seen_prompts and "gst_amount_mismatch" in transport.seen_prompts[0]


# --------------------------------------------------------------------------- #
# Opt-in gate: the live path cannot be built by accident.
# --------------------------------------------------------------------------- #

class TestOptInGate:
    def test_factory_refuses_without_env(self, monkeypatch):
        monkeypatch.delenv(LIVE_OPT_IN_ENV, raising=False)
        with pytest.raises(RuntimeError, match=LIVE_OPT_IN_ENV):
            make_live_transport(options=object())

    def test_factory_builds_with_opt_in(self, monkeypatch):
        monkeypatch.setenv(LIVE_OPT_IN_ENV, "1")
        lt = make_live_transport(options=object(), query_fn=_fake_query([_result()]))
        assert isinstance(lt, LiveAgentTransport)

    def test_factory_rejects_non_one_values(self, monkeypatch):
        monkeypatch.setenv(LIVE_OPT_IN_ENV, "true")
        with pytest.raises(RuntimeError):
            make_live_transport(options=object())
