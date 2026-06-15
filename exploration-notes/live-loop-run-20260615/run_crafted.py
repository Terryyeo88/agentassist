"""
T5.3-V crafted-finding LIVE run (architecture A) — machinery only.

Drives the rewired run_casefile_loop against a REAL model over a HAND-CRAFTED
ReviewResult + a real non-empty LoopContext (fixture PDF + small vendor catalog),
so the in-turn MCP reads return non-null evidence and the driver can actually stage
a PENDING proposal. NOT demo-DB, NOT real-client, NOT accuracy-validated.

Evidence discipline: the full raw SDK message stream is captured (tee'd off the real
query) and dumped BEFORE any metric is computed.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from pathlib import Path

os.environ["AGENT_LIVE_TRANSPORT"] = "1"  # explicit opt-in (token-burning)

from agent.budget import RunBudget
from agent.dossier import extract_findings
from agent.eval.metrics import dossier_completeness_rate, language_lint_pass_rate
from agent.ledger import Ledger
from agent.live_transport import make_live_transport
from agent.loop import LoopContext, run_casefile_loop
from agent.proposals import StagingStore
from agent.schemas import Tier

HERE = Path(__file__).parent
RAW = HERE / "raw"
RAW.mkdir(parents=True, exist_ok=True)

PDF = (HERE.parents[1] / "tests" / "fixtures" / "documents" / "INV-3001.pdf").resolve()

SYSTEM_PROMPT = (
    "You are an audit assistant assembling a case file for ONE GST review finding. You "
    "have read-only tools — get_source_document, read_vendor_gst_status, "
    "read_prior_period_treatment — to gather supporting evidence. For the given finding, "
    "call the tool(s) it needs, passing the finding's doc_num / card_name / key and the "
    "matching evidence_slot. Gather the evidence the finding requires; do not stop early. "
    'Then write exactly ONE line of candidate framing beginning "candidate for review:" '
    "describing what a reviewer should check. Never assert compliance, never state a "
    "verdict, never claim a transaction is wrong — you surface candidates for a human "
    "reviewer, nothing more."
)


def _crafted_review() -> dict:
    """Two findings exercising both read paths (NO_GST_REG -> vendor; doc -> PDF)."""
    return {
        "status": "completed",
        "compile_output": {"detect": {"issues": [{
            "severity": "HIGH", "error_code": "NO_GST_REG", "doc_num": 605,
            "doc_date": "2024-07-15", "card_name": "Mama Shop Supplies",
            "description": "Input tax claimed from supplier with no GST reg no.",
            "recommendation": "Review whether input tax is claimable.",
        }]}},
        "reasoning_artefact": {"status": "ok", "candidates": []},
        "document_candidates": [{
            "doc_num": 3001, "check_id": "gst_amount_mismatch", "severity": "MEDIUM",
            "message": "Invoice PDF GST (74.00) differs from SAP line (70.00).",
            "extracted_value": 74.0, "listing_value": 70.0, "determinability": "born_digital",
        }],
        "bundle_dir": "crafted-finding-live/no-real-bundle", "gate_failure": None,
    }


class _FixtureProvider:
    """Real DocumentProvider over a local fixture PDF (read-only)."""
    def __init__(self, mapping):
        self._m = {int(k): v for k, v in mapping.items()}

    def get_document(self, doc_num):
        return self._m.get(int(doc_num))


def _ser(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {"__type__": type(obj).__name__,
                **{f.name: _ser(getattr(obj, f.name)) for f in dataclasses.fields(obj)}}
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_ser(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


raw_stream: list = []  # one entry per query() call: {"prompt", "messages"}


def _capturing_query():
    """Wrap the real claude_agent_sdk.query, tee'ing every message to raw_stream."""
    from claude_agent_sdk import query as real_query

    async def _q(*, prompt, options):
        entry = {"prompt": prompt, "messages": []}
        raw_stream.append(entry)
        async for msg in real_query(prompt=prompt, options=options):
            entry["messages"].append(_ser(msg))
            yield msg
    return _q


def main() -> None:
    review = _crafted_review()
    ctx = LoopContext(
        provider=_FixtureProvider({3001: str(PDF)}),
        vendor_catalog={"Mama Shop Supplies": {"gst_registered": False, "gst_reg_no": None}},
        prior_period_store={"NO_GST_REG:Mama Shop Supplies": {"treatment": "disallowed",
                                                              "period": "2024Q2"}},
    )
    ledger = Ledger()
    budget = RunBudget(max_turns=8, max_cost_usd=2.00)
    store = StagingStore()
    transport = make_live_transport(
        ctx=ctx, ledger=ledger, budget=budget,
        system_prompt=SYSTEM_PROMPT, query_fn=_capturing_query(),
    )

    findings = extract_findings(review)
    print(f">>> crafted findings: {[(f.finding_id, f.check_id) for f in findings]}")
    print(f">>> PDF fixture exists: {PDF.exists()}  ({PDF})")
    print(">>> running LIVE loop (AGENT_LIVE_TRANSPORT=1, max_cost_usd=2.00) ...\n")

    err = None
    try:
        result = run_casefile_loop(
            invoke_review=lambda: review, transport=transport, ctx=ctx,
            ledger=ledger, budget=budget, store=store,
        )
    except Exception as e:  # pragma: no cover - surfaced into the report
        err = f"{type(e).__name__}: {e}"
        result = None

    # --- SAVE RAW FIRST (before any metric) ---
    (RAW / "stream.json").write_text(json.dumps(raw_stream, indent=2), encoding="utf-8")
    (RAW / "ledger.json").write_text(
        json.dumps([_ser(e) for e in ledger.entries], indent=2), encoding="utf-8")
    print(f">>> SAVED raw stream ({sum(len(e['messages']) for e in raw_stream)} msgs across "
          f"{len(raw_stream)} query calls) + ledger ({len(ledger.entries)} entries)")

    if err is not None:
        (HERE / "RUN-ERROR.txt").write_text(err, encoding="utf-8")
        print(f"\n!!! LIVE RUN ERRORED: {err}\n(raw stream saved for diagnosis)")
        return

    # --- artifacts ---
    pending = store.list_pending()
    outcomes = result.outcomes
    for o in outcomes:
        ev = dict(o.dossier.evidence) if o.dossier else {}
        ev_keys = {k: ("<present>" if v is not None else None) for k, v in ev.items()}
        print(f"    [{o.check_id}] status={o.status} attempts={o.attempts} "
              f"complete={o.dossier.completeness['satisfied'] if o.dossier else None} "
              f"lint={o.lint.passed if o.lint else None} sink_slots={ev_keys}")

    # --- open check (a): did the model call mcp__reads__* in-turn + sink fill? ---
    tool_calls = [b.get("name") for e in raw_stream for m in e["messages"]
                  if m.get("__type__") == "AssistantMessage"
                  for b in (m.get("content") or [])
                  if isinstance(b, dict) and b.get("__type__") == "ToolUseBlock"]
    reads_called = [n for n in tool_calls if isinstance(n, str) and "reads" in n]

    # --- open check (b): live hook-written Tier-0 read ledger tool_name form ---
    read_entries = [e for e in ledger.entries if e.tier == Tier.ZERO.value
                    and e.tool_name not in ("budget_increment",)]
    read_names = sorted({e.tool_name for e in read_entries})

    # --- metrics (after raw saved) ---
    comp = dossier_completeness_rate(outcomes)
    lint = language_lint_pass_rate(outcomes)

    summary = {
        "pinned_master": "af79296",
        "findings": [(f.finding_id, f.check_id) for f in findings],
        "total_cost_usd": round(result.cost_usd_used, 6),
        "budget_exceeded": result.budget_exceeded,
        "agent_layer_complete": result.agent_layer_complete,
        "pending_count": len(pending),
        "staged": [o.check_id for o in outcomes if o.status == "staged"],
        "tool_calls_seen": tool_calls,
        "reads_called_in_turn": reads_called,
        "read_ledger_tool_names": read_names,
        "dossier_completeness_rate": comp.value,
        "language_lint_pass_rate": lint.value,
    }
    (HERE / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n>>> SUMMARY:", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
