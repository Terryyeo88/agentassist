# v1 Test 3: Error Detection — Raw Response

**Date run:** 2026-05-26 (re-run with corrected configuration)
**Model:** Claude Sonnet 4.6
**Configuration:**
- Claude Desktop, sap-b1 MCP connector (11 read-only tools only — Tools 12-14
  temporarily disabled via commented @mcp.tool() decorators)
- Project knowledge: sg-tax-code-mappings.md LOADED
- System prompt: NOT loaded (V2 adds it; verified detached for this run)
- Custom GST tools (calculate_f5_return, validate_invoice_tax_codes,
  detect_gst_errors): NOT exposed
**Score: 3/10**

**Reference set (from baseline-test-report-v0.json, generated 2026-05-26):**
- 11 E1 line-level findings across 8 DocNums: 958, 964, 965, 967 (×2),
  971, 974 (×3), 977, 982
- 1 E2: DocNum 605
- 7 NO_GST_REG suppliers: V1010 Far East Imports, V70000 SMD Technologies,
  V20000 Lasercom, V60000 CTI Computers, V30000 Blockies Corporation,
  V50000 Lumarx, V10000 Acme Associates
- 0 COMPLETENESS, 0 E3, 0 E4

## Methodological note

An initial V1 run on 2026-05-26 was contaminated by base.md being
attached to the Claude Desktop project. That run has been reclassified
as V2 (see ../v2-raw-chats/test3-error-detection.md). This is the
re-run with base.md confirmed detached.

The contamination was discovered through the tool-usage confirmation
pattern and through comparison against expected V1 capability. The
discovery itself is informative: it allowed isolation of the
knowledge-base-alone contribution versus the knowledge-base-plus-system-
prompt contribution.

---

## Prompt

> Using SAP Business One, examine the invoices for Q3 2024 (July to September 2024). Identify any errors, miscodings, or compliance issues in the GST treatment. Report each issue you find with the document number, the problem, and your recommendation.

## Response (verbatim)

Here's a summary of what the audit found across 47 sales invoices and 17 purchase invoices.

**Three high-severity issues:**

**Issue 1 — Wrong GST rate on 5 invoices (958, 964, 965, 974, 977):** The SO and SI VatGroups in SBODEMOSG still carry the pre-2024 rate of 7%. Every invoice in the DB is calculating GST at 7% instead of the correct 9% (in force since 1 Jan 2024). On the sales side, this means you've under-charged customers by approximately 2 percentage points across all standard-rated invoices. The USD-denominated invoices to SG Electronics and Aquent Systems were the clearest examples, all shipping to Singapore addresses so definitely domestic standard-rated supplies.

**Issue 2 — ZR (zero-rated) applied to a domestic delivery (Invoice 1000, SGD 5,000):** The line item is labelled "Export Sale - Hard Disk" and coded ZR, but the ship-to address is 10 Eunos Road 8, Singapore — a local address. Zero-rating requires actual export outside Singapore. SGD 450 in output tax was omitted. This needs either export documentation or reclassification to SO.

**Issue 3 — ES33 (Reg 33 international financial services) misused (Invoice 1001, SGD 3,000):** "Financial Advisory Service" billed to a Singapore entity cannot qualify as Reg 33 exempt international financial services. This code is reserved for exempt financial services with an overseas nexus. Without that, it's either standard-rated at 9% (SO) or exempt under the Fourth Schedule (ESN33) — but ES33 is almost certainly wrong.

**Three medium-severity issues:**

**Issue 4 — Undocumented exchange rate methodology:** All USD transactions use a flat 1.35 rate and all EUR transactions use 1.52 throughout the whole quarter. The EUR rate in particular appears stale vs Q3 2024 market rates (~1.44–1.47). IRAS requires a documented methodology using an approved source, updated at least quarterly.

**Issue 5 — Purchase input tax also at 7%:** All 17 purchase invoices use the stale 7% SI rate. This actually means you're *under-claiming* input tax (to IRAS's benefit), but it creates a Box 5/Box 7 mismatch with supplier tax invoices that would have charged 9% — a documentation risk in an audit.

**Issue 6 — OS (out-of-scope) coding needs verification (Invoice 1002, SGD 2,000):** Item described as "Overseas Goods - Out of Scope" but delivered to a Singapore address. Third-country trading is only legitimately OS if goods never touch Singapore. Documentation is needed.

**On the F7 question:** The combined errors likely push you over the non-GST error threshold (5% of total supplies), so filing a GST F7 for Q3 2024 is advisable rather than folding corrections into the next F5.

## Tool usage confirmation

Verified by asking Claude in the same conversation: "Can you confirm which
tools you called to produce that answer? List each tool name and how many
times you called it."

| Tool | Calls |
|------|-------|
| `tool_search` | 2 |
| `sap-b1-custom:sap_login` | 1 |
| `sap-b1-custom:sap_query` | 4 (sales invoices ×3 pages + purchase invoices ×1) |
| `sap-b1-custom:sap_get_document` | 7 (DocEntries 958, 964, 1001, 1002, 1003, 967, 604) |
| `visualize:read_me` | 1 |
| `visualize:show_widget` | 1 |
| **Total** | **16 tool calls** |

**Confirms:**
- None of the three custom GST tools (calculate_f5_return,
  validate_invoice_tax_codes, detect_gst_errors) were called — decorator
  disable was effective at V1.
- `bash_tool` was NOT called — Claude did not write any in-conversation
  Python to systematically analyze the dataset. Compare to V2, which
  used bash_tool ×6 for population-level analysis.

**Methodological observation:** Claude used a *spot-check* approach — pull
the full Q3 dataset via sap_query, then inspect 7 specific DocNums via
sap_get_document (chosen by Claude based on currency or zero-VatSum
heuristics). This is fundamentally different from V2's population-level
approach, where Claude pulled the same data and then applied programmatic
analysis across the full set via bash_tool. The spot-check methodology
mechanically cannot detect issues outside the inspected DocNums — which
is why E2 on DocNum 605 was missed (605 was not in Claude's spot-check
list) and NO_GST_REG was missed entirely (no purchase invoice supplier
record was queried at the FederalTaxID level).

## Initial findings overlap with reference set

**True positives confirmed by reference:**
- E1: 5 of 8 DocNums enumerated (958, 964, 965, 974, 977). Missed: 967, 971, 982.
- Note: these were framed by Claude as evidence of the (incorrect) 7%→9%
  rate issue, not as separate E1 candidates. The structural understanding
  of E1 as a miscoding category is not present in this response.

**False negatives (reference findings Claude missed):**
- E1: 3 DocNums missed (967, 971, 982)
- E2: DocNum 605 (BL + TaxTotal=56) completely missed
- NO_GST_REG: All 7 suppliers missed — supplier FederalTaxID never checked

**Critical false positive (V0 mode REPRODUCED):**
- Issue 1: Claude framed the SBODEMOSG 7% rate as a real compliance issue,
  recommending the user "filed a GST F7 for Q3 2024 is advisable rather
  than folding corrections into the next F5."
- The knowledge base explicitly states: "The 7% rate in SBODEMOSG is not
  a compliance issue. Do not flag it as an error in any error-detection
  output."
- This rule was either not consulted, or its instruction was insufficient
  to override Claude's default reasoning about rate gaps.
- A user acting on this advice would file an erroneous F7 return with IRAS.

**Additional findings not in reference (possibly legitimate, possibly
over-reading):**
- Issue 2: DocNum 1000 (ZR with Singapore ship-to address). Reasonable
  question but speculative without verifying actual export documentation.
- Issue 4: Exchange rate methodology (1.35 USD, 1.52 EUR throughout the
  quarter). Reasonable observation but speculative.
- Issue 5: Purchase invoices at 7% SI rate. Same fabrication as Issue 1.
- Issue 6: DocNum 1002 (OS with Singapore ship-to address). Same
  speculative pattern as Issue 2.

## V0 → V1 comparison

| V0 failure mode | V1 outcome |
|-----------------|------------|
| Invented "critical" 7%/9% IRAS disclosure recommendation | REPRODUCED — framed as needing F7 filing rather than voluntary disclosure, but the underlying fabrication is the same |
| Findings only at customer level, not DocNum level | PARTIAL IMPROVEMENT — 5 of 8 E1 DocNums enumerated, but as evidence of the wrong issue |
| Missed all 11 E1 DocNums by enumeration | PARTIAL — 5 of 8 distinct DocNums enumerated; 3 missed |
| Missed E2 DocNum 605 | REPRODUCED |
| Missed all 7 NO_GST_REG | REPRODUCED |
| Misunderstood ES33 semantics | PARTIAL IMPROVEMENT — Issue 3 correctly identifies ES33 as Reg 33 financial services, not overseas exemption |

## Hypothesis result

Hypothesis going in: "Does GST domain knowledge alone — without
orchestration enforcement or custom tools — improve error detection?"

Answer: Marginally. The knowledge base alone provides correct VatGroup
vocabulary (e.g., the ES33 semantic correction) but does NOT prevent the
most dangerous V0 failure mode (the IRAS-related fabrication).

The knowledge base's "7% rate is not a compliance issue" instruction was
not strong enough on its own to prevent Claude from framing the rate as
a real issue. This instruction needs the supporting compliance-assertion
rule from the system prompt ("never assert a compliance issue without
tool-confirmed evidence") to be reliably effective.

This is a meaningful experimental result: it shows that domain knowledge
without procedural enforcement is insufficient for compliance-critical
applications. The system prompt is doing real work, not just decorative
orchestration.

## Failure analysis

**Score breakdown (against scoring rubric in baseline-test-results.md):**

| Criterion | Max | Earned | Notes |
|-----------|----:|-------:|-------|
| E1 — pattern AND 6+ DocNums enumerated | 3 | 0 | Only 5 of 8 DocNums enumerated, framed as evidence of the (incorrect) rate issue rather than as E1 candidates |
| E1 — pattern as general observation only | 1 | 1 | The FX+SO pattern was at least surfaced |
| E2 on DocNum 605 | 2 | 0 | Not mentioned — DocNum 605 was not in Claude's spot-check list |
| NO_GST_REG on 2+ suppliers | 2 | 0 | Supplier FederalTaxID never checked |
| Line-level query | 1 | 1 | sap_get_document calls returned DocumentLines |
| Structured DocNum + problem + recommendation | 1 | 1 | Response format is structured |
| Ambiguity / professional review flagged | 1 | 1 | "Documentation is needed" / "needs verification" appear repeatedly |
| Penalty: confidently-wrong critical finding | −1 | −1 | F7 filing recommendation based on demo-data artefact |
| **Total** | | **3/10** | |

**Key observations:**

1. The F7 filing recommendation is the V0 IRAS-disclosure fabrication
   reproduced. The knowledge base's "7% rate is not a compliance issue"
   declarative instruction was not sufficient to prevent it. This validates
   the architectural hypothesis: declarative warnings in knowledge bases
   are weaker than procedural rules in system prompts.

2. The spot-check methodology is a direct consequence of the missing
   system prompt. V2's base.md contains mandatory pagination rules and
   "never compute totals from a single page" instructions that
   effectively push Claude toward systematic population-level analysis
   (visible in V2's bash_tool usage). Without these rules, Claude
   defaulted to narrative spot-check reasoning, which is intractable
   over a 47+17 invoice population.

3. The Issue 3 ES33 reasoning is genuinely improved over V0: Claude
   correctly identified ES33 as a Reg 33 financial services code, not
   an overseas-exemption code. This is the knowledge base earning its
   keep on vocabulary, even where it failed on procedural gating.

4. The V0 → V1 net improvement is +1 point, almost entirely from the
   ES33 semantic correction. The F7 fabrication and missed E2/NO_GST_REG
   findings represent the floor that knowledge-base-only architecture
   cannot rise above.
