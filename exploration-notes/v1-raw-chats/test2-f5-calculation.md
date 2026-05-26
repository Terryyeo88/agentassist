# v1 Test 2: Tax Code Classification — Raw Response

**Date run:** 2026-05-25
**Model:** Claude Sonnet 4.6
**Configuration:** Claude Desktop, sap-b1 MCP connector + Project knowledge base (sg-tax-code-mappings.md + IRAS rules), no system prompt, no new tools
**Score:** 5/10 (rubric) | Recall: 2/8 VatGroups (25%)

## Prompt

> Look at the invoices in SAP B1. Classify each transaction by GST type: standard-rated, zero-rated, exempt, or out-of-scope.

## Response (verbatim)

Now let me also check purchase invoices for a fuller picture:Now I have enough to render a comprehensive classification. Let me build the visual.Here's the classification summary across all invoices retrieved from SBODEMOSG:

**Sales invoices (20 transactions) — all standard-rated**

Every sales invoice line carries VAT group `SO` (Sales Standard-Rated). Under the F5 mapping, these flow into Box 1 (net value, excl. GST) and Box 6 (GST charged). No zero-rated, exempt, or out-of-scope sales were found in this batch, which is consistent with a Singapore IT hardware distributor selling domestically.

**Purchase invoices (20 sampled) — all standard-rated**

All purchase lines carry VAT group `SI` (Purchase Standard-Rated). These belong in Box 5 (taxable purchases, excl. GST) and Box 7 (input tax claimed), provided valid tax invoices with supplier GST registration numbers are held. None of the blocked (`BL`), exempt (`EP`), non-registered (`NR`), or import scheme codes (`IM`, `ME`, `IGDS`) appear in this sample.

**One thing to flag:** The demo database uses a 5–7% GST rate (pre-2024 data). The current Singapore rate is 9% since 1 Jan 2024. The VAT group codes themselves are correctly set up for F5 classification — this is purely a rate artefact in the demo data and not a compliance issue for the POC, but you'd need to verify rates against live data before any production use.

Want me to check for any other VAT groups across the full invoice dataset, or move on to computing the F5 box totals?

## Failure analysis

See `../baseline-test-results.md` § "v1 Test 2" for full score breakdown and gap status.