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
from orchestrator.check_partial_exemption import run_partial_exemption_check
from orchestrator.check_scheme_status import run_scheme_status_check
from orchestrator.exceptions import GateFailure
from reasoning.exempt import run_exempt_pass
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
        gst_ledger:       Optional GST control-ledger side-input (T2.24) —
                          {"lines": [...], "declared_boxes": {"output_tax", "input_tax"}}.
                          When supplied, forwarded into run_chain, which runs the
                          ledger<->declared-return internal-consistency reconciliation
                          (a CANDIDATE surface, never a gate). Default None — byte-identical.
        sales_line_source: Optional callable → list of SALES line dicts (T2.30,
                          typically fetch_sales_lines).  When supplied, the
                          exempt-supply reasoning pass (run_exempt_pass) runs
                          beside the chain and its artefact rides the T2.27
                          extra_* seams (steps/exempt-supply-candidates.json;
                          gated extra_candidates).  Default None — the pass is
                          skipped and every reg2627-only run is byte-identical.
    """
    line_source: Callable[[], list[dict]]
    provider: "DocumentProvider | None" = None
    declared_f5: dict | None = None
    analytical_review: bool = False
    # Forward-ref only (never resolved at runtime under `from __future__ import annotations`);
    # qualified like chain.py's run_chain. Default None keeps every existing no-reader
    # construction (run_agent.py, ui/engine_seam.py) byte-identical.
    reader: "sap_b1_server.ChainReader | None" = None
    gst_ledger: dict | None = None
    sales_line_source: "Callable[[], list[dict]] | None" = None
    #: D-2026-09-23-xero-purchase-lines (ruling B2). A SEPARATE, optional purchase line
    #: source for the Reg 26/27 pass, mirroring sales_line_source rather than overloading
    #: `line_source`. Overloading would have been the smaller diff and the worse one:
    #: `line_source` also feeds run_documents_pass below, which on the Xero F5 branch
    #: carries the T-E(2)/D-40 document-context rows (one aggregate per document, no
    #: vat_group). Replacing it would silently re-key the document cross-reference surface
    #: and its coverage count — a shipped, browser-verified surface. Default None means the
    #: reg2627 dispatch falls back to `line_source` exactly as before, so every existing
    #: caller (SAP CLI included) is byte-identical.
    purchase_line_source: "Callable[[], list[dict]] | None" = None
    # t-decision-render (Terry R1 Branch B, STRICTLY BOUNDED): the reviewer-adjudication
    # view, built in api/ (api.viewmodel.build_adjudication_view) and threaded VERBATIM
    # into build_report — a pure data pass-through carrying ZERO logic, structurally
    # identical to the gst_ledger/declared_f5 side-inputs. engine/ never imports the
    # decision layer (tests/test_leaf_import_purity.py). Default None → every existing
    # construction and every decision-free render byte-identical.
    adjudications: dict | None = None


@dataclass
class ReviewResult:
    """Full output of one review() invocation.

    On status="completed" all fields except gate_failure are populated — unless
    review() was called with persist_artifacts=False (M2, t-xero-signoff), where
    report_pdf_path and bundle_dir are None by design (pure review: Phase-5
    render/seal skipped; nothing persisted to disk).
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
        exempt_artefact:      Dict from run_exempt_pass (T2.30).  None when
                              inputs.sales_line_source was not supplied or on
                              halted.  May carry status="errored" on a completed
                              run (non-blocking, mirrors reasoning_artefact).
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
    # T2.30: defaulted so pre-existing construction/consumption stays compatible.
    exempt_artefact: dict | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def review(
    client_config: ClientConfig,
    period: dict,
    inputs: ReviewInputs,
    *,
    persist_artifacts: bool = True,
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
        persist_artifacts: t-xero-signoff (M2). Execution POLICY, keyword-only —
                       deliberately NOT a ReviewInputs field (the T5.8 artifact
                       contract freezes that dataclass's field set; policy is not
                       input data). When False, Phase-5 (build_report/render_pdf/
                       seal_bundle) is skipped entirely: a pure review persisting
                       NO artefact — no unsigned PDF, no unsigned bundle. Plain
                       web uploads pass False; the sign path and every legacy
                       caller keep the default True (SAP/CLI byte-identical).
                       Phases 1-4c are untouched either way (box-isolation:
                       compile_output/gates come from run_chain).

    Returns:
        ReviewResult with status="completed" or status="halted".
        Never raises — GateFailure is caught and returned as
        ReviewResult(status="halted", gate_failure=GateHalt(...)).
    """
    run_started_at = datetime.now(timezone.utc).isoformat()

    # --- Phase 1: Deterministic chain ---

    try:
        compile_output, gate_results = run_chain(
            client_config, period, declared_f5=inputs.declared_f5, reader=inputs.reader,
            gst_ledger=inputs.gst_ledger,
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
    # B2: prefer the dedicated purchase source when one was supplied; otherwise the
    # historical `line_source` (the SAP CLI's fetch_si_purchase_lines). None -> unchanged.
    _reg2627_lines = inputs.purchase_line_source or inputs.line_source
    reasoning_artefact = run_reg2627_pass(period, line_source=_reg2627_lines)
    if reasoning_artefact.get("status") == "errored":
        log.warning(
            "reg2627 pass errored (non-blocking): %s",
            reasoning_artefact.get("error", "")[:120],
        )

    # --- Phase 2b: Exempt-supply reasoning pass (T2.30; optional, never raises) ---

    # Runs beside the chain only when a sales line source is supplied.  Default
    # None skips the pass entirely, keeping every reg2627-only run byte-identical.
    exempt_artefact: dict | None = None
    if inputs.sales_line_source is not None:
        exempt_artefact = run_exempt_pass(
            period, line_source=inputs.sales_line_source
        )
        if exempt_artefact.get("status") == "errored":
            log.warning(
                "exempt-supply pass errored (non-blocking): %s",
                exempt_artefact.get("error", "")[:120],
            )
    # Keyed extra_* mapping for the T2.27 seams; None (not {}) when the pass did
    # not run so build_report/seal_bundle behave byte-identically to pre-T2.30.
    extra_artefacts: dict | None = (
        {"exempt-supply": exempt_artefact} if exempt_artefact is not None else None
    )

    # --- Phase 3: Source-document cross-reference pass (optional) ---

    doc_candidates: list | None = None
    doc_legibility_rows: list | None = None
    if inputs.provider is not None:
        from documents.doc_pass import run_documents_pass  # noqa: PLC0415
        si_lines = inputs.line_source()
        # T2.14: collect "manual review required" rows for illegible documents;
        # they surface on the ungated coverage section, not the gated candidate
        # stream. run_documents_pass skips reconcile for an illegible document.
        doc_legibility_rows = []
        doc_candidates = run_documents_pass(
            si_lines, inputs.provider, period["start"], period["end"],
            legibility_rows=doc_legibility_rows,
        )

    # --- Phase 4: Annual analytical review pass (optional, non-gating) ---

    analytical_review_data: dict | None = None
    if inputs.analytical_review:
        analytical_review_data = run_analytical_review_pass(client_config, period)

    # --- Phase 4b: Deterministic partial-exemption / De Minimis check (Prompt I) ---

    # Self-gated by client_config.actively_makes_exempt_supplies (default False for
    # every shipped client -> returns [] and every existing run is byte-identical).
    # READ-ONLY over compile_output: no box recomputed, no gate touched, cannot halt.
    # Deliberately NOT a ReviewInputs flag and NOT a ReviewResult field (keeps the
    # frozen T5.8 contracts untouched); the finding reaches the working paper via
    # build_report below, ungated like the analytical review.
    partial_exemption_findings = run_partial_exemption_check(
        client_config, compile_output
    )

    # --- Phase 4c: Deterministic scheme-status contradiction check ---

    # Config-vs-data: declared MES/IGDS participation vs ME/IGDS-coded lines.
    # ALWAYS runs (the flags are a predicate input, not a gate); self-silent when
    # no ME/IGDS row exists in the classify inventory (every current frozen run ->
    # [] -> byte-identical). READ-ONLY over compile_output: no box recomputed, no
    # gate touched, cannot halt. Like the partial-exemption check, deliberately
    # NOT a ReviewInputs flag and NOT a ReviewResult field.
    scheme_status_findings = run_scheme_status_check(client_config, compile_output)

    # --- Phase 5: Report + seal (skipped when persist_artifacts=False, M2) ---

    pdf_path: Path | None = None
    bundle_dir: Path | None = None
    if persist_artifacts:
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
            document_legibility_rows=doc_legibility_rows,
            extra_judgment_artefacts=extra_artefacts,
            partial_exemption_findings=(partial_exemption_findings or None),
            scheme_status_findings=(scheme_status_findings or None),
            # t-decision-render: verbatim pass-through of the api-built decision view
            # (ZERO logic here — Terry R1 Branch B bounded seam). None → byte-identical.
            adjudications=inputs.adjudications,
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
            extra_reasoning_artefacts=extra_artefacts,
        )
    else:
        # Pure review: the deterministic result is returned in-memory only. The
        # timestamp is still stamped so the result shape stays uniform.
        run_completed_at = datetime.now(timezone.utc).isoformat()

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
        exempt_artefact=exempt_artefact,
    )
