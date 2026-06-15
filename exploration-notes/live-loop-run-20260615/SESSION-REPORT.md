# T5.3-V — crafted-finding LIVE run (architecture A) — SESSION REPORT

**Date:** 2026-06-15 · **Pinned master:** `af79296` (T5.3f merged, PR #25) · **Model:** `claude-opus-4-8` (live, via `claude` CLI 2.1.177, SDK 0.2.99, OAuth pro)

*(Preserved D15: this report + `summary.json` + `raw/ledger.json` are kept; the full `raw/stream.json` token stream (247 KB) was intentionally omitted as heavy — its salient facts are distilled here and in the ledger.)*

> **crafted-finding live — machinery only; NOT demo-DB, NOT real-client, NOT accuracy-validated.**

## What was run
The rewired `run_casefile_loop` (arch A, in-turn MCP reads, driver-decided staging) driven against a **real model**, over a **hand-crafted** `ReviewResult` (two findings) and a **real non-empty** `LoopContext`:
- `invoke_review` = hand-built `ReviewResult`: `detect:NO_GST_REG:605` (card `Mama Shop Supplies`) + `doc:gst_amount_mismatch:3001`.
- `ctx` = `LoopContext(provider=<fixture INV-3001.pdf for doc 3001>, vendor_catalog={"Mama Shop Supplies": …}, prior_period_store={"NO_GST_REG:Mama Shop Supplies": …})`.
- `transport = make_live_transport(ctx, ledger, budget, system_prompt=SYSTEM_PROMPT, query_fn=<tee of the real query>)`, `AGENT_LIVE_TRANSPORT=1`.
- `RunBudget(max_turns=8, max_cost_usd=2.00)`. Raw saved at `raw/stream.json` (+ `raw/ledger.json`) **before** any metric.

## Headline result
| Metric | Value |
|---|---|
| total `cost_usd` (real COGS) | **$1.08437** (under the $2 cap) |
| `budget_exceeded` | False · `agent_layer_complete` | True |
| PENDING proposals staged | **0** |
| `dossier_completeness_rate` | **0.0** (demo — NOT T2.11) |
| `language_lint_pass_rate` | **1.0** (demo — NOT T2.11) |
| reads called in-turn | **19** `mcp__reads__*` calls · ToolSearch (built-in) **13× — all denied** |

## The two open checks (the reason this run exists)

**(a) Did the model call the `mcp__reads__*` tools in-turn, and did the sink fill? — YES (mechanism validated).**
The model emitted real `ToolUseBlock`s for `mcp__reads__get_source_document` / `read_vendor_gst_status` / `read_prior_period_treatment` (19 calls); the SDK ran the T5.3e handlers in-turn and they wrote the per-finding `evidence_sink`. This is the decisive arch-A validation — **NOT** the prose-only behaviour the unbacked-tool probe showed. The in-turn round-trip works against a live model.

**(b) Live hook-written read ledger `tool_name` form — NAMESPACED.**
The live PreToolUse hook ledgered the reads as **`mcp__reads__get_source_document`** (and `…read_vendor_gst_status`, `…read_prior_period_treatment`). The hermetic fakes (constraint B) write the **bare** form (`get_source_document`). **DIVERGENCE flagged:** the hermetic loop basket's simulated read ledger entries do not match the live namespaced names. A follow-on should normalise (either the fakes write the namespaced form, or the ledger/eval normalises via `_strip_mcp_prefix`) so the hermetic basket faithfully mirrors live.

## Why 0 PENDING despite reads firing (the actionable finding)
Completeness is **code-defined** and keyed to the exact `CheckSpec.inputs_needed` slot names — `document_pdfs` (for `gst_amount_mismatch`) and `supplier_catalog` (for `NO_GST_REG`). The live model invented its **own** `evidence_slot` values:
- `get_source_document` → `evidence_slot="source_document"` (required: **`document_pdfs`**)
- `read_vendor_gst_status` → `evidence_slot="vendor_gst_status"` (required: **`supplier_catalog`**)
- it also mixed finding args (passed `doc_num=605` — the NO_GST_REG doc — to `get_source_document`; passed `card_name` as `key`; once sent `doc_num='"605"'` quoted), and burned turns calling the built-in `ToolSearch` looking for tools.

So the handlers wrote the sink under **the wrong keys**, completeness was never satisfied, and — correctly — the **driver declined to stage** (driver-decided A1 held: no completeness ⇒ no PENDING). Each finding exhausted `max_attempts_per_finding=3` (6 loop turns total) cleanly. **This is a system-prompt / tool-schema tuning gap, not a mechanism failure:** the prompt must pin the exact `evidence_slot` per check (and ideally the tool input schema should enumerate/validate the slot, or the driver should map model slot → canonical slot). That is the next follow-on before a useful demo-DB run.

## Cage invariants — held live ✅
- **Tier-3 denial:** `ToolSearch` (a leaked CLI built-in) was called 13× and **denied every time** ("tool-not-found: not in the agent registry"). The cage held against an out-of-registry tool.
- **No Tier-2:** zero seal/emit entries in the ledger; **nothing sealed or emitted**; 0 proposals approved.
- **Only PENDING path:** the loop's sole staging path is PENDING; none reached it (completeness unmet).
- **Justification gate:** the Tier-1 `run_review_chain` gather entry was written; reads gated Tier-0.
- `validation_status` / `show_ai_candidates` **untouched**.

## Honest qualifier (verbatim)
> Live loop run on SBODEMOSG, a SYNTHETIC demo DB, architecture A (in-turn MCP reads, driver-decided staging). Demonstrates the rewired loop runs live end-to-end and stages sane PENDING proposals at a measured token cost. NOT real-client validation; does NOT validate finding correctness. `validation_status` remains `"unvalidated"`, `show_ai_candidates` remains `False`. T2.11 still gates customer-facing.

*Run-specific correction to the boilerplate above: this was a **crafted-finding** run (hand-built ReviewResult + fixture ctx), **NOT** an SBODEMOSG/demo-DB run (SAP creds were unprovisioned), and it staged **0** PENDING (the model used non-canonical `evidence_slot` names). It validates the live arch-A **machinery** and the cage invariants — not dossier staging end-to-end, and not finding accuracy.*

## Follow-ons surfaced
1. **System-prompt + slot contract:** pin the exact `evidence_slot` per check (and the finding's `doc_num`/`card_name`/`key`); consider validating/enumerating `evidence_slot` in the MCP tool input schema, or mapping model-supplied slot → canonical slot in the handler. Without this, completeness can't be reached live.
2. **Hermetic ↔ live ledger parity (check b):** normalise the read `tool_name` form (namespaced vs bare) so the T5.7b basket mirrors live.
3. **Restrict built-ins:** the model reached `ToolSearch` (denied, but wasted turns) — consider `disallowed_tools` / tighter `allowed_tools` so the live model isn't offered CLI built-ins at all.
