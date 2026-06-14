"""
tests/test_t57a_transport.py — T5.7a: FakeTransport hermetic stream + scenario stream.

The FakeTransport is a concrete subclass of the SDK Transport ABC that replays a
scripted agent stream WITHOUT spawning a binary and WITHOUT tokens. It is the only
transport the eval harness ever uses.

Hermetic: no live model, no SAP, no subprocess.
"""
from __future__ import annotations

import asyncio

from agent.eval.scenario import Attempt, Scenario
from agent.eval.transport import FakeTransport, scenario_to_stream


def _run(coro):
    return asyncio.run(coro)


def test_fake_transport_is_sdk_transport_subclass():
    from claude_agent_sdk import Transport

    assert issubclass(FakeTransport, Transport)


def test_fake_transport_connect_spawns_no_binary():
    ft = FakeTransport([])
    assert ft.spawned_binary is False
    _run(ft.connect())
    assert ft.spawned_binary is False
    assert ft.is_ready() is True
    _run(ft.close())


def test_fake_transport_replays_scripted_messages_in_order():
    msgs = [
        {"type": "assistant", "message": {"role": "assistant", "model": "fake",
                                          "content": [{"type": "tool_use", "id": "t0",
                                                       "name": "read_ledger", "input": {}}]}},
        {"type": "assistant", "message": {"role": "assistant", "model": "fake",
                                          "content": [{"type": "tool_use", "id": "t1",
                                                       "name": "read_sap_invoices", "input": {}}]}},
    ]
    ft = FakeTransport(msgs)
    _run(ft.connect())

    async def _drain():
        return [m async for m in ft.read_messages()]

    got = _run(_drain())
    assert got == msgs


def test_write_and_end_input_are_noops_no_spawn():
    ft = FakeTransport([])
    _run(ft.connect())
    _run(ft.write('{"type":"control_response"}\n'))
    _run(ft.end_input())
    assert ft.spawned_binary is False


def test_scenario_to_stream_builds_tool_use_assistant_messages():
    scenario = Scenario(
        name="s",
        description="d",
        attempts=[
            Attempt(tool_name="read_ledger", tool_input={}),
            Attempt(tool_name="run_review_chain", tool_input={}, justification="x" * 30),
        ],
    )
    stream = scenario_to_stream(scenario)
    assert len(stream) == 2
    for raw in stream:
        assert raw["type"] == "assistant"
        blocks = raw["message"]["content"]
        assert len(blocks) == 1
        assert blocks[0]["type"] == "tool_use"

    # justification convenience merged into the tool_use input
    second = stream[1]["message"]["content"][0]
    assert second["name"] == "run_review_chain"
    assert second["input"]["justification"] == "x" * 30
