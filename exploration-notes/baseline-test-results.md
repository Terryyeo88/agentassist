# SAP B1 AI Agent — Baseline Test Results

*Manual tests: No system prompts, skills, or knowledge base active. Pure read-only MCP connector only.*
*Automated tests: Python reference implementation (known-correct), used for scoring manual runs.*
*Date: May 2026 | DB: SBODEMOSG | B1 Version: 1000250 (FP2502) | Quarter tested: Q3 2024 (Jul–Sep 2024)*

---

## Improvement Tracking

| Version | What was added | Test 1 | Test 2 | Test 3 | Overall |
|---------|---------------|--------|--------|--------|---------|
| v0 (baseline) | Read-only MCP connector only | 4/10 | 6/10 | 2/10 | 12/30 |
| v1 | + Knowledge base (sg-tax-code-mappings.md) | — | — | — | — |
| v2 | + System prompt (orchestration rules) | — | — | — | — |
| v3 | + 3 new MCP tools (F5 calc, validate, detect errors) | — | — | — | — |
| v4 | + Skill (full workflow) | — | — | — | — |
| *Reference* | *Python script `run_baseline_tests.py`* | *10/10* | *10/10* | *10/10* | *30/30* |

---

## Reference (Known-Correct) Numbers for Q3 2024

Source: `scripts/run_baseline_tests.py` automated run 2026-05-25 00:13:33 UTC.
All manual test scoring below is measured against these figures.

| Box | Value (SGD) |
|-----|-------------|
| Box 1 (Standard-rated supplies) | 370,589.97 |
| Box 2 (Zero-rated supplies) | 5,000.00 |
| Box 3 (Exempt supplies) | 3,000.00 |
| Box 4 (Total supplies) | 378,589.97 |
| Box 5 (Taxable purchases) | 123,277.76 |
| Box 6 (Output tax) | 25,941.32 |
| Box 7 (Input tax claimed) | 8,545.45 |
| Box 8 (Net GST payable) | 17,395.87 |

Known correct findings:
- 8 unique VatGroups in period: BL, ES33, IM, OS, SI, SO, ZP, ZR
- 10 FX invoices that must be excluded from box totals
- 11 E1 errors (FX+SO miscoding)

---

## Baseline Test 1: GST F5 Calculation

**Prompt:** *"Using SAP Business One, calculate the GST F5 return figures for the most recent quarter available in the system. Give me the values for Boxes 1 through 8."*

**Canonical v0 score: 4/10**

Raw chat: [`v0-raw-chats/test1-f5-calculation.md`](v0-raw-chats/test1-f5-calculation.md)
Model: Claude Sonnet 4.6, plain Claude Desktop with sap-b1 connector only.

### Numbers produced vs known-correct

| Box | Claude (v0) | Correct | Delta | Status |
|-----|-------------|---------|-------|--------|
| Box 1 | 442,293.08 | 370,589.97 | +71,703.11 | ❌ FX included |
| Box 2 | 10,000.00 | 5,000.00 | +5,000.00 | ❌ ES33 misclassified as ZR |
| Box 3 | 0.00 | 3,000.00 | −3,000.00 | ❌ Missed exempt category |
| Box 4 | 452,293.08 | 378,589.97 | +73,703.11 | ❌ |
| Box 5 | 144,663.27 | 123,277.76 | +21,385.51 | ❌ FX included |
| Box 6 | 31,002.55 | 25,941.32 | +5,061.23 | ❌ FX tax included |
| Box 7 | 10,126.44 | 8,545.45 | +1,580.99 | ❌ FX tax included |
| Box 8 | 20,876.11 | 17,395.87 | +3,480.24 | ❌ |

**Net financial impact if filed:** SGD 3,480 overpayment to IRAS in Q3 2024 alone.

### What Claude got right (partial credit)

- Attempted all 8 boxes (improvement on the very first manual run which only attempted 4)
- Correctly identified Q3 2024 as the most recent quarter
- Correctly understood the F5 structure conceptually (Box 4 = 1+2+3, Box 8 = 6−7)
- Pulled both Invoices and PurchaseInvoices entities
- Flagged multi-currency as a concern in the caveats
- Recommended accountant review before submission

### What Claude got wrong

| # | Error | Severity | Root cause |
|---|-------|----------|------------|
| 1 | All 8 box values numerically wrong | CRITICAL | Manual arithmetic on raw JSON, no validation |
| 2 | FX invoices silently included in all box totals | CRITICAL | Flagged FX as a concern but still summed them in |
| 3 | ES33 (exempt) invoice misclassified as zero-rated (Box 2) | HIGH | Used VatSum=0 as proxy for tax classification; never queried VatGroup |
| 4 | Box 3 returned as zero despite SGD 3,000 of exempt supplies | HIGH | Same root cause as #3 |
| 5 | No mention of BL, IM, ZP, OS VatGroup handling | HIGH | No knowledge of F5 box routing rules |

### Critical gaps (carried forward to v1+ targets)

| # | Gap | Severity | What fixes it |
|---|-----|----------|---------------|
| G1 | Foreign currency invoices included without conversion | CRITICAL | System prompt rule (v2) + `calculate_f5_return` tool (v3) |
| G2 | No tax code classification at line level | CRITICAL | Knowledge base (v1) — sg-tax-code-mappings.md |
| G3 | Manual arithmetic produces wrong numbers even with right method | CRITICAL | `calculate_f5_return` tool (v3) |
| G4 | Uses VatSum=0 as proxy for tax type | HIGH | Knowledge base (v1) |
| G5 | No GST-inclusive vs exclusive validation | MEDIUM | `validate_invoice_tax_codes` tool (v3) |
| G6 | Purchase vs sales ratio not validated | MEDIUM | `detect_gst_errors` tool (v3) |

### Earlier manual run (for evidence trail)

An earlier manual run scored 3/10 with the same prompt but stopped after Box 1 (not attempting Boxes 2/3/4). That run's Box 1 was SGD 380,962.30 — different from the canonical run because it queried different pagination batches and didn't attempt FX handling at all. Superseded by the canonical run above but retained here for completeness.

---

## Baseline Test 2: Tax Code Classification

**Prompt:** *"Look at the invoices in SAP B1. Classify each transaction by GST type: standard-rated, zero-rated, exempt, or out-of-scope."*

**Canonical v0 score: 6/10**

Raw chat: [`v0-raw-chats/test2-tax-classification.md`](v0-raw-chats/test2-tax-classification.md)
Model: Claude Sonnet 4.6, plain Claude Desktop with sap-b1 connector only.

### What Claude got right

- Queried VatGroups entity to retrieve full code-to-meaning mappings (good methodology)
- Queried DocumentLines for VatGroup field — the correct approach
- Correctly named ZR (zero-rated), ES33/ESN33 (exempt), OS (out of scope) by category
- Correctly noted the 7% rate is pre-2024 (pre-GST-hike)
- Detected the FX+SO mismatch pattern: explicitly flagged that USD/EUR-billed invoices coded SO may need reclassification to ZR if the customer is overseas
- Offered next steps (pull more invoices, check purchase invoices, flag FX for review)

### What Claude got wrong

| # | Error | Severity | Root cause |
|---|-------|----------|------------|
| 1 | Examined only 20 invoices out of ~64 in the dataset | CRITICAL | B1's hard 20-record pagination cap; Claude pulled one page and stopped |
| 2 | Reported only 1 VatGroup (SO) when 8 exist in the period | CRITICAL | Same as #1 — full population includes BL, ES33, IM, OS, SI, ZP, ZR which were not in the first 20 records |
| 3 | Did not examine purchase invoices at all | HIGH | Sales-only query; classification of "transactions" should include both sides |
| 4 | Pulled invoices spanning 2015–2024 instead of a meaningful period | MEDIUM | No period filter; took everything available |
| 5 | Aggregated by VatGroup instead of listing each transaction | LOW | The prompt said "each transaction" — Claude gave summary, not enumeration |

### Score breakdown

| Criterion | Points |
|-----------|--------|
| Queried VatGroup at line level | 2/2 |
| Found all/most of 8 VatGroups present | 0/2 (found 1 of 8) |
| Correctly mapped ≥5 of 8 VatGroups | 1/2 (partial — named 4 categories correctly but missed BL/IM/ZP/SI) |
| Detected FX+SO mismatch | 2/2 |
| Listed individual transactions | 0/1 |
| Flagged ambiguity / suggested review | 1/1 |
| **Total** | **6/10** |

### Gaps identified (added to catalogue)

| # | Gap | Severity | What fixes it |
|---|-----|----------|---------------|
| G10 | B1's 20-record pagination cap stops Claude at one page | CRITICAL | System prompt rule (v2) or `calculate_f5_return` tool (v3) |
| G11 | Doesn't default to a sensible period | MEDIUM | System prompt rule (v2) |
| G12 | Only examines sales side when asked about transactions | MEDIUM | Knowledge base (v1) |
| G13 | Aggregates when asked to enumerate | LOW | System prompt (v2) |

### Earlier manual run (preliminary, score 4/10)

What Claude got right:
- Successfully queried DocumentLines to find VatGroup field
- Correctly identified VatGroup as the tax classification field
- Correctly read SO = standard-rated, SI = input tax

What Claude got wrong / couldn't do:
- No knowledge of F5 box routing (SO→Box1, ZR→Box2 etc.)
- Cannot detect FX+SO mismatch (USD invoice coded SO instead of ZR)
- Would treat all demo data as Box 1 — correct by accident only

Key discovery from this run:
Invoice #958 (SG Electronics, USD 1,131.53) uses VatGroup=SO with 7% GST. USD-billed sale to overseas customer should likely be ZR (zero-rated). This is a real miscoding pattern the agent must detect.

Gaps identified:
| # | Gap | Severity |
|---|-----|----------|
| G7 | FX+VatGroup mismatch detection (USD/EUR + SO = suspicious) | HIGH |
| G8 | Demo data homogeneous — needed seeded ZR/OS/BL to test routing | MEDIUM (resolved by seeding) |
| G9 | VatGroup at line level only — header queries insufficient | LOW |

---

## Baseline Test 3: Error Detection

**Prompt:** *"Using SAP Business One, examine the invoices for Q3 2024 (July to September 2024). Identify any errors, miscodings, or compliance issues in the GST treatment. Report each issue you find with the document number, the problem, and your recommendation."*

**Canonical v0 score: 2/10**

Raw chat: [`v0-raw-chats/test3-error-detection.md`](v0-raw-chats/test3-error-detection.md)
Model: Claude Sonnet 4.6, plain Claude Desktop with sap-b1 connector only.

### Reference: known-correct issues in Q3 2024

The Python script (`scripts/run_baseline_tests.py`) detects 19 real issues:
- 11 × E1 — FX (USD/EUR) invoices coded SO instead of ZR (DocNums 958, 964, 965, 967×2, 971, 974×3, 977)
- 1 × E2 — DocNum 605 has VatGroup=BL but TaxTotal=SGD 56.00
- 7 × NO_GST_REG — Purchase invoices with input tax claimed from suppliers lacking FederalTaxID

### What Claude reported finding

Claude reported 7 issues across 4 severity tiers (3 critical, 3 warnings, 1 informational):

1. *(Critical)* "Systemic 7%-should-be-9% GST rate issue across all SO/SI invoices"
2. *(Critical)* INV-1001 River Inc — ES33 applied without clear overseas-recipient evidence
3. *(Critical)* INV-356 Maxi-Teq — Output GST on what may be a disbursement
4. *(Warning)* INV-1002 River Inc — OS code but Singapore shipping address
5. *(Warning)* ADA Technologies EUR invoices — currency/delivery inconsistency
6. *(Warning)* Aquent Systems — overseas registration needs verification
7. *(Info)* River Inc July 15 invoices — unusual audit trail

### Comparison against reference

**Hits (overlap with reference):**
- Findings 5 (ADA) and 6 (Aquent) detect the FX+SO miscoding pattern conceptually, but at customer level only — did not enumerate the 11 specific DocNums affected. Partial credit.

**Misses (real issues not detected):**
- All 11 × E1 docs not individually enumerated (DocNums 958, 964, 965, 967×2, 971, 974×3, 977)
- 0 of 1 × E2 found — DocNum 605 BL+TaxTotal=56 missed entirely
- 0 of 7 × NO_GST_REG found — supplier FederalTaxID never checked

**False positives (issues Claude reported that aren't real):**
- *Critical:* "7%-should-be-9%" — INCORRECT. This is a demo data artefact (SBODEMOSG was last updated pre-2024), explicitly documented in the project handoff. Claude framed this as the highest-priority compliance issue requiring voluntary disclosure to IRAS. If acted on by a real user, would cause material harm.
- *Critical:* INV-1001 ES33 reasoning — Claude's stated rationale (ES33 requires overseas recipient) is wrong. ES33 covers Regulation 33 exempt supplies (specific financial services), not overseas supplies. The invoice may still be misclassified for other reasons, but the reasoning given is incorrect.
- *Possible false positives:* INV-356 disbursement claim and INV-1002/Aquent/ADA findings are speculative — possibly real, possibly over-reading the data.

### Score breakdown

| Criterion | Points |
|-----------|--------|
| Detected FX+SO pattern AND enumerated ≥6 of 11 docs | 0/3 |
| Detected FX+SO pattern as general observation | 1/1 |
| Found BL+TaxTotal (E2) on DocNum 605 | 0/2 |
| Found NO_GST_REG on ≥2 of 7 purchase invoices | 0/2 |
| Queried at line level | 1/1 |
| Structured DocNum + problem + recommendation format | 0/1 |
| Flagged ambiguity / recommended review | 1/1 |
| Penalty: confidently-wrong "critical" 7%/9% finding | −1 |
| **Total** | **2/10** |

### Why the negative finding matters

The headline result of Test 3 is not just that plain Claude missed real issues — it actively *invented* a "critical" issue and recommended voluntary disclosure to IRAS based on a misreading of demo data versus production rates. This is materially more dangerous than missing real issues. A non-expert user receiving this report would have no way to know that the top-priority finding is fabricated.

This false-positive failure mode is the strongest single argument for the AgentAssist architecture: deterministic tools (v3) cannot invent compliance issues, and the system prompt (v2) can constrain Claude to only surface findings the tools confirm.

### Gaps identified (added to catalogue)

| # | Gap | Severity | What fixes it |
|---|-----|----------|---------------|
| G14 | Invents confident false positives (7%/9% rate claim) | CRITICAL | System prompt (v2) — "never claim a compliance issue without tool confirmation" + tools (v3) |
| G15 | Doesn't enumerate DocNums when reporting patterns | HIGH | System prompt (v2) requiring DocNum-level output |
| G16 | Doesn't check supplier records (FederalTaxID) when assessing input tax | HIGH | `detect_gst_errors` tool (v3) handles this internally |
| G17 | Confuses tax code semantics (ES33 ≠ overseas exemption) | HIGH | Knowledge base (v1) — sg-tax-code-mappings.md |
| G18 | Treats demo data artefacts as compliance issues | CRITICAL | System prompt (v2) — environment awareness |

---

## Methodology Notes

**Scoring rubric (applied to every manual test):**

- +1 for each correct numeric result (Tests 1) or correct classification (Test 2) or correctly identified error (Test 3)
- +1 for correctly identifying the relevant entity / field / period
- +1 for flagging genuine ambiguities (multi-currency, missing data)
- +1 for recommending professional review where appropriate
- Maximum 10/10 per test
- Cap of 5/10 if any headline figure is materially wrong (e.g. Box 8 off by >SGD 100)

**Why every v0 figure is wrong despite correct methodology:**

Plain Claude does manual arithmetic on 20-record JSON pages, summing dozens of floats inline. This is error-prone by design — the model has no way to spot-check its own sums. It also has no knowledge of F5 box routing, so it uses available signals (VatSum=0) as proxies for tax classification, which fails on exempt supplies. Both failure modes are direct targets for v1 (knowledge) and v3 (tools).

**Why this is a strong baseline result:**

A v0 score of 4/10 on Test 1 with all numbers wrong is *the value proposition* for the project. If plain Claude had scored 10/10, there would be no reason to build the system. The gap between 4/10 (v0) and the eventual v4 score is the measurable contribution of the AgentAssist architecture.
