#!/usr/bin/env python3
"""
run_agent.py — AgentAssist CLI launcher (T1.3 + T1.6 + T1.4 + T1.5 + T2.7).

Orchestrates a complete GST audit run for a single client and period.  The
script drives four sequential phases:

  1. Load the client config and verify SAP B1 connectivity.
  2. Execute the deterministic GST audit chain, which fetches SAP documents,
     detects issues, calculates GST box values, and enforces reconciliation
     gates.
  3. Run the Reg 26/27 reasoning pass (T2.7) in parallel-logical isolation —
     it reads its own line data directly from SAP rather than consuming chain
     output, so a reasoning failure never blocks sealing.
  4. Build a signed PDF report and seal the entire artefact set into a
     tamper-evident audit bundle under audit/<client_id>/.

Every successful run produces a sealed bundle regardless of whether issues
were detected; only a GateFailure (irreconcilable data) or ConfigError
(missing/invalid config) will prevent sealing.

CLI Args:
    --client CLIENT_ID   Config stem inside config/clients/ (e.g. sbodemosg).
    --period START END   Inclusive date range as two ISO-8601 YYYY-MM-DD
                         strings (e.g. 2024-07-01 2024-09-30).

Returns:
    Exits 0 on success; exits 1 on ConfigError or GateFailure.

Raises:
    SystemExit: Always — 0 for success, 1 for a handled fatal error.

Example:
    python run_agent.py --client sbodemosg --period 2024-07-01 2024-09-30

Dependencies:
    audit_bundle        Tamper-evident bundle writer and verifier (T1.5).
    config.loader       Client YAML config loader with connectivity check.
    orchestrator.chain  Deterministic GST audit chain (T1.3 / T1.6).
    reasoning.reg2627   Reg 26/27 multi-model reasoning pass (T2.7).
    reasoning.sap_lines SAP B1 SI/purchase-line fetcher used by T2.7.
    report.report       ReportModel builder (T1.4).
    report.render       Weasyprint PDF renderer (T1.4).
    python-dotenv       Loads .env before any module reads os.environ.
"""
from __future__ import annotations

import argparse
import functools
import sys
from datetime import datetime, timezone
from pathlib import Path

# Load .env before any module that reads os.environ at import time.
from dotenv import load_dotenv
load_dotenv()

# Repo root on path for config.loader and orchestrator imports.
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from audit_bundle import seal_bundle                                      # noqa: E402
from config.loader import ConfigError, load_client_config                 # noqa: E402
from orchestrator.chain import run_chain                                  # noqa: E402
from orchestrator.check_declared_f5 import load_declared_f5               # noqa: E402
from orchestrator.exceptions import GateFailure                           # noqa: E402
from reasoning.reg2627 import run_reg2627_pass            # noqa: E402
from reasoning.sap_lines import fetch_si_purchase_lines   # noqa: E402
from report.report import build_report                    # noqa: E402
from report.render import render_pdf                      # noqa: E402

# Intermediate PDF lives here before being copied into the audit bundle.
# The bundle's report.pdf is the durable copy; this path is ephemeral.
_REPORTS_DIR = _REPO_ROOT / "exploration-notes" / "t1.4-reports"


def _build_parser() -> argparse.ArgumentParser:
    """Construct and return the CLI argument parser for run_agent.

    Returns:
        argparse.ArgumentParser: Configured parser with --client and --period
            arguments.  No parsing is performed here; call parse_args() on
            the returned object.
    """
    p = argparse.ArgumentParser(
        prog="run_agent",
        description=(
            "AgentAssist — run the deterministic GST audit chain and seal "
            "a tamper-evident audit bundle."
        ),
    )
    p.add_argument("--client", required=True, metavar="CLIENT_ID",
                   help="Client config stem in config/clients/ (e.g. sbodemosg)")
    p.add_argument("--period", required=True, nargs=2, metavar=("START", "END"),
                   help="Period as two YYYY-MM-DD dates: --period 2024-07-01 2024-09-30")
    p.add_argument(
        "--show-ai-candidates", action="store_true", default=False,
        help=(
            "Render the AI-surfaced candidates subsection in the PDF report.  "
            "Overrides the client YAML show_ai_candidates flag for this run."
        ),
    )
    p.add_argument(
        "--upload-dir", default=None, metavar="DIR",
        help=(
            "Directory containing INV-<docnum>.pdf files.  When provided, wires "
            "CompositeProvider([B1AttachmentProvider, UploadProvider(DIR)]) so the "
            "source-document cross-reference pass runs against the seeded PDFs."
        ),
    )
    p.add_argument(
        "--declared-f5", default=None, metavar="FILE",
        help=(
            "Path to a declared-f5.json file containing the client's manually-filed "
            "F5 box values.  When provided, runs the declared-vs-computed checks "
            "(T2.9) and seals the declared figures as inputs/declared-f5.json.  "
            "Divergences surface as findings; the run always seals normally."
        ),
    )
    return p


def main(*, provider=None) -> None:
    """Entry point — parse CLI args then drive all four audit phases to completion.

    Phases:
        1. Config load   — validate the client YAML and check SAP connectivity.
        2. Chain run     — fetch SAP documents, detect issues, calculate boxes,
                           enforce reconciliation gates.
        3. Reasoning     — Reg 26/27 T2.7 pass against raw SAP line data.
        3b. Documents    — Source-document cross-reference pass (optional; runs
                           only when a DocumentProvider is supplied via the
                           provider kwarg; wired in Prompt 5).
        4. Report + seal — render signed PDF then write tamper-evident bundle.

    Args:
        provider: Optional DocumentProvider.  When not None, run_documents_pass
                  is called over the SI line items and the resulting candidates
                  are forwarded to build_report().  Defaults to None so CLI
                  invocations and all existing callers are unaffected until
                  Prompt 5 wires a live provider.

    Raises:
        SystemExit(1): On ConfigError (bad/missing client config) or GateFailure
            (chain reconciliation failed — no valid review to seal).
        SystemExit(0): On successful seal.
    """
    args = _build_parser().parse_args()
    period = {"start": args.period[0], "end": args.period[1]}

    # --- Phase 1: Config load ---

    print(f"Loading config: {args.client}")
    try:
        cfg = load_client_config(args.client, check_connectivity=True)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # --show-ai-candidates overrides the YAML flag for this run only.
    if args.show_ai_candidates:
        cfg.show_ai_candidates = True

    # --upload-dir wires CompositeProvider([B1AttachmentProvider, UploadProvider]).
    # Only applies when no provider was injected via the kwarg (existing callers).
    if provider is None and args.upload_dir is not None:
        from documents.provider import (  # noqa: PLC0415
            B1AttachmentProvider,
            CompositeProvider,
            UploadProvider,
        )
        provider = CompositeProvider([
            B1AttachmentProvider(cfg),
            UploadProvider(Path(args.upload_dir)),
        ])
        print(f"  DocumentProvider: CompositeProvider([B1Attachment, Upload({args.upload_dir})])")

    print(f"  company_db={cfg.company_db}  gst_rate={cfg.applicable_gst_rate}")

    # --- T2.9: Load declared F5 input (optional) ---

    declared_f5 = None
    if args.declared_f5 is not None:
        try:
            declared_f5 = load_declared_f5(Path(args.declared_f5), period)
            print(f"  Declared F5      : loaded from {args.declared_f5}")
        except (FileNotFoundError, ValueError) as exc:
            print(f"DECLARED-F5 ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    print(f"Running chain for period {period['start']} → {period['end']} ...")

    # Capture wall-clock start before any chain I/O so the bundle's run window
    # covers the full execution, including SAP fetch latency.
    run_started_at = datetime.now(timezone.utc).isoformat()

    # --- Phase 2: Chain run ---

    try:
        compile_output, gate_results = run_chain(cfg, period, declared_f5=declared_f5)
    except GateFailure as exc:
        # A gate failure means the data did not reconcile — there is no valid
        # review to seal.  Print the gate message and checked values, then halt.
        print(f"\nCHAIN HALTED — gate failed: {exc}", file=sys.stderr)
        if exc.checked:
            print(f"  Gate checked values: {exc.checked}", file=sys.stderr)
        sys.exit(1)

    # --- Phase 3: Reg 26/27 reasoning pass ---

    # Reg 26/27 reasoning pass — runs beside the chain, never inside it.
    # sap_b1_server is already configured by run_chain above.
    print("Running Reg 26/27 reasoning pass ...")

    # Wrap the line fetcher with the period dates pre-applied so run_reg2627_pass
    # can call it without needing to know about the CLI period values.
    line_source = functools.partial(fetch_si_purchase_lines, period["start"], period["end"])
    reasoning_artefact = run_reg2627_pass(
        period,
        line_source=line_source,
    )
    r_status = reasoning_artefact.get("status", "unknown")
    r_count = reasoning_artefact.get("candidate_count", 0)
    print(f"  Reg 26/27       : status={r_status}, candidates={r_count}")
    if r_status == "errored":
        # Truncate the error string to avoid flooding the terminal; full
        # detail is preserved inside the sealed bundle artefact.
        print(f"  (pass error: {reasoning_artefact.get('error', '')[:120]})")

    # --- Phase 3b: Source-document cross-reference pass (optional) ---

    # provider=None (default) means the documents pass does not run and the
    # unified report section will note "source documents: not examined."
    # Prompt 5 will wire a live B1AttachmentProvider here.
    doc_candidates: list | None = None
    if provider is not None:
        print("Running source-document cross-reference pass ...")
        from documents.doc_pass import run_documents_pass  # noqa: PLC0415
        si_lines = line_source()  # fetches SI lines from SAP for document joining
        doc_candidates = run_documents_pass(
            si_lines, provider, period["start"], period["end"]
        )
        print(f"  Source documents: {len(doc_candidates)} candidate(s)")

    # --- Phase 4: Report + seal ---

    # Summary from CompileOutput
    boxes = compile_output["calculate"]["boxes"]
    box_8 = boxes.get("box_8_net_gst", 0.0)
    total_issues = len(compile_output["detect"]["issues"])
    warnings = compile_output["surfaced_warnings"]

    # Tally how many documents of each type were processed during the fetch
    # phase so the operator can quickly spot missing or unexpected doc classes.
    items_examined: dict[str, int] = {}
    for r in compile_output["fetch_manifest"]["records"]:
        items_examined[r["doc_type"]] = items_examined.get(r["doc_type"], 0) + 1

    print("\n=== CHAIN COMPLETE ===")
    print(f"  Period         : {compile_output['period']['start']} → {compile_output['period']['end']}")
    print(f"  Items examined : {dict(sorted(items_examined.items()))}")
    print(f"  box_8 (net GST): {box_8:,.2f}")
    print(f"  Issues (detect): {total_issues}")
    if warnings:
        print(f"  Warnings       : {len(warnings)}")
        for w in warnings:
            print(f"    • {w}")
    df5_findings = compile_output.get("declared_f5_findings") or []
    if df5_findings:
        print(f"  Decl-F5 findings: {len(df5_findings)}")
        for f in df5_findings:
            ftype = f.get("finding_type", "")
            box = f.get("box", "")
            delta = f.get("delta", "")
            print(f"    • [{f.get('check')}] {ftype} box={box} delta={delta}")

    # Build PDF using the same T1.4 wiring as before; generated_at comes from
    # the chain's fetch timestamp so the report timestamp is deterministic.
    generated_at: str = compile_output["fetch_manifest"]["fetched_at"]

    # Convert the ISO-8601 fetch timestamp to a compact UTC string suitable
    # for embedding in a filename without colons (which are illegal on Windows).
    ts = (
        datetime.fromisoformat(generated_at)
        .astimezone(timezone.utc)
        .strftime("%Y%m%d-%H%M%S")
    )
    pdf_path = _REPORTS_DIR / f"{args.client}-{period['start']}-{period['end']}-{ts}.pdf"

    # exist_ok=True because a prior interrupted run may have created the dir.
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Building PDF report ...")
    model = build_report(compile_output, cfg, generated_at=generated_at,
                         judgment_artefact=reasoning_artefact,
                         document_candidates=doc_candidates)
    render_pdf(model, pdf_path)
    print(f"  Report PDF     : {pdf_path}")

    run_completed_at = datetime.now(timezone.utc).isoformat()

    # Seal — writes the bundle and marks it read-only.
    print("Sealing audit bundle ...")
    bundle_dir = seal_bundle(
        client_config=cfg,
        period=period,
        compile_output=compile_output,
        gate_results=gate_results,
        report_pdf_path=pdf_path,
        run_started_at=run_started_at,
        run_completed_at=run_completed_at,
        reasoning_artefact=reasoning_artefact,
        declared_f5=declared_f5,
    )

    print(f"\n=== BUNDLE SEALED ===")
    print(f"  Bundle         : {bundle_dir}")
    print(f"  Verify         : python -m audit_bundle.verify {bundle_dir}")

    sys.exit(0)


if __name__ == "__main__":
    main()
