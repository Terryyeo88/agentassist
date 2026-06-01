#!/usr/bin/env python3
"""
run_agent.py — AgentAssist CLI launcher (T1.3 + T1.6 + T1.4).

Usage:
    python run_agent.py --client sbodemosg --period 2024-07-01 2024-09-30
    python run_agent.py --client sbodemosg --period 2024-07-01 2024-09-30 --report
"""
from __future__ import annotations

import argparse
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

from config.loader import ConfigError, load_client_config  # noqa: E402
from orchestrator.chain import run_chain  # noqa: E402
from orchestrator.exceptions import GateFailure  # noqa: E402

_REPORTS_DIR = _REPO_ROOT / "exploration-notes" / "t1.4-reports"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_agent",
        description="AgentAssist — run the T1.6 deterministic GST audit chain.",
    )
    p.add_argument("--client", required=True, metavar="CLIENT_ID",
                   help="Client config stem in config/clients/ (e.g. sbodemosg)")
    p.add_argument("--period", required=True, nargs=2, metavar=("START", "END"),
                   help="Period as two YYYY-MM-DD dates: --period 2024-07-01 2024-09-30")
    p.add_argument("--report", action="store_true",
                   help="Build and write a PDF report after the chain run")
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

    try:
        report, out_path = run_chain(cfg, period)
    except GateFailure as exc:
        print(f"\nCHAIN HALTED: {exc}", file=sys.stderr)
        sys.exit(1)

    # Summary
    box_8 = report["boxes"].get("box_8_net_gst", 0.0)
    total_issues = len(report["issues"])
    print("\n=== CHAIN COMPLETE ===")
    print(f"  Period         : {report['period']['start']} → {report['period']['end']}")
    print(f"  Items examined : {dict(sorted(report['items_examined'].items()))}")
    print(f"  box_8 (net GST): {box_8:,.2f}")
    print(f"  Issues (detect): {total_issues}")
    if report["warnings"]:
        print(f"  Warnings       : {len(report['warnings'])}")
        for w in report["warnings"]:
            print(f"    • {w}")
    print(f"  Output JSON    : {out_path}")

    if args.report:
        # Deferred imports: only needed when --report is passed, avoiding a
        # mandatory reportlab dependency for chain-only runs.
        from report.contract import load_compile_output  # noqa: E402
        from report.report import build_report           # noqa: E402
        from report.render import render_pdf             # noqa: E402

        compile_output = load_compile_output(out_path)
        generated_at: str = compile_output["fetch_manifest"]["fetched_at"]

        # Derive a compact timestamp for the filename from the chain's fetched_at.
        ts = (
            datetime.fromisoformat(generated_at)
            .astimezone(timezone.utc)
            .strftime("%Y%m%d-%H%M%S")
        )
        pdf_path = (
            _REPORTS_DIR
            / f"{args.client}-{period['start']}-{period['end']}-{ts}.pdf"
        )

        print("Building PDF report ...")
        model = build_report(compile_output, cfg, generated_at=generated_at)
        render_pdf(model, pdf_path)
        print(f"  Report PDF     : {pdf_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
