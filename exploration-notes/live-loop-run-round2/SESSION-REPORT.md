# T5.3-V round 2 — live complete→stage validation (SESSION REPORT)

**Date:** 2026-06-15 · **Branch:** `t5.3v-round2` off `origin/master 5e4ae30` (incl. T5.3g) · **Crafted finding, no SAP.**

## What "success" is — and what it is NOT (verbatim)
- **Success = the live loop's gather → complete → stage MACHINERY runs end-to-end on a real model:** ≥1 PENDING staged on the crafted finding.
- This does **NOT** prove finding accuracy (that is T2.11), and it is still a **crafted** finding, NOT real client data. The claim graduates from round-1's "reads fire in-turn" to "the full loop stages a candidate live" — and stops there. `validation_status="unvalidated"` / `show_ai_candidates=False` stay frozen.

## Result: SUCCESS — both runs stage 2 PENDING

Controlled experiment, one variable per run. Round-1 (Opus, default) staged **0 PENDING** because the model invented `evidence_slot` names. T5.3g bound the slot in code and removed it from the model schema. Run A holds the model constant (Opus) → a green result is attributable to the slot fix. Run B changes only the model (Sonnet) → COGS/quality comparison.

| Field | Round-1 (Opus) | **Run A (Opus, pinned)** | **Run B (Sonnet, pinned)** |
|---|---|---|---|
| Model id (pin took?) | claude-opus-4-8 | **claude-opus-4-8** ✅ | **claude-sonnet-4-6** ✅ |
| **# PENDING staged** (≥1 = success) | 0 | **2** ✅ | **2** ✅ |
| Canonical slots filled | invented (`source_document`…) | `document_pdfs` + `supplier_catalog` ✅ | `document_pdfs` + `supplier_catalog` ✅ |
| dossier_completeness_rate | 0.0 | **1.0** | **1.0** |
| language_lint_pass_rate | 1.0 | 1.0 | 1.0 |
| Leaked-built-in denied-count | 13× `ToolSearch` | **0** | **1× `Read`** |
| Ledger name form | namespaced | namespaced (`mcp__reads__…`) | namespaced |
| Tier-2 (seal/emit) | none | none | none |
| **Cost (USD)** | $1.08 | **$0.859977** | **$0.496697** |

Ledger shape (both Run A & B): 7× Tier-0 reads + 3× Tier-1 (1 gather + 2 driver-decided `propose_action`); zero Tier-2. Each finding completed in **1 attempt** (round-1 took 6 attempts, staged nothing).

## The two resolving numbers

**1. # PENDING = 2 (≥1) on Opus held constant → the slot fix works.** With `evidence_slot` bound in code (T5.3g `READ_TOOL_SLOT` / `canonical_slot`) and removed from the model-facing schema, the model passed only the finding identifier, the canonical slots (`document_pdfs`, `supplier_catalog`) filled, the code-defined completeness was satisfied, and the **driver** (not the model) staged 2 PENDING. The live `gather → complete → stage` machinery is proven end-to-end on a real model — attributable to the slot fix alone (model held constant vs round-1).

**2. Denied-count resolves the T5.3g allowlist caveat — with nuance.**
- **Opus: 0 denials.** The model never tried `ToolSearch` (round-1: 13×). The `tool_allowlist=READ_TOOLS_QUALIFIED` + `disallowed_tools=["ToolSearch"]` removed it from Opus's schema.
- **Sonnet: 1 denial of `Read`.** Sonnet reached for a *different* built-in (`Read`) that is **not** in the denylist — the allowlist did **not** remove it from Sonnet's schema; it was **offered-then-denied by the cage PreToolUse hook** (Tier-3, "tool-not-found").

**Conclusion:** `allowed_tools` is an auto-approve filter, **not** a complete schema restriction (exactly as T5.3g flagged). `disallowed_tools` only suppresses the names you list; **the cage PreToolUse hook is the real backstop** — proven here, it denied `Read` for Sonnet and nothing escalated. A follow-on could extend `disallowed_tools` to common built-ins (`Read`/`Write`/`Bash`/`ToolSearch`…), but the cage backstop makes it non-critical; both runs staged correctly despite the denied attempt.

## COGS comparison (pricing input)
| | Opus 4.8 | Sonnet 4.6 | delta |
|---|---|---|---|
| Cost / 2-finding crafted review | **$0.859977** | **$0.496697** | **−$0.363 (Sonnet ≈ 58% of Opus)** |
| PENDING staged | 2 | 2 | same |
| Completeness / lint | 1.0 / 1.0 | 1.0 / 1.0 | same |

**Sonnet 4.6 produces identical output (2 PENDING, complete, lint-clean, same canonical slots) at ~42% lower cost** for this light gather+frame workload. The model is a per-run choice (T5.3g `model` param; default None) — this is the COGS evidence for choosing Sonnet for the demo/pilot loop.

## Honest framing
The live loop's **machinery** stages a candidate end-to-end on a real model, on both Opus and Sonnet. This does **NOT** prove finding accuracy (that is T2.11), and it is still a **crafted** finding, NOT real client data. `validation_status` remains `"unvalidated"`, `show_ai_candidates` remains `False`. T2.11 still gates everything customer-facing.

## Evidence
Raw saved before scoring: `runA-opus/{raw/stream.json,raw/ledger.json,summary.json,console.log}`, `runB-sonnet/{…}`. Round-1 apparatus folded in: `../live-loop-run-20260615/run_crafted.py` + `raw/stream.json` (previously omitted as heavy; now on the branch so `-liverun5` is disposable after merge). No production code touched.
