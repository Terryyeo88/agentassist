# T2.10 Session Report

**Branch**: `t2.10-listing-checks`
**Worktree**: `../aa-t2.10` off `master`
**Date**: 2026-06-09
**Run status**: COMPLETE — do not commit; awaiting Terry review

---

## Summary

Three checks added as specified:

| # | Check | Status |
|---|-------|--------|
| 1 | SEQ_GAP — sequence gap detection over DocNum | Implemented + tested |
| 2 | DUP_CLAIM — duplicate input-tax claim detection | Implemented + tested |
| 3 | ZP E2 extension — ZP added to both code sets | Implemented + tested |

---

## What was built

### Check 1 — SEQ_GAP

**Production path**: `orchestrator/check_listing.py` → `detect_seq_gaps(records)`

**Reference implementation**: `scripts/check_listing_reference.py` → `ref_detect_seq_gaps(records)`

**No shared helper** between production and reference (confirmed by inspection).

**Algorithm**: Groups records by `Series` integer. Within each series, finds the in-period DocNum range `[min, max]`. Flags integers missing from that range that are NOT explained by a cancelled document (same `Series`, `Cancelled="tYES"`). Gaps before `min` or after `max` are not flagged — they could be out-of-period documents continuing the same series.

**IRAS basis**: ASK Annual Review Guide §10.1(c)(i) — "Invoices not in running sequences"

### Check 2 — DUP_CLAIM

**Production path**: `orchestrator/check_listing.py` → `detect_dup_claims(records)`

**Reference implementation**: `scripts/check_listing_reference.py` → `ref_detect_dup_claims(records)`

**No shared helper** between production and reference (confirmed by inspection).

**Algorithm**: Groups purchase documents by key = `(CardCode.strip(), NumAtCard.strip(), round(DocTotal, 2))`. Any key with ≥ 2 documents surfaces a DUP_CLAIM candidate per duplicate occurrence. Documents with blank/None `NumAtCard` are excluded — blank vendor reference cannot identify a specific invoice. Different `NumAtCard` values (recurring charges from same vendor at same amount) are NOT flagged.

**IRAS basis**: ASK Annual Review Guide §10.1(d)(i) — "Processing the same invoice more than once"

### Check 3 — ZP E2 extension

**Production path**: `mcp-servers/custom/sap_b1_server.py`
- Added `"ZP"` to `_E2_ZERO_RATE_CODES` (line 352)

**Reference**: `scripts/run_baseline_tests.py`
- Added `"ZP"` to `E2_ZERO_RATE_CODES` (line 88)

**Both implementations agree**: `test_code_sets_agree_on_e2_membership` asserts `_E2_ZERO_RATE_CODES == E2_ZERO_RATE_CODES` between production and reference.

**IRAS basis**: ASK Annual Review Guide §10.1(d)(iv) — "tax coded as zero-rated/exempt/out-of-scope but reflects GST"

**Live fixture**: DocNum 610 (VatGroup=ZP, LineTotal=800.00, TaxTotal=56.00 at 7%, DocTotal=856.00) — the known SBODEMOSG fixture for this case. When run against live SAP, this document will now be flagged as E2. (Note: autonomous session noted 1200/84; live Phase 1 probe confirmed 800/56 — logic correct regardless of amounts.)

---

## Insertion points

| Component | File | Change |
|-----------|------|--------|
| SEQ_GAP production | `orchestrator/check_listing.py` | New file |
| DUP_CLAIM production | `orchestrator/check_listing.py` | New file |
| SEQ_GAP reference | `scripts/check_listing_reference.py` | New file |
| DUP_CLAIM reference | `scripts/check_listing_reference.py` | New file |
| ZP E2 production | `mcp-servers/custom/sap_b1_server.py:352` | Added "ZP" to `_E2_ZERO_RATE_CODES` |
| ZP E2 reference | `scripts/run_baseline_tests.py:88` | Added "ZP" to `E2_ZERO_RATE_CODES` |
| Tests | `tests/test_check_listing.py` | New file — 58 tests |
| conftest | `tests/conftest.py` | New file — dummy SAP creds for import |

---

## Audit-vs-reference agreement results

### SEQ_GAP

Agreement tests (`TestSeqGapAgreement`):
- `test_agree_on_acceptance_fixture` — PASS: both flag exactly `(series=1, gap=102)` on the acceptance fixture
- `test_agree_on_empty_input` — PASS: both return `[]` on empty input
- `test_agree_on_single_series_multiple_gaps` — PASS: both flag gaps 11, 12, 13, 14
- `test_agree_on_all_cancelled_gaps` — PASS: both return `[]` when all gaps are cancelled
- `test_agree_on_mixed_multi_series` — PASS: both agree on the full acceptance fixture

### DUP_CLAIM

Agreement tests (`TestDupClaimAgreement`):
- `test_agree_on_acceptance_fixture` — PASS: both flag `(doc_num=502, duplicate_of=501)`
- `test_agree_on_empty_input` — PASS: both return `[]`
- `test_agree_on_blank_num_at_card` — PASS: both return `[]` on blank NumAtCard
- `test_agree_on_three_duplicates` — PASS: both flag 2 findings for 3 entries with same key
- `test_agree_on_recurring_charges` — PASS: both return `[]` for different NumAtCards

### ZP E2

Agreement tests (`TestZpE2Agreement`):
- `test_both_contain_zp` — PASS: `"ZP"` in both `_E2_ZERO_RATE_CODES` and `E2_ZERO_RATE_CODES`
- `test_code_sets_agree_on_e2_membership` — PASS: `_E2_ZERO_RATE_CODES == E2_ZERO_RATE_CODES` (sets identical)
- `test_both_flag_zp_84` — PASS: both implementations flag ZP+TaxTotal=84 as E2
- `test_both_skip_zp_zero_tax` — PASS: both skip ZP+TaxTotal=0

---

## VERIFY-flagged assumptions

### SEQ_GAP

1. **VERIFY SAP FIELD — `Series` (int)**:
   Assumed to be the standard SAP B1 OData integer field identifying the document numbering series, present on `Invoices` and `PurchaseInvoices`. SAP B1's document numbering series feature is well-documented; the OData field `Series` is standard.
   **Action required**: confirm via a test OData query `GET /Invoices?$select=DocNum,Series&$top=5` on a live SBODEMOSG instance before deploying.

2. **VERIFY SAP FIELD — `Cancelled` (str)**:
   Assumed to be `"tYES"` for cancelled documents per SAP B1 `YNGroupEnum` convention (used throughout the Service Layer for boolean fields). The production algorithm's `_is_cancelled()` also handles `"Y"`, `"y"` variants as a defensive measure.
   **Action required**: confirm `Cancelled` field name and value encoding on live Service Layer. Note: SAP B1 may also use `DocumentStatus` or `Cancelled` field depending on the document type; the Service Layer for `Invoices` typically exposes `Cancelled` directly.

3. **VERIFY AGAINST IRAS SOURCE — "running sequence" definition**:
   The algorithm flags gaps within `[min_DocNum, max_DocNum]` for each series in the period. The IRAS ASK Guide §10.1(c)(i) cites "invoices not in running sequences" as a risk indicator but does not define what constitutes a "running sequence" with precision (single series vs. multi-series, cancelled slots, etc.).
   **Assumption**: each SAP B1 `Series` defines one independent running sequence; gaps within a series that are not explained by cancellations are findings.
   **Action required**: VERIFY AGAINST IRAS SOURCE whether the IRAS definition of "running sequence" aligns with SAP B1's series concept, or whether it applies only to the primary series.

### DUP_CLAIM

4. **VERIFY SAP FIELD — `NumAtCard` (str)**:
   Assumed to be the "Number at Vendor" field on SAP B1 `PurchaseInvoices` OData entity — the vendor's own invoice number as entered by the accounts-payable operator.
   **Action required**: confirm via `GET /PurchaseInvoices?$select=DocNum,NumAtCard&$top=5` on a live instance that `NumAtCard` carries the vendor invoice reference.

5. **VERIFY SAP FIELD — `DocTotal` (float)**:
   Used as the amount component of the duplicate key. Assumed to be the document total inclusive of tax. An alternative is to use the sum of `DocumentLines[*].LineTotal + DocumentLines[*].TaxTotal`. `DocTotal` is used here for simplicity (header-level field).
   **Action required**: confirm whether `DocTotal` includes tax (most likely yes in SAP B1) or excludes it, and whether this is consistent across currency types (SGD focus here).

6. **VERIFY AGAINST IRAS SOURCE — duplicate key definition**:
   The task spec gives key = `(CardCode + supplier reference + amount)`. The algorithm uses `DocTotal` as "amount". If the IRAS specification means "pre-tax line amount" rather than "total document amount", the key should use `sum(LineTotal)` instead.
   **Assumption**: DocTotal (document total inclusive of tax) is the most recognisable "invoice total" from the supplier's invoice face, and is the most likely amount a duplicate-entry operator would see and re-enter.

### ZP E2

7. **VERIFY AGAINST IRAS SOURCE — ZP with TaxTotal > 0**:
   ZP is "zero-rated purchase" per IRAS VatGroup mapping. A ZP line with non-zero TaxTotal indicates the supplier charged GST on what should be a zero-rated supply. This is classified as E2 per the pattern established for ZR, OS, ES33, ESN33, BL, NR.
   ASK Annual Review Guide §10.1(d)(iv) covers "tax coded as zero-rated/exempt/out-of-scope but reflects GST."
   **Assumption**: ZP falls within the §10.1(d)(iv) category. This is defensible because ZP is explicitly a zero-rate code.
   **Action required**: VERIFY AGAINST IRAS SOURCE that §10.1(d)(iv) applies to ZP (zero-rated purchases) in the same way it applies to ZR (zero-rated sales). The distinction between sales-side zero-rating (ZR) and purchase-side zero-rating (ZP) may be relevant to whether the same E2 logic applies.

---

## Test counts

| State | Passed | Skipped |
|-------|--------|---------|
| Baseline (before T2.10) | 1026 | 1 |
| After T2.10 autonomous run | 1084 | 1 |
| After SEQ_GAP semantic fix (Phase 1 correction) | 1087 | 1 |
| New tests total added | 61 | 0 |

The 1 skipped test is `tests/test_audit_seal_verify.py::test_T8_readonly_flag` — Windows read-only advisory check, skipped on Windows by design (pre-existing, unchanged).

---

## Phase 1 — Field verification (2026-06-09)

See `exploration-notes/t2.10/FIELD-VERIFICATION.md` for full details.

| Field | Verified | Notes |
|-------|---------|-------|
| `Series` int on Invoices | CONFIRMED | Series=1 (sales), Series=6 (purchases) in SBODEMOSG |
| `Cancelled` tNO/tYES | CONFIRMED (tNO) | tYES not observable — no cancelled invoices in SBODEMOSG |
| `NumAtCard` on PurchaseInvoices | CONFIRMED PRESENT, 0% POPULATED | All null in SBODEMOSG; see DUP_CLAIM note below |
| `DocTotal` tax-inclusive | CONFIRMED | DocTotal = sum(LineTotal) + sum(TaxTotal) exactly |

---

## Phase 1 — SEQ_GAP semantic fix

The autonomous run's SEQ_GAP algorithm was range-filling within the period's `[min, max]` and would have flagged ~617 DocNums (357–956) as gaps on SBODEMOSG Q3 2024, even though those DocNums exist in earlier periods.

**Correction applied**: `detect_seq_gaps(period_records, all_records)` now takes a second argument — the company-wide document population (all periods, all statuses). A DocNum is a gap candidate ONLY when absent from `all_records`. DocNums present anywhere in the company history are NOT flagged, regardless of whether they appear in the reviewed period.

Files changed:
- `orchestrator/check_listing.py` — new 2-arg signature; algorithm rewritten
- `scripts/check_listing_reference.py` — new 2-arg signature; algorithm rewritten independently
- `tests/test_check_listing.py` — all SEQ_GAP tests updated; 2 new tests added:
  - `test_other_period_doc_not_flagged` — critical acceptance test for the fix
  - `test_truly_absent_flagged` — verifies truly-absent DocNums ARE still flagged
  - `test_agree_on_other_period_exclusion` (agreement class)

---

## Phase 2 — Chain wiring (2026-06-09)

### What was wired

| Component | File | Change |
|-----------|------|--------|
| `listing_findings` schema field | `orchestrator/schemas.py` | Added to `CompileOutput` TypedDict |
| `_fetch_headers_paginated` helper | `orchestrator/steps.py` | New private helper for header-only OData fetches with $select |
| `fetch_listing_data` step | `orchestrator/steps.py` | New step: fetches period + company-wide headers for listing checks |
| `compile` step init | `orchestrator/steps.py` | Added `"listing_findings": []` to compile return (consistent with `declared_f5_findings`) |
| Chain wiring | `orchestrator/chain.py` | After gate_5: calls `fetch_listing_data`, `detect_seq_gaps`, `detect_dup_claims`; stores results in `result["listing_findings"]` |
| BOX-ISOLATION assertion | `orchestrator/chain.py` | Snapshots `result["calculate"]["boxes"]` before listing checks; raises RuntimeError on mutation |

### Smoke run results (SBODEMOSG, Q3 2024, 2026-06-09)

| Check | Findings | Expected |
|-------|---------|----------|
| SEQ_GAP (sales) | 0 | 0 (DocNums 357–956 exist in earlier periods) |
| DUP_CLAIM (purchases) | 0 | 0 (NumAtCard 0% populated in SBODEMOSG) |
| BOX-ISOLATION | PASS | Boxes identical before/after listing checks |
| Gate 1 | WARN_PASS | SAP $inlinecount unavailable — normal for this instance |
| Gates 2–5 | PASS | — |
| `listing_findings` key present | YES | — |

**F5 boxes (smoke run)**:
```
box_1_standard_rated_sales:  369,589.97
box_2_zero_rated_sales:       10,000.00
box_3_exempt_sales:            6,000.00
box_4_total_sales:           385,589.97
box_5_taxable_purchases:     191,077.76
box_6_output_tax:             25,871.32
box_7_input_tax:              13,207.45
box_8_net_gst:                12,663.87
```

### DUP_CLAIM: inert on SBODEMOSG

DUP_CLAIM is implemented, unit-tested, and wired into the chain. It returns `[]` on SBODEMOSG because all `NumAtCard` fields are null. This is correct by design — blank vendor reference cannot identify a specific invoice. The check requires client AP data-quality: NumAtCard must be populated by the AP operator when entering purchase invoices. This is a **client-onboarding data-quality precondition**, not a demo-validatable check.

### Period-boundary gap suppression — RESOLVED

The previous heuristic ("cancelled documents explain gaps") was replaced by the semantically correct algorithm: company-wide existence check. A DocNum absent from ALL company records AND within the period's active range is a genuine gap. DocNums present in any period (any status) are not flagged.

The `_fetch_headers_paginated` function paginates with `page_size=20` to match SAP B1 Service Layer's server-side page cap. Using a larger page_size caused the pagination loop to stop after the first page (20 returned < 100 requested = false "last page" sentinel).

---

## What remains NOT done

### No report rendering

No PDF report section was added for SEQ_GAP / DUP_CLAIM findings. Report integration is a downstream concern.

### No purchase-side SEQ_GAP

SEQ_GAP is wired over the SALES listing only (Invoices). The listing data fetch also retrieves purchase invoice headers but the chain currently only runs SEQ_GAP over sales. Purchase-side SEQ_GAP is a separate scope decision.

---

## Hard guardrail verification

| Guardrail | Status |
|-----------|--------|
| No `anthropic` import in orchestrator/ | CLEAN — confirmed by `grep "^import anthropic\|^from anthropic"` |
| reasoning/ not touched | CLEAN |
| documents/ not touched | CLEAN |
| reg2627-*.json not touched | CLEAN |
| show_ai_candidates not touched | CLEAN |
| validation_status not touched | CLEAN |
| declared-f5/T2.9 code not touched | CLEAN |
| All tests hermetic (no live SAP) | CLEAN — `tests/conftest.py` sets dummy creds only for module import |
| No secrets in any file | CLEAN — conftest.py uses "_test_stub_no_sap_" placeholder strings |
| Production + reference with NO shared helper | CLEAN — `orchestrator/check_listing.py` and `scripts/check_listing_reference.py` share zero functions |
| Findings only, no gates/halts | CLEAN — chain catches exception from listing checks; findings never halt the chain |
| DETERMINISTIC ONLY | CLEAN — pure Python arithmetic, no randomness |
| BOX-ISOLATION | CLEAN — runtime assertion in chain.py snapshots boxes before and asserts equality after listing checks; smoke run confirmed no mutation |
| SAP access READ-ONLY | CLEAN — `_fetch_headers_paginated` and `fetch_listing_data` use only GET; no POST/PATCH/PUT/DELETE |
