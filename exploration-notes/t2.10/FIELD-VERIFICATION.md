# T2.10 Phase 1 — Field Verification Report

**Date**: 2026-06-09  
**Environment**: SBODEMOSG (live, READ-ONLY)  
**Period probed**: Q3 2024 (2024-07-01 to 2024-09-30)  
**Probe script**: `exploration-notes/t2.10/probe_fields.py`  
**Status**: COMPLETE — awaiting Terry's "proceed" before any code change

---

## Summary

| Field | Assumed | Actual | Status |
|-------|---------|--------|--------|
| `Series` on Invoices | int, present | int, present; value=1 in Q3 2024 | CONFIRMED |
| `Series` on PurchaseInvoices | int, present | int, present; value=6 in Q3 2024 | CONFIRMED |
| `Cancelled` field name | `Cancelled` | `Cancelled` | CONFIRMED |
| `Cancelled` encoding | `"tNO"` / `"tYES"` | `"tNO"` confirmed; `"tYES"` not seen in SBODEMOSG (0 cancelled invoices exist) | PARTIALLY CONFIRMED — see below |
| `NumAtCard` on PurchaseInvoices | populated vendor ref | 0% populated (all null) across ALL 20 purchase invoices | **CRITICAL FLAG — see below** |
| `DocTotal` is tax-inclusive | yes | yes — DocTotal = sum(LineTotal) + sum(TaxTotal) exactly | CONFIRMED |

---

## (a) Series field

### Invoices (sales)
- Field present: yes  
- Value type: `int`  
- Distinct Series values in Q3 2024: `[1]` — single series only  
- Sample: DocNum 356 → Series=1; DocNums 957–976 → Series=1

### PurchaseInvoices (purchases)
- Field present: yes  
- Value type: `int`  
- Distinct Series values in Q3 2024: `[6]` — single series only  
- Sample: DocNums 591–610 → Series=6

**Conclusion**: `Series` is a standard integer field, present on both entity types. The SEQ_GAP algorithm's group-by-Series logic is correct. SBODEMOSG uses a single series per document type (Series=1 for sales, Series=6 for purchases), so the multi-series path of the algorithm will not fire in SBODEMOSG smoke runs but remains correct for deployments with multiple numbering series.

**No code change required.**

---

## (b) Cancelled field

### Confirmed
- Field name: `Cancelled` ✓  
- Encoding for non-cancelled: `"tNO"` ✓ (matches `_CANCELLED_FALSY` in `check_listing.py`)  
- Field type: `str`

### Not verifiable in SBODEMOSG
- SBODEMOSG has **zero cancelled invoices** across the entire database.  
  Query `GET /Invoices?$filter=Cancelled eq 'tYES'&$top=5` returned 0 results.  
- Therefore `"tYES"` encoding is INFERRED (standard SAP B1 `BoYesNoEnum` for `Cancelled`) but not directly observed.

### Risk assessment
- `"tNO"` is confirmed. `"tYES"` is the standard complement per SAP B1 `BoYesNoEnum` convention (`tYES` / `tNO` is the universal Boolean encoding across the Service Layer).  
- The production code also handles `"Y"`, `"y"`, `"false"`, `""`, `None` defensively.  
- Risk is LOW — the encoding is standard and appears across many other fields in the Service Layer.

**No code change required.**

---

## (c) NumAtCard — CRITICAL FLAG

### Probe results

| Scope | Total PIs | NumAtCard populated | NumAtCard null/empty |
|-------|-----------|--------------------|--------------------- |
| Q3 2024 period | 20 | 0 (0.0%) | 20 (100%) |
| ALL periods (top 100) | 20 | 0 (0.0%) | 20 (100%) |

SBODEMOSG contains exactly **20 purchase invoices** total. Every single one has `NumAtCard = null`.

### Impact on DUP_CLAIM

The DUP_CLAIM check keys on `(CardCode.strip(), NumAtCard.strip(), round(DocTotal, 2))`. Records with blank/null `NumAtCard` are **excluded** from the check by design. Therefore:

> **DUP_CLAIM will produce ZERO findings when run against SBODEMOSG.**

This is NOT a code bug. The implementation is correct per spec — blank vendor reference cannot identify a specific vendor invoice, so such records cannot logically be duplicates of one another. The situation reflects the data in the demo database (AP operators did not enter vendor invoice numbers when creating purchase invoices in SBODEMOSG).

### Does DUP_CLAIM need rethinking?

**Short answer: No — keep the current key.**

Reasoning:
1. In real client deployments, `NumAtCard` is the standard field where AP operators enter the supplier's invoice number. Its population is enforced by internal AP procedure, not by SAP.
2. The IRAS ASK Guide §10.1(d)(i) describes duplicate claims as "processing the same invoice more than once." Without a vendor invoice reference, there is no unambiguous invoice identity — so exclusion is correct.
3. An alternative duplicate-detection key using only `(CardCode, DocTotal)` would produce false positives for recurring charges (same vendor, same amount, different months) — this was explicitly identified as undesirable in the task spec.

**Smoke-run implication**: When the smoke run executes against SBODEMOSG, DUP_CLAIM will return `[]`. This is correct and expected. It does NOT indicate the check is broken.

**No code change required.** The current implementation is correct. Document this in SESSION-REPORT.md.

---

## (d) DocTotal — tax-inclusive confirmation

### PurchaseInvoice 591 (sample)
- `DocTotal` = 4872.97  
- `sum(DocumentLines[*].LineTotal)` = 4554.18  
- `sum(DocumentLines[*].TaxTotal)` = 318.79  
- 4554.18 + 318.79 = **4872.97** ✓ (exact match)

### PurchaseInvoice 610 (ZP fixture)
- `DocTotal` = 856.00  
- `sum(DocumentLines[*].LineTotal)` = 800.00  
- `sum(DocumentLines[*].TaxTotal)` = 56.00  
- 800.00 + 56.00 = **856.00** ✓ (exact match)

**Conclusion**: `DocTotal = sum(LineTotal) + sum(TaxTotal)` — confirmed tax-inclusive.

**Note on SESSION-REPORT documentation**: The autonomous run's SESSION-REPORT.md mentions "DocNum 610 (LineTotal=1200, TaxTotal=84 at 7%)". The live data shows DocTotal=856, LineTotal=800, TaxTotal=56 (7% of 800 = 56). This discrepancy is in the documentation only — the ZP code logic is correct regardless of the specific amounts. The live fixture still demonstrates E2 correctly (ZP VatGroup + TaxTotal > 0).

**No code change required.**

---

## Discrepancies requiring code or doc updates

| # | Item | Action |
|---|------|--------|
| 1 | SESSION-REPORT.md cites DocNum 610 as LineTotal=1200, TaxTotal=84 | Update to 800/56 |
| 2 | None for code | — |

---

## Phase 2 integration plan

### Wire SEQ_GAP into chain

**Additional fields needed from SAP** (not currently fetched by the chain):

| Entity | New fields | Why |
|--------|-----------|-----|
| `Invoices` (sales listing) | `Series`, `Cancelled` | SEQ_GAP groups by Series and uses Cancelled to explain gaps |
| `PurchaseInvoices` (purchases) | `Series`, `Cancelled` | SEQ_GAP on purchase side (if in scope) |

**Chain insertion point**: After the existing `detect` step in `orchestrator/chain.py`, add a new step that:
1. Calls `detect_seq_gaps(sales_records)` over the sales listing  
2. Appends findings to `CompileOutput` under a new `listing_findings: list[dict]` field in `orchestrator/schemas.py`

**BOX-ISOLATION**: `detect_seq_gaps` is read-only over already-fetched data. It does not modify any box figure or any field used by the gate functions. The invariant holds by construction — adding a new findings field to `CompileOutput` does not affect the existing `f5_boxes`, `gate_results`, or `declared_f5_findings` fields.

### Wire DUP_CLAIM into chain

**Additional fields needed**:  
`NumAtCard` and `Cancelled` on `PurchaseInvoices`. `CardCode` and `DocTotal` are already fetched.

**Smoke-run expectation**: `detect_dup_claims(purchase_records)` will return `[]` on SBODEMOSG because all `NumAtCard` are null. This is correct.

### BOX-ISOLATION assertion

```python
# In chain.py, after listing checks:
assert output_with_checks["f5_boxes"] == output_without_checks["f5_boxes"]
assert output_with_checks["gate_results"] == output_without_checks["gate_results"]
```

Or implemented as a test comparing chain output with and without the new checks active.

### CompileOutput schema extension

```python
# In orchestrator/schemas.py — add to CompileOutput:
listing_findings: list[dict]  # SEQ_GAP + DUP_CLAIM findings; empty list if none
```

### Fetch extensions for steps.py

The `build_sales_listing` and `build_purchases_listing` step functions need to include `Series` and `Cancelled` in the `$select` list. No other changes to the fetch logic.

---

## Verification status: COMPLETE

All four assumptions verified. Two are CONFIRMED outright. One (`Cancelled="tYES"`) is confirmed for the `tNO` case with the `tYES` value being the standard SAP complement (low risk). One (`NumAtCard`) is CONFIRMED present but universally null in SBODEMOSG — flagged, assessed as correct-by-design, no code change needed.

**Awaiting Terry's "proceed" before making any code changes.**
