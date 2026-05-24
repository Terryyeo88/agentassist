# Singapore GST Tax Code → F5 Box Mapping
*Source: IRAS iras.gov.sg + SBODEMOSG VatGroups entity*
*Current GST rate: 9% (effective 1 Jan 2024)*
*Note: Demo DB SBODEMOSG has rates at 7% (pre-2024). Update before production use.*

---

## SAP B1 VatGroup Codes in SBODEMOSG

### Output Tax Codes (Sales)
| Code | Name | F5 Box | Rate | Notes |
|------|------|--------|------|-------|
| SO | Sales Standard Rated Supplier SR | Box 1 + Box 6 | 9% | Main standard-rated sales |
| ZR | Sales Zero Rated | Box 2 | 0% | Exports, international services |
| OS | Sales Out of Scope | Excluded | 0% | Overseas-to-overseas, not reported |
| DS | Sales Deemed Supplier | Box 1 + Box 6 | 9% | Platform/marketplace operators |
| ES33 | Sales Regulation 33 Exempt | Box 3 | 0% | Exempt financial services |
| ESN33 | Sales Non-Regulation 33 Exempt | Box 3 | 0% | Other exempt supplies |

### Input Tax Codes (Purchases)
| Code | Name | F5 Box | Rate | Notes |
|------|------|--------|------|-------|
| SI | Purchase Taxable Supplies TX | Box 5 + Box 7 | 9% | Standard claimable input tax |
| ZP | Purchase Zero Rated | Box 5 only | 0% | Zero-rated purchases, no GST to claim |
| EP | Purchase Exempt GST | Excluded | 0% | Cannot claim input tax |
| OP | Purchase Out of Scope | Excluded | 0% | Cannot claim input tax |
| IM | Purchase Imported Goods | Box 5 + Box 7 | 9% | Import GST claimable |
| IGDS | Import GST Deferment Scheme | Box 5 + Box 7 | 9% | IGDS participants only |
| ME | Purchase Major Exporter | Box 5 only | 0% | MES scheme, no GST charged |
| NR | Purchase Non-GST Registered | Box 5 only | 0% | Supplier not GST-registered |
| BL | Purchase Business Regulation 26/27 | Excluded | 9% | Blocked — cannot claim |
| TX-E33 | Purchase Regulation 33 Exempt | Excluded | — | Cannot claim |
| TX-N33 | Purchase Non-Regulation 33 Exempt | Excluded | 0% | Cannot claim |
| TX-RE | Purchase Residual | Box 7 partial | 0% | Partial claim only |

---

## F5 Box Calculation Rules

### Box 1 — Standard-Rated Supplies
- Sum of (DocTotal - VatSum) for all sales invoices where VatGroup = SO or DS
- EXCLUDE GST component
- DEDUCT credit notes with same tax codes

### Box 2 — Zero-Rated Supplies  
- Sum of DocTotal for all sales invoices where VatGroup = ZR
- No GST component to exclude (rate = 0%)

### Box 3 — Exempt Supplies
- Sum of DocTotal for sales invoices where VatGroup = ES33 or ESN33

### Box 4 — Total Supplies
- Auto: Box 1 + Box 2 + Box 3

### Box 5 — Taxable Purchases
- Sum of (DocTotal - VatSum) for purchase invoices where VatGroup IN (SI, ZP, IM, IGDS, ME, NR)
- EXCLUDE blocked codes: BL, TX-E33, TX-N33, EP, OP

### Box 6 — Output Tax Due
- Sum of VatSum for all sales invoices where VatGroup = SO or DS

### Box 7 — Input Tax Claimed
- Sum of VatSum for purchase invoices where VatGroup IN (SI, IM, IGDS)
- EXCLUDE: BL, ZP, EP, OP, ME, NR (zero rate or blocked)

### Box 8 — Net GST
- Auto: Box 6 - Box 7
- Positive = payable to IRAS
- Negative = refund from IRAS

---

## Foreign Currency Rule
Per IRAS: All F5 figures must be in SGD.
Foreign currency invoices must be converted using a consistent exchange rate methodology.
Acceptable methods: invoice date rate, monthly average rate (must be consistent across period).
Source: IRAS Foreign Currency Transactions guidance.

---

## Critical Validation Rules (Common IRAS Audit Triggers)
1. Boxes 1–5 must EXCLUDE GST — enter net amount only
2. Input tax (Box 7) requires valid tax invoice with supplier GST reg number
3. BL (blocked input tax) is NEVER claimable regardless of amount
4. OS (out-of-scope) supplies are excluded from ALL boxes
5. Foreign currency must be converted to SGD before reporting