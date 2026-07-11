# Xero real-format fixtures (real format, synthetic content)
Captured from a Singapore-localised Xero org with synthetic transactions.
Honest rung: real Xero EXPORT format over SYNTHETIC content.
NOT real-client-export-validated. NOT accuracy-validated. T2.11 unmoved.

Files / surfaces:
- AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx — two sheets: `Return`
  (box summary) and `Transactions by box number` (line detail, incl. a
  `Transactions not included` section at the foot).
- AgentAssist_-_Account_Transactions.xlsx — GST control-account (820) ledger,
  period 1 Apr–30 Jun 2026, sheet `GST Transactions`.
- SalesInvoices_AgentAssist_*.csv — Xero sales-invoice export (carries credit
  notes inline).
- Contacts.csv — contact master incl. TaxNumber column.

What the corpus exercises (intended fixtures):
- E2: INV-2003 (ZR-Broken) — zero-rated code carrying 9% tax.
- E3: INV-2002 (SR-NoGST) — standard-rated code carrying 0 tax.
- E4/stale-rate: BILL-3002 (SI-Stale 8%) among 9% peers.
- Quotation-in-filing: BILL-3004 ("Server hardware (quotation)").
- Standing-order duplicate (MUST NOT fire): BILL-3004 + BILL-3005, same
  supplier + amount, different references.
- NO_GST_REG: NoReg Trading has a blank TaxNumber + claims input tax on BILL-3003.
- Blocked-input (Reg 26/27) surface cases: BILL-3006 (entertainment),
  BILL-3007 (private passenger car) — sit in Box 7 as claimed; semantic/
  reasoning-layer catch, NOT arithmetic.
- In-period credit note: CN-0002 (29 Jun) folds into Box 1/6 as a NEGATIVE
  line (−2000 net / −180 tax); ledger shows a +180 reversal.
- Manual-journal drop-out: MJ-RAWGL (GST posted raw to acct 820, no tax code)
  appears in the F5 `Transactions not included` section and in the ledger, but
  NOT in any box; MJ-CODED (tax-coded) IS in Box 5/7. VERIFIED on SG org.

Known gaps / cautions:
- Cross-period credit note NOT yet captured (this CN is in-period).
- Ledger `Total GST` / `Closing Balance` rows do NOT foot cleanly under
  accrual + unpaid invoices — a display artifact. Any reconciliation must
  recompute from line-level Debit/Credit, never trust the totals row.
- GST basis: ACCRUAL.
