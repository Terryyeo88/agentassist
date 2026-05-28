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

---

## DocNum 611 — confirmed E2 fixture (added post-T1.2)

Confirmed via live query 2026-05-28: DocNum 611 carries VatGroup NR,
LineTotal 500.00, TaxTotal 45.00. Rate is 9% (500 × 0.09 = 45.00) — an
anomaly against the SBODEMOSG demo norm of 7%. SAP's tax engine applied
the current statutory rate to the NR-coded line at seed time.

The line is retained as a known E2 fixture. NR with TaxTotal > 0.01 is a
genuine compliance error — the tool correctly flags it. The _E2_ZERO_RATE_CODES
addition (NR) that was deferred from T1.2 and completed in T1.1 is what
enables this detection.

The 9% rate anomaly is documented here and in test_data_registry.json. It
does not affect E2 detection. Monitor for E4 double-flagging if E4 logic
is extended beyond SO/SI in future.
