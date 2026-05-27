# v3 Test 3: Error Detection — Raw Response

**Date run:** 2026-05-26
**Model:** Claude Sonnet 4.6
**Configuration:**
- Claude Desktop, sap-b1 MCP connector (all 14 tools enabled, including
  the three custom GST tools)
- Project knowledge: sg-tax-code-mappings.md LOADED
- System prompt: base.md LOADED (attached to project)
- Custom GST tools (calculate_f5_return, validate_invoice_tax_codes,
  detect_gst_errors): EXPOSED and called by Claude

**Score:** 10/10

**Reference set (from baseline-test-report-v0.json, generated 2026-05-26):**
- 11 E1 line-level findings across 8 DocNums: 958, 964, 965, 967 (×2),
  971, 974 (×3), 977, 982
- 1 E2: DocNum 605
- 7 NO_GST_REG suppliers: V1010 Far East Imports, V70000 SMD Technologies,
  V20000 Lasercom, V60000 CTI Computers, V30000 Blockies Corporation,
  V50000 Lumarx, V10000 Acme Associates
- 0 COMPLETENESS, 0 E3, 0 E4

---

## Prompt

> Using SAP Business One, examine the invoices for Q3 2024 (July to September 2024). Identify any errors, miscodings, or compliance issues in the GST treatment. Report each issue you find with the document number, the problem, and your recommendation.

## Response (verbatim)

> I'll run a GST compliance audit for Q3 2024 (1 Jul 2024 – 30 Sep 2024). Let me start by logging into SAP B1 and then use the `detect_gst_errors` tool to get a comprehensive analysis.
>
> Connected to SBODEMOSG. Now let me load and run the error detection tool.
>
> Good. I'll run both `detect_gst_errors` and `validate_invoice_tax_codes` in parallel for a complete picture. The demo DB uses 7%, so I'll use the default `expected_rate` of 0.07.
>
> Comprehensive results. Let me also run the line-level validator to make sure nothing was missed.
>
> I now have everything I need. Let me log out and compile the full report.
>
> Here is the full audit report for Q3 2024.
>
> ---
>
> ## GST Compliance Audit — Q3 2024 (1 Jul – 30 Sep 2024)
> **Database:** SBODEMOSG · **Total issues found:** 19 (18 HIGH, 1 MEDIUM)
>
> > **Reminder:** SBODEMOSG is a demo environment. No findings here carry regulatory significance, and the 7% GST rate stored in the demo DB is a pre-2024 data artefact — it is not a compliance error and has not been flagged below.
>
> ---
>
> ### Category 1 — E1: Foreign-Currency Invoices Coded SO (HIGH) · 11 line instances across 7 documents
>
> These invoices are denominated in USD or EUR but are coded **SO** (standard-rated output, 9% GST). Overseas sales should ordinarily be **ZR** (zero-rated) under s21(3) of the GST Act. Coding them SO incorrectly charges GST on exports and causes the output tax in Box 6 to be overstated.
>
> | Doc # | Date | Customer | Currency | Lines affected | VatGroup | LineTotal (FX) | TaxTotal (FX) |
> |-------|------|----------|----------|----------------|----------|---------------|---------------|
> | 958 | 2 Jul 2024 | SG Electronics | USD | 1 | SO | 1,057.50 | 74.03 |
> | 964 | 9 Jul 2024 | Aquent Systems | USD | 1 | SO | 5,250.00 | 367.50 |
> | 965 | 9 Jul 2024 | Aquent Systems | USD | 1 | SO | 367.50 | 25.73 |
> | 974 | 11 Jul 2024 | SG Electronics | USD | 3 | SO | 36,086.25 | 2,526.04 |
> | 971 | 24 Jul 2024 | ADA Technologies | EUR | 1 | SO | 66.45 | 4.65 |
> | 967 | 28 Jul 2024 | ADA Technologies | EUR | 2 | SO | 3,850.00 | 269.50 |
> | 977 | 29 Jul 2024 | Aquent Systems | USD | 1 | SO | 775.40 | 54.28 |
> | 982 | 3 Aug 2024 | ADA Technologies | EUR | 1 | SO | 24,850.00 | 1,739.50 |
>
> **Recommendation for each:** Confirm whether the customer is an overseas entity receiving an export of goods or international service. If so, reclassify all affected lines from SO → ZR. Note that these invoices are also excluded from F5 box totals until converted to SGD using an IRAS-acceptable exchange rate methodology (MAS, Bloomberg, Reuters, Oanda, or local bank rates — updated at least quarterly and applied consistently).
>
> ---
>
> ### Category 2 — NO_GST_REG: Input Tax Claimed Without Supplier GST Registration Number (HIGH) · 7 purchase invoices
>
> Input tax claims in Box 7 require a valid tax invoice bearing the supplier's GST registration number (IRAS para 5.13). The following supplier records have a blank or missing `FederalTaxID`, making any input tax claimed on their invoices potentially unclaimable.
>
> | Doc # | Date | Supplier | Supplier Code | Amount at Risk |
> |-------|------|----------|---------------|----------------|
> | 605 | 15 Jul 2024 | Acme Associates | V10000 | (see E2 note below) |
> | 592 | 16 Jul 2024 | Far East Imports | V1010 | — |
> | 594 | 16 Jul 2024 | SMD Technologies | V70000 | — |
> | 595 | 20 Jul 2024 | Lasercom | V20000 | — |
> | 604 | 17 Aug 2024 | Lumarx | V50000 | — |
> | 600 | 20 Aug 2024 | CTI Computers | V60000 | — |
> | 601 | 27 Aug 2024 | Blockies Corporation | V30000 | — |
>
> **Recommendation:** For each supplier, obtain a tax invoice that includes a valid Singapore GST registration number. If the supplier is not GST-registered, the purchase must be reclassified from SI → NR, the input tax claim in Box 7 must be reversed, and the line must be excluded from Box 5 as well (IRAS para 5.11(o)). Do not assume these suppliers are unregistered — verify directly with each supplier or check the IRAS GST register.
>
> ---
>
> ### Category 3 — E2: GST Charged on a Blocked (BL) Line (MEDIUM) · 1 instance
>
> | Doc # | Date | Supplier | VatGroup | LineTotal | TaxTotal |
> |-------|------|----------|----------|-----------|----------|
> | 605 | 15 Jul 2024 | Acme Associates | BL | SGD 800.00 | SGD 56.00 |
>
> Doc 605 (Acme Associates) has a line coded **BL** (blocked input tax under Regulations 26/27 — covering motor cars, entertainment, club fees, medical, etc.) but has a non-zero TaxTotal of SGD 56.00 recorded against it. BL lines must never carry claimable input tax; they are excluded from both Box 5 and Box 7. The recorded TaxTotal of 56.00 on this line is erroneous.
>
> **Recommendation:** Confirm what the purchase relates to. If it is genuinely a Reg 26/27 blocked expense, the SGD 56.00 must not be claimed in Box 7 — correct the line so TaxTotal is zero or reclassify if the expense category is wrong. This invoice also carries a NO_GST_REG flag (see Category 2 above), so the entire input tax claim on Doc 605 requires review.
>
> ---
>
> ### Summary Table
>
> | Error Code | Severity | Documents affected | Root cause |
> |---|---|---|---|
> | E1 | HIGH | 958, 964, 965, 974, 971, 967, 977, 982 | FX invoices coded SO instead of ZR |
> | NO_GST_REG | HIGH | 605, 592, 594, 595, 604, 600, 601 | Supplier GST reg number missing from master data |
> | E2 | MEDIUM | 605 | GST recorded on a BL (blocked) line |
>
> ---
>
> ### What to do next
>
> 1. **E1 invoices:** Review each FX sale with your operations team to confirm the supply qualifies as an export or international service. If confirmed, reclassify SO → ZR and ensure your FX conversion methodology is documented (IRAS-acceptable source, consistent application, updated at least quarterly).
>
> 2. **NO_GST_REG suppliers:** Run a verification pass against the IRAS GST register for all 7 suppliers. Update `FederalTaxID` in the SAP B1 Business Partner master record for any that are registered. For any confirmed non-registered suppliers, reclassify their purchase codes from SI → NR and reverse the associated Box 7 claims.
>
> 3. **Doc 605 (Acme Associates):** This document carries both a NO_GST_REG flag and an E2 flag — it needs dual remediation. Treat it as the highest-priority single document in this audit.
>
> 4. **Error correction threshold:** Before any amended return is considered, your tax adviser should assess whether the combined net GST impact of these corrections exceeds the SGD 3,000 / 5%-of-Box-4 concession thresholds (IRAS para 4.2.9). If either threshold is breached, a GST F7 would be required for the affected period. Given the scale of the E1 issues (multiple large FX invoices), the F7 threshold may well be exceeded — but that determination requires SGD-converted values and is outside this tool's scope.

## Tool usage confirmation

Verified by asking Claude in the same conversation: "Can you confirm which
tools you called to produce that answer? List each tool name and how many
times you called it."

| Tool | Calls |
|------|-------|
| `tool_search` | 2 (setup: load SAP B1 tool schemas) |
| `sap-b1-custom:sap_login` | 1 |
| `sap-b1-custom:detect_gst_errors` | 1 |
| `sap-b1-custom:validate_invoice_tax_codes` | 1 |
| `sap-b1-custom:sap_logout` | 1 |
| **Total** | **6 tool calls** |

**Confirms:**
- The three custom GST tools were exposed and Claude used them directly:
  `detect_gst_errors` and `validate_invoice_tax_codes` were the only
  analytical tools called. `calculate_f5_return` was not needed (this
  test focuses on error detection, not F5 calculation).
- No `sap_query` calls — Claude did not pull raw invoice data. The
  custom tools handle data retrieval internally.
- No `bash_tool` calls — Claude did not write in-conversation Python.
  The custom tools' deterministic logic replaced the need for ad-hoc
  analysis code.
- No `sap_get_document` spot-checks — Claude did not inspect individual
  documents. The custom tools provide population-level coverage.

**Methodological observation:** V3 used roughly half the tool calls of V1
(14) and V2 (15). This reflects the architectural payoff: purpose-built
tools eliminate the need for both raw data retrieval and ad-hoc
analytical code. Claude's role shifts from "retrieve, analyze, synthesize"
to "select tool, format output, add cross-finding synthesis."

**Cross-version tool usage comparison:**

| Tool category | V1 | V2 | V3 |
|---------------|-----|-----|-----|
| Data retrieval (sap_query, sap_get_document) | 11 | 6 | 0 |
| In-conversation analysis (bash_tool) | 0 | 6 | 0 |
| Custom GST tools | 0 | 0 | 2 |
| Session management (login/logout) | 1 | 2 | 2 |
| Setup (tool_search) | 2 | 1 | 2 |
| **Total** | **14** | **15** | **6** |

The reduction in tool calls at V3 is itself an architectural benefit:
lower latency, lower API costs, more deterministic execution, easier
regression testing.

## Findings overlap with reference set

**Perfect match against reference:**
- E1: 8 of 8 distinct DocNums enumerated, with 11 line-level instances
  correctly attributed (note: 967 has 2 lines, 974 has 3 lines, others
  single-line — total = 1+1+1+3+1+2+1+1 = 11, matching reference)
- E2: DocNum 605 caught with exact BL+TaxTotal=56
- NO_GST_REG: All 7 suppliers correctly enumerated at supplier level
  (DocNums 605, 592, 594, 595, 604, 600, 601 — exactly the reference)

**Cross-finding synthesis:**
- Claude explicitly identified Doc 605 as carrying BOTH NO_GST_REG and
  E2 flags, and prioritized it as the highest-priority single document.
  This is reasoning across tool results, not directly produced by the
  tools themselves.

**Fabrications avoided:**
- Rate artefact correctly framed in the opening disclaimer; no F7
  recommendation framed as needed. Item 4 of "What to do next"
  appropriately flags the F7 threshold as something the tax adviser
  must assess based on SGD-converted values, with explicit
  acknowledgement that this is outside the tool's scope.

## V0 → V1 → V2 → V3 comparison

| V0 failure mode | V0 | V1 | V2 | V3 |
|-----------------|-----|-----|-----|-----|
| Invented IRAS disclosure recommendation | YES | YES (F7) | NO | NO |
| Findings only at customer level | YES | PARTIAL | NO | NO |
| Missed 11 E1 DocNums | ALL | 3 of 8 | 0 | 0 |
| Missed E2 DocNum 605 | YES | YES | NO | NO |
| Missed all 7 NO_GST_REG | YES | YES | OVER-FLAGGED (17 instead of 7) | NO |
| Misunderstood ES33 semantics | YES | NO | NO | N/A (not surfaced) |

## Failure analysis

**Score breakdown:**

| Criterion | Max | Earned | Notes |
|-----------|----:|-------:|-------|
| E1 — pattern AND 6+ DocNums enumerated | 3 | 3 | All 8 distinct DocNums with full detail |
| E2 on DocNum 605 | 2 | 2 | Exact match |
| NO_GST_REG on 2+ suppliers | 2 | 2 | All 7 suppliers, supplier-level dedup |
| Line-level query | 1 | 1 | Tool returns line-level data |
| Structured output | 1 | 1 | Cleaner than V2 — categorized + summary table |
| Ambiguity / professional review flagged | 1 | 1 | Appropriate throughout |
| Penalty: confidently-wrong critical finding | −1 | 0 | None |
| **Total** | | **10/10** | |

**Key observations:**

1. The V2 → V3 delta is +1 point — smaller than V1 → V2 (+6), but
   structurally important. The single point V2 lost was on NO_GST_REG
   over-flagging (reporting all 17 invoices rather than 7 unique
   suppliers). V3 closes this precisely because detect_gst_errors dedupes
   by CardCode internally.

2. V3 dropped the V2 "extras" (ZP+TaxTotal=84 on DocNum 607, ES33 on
   DocNum 1001, FX purchases SI miscoding). These were defensible
   findings outside the reference set. Their absence at V3 reflects a
   precision-over-recall tradeoff: V3 reports only tool-confirmed
   findings. For a compliance tool this is the right tradeoff, but it
   means V3's scope is bounded by what the custom tools can detect.

3. V3 demonstrates the architectural payoff: deterministic detection
   (custom tools) + procedural enforcement (system prompt) +
   domain vocabulary (knowledge base) → tool-confirmed findings only,
   no fabrications, complete coverage of the reference set.

4. The "Doc 605 carries dual flags" synthesis is a useful demonstration
   of where the LLM still adds value: tools produce per-finding records,
   but cross-finding correlation (this one document has multiple issues,
   prioritize it) requires reasoning across the tool output.
