# SESSION-REPORT — Synthetic Demo Build (2026-06-10)

## Overview

Built a synthetic showcase report in the `aa-demo-report` worktree (branch `demo-report`,
forked from `master` @ `e0cab63`). The report combines live F5 boxes / E-codes from real
SBODEMOSG Q3 2024 data with crafted/injected illustrative findings demonstrating the three
main finding classes.

---

## Worktree and environment

| Item | Value |
|------|-------|
| Worktree path | `C:\Users\terry\Desktop\AgentAssist\aa-demo-report` |
| Branch | `demo-report` (forked from `master` @ `e0cab63`) |
| Python env | `.venv` (Python 3.13, packages from `requirements.txt` + `pdfplumber`) |
| .env | Copied from `sap-b1-ai-agent/.env`; confirmed covered by `.gitignore` |
| master HEAD | `e0cab63` — confirmed clean and untouched |

---

## Live computed F5 boxes (SBODEMOSG Q3 2024 — real data)

Captured live at 2026-06-10 ~11:14 UTC from SBODEMOSG:

| Box | Key | Computed Value (SGD) |
|-----|-----|----------------------|
| Box 1 | box_1_standard_rated_sales | 369,589.97 |
| Box 2 | box_2_zero_rated_sales | 10,000.00 |
| Box 3 | box_3_exempt_sales | 6,000.00 |
| Box 4 | box_4_total_sales | 385,589.97 |
| Box 5 | box_5_taxable_purchases | 191,077.76 |
| Box 6 | box_6_output_tax | 25,871.32 |
| Box 7 | box_7_input_tax | 13,207.45 |
| Box 8 | box_8_net_gst | 12,663.87 |

## Live E-codes (SBODEMOSG Q3 2024 — real data)

23 issues detected by live `detect_gst_errors`:

| doc_num | error_code | severity |
|---------|------------|----------|
| 958, 964, 965, 971, 974(×3), 967(×2), 977, 982 | E1 | HIGH |
| 592, 594, 595, 600, 601, 604, 605 | NO_GST_REG | HIGH |
| 605, 607, 608, 610, 611 | E2 | MEDIUM |

Gate results: Gate 1 WARN_PASS (SAP $inlinecount unavailable); Gates 2–5 all PASS.
Live baseline listing: 0 SEQ_GAP, 0 DUP_CLAIM (FP-check confirmed).

---

## Crafted injections

### 1. Declared-vs-Computed Divergence (Check B)

File: `declared-f5-demo.json` (Fixture-B style, integer values)

| Box | Declared | Computed | Delta | Status |
|-----|----------|----------|-------|--------|
| box_1 | 374,590 | 369,589.97 | +5,000.03 | over_declared (Check B primary) |
| box_4 | 390,590 | 385,589.97 | +5,000.03 | derived consequence note |
| box_2, box_3, box_5, box_6, box_7, box_8 | within ±1.00 of computed | — | — | within tolerance, no finding |

Check A: internally consistent (box_4 = box_1+box_2+box_3; box_8 = box_6−box_7; all exact
integer arithmetic, no floating-point artifacts).

### 2. SEQ_GAP (crafted sales listing headers)

| DocNum | Series | Cancelled | Role |
|--------|--------|-----------|------|
| 8001 | 1 | tNO | period + company-wide active |
| 8003 | 1 | tNO | period + company-wide active (near-miss: present elsewhere → NOT flagged) |
| 8004 | 1 | tNO | period + company-wide active |
| 8002 | — | — | absent company-wide → ONE SEQ_GAP finding |

Active range [8001, 8004]. One finding: DocNum 8002 gap.

### 3. DUP_CLAIM (crafted purchase listing headers)

| DocNum | CardCode | NumAtCard | DocTotal | Role |
|--------|----------|-----------|----------|------|
| 7001 | V001 | INV-2024-001 | 1,000.00 | first occurrence |
| 7002 | V001 | INV-2024-001 | 1,000.00 | duplicate → ONE DUP_CLAIM finding |
| 7003 | V001 | INV-2024-002 | 1,000.00 | near-miss (different NumAtCard) → NOT flagged |

---

## PDF artifact

| Property | Value |
|----------|-------|
| Path | `exploration-notes/demo-scenario/AgentAssist-demo-report.pdf` |
| Size | 19,701 bytes |
| Client | SAP B1 Demo (SBODEMOSG) |
| Period | 2024-07-01 → 2024-09-30 |

---

## Self-verification results

All 10 checks passed (run_demo.py self-verify):

| Check | Test | Result |
|-------|------|--------|
| V1 | PDF exists and is non-zero | PASS (19,701 bytes) |
| V2 | PDF contains live Box 1 value `369,589.97` | PASS |
| V2 | PDF contains declared Box 1 value `374,590.00` | PASS |
| V2 | PDF contains text `over_declared` | PASS |
| V2 | PDF contains SEQ_GAP DocNum `8002` | PASS |
| V2 | PDF contains DUP_CLAIM DocNum `7002` | PASS |
| V3 | Box isolation: patched-run boxes byte-identical to baseline | PASS |
| V4 | Exactly 1 SEQ_GAP finding (DocNum 8002) | PASS |
| V4 | Exactly 1 DUP_CLAIM finding (DocNum 7002 dup of 7001) | PASS |
| V5 | Check B box_1 delta +5000.03 (~+5000, over_declared) | PASS |

Pytest sanity suite (49 tests):

```
tests/test_listing_findings_section.py  .....  (all pass)
tests/test_check_declared_f5.py         .....  (all pass)
49 passed in 1.18s
```

---

## Files created (all in exploration-notes/demo-scenario/)

| File | Purpose |
|------|---------|
| `run_demo.py` | Main demo script; patches fetch_listing_data + runs live chain + renders PDF |
| `declared-f5-demo.json` | Crafted declared F5 (box_1 +5000 over-declared; Fixture-B style) |
| `live_boxes_baseline.json` | Saved live computed boxes (no patch); used for V3 box-isolation check |
| `compile_output_demo.json` | Saved compile output from demo run (for post-analysis) |
| `AgentAssist-demo-report.pdf` | Rendered synthetic showcase PDF |
| `README.md` | Plain-language disclosure of real vs. crafted content |
| `SESSION-REPORT.md` | This file |

---

## Git / commit status

**NOTHING WAS COMMITTED OR PUSHED.**

- `master` branch: never touched. HEAD remains at `e0cab63` (confirmed before and after).
- `demo-report` branch: all files are uncommitted (untracked) in the `aa-demo-report`
  worktree. `git status` in the worktree shows only untracked files — no staged changes,
  no commits beyond the branch-creation point.
- No `git commit`, `git push`, `git rebase`, `git reset`, or `git merge` was executed.
- The `.env` file was copied to the worktree but is covered by `.gitignore` and was not
  staged or committed.

---

## Notes for reviewer

- The report demonstrates **correct surfacing** of each finding class when findings are
  present. This is NOT real-client validation.
- The positive-detection logic (SEQ_GAP, DUP_CLAIM, declared-vs-computed Check B) was
  validated on synthetic cases in T2.10-V and T2.9-V respectively.
- Live zero-FP on SBODEMOSG Q3 2024 was confirmed in T2.10 Phase 3 validation and again
  in this session (listing_findings=0 on the unpatched baseline run).
- Pair with the v0-vs-v3 contrast material for prospect demos.
