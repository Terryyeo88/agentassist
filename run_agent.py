#!/usr/bin/env python3
"""
run_agent.py — AgentAssist CLI launcher (T5.1 thin CLI).

Thin CLI wrapper around engine.review.review().  Parses arguments, loads
the client config, builds a ReviewInputs descriptor, and calls review().
All terminal output is printed from the returned ReviewResult — review()
itself is silent.

Observable behavior is content-equivalent to the prior inline wiring:
  - Same printed lines appear (status, box_8, issues, bundle path, verify cmd)
  - Same exit codes (0 on success, 1 on ConfigError / GateFailure / bad input)
  - Mid-run progress lines (Reg 26/27, documents, analytical review) print from
    ReviewResult fields after review() returns, not mid-pipeline
  - Existing substring-based tests pass unchanged

CLI Args:
    --client CLIENT_ID   Config stem inside config/clients/ (e.g. sbodemosg).
    --period START END   Inclusive date range as two ISO-8601 YYYY-MM-DD
                         strings (e.g. 2024-07-01 2024-09-30).
    --show-ai-candidates Override YAML show_ai_candidates flag for this run.
    --upload-dir DIR     Wire CompositeProvider for source-document pass.
    --declared-f5 FILE   Path to declared-f5.json for Check A/B.
    --analytical-review  Run annual TP/TS ratio pass (T2.16).

Returns:
    Exits 0 on success; exits 1 on ConfigError, GateFailure, or bad input.
"""
from __future__ import annotations

import argparse
import functools
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config.loader import ConfigError, load_client_config          # noqa: E402
from engine.review import ReviewInputs, review                     # noqa: E402
from orchestrator.check_declared_f5 import load_declared_f5        # noqa: E402
from reasoning.sap_lines import fetch_sales_lines, fetch_si_purchase_lines  # noqa: E402


# The gst_ledger assembly is shared with the web layer (api/app.py) — a single source of
# truth so CLI and web build the side-input identically. Re-exported here so existing
# run_agent.build_gst_ledger_input callers/tests are unaffected.
from gst_ledger_input import build_gst_ledger_input  # noqa: E402,F401


def _build_parser() -> argparse.ArgumentParser:
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
        help="Render the AI-surfaced candidates subsection in the PDF report.",
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
            "(T2.9) and seals the declared figures as inputs/declared-f5.json."
        ),
    )
    p.add_argument(
        "--analytical-review", action="store_true", default=False,
        help=(
            "Run the annual analytical review pass (T2.16): compute the FY TP/TS "
            "ratio across four quarterly SAP reads and surface a candidate when the "
            "ratio exceeds the IRAS 1.2 threshold."
        ),
    )
    p.add_argument(
        "--gst-ledger", default=None, metavar="FILE",
        help=(
            "Path to a Xero GST control-account (820) 'Account Transactions' .xlsx export. "
            "With --xero-f5, runs the T2.24 ledger<->declared-return internal-consistency "
            "reconciliation (Signal A) + the not-included raw-GL drop surface (Signal B). "
            "Requires --xero-f5 (the declared boxes are read from it)."
        ),
    )
    p.add_argument(
        "--xero-f5", default=None, metavar="FILE",
        help=(
            "Path to the Xero IRAS-F5 .xlsx workbook (the 'Return' sheet supplies declared "
            "Box 6/7; the 'Transactions not included' section supplies Signal B). Its own "
            "period line is validated against --period (which stays authoritative)."
        ),
    )
    return p


def main(*, provider=None) -> None:
    """Entry point — parse CLI args, build ReviewInputs, call review(), print results.

    Args:
        provider: Optional DocumentProvider injected by tests or callers that
                  pre-build a provider.  When None and --upload-dir is set, a
                  CompositeProvider is built from the CLI argument.

    Raises:
        SystemExit(1): On ConfigError, bad declared-f5 input, or GateFailure.
        SystemExit(0): On successful seal.
    """
    args = _build_parser().parse_args()
    period = {"start": args.period[0], "end": args.period[1]}

    # --- Config load ---

    print(f"Loading config: {args.client}")
    try:
        cfg = load_client_config(args.client, check_connectivity=True)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.show_ai_candidates:
        cfg.show_ai_candidates = True

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

    # --- Declared F5 input (optional) ---

    declared_f5 = None
    if args.declared_f5 is not None:
        try:
            declared_f5 = load_declared_f5(Path(args.declared_f5), period)
            print(f"  Declared F5      : loaded from {args.declared_f5}")
        except (FileNotFoundError, ValueError) as exc:
            print(f"DECLARED-F5 ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    # --- GST control-ledger recon input (optional, T2.24) ---

    gst_ledger = None
    if args.gst_ledger is not None:
        if args.xero_f5 is None:
            print(
                "GST-LEDGER ERROR: --gst-ledger requires --xero-f5 (declared boxes are read "
                "from the F5 workbook's Return sheet).",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            gst_ledger = build_gst_ledger_input(
                Path(args.gst_ledger), Path(args.xero_f5), period
            )
            print(f"  GST ledger recon : {args.gst_ledger} + {args.xero_f5}")
        except (FileNotFoundError, ValueError) as exc:
            print(f"GST-LEDGER ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    # --- Build inputs and call review() ---

    line_source = functools.partial(fetch_si_purchase_lines, period["start"], period["end"])
    # T2.30: sales line source for the exempt-supply pass. The pass runs beside
    # the chain; its stream stays hidden while show_ai_candidates=False.
    sales_line_source = functools.partial(fetch_sales_lines, period["start"], period["end"])
    inputs = ReviewInputs(
        line_source=line_source,
        provider=provider,
        declared_f5=declared_f5,
        analytical_review=args.analytical_review,
        gst_ledger=gst_ledger,
        sales_line_source=sales_line_source,
    )

    print(f"Running chain for period {period['start']} → {period['end']} ...")

    result = review(cfg, period, inputs)

    # --- Handle halted path ---

    if result.status == "halted":
        gf = result.gate_failure
        print(f"\nCHAIN HALTED — gate failed: {gf.message}", file=sys.stderr)
        if gf.checked:
            print(f"  Gate checked values: {gf.checked}", file=sys.stderr)
        sys.exit(1)

    # --- Print content-equivalent progress from ReviewResult fields ---
    # review() is silent; these lines appear after the pipeline completes.
    # stdout is content-equivalent to the prior inline wiring (same lines,
    # same exit codes); mid-run lines now print at the end rather than
    # mid-execution.

    r_status = result.reasoning_artefact.get("status", "unknown")
    r_count = result.reasoning_artefact.get("candidate_count", 0)
    print("Running Reg 26/27 reasoning pass ...")
    print(f"  Reg 26/27       : status={r_status}, candidates={r_count}")
    if r_status == "errored":
        print(f"  (pass error: {result.reasoning_artefact.get('error', '')[:120]})")

    if result.document_candidates is not None:
        print("Running source-document cross-reference pass ...")
        print(f"  Source documents: {len(result.document_candidates)} candidate(s)")

    if result.analytical_review_data is not None:
        print("Running annual analytical review pass (ASK Step 1.3d) ...")
        ratio = result.analytical_review_data.get("ratio") or "—"
        nf = len(result.analytical_review_data.get("findings", []))
        print(f"  TP/TS ratio    : {ratio}  findings={nf}")

    compile_output = result.compile_output
    boxes = compile_output["calculate"]["boxes"]
    box_8 = boxes.get("box_8_net_gst", 0.0)
    total_issues = len(compile_output["detect"]["issues"])
    warnings = compile_output["surfaced_warnings"]

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

    print("Building PDF report ...")
    print(f"  Report PDF     : {result.report_pdf_path}")

    print("Sealing audit bundle ...")

    bundle_dir = result.bundle_dir
    print(f"\n=== BUNDLE SEALED ===")
    print(f"  Bundle         : {bundle_dir}")
    print(f"  Verify         : python -m audit_bundle.verify {bundle_dir}")

    sys.exit(0)


if __name__ == "__main__":
    main()
