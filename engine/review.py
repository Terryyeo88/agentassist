"""
engine/review.py — Full GST review pipeline seam (T5.1).

Exposes the complete AgentAssist GST review pipeline as one atomic callable:

    review(client_config, period, inputs) -> ReviewResult

The function composes the existing pipeline pieces in the existing order —
no logic changes to chain/gates/report/seal/reasoning:

    1. run_chain             — deterministic audit chain (fetches SAP, runs
                               five gates, compiles CompileOutput)
    2. run_reg2627_pass      — Reg 26/27 disallowed input-tax reasoning pass
                               (runs beside the chain; never raises; a
                               status="errored" artefact still seals normally)
    3. run_documents_pass    — source-document cross-reference pass (optional;
                               only when inputs.provider is not None)
    4. run_analytical_review_pass  — TP/TS ratio pass (optional; only when
                               inputs.analytical_review is True)
    5. build_report / render_pdf   — signed PDF report
    6. seal_bundle           — tamper-evident audit bundle

Agent-layer failure (Invariant 7) is preserved: a status="errored" reasoning
artefact is logged and forwarded to seal; the bundle still completes.

On GateFailure the function returns ReviewResult(status="halted") — it never
re-raises.  The thin CLI (run_agent.py) reads result.gate_failure to reproduce
the exact prior stderr output.

Dependency direction: engine/ -> orchestrator/ (never the reverse).
orchestrator/ must not import engine/.

Module-level _REPORTS_DIR is monkeypatchable by tests without touching the
function signature.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from audit_bundle import seal_bundle
from config.loader import ClientConfig
from orchestrator.chain import run_chain
from orchestrator.check_analytical_review import run_analytical_review_pass
from orchestrator.exceptions import GateFailure
from reasoning.reg2627 import run_reg2627_pass
from report.report import build_report
from report.render import render_pdf

if TYPE_CHECKING:
    from documents.provider import DocumentProvider
    # Type-only (never imported at runtime): the structural ChainReader Protocol lives in the
    # custom MCP server, which orchestrator.chain puts on sys.path. Mirrors chain.py's annotation.
    import sap_b1_server  # noqa: F401

log = logging.getLogger(__name__)

# Intermediate PDF directory — exists before the bundle is sealed.
# The bundle's report.pdf is the durable copy; this path is ephemeral.
# Module-level so tests can redirect via monkeypatch without changing signature.
_REPORTS_DIR = Path(__file__).resolve().parent.parent / "exploration-notes" / "t1.4-reports"


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class GateHalt:
    """Plain serialisable record produced when a gate halts the chain.

    Extracted from GateFailure so ReviewResult carries no live exception object
    and remains fully serialisable.

    Attributes:
        message: Human-readable gate failure description (str(exc)).
        checked: Dict of values the gate inspected (exc.checked).
    """
    message: str
    checked: dict


@dataclass
class ReviewInputs:
    """Source-adapter descriptor for one review invocation.

    Carries the injectable callables and optional inputs that control the
    non-chain parts of the pipeline.  client_config is a separate positional
    argument to review(); ReviewInputs covers the adapter boundary.

    The line_source callable is the forward-compatibility seam for T2.12:
    today it wraps fetch_si_purchase_lines; a T2.12 CSV/Excel adapter
    substitutes a different callable without changing review()'s signature.

    Attributes:
        line_source:      Callable → list[dict].  Returns purchase invoice line
                          dicts for the period (used by the Reg 26/27 pass and,
                          when provider is set, the documents pass).
                          Required keys per line: doc_num, doc_type, doc_date,
                          card_name, line_index, vat_group, line_description,
                          line_total, tax_total.
        provider:         Optional DocumentProvider.  When not None, the source-
                          document cross-reference pass runs.  When None, the
                          pass is skipped and document_candidates=None in the
                          result.
        declared_f5:      Optional validated declared-F5 dict from
                          check_declared_f5.load_declared_f5().  When supplied,
                          Check A and Check B run inside run_chain and their
                          findings appear in compile_output["declared_f5_findings"].
        analytical_review: When True, run_analytical_review_pass is called and
                          its output appears in result.analytical_review_data.
        reader:           Optional ChainReader (T2.12/T2.23 structural feeder, e.g.
                          ExtractChainReader / XeroF5ChainReader) threaded into
                          run_chain so an uploaded client export drives the
                          deterministic chain.  Default None — the live-SAP path is
                          byte-identical (run_chain's _reader_kw collapses to {}).
    """
    line_source: Callable[[], list[dict]]
    provider: "DocumentProvider | None" = None
    declared_f5: dict | None = None
    analytical_review: bool = False
    # Forward-ref only (never resolved at runtime under `from __future__ import annotations`);
    # qualified like chain.py's run_chain. Default None keeps every existing no-reader
    # construction (run_agent.py, ui/engine_seam.py) byte-identical.
    reader: "sap_b1_server.ChainReader | None" = None


@dataclass
class ReviewResult:
    """Full output of one review() invocation.

    On status="completed" all fields except gate_failure are populated.
    On status="halted" (GateFailure): compile_output, gate_results,
    reasoning_artefact, document_candidates, analytical_review_data,
    report_pdf_path, bundle_dir, and run_completed_at are all None.

    Attributes:
        status:               "completed" or "halted".
        compile_output:       CompileOutput dict from run_chain.  None on halted.
        gate_results:         Gate results dict from run_chain.  None on halted
                              (chain raises before returning).
        reasoning_artefact:   Dict from run_reg2627_pass.  May carry
                              status="errored" on a completed run (non-blocking).
                              None on halted.
        document_candidates:  List from run_documents_pass; None when no provider
                              was supplied or on halted.
        analytical_review_data: Dict from run_analytical_review_pass; None when
                              inputs.analytical_review=False or on halted.
        report_pdf_path:      Absolute path to the intermediate PDF.  None on
                              halted.
        bundle_dir:           Absolute path to the sealed bundle dir.  None on
                              halted.
        run_started_at:       ISO-8601 UTC timestamp captured before run_chain.
                              Always set.
        run_completed_at:     ISO-8601 UTC timestamp captured after render_pdf,
                              before seal_bundle.  None on halted.
        gate_failure:         GateHalt(message, checked) on halted; None on
                              completed.
    """
    status: str
    compile_output: dict | None
    gate_results: dict | None
    reasoning_artefact: dict | None
    document_candidates: list | None
    analytical_review_data: dict | None
    report_pdf_path: Path | None
    bundle_dir: Path | None
    run_started_at: str
    run_completed_at: str | None
    gate_failure: GateHalt | None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def review(
    client_config: ClientConfig,
    period: dict,
    inputs: ReviewInputs,
) -> ReviewResult:
    """Run the full GST review pipeline and return a ReviewResult.

    Composes run_chain → run_reg2627_pass → (run_documents_pass) →
    (run_analytical_review_pass) → build_report/render_pdf → seal_bundle
    in that order, exactly as run_agent.py did before T5.1.

    This function is SILENT — it never prints to stdout or stderr.
    The caller (run_agent.py thin CLI) is responsible for all terminal output,
    reading from the returned ReviewResult.

    Args:
        client_config: Validated ClientConfig from config.loader.
        period:        {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}.
        inputs:        ReviewInputs descriptor carrying the source-adapter
                       callables and optional inputs for this run.

    Returns:
        ReviewResult with status="completed" or status="halted".
        Never raises — GateFailure is caught and returned as
        ReviewResult(status="halted", gate_failure=GateHalt(...)).
    """
    run_started_at = datetime.now(timezone.utc).isoformat()

    # --- Phase 1: Deterministic chain ---

    try:
        compile_output, gate_results = run_chain(
            client_config, period, declared_f5=inputs.declared_f5, reader=inputs.reader
        )
    except GateFailure as exc:
        return ReviewResult(
            status="halted",
            compile_output=None,
            gate_results=None,
            reasoning_artefact=None,
            document_candidates=None,
            analytical_review_data=None,
            report_pdf_path=None,
            bundle_dir=None,
            run_started_at=run_started_at,
            run_completed_at=None,
            gate_failure=GateHalt(message=str(exc), checked=exc.checked),
        )

    # --- Phase 2: Reg 26/27 reasoning pass (never raises; non-blocking) ---

    # sap_b1_server is already configured by run_chain above.
    reasoning_artefact = run_reg2627_pass(period, line_source=inputs.line_source)
    if reasoning_artefact.get("status") == "errored":
        log.warning(
            "reg2627 pass errored (non-blocking): %s",
            reasoning_artefact.get("error", "")[:120],
        )

    # --- Phase 3: Source-document cross-reference pass (optional) ---

    doc_candidates: list | None = None
    if inputs.provider is not None:
        from documents.doc_pass import run_documents_pass  # noqa: PLC0415
        si_lines = inputs.line_source()
        doc_candidates = run_documents_pass(
            si_lines, inputs.provider, period["start"], period["end"]
        )

    # --- Phase 4: Annual analytical review pass (optional, non-gating) ---

    analytical_review_data: dict | None = None
    if inputs.analytical_review:
        analytical_review_data = run_analytical_review_pass(client_config, period)

    # --- Phase 5: Report + seal ---

    generated_at: str = compile_output["fetch_manifest"]["fetched_at"]
    ts = (
        datetime.fromisoformat(generated_at)
        .astimezone(timezone.utc)
        .strftime("%Y%m%d-%H%M%S")
    )

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = _REPORTS_DIR / (
        f"{client_config.client_id}-{period['start']}-{period['end']}-{ts}.pdf"
    )

    model = build_report(
        compile_output, client_config,
        generated_at=generated_at,
        judgment_artefact=reasoning_artefact,
        document_candidates=doc_candidates,
        analytical_review_data=analytical_review_data,
    )
    render_pdf(model, pdf_path)

    run_completed_at = datetime.now(timezone.utc).isoformat()

    bundle_dir = seal_bundle(
        client_config=client_config,
        period=period,
        compile_output=compile_output,
        gate_results=gate_results,
        report_pdf_path=pdf_path,
        run_started_at=run_started_at,
        run_completed_at=run_completed_at,
        reasoning_artefact=reasoning_artefact,
        declared_f5=inputs.declared_f5,
    )

    return ReviewResult(
        status="completed",
        compile_output=compile_output,
        gate_results=gate_results,
        reasoning_artefact=reasoning_artefact,
        document_candidates=doc_candidates,
        analytical_review_data=analytical_review_data,
        report_pdf_path=pdf_path,
        bundle_dir=bundle_dir,
        run_started_at=run_started_at,
        run_completed_at=run_completed_at,
        gate_failure=None,
    )
