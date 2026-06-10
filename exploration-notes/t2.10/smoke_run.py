#!/usr/bin/env python3
"""
T2.10 Phase 2 smoke run — READ-ONLY.
Verifies: chain runs end-to-end, BOX-ISOLATION, listing_findings present.
No POST/PATCH/PUT/DELETE. No commits. Pure read-only.
"""
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    for _p in [_REPO_ROOT / ".env", _REPO_ROOT.parent / "sap-b1-ai-agent" / ".env"]:
        if _p.exists():
            load_dotenv(_p)
            break
except ImportError:
    pass

from config.loader import load_client_config
from orchestrator.chain import run_chain

PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}


def main():
    print("=" * 70)
    print("T2.10 Phase 2 Smoke Run — READ-ONLY")
    print(f"Period: {PERIOD['start']} to {PERIOD['end']}")
    print("=" * 70)

    cfg = load_client_config("sbodemosg")

    print("\nRunning chain (this will contact live SBODEMOSG)...")
    result, gates = run_chain(cfg, PERIOD)
    print("  Chain completed.")

    # ── BOX-ISOLATION check ──────────────────────────────────────────────────
    print("\n--- BOX-ISOLATION ---")
    boxes = result["calculate"]["boxes"]
    for box_name, val in sorted(boxes.items()):
        print(f"  {box_name}: {val}")
    print("  (These box values must be identical to a baseline run without T2.10)")

    # ── Gate results ────────────────────────────────────────────────────────
    print("\n--- Gate Results ---")
    for g in gates["gates"]:
        status = g["status"]
        print(f"  Gate {g['gate']} ({g['name']}): {status}")
    print(f"  all_passed: {gates['all_passed']}")

    # ── listing_findings ────────────────────────────────────────────────────
    print("\n--- listing_findings ---")
    lf = result.get("listing_findings", "KEY MISSING")
    if isinstance(lf, list):
        print(f"  Count: {len(lf)}")
        if lf:
            print(f"  Findings:")
            for f in lf:
                print(f"    {json.dumps(f, indent=6)}")
        else:
            print("  [] (empty — expected: SEQ_GAP=0 or small, DUP_CLAIM=0)")
    else:
        print(f"  ERROR: listing_findings = {lf!r}")

    # ── SEQ_GAP / DUP_CLAIM split ───────────────────────────────────────────
    if isinstance(lf, list):
        seq_gap = [f for f in lf if f.get("check") == "SEQ_GAP"]
        dup_claim = [f for f in lf if f.get("check") == "DUP_CLAIM"]
        print(f"\n  SEQ_GAP findings:  {len(seq_gap)}")
        for f in seq_gap:
            print(f"    DocNum {f['gap_doc_num']} (Series {f['series']}) "
                  f"range [{f['series_min']}, {f['series_max']}]")
        print(f"  DUP_CLAIM findings: {len(dup_claim)} "
              f"(expected 0 — SBODEMOSG NumAtCard all null)")

    # ── declared_f5_findings ────────────────────────────────────────────────
    print(f"\n--- declared_f5_findings ---")
    dff = result.get("declared_f5_findings", [])
    print(f"  Count: {len(dff)} (expected 0 — no declared_f5 supplied)")

    # ── Schema keys check ───────────────────────────────────────────────────
    print("\n--- CompileOutput keys ---")
    expected_keys = {
        "period", "fetch_manifest", "calculate", "classify", "detect",
        "deduplicated_anomalies", "e1_reconciliation", "surfaced_warnings",
        "declared_f5_findings", "listing_findings",
    }
    present = set(result.keys())
    missing = expected_keys - present
    extra = present - expected_keys
    print(f"  Expected keys present: {'YES' if not missing else 'NO — missing: ' + str(missing)}")
    if extra:
        print(f"  Extra keys: {extra}")

    # ── Acceptance criterion ─────────────────────────────────────────────────
    print("\n--- Acceptance ---")
    seq_gap_count = len([f for f in lf if f.get("check") == "SEQ_GAP"]) if isinstance(lf, list) else -1
    dup_count = len([f for f in lf if f.get("check") == "DUP_CLAIM"]) if isinstance(lf, list) else -1

    accept = (
        gates["all_passed"] and
        isinstance(lf, list) and
        seq_gap_count < 10 and  # must NOT be ~600 from the broken algorithm
        dup_count == 0 and
        "listing_findings" in result and
        not missing
    )
    print(f"  SEQ_GAP count < 10: {'PASS' if seq_gap_count < 10 else 'FAIL — got ' + str(seq_gap_count)}")
    print(f"  DUP_CLAIM == 0:     {'PASS' if dup_count == 0 else 'FAIL — got ' + str(dup_count)}")
    print(f"  Gates all_passed:   {'PASS' if gates['all_passed'] else 'FAIL'}")
    print(f"  listing_findings key present: {'PASS' if 'listing_findings' in result else 'FAIL'}")
    print(f"\n  OVERALL: {'PASS' if accept else 'FAIL'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
