"""T2.30 live MECHANISM demo — exempt-supply pass over frozen SBODEMOSG ES33 lines.

Runs the REAL run_exempt_pass (live Anthropic model via the pass's own
default_llm_call) over:
  * the frozen SBODEMOSG sales lines carrying an exempt code (ES33 — the frozen
    extract contains no ESN33 line, recorded honestly), extracted through the
    real reasoning/sap_lines._extract_sales_lines code path; PLUS
  * ONE crafted trap line: "OFFICE UNIT LEASE Q3" coded ES33 (slice §4
    commercial-property trap; §7 worked example).

The raw artefact is saved to raw-candidates.json BEFORE any inspection.

This is EVIDENCE OF MECHANISM ("a §4-trap description produces a candidate"),
NOT an accuracy claim: no labels, no scoring, no gate. T2.11 unmoved.

Run from the repo root:  python exploration-notes/t2.30-exempt-demo/run_live_demo.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

from reasoning.exempt import run_exempt_pass  # noqa: E402
from reasoning.sap_lines import _extract_sales_lines  # noqa: E402

_OUT = Path(__file__).resolve().parent / "raw-candidates.json"
_EXTRACT = _ROOT / "tests" / "fixtures" / "sbodemosg-extract"
_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}

# The crafted §4 trap line (slice §7 worked example: commercial property is not
# exempt).  Coded ES33 so the frozenset filter selects it.
_TRAP_LINE = {
    "doc_num": 99001,
    "doc_type": "sales_invoice",
    "doc_date": "2024-08-15",
    "card_name": "DEMO TENANT PTE LTD",
    "line_index": 0,
    "vat_group": "ES33",
    "line_description": "OFFICE UNIT LEASE Q3",
    "line_total": 12000.0,
    "tax_total": 0.0,
}


def _identity_norm(raw):
    # SAP B1 behaviour: empty mappings -> raw code unchanged (codes are canonical).
    return str(raw or "").strip()


def _frozen_exempt_lines() -> list[dict]:
    """Extract the exempt-coded sales lines from the frozen extract via the
    REAL extraction path, then keep only ES33/ESN33 lines (the pass would
    filter anyway; kept small for a cheap single-batch call)."""
    lines: list[dict] = []
    for name, doc_type in (("invoices.raw.json", "sales_invoice"),
                           ("credit-notes.raw.json", "sales_credit_note")):
        docs = json.loads((_EXTRACT / name).read_text(encoding="utf-8"))
        lines.extend(_extract_sales_lines(docs, doc_type, normalize=_identity_norm))
    return [ln for ln in lines if ln["vat_group"] in ("ES33", "ESN33")]


def main() -> int:
    # .env may live in the primary checkout rather than a build worktree —
    # try the repo root first, then the sibling main checkout.
    for env_path in (_ROOT / ".env", _ROOT.parent / "sap-b1-ai-agent" / ".env"):
        if env_path.exists():
            load_dotenv(env_path)
            break

    frozen = _frozen_exempt_lines()
    all_lines = frozen + [_TRAP_LINE]
    print(f"frozen exempt-coded lines: {len(frozen)} "
          f"(codes: {sorted({l['vat_group'] for l in frozen})}) + 1 crafted trap")

    artefact = run_exempt_pass(_PERIOD, line_source=lambda: all_lines)

    # SAVE RAW BEFORE INSPECTION — the file is the evidence.
    record = {
        "demo": "t2.30-exempt-live-mechanism-demo",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "note": ("MECHANISM demo over frozen SBODEMOSG ES33 lines + 1 crafted "
                 "trap line. NOT accuracy-validated; no labels; no scoring. "
                 "ESN33 absent from the frozen extract (recorded honestly)."),
        "input_lines": all_lines,
        "artefact": artefact,
    }
    _OUT.write_text(json.dumps(record, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"raw artefact saved to {_OUT} (before inspection)")
    print(f"status={artefact['status']} candidates={artefact['candidate_count']} "
          f"tokens={artefact['token_usage']}")
    return 0 if artefact["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
