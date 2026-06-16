# UNVALIDATED / DRAFT — T5.3-V round 2 (real-ctx) live MECHANISM validation

**Date:** 2026-06-16 · **Branch:** `t5.3v-round2-live-loop` off `master 19eb62e` · **Model:** `claude-opus-4-8`
**Run:** arch-A `run_casefile_loop` over a REAL `LoopContext` (T5.3h `build_loop_context`) + REAL findings
(offline `replay_review` off the frozen SBODEMOSG extract, SAP unreachable). Attended, opt-in, token-burning.

## What this validates — and what it does NOT
- **Validates:** the agentic-shell **MECHANISM** — `gather → complete → stage` produces real PENDING
  `ProposalArtifact`s on a live model over real data, and the cage holds.
- **Does NOT validate:** finding **accuracy** (that is T2.11). Still nothing customer-facing:
  `validation_status="unvalidated"`, `show_ai_candidates=False` (untouched — `git diff` empty on
  `config/`/`engine/`/`ui/`).

## Setup
- Finding set (option B, Terry 2026-06-16): the first 3 `NO_GST_REG` findings —
  **Acme Associates (605), Far East Imports (592), SMD Technologies (594)** — chosen so the loop exercises
  the T5.3g `supplier_catalog` slot LIVE via `read_vendor_gst_status` over the real S3 vendor catalog.
- `RunBudget(max_turns=12, max_cost_usd=3.00)`. `ctx` = `AbsentDocumentProvider` + real vendor catalog
  (9 vendors) + empty prior-period store (honest SBODEMOSG degraded case).
- Run script: `run_round2_realctx.py` (thin; under `exploration-notes/` — no source/test change).

## Result — SUCCESS (round-1 0-PENDING gap CLOSED)

| Field | Round-1 (2026-06-15, crafted) | **Round-2 real-ctx (this run)** |
|---|---|---|
| Data | hand-built ReviewResult + fixture ctx | **real `replay_review` findings + real T5.3h ctx** |
| # PENDING staged (≥1 = success) | **0** | **3** ✅ |
| Attempts / finding | 6 (staged nothing) | **1** each |
| Canonical slots filled | invented (`source_document`…) | **`supplier_catalog`** (code-bound) ✅ |
| dossier_completeness_rate | 0.0 | **1.0** |
| language_lint_pass_rate | 1.0 | **1.0** |
| Tier-3 leaked-built-in denials | 13× `ToolSearch` | **0** |
| Tier-2 (seal/emit) | none | **none** |
| Cost (USD) | ~$1.08 (cap $2) | **$1.013447** (cap $3.00) ✅ |
| budget_exceeded / agent_layer_complete | false / true | **false / true** |

### MECHANISM assertions (per the run prompt)
1. **≥1 real PENDING staged** — ✅ **3** `NO_GST_REG` PENDING proposals.
2. **completeness met via correctly-named slots (T5.3g LIVE)** — ✅ all 3 met through `supplier_catalog`.
   The model passed only `card_name`; the slot is code-bound (`READ_TOOL_SLOT`/`canonical_slot`, removed
   from the model-facing schema), so the round-1 "invented slot name" failure is structurally impossible.
3. **Cage held** — ✅ ledger = 16 entries: 1× Tier-1 `run_review_chain` (gather) +
   3×(3 Tier-0 `mcp__reads__*` + Tier-0 `budget_increment` + Tier-1 `propose_action`). **Zero Tier-2**,
   nothing sealed/emitted, **zero Tier-3 denials** (Opus never reached for `ToolSearch`).
4. **Budget non-blocking (Invariant 7)** — ✅ `$1.013447 ≤ $3.00`; no `BudgetExceededSignal`.
5. **Frozen flags untouched** — ✅ `git diff` empty on `config/`/`engine/`/`ui/`.

## Honest scope — slot coverage
- **`supplier_catalog`: validated LIVE ×3** — the required slot for `NO_GST_REG`; completeness met through it.
- **`document_pdfs`: NOT live-exercised through complete→stage.** The model *did* call `get_source_document`
  in-turn and the handler correctly wrote the canonical `document_pdfs` slot — but over
  `AbsentDocumentProvider` it returned ABSENT (`None`), and **no document-requiring check was in the set**
  (`NO_GST_REG` does not need `document_pdfs`). So the slot **binding** is shown correct, but the
  **complete→stage path through `document_pdfs`** is not (needs a document-requiring finding + a real PDF
  provider — a future run).

## Evidence (raw saved BEFORE any scoring)
- `raw/ledger.json` — 16 entries (the cage trace).
- `raw/stream.json` — 64,773 bytes (under the ~1 MB cap, so retained; 48 SDK messages / 3 query calls).
- `summary.json` — the scored summary (cost, PENDING count, tool calls, tier counts, metrics).
- `run_round2_realctx.py` — the thin run-script.

## Status line
MECHANISM validated on a live model over real data; **NOT** accuracy-validated. `show_ai_candidates`
stays `False`; **T2.11 still gates everything customer-facing.**
