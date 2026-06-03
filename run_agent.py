#!/usr/bin/env python3
"""
run_agent.py — AgentAssist CLI launcher (T1.3 + T1.6 + T1.4 + T1.5 + T2.7).

Every successful run produces a sealed audit bundle under audit/<client_id>/.
No --report flag: the PDF is always generated and included in the bundle.
The Reg 26/27 reasoning pass (T2.7) always runs beside the chain and its
artefact is always sealed into the bundle (status may be "errored").

Usage:
    python run_agent.py --client sbodemosg --period 2024-07-01 2024-09-30
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

from audit_bundle import seal_bundle                      # noqa: E402
from config.loader import ConfigError, load_client_config # noqa: E402
from orchestrator.chain import run_chain                  # noqa: E402
from orchestrator.exceptions import GateFailure           # noqa: E402
from reasoning.reg2627 import run_reg2627_pass            # noqa: E402
from reasoning.sap_lines import fetch_si_purchase_lines   # noqa: E402
from report.report import build_report                    # noqa: E402
from report.render import render_pdf                      # noqa: E402

# Intermediate PDF lives here before being copied into the audit bundle.
# The bundle's report.pdf is the durable copy; this path is ephemeral.
_REPORTS_DIR = _REPO_ROOT / "exploration-notes" / "t1.4-reports"


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
    return p


def main() -> None:
    args = _build_parser().parse_args()
    period = {"start": args.period[0], "end": args.period[1]}

    print(f"Loading config: {args.client}")
    try:
        cfg = load_client_config(args.client, check_connectivity=True)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  company_db={cfg.company_db}  gst_rate={cfg.applicable_gst_rate}")
    print(f"Running chain for period {period['start']} → {period['end']} ...")

    run_started_at = datetime.now(timezone.utc).isoformat()

    try:
        compile_output, gate_results = run_chain(cfg, period)
    except GateFailure as exc:
        # A gate failure means the data did not reconcile — there is no valid
        # review to seal.  Print the gate message and checked values, then halt.
        print(f"\nCHAIN HALTED — gate failed: {exc}", file=sys.stderr)
        if exc.checked:
            print(f"  Gate checked values: {exc.checked}", file=sys.stderr)
        sys.exit(1)

    # Reg 26/27 reasoning pass — runs beside the chain, never inside it.
    # sap_b1_server is already configured by run_chain above.
    print("Running Reg 26/27 reasoning pass ...")

    line_source = functools.partial(fetch_si_purchase_lines, period["start"], period["end"])
    reasoning_artefact = run_reg2627_pass(
        period,
        line_source=line_source,
    )
    r_status = reasoning_artefact.get("status", "unknown")
    r_count = reasoning_artefact.get("candidate_count", 0)
    print(f"  Reg 26/27       : status={r_status}, candidates={r_count}")
    if r_status == "errored":
        print(f"  (pass error: {reasoning_artefact.get('error', '')[:120]})")

    # Summary from CompileOutput
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

    # Build PDF using the same T1.4 wiring as before; generated_at comes from
    # the chain's fetch timestamp so the report timestamp is deterministic.
    generated_at: str = compile_output["fetch_manifest"]["fetched_at"]
    ts = (
        datetime.fromisoformat(generated_at)
        .astimezone(timezone.utc)
        .strftime("%Y%m%d-%H%M%S")
    )
    pdf_path = _REPORTS_DIR / f"{args.client}-{period['start']}-{period['end']}-{ts}.pdf"
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Building PDF report ...")
    model = build_report(compile_output, cfg, generated_at=generated_at)
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
    )

    print(f"\n=== BUNDLE SEALED ===")
    print(f"  Bundle         : {bundle_dir}")
    print(f"  Verify         : python -m audit_bundle.verify {bundle_dir}")

    sys.exit(0)


if __name__ == "__main__":
    main()
