# v0 Test 3: Error Detection — Raw Response

**Date run:** 2026-05-25
**Model:** Claude Sonnet 4.6
**Configuration:** Claude Desktop, sap-b1 MCP connector only, no project knowledge, no system prompt
**Score:** 2/10

## Prompt

> Using SAP Business One, examine the invoices for Q3 2024 (July to September 2024). Identify any errors, miscodings, or compliance issues in the GST treatment. Report each issue you find with the document number, the problem, and your recommendation.

## Response (verbatim)

*Claude connected to SBODEMOSG and made multiple sap_query calls: pulling Q3 2024 invoices, line-level detail on flagged invoices, business partner records for customers including River Inc (C26000), SG Electronics (C60000), ADA Technologies (C50000), and Aquent Systems (C70000), and GST tax code definitions. Verified Singapore's 9% GST rate effective 1 January 2024.*

Here is a summary of what the audit found across the 52 Q3 2024 invoices.

**3 critical issues require immediate action:**

The most significant is a systemic one: the `SO` and `SI` VatGroup records in SAP still carry a 7% rate, but Singapore GST rose to 9% on 1 January 2024. Every standard-rated invoice in Q3 has been undercharging GST by 2 percentage points. You'll need to quantify the shortfall across all affected documents and consider a voluntary disclosure to IRAS if the amount is material.

The second critical issue is on INV-1001 (River Inc, SGD 3,000 for "Financial Advisory Service"), where Regulation 33 exemption (ES33) has been applied without clear evidence that the recipient is an overseas person. The customer has a UK VAT number but Singapore billing and ship-to addresses — this is contradictory and the exemption is unsupported as recorded. A correction is needed.

Third, INV-356 (Maxi-Teq, SGD 214 for stationery) has output GST applied to what appears to be a disbursement recharge — zero quantity, no item code, expense account posting. Disbursements are out-of-scope under IRAS rules and should not carry GST.

**3 warnings** relate to INV-1002 (River Inc "Overseas Goods" coded OS but shipped to a Singapore address), the ADA Technologies EUR-denominated invoices where the currency and local delivery address are inconsistent, and Aquent Systems invoices where overseas registration needs verification before standard-rating is confirmed.

**1 informational note:** the three River Inc invoices on 15 July have no comments, no source document chain, and were split across three separate invoices — unusual compared to every other invoice in the period, and worth documenting properly for audit trail purposes.

I'd recommend starting with the 9% rate correction in the VatGroup master as the highest-priority fix, since it affects the entire population of Q3 invoices. Let me know if you'd like me to drill into any specific invoice in more detail.

## Tool usage confirmation

*[Add the result of the meta-question you asked Claude here, confirming which tools were called — should show only the original 11 read-only MCP tools, not the 3 new ones.]*

## Failure analysis

See `../baseline-test-results.md` § "Baseline Test 3" for full score breakdown.

**Headline:** Claude found 7 issues, of which only 2 (ADA and Aquent FX patterns) overlap with the 19 known real issues, and only at customer level — not enumerated by DocNum as the prompt required. Missed all 11 specific E1 DocNums, the E2 on DocNum 605, and all 7 NO_GST_REG findings. Most critically, Claude *invented* a "highest-priority critical" finding — the 7%/9% rate gap — that is actually a demo data artefact, not a real compliance issue. Also misunderstood ES33's semantics. The false positive on the rate gap is materially dangerous: a non-expert user acting on Claude's recommendation would file an erroneous voluntary disclosure to IRAS.

**Key gap exposed:** G14 — plain Claude produces confident false positives in compliance contexts. This is the strongest argument in the v0 results for why the AgentAssist architecture (tools + system prompt + knowledge base) is necessary, not just helpful.