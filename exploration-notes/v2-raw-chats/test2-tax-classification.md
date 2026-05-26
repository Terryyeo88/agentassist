# v2 Test 2: Tax Code Classification — Raw Response

**Date run:** 2026-05-25
**Model:** Claude Sonnet 4.6
**Configuration:** Claude Desktop, sap-b1 MCP connector + knowledge base + system prompt (base.md)
**Score:** 9/10 (rubric) | VatGroup recall: 8/8 (100%)

## Prompt

> Look at the invoices in SAP B1. Classify each transaction by GST type: standard-rated, zero-rated, exempt, or out-of-scope.

## Response (verbatim)

I'll work through this systematically. Let me start by setting the period, then fetch and classify all transactions.

---

**Step 1 — Period**

Today is 2026-05-25. The most recent complete calendar quarter is **Q1 2026: 2026-01-01 to 2026-03-31**.

All queries will filter on `DocDate ge '2026-01-01' and DocDate le '2026-03-31'`.

---

**Step 2 — Fetch invoices. Paginating both sides.**

Let me log in and start pulling data.Connected to SBODEMOSG. Now loading the query tool and fetching sales invoices.Now fetching sales invoices — Page 1 (skip=0):Zero sales invoices for Q1 2026. Per the period rule, I'll fall back to the prior complete quarter — **Q4 2025: 2025-10-01 to 2025-12-31**.Q4 2025 is also empty. Let me check further back to find where data actually exists.The most recent sales invoice date is **2024-08-27**. The most recent complete quarter containing data is therefore **Q2 2024: 2024-04-01 to 2024-06-30**. But the latest data is in August, which falls in **Q3 2024: 2024-07-01 to 2024-09-30**. That is a complete quarter (it ended 2024-09-30, which is before today). I'll use **Q3 2024** as the period.

**Revised period: Q3 2024 — 2024-07-01 to 2024-09-30**

Now fetching all sales invoices for Q3 2024 with pagination:Page 1 returned exactly 20 records. Fetching page 2:Page 2 also returned exactly 20 records. Fetching page 3:Page 3 returned 8 records (< 20) — sales invoices are complete. Now fetching purchase invoices. Page 1 (skip=0):Page 1 returned 17 records (< 20) — purchase invoices are complete. All data is now fetched. Let me compile and analyse everything.All data is in. Here is the complete classification report.

---

# GST Transaction Classification — Q3 2024
**Period:** 2024-07-01 to 2024-09-30
*(Q1 and Q4 2025/Q1 2026 returned zero records; Q3 2024 is the most recent complete quarter with data)*

**Record counts fetched:**
- Sales invoices: **48 invoices, 75 lines** across 3 pages
- Purchase invoices: **17 invoices, 51 lines** on 1 page
- FX invoices excluded from box calculations: 8 sales, 2 purchases

---

## Step 3 — Individual Line Enumeration

### Sales Invoices

| DocNum | DocDate | Customer | CCY | Ln | VatGroup | LineTotal | TaxTotal | GST Category |
|-------:|---------|----------|-----|---:|----------|----------:|---------:|--------------|
| 356 | 2024-08-05 | Maxi-Teq | SGD | 0 | SO | 200.00 | 14.00 | Standard-rated |
| 957 | 2024-07-25 | Earthshaker Corporation | SGD | 0 | SO | 293.75 | 20.56 | Standard-rated |
| **958** | 2024-07-02 | SG Electronics | **USD** | 0 | SO | 1,057.50 | 74.03 | Standard-rated ⚠ FX/E1 |
| 959 | 2024-07-23 | Web Customer | SGD | 0 | SO | 411.25 | 28.79 | Standard-rated |
| 960 | 2024-07-19 | One Time Customer | SGD | 0 | SO | 3,701.25 | 259.09 | Standard-rated |
| 961 | 2024-07-02 | Microchips | SGD | 0 | SO | 44,137.50 | 3,089.63 | Standard-rated |
| 962 | 2024-07-05 | Earthshaker Corporation | SGD | 0 | SO | 1,468.75 | 102.81 | Standard-rated |
| 963 | 2024-07-27 | Earthshaker Corporation | SGD | 0 | SO | 24,850.00 | 1,739.50 | Standard-rated |
| **964** | 2024-07-09 | Aquent Systems | **USD** | 0 | SO | 5,250.00 | 367.50 | Standard-rated ⚠ FX/E1 |
| **965** | 2024-07-09 | Aquent Systems | **USD** | 0 | SO | 367.50 | 25.73 | Standard-rated ⚠ FX/E1 |
| 966 | 2024-07-15 | Parameter Technology | SGD | 0 | SO | 7.50 | 0.53 | Standard-rated |
| **967** | 2024-07-28 | ADA Technologies | **EUR** | 0 | SO | 3,550.00 | 248.50 | Standard-rated ⚠ FX/E1 |
| **967** | 2024-07-28 | ADA Technologies | **EUR** | 1 | SO | 300.00 | 21.00 | Standard-rated ⚠ FX/E1 |
| 968 | 2024-07-12 | Maxi-Teq | SGD | 0 | SO | 352.50 | 24.68 | Standard-rated |
| 969 | 2024-07-06 | Star Company | SGD | 0 | SO | 675.00 | 47.25 | Standard-rated |
| 969 | 2024-07-06 | Star Company | SGD | 1 | SO | 90.00 | 6.30 | Standard-rated |
| 969 | 2024-07-06 | Star Company | SGD | 2 | SO | 1,063.44 | 74.44 | Standard-rated |
| 970 | 2024-07-11 | Maxi-Teq | SGD | 0 | SO | 99.71 | 6.98 | Standard-rated |
| 970 | 2024-07-11 | Maxi-Teq | SGD | 1 | SO | 18,610.20 | 1,302.71 | Standard-rated |
| 970 | 2024-07-11 | Maxi-Teq | SGD | 2 | SO | 5,287.50 | 370.13 | Standard-rated |
| **971** | 2024-07-24 | ADA Technologies | **EUR** | 0 | SO | 66.45 | 4.65 | Standard-rated ⚠ FX/E1 |
| 972 | 2024-07-07 | River Inc | SGD | 0 | SO | 52.50 | 3.68 | Standard-rated |
| 972 | 2024-07-07 | River Inc | SGD | 1 | SO | 31,200.00 | 2,184.00 | Standard-rated |
| 973 | 2024-07-02 | Mashina Corporation | SGD | 0 | SO | 421.95 | 29.54 | Standard-rated |
| 973 | 2024-07-02 | Mashina Corporation | SGD | 1 | SO | 221.50 | 15.51 | Standard-rated |
| 973 | 2024-07-02 | Mashina Corporation | SGD | 2 | SO | 300.00 | 20.99 | Standard-rated |
| 973 | 2024-07-02 | Mashina Corporation | SGD | 3 | SO | 187.50 | 13.13 | Standard-rated |
| **974** | 2024-07-11 | SG Electronics | **USD** | 0 | SO | 540.00 | 37.80 | Standard-rated ⚠ FX/E1 |
| **974** | 2024-07-11 | SG Electronics | **USD** | 1 | SO | 236.25 | 16.54 | Standard-rated ⚠ FX/E1 |
| **974** | 2024-07-11 | SG Electronics | **USD** | 2 | SO | 35,310.00 | 2,471.70 | Standard-rated ⚠ FX/E1 |
| 975 | 2024-07-14 | Parameter Technology | SGD | 0 | SO | 1,800.00 | 126.00 | Standard-rated |
| 975 | 2024-07-14 | Parameter Technology | SGD | 1 | SO | 3,150.00 | 220.50 | Standard-rated |
| 976 | 2024-07-27 | One Time Customer | SGD | 0 | SO | 2,688.14 | 188.17 | Standard-rated |
| **977** | 2024-07-29 | Aquent Systems | **USD** | 0 | SO | 775.40 | 54.28 | Standard-rated ⚠ FX/E1 |
| 978 | 2024-07-17 | Parameter Technology | SGD | 0 | SO | 180.00 | 12.60 | Standard-rated |
| 979 | 2024-07-16 | Earthshaker Corporation | SGD | 0 | SO | 166.17 | 11.63 | Standard-rated |
| 979 | 2024-07-16 | Earthshaker Corporation | SGD | 1 | SO | 196.89 | 13.78 | Standard-rated |
| 980 | 2024-07-05 | One Time Customer | SGD | 0 | SO | 2,056.25 | 143.94 | Standard-rated |
| 981 | 2024-08-18 | One Time Customer | SGD | 0 | SO | 4,900.00 | 343.00 | Standard-rated |
| **982** | 2024-08-03 | ADA Technologies | **EUR** | 0 | SO | 24,850.00 | 1,739.50 | Standard-rated ⚠ FX/E1 |
| 983 | 2024-08-16 | Parameter Technology | SGD | 0 | SO | 60.00 | 4.20 | Standard-rated |
| 984 | 2024-08-12 | Maxi-Teq | SGD | 0 | SO | 6,510.00 | 455.70 | Standard-rated |
| 985 | 2024-08-05 | Star Company | SGD | 0 | SO | 16,275.00 | 1,139.25 | Standard-rated |
| 986 | 2024-08-12 | River Inc | SGD | 0 | SO | 22.50 | 1.58 | Standard-rated |
| 987 | 2024-08-06 | Mashina Corporation | SGD | 0 | SO | 75.00 | 5.25 | Standard-rated |
| 988 | 2024-08-10 | Parameter Technology | SGD | 0 | SO | 15,750.00 | 1,102.50 | Standard-rated |
| 989 | 2024-08-14 | Earthshaker Corporation | SGD | 0 | SO | 175.00 | 12.25 | Standard-rated |
| 990 | 2024-08-27 | Parameter Technology | SGD | 0 | SO | 67.50 | 4.73 | Standard-rated |
| 990 | 2024-08-27 | Parameter Technology | SGD | 1 | SO | 2,700.00 | 189.00 | Standard-rated |
| 991 | 2024-08-22 | Parameter Technology | SGD | 0 | SO | 1,260.00 | 88.20 | Standard-rated |
| 991 | 2024-08-22 | Parameter Technology | SGD | 1 | SO | 3,150.00 | 220.50 | Standard-rated |
| 991 | 2024-08-22 | Parameter Technology | SGD | 2 | SO | 60.00 | 4.20 | Standard-rated |
| 992 | 2024-08-07 | Earthshaker Corporation | SGD | 0 | SO | 147.72 | 10.34 | Standard-rated |
| 992 | 2024-08-07 | Earthshaker Corporation | SGD | 1 | SO | 150.00 | 10.50 | Standard-rated |
| 993 | 2024-08-10 | River Inc | SGD | 0 | SO | 434.28 | 30.40 | Standard-rated |
| 993 | 2024-08-10 | River Inc | SGD | 1 | SO | 150.00 | 10.50 | Standard-rated |
| 993 | 2024-08-10 | River Inc | SGD | 2 | SO | 4,260.00 | 298.20 | Standard-rated |
| 994 | 2024-08-14 | Maxi-Teq | SGD | 0 | SO | 1,181.25 | 82.69 | Standard-rated |
| 994 | 2024-08-14 | Maxi-Teq | SGD | 1 | SO | 390.00 | 27.30 | Standard-rated |
| 994 | 2024-08-14 | Maxi-Teq | SGD | 2 | SO | 270.00 | 18.90 | Standard-rated |
| 995 | 2024-08-16 | Web Customer | SGD | 0 | SO | 1,890.00 | 132.30 | Standard-rated |
| 996 | 2024-08-10 | One Time Customer | SGD | 0 | SO | 131.25 | 9.19 | Standard-rated |
| 996 | 2024-08-10 | One Time Customer | SGD | 1 | SO | 284.35 | 19.90 | Standard-rated |
| 996 | 2024-08-10 | One Time Customer | SGD | 2 | SO | 54,600.00 | 3,822.00 | Standard-rated |
| 997 | 2024-08-21 | One Time Customer | SGD | 0 | SO | 69,037.50 | 4,832.62 | Standard-rated |
| 997 | 2024-08-21 | One Time Customer | SGD | 1 | SO | 413.56 | 28.95 | Standard-rated |
| 997 | 2024-08-21 | One Time Customer | SGD | 2 | SO | 29,120.00 | 2,038.40 | Standard-rated |
| 997 | 2024-08-21 | One Time Customer | SGD | 3 | SO | 2,625.00 | 183.75 | Standard-rated |
| 998 | 2024-08-22 | Earthshaker Corporation | SGD | 0 | SO | 1,163.26 | 81.43 | Standard-rated |
| 998 | 2024-08-22 | Earthshaker Corporation | SGD | 1 | SO | 6,187.50 | 433.12 | Standard-rated |
| 998 | 2024-08-22 | Earthshaker Corporation | SGD | 2 | SO | 875.00 | 61.25 | Standard-rated |
| 999 | 2024-08-13 | Mashina Corporation | SGD | 0 | SO | 155.05 | 10.85 | Standard-rated |
| 999 | 2024-08-13 | Mashina Corporation | SGD | 1 | SO | 2,250.00 | 157.50 | Standard-rated |
| 1000 | 2024-07-15 | River Inc | SGD | 0 | ZR | 5,000.00 | 0.00 | **Zero-rated** |
| 1001 | 2024-07-15 | River Inc | SGD | 0 | ES33 | 3,000.00 | 0.00 | **Exempt (Reg 33)** |
| 1002 | 2024-07-15 | River Inc | SGD | 0 | OS | 2,000.00 | 0.00 | **Out-of-scope** |

### Purchase Invoices

| DocNum | DocDate | Vendor | CCY | Ln | VatGroup | LineTotal | TaxTotal | GST Category |
|-------:|---------|--------|-----|---:|----------|----------:|---------:|--------------|
| 591 | 2024-07-26 | Sea Corp | SGD | 0–4 | SI | 4,554.18 | 318.79 | Standard-rated input |
| 592 | 2024-07-16 | Far East Imports | SGD | 0–3 | SI | 8,887.50 | 622.13 | Standard-rated input |
| 593 | 2024-07-16 | Ocean Computers | SGD | 0–2 | SI | 6,945.14 | 486.16 | Standard-rated input |
| 594 | 2024-07-16 | SMD Technologies | SGD | 0–3 | SI | 11,873.75 | 831.16 | Standard-rated input |
| 595 | 2024-07-20 | Lasercom | SGD | 0–1 | SI | 14,907.50 | 1,043.53 | Standard-rated input |
| 596 | 2024-07-18 | SMD Technologies | SGD | 0–3 | SI | 30,065.10 | 2,104.56 | Standard-rated input |
| 597 | 2024-08-13 | Sea Corp | SGD | 0–3 | SI | 32,530.08 | 2,277.11 | Standard-rated input |
| 598 | 2024-08-04 | SMD Technologies | SGD | 0 | SI | 6.00 | 0.42 | Standard-rated input |
| 599 | 2024-08-27 | SMD Technologies | SGD | 0–2 | SI | 3,121.10 | 218.48 | Standard-rated input |
| 600 | 2024-08-20 | CTI Computers | SGD | 0–1 | SI | 105.76 | 7.40 | Standard-rated input |
| **601** | 2024-08-27 | Blockies Corporation | **EUR** | 0–3 | SI | 11,985.65 | 839.00 | Standard-rated input ⚠ **FX — excluded** |
| 602 | 2024-08-11 | Lasercom | SGD | 0–3 | SI | 2,955.17 | 206.86 | Standard-rated input |
| 603 | 2024-08-08 | CTI Computers | SGD | 0–2 | SI | 1,626.48 | 113.85 | Standard-rated input |
| **604** | 2024-08-17 | Lumarx | **USD** | 0–3 | SI | 8,599.86 | 601.99 | Standard-rated input ⚠ **FX — excluded** |
| 605 | 2024-07-15 | Acme Associates | SGD | 0 | BL | 800.00 | 56.00 | **Blocked (Reg 26/27)** |
| 606 | 2024-07-15 | Acme Associates | SGD | 0 | IM | 4,500.00 | 315.00 | **Import GST** |
| 607 | 2024-07-15 | Acme Associates | SGD | 0 | ZP | 1,200.00 | 84.00 | **Zero-rated purchase** |

*(DocNums 601 and 604 are shown with line-level detail in the full enumeration above; purchase-side totals for those rows are given here for reference only — they are excluded from all F5 calculations.)*

---

## Step 6 — VatGroup Summary (SGD invoices only)

### Sales

| VatGroup | GST Category | Lines | LineTotal (SGD) | TaxTotal (SGD) |
|----------|-------------|------:|----------------:|---------------:|
| SO | Standard-rated output | 62 | 370,589.97 | 25,941.32 |
| ZR | Zero-rated supply | 1 | 5,000.00 | 0.00 |
| ES33 | Exempt — Regulation 33 | 1 | 3,000.00 | 0.00 |
| OS | Out-of-scope | 1 | 2,000.00 | 0.00 |

### Purchases

| VatGroup | GST Category | Lines | LineTotal (SGD) | TaxTotal (SGD) |
|----------|-------------|------:|----------------:|---------------:|
| SI | Standard-rated input | 39 | 117,577.76 | 8,230.45 |
| IM | Import GST | 1 | 4,500.00 | 315.00 |
| ZP | Zero-rated purchase | 1 | 1,200.00 | 84.00 |
| BL | Blocked input (Reg 26/27) | 1 | 800.00 | 56.00 |

---

## Step 5 — E1 Candidates (non-SGD sales invoices coded SO or DS)

11 lines across 8 invoices are flagged. All have `DocCurrency ≠ SGD` and `VatGroup = SO`:

| DocNum | Date | Customer | CCY | Lines affected |
|-------:|------|----------|-----|---------------|
| 958 | 2024-07-02 | SG Electronics | USD | Line 0 |
| 964 | 2024-07-09 | Aquent Systems | USD | Line 0 |
| 965 | 2024-07-09 | Aquent Systems | USD | Line 0 |
| 967 | 2024-07-28 | ADA Technologies | EUR | Lines 0–1 |
| 971 | 2024-07-24 | ADA Technologies | EUR | Line 0 |
| 974 | 2024-07-11 | SG Electronics | USD | Lines 0–2 |
| 977 | 2024-07-29 | Aquent Systems | USD | Line 0 |
| 982 | 2024-08-03 | ADA Technologies | EUR | Line 0 |

These appear to be overseas customer invoices coded SO (standard-rated). If these represent exports of goods or international services under GST Act s21(3), they should be coded ZR. **Review export documentation (customs permits, service contracts) for each before reclassifying.** Do not reclassify without confirmed evidence.

---

## FX Invoices Excluded from All Box Calculations

**Sales (8 invoices):** DocNums 958, 964, 965, 967, 971, 974, 977, 982 — currencies USD and EUR.
**Purchases (2 invoices):** DocNum 601 (Blockies Corporation, EUR), DocNum 604 (Lumarx, USD).

These 10 invoices are fully excluded from any F5 box totals until their values are converted to SGD using an IRAS-approved exchange rate methodology and re-entered in SGD.

---

## Anomalies

None. Every VatGroup found in the data (SO, ZR, ES33, OS on the sales side; SI, IM, ZP, BL on the purchase side) is in the standard mapping.

---

## Note on Tax Rates

All `TaxPercentagePerRow` values in the data are **7%** — this is the pre-2024 SBODEMOSG demo data artefact. The current statutory rate is 9% (effective 1 January 2024). This is not a compliance issue in this demo environment and has not been treated as an error in this classification.

## Failure analysis

See `../baseline-test-results.md` § "v2 Test 2" for full score breakdown and gap status.

## Key finding

DocNum 982 (ADA Technologies, EUR, 2024-08-03) flagged as E1 candidate but not in the
reference set of 11 E1 errors. Possible false positive — August invoice may be outside
the seeded error set. Costs 1 precision point. Response correctly withheld reclassification
pending review.