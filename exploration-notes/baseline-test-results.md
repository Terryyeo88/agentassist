# SAP B1 AI Agent — Baseline Test Results
*No system prompts, skills, or knowledge base active. Pure connector only.*
*Date: May 2026 | DB: SBODEMOSG | B1 Version: 1000250 (FP2502)*

---

## Baseline Test 1: GST F5 Calculation
**Prompt:** "Using SAP Business One, calculate the GST F5 return figures for 
the most recent quarter available in the system. Give me the values for 
Boxes 1 through 8."

**Quarter tested:** Q3 2024 (Jul–Sep 2024)
**Score: 3/10**

### What Claude got right
- Correctly identified most recent quarter from invoice data
- Pulled sales invoices (Invoices entity) and purchase invoices (PurchaseInvoices entity)
- Correctly calculated Box 1 as DocTotal minus VatSum (excl. GST)
- Correctly identified VatSum as Box 6 (output tax)
- Correctly calculated Box 8 as Box 6 minus Box 7

### Raw numbers produced (SGD only)
| Box | Value | Notes |
|-----|-------|-------|
| Box 1 | SGD 380,962.30 | Standard-rated supplies excl. GST |
| Box 2 | — | Not attempted |
| Box 3 | — | Not attempted |
| Box 4 | — | Not attempted |
| Box 5 | SGD 137,044.28 | Taxable purchases excl. GST |
| Box 6 | SGD 26,663.01 | Output tax |
| Box 7 | SGD 9,590.44 | Input tax |
| Box 8 | SGD 17,072.57 | Net GST payable (estimate) |

### Critical gaps identified
| # | Gap | Severity | Root Cause |
|---|-----|----------|------------|
| G1 | Foreign currency invoices (USD, EUR) silently excluded | HIGH | No FX conversion logic, no exchange rate source |
| G2 | No tax code classification — cannot separate Box 1 vs Box 2 vs Box 3 | HIGH | Did not query DocumentLines for VatGroup |
| G3 | Boxes 2, 3, 9–14 not attempted | HIGH | No knowledge of F5 structure |
| G4 | No GST-inclusive vs exclusive validation | HIGH | No rule to check DocTotal integrity |
| G5 | Purchase invoice count not validated against sales | MEDIUM | No completeness check logic |

---

## Baseline Test 2: Tax Code Classification
*(To be completed)*

---

## Baseline Test 3: Error Detection
*(To be completed)*

---

## Improvement Tracking
| Version | What was added | Test 1 Score | Test 2 Score | Test 3 Score |
|---------|---------------|--------------|--------------|--------------|
| Baseline (v0) | Nothing | 3/10 | TBD | TBD |
| v1 | Knowledge base added | — | — | — |
| v2 | System prompt added | — | — | — |
| v3 | Full skill built | — | — | — |