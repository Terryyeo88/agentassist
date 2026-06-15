# T5.3-probe — how does `query()` handle an unbacked Tier-0 read?

**Date:** 2026-06-15 · **Pinned master:** `d77c64d` · **Cost:** $0.163958 (one call, cap was $0.50)

## Question
When the live model is told to use a Tier-0 read (`get_source_document`) that is in
`allowed_tools()` **by name but has no MCP handler**, under a propose-only system prompt —
does `claude_agent_sdk.query()` return exactly ONE clean `ResultMessage` (one turn), or does
it feed "tool-not-found" back to the model and keep looping?

## Method
One direct `query(prompt, options)` call. `options = build_options(ledger, budget,
system_prompt=PROBE_SYSTEM_PROMPT)` → `allowed_tools` = the 11 registry names (incl.
`get_source_document`), `mcp_servers = {}` (no backing handler). `RunBudget(max_turns=2,
cost_cap_usd=0.50)`. Raw stream saved to `raw/stream.json` (9 messages) **before** interpretation.

## Raw result (9 messages, in order)
`SystemMessage` ×1 → `RateLimitEvent` → `SystemMessage` ×4 → **`AssistantMessage`[`ThinkingBlock`]**
→ **`AssistantMessage`[`TextBlock`]** → **`ResultMessage`** (`subtype=success`, `is_error=False`,
**`num_turns=1`**, `stop_reason=end_turn`, **`total_cost_usd=0.163958`**).

- **`ResultMessage` count: exactly 1.** Turn count consumed: **1**.
- **`ToolUseBlock`s emitted: NONE.**
- The model expressed the read as **prose** in the `TextBlock`, then the framing line:
  ```
  get_source_document read request:
  - evidence_slot: "document_pdfs"
  - justification: "Fetch source invoice PDF for doc_num 958 to inspect GST fields flagged by gst_amount_mismatch."

  candidate for review: doc_num 958 flagged by check_id gst_amount_mismatch — source invoice PDF
  requested for human verification of GST amounts; no compliance determination made.
  ```

## Answers
- **Turn shape:** ONE clean turn (single `ResultMessage`, `end_turn`). No multi-turn loop.
- **Unbacked-tool handling:** there was **no tool-use to handle**. `--allowedTools` is a *permission
  filter*, not a tool *definition* (tools are defined only via MCP). With no MCP backing,
  `get_source_document` is **never in the model's tool schema**, so the model **cannot emit a
  structured `ToolUseBlock`** for it → no "tool-not-found" error, no loop. The CLI ran the turn to a
  normal `end_turn`.
- **Model reaction:** honored propose-only and fell back to describing the read in **prose** (it
  could not structurally call the absent tool), and produced the clean `candidate for review:` line.
- **Cost/turns:** $0.163958, 1 turn.

## Verdict
The **timing** half of the `LiveAgentTransport` model **HOLDS**: one `query()` = one clean turn (one
`ResultMessage`), so the adapter's `ResultMessage→ResultEvent(cost_usd=total_cost_usd)` per-turn COGS
mapping is correct.

The **mechanism** half **DOES NOT HOLD**: the assumption that "the model emits a structured tool-use
the driver translates into a read" fails for a **name-only allow-list with no MCP backing**. The model
*cannot* call an unbacked tool, so `_translate` yields **zero `ToolUseEvent`s** — only one
`FramingEvent` (from the `TextBlock`) and the `ResultEvent`. Consequence in a real loop: no evidence
slot is ever filled by tool-use, completeness fails, and no PENDING proposal is staged. The driver's
"fill evidence between turns from `ToolUseEvent`s" path never triggers.

## Recommended read-wiring for the real T5.3-V harness
**MCP-back the Tier-0 reads with driver-controlled handlers** (option (a)). Define the reads via
`create_sdk_mcp_server` + `@tool` handlers that wrap the driver's `ctx` reads (`get_source_document`,
`read_vendor_gst_status`, `read_prior_period_treatment`) and wire that server into
`build_options(..., engine_server=...)`/`mcp_servers` — exactly the pattern the engine tool already
uses (`agent/engine_tool.py`). Then the reads appear in the model's schema, the model *actually calls*
them, the SDK invokes the **driver-written** read handler in-turn (which IS the driver executing a
read-only Tier-0 op), and the result returns to the model. Invoke-never-perform is preserved (reads
are read-only Tier-0; no Tier-2; handlers are ours and the cage hooks still gate). The `LiveAgentTransport`
`ToolUseBlock→ToolUseEvent` mapping then also fires for observability.

**Architecture note this surfaces:** with MCP-backed reads, evidence is gathered *inside* `query()`
(handler returns it to the model in-turn) rather than assembled by the driver *between* turns — a real
shift from the hermetic `ScriptedLoopTransport` shape. The T5.3-V harness build must decide how the
in-turn handler results populate the driver-side evidence map (e.g. handlers append to a driver-owned
evidence collector keyed by `evidence_slot`, and the code-defined completeness checklist still governs
termination). Structured-text parsing (option (b)) is possible — the prose here is regex-parseable —
but brittle; `ClaudeSDKClient` manual turns (option (c)) adds plumbing without solving the unbacked-tool
issue. **Recommend (a).**

---

> Probe only — a single minimal `query()` call to characterise SDK turn behaviour with an unbacked
> tool-use. Not a loop run, not validation. `validation_status`/`show_ai_candidates` untouched. T2.11
> still gates customer-facing.
