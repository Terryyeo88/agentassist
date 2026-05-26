# Singapore GST Tax Code → F5 Box Mapping
*Source: IRAS e-Tax Guide "How do I prepare my GST return?" (Eleventh Edition, published 30 Jan 2026) + SBODEMOSG VatGroups entity*
*Last verified against IRAS Eleventh Edition on 2026-05-25*
*Current GST rate: 9% (effective 1 Jan 2024)*
*Note: Demo DB SBODEMOSG has rates at 7% (pre-2024). This is a demo data artefact, NOT a compliance issue. Update before production use against live SME data.*

---

## SAP B1 VatGroup Codes in SBODEMOSG

### Output Tax Codes (Sales)
| Code | Name | F5 Box | Rate | Notes |
|------|------|--------|------|-------|
| SO | Sales Standard Rated | Box 1 + Box 6 | 9% | Main standard-rated sales. Box 1 = value excl. GST; Box 6 = GST charged |
| ZR | Sales Zero Rated | Box 2 | 0% | Exports of goods + international services under s21(3) GST Act |
| OS | Sales Out of Scope | Excluded | N/A | Third-country trading (overseas-to-overseas), not reported in any box |
| DS | Sales Deemed Supplier | Box 1 + Box 6 | 9% | Deemed supplies: gifts >$200 with input tax claimed, business assets to non-business use, etc. |
| ES33 | Sales Reg 33 Exempt | Box 3 | 0% | International financial services treated as exempt under Reg 33 of GST (General) Regulations |
| ESN33 | Sales Non-Reg 33 Exempt | Box 3 | 0% | Other exempt supplies: residential property sale/lease, IPM, financial services under 4th Schedule |

### Input Tax Codes (Purchases)
| Code | Name | F5 Box | Rate | Notes |
|------|------|--------|------|-------|
| SI | Purchase Standard Rated | Box 5 + Box 7 | 9% | Standard claimable input tax — valid tax invoice required |
| ZP | Purchase Zero Rated | Box 5 only | 0% | Zero-rated purchases (e.g. air tickets, international freight). Box 5 includes value; Box 7 excluded (no GST to claim) |
| EP | Purchase Exempt GST | Excluded | N/A | Per IRAS para 5.11(m): exempt purchases (residential property, financial services, IPM) excluded from Box 5 |
| OP | Purchase Out of Scope | Excluded | N/A | Out-of-scope purchases excluded from all boxes |
| IM | Purchase Imported Goods | Box 5 + Box 7 | 9% | Import GST claimable. Value per import permit. Box 9 also relevant if under MES/3PL/other approved schemes |
| IGDS | Import GST Deferment Scheme | Box 5 + Box 7 + Box 9 | 9% | IGDS approved participants only. Defers import GST. Additional Boxes 18-21 apply |
| ME | Purchase Major Exporter Scheme | Box 5 + Box 9 | 0% | MES participants only — GST suspended on imports. Value in Box 5 and Box 9 |
| NR | Purchase Non-GST Registered | **Excluded** | N/A | **Per IRAS para 5.11(o): purchases from non-GST registered traders are EXCLUDED from Box 5** |
| BL | Purchase Reg 26/27 Blocked | Excluded | 9% | Blocked under Reg 26/27 (entertainment, club fees, private cars, medical etc.). Per IRAS para 5.11(l): excluded from Box 5. Per IRAS para 5.13(n): excluded from Box 7. Input tax NEVER claimable. |
| TX-E33 | Purchase Reg 33 Exempt Input | Excluded | — | Input tax on exempt supply purchases — cannot claim |
| TX-N33 | Purchase Non-Reg 33 Exempt Input | Excluded | 0% | Input tax on other exempt purchases — cannot claim |
| TX-RE | Purchase Residual Input | Box 7 partial | varies | Residual input tax — partial claim only via partial exemption rules. Out of scope for POC. |

---

## F5 Box Calculation Rules

### Box 1 — Standard-Rated Supplies (value)
- Sum of LineTotal (excl. GST) for sales invoice lines where VatGroup = SO or DS
- EXCLUDE any GST component (Box 1 reports net values only)
- DEDUCT credit notes with same VatGroups
- IRAS reference: para 5.7 and inclusion list 5.7(a)–(k)

### Box 2 — Zero-Rated Supplies (value)
- Sum of LineTotal for sales invoice lines where VatGroup = ZR
- No GST component to exclude (rate = 0%)
- IRAS reference: para 5.8

### Box 3 — Exempt Supplies (value)
- Sum of LineTotal for sales invoice lines where VatGroup IN (ES33, ESN33)
- IRAS reference: para 5.9
- Note: For financial services exempt supplies, IRAS para 6.3.1 lists 9 specific transaction types with different valuation rules (interest, gross sale proceeds, net realised gains, etc.). Implementing these correctly requires per-transaction-type handling beyond simple LineTotal summation. Out of scope for POC.

### Box 4 — Total Supplies
- Auto-computed: Box 1 + Box 2 + Box 3
- IRAS reference: para 5.10

### Box 5 — Taxable Purchases (value)
- Sum of LineTotal (excl. GST) for purchase invoice lines where VatGroup IN (SI, ZP, IM, IGDS, ME)
- EXCLUDE: BL, NR, EP, OP, TX-E33, TX-N33 — these are not "taxable purchases" per IRAS
- IRAS reference: para 5.11
- **Critical**: Box 5 must be tracked separately from Box 7. Do NOT compute Box 5 by re-grossing Box 7 (IRAS para 6.5.1)

### Box 6 — Output Tax Due
- Sum of TaxTotal at line level for sales invoice lines where VatGroup IN (SO, DS)
- IRAS reference: para 5.12
- Production scope additions (not in POC): reverse charge GST, overseas vendor registration GST, low-value goods GST, bad debt recovery, eTRS reclaims

### Box 7 — Input Tax Claimed
- Sum of TaxTotal at line level for purchase invoice lines where VatGroup IN (SI, IM, IGDS)
- EXCLUDE: BL (blocked), ZP (zero-rated, no GST), EP, OP, ME (GST suspended), NR (no GST), TX-E33, TX-N33
- IRAS reference: para 5.13
- Requires valid tax invoice with supplier's GST registration number for each claim

### Box 8 — Net GST
- Auto-computed: Box 6 − Box 7
- Positive = payable to IRAS
- Negative = refund from IRAS
- **If absolute value < SGD 5: no payment / no refund / does not carry forward** (IRAS para 6.8.3)
- IRAS reference: para 5.14

---

## Out of Scope for POC (Boxes 9–17, 18–21)

The following boxes exist in the F5 form but are NOT covered by this mapping or the current Python reference / MCP tools. Implementation requires data not derivable from invoice records alone.

| Box | Purpose | Why out of scope |
|-----|---------|------------------|
| Box 9 | Value of goods imported under MES / 3PL / other approved schemes | Requires scheme participation flag on company |
| Box 10 | eTRS claim flag (IR/CRA only) | Specialised retail/refund agency scope |
| Box 11 | Bad debt + reverse charge refund claims | Requires bad debt tracking + reverse charge logic |
| Box 12 | Pre-registration claims (first F5 only) | One-time edge case |
| Box 13 | Revenue (gross sales from P&L) | Requires financial reporting integration outside GST data |
| Box 14 | Reverse charge on imported services | Partial exemption businesses only |
| Box 15 | Electronic marketplace operator OVR | Specialised digital economy scope |
| Box 16 | Redeliverer / marketplace low-value goods | Specialised digital economy scope |
| Box 17 | Low-value goods supplier | Specialised digital economy scope |
| Boxes 18–21 | IGDS scheme detail | IGDS-approved businesses only |

These are flagged for v2/v3 production scope expansion. The POC covers the 8 boxes that apply to a typical Singapore SME without specialised scheme participation.

---

## Foreign Currency Rule
- All F5 figures must be in SGD (IRAS para 4.1)
- Foreign currency invoices must be converted using a consistent exchange rate methodology
- Acceptable methods: invoice date rate, monthly average rate (must be consistent across the period)
- Source: IRAS "Foreign Currency Transactions" page on iras.gov.sg

## Materiality Threshold for Error Correction
Per IRAS para 4.2.9, errors in a submitted F5 can be corrected in the *next* F5 (rather than filing F7) only if BOTH:
- (a) Net GST amount in error ≤ SGD 3,000
- (b) Sum of non-GST amounts in error ≤ 5% of total supplies (Box 4) in the submitted return

If either threshold is exceeded, GST F7 (Disclosure of Errors) must be filed for the affected accounting period.

This threshold matters for error-severity classification in error detection logic: errors above the threshold are HIGH severity (require F7), errors below are LOW/MEDIUM severity (correctable in next return).

---

## Critical Validation Rules (Common IRAS Audit Triggers)

1. **Boxes 1, 2, 3, 5 must EXCLUDE GST** — values are net of tax (IRAS para 5.7, 6.5.1)
2. **Box 5 must be tracked separately from Box 7** — cannot be derived by re-grossing input tax (IRAS para 6.5.1)
3. **Input tax (Box 7) requires valid tax invoice** with supplier GST registration number (IRAS para 5.13)
4. **BL is NEVER claimable** regardless of amount — Reg 26/27 disallows medical, motor cars, club fees, family benefits, etc. (IRAS para 5.11(l), 5.13(n))
5. **NR purchases are excluded from Box 5** — purchases from non-GST registered traders are not "taxable purchases" (IRAS para 5.11(o))
6. **OS (out of scope) supplies are excluded from ALL boxes** (IRAS para 5.7(o))
7. **Foreign currency must be converted to SGD** with consistent methodology (IRAS para 4.1)
8. **Box 8 net values under SGD 5 are dropped** — no payment, no refund, no carry-forward (IRAS para 6.8.3)
9. **Box 13 (revenue) errors don't require F7** — just report correctly in subsequent returns (IRAS para 4.2.8)
10. **Errors must be corrected within 5 years** from end of relevant accounting period (IRAS para 4.2.14)