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
**Prompt:** "Look at the invoices in SAP B1. Classify each transaction by 
GST type: standard-rated, zero-rated, exempt, or out-of-scope."
**Score: 4/10**

### What Claude got right
- Successfully queried DocumentLines to find VatGroup field
- Correctly identified VatGroup as the tax classification field
- Correctly read SO = standard-rated, SI = input tax

### What Claude got wrong / couldn't do
- No knowledge of F5 box routing (SO→Box1, ZR→Box2 etc.)
- Cannot detect FX+SO mismatch (USD invoice coded SO instead of ZR)
- Would treat all demo data as Box 1 — correct by accident only

### New gaps identified
| # | Gap | Severity |
|---|-----|----------|
| G6 | FX+VatGroup mismatch detection (USD/EUR + SO = suspicious) | HIGH |
| G7 | Demo data homogeneous — all SO/SI, no ZR/OS/BL to test routing | MEDIUM |
| G8 | VatGroup at line level only — header queries insufficient | LOW |

### Key discovery
Invoice #958 (SG Electronics, USD 1,131.53) uses VatGroup=SO with 7% GST.
USD-billed sale to overseas customer should likely be ZR (zero-rated).
This is a real miscoding pattern the agent must detect.

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
## Automated Baseline Run v0

*Run date: 2026-05-25 00:06:07 UTC | Script: run_baseline_tests.py*

### Results Summary

| Test | Score | Notes |
|------|-------|-------|
| Test 1: F5 Calculation | 9/10 | Boxes 1-8 calculated from 14 SGD sales and 15 SGD purchase invoices. FX invoices |
| Test 2: Tax Classification | 10/10 | Found 5 unique VatGroup codes: 5 known, 0 unknown/unmapped. 9 FX+SO mismatch(es) |
| Test 3: Error Detection | 10/10 | All 4 error checks (E1-E4) executed. Found 88 error(s). Error types: ['E1']. Inv |
| **Overall** | **29/30** | |

### Test 1: F5 Box Values (SGD)

| Box | Value |
|-----|-------|
| Box 1 (Standard-rated supplies) | SGD 138,581.80 |
| Box 2 (Zero-rated supplies) | SGD 0.00 |
| Box 3 (Exempt supplies) | SGD 0.00 |
| Box 4 (Total supplies) | SGD 138,581.80 |
| Box 5 (Taxable purchases) | SGD 123,277.76 |
| Box 6 (Output tax) | SGD 0.00 |
| Box 7 (Input tax claimed) | SGD 0.00 |
| Box 8 (Net GST payable) | SGD 0.00 |

FX invoices flagged (excluded from boxes): 8

### Test 2: VatGroups Found

- `BL`: Blocked input tax (Reg 26/27) → Excluded
- `IM`: Import GST → Box 5 + Box 7
- `SI`: Standard-rated input → Box 5 + Box 7
- `SO`: Standard-rated output → Box 1 + Box 6
- `ZP`: Zero-rated purchase → Box 5 only

FX+SO mismatches detected: 9

### Test 3: Errors Found

Total errors detected: 88
- DocNum 356: E3: VatGroup=SO (standard-rated) but VatSum=0 on SGD 200.00 line
- DocNum 957: E3: VatGroup=SO (standard-rated) but VatSum=0 on SGD 293.75 line
- DocNum 958: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 958: E3: VatGroup=SO (standard-rated) but VatSum=0 on SGD 1057.50 line
- DocNum 959: E3: VatGroup=SO (standard-rated) but VatSum=0 on SGD 411.25 line
- DocNum 960: E3: VatGroup=SO (standard-rated) but VatSum=0 on SGD 3701.25 line
- DocNum 961: E3: VatGroup=SO (standard-rated) but VatSum=0 on SGD 44137.50 line
- DocNum 962: E3: VatGroup=SO (standard-rated) but VatSum=0 on SGD 1468.75 line
- DocNum 963: E3: VatGroup=SO (standard-rated) but VatSum=0 on SGD 24850.00 line
- DocNum 964: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR

---

## Automated Baseline Run v0

*Run date: 2026-05-25 00:12:40 UTC | Script: run_baseline_tests.py*

### Results Summary

| Test | Score | Notes |
|------|-------|-------|
| Test 1: F5 Calculation | 9/10 | Boxes 1-8 calculated from 39 SGD sales and 15 SGD purchase invoices. FX invoices |
| Test 2: Tax Classification | 10/10 | Found 8 unique VatGroup codes: 8 known, 0 unknown/unmapped. 11 FX+SO mismatch(es |
| Test 3: Error Detection | 10/10 | All 4 error checks (E1-E4) executed. Found 11 error(s). Error types: ['E1']. Inv |
| **Overall** | **29/30** | |

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

### Test 3: Errors Found

Total errors detected: 11
- DocNum 958: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 964: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 965: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 967: E1: Foreign currency (EUR) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 967: E1: Foreign currency (EUR) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 971: E1: Foreign currency (EUR) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 974: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 974: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 974: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 977: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR

---

## Automated Baseline Run v0

*Run date: 2026-05-25 00:13:33 UTC | Script: run_baseline_tests.py*

### Results Summary

| Test | Score | Notes |
|------|-------|-------|
| Test 1: F5 Calculation | 10/10 | Boxes 1-8 calculated from 39 SGD sales and 15 SGD purchase invoices. FX invoices |
| Test 2: Tax Classification | 10/10 | Found 8 unique VatGroup codes: 8 known, 0 unknown/unmapped. 11 FX+SO mismatch(es |
| Test 3: Error Detection | 10/10 | All 4 error checks (E1-E4) executed. Found 11 error(s). Error types: ['E1']. Inv |
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

### Test 3: Errors Found

Total errors detected: 11
- DocNum 958: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 964: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 965: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 967: E1: Foreign currency (EUR) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 967: E1: Foreign currency (EUR) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 971: E1: Foreign currency (EUR) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 974: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 974: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 974: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR
- DocNum 977: E1: Foreign currency (USD) invoice uses VatGroup=SO — overseas sale should be ZR

---
