# SAP B1 AI Agent — Baseline Test Results

*Manual tests: No system prompts, skills, or knowledge base active. Pure read-only MCP connector only.*
*Automated tests: Python reference implementation (known-correct), used for scoring manual runs.*
*Date: May 2026 | DB: SBODEMOSG | B1 Version: 1000250 (FP2502) | Quarter tested: Q3 2024 (Jul–Sep 2024)*

---

## Improvement Tracking

| Version | What was added | Test 1 | Test 2 | Test 3 | Overall |
|---------|---------------|--------|--------|--------|---------|
| v0 (baseline) | Read-only MCP connector only | 4/10 | 6/10 | 2/10 | 12/30 |
| v1 | + Knowledge base (sg-tax-code-mappings.md) | 5/10 | 5/10 | 3/10 | 13/30 |
| v2 | + System prompt (orchestration rules) | 7/10 | 9/10 | 9/10 | 25/30 |
| v3 | + 3 new MCP tools (F5 calc, validate, detect errors) | **10/10** | **10/10** | **10/10** | **30/30** |
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

## v1 Test 1: GST F5 Calculation

**Prompt:** *"Using SAP Business One, calculate the GST F5 return figures for the most recent quarter available in the system. Give me the values for Boxes 1 through 8."*

**v1 score: 5/10 (rubric) | MAPE: N/A (quarter mismatch)**

Raw chat: [`v1-raw-chats/test1-f5-calculation.md`](v1-raw-chats/test1-f5-calculation.md)
Model: Claude Sonnet 4.6, Claude Desktop with sap-b1 connector + Project knowledge base.

### Quarter mismatch

Response returned Q2 2024 (Apr–Jun) figures instead of Q3 2024 (Jul–Sep). Direct numerical comparison against reference figures is not valid. MAPE recorded as N/A. Root cause: no system prompt default-period rule — same as v0 gap G11.

### Numbers produced vs known-correct

| Box | Claude (v1) | Correct (Q3) | Status |
|-----|-------------|--------------|--------|
| Box 1 | 226,189.78 | 370,589.97 | ❌ Wrong quarter |
| Box 2 | 0.00 | 5,000.00 | ❌ Wrong quarter |
| Box 3 | 0.00 | 3,000.00 | ❌ Wrong quarter |
| Box 4 | 226,189.78 | 378,589.97 | ❌ Wrong quarter |
| Box 5 | 244,955.28 | 123,277.76 | ❌ Wrong quarter |
| Box 6 | 20,357.08 | 25,941.32 | ❌ Wrong quarter |
| Box 7 | 22,045.98 | 8,545.45 | ❌ Wrong quarter |
| Box 8 | −1,688.90 | 17,395.87 | ❌ Wrong quarter |

*Numbers cannot be evaluated for accuracy — quarter mismatch invalidates comparison.*

### What v1 got right vs v0

| Criterion | v0 | v1 | Change |
|-----------|----|----|--------|
| Queried correct quarter (Q3 2024) | ✅ | ❌ | Regressed — v0 correctly identified Q3, v1 chose Q2 |
| Pulled both sales and purchase invoices | ✅ | ✅ | Maintained |
| Used LineTotal (net) for Boxes 1/5, TaxTotal for Boxes 6/7 | ❌ | ✅ | **CLOSED** — cites IRAS para 5.7/6.5.1 explicitly |
| Acknowledged and adjusted 7%→9% rate artefact | ❌ | ✅ | **CLOSED** — correctly identified demo DB artefact, did not escalate as compliance issue |
| FX invoice handling | ❌ (silently included) | Partial | **PARTIALLY CLOSED** — acknowledged FX risk and exchange rate requirement; did not enumerate the 10 FX DocNums to exclude |
| Populated all 8 boxes with correct structure | Partial | Partial | Maintained — structure correct, values wrong due to quarter |

### Gaps closed by knowledge base (v1)

| Gap | Status | Notes |
|-----|--------|-------|
| G2 — No tax code classification at line level | **CLOSED** | Correctly used VatGroup-level classification |
| G4 — Uses VatSum=0 as proxy for tax type | **CLOSED** | Did not fall back to this proxy |
| G18 (from Test 3) — Treats demo artefacts as compliance issues | **CLOSED** | Rate artefact correctly framed as demo data issue, not compliance finding |

### Gaps still open

| Gap | Status | What fixes it |
|-----|--------|---------------|
| G11 — No default period rule (wrong quarter) | Open | System prompt (v2) — "default to most recent complete quarter" |
| G10 — Pagination cap (20-record wall) | Open | Still hit — 20 sales + 16 purchase invoices only; system prompt pagination rule or `calculate_f5_return` tool (v3) |
| G1 — FX invoices not enumerated/excluded | Partially open | Acknowledged risk but did not exclude from totals; `calculate_f5_return` tool (v3) |
| G3 — Manual arithmetic | Open | `calculate_f5_return` tool (v3) |

### v0 → v1 delta

**Score: 4/10 → 5/10 (+1).** Knowledge base closed 3 methodology gaps (LineTotal/TaxTotal method, rate artefact handling, tax code classification) but the wrong-quarter failure and pagination cap mean the numbers produced are still not evaluable against reference figures. The +1 point reflects correct methodology in the absence of correct data scope.

---
## v2 Test 1: GST F5 Calculation

**Prompt:** *"Using SAP Business One, calculate the GST F5 return figures for the most recent quarter available in the system. Give me the values for Boxes 1 through 8."*

**v2 score: 7/10 (rubric) | MAPE: N/A (quarter mismatch)**

Raw chat: [`v2-raw-chats/test1-f5-calculation.md`](v2-raw-chats/test1-f5-calculation.md)
Model: Claude Sonnet 4.6, Claude Desktop with sap-b1 connector + knowledge base + system prompt (base.md).

### Quarter mismatch

Response returned Q2 2024 (Apr–Jun) figures instead of Q3 2024 (Jul–Sep). Direct numerical
comparison against reference figures is not valid. MAPE recorded as N/A.

Root cause differs from v1: the system prompt default-period rule fired correctly ("most recent
complete quarter"), but the agent probed the DB, found data ending in August 2024, and declared
Q3 2024 incomplete — falling back to Q2. v1 chose Q2 silently without checking; v2 chose Q2
after explicit reasoning. The rule works; the DB probe logic needs refinement (Q3 Jul–Sep 2024
is complete in the dataset — the agent should trust the period boundary, not infer completeness
from the last invoice date seen on page 1).

Fix: add explicit rule to base.md — "Do not infer period completeness from the last invoice 
date visible in a single query. If data exists in the period window, treat the period as 
complete. Only fall back to a prior quarter if zero records are returned for the period."

### Numbers produced vs known-correct

| Box | Claude (v2) | Correct (Q3) | Status |
|-----|-------------|--------------|--------|
| Box 1 | 379,963.76 | 370,589.97 | ❌ Wrong quarter |
| Box 2 | 0.00 | 5,000.00 | ❌ Wrong quarter |
| Box 3 | 0.00 | 3,000.00 | ❌ Wrong quarter |
| Box 4 | 379,963.76 | 378,589.97 | ❌ Wrong quarter |
| Box 5 | 216,027.82 | 123,277.76 | ❌ Wrong quarter |
| Box 6 | 26,597.49 | 25,941.32 | ❌ Wrong quarter |
| Box 7 | 15,121.97 | 8,545.45 | ❌ Wrong quarter |
| Box 8 | 11,475.52 | 17,395.87 | ❌ Wrong quarter |

*Numbers cannot be evaluated for accuracy — quarter mismatch invalidates comparison.*

### What v2 got right vs v1

| Criterion | v0 | v1 | v2 | Change |
|-----------|----|----|-----|--------|
| Queried correct quarter (Q3 2024) | ✅ | ❌ | ❌ (diff cause) | Still wrong quarter, different failure mode |
| Paginated past 20-record cap | ❌ | ❌ | ✅ | **CLOSED** — 3 pages fetched, counts stated |
| FX invoices excluded and enumerated | ❌ | Partial | ✅ | **CLOSED** — all 15 listed with DocNum/date/counterparty |
| E1 flags on FX+SO invoices | ❌ | ❌ | ✅ | **CLOSED** — all 13 FX sales individually flagged |
| Used TaxTotal as recorded | ❌ | ✅ | ✅ | Maintained |
| 7% rate not escalated | ❌ | ✅ | ✅ | Maintained — explicitly called demo artefact |
| Correct output format (record counts → boxes → FX table → caveats) | ❌ | ❌ | ✅ | **CLOSED** — followed base.md output spec exactly |
| Credit notes queried | ❌ | ❌ | ❌ | Still open — flagged in caveats but not queried |

### Gaps closed by system prompt (v2)

| Gap | Status | Notes |
|-----|--------|-------|
| G10 — Pagination cap | **CLOSED** | Paginated 3 pages for sales, 1 for purchases, stated counts |
| G1 — FX invoices excluded | **CLOSED** | Full enumeration, DocNums listed, excluded from all boxes |
| G7 — FX+SO E1 flag (regressed in v1) | **CLOSED** | All 13 flagged individually, ZR recommendation given |
| G15 — No DocNum enumeration | **CLOSED** | Full table with DocNums, dates, counterparties |

### Gaps still open

| Gap | Status | What fixes it |
|-----|--------|---------------|
| G11 — Period completeness inference | **Partially open** | Add explicit rule to base.md: never infer completeness from last invoice date |
| G3 — Manual arithmetic | Open | `calculate_f5_return` tool (v3) |
| G19 (new) — Credit notes not queried | Open | Add to base.md and test1-prefix.md |

### v1 → v2 delta

**Score: 5/10 → 7/10 (+2).** System prompt closed pagination, FX enumeration, E1 flagging,
and output format in one step. Quarter mismatch persists but for a different, fixable reason.
The +2 reflects correct execution of four previously-failing procedural rules.

### One-line base.md fix required before v3

Add to the "Mandatory Period Filter" section:

> Do not infer period completeness from the last invoice date visible in a single query page.
> If any records exist within the requested date range, treat the period as complete and
> report from it. Only fall back to the prior complete quarter if the period query returns
> zero records.

## v3 Test 1: GST F5 Calculation

**Prompt:** *"Using SAP Business One, calculate the GST F5 return figures for the most recent quarter available in the system. Give me the values for Boxes 1 through 8."*

**v3 score: 10/10 | MAPE: 0.00%**

Raw chat: [`v3-raw-chats/test1-f5-calculation.md`](v3-raw-chats/test1-f5-calculation.md)
Model: Claude Sonnet 4.6, Claude Desktop with sap-b1 connector + knowledge base + system prompt (base.md) + 3 custom MCP tools.

### Quarter detection

Correctly identified Q3 2024 (Jul–Sep 2024) as the most recent quarter with data. The patched fallback rule worked as intended: the agent stepped back quarter by quarter (Q1 2026 → Q4 2025 → Q3 2024), stopping when records were found rather than inferring incompleteness from the last invoice date. The v2 false-fallback bug is confirmed closed.

### Numbers produced vs known-correct

| Box | Claude (v3) | Correct | Delta | Status |
|-----|-------------|---------|-------|--------|
| Box 1 | 370,589.97 | 370,589.97 | 0.00 | ✅ |
| Box 2 | 5,000.00 | 5,000.00 | 0.00 | ✅ |
| Box 3 | 3,000.00 | 3,000.00 | 0.00 | ✅ |
| Box 4 | 378,589.97 | 378,589.97 | 0.00 | ✅ |
| Box 5 | 123,277.76 | 123,277.76 | 0.00 | ✅ |
| Box 6 | 25,941.32 | 25,941.32 | 0.00 | ✅ |
| Box 7 | 8,545.45 | 8,545.45 | 0.00 | ✅ |
| Box 8 | 17,395.87 | 17,395.87 | 0.00 | ✅ |

**Net financial impact if filed:** SGD 0.00 variance from correct figures.

### What v3 got right vs v2

| Criterion | v0 | v1 | v2 | v3 | Change |
|-----------|----|----|----|----|--------|
| Correct quarter (Q3 2024) | ✅ | ❌ | ❌ | ✅ | **CLOSED** — patched fallback rule confirmed working |
| All 8 boxes numerically correct | ❌ | ❌ | ❌ | ✅ | **CLOSED** — calculate_f5_return removes Claude from arithmetic path |
| FX invoices excluded (10 docs) | ❌ | Partial | ✅ | ✅ | Maintained |
| FX count consistent (8 sales + 2 purchase = 10) | — | — | — | ✅ | Matches reference |
| E1 candidates flagged with DocNums | ❌ | ❌ | ✅ | ✅ | Maintained |
| 7% rate not escalated as compliance issue | ❌ | ✅ | ✅ | ✅ | Maintained |
| Correct output format | ❌ | ❌ | ✅ | ✅ | Maintained |

### Gaps closed by custom MCP tools (v3)

| Gap | Status | Notes |
|-----|--------|-------|
| G3 — Manual arithmetic | **CLOSED** | calculate_f5_return handles all arithmetic internally; 0.00% MAPE |
| G11 — Period completeness inference (patched) | **CLOSED** | Stepped back correctly; zero-record fallback rule confirmed working |
| G1 — FX invoices excluded | Maintained closed | Tool handles FX exclusion deterministically |

### Gaps still open

| Gap | Status | What fixes it |
|-----|--------|---------------|
| G5 — GST-inclusive vs exclusive validation | Open | validate_invoice_tax_codes tool (tested in Test 2) |
| G6 — Purchase vs sales ratio not validated | Open | detect_gst_errors tool (tested in Test 3) |
| G19 — Credit notes not queried | Open | v4 skill |

### v2 → v3 delta

**Score: 7/10 → 10/10 (+3). MAPE: N/A → 0.00%.** The calculate_f5_return tool eliminated all arithmetic and FX-exclusion errors in one step. The base.md period-completeness patch eliminated the wrong-quarter failure. Together these two changes moved Test 1 from "correct methodology, wrong quarter, wrong numbers" to a perfect result. This confirms the core hypothesis: removing Claude from the computation path produces deterministic, auditable F5 figures.

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

## v1 Test 2: Tax Code Classification

**Prompt:** *"Look at the invoices in SAP B1. Classify each transaction by GST type: standard-rated, zero-rated, exempt, or out-of-scope."*

**v1 score: 5/10 (rubric) | VatGroup recall: 2/8 (25%)**

Raw chat: [`v1-raw-chats/test2-tax-classification.md`](v1-raw-chats/test2-tax-classification.md)
Model: Claude Sonnet 4.6, Claude Desktop with sap-b1 connector + Project knowledge base.

### What v1 got right vs v0

| Criterion | v0 | v1 | Change |
|-----------|----|----|--------|
| Queried VatGroup at line level | 2/2 | 2/2 | Maintained |
| Found all/most of 8 VatGroups present | 0/2 | 0/2 | No change — still hit 20-record cap, found SO + SI only |
| Correctly mapped ≥5 of 8 VatGroups | 1/2 | 1/2 | Partial — named SO/SI correctly; listed wrong codes for others (EP, NR, ME, IGDS instead of ES33, ZR, BL, OS) |
| Detected FX+SO mismatch | 2/2 | 0/2 | **REGRESSED** — ADA Technologies, SG Electronics, Aquent Systems visible in output table with non-SGD invoices, all classified SO with no flag |
| Listed individual transactions | 0/1 | 1/1 | **CLOSED** — full transaction-level HTML table rendered with DocNum, date, customer, VAT group, amounts |
| Flagged ambiguity / suggested review | 1/1 | 1/1 | Rate artefact note correct and clean — no false positive this time |
| **Total** | **6/10** | **5/10** | **Net −1** |

### Key regression: FX+SO mismatch

v0 explicitly flagged USD/EUR invoices coded SO as potentially needing ZR reclassification — without any knowledge base. v1 has sg-tax-code-mappings.md in the knowledge base but produced a clean transaction table showing ADA Technologies, SG Electronics, and Aquent Systems (all known FX+SO miscoding candidates, DocNums 88–97) as "Standard-rated / Box 1+6" with no flag whatsoever.

The knowledge base improved enumeration quality and eliminated the rate false positive, but appears to have made the model more conservative about raising potential issues — trading a correct flag for silence.

### Additional finding: no period filter applied

The sales table contains invoices dating from 2015 through 2024, confirming the same G11 (no period filter) failure as v0. The model pulled from the full DB history rather than scoping to a relevant quarter.

### Gaps status after v1 Test 2

| Gap | v0 | v1 | Change |
|-----|----|----|--------|
| G10 — Pagination cap | Open | Open | No change |
| G11 — No period filter | Open | Open | No change |
| G12 — Sales-only query | Open | **CLOSED** | Queried both Invoices and PurchaseInvoices |
| G13 — Aggregates not enumerates | Open | **CLOSED** | Full transaction-level table rendered |
| G7 — FX+SO mismatch detection | Working | **REGRESSED** | Was heuristic in v0, dropped entirely in v1 |

### v0 → v1 delta

**Score: 6/10 → 5/10 (−1).** Knowledge base closed G12 and G13 but caused a regression on FX+SO detection. The system prompt (v2) will need an explicit rule: *"always check DocCurrency; flag any non-SGD invoice coded SO as a potential ZR miscoding."*

---
## v2 Test 2: Tax Code Classification

**Prompt:** *"Look at the invoices in SAP B1. Classify each transaction by GST type: standard-rated, zero-rated, exempt, or out-of-scope."*

**v2 score: 9/10 (rubric) | VatGroup recall: 8/8 (100%)**

Raw chat: [`v2-raw-chats/test2-tax-classification.md`](v2-raw-chats/test2-tax-classification.md)
Model: Claude Sonnet 4.6, Claude Desktop with sap-b1 connector + knowledge base + system prompt (base.md).

### What v2 got right vs v1

| Criterion | v0 | v1 | v2 | Change |
|-----------|----|----|-----|--------|
| Queried VatGroup at line level | 2/2 | 2/2 | 2/2 | Maintained |
| Found all/most of 8 VatGroups | 0/2 | 0/2 | 2/2 | **CLOSED** — all 8 found |
| Correctly mapped ≥5 of 8 VatGroups | 1/2 | 1/2 | 2/2 | **CLOSED** — all 8 correct |
| Detected FX+SO mismatch | 2/2 | 0/2 | 2/2 | **CLOSED** — 11 E1 lines with DocNums |
| Listed individual transactions | 0/1 | 1/1 | 1/1 | Maintained |
| Flagged ambiguity / suggested review | 1/1 | 1/1 | 1/1 | Maintained |
| **Total** | **6/10** | **5/10** | **9/10** | |

### Gaps closed by system prompt (v2)

| Gap | Status | Notes |
|-----|--------|-------|
| G10 — Pagination cap | **CLOSED** | 3 pages sales, 1 page purchases, counts stated |
| G11 — Period filter / wrong quarter | **CLOSED** | G11 fix worked — Q3 2024 correctly selected |
| G7 — FX+SO mismatch (regressed v1) | **CLOSED** | All 11 reference E1 lines flagged individually |

### Remaining issue

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| P1 | DocNum 982 flagged as E1 but not in reference set | LOW | August invoice outside seeded error set — possible false positive. Response correctly withheld reclassification. |

### Bonus finding

The SO VatGroup summary line total of **370,589.97** matches Box 1 reference exactly — the
agent produced the correct F5 Box 1 figure as a byproduct of classification without being
asked. Confirms the FX exclusion and VatGroup routing logic is now working correctly.

### v1 → v2 delta

**Score: 5/10 → 9/10 (+4).** Largest single-version improvement in the experiment so far.
System prompt closed all four open gaps simultaneously. The +4 reflects pagination, period
filter, FX enumeration, and VatGroup coverage all working correctly in one run.

---

## v3 Test 2: Tax Code Classification

**Prompt:** *"Log in to SAP Business One, then use the validate_invoice_tax_codes tool for Q3 2024 (2024-07-01 to 2024-09-30). Report every unique VatGroup found, its GST category, and which F5 box it maps to. List any transactions where the tax code appears incorrect or inconsistent, with DocNum and recommendation."*

**v3 score: 10/10 | VatGroup recall: 8/8 (100%)**

Raw chat: [`v3-raw-chats/test2-tax-classification.md`](v3-raw-chats/test2-tax-classification.md)
Model: Claude Sonnet 4.6, Claude Desktop with sap-b1 connector + knowledge base + system prompt (base.md) + 3 custom MCP tools (patched: validate_invoice_tax_codes now returns vatgroup_inventory).

### Note on tool patch

The first v3 Test 2 run scored 8/10 because validate_invoice_tax_codes originally only returned error-bearing lines — clean VatGroups were invisible. A patch was applied to add a vatgroup_inventory field built as a byproduct of the same loop. After restart the tool returned all 8 VatGroups directly. The patch did not change any error-detection logic.

### Numbers produced vs known-correct

| Criterion | v0 | v1 | v2 | v3 | Change |
|-----------|----|----|----|----|--------|
| Queried VatGroup at line level | 2/2 | 2/2 | 2/2 | 2/2 | Maintained |
| Found all 8 VatGroups | 0/2 | 0/2 | 2/2 | 2/2 | Maintained |
| Correctly mapped all 8 VatGroups | 1/2 | 1/2 | 2/2 | 2/2 | Maintained |
| Detected FX+SO mismatch (E1, all 11 docs) | 2/2 | 0/2 | 2/2 | 2/2 | Maintained |
| Detected E2 DocNum 605 | 0/2 | 0/2 | 0/2 | 2/2 | **Maintained from fixed v3** |
| Listed individual transactions | 0/1 | 1/1 | 1/1 | 1/1 | Maintained |
| Flagged ambiguity / suggested review | 1/1 | 1/1 | 1/1 | 1/1 | Maintained |
| False positives | 0 | 0 | −1 (DocNum 982) | 0 | **IMPROVED** — v2 false positive absent |
| **Total** | **6/10** | **5/10** | **9/10** | **10/10** | |

### Gaps closed by tool patch

| Gap | Status | Notes |
|-----|--------|-------|
| G20 — validate_invoice_tax_codes blind to clean VatGroups | **CLOSED** | vatgroup_inventory field added; all 8 codes returned directly from tool |

### v2 → v3 delta

**Score: 9/10 → 10/10 (+1).** Tool patch closed the VatGroup visibility gap and eliminated the DocNum 982 false positive present in v2. All 8 VatGroups now returned deterministically from the tool with correct category labels and F5 box mappings. E2 detection (DocNum 605) confirmed working for the second consecutive run.

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
- *Critical:* INV-1001 ES33 reasoning — Claude's stated rationale (ES33 requires overseas recipient) is wrong. ES33 covers Regulation 33 exempt supplies (specific financial services), not overseas supplies. The invoice may still be misclassified for for other reasons, but the reasoning given is incorrect.
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

---

## V1/V2 Test 3 Reclassification Note

An initial run on 2026-05-26, originally labelled V1 Test 3, was conducted
with both sg-tax-code-mappings.md and base.md attached to the Claude Desktop
project. This was discovered after the fact through the tool-usage
confirmation pattern.

The original run has been reclassified as V2 (knowledge base + system
prompt). A clean V1 run (knowledge base only, base.md detached) was
conducted on the same day. Both files are preserved at their corrected
paths:
- v1-raw-chats/test3-error-detection.md — clean V1 run
- v2-raw-chats/test3-error-detection.md — original "V1" run, reclassified

The reclassification is informative: comparing the two runs isolates the
incremental contribution of the system prompt over the knowledge base
alone. The V1 result reproduces the V0 IRAS-related fabrication (this time
as an F7 filing recommendation), confirming that the knowledge base's
"not a compliance issue" instruction is insufficient on its own. The V2
result eliminates this fabrication, confirming the compliance-assertion
rule in the system prompt does the work the knowledge base alone cannot.

### Methodological finding: system prompt changes analytical approach

A tool-usage comparison between V1 and V2 revealed a structural difference
in how Claude approached the task:

| Approach | V1 (no system prompt) | V2 (system prompt) |
|----------|----------------------|--------------------|
| Data retrieval | sap_query × 4 (paginated) | sap_query × 6 (paginated) |
| Detail inspection | sap_get_document × 7 (spot-check specific DocNums) | (none) |
| Analysis | Narrative reasoning over inspected documents | bash_tool × 6 (population-level Python analysis) |
| Coverage | 7 of 64 invoices inspected in detail | All 64 invoices analyzed |

The mandatory pagination rules and "never compute totals from a single
page" instructions in base.md effectively pushed Claude toward writing
in-conversation Python to handle the full population. Without those rules
(V1), Claude defaulted to inspecting a handful of suspicious-looking
DocNums by hand and reasoning narratively about them.

This is why V1 missed E2 DocNum 605 (it was not in Claude's spot-check
list) and missed NO_GST_REG entirely (no supplier FederalTaxID was queried).
The system prompt's contribution at V2 is not just about preventing
fabrication; it's also about driving a structural shift in analytical
methodology that makes comprehensive detection tractable.

This is a stronger experimental result than originally anticipated: it
demonstrates that each architectural layer addresses specific failure
modes, with no single layer sufficient on its own.

---

## Decisions

| Date | Decision | Rationale | Files changed |
|------|----------|-----------|---------------|
| 2026-05-26 | NO_GST_REG severity standardized to HIGH | Tool already assigns HIGH; substantive risk (invalid input tax claim, IRAS audit exposure) is high-severity by nature; system prompt table updated to match | system-prompts/base.md |
## Automated Baseline Run v0

*Run date: 2026-05-26 14:21:35 UTC | Script: run_baseline_tests.py*

### Results Summary

| Test | Score | Notes |
|------|-------|-------|
| Test 1: F5 Calculation | 10/10 | Boxes 1-8 calculated from 39 SGD sales and 15 SGD purchase invoices. FX invoices |
| Test 2: Tax Classification | 10/10 | Found 8 unique VatGroup codes: 8 known, 0 unknown/unmapped. 11 FX+SO mismatch(es |
| Test 3: Error Detection | 10/10 | Checks: E1, E2(sales+purchases,incl.BL), E3, E4, NO_GST_REG, COMPLETENESS. Findi |
| **Overall** | **30/30** | |

### Test 1: F5 Box Values (SGD)

| Box | Value |
|-----|-------|
| Box 1 (Standard-rated supplies) | SGD 370,589.97 |
| Box 2 (Zero-rated supplies) | SGD 5,000.00 |
| Box 3 (Exempt supplies) | SGD 3,000.00 |
| Box 4 (Total supplies) | SGD 378,589.97 |
| Box 5 (Taxable purchases) | SGD 123,277.76 |
| Box 6 (Output tax) | SGD 25,941.32 |
| Box 7 (Input tax claimed) | SGD 8,545.45 |
| Box 8 (Net GST payable) | SGD 17,395.87 |

FX invoices flagged (excluded from boxes): 10

### Test 2: VatGroups Found

- `BL`: Blocked input tax (Reg 26/27) → Excluded
- `ES33`: Exempt supply (Reg 33) → Box 3
- `IM`: Import GST → Box 5 + Box 7
- `OS`: Out of scope → Excluded
- `SI`: Standard-rated input → Box 5 + Box 7
- `SO`: Standard-rated output → Box 1 + Box 6
- `ZP`: Zero-rated purchase → Box 5 only
- `ZR`: Zero-rated supply → Box 2

FX+SO mismatches detected: 11

### Test 3: Findings

Total findings: 19 (HIGH: 18, MEDIUM: 1)
- [HIGH] NO_GST_REG DocNum 592: Input tax claimed from supplier V1010 (Far East Imports) without a GST registrat
- [HIGH] NO_GST_REG DocNum 594: Input tax claimed from supplier V70000 (SMD Technologies) without a GST registra
- [HIGH] NO_GST_REG DocNum 595: Input tax claimed from supplier V20000 (Lasercom) without a GST registration num
- [HIGH] NO_GST_REG DocNum 600: Input tax claimed from supplier V60000 (CTI Computers) without a GST registratio
- [HIGH] NO_GST_REG DocNum 601: Input tax claimed from supplier V30000 (Blockies Corporation) without a GST regi
- [HIGH] NO_GST_REG DocNum 604: Input tax claimed from supplier V50000 (Lumarx) without a GST registration numbe
- [HIGH] NO_GST_REG DocNum 605: Input tax claimed from supplier V10000 (Acme Associates) without a GST registrat
- [HIGH] E1 DocNum 958: FX invoice (USD) with VatGroup=SO — overseas sale should use ZR
- [HIGH] E1 DocNum 964: FX invoice (USD) with VatGroup=SO — overseas sale should use ZR
- [HIGH] E1 DocNum 965: FX invoice (USD) with VatGroup=SO — overseas sale should use ZR

---
