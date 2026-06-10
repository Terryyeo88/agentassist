# T2.10 Implementation Plan

## Baseline confirmation
- Worktree: `../aa-t2.10` off master (branch `t2.10-listing-checks`)
- Venv: `aa-t2.10/venv`
- Fixtures regenerated: `tests/fixtures/documents/generate_invoices.py` → 8 PDFs + manifest
- Baseline test state: **1026 passed, 1 skipped** (identical to master)

---

## Scope: three checks, nothing else

| # | Check | IRAS Basis | Location |
|---|-------|-----------|---------|
| 1 | SEQ_GAP — invoice sequence gap detection | ASK Annual Review Guide §10.1(c)(i) | `orchestrator/check_listing.py` |
| 2 | DUP_CLAIM — duplicate input-tax claim | ASK Annual Review Guide §10.1(d)(i) | `orchestrator/check_listing.py` |
| 3 | ZP E2 extension — add ZP to zero-rate code set | ASK Annual Review Guide §10.1(d)(iv) | `mcp-servers/custom/sap_b1_server.py` + `scripts/run_baseline_tests.py` |

---

## Insertion points

### Check 1 (SEQ_GAP) + Check 2 (DUP_CLAIM)

**Production path**: New module `orchestrator/check_listing.py`
- `detect_seq_gaps(records: list[dict]) -> list[dict]` — SEQ_GAP production
- `detect_dup_claims(records: list[dict]) -> list[dict]` — DUP_CLAIM production

**Independent reference**: New module `scripts/check_listing_reference.py`
- `ref_detect_seq_gaps(records: list[dict]) -> list[dict]` — SEQ_GAP reference (NO shared helpers)
- `ref_detect_dup_claims(records: list[dict]) -> list[dict]` — DUP_CLAIM reference (NO shared helpers)

Both modules are pure Python, no `anthropic` import, no SAP calls, no shared helpers.

### Check 3 (ZP E2 extension)

**Production path**: `mcp-servers/custom/sap_b1_server.py`
- Line 352: Add "ZP" to `_E2_ZERO_RATE_CODES`

**Reference**: `scripts/run_baseline_tests.py`
- Line 88: Add "ZP" to `E2_ZERO_RATE_CODES`

---

## SAP field assumptions (VERIFY flags)

### SEQ_GAP

| Field | Assumption | Verify flag |
|-------|-----------|-------------|
| `Series` (int) | SAP B1 OData integer field identifying the numbering series. Standard field present on all document types. | VERIFY SAP FIELD: confirm `Series` is exposed by Service Layer OData for `Invoices` and `PurchaseInvoices` |
| `Cancelled` (str) | `"tYES"` when document is cancelled, per SAP B1 Service Layer `YNGroupEnum` convention. Cancelled documents retain their DocNum slot. | VERIFY SAP FIELD: confirm `Cancelled` field name and value encoding on Service Layer |

**Defensible assumption for algorithm**: A cancelled document still appears in the listing with its DocNum and `Cancelled="tYES"`. The check receives the full listing (active + cancelled) and uses Cancelled to explain gaps.

### DUP_CLAIM

| Field | Assumption | Verify flag |
|-------|-----------|-------------|
| `NumAtCard` (str) | "Number at Vendor" — the supplier's own invoice number as entered in SAP B1. Standard `NumAtCard` field on `PurchaseInvoices`. Blank/None means no vendor reference captured. | VERIFY SAP FIELD: confirm `NumAtCard` is the correct OData field for vendor invoice reference |

**Defensible assumption for algorithm**: Duplicate key = (CardCode, NumAtCard.strip(), round(DocTotal, 2)). Documents with blank/None NumAtCard are excluded from duplicate detection (blank ref cannot identify a specific vendor invoice).

---

## Algorithm definitions

### SEQ_GAP

```
Input: list of records with {DocNum: int, Series: int, Cancelled: str}
1. Split into: cancelled_nums_by_series = {series: {doc_nums}}
               active_records_by_series = {series: [records]}
2. For each series in active_records_by_series:
   a. sorted_nums = sorted unique DocNums for this series
   b. if len(sorted_nums) < 2: skip (can't define a sequence from 1 doc)
   c. min_n = min(sorted_nums), max_n = max(sorted_nums)
   d. expected = set(range(min_n, max_n + 1))
   e. present = set(sorted_nums)
   f. gaps = expected - present
   g. For each gap_num in gaps:
      - if gap_num in cancelled_nums_by_series[series]: skip (cancelled explains it)
      - else: emit SEQ_GAP candidate
Output: list of {check: "SEQ_GAP", series: ..., gap_doc_num: ..., series_range: [min, max], description: ..., basis: "IRAS ASK Annual Review Guide §10.1(c)(i)"}
```

PERIOD BOUNDARY note: gaps before min_n or after max_n are never flagged — they could be out-of-period documents continuing the same series. The algorithm only flags gaps strictly within [min_n, max_n].

### DUP_CLAIM

```
Input: list of records with {DocNum: int, CardCode: str, NumAtCard: str, DocTotal: float}
1. Filter to records where NumAtCard is non-blank
2. key = (CardCode.strip(), NumAtCard.strip(), round(DocTotal, 2))
3. Group by key → {key: [doc_nums]}
4. For any key with len(doc_nums) > 1: emit DUP_CLAIM candidate per doc_num pair
Output: list of {check: "DUP_CLAIM", doc_num: ..., duplicate_of: ..., card_code: ..., num_at_card: ..., doc_total: ..., description: ..., basis: "IRAS ASK Annual Review Guide §10.1(d)(i)"}
```

RECURRING CHARGE note: Same amount + same vendor + DIFFERENT NumAtCard is NOT a duplicate. The algorithm only matches on NumAtCard (not just amount) so identical amounts from the same vendor with different vendor invoice refs are not flagged.

---

## Synthetic fixtures

### SEQ_GAP acceptance fixture (for `tests/test_check_listing.py`)

```python
SEQ_GAP_FIXTURE = [
    # Series 1 — genuine gap at 102 (not cancelled)
    {"DocNum": 101, "Series": 1, "Cancelled": "tNO"},
    {"DocNum": 103, "Series": 1, "Cancelled": "tNO"},  # 102 missing → SEQ_GAP
    {"DocNum": 104, "Series": 1, "Cancelled": "tNO"},

    # Series 1 — gap at 106 explained by cancelled doc
    {"DocNum": 105, "Series": 1, "Cancelled": "tNO"},
    {"DocNum": 106, "Series": 1, "Cancelled": "tYES"},  # cancelled → NOT a gap
    {"DocNum": 107, "Series": 1, "Cancelled": "tNO"},

    # Series 2 — different series, no gaps within its range
    {"DocNum": 201, "Series": 2, "Cancelled": "tNO"},
    {"DocNum": 202, "Series": 2, "Cancelled": "tNO"},
]
# Expected: exactly one SEQ_GAP for DocNum 102 in Series 1
```

### DUP_CLAIM acceptance fixture

```python
DUP_CLAIM_FIXTURE = [
    # True duplicate: same CardCode + NumAtCard + DocTotal → flagged
    {"DocNum": 501, "CardCode": "V10000", "NumAtCard": "INV-ABC-001", "DocTotal": 1000.00},
    {"DocNum": 502, "CardCode": "V10000", "NumAtCard": "INV-ABC-001", "DocTotal": 1000.00},

    # Recurring charge: same amount + same vendor, DIFFERENT NumAtCard → NOT flagged
    {"DocNum": 503, "CardCode": "V10000", "NumAtCard": "INV-MONTHLY-JUL", "DocTotal": 500.00},
    {"DocNum": 504, "CardCode": "V10000", "NumAtCard": "INV-MONTHLY-AUG", "DocTotal": 500.00},

    # Different vendor, same ref → NOT flagged (different CardCode)
    {"DocNum": 505, "CardCode": "V20000", "NumAtCard": "INV-ABC-001", "DocTotal": 1000.00},
]
# Expected: exactly one DUP_CLAIM pair (DocNums 501 and 502)
```

### ZP E2 acceptance fixture

```python
ZP_LINE = {"VatGroup": "ZP", "LineTotal": 1200.00, "TaxTotal": 84.00, "LineNum": 0}
ZP_DOC = {"DocNum": 610, "DocDate": "2024-07-15", "DocCurrency": "SGD",
          "CardName": "Test Vendor", "CardCode": "V10000"}
# Expected: _classify_line(ZP_LINE, ZP_DOC, entity_type="purchase") → E2 issue
# Expected: E2_ZERO_RATE_CODES contains "ZP" in run_baseline_tests.py
```

---

## Acceptance criteria

| Check | Test | Expected |
|-------|------|----------|
| SEQ_GAP | `test_seq_gap_genuine_gap_flagged` | DocNum 102 gap in Series 1 → 1 SEQ_GAP candidate |
| SEQ_GAP | `test_seq_gap_cancelled_explains_gap` | DocNum 106 cancelled → NOT flagged |
| SEQ_GAP | `test_seq_gap_multi_series_no_cross_gap` | Series 2 separate → no cross-series gaps |
| SEQ_GAP | `test_seq_gap_production_reference_agree` | Both impls return identical candidate list on shared fixture |
| DUP_CLAIM | `test_dup_claim_true_dup_flagged` | DocNums 501+502 (same key) → 1 DUP_CLAIM pair |
| DUP_CLAIM | `test_dup_claim_recurring_not_flagged` | DocNums 503+504 (different NumAtCard) → NOT flagged |
| DUP_CLAIM | `test_dup_claim_production_reference_agree` | Both impls return identical candidate list |
| ZP E2 | `test_zp_line_flagged_e2_production` | `_classify_line` flags ZP+TaxTotal=84 as E2 |
| ZP E2 | `test_zp_line_flagged_e2_reference` | `E2_ZERO_RATE_CODES` contains "ZP" and logic flags it |
| ZP E2 | `test_existing_e2_cases_not_regressed` | All prior E2 codes (ZR, OS, etc.) still flagged |
| ZP E2 | `test_zp_zero_tax_not_flagged` | ZP line with TaxTotal=0 → NOT an E2 |

---

## Files to create/modify

| Action | File | Purpose |
|--------|------|---------|
| CREATE | `orchestrator/check_listing.py` | Production SEQ_GAP + DUP_CLAIM |
| CREATE | `scripts/check_listing_reference.py` | Independent reference implementations |
| CREATE | `tests/test_check_listing.py` | Tests for all three checks |
| MODIFY | `mcp-servers/custom/sap_b1_server.py` | Add ZP to `_E2_ZERO_RATE_CODES` |
| MODIFY | `scripts/run_baseline_tests.py` | Add ZP to `E2_ZERO_RATE_CODES` |
| CREATE | `exploration-notes/t2.10/SESSION-REPORT.md` | Post-run session report |

## Hard guardrails checklist

- [ ] No `anthropic` import in orchestrator/
- [ ] Does not touch: reasoning/, documents/, reg2627-*.json, show_ai_candidates, validation_status, declared-f5/T2.9 code
- [ ] All new tests hermetic (no live SAP)
- [ ] No secrets in any file
- [ ] Production + independent reference with NO shared helper
- [ ] Findings only — no gates, no chain halts, no data mutation
