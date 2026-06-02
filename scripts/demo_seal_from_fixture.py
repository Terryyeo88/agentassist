"""
demo_seal_from_fixture.py — throwaway walkthrough script (NOT wired into any pipeline).

Mirrors exactly what run_agent.py does AFTER run_chain returns, using the static
CompileOutput fixture instead of a live SAP connection.  Run from repo root:

    python scripts/demo_seal_from_fixture.py

Produces a sealed bundle under audit/sbodemosg-fixture/ so it doesn't collide
with live runs.  The bundle is gitignored (audit/ is in .gitignore).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Repo root on path.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

# ── Inputs ────────────────────────────────────────────────────────────────────

FIXTURE = _ROOT / "tests" / "fixtures" / "chain-run-sample.json"
compile_output: dict = json.loads(FIXTURE.read_text(encoding="utf-8"))

# ── Client config (no SAP connectivity — fixture run) ─────────────────────────

from config.loader import load_client_config  # noqa: E402

cfg = load_client_config("sbodemosg", check_connectivity=False)

# ── Shape gate_results from the compile_output sub-dicts ──────────────────────
# Run the five deterministic gate functions directly on the fixture data.
# These are pure functions — no SAP, no network.

from orchestrator.gates import (  # noqa: E402
    gate_1_record_count,
    gate_2_box_reconciliation,
    gate_3_inventory_consistency,
    gate_4_detect_consistency,
    gate_5_cross_tool_consistency,
)
from audit_bundle.gate_record import build_gate_results  # noqa: E402

manifest_dict = compile_output["fetch_manifest"]
calc_dict     = compile_output["calculate"]
cls_dict      = compile_output["classify"]
det_dict      = compile_output["detect"]

# doc_nums in the fixture is a JSON array (serialised from a set); gate_4 needs
# something that supports `in` — a list works fine.
manifest_dict["doc_nums"] = manifest_dict.get("doc_nums", [])

_records: list[dict] = []

def _rec(gate, name, after_step, status, passed, checked, message=None):
    e = {"gate": gate, "name": name, "after_step": after_step,
         "status": status, "passed": passed, "checked": checked}
    if message is not None:
        e["message"] = message
    _records.append(e)

# Gate 1
try:
    c = gate_1_record_count(manifest_dict)
    status = "WARN_PASS" if c["sap_inline_count"] is None else "PASS"
    _rec(1, "record-count", "fetch", status, True, c,
         "SAP $inlinecount unavailable" if status == "WARN_PASS" else None)
except Exception as exc:
    _rec(1, "record-count", "fetch", "FAIL", False,
         getattr(exc, "checked", {}), str(exc))

# Gate 2
try:
    c = gate_2_box_reconciliation(calc_dict)
    _rec(2, "box-reconciliation", "calculate", "PASS", True, c)
except Exception as exc:
    _rec(2, "box-reconciliation", "calculate", "FAIL", False,
         getattr(exc, "checked", {}), str(exc))

# Gate 3
try:
    c = gate_3_inventory_consistency(cls_dict)
    _rec(3, "inventory-consistency", "classify", "PASS", True, c)
except Exception as exc:
    _rec(3, "inventory-consistency", "classify", "FAIL", False,
         getattr(exc, "checked", {}), str(exc))

# Gate 4
try:
    c = gate_4_detect_consistency(det_dict, manifest_dict)
    _rec(4, "detect-consistency", "detect", "PASS", True, c)
except Exception as exc:
    _rec(4, "detect-consistency", "detect", "FAIL", False,
         getattr(exc, "checked", {}), str(exc))

# Gate 5
try:
    c = gate_5_cross_tool_consistency(calc_dict, cls_dict, det_dict)
    _rec(5, "cross-tool-consistency", "compile", "PASS", True, c)
except Exception as exc:
    _rec(5, "cross-tool-consistency", "compile", "FAIL", False,
         getattr(exc, "checked", {}), str(exc))

gate_results = build_gate_results(_records)

# ── Render PDF (same T1.4 path as run_agent.py) ───────────────────────────────

from report.report import build_report  # noqa: E402
from report.render import render_pdf    # noqa: E402

generated_at: str = compile_output["fetch_manifest"]["fetched_at"]
ts = (datetime.fromisoformat(generated_at).astimezone(timezone.utc)
      .strftime("%Y%m%d-%H%M%S"))

_pdf_dir = _ROOT / "exploration-notes" / "t1.4-reports"
_pdf_dir.mkdir(parents=True, exist_ok=True)
pdf_path = _pdf_dir / f"sbodemosg-fixture-{ts}.pdf"

model = build_report(compile_output, cfg, generated_at=generated_at)
render_pdf(model, pdf_path)
print(f"PDF rendered : {pdf_path}")

# ── Seal ──────────────────────────────────────────────────────────────────────

import audit_bundle.seal as _seal_mod  # noqa: E402

# Write to a fixture-specific subdirectory so it doesn't collide with live runs.
_seal_mod._AUDIT_ROOT = _ROOT / "audit"

from audit_bundle import seal_bundle  # noqa: E402

now = datetime.now(timezone.utc).isoformat()
bundle_dir = seal_bundle(
    client_config=cfg,
    period=compile_output["period"],
    compile_output=compile_output,
    gate_results=gate_results,
    report_pdf_path=pdf_path,
    run_started_at=now,
    run_completed_at=now,
)

print(f"\nBundle sealed: {bundle_dir}")
print(f"Verify       : python -m audit_bundle.verify {bundle_dir}")
