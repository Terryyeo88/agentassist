"""
tests/test_t53a_sealed_routing.py — T5.3 Slice 1: sealed-chain vs audit_log
routing (acceptance (c)).

LOCKED decision:
  * Tier-2 outcome-bearing executions (seal/emit, post-approval) → execution
    outcome APPENDS to the SEALED hash-chained agent-ledger.
  * Tier-0 routine reads (PostToolUse) → stay in the SEPARATE, unsealed audit_log.

This test asserts the routing: a Tier-0 read lands in audit_log only (no
execution-outcome entry in the sealed ledger), while a Tier-2 seal lands in the
sealed ledger only (not in audit_log).

All hermetic: synthetic hook events + fake seal_fn. No model, no SAP, no network.
"""
from __future__ import annotations

import asyncio

from agent.executor import Executor, make_tier2_handlers
from agent.hooks import make_hooks
from agent.ledger import Ledger
from agent.proposals import build_proposal, StagingStore
from agent.schemas import Tier


def _run(coro):
    return asyncio.run(coro)


_CONTEXT: dict = {}


def _post(tool_name: str) -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": {},
        "tool_response": {"ok": True},
        "tool_use_id": "uid-post-1",
        "session_id": "s",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "/tmp",
    }


def test_tier0_read_routes_to_audit_log_not_sealed_ledger():
    ledger = Ledger()
    _pre, post_cb, audit_log = make_hooks(ledger)

    _run(post_cb(_post("read_sap_invoices"), "uid-post-1", _CONTEXT))

    # Tier-0 routine read → audit_log (unsealed).
    assert len(audit_log) == 1
    assert audit_log[0]["tool_name"] == "read_sap_invoices"
    # No Tier-2 execution outcome enters the sealed ledger from a routine read.
    assert all(e.tier != Tier.TWO.value for e in ledger.entries)


def test_tier2_seal_routes_to_sealed_ledger_not_audit_log():
    ledger = Ledger()
    _pre, _post_cb, audit_log = make_hooks(ledger)

    store = StagingStore()
    proposal = build_proposal(
        action="seal_bundle",
        justification="Human-approved seal of the engagement bundle at audit close.",
        evidence_refs=["audit/compile-output.json"],
        inputs={"client_id": "sbodemosg"},
    )
    store.stage(proposal)
    store.approve(proposal.proposal_id)

    handlers = make_tier2_handlers(
        ledger,
        seal_fn=lambda *, proposal, ledger: "audit/bundle/dir",
        emit_fn=lambda *, proposal, ledger: "audit/bundle/report.pdf",
    )
    Executor(staging_store=store, extra_handlers=handlers).execute(proposal.proposal_id)

    # Tier-2 execution outcome → sealed ledger.
    tier2 = [e for e in ledger.entries if e.tier == Tier.TWO.value]
    assert len(tier2) == 1
    assert tier2[0].tool_name == "seal_bundle"
    assert tier2[0].outcome == "executed"
    # The Tier-2 execution outcome is NOT in the unsealed audit_log.
    assert all(entry["tool_name"] != "seal_bundle" for entry in audit_log)
    ledger.verify()
