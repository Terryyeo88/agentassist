"""
exploration-notes/demo-scenario/run_demo.py

SYNTHETIC SHOWCASE SCRIPT — run from the aa-demo-report worktree root:
    .venv/Scripts/python exploration-notes/demo-scenario/run_demo.py

What this script does
---------------------
1. Patches ONLY fetch_listing_data in orchestrator.chain to return crafted
   listing headers (SEQ_GAP + DUP_CLAIM injections). Everything else — the
   F5 fetch/calculate/classify/detect, declared-f5 reconciliation, and PDF
   render — runs against the real SBODEMOSG Q3 2024 data live.

2. Loads declared-f5-demo.json: box_1 is over-declared by +5000.00 above
   the live computed value. Internally consistent (Check A passes; Check B
   fires on box_1).

3. Renders exploration-notes/demo-scenario/AgentAssist-demo-report.pdf

4. Performs self-verification: PDF size, text content, box isolation.

All crafted injections are in-memory only. No SAP writes. No git commits.

CRAFTED INJECTIONS (labelled)
------------------------------
SEQ_GAP
    Sales active range [8001, 8004]; DocNums 8001, 8003, 8004 present in
    both period and company-wide records; 8002 is truly absent → one
    SEQ_GAP finding. 8003 is present company-wide → not flagged.
    (Mirrors the T2.10-V validated fixture structure.)

DUP_CLAIM
    DocNums 7001 + 7002 share same CardCode + NumAtCard + DocTotal → one
    DUP_CLAIM finding. DocNum 7003 has a different NumAtCard → near-miss,
    not flagged. (Mirrors the T2.10-V validated fixture structure.)

Declared-vs-Computed (Check B)
    box_1 declared = live_computed_box_1 + 5000.00 → over_declared primary
    finding; box_4 derived consequence note (sum of supplies). (Mirrors
    T2.9-V Fixture-B structure.)
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import urllib3

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Repo root on path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "mcp-servers" / "custom"))

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env", override=True)

from config.loader import load_client_config  # noqa: E402
from orchestrator.check_declared_f5 import load_declared_f5  # noqa: E402
from report.report import build_report  # noqa: E402
from report.render import render_pdf  # noqa: E402

PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}
DEMO_DIR = Path(__file__).resolve().parent
DECLARED_F5_PATH = DEMO_DIR / "declared-f5-demo.json"
PDF_OUT = DEMO_DIR / "AgentAssist-demo-report.pdf"

# ---------------------------------------------------------------------------
# Crafted listing headers — injected in-memory; no SAP writes
# ---------------------------------------------------------------------------
# SEQ_GAP scenario:
#   period_sales_headers active DocNums: 8001, 8003, 8004 (all Series=1)
#   all_sales_headers same set: 8001, 8003, 8004
#   → active range [8001, 8004]; 8002 absent company-wide → ONE SEQ_GAP
#   → 8003 is in all_records (present company-wide) → NOT flagged (near-miss)
#
# DUP_CLAIM scenario:
#   7001 + 7002 share (CardCode="V001", NumAtCard="INV-2024-001", DocTotal=1000.00)
#   → ONE DUP_CLAIM finding
#   7003: same CardCode+DocTotal but NumAtCard="INV-2024-002" → NOT flagged (near-miss)
_CRAFTED_LISTING = {
    "period_sales_headers": [
        {"DocNum": 8001, "Series": 1, "Cancelled": "tNO"},
        {"DocNum": 8003, "Series": 1, "Cancelled": "tNO"},
        {"DocNum": 8004, "Series": 1, "Cancelled": "tNO"},
    ],
    "all_sales_headers": [
        {"DocNum": 8001, "Series": 1, "Cancelled": "tNO"},
        {"DocNum": 8003, "Series": 1, "Cancelled": "tNO"},
        {"DocNum": 8004, "Series": 1, "Cancelled": "tNO"},
    ],
    "period_purch_headers": [
        {
            "DocNum": 7001, "Series": 6, "Cancelled": "tNO",
            "CardCode": "V001", "NumAtCard": "INV-2024-001", "DocTotal": 1000.00,
        },
        {
            "DocNum": 7002, "Series": 6, "Cancelled": "tNO",
            "CardCode": "V001", "NumAtCard": "INV-2024-001", "DocTotal": 1000.00,
        },
        {
            "DocNum": 7003, "Series": 6, "Cancelled": "tNO",
            "CardCode": "V001", "NumAtCard": "INV-2024-002", "DocTotal": 1000.00,
        },
    ],
    "all_purch_headers": [],
}


def _patched_fetch_listing(client_config, period):
    print("  [PATCH] fetch_listing_data → returning crafted listing headers")
    return _CRAFTED_LISTING


# ---------------------------------------------------------------------------
# Patch fetch_listing_data at the chain module level BEFORE run_chain import.
# run_chain resolves fetch_listing_data from orchestrator.chain's module
# globals at call time, so patching the chain module's binding is sufficient.
# ---------------------------------------------------------------------------
import orchestrator.chain as _chain_mod  # noqa: E402

_real_fetch_listing = _chain_mod.fetch_listing_data
_chain_mod.fetch_listing_data = _patched_fetch_listing

from orchestrator.chain import run_chain  # noqa: E402 — after patch so run_chain sees it


def main() -> None:
    print("=" * 66)
    print("AgentAssist SYNTHETIC DEMO — Q3 2024 SBODEMOSG")
    print("Crafted injections: SEQ_GAP + DUP_CLAIM + declared-vs-computed")
    print("Live F5 boxes + E-codes from real SBODEMOSG data")
    print("=" * 66)

    # --- Config ---
    cfg = load_client_config("sbodemosg", check_connectivity=False)
    print(f"Config: {cfg.client_name}  db={cfg.company_db}")

    # --- Declared F5 (crafted box_1 +5000 over-declaration) ---
    declared_f5 = load_declared_f5(DECLARED_F5_PATH, PERIOD)
    print(
        f"Declared F5: loaded — box_1={declared_f5['declared']['box_1']:.2f} "
        f"(over-declared by +5000 vs computed)"
    )

    # --- Live chain + patched listing ---
    print(f"\nRunning live chain for {PERIOD['start']} → {PERIOD['end']} ...")
    compile_out, gate_results = run_chain(cfg, PERIOD, declared_f5=declared_f5)

    boxes = compile_out["calculate"]["boxes"]
    print("\n--- Live computed F5 boxes ---")
    for k in sorted(boxes):
        print(f"  {k}: {boxes[k]}")

    df5_findings = compile_out.get("declared_f5_findings", [])
    print(f"\n--- Declared-vs-computed findings ({len(df5_findings)}) ---")
    for f in df5_findings:
        print(f"  [{f['check']}] {f.get('finding_type','')} box={f['box']} delta={f.get('delta')}")

    listing_findings = compile_out.get("listing_findings", [])
    seq_gaps = [f for f in listing_findings if f.get("check") == "SEQ_GAP"]
    dup_claims = [f for f in listing_findings if f.get("check") == "DUP_CLAIM"]
    print(f"\n--- Listing findings ({len(listing_findings)}) ---")
    print(f"  SEQ_GAP  : {len(seq_gaps)}")
    for f in seq_gaps:
        print(f"    gap_doc_num={f['gap_doc_num']} series={f['series']} range=[{f['series_min']},{f['series_max']}]")
    print(f"  DUP_CLAIM: {len(dup_claims)}")
    for f in dup_claims:
        print(f"    doc_num={f['doc_num']} dup_of={f['duplicate_of']} card={f['card_code']} ref={f['num_at_card']}")

    print(f"\n--- Gate results ---")
    print(f"  all_passed: {gate_results['all_passed']}")
    for g in gate_results["gates"]:
        print(f"  Gate {g['gate']} {g['name']}: {g['status']}")

    # Save compile output for post-analysis
    compile_out_path = DEMO_DIR / "compile_output_demo.json"
    import copy
    save_obj = copy.deepcopy(compile_out)
    # E1 reconciliation sets are not JSON-serialisable; convert to sorted lists
    e1r = save_obj.get("e1_reconciliation", {})
    for key in ("calc_doc_nums", "detect_doc_nums"):
        if isinstance(e1r.get(key), set):
            e1r[key] = sorted(e1r[key])
    # fetch_manifest doc_nums set → sorted list
    fm = save_obj.get("fetch_manifest", {})
    if isinstance(fm.get("doc_nums"), set):
        fm["doc_nums"] = sorted(fm["doc_nums"])
    with open(compile_out_path, "w") as fh:
        json.dump(save_obj, fh, indent=2, default=str)
    print(f"\nCompile output saved: {compile_out_path}")

    # --- Build and render PDF ---
    print("\nBuilding PDF report ...")
    generated_at = compile_out["fetch_manifest"]["fetched_at"]
    model = build_report(compile_out, cfg, generated_at=generated_at)
    render_pdf(model, PDF_OUT)
    pdf_size = PDF_OUT.stat().st_size
    print(f"PDF rendered: {PDF_OUT}  ({pdf_size:,} bytes)")

    # --- Self-verify: assertions ---
    print("\n--- Self-verification ---")
    errors: list[str] = []

    # V1: PDF non-zero
    if pdf_size == 0:
        errors.append("FAIL V1: PDF is zero bytes")
    else:
        print(f"  V1 PASS: PDF exists and is non-zero ({pdf_size:,} bytes)")

    # V2: PDF text content check
    try:
        import pdfplumber

        with pdfplumber.open(PDF_OUT) as pdf:
            full_text = "\n".join(
                page.extract_text() or "" for page in pdf.pages
            )

        checks = {
            "live_box_1": "369,589.97",
            "check_b_box_1": "374,590.00",
            "delta_direction": "over_declared",
            "seq_gap_docnum": "8002",
            "dup_claim_docnum": "7002",
        }
        for label, needle in checks.items():
            if needle in full_text:
                print(f"  V2 PASS: PDF contains expected text [{label}]: {needle!r}")
            else:
                errors.append(f"FAIL V2: PDF missing expected text [{label}]: {needle!r}")

    except Exception as exc:
        errors.append(f"FAIL V2: pdfplumber extraction failed: {exc}")

    # V3: Box isolation — compare with saved baseline
    baseline_path = DEMO_DIR / "live_boxes_baseline.json"
    if baseline_path.exists():
        with open(baseline_path) as fh:
            baseline_boxes = json.load(fh)
        patched_boxes = compile_out["calculate"]["boxes"]
        baseline_json = json.dumps(baseline_boxes, sort_keys=True)
        patched_json = json.dumps(patched_boxes, sort_keys=True)
        if baseline_json == patched_json:
            print(f"  V3 PASS: box isolation — patched-run boxes byte-identical to baseline")
        else:
            errors.append("FAIL V3: box isolation VIOLATED — patched run perturbed F5 boxes")
            for k in sorted(set(baseline_boxes) | set(patched_boxes)):
                bv = baseline_boxes.get(k)
                pv = patched_boxes.get(k)
                if bv != pv:
                    print(f"    diff {k}: baseline={bv} patched={pv}")
    else:
        errors.append("FAIL V3: live_boxes_baseline.json not found — run Step 4 first")

    # V4: Listing finding counts
    if len(seq_gaps) == 1:
        print(f"  V4 PASS: exactly 1 SEQ_GAP finding (DocNum 8002)")
    else:
        errors.append(f"FAIL V4: expected 1 SEQ_GAP finding, got {len(seq_gaps)}")

    if len(dup_claims) == 1:
        print(f"  V4 PASS: exactly 1 DUP_CLAIM finding (DocNum 7002 dup of 7001)")
    else:
        errors.append(f"FAIL V4: expected 1 DUP_CLAIM finding, got {len(dup_claims)}")

    # V5: Check B primary finding on box_1
    b_primary = [
        f for f in df5_findings
        if f.get("check") == "B" and f.get("finding_type") == "declared_vs_computed_divergence"
    ]
    if len(b_primary) == 1 and b_primary[0].get("box") == "box_1":
        delta = b_primary[0].get("delta", 0)
        if abs(delta - 5000.0) < 1.0:
            print(f"  V5 PASS: Check B box_1 delta={delta:+.2f} (~+5000, over_declared)")
        else:
            errors.append(f"FAIL V5: Check B box_1 delta={delta}, expected ~+5000")
    else:
        errors.append(
            f"FAIL V5: expected exactly 1 Check B primary finding on box_1, "
            f"got {[(f.get('box'), f.get('finding_type')) for f in b_primary]}"
        )

    # Summary
    print()
    if errors:
        print(f"SELF-VERIFY RESULT: {len(errors)} FAILURE(S)")
        for e in errors:
            print(f"  {e}")
    else:
        print("SELF-VERIFY RESULT: ALL CHECKS PASSED")

    return errors


if __name__ == "__main__":
    errs = main()
    sys.exit(1 if errs else 0)
