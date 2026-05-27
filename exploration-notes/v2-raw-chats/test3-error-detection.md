# v2 Test 3: Error Detection — Raw Response

**Date run:** 2026-05-26
**Model:** Claude Sonnet 4.6
**Configuration:**
- Claude Desktop, sap-b1 MCP connector (11 read-only tools only — Tools 12-14
  temporarily disabled via commented @mcp.tool() decorators)
- Project knowledge: sg-tax-code-mappings.md LOADED
- System prompt: base.md LOADED (attached to project)
- Custom GST tools (calculate_f5_return, validate_invoice_tax_codes,
  detect_gst_errors): NOT exposed
**Score: 9/10**

**Reference set (from baseline-test-report-v0.json, generated 2026-05-26):**
- 11 E1 line-level findings across 8 DocNums: 958, 964, 965, 967 (×2),
  971, 974 (×3), 977, 982
- 1 E2: DocNum 605
- 7 NO_GST_REG suppliers: V1010 Far East Imports, V70000 SMD Technologies,
  V20000 Lasercom, V60000 CTI Computers, V30000 Blockies Corporation,
  V50000 Lumarx, V10000 Acme Associates
- 0 COMPLETENESS (ratio 17/47 = 0.36)
- 0 E3, 0 E4

## Note on V1/V2 reclassification

This run was originally labelled V1 but was conducted with base.md
inadvertently attached to the Claude Desktop project. The run is
correctly classified as V2 (knowledge base + system prompt, custom
tools disabled). The original V1 was re-run with base.md detached;
see v1-raw-chats/test3-error-detection.md.

The reclassification was discovered through the tool-usage
confirmation pattern (asking Claude to list its called tools) and
comparison of result quality against expected V1 capability.

---

## Prompt

> Using SAP Business One, examine the invoices for Q3 2024 (July to September 2024). Identify any errors, miscodings, or compliance issues in the GST treatment. Report each issue you find with the document number, the problem, and your recommendation.

## Response (verbatim)

[Insert the full V2 response — the run originally labelled V1, conducted
with both sg-tax-code-mappings.md and base.md attached. Starts with
"Connected to SBODEMOSG. Now I'll fetch Q3 2024 sales invoices..." through
to "...All findings are for testing purposes only."]

## Tool usage confirmation

Verified by asking Claude in the same conversation: "Can you confirm which
tools you called to produce that answer? List each tool name and how many
times you called it."

| Tool | Calls |
|------|-------|
| `tool_search` | 1 |
| `sap-b1-custom:sap_login` | 1 |
| `sap-b1-custom:sap_query` | 6 (3 pages sales + 3 attempted pages purchases) |
| `bash_tool` | 6 (JSON parsing + analysis script execution) |
| `sap-b1-custom:sap_logout` | 1 |
| **Total** | **15 tool calls** |

**Confirms:**
- None of the three custom GST tools were called — decorator disable was
  effective at V2.
- `bash_tool` was used 6 times for population-level analysis. Claude
  parsed the full JSON dataset and ran detection logic against every
  line, rather than spot-checking specific DocNums.

**Methodological observation:** V2's analytical approach differs
fundamentally from V1's. Where V1 used sap_get_document to inspect 7
specific DocNums and then reasoned narratively, V2 used bash_tool to
write Python that iterated over the full dataset and applied rule-based
detection systematically. This shift was driven by the system prompt's
mandatory pagination ("never compute totals from a single page") and
output format requirements, which made narrative spot-check methodology
unworkable.

## Initial findings overlap with reference set

**True positives confirmed by reference:**
- E1: 8 of 8 DocNums enumerated (958, 964, 965, 967, 971, 974, 977, 982).
  Reference set has 11 line-level findings across these 8 DocNums; Claude
  reported at DocNum level (8 entries) rather than line level (11 entries).
- E2: DocNum 605 (BL + TaxTotal=56) caught precisely.

**Findings requiring review:**
- NO_GST_REG: Claude reported "all 17 purchase invoices have FederalTaxID
  null," but the reference set flags 7 unique suppliers (not 17 invoices).
  Possible explanations: (a) Claude queried line-level where the field is
  uniformly blank rather than supplier-level where the check belongs;
  (b) over-flagging.
- ES33 on DocNum 1001: Not in the reference set. Defensible reasoning
  (ES33 is for Reg 33 international financial services, "advisory" may
  not qualify), but the script's automated check doesn't evaluate
  semantic appropriateness of VatGroup for item description.
- ZP+TaxTotal=84 on DocNum 607: Not in reference set. ZP is not in the
  current E2 set of either the script or the MCP tool (set is
  {ZR, OS, ES33, ESN33, BL}). Conceptually ZP should arguably be included
  since zero-rated purchases shouldn't carry GST. This may be a gap in
  both the script and the MCP tool worth investigating.
- FX purchases SI miscoding (DocNums 601, 604): Not in reference set as
  compliance findings. Reasonable observation but outside automated
  checks.

**False positive (V0 mode) NOT reproduced:**
- The V0 "critical 7%/9% IRAS disclosure" fabrication did NOT occur at V2.
  Claude explicitly noted: "The SBODEMOSG 7% tax rate present on all lines
  is a pre-2024 demo data artefact and is not flagged as a compliance issue."
  This confirms the system prompt's compliance-assertion rule is doing work
  the knowledge base alone cannot (see V1 result, which reproduces the
  fabrication despite having the knowledge base's rate-artefact note).

## V0 → V2 comparison

| V0 failure mode | V2 outcome |
|-----------------|------------|
| Invented "critical" 7%/9% IRAS disclosure recommendation | AVOIDED — explicitly flagged as demo artefact, not a compliance issue; system prompt compliance-assertion rule enforced |
| Findings only at customer level, not DocNum level | RESOLVED — DocNum-level enumeration throughout |
| Missed all 11 E1 DocNums by enumeration | RESOLVED — 8 of 8 distinct DocNums caught (11 lines collapsed to 8 DocNums in reporting) |
| Missed E2 DocNum 605 | RESOLVED — caught precisely |
| Missed all 7 NO_GST_REG | PARTIAL — issue type detected; supplier-level deduplication not applied |
| Misunderstood ES33 semantics | PARTIAL — ES33 finding on DocNum 1001 is more nuanced; reasoning is defensible |

## Hypothesis result

Hypothesis going in: "Does adding the system prompt to the knowledge base
close additional Test 3 failure modes?"

Answer: Yes, on the most critical dimension. The system prompt eliminates
the IRAS fabrication that the knowledge base alone cannot prevent (see V1
result). This is the clearest signal from the V1/V2 comparison: the
knowledge base's rate-artefact instruction is not sufficient on its own;
it requires the system prompt's compliance-assertion rule ("never assert
a compliance issue without tool-confirmed evidence") to be reliably
effective.

Remaining gaps (NO_GST_REG deduplication, line-level vs DocNum-level E1
reporting) are not addressed by either the knowledge base or the system
prompt — they require the custom tools introduced in V3.

## Failure analysis

**Score breakdown (against scoring rubric in baseline-test-results.md):**

| Criterion | Max | Earned | Notes |
|-----------|----:|-------:|-------|
| E1 — pattern AND 6+ DocNums enumerated | 3 | 3 | All 8 of 8 distinct E1 DocNums correctly enumerated |
| E2 on DocNum 605 | 2 | 2 | Caught precisely with BL+TaxTotal=56 |
| NO_GST_REG on 2+ suppliers | 2 | 1 | Issue type detected, but over-flagged (reported "all 17 invoices" rather than 7 unique suppliers) |
| Line-level query | 1 | 1 | Population-level DocumentLines analysis via bash |
| Structured DocNum + problem + recommendation | 1 | 1 | |
| Ambiguity / professional review flagged | 1 | 1 | |
| Penalty: confidently-wrong critical finding | −1 | 0 | No fabrication; explicitly flagged 7% as demo artefact |
| **Total** | | **9/10** | |

**Additional findings worth noting (not penalized):**

- ZP+TaxTotal=84 on DocNum 607: Not in reference set, but conceptually a
  real issue (zero-rated purchases should not carry tax). Both the script
  and the MCP tool's E2 set exclude ZP. Claude caught a gap in both
  reference implementations.
- ES33 on DocNum 1001: Defensible semantic reasoning (ES33 has narrow
  Reg 33 scope; "Financial Advisory Service" likely doesn't qualify).
- FX purchases SI miscoding (DocNums 601, 604): Reasonable observation
  outside automated checks.

None of these are fabrications. They are reasoning that goes beyond what
the automated checks can verify — exactly the kind of finding that adds
value over pure rule-based detection.

**Key observations:**

1. The V1 → V2 delta is +6 points (3/10 → 9/10), the largest single-
   layer improvement in the Test 3 experiment. This isolates the
   incremental contribution of the system prompt very precisely.

2. The system prompt eliminated the F7 fabrication that V1 reproduced.
   The compliance-assertion rule ("never assert a compliance issue
   without tool-confirmed evidence") combined with the rate-artefact
   exception in base.md did the work the knowledge base alone could not.

3. The system prompt changed Claude's analytical approach from spot-check
   (V1) to population-level analysis (V2). This is a more important
   architectural insight than initially appreciated: orchestration rules
   in system prompts can drive structural changes in how the LLM
   approaches a task, not just constrain the output format.

4. The single point lost is on NO_GST_REG over-flagging. This reflects
   that the system prompt directs Claude toward systematic analysis but
   doesn't fully specify the supplier-level deduplication that
   detect_gst_errors handles internally. This is exactly the kind of
   precision gap that V3's custom tools should close.
