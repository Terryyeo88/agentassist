# AgentAssist Demo Report — Synthetic Showcase

## IMPORTANT: This is a SYNTHETIC demonstration

This folder contains a showcase report (`AgentAssist-demo-report.pdf`) that combines
**live engine output** with **crafted/injected illustrative findings**.

---

## What is real vs. what is crafted

### REAL (live from SBODEMOSG Q3 2024)
- **F5 box values** (Boxes 1–8) — computed live by `calculate_f5_return` from actual
  SBODEMOSG transaction data.
- **E-codes** (E1, E2, NO_GST_REG) — detected live by `detect_gst_errors` from actual
  SBODEMOSG data. E2 for DocNum 610 is expected and real.
- **All gate outcomes** (WARN_PASS on Gate 1 due to SAP $inlinecount unavailability; all
  other gates PASS) — real reconciliation results against live SAP data.

### CRAFTED INJECTIONS (in-memory only — NOT real SBODEMOSG data)

**1. Declared-vs-Computed F5 Divergence (Check B)**
- `declared-f5-demo.json` sets Box 1 declared = 374,590.00, which is ~+5,000 above the
  live computed value of 369,589.97.
- This triggers one Check B primary finding (`box_1 over_declared, delta +5000.03`) and
  one derived consequence note (`box_4 +5000.03`).
- The declared figures are internally consistent (Check A passes): `box_4 = box_1+box_2+box_3`
  and `box_8 = box_6−box_7` both hold exactly.
- **This divergence did NOT happen in SBODEMOSG.** It is injected to demonstrate correct
  surfacing of declared-vs-computed divergences when they are present.

**2. Sequence Gap (SEQ_GAP)**
- Crafted sales listing: period active range [8001, 8004]; DocNums 8001, 8003, 8004 present
  company-wide; DocNum 8002 is truly absent → one SEQ_GAP finding.
- DocNum 8003 (present in company-wide records) is correctly not flagged — demonstrating
  the discriminating case.
- IRAS basis: ASK Annual Review Guide §10.1(c)(i) "Invoices not in running sequences".
- **DocNums 7001–8004 do not exist in SBODEMOSG.** They are crafted in-memory by the
  demo script and never written to SAP.

**3. Duplicate Input-Tax Claim (DUP_CLAIM)**
- Crafted purchase listing: DocNums 7001 + 7002 share the same CardCode (V001),
  NumAtCard (INV-2024-001), and DocTotal (SGD 1,000.00) → one DUP_CLAIM finding.
- DocNum 7003 has a different NumAtCard (INV-2024-002) → near-miss, correctly not flagged.
- IRAS basis: ASK Annual Review Guide §10.1(d)(i) "Processing the same invoice more than once".
- **These purchase records do not exist in SBODEMOSG.** They are crafted in-memory only.

---

## How to reproduce

From the `aa-demo-report` worktree root:

```
.venv/Scripts/python exploration-notes/demo-scenario/run_demo.py
```

The script patches only `fetch_listing_data` in-memory. All other chain steps
(fetch, calculate, classify, detect, compile, declared-f5 reconciliation) run
live against SBODEMOSG. No SAP writes are made.

---

## What this demonstrates

This report demonstrates that the AgentAssist engine correctly surfaces each class
of finding when findings are present:

- **Declared-vs-computed divergence**: Box 1 over-declaration with correct delta, direction,
  and derived Box 4 consequence note.
- **Invoice sequence gap**: DocNum 8002 flagged; 8003 (present elsewhere) not flagged.
- **Duplicate input-tax claim**: DocNum 7002 flagged as dup of 7001; DocNum 7003 (different
  vendor reference) not flagged.

**This is NOT real-client validation.** The positive detections were validated on
synthetic cases. For real-client validation, run the chain against a real client dataset
where these findings are known to be present and independently confirmed.

Pair with the v0-vs-v3 contrast for prospects.

---

## Validation status

- Declared-vs-computed (T2.9): mechanism validated on SBODEMOSG demo (T2.9-V).
- SEQ_GAP / DUP_CLAIM (T2.10): positive-detection validated on synthetic cases; live
  zero-FP confirmed on SBODEMOSG Q3 2024.
- **NOT real-client validated.** (validation_status unchanged from main branch.)
