# v0 Raw Chat Evidence

This folder contains the raw, unedited Claude Desktop responses for the v0 baseline tests. These are the source data for the scores in `../baseline-test-results.md`.

## Folder contents

| File | Test | Date run | Score |
|------|------|----------|-------|
| `test1-f5-calculation.md` | F5 Calculation | 2026-05-25 | 4/10 |
| `test2-tax-classification.md` | Tax Code Classification | TBD | TBD |
| `test3-error-detection.md` | Error Detection | TBD | TBD |

## Methodology

Each test was run in a **fresh Claude Desktop chat** with the following configuration:

- Model: Claude Sonnet 4.6
- Active connectors: sap-b1 (read-only MCP custom server, 11 original tools)
- Project knowledge: none
- Custom instructions: none
- Style: default
- Previous conversation context: none

The new MCP tools added in phase2-accounting-workflows (`calculate_f5_return`, `validate_invoice_tax_codes`, `detect_gst_errors`) were NOT available to Claude Desktop at the time of these runs because Claude Desktop had not been restarted since the tools were added. This is intentional — v0 must measure plain-Claude capability with no help from deterministic helpers.

## How responses were captured

Each chat response is saved verbatim. Tool calls and intermediate "thinking" steps are summarised in italics at the points where they occurred; final user-facing output is reproduced in full. No edits to wording, formatting, or numbers.

## Why these are kept

1. **Evidence trail** — anyone questioning a score can read the original response.
2. **Comparison material** — when v1, v2, v3 runs are done with the same prompts, the deltas can be compared line-by-line against these.
3. **Failure analysis** — the specific way Claude got things wrong (which numbers, which classifications, which omissions) tells us exactly what context or tooling would have prevented each failure.