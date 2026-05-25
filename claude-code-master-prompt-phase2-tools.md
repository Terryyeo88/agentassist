# Claude Code Master Prompt — Add 3 MCP Tools to sap_b1_server.py

Paste everything below the line into Claude Code from the project root
(`C:\Users\terry\Desktop\AgentAssist\sap-b1-ai-agent`).

---

You are extending the custom MCP server for the AgentAssist project — an AI
accounting assistant for Singapore SMEs running on SAP Business One. Read the
context below carefully before writing any code, then follow the task
instructions exactly.

## PROJECT CONTEXT — read these files first

Before touching anything, read these to ground yourself:

1. `mcp-servers/custom/sap_b1_server.py` — the existing MCP server you will be
   modifying. Note the FastMCP pattern (sync `httpx.Client`, `@mcp.tool()`
   decorators, the `sap` client object, the `_fmt()` helper).
2. `scripts/run_baseline_tests.py` — contains the reference F5 calculation and
   E1–E4 error-detection logic you will be porting. This logic is
   known-correct (it produced the baseline test report).
3. `knowledge-base/sg-tax-code-mappings.md` — authoritative VatGroup → F5 box
   mappings. Use these exactly; do not invent new mappings.
4. `exploration-notes/baseline-test-results.md` — the gaps these tools must
   close (FX handling, tax-code classification, full F5 coverage, E1–E4
   detection).
5. `scripts/test_data_registry.json` — DocEntry list of the 6 seeded test
   invoices, so you know what to expect when testing.

## CRITICAL CONSTRAINTS — do not violate

- **Do NOT rewrite the existing 12 tools.** Add the 3 new tools to the same
  file, preserving the existing FastMCP pattern, the `sap` client, the
  `_fmt()` helper, and the `main()` entry point.
- **Sync httpx only.** The existing server uses `httpx.Client`, not async.
  Match that pattern — async will break FastMCP stdio.
- **Pagination.** B1 enforces a hard 20-record page cap regardless of `$top`.
  Loop using `$skip` until fewer than 20 records come back. The existing
  baseline script already does this — port the loop pattern.
- **Line-level tax field is `TaxTotal`, not `VatSum`.** `VatSum` only exists
  at header level. When iterating `DocumentLines`, sum `TaxTotal` per line.
- **VatGroup lives in `DocumentLines`**, not in the invoice header. Header
  has no VatGroup field — do not try to read one.
- **Do not do arithmetic in Claude. Do it in Python.** These tools exist
  precisely so Claude never calculates F5 figures itself. Every box value
  must be computed in the tool and returned as a number.
- **Return structured JSON strings** via `_fmt()` (or equivalent) — matching
  how the existing tools return data. Claude Desktop expects strings from
  MCP tools.
- **GST rate.** Demo data is 7% (SBODEMOSG, pre-2024). Production is 9%
  (from 1 Jan 2024). Make the expected rate a parameter with default 0.07
  for E4 detection, so production can override to 0.09 without code change.
- **Currency.** Only SGD invoices contribute to F5 box totals. Non-SGD
  invoices must be listed separately as `fx_invoices_requiring_conversion`
  with DocNum, DocDate, DocCurrency, DocTotal, CardName — never silently
  included or excluded. Claude will decide what to do with them.

## TASK — add exactly these 3 tools

### Tool 1: `calculate_f5_return(period_start: str, period_end: str) -> str`

Port the F5 calculation from `scripts/run_baseline_tests.py`. Dates are
ISO format `YYYY-MM-DD`.

Query both `Invoices` and `PurchaseInvoices` for the period, paginating
20 at a time, with `DocumentLines` expanded. Filter SGD vs non-SGD.

For SGD records only, compute:

- Box 1 — `LineTotal` where VatGroup ∈ {SO, DS} on sales invoices
- Box 2 — `LineTotal` where VatGroup = ZR on sales invoices
- Box 3 — `LineTotal` where VatGroup ∈ {ES33, ESN33} on sales invoices
- Box 4 — Box 1 + Box 2 + Box 3
- Box 5 — `LineTotal` where VatGroup ∈ {SI, ZP, IM, IGDS, ME, NR} on
  purchase invoices (note: BL and OS are excluded from Box 5)
- Box 6 — `TaxTotal` where VatGroup ∈ {SO, DS} on sales invoices
- Box 7 — `TaxTotal` where VatGroup ∈ {SI, IM, IGDS} on purchase invoices
- Box 8 — Box 6 − Box 7

Return JSON with this shape:

```json
{
  "period": {"start": "...", "end": "..."},
  "currency": "SGD",
  "boxes": {
    "box_1_standard_rated_sales": 0.00,
    "box_2_zero_rated_sales": 0.00,
    "box_3_exempt_sales": 0.00,
    "box_4_total_sales": 0.00,
    "box_5_taxable_purchases": 0.00,
    "box_6_output_tax": 0.00,
    "box_7_input_tax": 0.00,
    "box_8_net_gst": 0.00
  },
  "fx_invoices_requiring_conversion": [
    {"doc_num": ..., "doc_date": "...", "currency": "...",
     "doc_total": ..., "card_name": "...", "type": "sales|purchase"}
  ],
  "record_counts": {
    "sales_invoices_sgd": 0, "sales_invoices_fx": 0,
    "purchase_invoices_sgd": 0, "purchase_invoices_fx": 0
  },
  "anomalies": [
    {"doc_num": ..., "issue": "unknown VatGroup 'XYZ' — not in mapping"}
  ]
}
```

Round all monetary values to 2 dp at the end, not during accumulation.

### Tool 2: `validate_invoice_tax_codes(period_start: str, period_end: str, expected_rate: float = 0.07) -> str`

For every line of every invoice (sales + purchase) in the period, check:

- **E1 — FX miscoding.** `DocCurrency != "SGD"` AND any line VatGroup = SO.
  Overseas sale likely miscoded; should usually be ZR.
- **E2 — Tax on non-taxable supply.** Line `TaxTotal > 0` AND VatGroup ∈
  {ZR, OS, ES33, ESN33, BL}. GST charged on something that shouldn't be
  taxed.
- **E3 — Missing tax on taxable supply.** Line `TaxTotal == 0` AND
  VatGroup ∈ {SO, SI}. Standard-rated line with no GST.
- **E4 — Rate mismatch.** Line VatGroup ∈ {SO, SI} AND
  `abs((TaxTotal / LineTotal) - expected_rate) > 0.001`. Likely GST-
  inclusive entered as exclusive, or wrong rate applied.
  Skip this check when `LineTotal == 0`.

Return JSON:

```json
{
  "period": {"start": "...", "end": "..."},
  "expected_rate": 0.07,
  "issues": [
    {"error_code": "E1", "doc_num": ..., "doc_date": "...",
     "doc_currency": "...", "card_name": "...", "vat_group": "...",
     "line_total": ..., "tax_total": ...,
     "description": "FX invoice with SO code — should likely be ZR"}
  ],
  "summary": {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 0}
}
```

### Tool 3: `detect_gst_errors(period_start: str, period_end: str, expected_rate: float = 0.07) -> str`

Higher-level tool. Internally calls the same helpers as Tool 2, then adds:

- **Completeness check.** Compare sales-to-purchase invoice ratio. If
  purchases / sales < 0.1 (by count) for a quarter with material sales,
  flag as MEDIUM: "Suspiciously low purchase volume — input tax may be
  understated."
- **Missing tax-invoice supplier data.** For any line with `TaxTotal > 0`
  on a purchase invoice, fetch the supplier (BusinessPartner by CardCode)
  and check `FederalTaxID`. If missing, flag HIGH: "Input tax claimed
  from supplier without GST registration number — may not be claimable."

Assign severity:

- HIGH — E1, E3, missing FederalTaxID with input tax claimed
- MEDIUM — E2, E4, completeness anomalies
- LOW — anomalies (unknown VatGroups)

Return JSON:

```json
{
  "period": {"start": "...", "end": "..."},
  "severity_counts": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
  "issues": [
    {"severity": "HIGH", "error_code": "E1", "doc_num": ...,
     "doc_date": "...", "card_name": "...",
     "description": "...", "recommendation": "..."}
  ]
}
```

Sort issues by severity (HIGH → MEDIUM → LOW), then by doc_date.

## REFACTOR — extract shared helpers

Both Tool 2 and Tool 3 do per-line validation. Both Tool 1 and Tool 2 do
paginated invoice fetching. Pull out:

- `_fetch_invoices_paginated(entity: str, period_start: str, period_end: str) -> list` —
  returns all records with DocumentLines expanded, handling the 20-record cap.
- `_classify_line(line, doc) -> list[dict]` — returns any E1–E4 issues
  found on one line.
- `F5_BOX_MAPPING` — a module-level dict keyed by VatGroup, mapping to
  box name and side (sales/purchase). Use this in Tool 1 instead of
  hardcoding sets in three places.

Keep helpers private (leading underscore). Do not expose them as tools.

## VERIFICATION — run after writing

1. Confirm the file still parses: `python -c "import ast; ast.parse(open('mcp-servers/custom/sap_b1_server.py').read())"`
2. Confirm the existing 12 tools are still defined (grep for `@mcp.tool()`
   — should now show 15).
3. Run a quick smoke test by invoking the tools directly (not through MCP)
   against the Q3 2024 test data. Create a temporary scratch script
   `scripts/_smoke_test_new_tools.py` that imports and calls each new
   tool with `period_start="2024-07-01", period_end="2024-09-30"`, prints
   the result, and exits. Delete the scratch script after verification.
4. Expected smoke-test signals:
   - `calculate_f5_return` — non-zero Box 1 (the demo data has standard-
     rated sales), non-empty `fx_invoices_requiring_conversion` (the
     seeded ZR/IM and demo data both include FX), all 8 boxes present.
   - `validate_invoice_tax_codes` — at least 11 E1 issues (the baseline
     Python script previously detected 11 FX-with-SO miscodings).
   - `detect_gst_errors` — same issues, with severity assigned and
     sorted, plus any completeness/FederalTaxID flags.
5. Report back: the 3 tool signatures, the smoke-test counts, and any
   anomalies found. Do not commit yet — I want to review before
   committing to the `phase2-accounting-workflows` branch.

## STOP CONDITIONS — ask before proceeding if

- The existing `sap_b1_server.py` has materially diverged from what the
  handoff describes (e.g. already has a Tool 1 placeholder).
- The seeded test data isn't present in B1 (`test_data_registry.json`
  references DocEntries that 404).
- You discover a VatGroup in the live data that isn't in the knowledge
  base mapping — flag it in the response, don't guess.

Begin by reading the 5 context files, then summarise back to me what you
plan to do before writing code.
