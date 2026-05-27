# DocNum 605 — TaxTotal Verification

**Date:** 2026-05-26
**Script:** `scripts/verify_docnum_605.py`
**Purpose:** Determine whether DocNum 605 (VatGroup=BL purchase invoice) qualifies
as an E2 error, resolving an open question in the Test 3 scoring rubric.

---

## Query Used

```
GET /PurchaseInvoices?$filter=DocNum eq 605
```

Endpoint: `https://35.186.145.230:55000/b1s/v2/PurchaseInvoices`
Database: SBODEMOSG | User: manager | Run: 2026-05-26 13:42:13 UTC

---

## Full Output

```
HEADER FIELDS
----------------------------------------
  DocEntry            : 606
  DocNum              : 605
  DocDate             : 2024-07-15
  CardCode            : V10000
  CardName            : Acme Associates
  DocCurrency         : SGD
  DocTotal            : 856.0
  VatSum              : 56.0
  DocTotalFc          : 0.0

DOCUMENT LINES (1 line(s))
----------------------------------------
  Line 0:
    ItemCode       : Z00002
    ItemDescription: Staff Club Membership
    VatGroup       : BL
    LineTotal      : 800.00
    TaxTotal       : 56.00
    VatPercent     : 7.0
    *** E2 candidate: BL line with TaxTotal=56.00 > 0 ***

SUMMARY
----------------------------------------
  DocNum 605 has 1 line(s).
  Lines with VatGroup=BL and TaxTotal>0.01: 1
  E2 status: TRUE
```

---

## Conclusion

**DocNum 605 IS an E2 error.**

The single line (Staff Club Membership, ItemCode Z00002, LineTotal SGD 800.00) carries
VatGroup=BL with TaxTotal=56.00 (exactly 7% of 800.00). BL is the "Blocked input tax
(Reg 26/27)" code — GST on a blocked purchase is not claimable and should never appear in
Box 7. Having TaxTotal > 0 on a BL line means GST was charged or posted when it should not
have been. This is the definition of an E2 error.

The invoice was created by `scripts/seed_test_data.py` with `VatGroup=BL` and
`UnitPrice=800.00`. SAP B1 applied the 7% rate configured for the BL tax code in SBODEMOSG,
producing TaxTotal=56.00. That SAP B1 does this is itself a data quality issue: the BL code
should be configured with rate=0% so that no tax is computed, but in the demo database it has
rate=7%. The consequence is a live E2 error in the seeded data.

---

## Why the Python reference script did not flag it

`scripts/run_baseline_tests.py` applies the E2 check only to `invoices` (sales), not to
`purchase_invoices`. The relevant code (lines 332–334):

```python
# E2: GST charged (VatSum > 0) on non-taxable supply
if vat_sum > 0.01 and vg in ZERO_RATE_SALES:
    errors.append(...)
```

`ZERO_RATE_SALES = {"ZR", "OS", "ES33", "ESN33"}` — BL is absent, and this check runs only
inside the `for doc in invoices:` loop. Purchase invoices are processed separately but only
for E3 and E4 (SI with zero tax, and rate deviations). The reference script has no E2 check
on the purchase side at all.

The MCP tool `detect_gst_errors` (and `validate_invoice_tax_codes`) use `_classify_line` on
both sales and purchase invoices, and `_E2_ZERO_RATE_CODES` includes BL:

```python
_E2_ZERO_RATE_CODES = {"ZR", "OS", "ES33", "ESN33", "BL"}
```

This means the MCP tool IS more comprehensive than the reference script for E2 detection, and
its detection of DocNum 605 as E2 is correct.

---

## Implications for the Test 3 scoring rubric

The open question in `AGENTASSIST_TECHNICAL_STATE.md` (Appendix C, item 3) was:

> "Was the BL purchase invoice seeded with a non-zero TaxTotal of 56.00 deliberately, or did
> SAP B1 apply tax when VatGroup=BL was set? If SAP B1 correctly blocks tax on BL-coded lines,
> DocNum 605 should have TaxTotal=0 and would NOT be an E2 error."

**Answer:** SAP B1 applied tax (7%) to the BL line. DocNum 605 has TaxTotal=56.00 confirmed
live. The E2 finding is real.

**Implication:** The Test 3 scoring rubric entry "1 × E2 — DocNum 605 has VatGroup=BL but
TaxTotal=SGD 56.00" is **correct**. It was not manually fabricated; it reflects the actual
data state. The Python reference script simply has incomplete E2 coverage (purchase-side E2
not implemented), which is an acknowledged gap in the reference script, not an error in the
rubric.

The `validate_invoice_tax_codes` and `detect_gst_errors` MCP tools correctly detect this
error. The v3 Test 2 score of 10/10 (which includes E2 detection credit) is valid.

To fully close this topic: the Python reference script should be extended to apply E2 checks
to purchase invoices as well, bringing its coverage in line with the MCP tools. This would
allow the full Test 3 reference (E1 + E2 + NO_GST_REG) to be auto-generated rather than
requiring a combination of script output and manual identification.
