# Credit Note SAP Exploration

**Date**: 2026-05-28
**Task**: T1.1 pre-implementation exploration
**SAP instance**: SBODEMOSG at 35.186.145.230, FP2502

---

## Entity availability

| Entity | HTTP Status | Records accessible |
|---|---|---|
| CreditNotes | 200 | yes |
| PurchaseCreditNotes | 200 | yes |

Both entities returned records with no OData error. The DB contains 9 CreditNotes and
10 PurchaseCreditNotes (all 2015–2023 demo data; none in Q3 2024 — see below).

---

## Field structure

### Fields present on CreditNotes DocumentLines

| Field needed | Present | Actual field name | Notes |
|---|---|---|---|
| VatGroup | yes | `VatGroup` | Exact match |
| LineTotal | yes | `LineTotal` | Exact match |
| TaxTotal | yes | `TaxTotal` | Exact match |
| LineNum | yes | `LineNum` | Exact match |

### Fields present on CreditNotes header

| Field needed | Present | Actual field name | Notes |
|---|---|---|---|
| DocNum | yes | `DocNum` | Exact match |
| DocDate | yes | `DocDate` | Exact match |
| DocCurrency | yes | `DocCurrency` | Exact match |
| CardCode | yes | `CardCode` | Exact match |
| CardName | yes | `CardName` | Exact match |
| FreeText | no | — | Not a header-level field on any document entity in this instance. Confirmed absent on `Invoices` too. At header level, `Comments` and `LegTextF` exist. `FreeText` does appear as a field on DocumentLines (line level only). |

### Fields present on PurchaseCreditNotes DocumentLines

| Field needed | Present | Actual field name | Notes |
|---|---|---|---|
| VatGroup | yes | `VatGroup` | Exact match |
| LineTotal | yes | `LineTotal` | Exact match |
| TaxTotal | yes | `TaxTotal` | Exact match |
| LineNum | yes | `LineNum` | Exact match |

### Fields present on PurchaseCreditNotes header

| Field needed | Present | Actual field name | Notes |
|---|---|---|---|
| DocNum | yes | `DocNum` | Exact match |
| DocDate | yes | `DocDate` | Exact match |
| DocCurrency | yes | `DocCurrency` | Exact match |
| CardCode | yes | `CardCode` | Exact match |
| CardName | yes | `CardName` | Exact match |
| FreeText | no | — | Same as CreditNotes — not a header-level field. `Comments` and `LegTextF` exist at header. `FreeText` appears only at the line level. |

---

## Sign of LineTotal and TaxTotal on credit note lines

**All credit note line amounts are stored as POSITIVE values.**

Evidence from all 9 CreditNotes (20 lines total, all VatGroup=SO):
- DocEntry=1, Line 0: LineTotal=1033.9, TaxTotal=51.69
- DocEntry=1, Line 1: LineTotal=361.9, TaxTotal=18.10
- DocEntry=1, Line 2: LineTotal=504.0, TaxTotal=25.20

Evidence from all 10 PurchaseCreditNotes (50 lines total, all VatGroup=SI):
- DocEntry=1, Line 0: LineTotal=22500.0, TaxTotal=1125.0
- DocEntry=1, Line 1: LineTotal=9000.0, TaxTotal=450.0
- DocEntry=1, Line 2: LineTotal=900.0, TaxTotal=45.0

**Implementation consequence**: The implementation MUST negate credit note line amounts
when subtracting from F5 boxes. Credit notes reduce the same boxes that invoices
increment, so the loop should do `boxes[lt_box] -= line_total` (or equivalently sum
them separately and subtract the total at the end). Summing them directly as positive
values would inflate the boxes instead of reducing them.

---

## Q3 2024 data

### CreditNotes in Q3 2024

None found. Query `DocDate ge '2024-07-01' and DocDate le '2024-09-30'` returned 0
records. Full-year 2024 also returned 0 records.

### PurchaseCreditNotes in Q3 2024

None found. Same filter returned 0 records. Full-year 2024 also returned 0 records.

The entire credit note dataset in SBODEMOSG consists of 9 sales credit notes and 10
purchase credit notes, all dated between 2015 and 2023.

---

## VatGroups found on credit note lines (Q3 2024)

No credit notes in period — not applicable for Q3 2024 specifically.

**All-DB inventory** (for implementation completeness):

| Entity | VatGroup | Line count | In F5_BOX_MAPPING | F5 box(es) |
|---|---|---|---|---|
| CreditNotes | SO | 20 | yes | box_1_standard_rated_sales, box_6_output_tax |
| PurchaseCreditNotes | SI | 50 | yes | box_5_taxable_purchases, box_7_input_tax |

No VatGroups appear in the DB that are outside of F5_BOX_MAPPING. The SBODEMOSG demo
data uses only SO for sales credit notes and SI for purchase credit notes. Real
production data may use a wider set of codes, but no unknown codes were encountered.

---

## Pagination behaviour

All tests performed with `$filter=DocDate ge '...' and DocDate le '...'` plus `$top`
and `$skip` against both entities. The Q3 2024 filter returns zero records, so
pagination was also verified against all-years data (no date filter) to confirm the
mechanism works.

| Parameter | CreditNotes | PurchaseCreditNotes |
|---|---|---|
| $top works | yes | yes |
| $skip works | yes | yes |
| $filter on DocDate works | yes | yes |
| Behaviour matches Invoices entity | yes | yes |

`$top=3` + `$skip=0` → 3 records; `$top=3` + `$skip=3` → next 3 records. No errors
on any combination. The existing `_fetch_invoices_paginated` loop pattern (page size
20, increment `$skip` by 20, stop when `len(page) < 20`) will work identically for
`CreditNotes` and `PurchaseCreditNotes`.

---

## Implementation notes for T1.1

- **All field names match exactly**: `VatGroup`, `LineTotal`, `TaxTotal`, `LineNum`
  at the DocumentLines level and `DocNum`, `DocDate`, `DocCurrency`, `CardCode`,
  `CardName` at the header level are identical across `CreditNotes`,
  `PurchaseCreditNotes`, `Invoices`, and `PurchaseInvoices`. No path differences.

- **FreeText is absent from headers on all document entities** — confirmed missing on
  both credit note types and on `Invoices`. This is consistent SAP B1 Service Layer
  behaviour for this instance. The implementation should not attempt to read
  `doc.get("FreeText")` at the header level; use `Comments` if a remarks field is ever
  needed.

- **LineTotal and TaxTotal are POSITIVE on credit note lines** (confirmed across all
  9 + 10 existing records). The implementation must subtract credit note contributions
  from the F5 boxes, not add them. Recommended pattern: run a separate loop for credit
  notes that does `boxes[lt_box] -= lt` and `boxes[tt_box] -= tt`.

- **No Q3 2024 credit notes exist in SBODEMOSG** — the F5 return for Q3 2024 will
  produce the same result whether or not credit note handling is implemented, which
  means there is no live data to validate the sign logic against. A seed credit note
  should be created as part of T1.1 test setup to verify the subtraction is correct.

- **Pagination is identical to invoices** — `_fetch_invoices_paginated` can be called
  with `"CreditNotes"` and `"PurchaseCreditNotes"` as the entity argument without
  any changes to the pagination logic itself.

- **DocumentLines are returned inline without `$expand`** — the same as for `Invoices`
  and `PurchaseInvoices`. No need to add an `$expand=DocumentLines` parameter to
  `_fetch_invoices_paginated`.

---

## Post-seed reference figures (Q3 2024)

Seed documents created 2026-05-28. Credit Note A (DocNum=10, DocEntry=11) and
Credit Note B (DocNum=11, DocEntry=12) seeded into SBODEMOSG.

SAP B1 applied 7% tax (SBODEMOSG demo rate) to both credit note lines:
- Credit Note A: LineTotal=1000.00, TaxTotal=70.00 (SO)
- Credit Note B: LineTotal=500.00, TaxTotal=35.00 (SI)

| Box | Pre-seed value | Delta | Post-seed value |
|-----|---------------|-------|-----------------|
| Box 1 (standard-rated sales) | 370,589.97 | -1,000.00 | 369,589.97 |
| Box 2 (zero-rated sales) | 10,000.00 | 0 | 10,000.00 |
| Box 3 (exempt sales) | 6,000.00 | 0 | 6,000.00 |
| Box 4 (total sales) | 386,589.97 | -1,000.00 | 385,589.97 |
| Box 5 (taxable purchases) | 128,977.76 | -500.00 | 128,477.76 |
| Box 6 (output tax) | 25,941.32 | -70.00 | 25,871.32 |
| Box 7 (input tax) | 8,860.45 | -35.00 | 8,825.45 |
| Box 8 (net GST payable) | 17,080.87 | -35.00 | 17,045.87 |

NR E2 check confirmed: DocNum 611 (VatGroup=NR, TaxTotal=45.00) appears in Test 3
E2 output after adding NR to `E2_ZERO_RATE_CODES` in both sap_b1_server.py and
run_baseline_tests.py. Also DocNums 605 and 608 (VatGroup=BL) appear as E2.

---

## T1.1 implementation summary

**Date completed**: 2026-05-28

**New function added**: `_fetch_credit_notes_paginated(entity_type, period_start, period_end)`
in `mcp-servers/custom/sap_b1_server.py`. Accepts `"sales"` (CreditNotes) or
`"purchases"` (PurchaseCreditNotes). Same 20-record pagination loop as
`_fetch_invoices_paginated`. Tags each returned record with `is_credit_note=True`.
Does not negate amounts — negation is the caller's responsibility.

**Tools updated**:

- `calculate_f5_return`: fetches credit notes for both sides; subtracts SGD credit
  note line amounts from F5 boxes; adds FX credit notes to the FX list; adds
  `credit_note_counts` and `credit_notes_applied` fields to the output.

- `validate_invoice_tax_codes`: fetches credit note lines and passes them through
  `_classify_line` with `credit_note=True`; includes credit note VatGroups in
  `vatgroup_inventory` counts.

- `detect_gst_errors`: fetches credit note lines for E1–E4 checking; extends
  NO_GST_REG check to purchase credit notes (combined with purchase invoices in
  a single supplier aggregation pass).

**NR added to `_E2_ZERO_RATE_CODES`** in `sap_b1_server.py` — the task description
stated this was done in T1.2 but the code showed NR absent. Added here to make
E2 detection complete and consistent with the Step 3 specification.

**Seed documents created**:

| Label | Entity | DocNum | DocEntry | LineTotal | TaxTotal | VatGroup |
|-------|--------|--------|----------|-----------|----------|----------|
| Credit Note A | CreditNotes | 10 | 11 | 1,000.00 | 70.00 | SO |
| Credit Note B | PurchaseCreditNotes | 11 | 12 | 500.00 | 35.00 | SI |

TaxTotal calculated by SAP B1 at 7% SBODEMOSG demo rate. FreeText="BASELINE_TEST_DATA"
applied at line level in DocumentLines (not header — FreeText is a line-level field
in this instance).

**Updated reference figures for Q3 2024** (all 8 boxes, post-seed):
Box 1=369,589.97 / Box 2=10,000.00 / Box 3=6,000.00 / Box 4=385,589.97 /
Box 5=128,477.76 / Box 6=25,871.32 / Box 7=8,825.45 / Box 8=17,045.87

**NR E2 extension**: DocNum 611 (VatGroup=NR, TaxTotal=45.00) confirmed present in
Test 3 E2 output from reference script after NR added to `E2_ZERO_RATE_CODES`.

**System prompt change**: No explicit "credit notes not checked" caveat was found in
`system-prompts/base.md` — none needed removing. Updated the `calculate_f5_return`
tool description and F5 output format example to mention credit notes and updated
the E2 table to include NR.

**Surprises / deviations**:

- SAP B1 returned 7% TaxTotal on credit note lines (not 9% as the task description
  hoped for). SBODEMOSG demo data enforces 7% via the SO/SI tax codes — cannot
  override at seed time. The 7% figures are the correct reference values for this DB.

- `_E2_ZERO_RATE_CODES` in `sap_b1_server.py` did not contain NR despite the task
  description stating "MCP tool was already updated in T1.2". Added here as part of
  Step 3 (credit note E2 detection requires NR per the spec).

- `run_baseline_tests.py` used the `requests` library (not `httpx`) for its
  `B1Session`. The HTTP method instruction applies to new SAP API calls; the existing
  `requests`-based reference script was left unchanged per "no shared code" principle.
