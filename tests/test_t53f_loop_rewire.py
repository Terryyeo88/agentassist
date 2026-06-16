"""
tests/test_t53f_loop_rewire.py — T5.3f: the rewired in-turn-evidence loop (arch A).

The case-file loop now gathers evidence IN-TURN: the transport's
``gather(prompt, finding, evidence_sink)`` fills the sink (live: via the MCP reads
server handlers; hermetic: directly) and yields only FramingEvent/ResultEvent. The
plain-Python DRIVER still disposes — it runs budget, code-defined completeness over
the sink, the language-lint, driver-decided staging (A1), and bounded re-entry.

These tests drive the rewired loop with a hermetic fake gather-transport — no live
model, no SDK, no tokens. They assert the arch-A non-negotiables:
  * completeness is computed by the driver over the sink (code-defined);
  * reads are NOT executed by the driver (no _execute_read double-run);
  * staging is driver-decided when completeness + lint pass, with the Tier-1
    justification written to the ledger BEFORE staging;
  * the loop stages ONLY PENDING proposals (no seal/emit);
  * review() runs once up front; BudgetExceededSignal is non-blocking (Invariant 7).
"""
from __future__ import annotations

import agent.loop as loop_mod
from agent.budget import RunBudget
from agent.ledger import Ledger
from agent.loop import (
    AgentTransport,
    FramingEvent,
    LoopContext,
    ResultEvent,
    run_casefile_loop,
)
from agent.proposals import StagingStore
from agent.read_tools_server import qualified_read_name
from agent.schemas import Tier


# --------------------------------------------------------------------------- #
# A hermetic gather-transport: fills the sink directly, yields framing/cost.
# --------------------------------------------------------------------------- #

class _GatherFake:
    """Fills evidence_sink directly (simulating the MCP handlers) and yields events.

    Per constraint B it writes the Tier-0 read ledger entries itself; the driver
    writes none for reads.
    """

    def __init__(self, ledger, *, evidence, framing, cost):
        self._ledger = ledger
        self._evidence = dict(evidence)
        self._framing = framing
        self._cost = cost
        self.gather_calls: list[str] = []

    def gather(self, prompt, finding, evidence_sink):
        self.gather_calls.append(finding.finding_id)
        for slot, val in self._evidence.items():
            evidence_sink[slot] = val
            # T5.7b: ledger under the LIVE namespaced read name (mcp__reads__<tool>).
            self._ledger.append(
                tool_name=qualified_read_name("get_source_document"),
                tier=Tier.ZERO, justification=None,
                call_params={"evidence_slot": slot}, outcome="allowed", blocked_reason=None,
            )
        yield FramingEvent(text=self._framing)
        yield ResultEvent(cost_usd=self._cost)


def _single_doc_review():
    return {
        "status": "completed",
        "compile_output": {"detect": {"issues": []}},
        "reasoning_artefact": {"status": "ok", "candidates": []},
        "document_candidates": [{
            "doc_num": 958, "check_id": "gst_amount_mismatch", "severity": "MEDIUM",
            "message": "Invoice PDF GST (74.00) differs from SAP line (70.00).",
            "extracted_value": 74.0, "listing_value": 70.0, "determinability": "born_digital",
        }],
        "bundle_dir": "audit/sbodemosg/2024Q3/seal-001", "gate_failure": None,
    }


class _CountingInvoke:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self._result


_CLEAN = ("The invoice PDF GST amount appears to differ from the SAP line; flagged as "
          "a candidate for review.")
_ASSERTIVE = "This invoice is compliant and the supplier violates nothing."


def _run(*, framing=_CLEAN, cost=0.009, max_cost=1.0):
    ledger = Ledger()
    budget = RunBudget(max_turns=20, max_cost_usd=max_cost)
    store = StagingStore()
    invoke = _CountingInvoke(_single_doc_review())
    transport = _GatherFake(
        ledger, evidence={"document_pdfs": "/tmp/INV-958.pdf"}, framing=framing, cost=cost,
    )
    result = run_casefile_loop(
        invoke_review=invoke, transport=transport, ctx=LoopContext(),
        ledger=ledger, budget=budget, store=store,
    )
    return result, ledger, budget, store, transport, invoke


# --------------------------------------------------------------------------- #
# Contract
# --------------------------------------------------------------------------- #

def test_transport_protocol_is_gather_not_stream():
    assert hasattr(AgentTransport, "gather")


def test_driver_does_not_execute_reads_itself():
    # The between-turns _execute_read path is gone; reads happen in the transport.
    assert not hasattr(loop_mod, "_execute_read")


# --------------------------------------------------------------------------- #
# Happy path: gather -> sink -> completeness -> driver-decided staging (PENDING)
# --------------------------------------------------------------------------- #

def test_complete_finding_is_staged_pending():
    result, ledger, budget, store, transport, invoke = _run()
    pending = store.list_pending()
    assert len(pending) == 1 and pending[0].status == "pending"
    assert len(result.proposals) == 1
    assert {o.status for o in result.outcomes} == {"staged"}
    # evidence came from the sink the transport filled (the agent slot).
    outcome = result.outcomes[0]
    assert outcome.dossier.evidence["document_pdfs"] == "/tmp/INV-958.pdf"
    assert outcome.dossier.completeness["satisfied"] is True
    # review() ran exactly once up front.
    assert invoke.calls == 1
    # cost flowed to the budget COGS.
    assert abs(budget.cost_usd_used - 0.009) < 1e-9


def test_staging_justification_written_before_staging_driver_decided():
    # A1: the driver triggers staging and writes the Tier-1 propose_action justification.
    result, ledger, budget, store, transport, invoke = _run()
    propose = [e for e in ledger.entries if e.tool_name == "propose_action"]
    assert len(propose) == 1
    assert propose[0].tier == Tier.ONE.value
    assert propose[0].outcome == "allowed"
    assert propose[0].justification  # non-empty driver justification


def test_reads_ledgered_by_transport_not_driver():
    # Constraint B: the transport (here the fake) writes the Tier-0 read entries.
    result, ledger, budget, store, transport, invoke = _run()
    reads = [e for e in ledger.entries if e.tier == Tier.ZERO.value
             and e.tool_name == qualified_read_name("get_source_document")]
    assert len(reads) == 1
    ledger.verify()


def test_only_pending_no_seal_or_emit():
    result, ledger, budget, store, transport, invoke = _run()
    assert all(e.tier != Tier.TWO.value for e in ledger.entries)
    assert result.deterministic_bundle_dir == "audit/sbodemosg/2024Q3/seal-001"


# --------------------------------------------------------------------------- #
# Lint guard + budget non-blocking
# --------------------------------------------------------------------------- #

def test_assertive_framing_held_back_by_lint():
    result, ledger, budget, store, transport, invoke = _run(framing=_ASSERTIVE)
    assert store.list_pending() == []
    assert {o.status for o in result.outcomes} == {"incomplete"}


def test_budget_exceeded_is_non_blocking():
    # A tiny cap trips BudgetExceededSignal inside the agent layer; the deterministic
    # deliverable still stands (Invariant 7).
    result, ledger, budget, store, transport, invoke = _run(cost=5.0, max_cost=0.5)
    assert result.agent_layer_complete is False
    assert result.review_status == "completed"
    assert result.deterministic_bundle_dir == "audit/sbodemosg/2024Q3/seal-001"
    assert store.list_pending() == []
