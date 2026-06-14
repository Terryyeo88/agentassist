"""
tests/test_t57b_audit_handle.py — T5.7b tech-debt fix: make_hooks exposes the
audit_log through a PUBLIC handle, and the eval runner reads it from that handle
instead of introspecting ``post_cb.__closure__``.

The fix is additive and backward-compatible: the 3-tuple return shape is unchanged
(every existing caller still unpacks (pre_cb, post_cb, audit_log)); the public
handle is an attribute attached to the returned PostToolUse callback.

Hermetic: synthetic hook events + the eval runner over FakeTransport. No model,
no SAP, no subprocess.
"""
from __future__ import annotations

import asyncio
import inspect

from agent.hooks import make_hooks
from agent.ledger import Ledger


def _run(coro):
    return asyncio.run(coro)


def _post_event(tool_name: str) -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": {},
        "tool_response": {"ok": True},
        "tool_use_id": "uid-1",
        "session_id": "s",
        "transcript_path": "/t",
        "cwd": "/",
    }


def test_make_hooks_return_shape_unchanged_three_tuple():
    out = make_hooks(Ledger())
    assert isinstance(out, tuple)
    assert len(out) == 3
    pre_cb, post_cb, audit_log = out
    assert callable(pre_cb)
    assert callable(post_cb)
    assert isinstance(audit_log, list)


def test_post_cb_exposes_audit_log_public_handle():
    _pre_cb, post_cb, audit_log = make_hooks(Ledger())
    assert hasattr(post_cb, "audit_log"), "post callback must expose a public audit_log handle"
    # The public handle is the SAME object the tuple returns (no copy).
    assert post_cb.audit_log is audit_log


def test_public_handle_tracks_appends():
    _pre_cb, post_cb, audit_log = make_hooks(Ledger())
    assert post_cb.audit_log == []
    _run(post_cb(_post_event("read_sap_invoices"), "uid-1", {}))
    assert len(audit_log) == 1
    # Reading via the public handle sees the same append.
    assert post_cb.audit_log[-1]["tool_name"] == "read_sap_invoices"


def test_runner_no_longer_introspects_closure():
    import agent.eval.runner as runner_mod

    src = inspect.getsource(runner_mod)
    assert "__closure__" not in src, (
        "the eval runner must read audit_log via the public handle, "
        "not by introspecting post_cb.__closure__"
    )


def test_runner_recovers_audit_log_via_public_handle():
    from agent.eval.runner import run_scenario
    from agent.eval.scenario import Attempt, Scenario

    rec = run_scenario(Scenario(name="t0", description="", attempts=[
        Attempt(tool_name="read_sap_invoices", tool_input={}),
    ]))
    # The Tier-0 read's PostToolUse outcome reached the audit_log the runner read
    # off the public handle.
    assert any(e["tool_name"] == "read_sap_invoices" for e in rec.audit_log)
