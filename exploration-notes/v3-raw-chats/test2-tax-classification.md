# v3 Test 2 Raw Chat — Tax Code Classification

**Date:** 2026-05-25
**Model:** Claude Sonnet 4.6
**Setup:** sap-b1 MCP connector + knowledge base + system prompt (base.md) + 3 custom MCP tools (validate_invoice_tax_codes patched to include vatgroup_inventory)
**Prompt:** "Log in to SAP Business One, then use the validate_invoice_tax_codes tool for Q3 2024 (2024-07-01 to 2024-09-30). Report every unique VatGroup found, its GST category, and which F5 box it maps to. List any transactions where the tax code appears incorrect or inconsistent, with DocNum and recommendation."

---

## Agent response (condensed)

Logged in to SBODEMOSG. Ran validate_invoice_tax_codes for Q3 2024 at expected_rate=0.07.

### Part 1 — VatGroup Inventory (8/8 found)

Sales:

| VatGroup | GST Category | Doc Count | LineTotal Box | TaxTotal Box |
|---|---|---|---|---|
| SO | Standard-rated output | 73 | Box 1 | Box 6 |
| ZR | Zero-rated supply | 1 | Box 2 | — |
| ES33 | Exempt — Reg 33 | 1 | Box 3 | — |
| OS | Out-of-scope | 1 | Excluded | Excluded |

Purchases:

| VatGroup | GST Category | Doc Count | LineTotal Box | TaxTotal Box |
|---|---|---|---|---|
| SI | Standard-rated input | 47 | Box 5 | Box 7 |
| IM | Import GST | 1 | Box 5 | Box 7 |
| ZP | Zero-rated purchase | 1 | Box 5 | — |
| BL | Blocked — Reg 26/27 | 1 | Excluded | Excluded |

### Part 2 — Issues (12 total: 11×E1, 1×E2)

E1 (11 lines, 8 docs):

| DocNum | Customer | Currency | Recommendation |
|---|---|---|---|
| 958 | SG Electronics | USD | Review — likely ZR |
| 964 | Aquent Systems | USD | Review — likely ZR |
| 965 | Aquent Systems | USD | Review — likely ZR |
| 967 | ADA Technologies | EUR | Review — likely ZR (line 1) |
| 967 | ADA Technologies | EUR | Review — likely ZR (line 2) |
| 971 | ADA Technologies | EUR | Review — likely ZR |
| 974 | SG Electronics | USD | Review — likely ZR (line 1) |
| 974 | SG Electronics | USD | Review — likely ZR (line 2) |
| 974 | SG Electronics | USD | Review — likely ZR (line 3) |
| 977 | Aquent Systems | USD | Review — likely ZR |
| 982 | ADA Technologies | EUR | Review — likely ZR |

E2 (1 line):

| DocNum | Supplier | VatGroup | TaxTotal | Error |
|---|---|---|---|---|
| 605 | Acme Associates | BL | 56.00 | GST on blocked line — must not appear in Box 7 |

### Caveats

Demo environment only. 7% rate is pre-2024 artefact, not flagged as error. E1 flags are candidates requiring accountant confirmation. No reclassification made.

---

## Scoring notes

| Criterion | Result |
|-----------|--------|
| All 8 VatGroups found via vatgroup_inventory | ✅ |
| All 8 correctly mapped to F5 boxes | ✅ |
| All 11 E1 DocNums correct incl. 967×2, 974×3 | ✅ |
| E2 DocNum 605 detected | ✅ |
| Individual transactions listed | ✅ |
| Ambiguity flagged | ✅ |
| 7% rate not escalated | ✅ |
| False positives | None |

**Final score: 10/10 | VatGroup recall: 8/8**
