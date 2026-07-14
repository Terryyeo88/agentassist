"""
tests/fixtures/demo_artifacts_builder.py — T5.8 demo-artifact freezer (BUILD-TIME ONLY).

Runs the REAL case-file loop (agent/loop.py::run_casefile_loop) once over a frozen
deterministic ReviewResult and freezes its outputs — dossiers, PENDING proposals, and
the hash-chained ledger — to ``tests/fixtures/demo-artifacts/*.json``. The T5.8 Streamlit
UI loads ONLY those JSONs; it never runs the loop at render time (the freeze is the
boundary between build-time computation and render-time viewing).

Honesty (mock-first, T5.8):
  * The deterministic core is REAL: ``compile_output`` / ``gate_results`` are copied
    verbatim from the frozen offline-replay oracle
    (tests/fixtures/sbodemosg-extract/_replay-oracle.compiled.json), whose bytes the
    T2.12a offline-replay test proves run_chain reproduces with SAP unreachable.
  * ``reasoning_artefact.candidates`` is EMPTY — the Reg 26/27 reasoning pass is
    token-gated and does not run offline. Any reasoning J+ candidate shown in the demo
    would be crafted, not validated; we surface none rather than fake one.
  * ONE ``document_candidate`` (gst_amount_mismatch) is CRAFTED to exercise the
    probabilistic surface in the queue. It is clearly a demo artefact, not a validated
    finding, and is framed as a candidate only.

Regenerate with:  python -m tests.fixtures.demo_artifacts_builder
(proposal_id / entry_id / created_at carry fresh values on each regen — the
schema-stability test pins field SHAPES, not these values.)

Pure Python + JSON. No network, no SAP, no model, no SDK, no tokens.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from agent.budget import RunBudget
from agent.decision_ledger import (
    KNOWN_ACCEPTED,
    DecisionLedger,
    compute_finding_fingerprint,
)
from agent.loop import (
    FramingEvent,
    ResultEvent,
    ToolUseEvent,
    LoopContext,
    run_casefile_loop,
)
from agent.loop_context import build_vendor_catalog
from agent.ledger import Ledger
from agent.proposals import StagingStore

# FakeTransport / FakeProvider live in the sibling hermetic fixtures module.
from tests.fixtures.agent_loop import FakeProvider, FakeTransport

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ORACLE = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract" / "_replay-oracle.compiled.json"
_OUT_DIR = _REPO_ROOT / "tests" / "fixtures" / "demo-artifacts"

# A crafted (demo-only) document candidate exercising the probabilistic surface.
_CRAFTED_DOC_CANDIDATE = {
    "doc_num": 958,
    "check_id": "gst_amount_mismatch",
    "severity": "MEDIUM",
    "message": "Invoice PDF GST (74.00) appears to differ from the SAP line (70.00).",
    "extracted_value": 74.0,
    "listing_value": 70.0,
    "determinability": "born_digital",
}


def build_review_result() -> dict:
    """Assemble the frozen demo ReviewResult (all 11 ReviewResult fields).

    Deterministic surfaces (compile_output / gate_results) are the real oracle bytes;
    reasoning candidates are empty (token-gated offline); one document candidate is
    crafted for the probabilistic-queue demo.
    """
    oracle = json.loads(_ORACLE.read_text(encoding="utf-8"))
    compile_output = oracle["compile_output"]
    gate_results = oracle["gate_results"]
    fetched_at = compile_output["fetch_manifest"]["fetched_at"]

    return {
        "status": "completed",
        "compile_output": compile_output,
        "gate_results": gate_results,
        "reasoning_artefact": {
            "status": "ok",
            "check": "reg-26-27-disallowed-input-tax",
            "candidates": [],  # token-gated offline — honest empty, never faked
        },
        "document_candidates": [_CRAFTED_DOC_CANDIDATE],
        "analytical_review_data": None,
        "report_pdf_path": None,   # regenerated on the Sign action, never frozen
        "bundle_dir": "audit/sbodemosg/2024Q3/seal-demo-0001",
        "run_started_at": fetched_at,
        "run_completed_at": fetched_at,
        "gate_failure": None,
        "exempt_artefact": None,
    }


# Lint-clean candidate framing (agent/lint.py): carries candidate markers, no verdict.
def _framing(code: str, doc_num) -> str:
    return (
        f"Document {doc_num} ({code}) appears to be a candidate for reviewer "
        "attention; consider reviewing the GST treatment for this item."
    )


def build_scripts(review_result: dict) -> dict:
    """Build a per-finding FakeTransport script for every registered finding.

    E1/E2 require only engine-seeded slots, so a framing turn completes them.
    NO_GST_REG additionally needs the agent-gathered supplier_catalog slot, filled by
    a read_vendor_gst_status read. The crafted document candidate needs document_pdfs,
    filled by a get_source_document read.
    """
    scripts: dict = {}
    issues = review_result["compile_output"]["detect"]["issues"]
    for issue in issues:
        code = issue["error_code"]
        doc_num = issue.get("doc_num")
        finding_id = f"detect:{code}:{doc_num}"
        turn: list = []
        if code == "NO_GST_REG":
            turn.append(ToolUseEvent(
                tool_name="read_vendor_gst_status",
                tool_input={
                    "justification": f"Gather supplier GST status for the {code} case file on doc {doc_num}.",
                    "card_name": issue.get("card_name"),
                    "evidence_slot": "supplier_catalog",
                },
            ))
        turn.append(FramingEvent(text=_framing(code, doc_num)))
        turn.append(ResultEvent(cost_usd=0.004, usage={"input_tokens": 600, "output_tokens": 80}))
        scripts[finding_id] = [turn]

    # Crafted probabilistic document candidate.
    for cand in review_result["document_candidates"]:
        finding_id = f"doc:{cand['check_id']}:{cand['doc_num']}"
        scripts[finding_id] = [[
            ToolUseEvent(
                tool_name="get_source_document",
                tool_input={
                    "justification": f"Read the source invoice PDF to support the {cand['check_id']} case file.",
                    "doc_num": cand["doc_num"],
                    "evidence_slot": "document_pdfs",
                },
            ),
            FramingEvent(text=_framing(cand["check_id"], cand["doc_num"])),
            ResultEvent(cost_usd=0.009, usage={"input_tokens": 700, "output_tokens": 90}),
        ]]
    return scripts


# The seeded prior-period adjudication: a real, genuinely-unregistered NO_GST_REG
# vendor (doc 592, "Far East Imports"). KNOWN_ACCEPTED -> the recurring current finding
# renders DEMOTED + annotated in the panel, yet STILL PRESENT (Invariant 5).
_SEED_ADJUDICATION = {
    "error_code": "NO_GST_REG",
    "card_name": "Far East Imports",
    "reviewer": "Prior-Period Reviewer",
    "reason": "Standing treatment: supplier confirmed not GST-registered; input tax correctly not claimed.",
    "period": "2024Q2",
    "timestamp": "2024-06-30T00:00:00+00:00",
}


def build_decision_ledger(review_result: dict) -> list[dict]:
    """Seed ONE prior-period KNOWN_ACCEPTED entry keyed to a REAL finding's fingerprint.

    The fingerprint is computed from the genuine detect-issue (error_code + card_name),
    so it matches the current-period finding the panel re-keys from the same issue —
    making the demote visible over real data, not a fabricated key. The DecisionLedger is
    append-only + hash-chained; verify() holds over the frozen entry.
    """
    issues = review_result["compile_output"]["detect"]["issues"]
    target = next(
        i for i in issues
        if i.get("error_code") == _SEED_ADJUDICATION["error_code"]
        and i.get("card_name") == _SEED_ADJUDICATION["card_name"]
    )
    ledger = DecisionLedger()
    ledger.append(
        fingerprint=compute_finding_fingerprint(target),
        disposition=KNOWN_ACCEPTED,
        reviewer=_SEED_ADJUDICATION["reviewer"],
        reason=_SEED_ADJUDICATION["reason"],
        period=_SEED_ADJUDICATION["period"],
        timestamp=_SEED_ADJUDICATION["timestamp"],
    )
    return [asdict(e) for e in ledger.entries]


def build_context(review_result: dict) -> LoopContext:
    """Hermetic Tier-0 read sources covering the findings' card_names / doc_nums.

    The vendor catalog is REAL frozen-extract-derived ctx (T5.8c): it is assembled by
    the T5.3h ``build_vendor_catalog`` from tests/fixtures/sbodemosg-extract/
    business-partners.raw.json — not fabricated. The finding card_names are genuinely
    unregistered there (which is why they are NO_GST_REG findings), so the supplier_catalog
    evidence the loop records is real ground truth rather than a placeholder. The source
    document provider stays a ``FakeProvider`` so the crafted probabilistic document
    candidate still has a readable source path. No SAP, no model, no tokens.
    """
    vendor_catalog = build_vendor_catalog()
    provider = FakeProvider({
        cand["doc_num"]: f"tests/fixtures/demo-artifacts/INV-{cand['doc_num']}.txt"
        for cand in review_result["document_candidates"]
    })
    return LoopContext(provider=provider, vendor_catalog=vendor_catalog, prior_period_store={})


def freeze() -> dict:
    """Run the loop once and freeze review_result/dossiers/proposals/ledger to JSON."""
    review_result = build_review_result()
    scripts = build_scripts(review_result)
    ctx = build_context(review_result)
    ledger = Ledger()
    store = StagingStore()
    budget = RunBudget(max_turns=10_000, max_cost_usd=1_000.0)
    transport = FakeTransport(scripts=scripts, ctx=ctx, ledger=ledger)

    result = run_casefile_loop(
        invoke_review=lambda: review_result,
        transport=transport,
        ctx=ctx,
        ledger=ledger,
        budget=budget,
        store=store,
        max_attempts_per_finding=3,
    )

    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    def _dump(name: str, obj) -> None:
        (_OUT_DIR / name).write_text(
            json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    _dump("review_result.json", review_result)
    _dump("dossiers.json", [asdict(d) for d in result.dossiers])
    _dump("proposals.json", [asdict(p) for p in result.proposals])
    _dump("ledger.json", [asdict(e) for e in ledger.entries])
    _dump("decision-ledger.json", build_decision_ledger(review_result))

    summary = {
        "review_status": result.review_status,
        "dossiers": len(result.dossiers),
        "proposals": len(result.proposals),
        "ledger_entries": len(ledger.entries),
        "decision_ledger_entries": len(build_decision_ledger(review_result)),
        "staged": sum(1 for o in result.outcomes if o.status == "staged"),
        "skipped": sum(1 for o in result.outcomes if o.status == "skipped"),
        "incomplete": sum(1 for o in result.outcomes if o.status == "incomplete"),
        "cost_usd_used": result.cost_usd_used,
    }
    return summary


if __name__ == "__main__":
    print(json.dumps(freeze(), indent=2))
