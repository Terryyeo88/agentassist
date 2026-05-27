## Seed Invoice Result (2026-05-27)

**DocEntry**: 613
**DocNum**: 611
**LineTotal**: 500.00
**TaxTotal**: 45.00 (preserved by SAP B1 tax engine)
**VatGroup**: NR

**Finding**: SAP B1 preserved the non-zero TaxTotal on the NR line. This invoice is
therefore both a Box 5 exclusion test (LineTotal 500.00 must not appear in Box 5
after the T1.2 fix) and a genuine E2 error (non-taxable purchase carrying GST).
The E2 check in `validate_invoice_tax_codes` should flag this invoice. Verify this
when running the next Test 2 or Test 3 pass.

**Action**: No further seed change needed. Both test angles are active.
