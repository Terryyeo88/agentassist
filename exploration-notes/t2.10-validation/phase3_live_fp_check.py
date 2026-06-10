"""
Phase 3 live read-only FP check — SBODEMOSG Q3 2024.

Runs the real run_chain with real fetch_listing_data against SBODEMOSG.
Asserts zero SEQ_GAP and zero DUP_CLAIM findings in listing_findings.

READ-ONLY: only GET requests issued (fetch_listing_data uses search_documents).
No SAP writes.
"""
import sys
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(".env"), override=True)

import warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, str(Path("mcp-servers/custom").resolve()))

from config.loader import load_client_config
from orchestrator.chain import run_chain

PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}

print("=" * 60)
print("T2.10 Phase 3 — Live read-only FP check")
print(f"Client: SBODEMOSG  Period: {PERIOD['start']} → {PERIOD['end']}")
print("=" * 60)

cfg = load_client_config("sbodemosg", check_connectivity=False)
print(f"Config loaded: {cfg.client_name} | {cfg.company_db}")
print("Running chain (live SAP reads, no writes)...")

compile_out, gate_results = run_chain(cfg, PERIOD)

findings   = compile_out.get("listing_findings", [])
seq_gaps   = [f for f in findings if f.get("check") == "SEQ_GAP"]
dup_claims = [f for f in findings if f.get("check") == "DUP_CLAIM"]

print()
print(f"listing_findings total   : {len(findings)}")
print(f"  SEQ_GAP  findings      : {len(seq_gaps)}")
print(f"  DUP_CLAIM findings     : {len(dup_claims)}")
print()

if seq_gaps:
    print("FAIL — unexpected SEQ_GAP findings:")
    for f in seq_gaps:
        print(f"  gap_doc_num={f['gap_doc_num']} series={f['series']} "
              f"range=[{f['series_min']},{f['series_max']}]")
    sys.exit(1)

if dup_claims:
    print("FAIL — unexpected DUP_CLAIM findings:")
    for f in dup_claims:
        print(f"  doc_num={f['doc_num']} dup_of={f['duplicate_of']} "
              f"card={f['card_code']} ref={f['num_at_card']} total={f['doc_total']}")
    sys.exit(1)

print("Gates:")
for g in gate_results.get("gates", []):
    mark = "PASS" if g["passed"] else "FAIL"
    print(f"  [{mark}] Gate {g['gate']} — {g['name']} (status={g['status']})")
print()

boxes = compile_out["calculate"]["boxes"]
print("F5 Boxes (spot-check):")
for k, v in sorted(boxes.items()):
    print(f"  {k}: {v}")
print()

print("PHASE 3 RESULT: PASS")
print("  zero SEQ_GAP findings  ✓")
print("  zero DUP_CLAIM findings ✓")
print(f"  all_passed={gate_results.get('all_passed')}  ✓")
