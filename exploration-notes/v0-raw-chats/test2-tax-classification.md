# v0 Test 2: Tax Code Classification — Raw Response

**Date run:** 2026-05-25
**Model:** Claude Sonnet 4.6
**Configuration:** Claude Desktop, sap-b1 MCP connector only, no project knowledge, no system prompt
**Score:** 6/10

## Prompt

> Look at the invoices in SAP B1. Classify each transaction by GST type: standard-rated, zero-rated, exempt, or out-of-scope.

## Response (verbatim)

*Claude queried the VatGroups entity to retrieve full code-to-meaning definitions, then queried Invoices with DocumentLines expanded. Pulled one page of 20 sales invoices (B1's hard pagination cap) and did not paginate further. Did not query PurchaseInvoices.*

Now I have the full VAT group definitions. Let me classify all 20 invoices and render the results.

Here's the classification across all 20 invoices retrieved from SAP B1. Every invoice uses VAT group SO — "Sales Standard Rated Supplier SR", which maps to standard-rated GST in Singapore's GST framework. No zero-rated, exempt, or out-of-scope transactions appear in this batch.

A few things worth noting:

**VAT rate consistency** — the effective GST rate on all lines is ~7% (the pre-GST-hike rate), which aligns with the invoice dates ranging from 2015 to 2024 (before Singapore's January 2024 rate increase to 9%).

**Foreign currency invoices** — docs 88, 89, 90, 95, 96, and 97 are billed in EUR or USD to customers like ADA Technologies, SG Electronics, and Aquent Systems. Even though these are foreign-currency transactions, they still carry the SO VAT group, suggesting these are local Singapore supplies invoiced in foreign currency — still standard-rated. If any of these customers are overseas and the supply is made outside Singapore, those lines may warrant reclassification to ZR (zero-rated).

**GST group definitions in your system that are set up but unused in this batch:**

- `ZR` — Sales Zero Rated (0%)
- `ES33` / `ESN33` — Exempt sales (Reg 33 and non-Reg 33)
- `OS` — Out of Scope

Would you like me to pull more invoices, check purchase invoices, or flag the foreign-currency ones for potential reclassification review?

*[A transaction-level table was also rendered in the chat UI but is not reproduced here — it was a 20-row aggregation of the same SO-classified invoices, adding no information beyond the prose summary above. The chat record is preserved under project chat "SAP B1 invoice GST classification" for future reference if needed.]*

## Failure analysis

See `../baseline-test-results.md` § "Baseline Test 2" for full score breakdown and gaps catalogue.

**Headline:** Methodology was correct (queried VatGroups entity, queried DocumentLines for line-level VatGroup, detected FX+SO mismatch pattern), but Claude saw only 20 of ~64 invoices because B1's 20-record pagination cap stopped the query at the first page. Reported finding only 1 VatGroup (SO) when 8 exist in the full Q3 2024 dataset. Did not examine purchase invoices at all. Did not filter by period — pulled invoices spanning 2015–2024.

**Key gap exposed:** G10 — the pagination cap. This is the same root cause behind several Test 1 failures and will be the single biggest target for v2 (system prompt: "always paginate until len(results) < 20") and v3 (tools that handle pagination internally).

**Partial credit for the FX+SO detection:** Even within its 20-invoice sample, Claude correctly flagged the FX+SO pattern as suspicious — *"if any of these customers are overseas and the supply is made outside Singapore, those lines may warrant reclassification to ZR."* This is the exact pattern the agent must detect in production, and plain Claude did identify it conceptually (though without the systematic detection needed to catch all 11 instances across the full period).