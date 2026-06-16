"""
T5.3-V round 2 (real-ctx) LIVE run — MECHANISM validation, architecture A.

Graduates the round-2 crafted run to REAL data: the case-file loop runs over a REAL
``ReviewResult`` (offline replay of the deterministic chain off the frozen SBODEMOSG
extract, SAP unreachable) and a REAL ``LoopContext`` assembled by T5.3h
``build_loop_context`` (AbsentDocumentProvider + the real S3 vendor catalog). NOT
accuracy-validated (that is T2.11); ``validation_status``/``show_ai_candidates`` stay
frozen.

Option B finding set (Terry, 2026-06-16): the first 3 ``NO_GST_REG`` findings — Acme
Associates (605), Far East Imports (592), SMD Technologies (594) — chosen so the loop
actually exercises the T5.3g ``supplier_catalog`` slot LIVE via ``read_vendor_gst_status``
over the real vendor catalog. ``document_pdfs`` is NOT exercised: the frozen extract ships
no PDFs (AbsentDocumentProvider) and no document-needing finding is in the set.

Evidence discipline: the full raw SDK message stream is tee'd off the real query and
dumped BEFORE any metric is computed.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

# Offline-replay credential stubs (mirror tests/conftest.py) — no real SAP is contacted;
# the chain runs against the frozen extract via the source seam.
os.environ.setdefault("SAP_USERNAME", "_test_stub_no_sap_")
os.environ.setdefault("SAP_PASSWORD", "_test_stub_no_sap_")
os.environ.setdefault("CLIENT_ID", "sbodemosg")
os.environ["AGENT_LIVE_TRANSPORT"] = "1"  # explicit opt-in (token-burning)

from agent.budget import RunBudget
from agent.dossier import extract_findings
from agent.eval.metrics import dossier_completeness_rate, language_lint_pass_rate
from agent.ledger import Ledger
from agent.live_transport import make_live_transport
from agent.loop import run_casefile_loop
from agent.loop_context import build_loop_context
from agent.proposals import StagingStore
from agent.schemas import Tier
from tests.replay_shim import period_from_manifest, replay_review

HERE = Path(__file__).parent
OUT = HERE
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)

# Option B: the three NO_GST_REG card names to run (exercises supplier_catalog live).
SELECTED_CARDS = {"Acme Associates", "Far East Imports", "SMD Technologies"}

# Verbatim system prompt from the merged round-2 crafted run (run_round2.py).
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


def _trim_to_selected(review_result):
    """Return a ReviewResult whose detect.issues are only the SELECTED_CARDS NO_GST_REG."""
    co = dict(review_result.compile_output)
    detect = dict(co.get("detect") or {})
    issues = detect.get("issues") or []
    kept = [i for i in issues
            if i.get("error_code") == "NO_GST_REG" and i.get("card_name") in SELECTED_CARDS]
    detect = {**detect, "issues": kept}
    co = {**co, "detect": detect}
    return dataclasses.replace(review_result, compile_output=co)


def main() -> None:
    period = period_from_manifest()
    full = replay_review(period)
    review = _trim_to_selected(full)

    built = build_loop_context(period, review_result=review)
    ctx = built.ctx
    findings = extract_findings(review)

    ledger = Ledger()
    budget = RunBudget(max_turns=12, max_cost_usd=3.00)
    store = StagingStore()
    transport = make_live_transport(
        ctx=ctx, ledger=ledger, budget=budget, model="claude-opus-4-8",
        system_prompt=SYSTEM_PROMPT, query_fn=_capturing_query(),
    )

    print(f">>> real findings ({len(findings)}): "
          f"{[(f.finding_id, f.check_id, f.payload.get('card_name')) for f in findings]}")
    print(f">>> vendor catalog size: {len(ctx.vendor_catalog)}  "
          f"provider={type(ctx.provider).__name__}")
    print(">>> running LIVE loop (AGENT_LIVE_TRANSPORT=1, max_turns=12, "
          "max_cost_usd=3.00, model=claude-opus-4-8) ...\n")

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
    (RAW / "ledger.json").write_text(
        json.dumps([_ser(e) for e in ledger.entries], indent=2), encoding="utf-8")
    stream_json = json.dumps(raw_stream, indent=2)
    if len(stream_json.encode("utf-8")) < 1_000_000:
        (RAW / "stream.json").write_text(stream_json, encoding="utf-8")
        stream_note = f"saved ({len(stream_json.encode('utf-8'))} bytes)"
    else:
        (RAW / "stream.OMITTED.txt").write_text(
            f"stream.json omitted: {len(stream_json.encode('utf-8'))} bytes > ~1 MB cap.\n",
            encoding="utf-8")
        stream_note = f"OMITTED ({len(stream_json.encode('utf-8'))} bytes > 1 MB)"
    print(f">>> SAVED raw: ledger.json ({len(ledger.entries)} entries); "
          f"stream.json {stream_note}; "
          f"{sum(len(e['messages']) for e in raw_stream)} msgs / {len(raw_stream)} calls")

    if err is not None:
        (OUT / "RUN-ERROR.txt").write_text(err, encoding="utf-8")
        print(f"\n!!! LIVE RUN ERRORED: {err}\n(raw saved for diagnosis)")
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

    # --- in-turn reads + ledger names (cage evidence) ---
    tool_calls = [b.get("name") for e in raw_stream for m in e["messages"]
                  if m.get("__type__") == "AssistantMessage"
                  for b in (m.get("content") or [])
                  if isinstance(b, dict) and b.get("__type__") == "ToolUseBlock"]
    reads_called = [n for n in tool_calls if isinstance(n, str) and "reads" in n]
    denied = [_ser(e) for e in ledger.entries if e.outcome != "allowed"]

    read_entries = [e for e in ledger.entries if e.tier == Tier.ZERO.value
                    and e.tool_name not in ("budget_increment",)]
    read_names = sorted({e.tool_name for e in read_entries})
    tier_counts = {}
    for e in ledger.entries:
        tier_counts[e.tier] = tier_counts.get(e.tier, 0) + 1

    comp = dossier_completeness_rate(outcomes)
    lint = language_lint_pass_rate(outcomes)

    summary = {
        "run": "T5.3-V round 2 (real-ctx, option B)",
        "pinned_master": "19eb62e",
        "model": "claude-opus-4-8",
        "budget": {"max_turns": 12, "max_cost_usd": 3.00},
        "findings": [(f.finding_id, f.check_id, f.payload.get("card_name")) for f in findings],
        "total_cost_usd": round(result.cost_usd_used, 6),
        "budget_exceeded": result.budget_exceeded,
        "agent_layer_complete": result.agent_layer_complete,
        "pending_count": len(pending),
        "staged": [o.check_id for o in outcomes if o.status == "staged"],
        "attempts_per_finding": {o.finding_id: o.attempts for o in outcomes},
        "tool_calls_seen": tool_calls,
        "reads_called_in_turn": reads_called,
        "read_ledger_tool_names": read_names,
        "ledger_tier_counts": tier_counts,
        "denied_entries": denied,
        "dossier_completeness_rate": comp.value,
        "language_lint_pass_rate": lint.value,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n>>> SUMMARY:", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
