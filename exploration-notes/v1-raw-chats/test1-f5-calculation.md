# v1 Test 1: F5 Calculation — Raw Response

**Date run:** 2026-05-25
**Model:** Claude Sonnet 4.6
**Configuration:** Claude Desktop, sap-b1 MCP connector + Project knowledge base (sg-tax-code-mappings.md + IRAS rules), no system prompt, no new tools
**Score:** 5/10 (rubric) | MAPE: N/A (quarter mismatch)

## Prompt

> Using SAP Business One, calculate the GST F5 return figures for the most recent quarter available in the system. Give me the values for Boxes 1 through 8.

## Response (verbatim)

Connected to SBODEMOSG. Let me first find the most recent transactions to determine the latest quarter available.Most recent data is in August 2024. The most recent full quarter would be **Q2 2024 (Apr–Jun 2024)**. Now let me pull all the relevant invoices. I'll query sales and purchase invoices for that quarter, including their line-level tax codes and amounts.Good — I can see the structure. The key fields are `VatGroup`, `LineTotal`, and `TaxTotal`. Note the demo DB has 7% rate (as documented). Now let me extract all the data properly.No credit notes on either side. Now let me compile the full F5 calculation and apply the rate adjustment note.Here are the GST F5 figures for **Q2 2024 (1 April – 30 June 2024)**, the most recent complete quarter in SBODEMOSG:

---

## GST F5 Return — Q2 2024

| Box | Description | SGD |
|-----|-------------|----:|
| **Box 1** | Total value of standard-rated supplies (net) | **226,189.78** |
| **Box 2** | Total value of zero-rated supplies | **0.00** |
| **Box 3** | Total value of exempt supplies | **0.00** |
| **Box 4** | Total supplies (1 + 2 + 3) | **226,189.78** |
| **Box 5** | Total value of taxable purchases (net) | **244,955.28** |
| **Box 6** | Output tax due | **20,357.08** |
| **Box 7** | Input tax claimed | **22,045.98** |
| **Box 8** | Net GST (6 − 7) | **−1,688.90** ← **REFUND** |

---

### How the figures were derived

**Sources found in the quarter:**
- **20 sales invoices** — all lines coded `SO` (standard-rated sales). No zero-rated (`ZR`), exempt (`ES33`/`ESN33`), or deemed supply (`DS`) lines were present.
- **16 purchase invoices** — all lines coded `SI` (standard-rated purchases). No blocked (`BL`), non-registered (`NR`), import, or exempt purchase codes found.
- **Zero credit notes** on either side, so no deductions apply.

**Box 1 & 5** use `LineTotal` (net of GST) per IRAS para 5.7 / 6.5.1 — values tracked separately from tax, not derived by re-grossing.

**Box 6 & 7** use line-level `TaxTotal` amounts, recalculated at the current **9% GST rate** (effective 1 Jan 2024). The demo database stores transactions at 7% — this is a known data artefact in SBODEMOSG and is not a compliance issue in the demo environment.

**Box 8** is negative (−SGD 1,688.90), meaning a **refund from IRAS** is due. Since the absolute value exceeds SGD 5, the refund threshold at para 6.8.3 is met and the amount does not get dropped.

> ⚠️ **Before filing against live data:** Confirm the 9% rate is correctly configured in your production VatGroups, and verify that any foreign currency invoices have been converted to SGD using an IRAS-acceptable exchange rate methodology (per the Exchange Rates e-Tax Guide).

## Failure analysis

See `../baseline-test-results.md` § "v1 Test 1" for full score breakdown and gap status.