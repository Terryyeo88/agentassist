# AgentAssist Technical Roadmap v5

Revised from v4. v5 records what the diagnostic/fix runs of 2026-06-08 established, adds an explicit validation-dataset task, and places the multi-vertical platform vision as a gated north-star. It does not change any Tier 1/2/3 task already specified in v4 except where noted in the changelog.

**Status convention:** `DONE` / `IN PROGRESS` / `PROVISIONAL (unvalidated)` / `PLANNED`. Effort estimates on new tasks are **PROPOSED — needs Terry confirmation**; first-pass sizings, not commitments.

---

## What changed from v4 (changelog)

1. **The AI-candidate forwarding bug is fixed.** `run_agent.py` now forwards `judgment_artefact=reasoning_artefact` to `build_report`. The report's "AI-surfaced candidates" section renders the real status (e.g. "No AI-surfaced candidates" when `candidate_count=0`) instead of the false "AI candidate pass did not complete." Confirmed by a live re-run on 2026-06-08.

2. **`show_ai_candidates` wiring is confirmed working (T2.7 branch).** Declared in `config/loader.py` (default `False`), read in `report/report.py`, consumed in `report/sections.py` / `render.py`. The earlier v4 flag "not visibly consumed" is resolved — it is consumed on branch `t2.7-reasoning-reg2627`; it remains absent from `master`.

3. **SBODEMOSG holds no document attachments.** The `Attachments2` entity is supported (HTTP 200) but empty; 0/21 purchase invoices and 0/50 sales invoices carry an `AttachmentEntry`. Consequence for T2.8: invoices must be attached/uploaded manually for any document-ingestion demo or build — they cannot be pulled from this demo company.

4. **New task T2.13 — Validation dataset construction** (synthetic-paired + pilot-derived). Makes explicit the ground-truth substrate that T2.11 consumes, including the line-item-only-for-now vs paired-with-invoice-for-T2.8 distinction.

5. **New Tier 4 — Platform vision (north-star, gated).** Captures the consolidated multi-vertical agent dashboard as an explicitly sequenced future state, not a near-term build.

---

## Current build-state snapshot

**Shipping today (deterministic, validated on SBODEMOSG only):**
- SAP B1 MCP connector (Python FastMCP, stdio); three custom tools: `calculate_f5_return`, `validate_invoice_tax_codes`, `detect_gst_errors`. Error codes E1–E4, NO_GST_REG, COMPLETENESS.
- T1.6 deterministic orchestration chain (fetch → classify → calculate → detect → compile) with five pure-Python reconciliation gates that halt on failure. `orchestrator/` pure-Python; `llm_in_run_path: false`.
- T1.4 signed PDF working paper (`report/`); T1.5 tamper-evident audit bundle.
- Validated 10/10 on Tests 1–3 at v3 on SBODEMOSG Q3 2024 — clean demo data, not production-proven.
- **CI self-provisioning** (commit 40112ca, 2026-06-10): session-scoped autouse conftest fixture auto-generates gitignored PDF fixtures; `pdfplumber` added to `requirements.txt`; suite green on clean checkouts. Diagnosis: `exploration-notes/infra/ci-fixture-diagnosis-20260610.md`.
- **Synthetic demo scenario** at `exploration-notes/demo-scenario/` (commit 8b60d87): crafted SEQ_GAP/DUP_CLAIM/declared-F5 injections over SBODEMOSG Q3 2024, 10 self-verification assertions, disclosure README. **SYNTHETIC — NOT real-client validation.**
- **Check A float-robustness** (commit 40c9024): cent-quantized `Decimal` comparison; 5 new `[A-FP]` tests (see T2.9 entry).
- **Report styling normalized** (commit ae76578, merged PR #4): shared `_ai_table_style()` helper, redundant `_META` removed; content invariant (byte-identical text extraction); minor spacing only.
- **PDF test-fixture infrastructure fix** (commits `47e31a0`, `19a6f86`, 2026-06-10, branch `t2.2-vat-discovery`): a fresh-checkout pytest run found 209 pre-existing `FileNotFoundError` failures across `test_documents_ingest.py`, `test_documents_reconcile.py`, `test_document_fixtures.py`, `test_documents_unified_report.py` — the 8 generated fixture PDFs (`tests/fixtures/documents/INV-3001.pdf`…`INV-3008.pdf`) were excluded by a blanket `*.pdf` rule in `.gitignore` (this appears to conflict with the "suite green on clean checkouts" claim above for commit 40112ca). Fixed by adding `!tests/fixtures/documents/*.pdf` to `.gitignore` and committing the 8 generated PDFs, plus a new `.gitattributes` (`*.pdf binary`) to prevent Git CRLF corruption of the binaries under `core.autocrlf=true`. Suite: 975 passed/209 failed/1 skipped → **1184 passed, 0 failed, 1 skipped**.

**Built but unvalidated (all on `master` as of 2026-06-09, except where noted):**
- **T2.7** — Reasoning layer (`reasoning/` package): Reg 26/27 disallowed-input candidate surfacing. `show_ai_candidates` flag wired and working. Re-run over SBODEMOSG + 13 AGENTASSIST_SEED docs (2026-06-08) surfaced **5 reasoning candidates** (G2 bait DocNums 620–624) and **7 document candidates** (G1 reconciliation DocNums 614–619); both render in the unified `UnifiedCandidatesSection` with mandatory per-row `basis` tag.
- Provisional measurement (2026-06-03, 110-line Opus-labelled fixture): Sonnet recall 1.000 / FP 0.000, Opus 1.000 / 0.022, Haiku 1.000 / 0.065. **NOT gate results** — fixture labels are AI-generated, not human-reviewed. `validation_status: unvalidated`; `show_ai_candidates` stays `False` for any deliverable until T2.11 reconciles.
- **T2.8** — Source-document cross-reference (`documents/` package): ingests PDFs, runs 4 reconciliation checks (gst_amount_mismatch J+, correct_period D+, total_inconsistency J+, reg11_supplier_gst_absent J+). Born-digital path verified on seeded PDFs. **B1 attachment `/$value` byte-download UNVERIFIED** — SBODEMOSG `AttachmentsFolderPath` not configured; upload path (`UploadProvider`) is the working path. 13 AGENTASSIST_SEED docs seeded for end-to-end demo; Box 8 post-seed = 12,663.87 (DB-state-dependent).
- **T2.9** — Declared-vs-computed F5 checks (`orchestrator/check_declared_f5.py`): Check A (declared internal consistency: Box 4==1+2+3, Box 8==6−7) + Check B (declared-vs-computed per independent box, `--declared-f5` flag, off by default). Default $1.00 per-box tolerance is a **materiality floor grounded in IRAS ASK Annual Review Guide s10.1(d)(iii) fn33** — NOT a confirmed IRAS F5 filing rounding convention (the convention could not be verified against IRAS source). Findings, never verdicts; does not affect F5 boxes or gates. 19 new tests. **T2.9-V validated on demo (2026-06-10):** mechanism confirmed end-to-end (Fixtures A/B/C, 22 assertions, box-isolation held, report section renders). Rounding-convention confirmation STILL PENDING (cousin task).
- **T2.13** — Reg 26/27 validation dataset built + blank-labelled: `tests/fixtures/reg2627-representative-v1.json` + `reg2627-adversarial-v1.json`. `expected_candidate` fields are present but **empty** — labels assigned only after independent specialist review. `validation_status: unvalidated`; `show_ai_candidates` stays `False`; **T2.11 remains the binding constraint**. 92 new tests.
- **T2.10** — Listing checks (`orchestrator/check_listing.py`): SEQ_GAP (DocNum sequence-gap over sales invoices, §10.1(c)(i)) + DUP_CLAIM (duplicate input-tax claim over purchases, §10.1(d)(i)) + ZP added to `_E2_ZERO_RATE_CODES` (§10.1(d)(iv)). Two-argument company-wide SEQ_GAP semantics (period-boundary false-positive fix applied). Chain-wired after gate_5; BOX-ISOLATION invariant; findings not gates. Smoke run: SEQ_GAP=0 (sane — period-boundary fix confirmed), DUP_CLAIM=0 (NumAtCard unpopulated — INERT on SBODEMOSG). Positive-detection validated on synthetic crafted-input full-chain cases (T2.10-V): SEQ_GAP (DocNum 8002 truly-absent flagged; 8003 within-range-but-present company-wide NOT flagged) and DUP_CLAIM (7001/7002 flagged; 7003 near-miss not). Renders in signed PDF under 'Invoice Listing Completeness Checks'. Live zero-FP on SBODEMOSG Q3 2024 (1005 sales / 624 purchase headers). NOT validated on real client data. 61 new tests. Merged to master (commit `4f52b20`, merge commit `9434f00`).

- **T2.19** — Tax code normalization layer for non-SAP-B1 source systems (`normalize_vat_group()` in `sap_b1_server.py`; `tax_code_mappings`/`source_system` in `ClientConfig`; audit allow-list updated). **Merged to master** (PR #8, merge `5d91fdc`, feat `3cc379c`; originally branch `t2.2-vat-discovery`). 28 new tests in `tests/test_tax_code_normalization.py`, zero network calls, fully synthetic. SAP B1 clients unaffected (empty `tax_code_mappings` = passthrough; all baseline figures unchanged) — the layer runs in the chain but is passthrough for SBODEMOSG, so the T2.12a replay oracle (captured present-but-passthrough) is unaffected. Validated on synthetic fixtures only; not yet tested against a real non-SAP-B1 client engagement.
- **T5.1** — Engine seam (`engine/review.py`). `review(client_config, period, inputs) → ReviewResult` — full GST review pipeline as one atomic callable. `ReviewInputs` is the forward-compatible source-adapter seam (SAP wired only; deep substitution is T2.12). `ReviewResult` 11 fields incl. `analytical_review_data`. `run_agent.py` reduced to thin CLI. Import-scan gate bars `orchestrator/` from importing `engine/`. **Honest qualifier:** behavior-preserving refactor; built + unit-tested (15 new tests); NOT demo-validated end-to-end; no agent loop (T5.3); nothing customer-facing changes.
- **T5.2** — Action-tier framework + justification ledger (`agent/` cage). Tiered tool registry, heuristic justification gate, append-only hash-chained ledger, Tier-2 proposal + StagingStore, deterministic executor framework, RunBudget. **Cage built + hermetically unit-tested; NO live loop at T5.2** (seal/emit were NotImplemented stubs until T5.3 Slice 1). 133 new tests.
- **T5.3 (Slice 1 + Slice 2)** — Engine-tool plumbing + case-file loop (on master 2026-06-14). Slice 1: `agent/engine_tool.py` exposes `review()` as ONE atomic MCP tool (no sub-step reachable); MCP-prefix-aware `get_tier()`; `make_tier2_handlers` (approved-only seal/emit via `extra_handlers`); 3 new Tier-0 reads; SEALED-CHAIN routing locked (Tier-2 post-approval → sealed ledger, Tier-0 → unsealed audit_log). Slice 2: plain-Python `run_casefile_loop` gather→act→verify driver (model invoked within, never drives); CODE-DEFINED completeness checklist keyed to `CheckSpec.inputs_needed`; deterministic language-lint (brittle backstop); `DossierArtifact`; additive `compute_inputs_hash`; `cost_usd_used` → ledger COGS; budget-exceeded non-blocking; loop only stages PENDING proposals. **Built + hermetically tested (FakeTransport, no live model), NOT validated.** +21 (Slice 1) +38 (Slice 2) tests.
- **T5.7a** — Agent-behaviour eval harness (`agent/eval/`, on master 2026-06-14). `FakeTransport` (SDK-`Transport`-ABC subclass), runner over the REAL cage with a tripwire'd engine invoker, 4 cage-invariant metrics, adversarial scenario library, scorecard. **Measurement infra — gates "built → validated" for the cage invariants, NOT loop validation; loop-quality metrics deferred to T5.7b.** +33 tests.
- **T5.7b** — Loop-quality eval metrics (`agent/eval/`, on master 2026-06-14, PR #18). `ScriptedLoopTransport` (an `agent.loop.AgentTransport`, never touches the SDK) drives the REAL Slice-2 `run_casefile_loop`; two loop-quality metrics `dossier_completeness_rate` + `language_lint_pass_rate`; scorecard now **6 rows** (4 cage + 2 loop, the DEFERRED rows filled); `make_hooks` public `.audit_log` handle (runner no longer introspects `__closure__`). **Loop-quality metrics pass on SCRIPTED scenarios — NOT real-data validation; T2.11 still gates customer-facing.** +20 tests. Master total after T5.3 + T5.7a + T5.7b: **1499 passed, 1 skipped**.
- **T5.3c** — Live-model `AgentTransport` adapter (`agent/live_transport.py`, on master 2026-06-15, PR #21, commit `5cb9fd3`). `LiveAgentTransport` maps a `claude_agent_sdk.query()` stream → the loop's `AgentEvent`s (`ToolUseBlock→ToolUseEvent`, `TextBlock→FramingEvent`, `ResultMessage→ResultEvent(cost_usd=total_cost_usd)`); opt-in factory `make_live_transport` gated behind env `AGENT_LIVE_TRANSPORT`; relay-only (invoke-never-perform preserved, no new tools, no Tier-2 surface); SDK import confined + deferred to call time. **Unblocks T5.3-V** (the supervised, opt-in live run — still a separate step). **Mock-tested only (no live model/binary/tokens), NOT live-validated; T2.11 still gates customer-facing.** +14 tests. Master total after T5.3c: **1513 passed, 1 skipped**.
- **T5.3h** — Real case-file-loop `LoopContext` from the frozen extract (`agent/loop_context.py` + reusable `tests/replay_shim.py`, on master 2026-06-16, PR #35, feat `8785f92`). `build_loop_context(period, *, review_result)` assembles a REAL ctx from the frozen SBODEMOSG ground truth (A1: the offline-replayed `ReviewResult` is injected, pure assembler — no SAP/monkeypatch/SDK; vendor catalog from the S3 business-partners surface; `AbsentDocumentProvider` + empty prior-period store = honest degraded case; B1 chain-only — `reasoning_artefact`/`document_candidates` `None`). `replay_shim` is a byte-preserving extraction of the inline T2.12a fixture, so the **T2.12a byte-identity gate is intact**. **Hermetic/scripted via the byte-identity-gated offline replay — NOT live-validated (T5.3-V round-2 + T5.3g PENDING), NOT accuracy-validated; T2.11 gates customer-facing.** Surfaced the open `finding_id`-collision decision (Appendix C #33). +11 tests.
- **T5.8** — Demo showcase UI (`ui/` package, on master 2026-06-16, PR #36 feat `79e451f` + T5.8b shim PR #37 feat `0f3b20a`). Mock-first Streamlit showcase over frozen artifacts: MockEngine default / RealEngine lazy drop-in over `engine.review.review`; four views (ledger / PENDING proposals / executor dispatch / adjudication); `sign.py` renders the working paper via the EXISTING `report.build_report`→`render_pdf` path with **`show_ai_candidates` RESPECTED** (default False) and no secrets; pure view-models with frozen `VALIDATION_STATUS="unvalidated"`; T5.8b `sys.path` shim makes `streamlit run ui/app.py` work from a fresh checkout. Mock+Sign path imports no `anthropic`/SDK/`agent.loop` (guard-tested). **Built ≠ demo-validated — mock-first, showcase-not-product, GATED; T2.11 still gates customer-facing.** **T5.8c** (branch `t5.8c-demo-loopcontext-converge`, 2026-06-16) converged the demo freezer onto the T5.3h `build_vendor_catalog` so it renders **real frozen-extract-derived vendor ctx** (not the hardcoded placeholder); hermetic, MockEngine/RealEngine boundary untouched, frozen flags + token-gating intact, +2 tests. Master total after T5.3h + T5.8 + T5.8c (full-suite recount): **1641 passed, 1 skipped**.

**Validated offline (deterministic chain) — on master:**
- **T2.12a** — Ground-truth capture + offline-replay gate. Six SBODEMOSG read surfaces (S0–S5) frozen verbatim under `tests/fixtures/sbodemosg-extract/` + same-session `_replay-oracle.compiled.json` + `capture-manifest.json` (per-fixture SHA-256 + `source_function`); EOL pinned (`.gitattributes eol=lf`); hermetic integrity test (capture `63bf32d`/`0084031`). **Offline-replay gate PASSED** (`b61f219`): `run_chain` off the frozen fixtures with SAP unreachable == the oracle byte-for-byte via `canonical_json`, so `rederivation_grade: "same-SAP-state"` is achieved offline for the deterministic path. **Honest:** proves freeze-sufficiency + offline reproducibility ONLY — NOT accuracy (T2.11), NOT the Excel adapter (T2.12); **S4 (reasoning-pass surface) out of scope** (frozen, not replay-validated); test harness, not the product adapter (`orchestrator/` untouched). This is the **validation substrate** — SOP step 2 live-recon → fixture recon, step 5 seed-live/chain-acceptance → offline-replay acceptance (PDF-render retained); **B1 expendable for the deterministic path**. Honest-status ladder: built ≠ hermetic ≠ offline-replay-validated ≠ adapter-round-trip-validated-on-synthetic ≠ real-client-export-validated ≠ accuracy-validated (T2.11). See T2.12a entry.
- **T5.7c (ledger-name parity)** — agent test fakes normalized to namespaced `mcp__reads__<tool>` ledger names matching the live loop (anchored to round-2 evidence cross-checked against `READ_TOOLS_QUALIFIED`); slot lookups still resolve on the bare name, so the T5.3g slot binding is byte-unchanged. On master 2026-06-16 (branch `t5.7b-ledger-name-parity`, PR #32, `67c8f09`); +5 tests; hermetic. (The `t5.7b-` branch label collides with the earlier loop-quality **T5.7b**/#18; tracked here as **T5.7c** to keep the labels distinct.)
- **T2.23 (chain source seam)** — per-surface injectable `ChainReader` read provider for `run_chain`'s raw SAP reads (S0/S1/S2/S3/S5); `SapChainReader` default wraps the existing fetch primitives **verbatim** (behaviour-preserving — a wrapper, not a rewrite), `reader=` threaded through `run_chain` + the three MCP tool fns (`calculate_f5_return`/`validate_invoice_tax_codes`/`detect_gst_errors`). On master 2026-06-16 (branch `t2.23-chain-source-seam`, PR #39, merge commit `5c48ccb`). The Surface-B counterpart to T5.1's `line_source`, one layer down — the dependency that lets **T2.12 become a clean adapter against a seam** rather than a rewrite of the deterministic backbone. **Offline-replay-validated:** `tests/test_t2_12a_offline_replay.py` rewired to inject a `FrozenExtractReader` through the public seam param, `run_chain` off the frozen extract == oracle byte-for-byte (`canonical_json`); `test_seam_param_is_load_bearing` proves every surface routes through the injected reader. The `@odata.count` Gate-1 dormancy (backlog #5) is **preserved verbatim, not fixed**; BOX-ISOLATION intact; **T2.11 still gates customer-facing**. See T2.23 entry.

**Extract pivot — decided + in progress (NOT complete):** the strategic decision to move primary ingestion to client Excel/CSV extracts is **made**, with **T2.12 (the Excel/CSV adapter) as the next build**. The engine seam (T5.1) + the offline-replay harness (T2.12a) are evidence the path is viable. This is **not** a flip of the roadmap to Excel-primary — T2.12 is not built and the deterministic path still runs on the MCP connector / frozen fixtures. See T2.12 / T2.12a.

**Remaining gates to a paid pilot (none are correctness or delivery-format gaps):** production-data trust, PDPA compliance, security history scrub.

---

## Tier 1 — Required Before First Paying Customer — ALL DONE

| Task | Effort | Owner | Status |
|------|--------|-------|--------|
| T1.1 Credit note support across all three tools | ~1 wk | Collin | DONE |
| T1.2 NR VatGroup resolution (4-artefact consistency) | — | Terry (verify) | DONE |
| T1.3 Per-client configuration model (`ClientConfig`, YAML) | 1.5–2 wk | Terry | DONE |
| T1.6 Orchestration chain + 5 deterministic gates | 1.5–2 wk | Terry | DONE |
| T1.4 Signed PDF report generation | 2.5–3 wk | Terry | DONE |
| T1.5 Audit trail + input immutability (sealed bundle) | 1.5–2 wk | Collin | DONE |

The chain is the defensibility backbone: a fixed, auditable sequence with deterministic gates that halt rather than emit a confident wrong result. The report projects the chain's gated output; the audit bundle captures gate results so the trail shows reconciliation passed before the report was produced.

---

## Tier 2 — Required Before Scaling Beyond Initial Pilot

Non-blocking for the first 1–2 friendly pilots; real problems at 5+ clients or formal contracts.

### T2.1 — Manual journal entry support — PLANNED
Effort 1–1.5 wk. Owner Collin. Add `JournalEntries` queries; filter GST-relevant accounts via per-client `gst_accounts` config; per-line classification where account context is GST-input/output. Hardest part: identifying GST-relevant journal lines (inferred from GL account). Out of scope: adjusting journals that re-classify GST across boxes.

### T2.2 — Custom VatGroup discovery and reporting — PLANNED (sequenced behind T2.20)
Effort 1 wk. Owner Collin. Enumerate the VatGroup codes actually present in the client's transaction data, classify against the 18-code standard set, and surface unknowns with sample DocNums/counterparties — the independent completeness check that catches codes the client forgot or never declared. The enumeration produces a client-confirmation worksheet; the client declares the intended treatment of each custom/unknown code; those client-declared treatments persist to per-client config. Treatment is CLIENT-DECLARED, not auto-classified — intended treatment of a custom code cannot be inferred from data (self-report is authoritative for treatment; enumeration is authoritative for completeness). Thin slice of the future T2.12 normalization adapter.

**Sequencing note (T2.20, 2026-06-12; updated 2026-06-15):** this entry's
"18-code standard set" is the pre-Annex-E vocabulary. T2.20's discovery audit
(`exploration-notes/t2.20/vocabulary-migration-inventory.md`) found that 20 of
the 35 IRAS Annex E GST Category Codes either have no equivalent in the
18-code set or collide with an existing code under a different meaning. T2.21
buckets 1+2 (the `SO`→`SR`/`SI`→`TX` renames + 14 direct carryovers — 16 of 35
codes) are DONE (commit `21c70e9`, branch `t2.21a-annex-e-baseline-vocab`, not
yet merged — see T2.21 entry below), but T2.21's remaining buckets 3+4+8 (8
codes) are blocked on T2.18 with no scheduled follow-on. Do not scope T2.2
against "the 18-code standard set" until T2.21's full scope has landed or the
remainder has been explicitly deferred — otherwise T2.2's classification step
will need rework against whatever vocabulary the remaining buckets produce.

### T2.3 — Automated evaluation harness — PLANNED (durability mechanism for the headline reliability claim)
Effort 2–3 wk. Owner Terry. Given stored prompt + reference output, invoke the Claude API directly, capture response, compute a scoring vector; run as CI on every meaningful change. Scoring uses structural checks, not text comparison. Protects the 30/30 across model upgrades and prompt/KB edits. T2.11 builds on it for the reasoning-layer basket.

### T2.4 — Hardened error handling and retry logic — PLANNED
Effort 1–2 wk. Owner Collin/Terry. Exponential backoff on 503/timeout; pagination resumption from `$skip`; session re-auth on 401 mid-pagination; partial-data detection via `$inlinecount`; entity-named error messages.

### T2.5 — FX conversion (box-level SGD equivalent) — PLANNED
Effort 1.5–2 wk. Owner Terry. `convert_fx_to_sgd` reading SAP's rate table or a configured source; add converted values to boxes; disclose the rate source. Hardest part: methodology (IRAS supply-date rate vs client month-end) captured in config. Until then FX stays excluded and listed for manual conversion.

### T2.6 — Multi-quarter / rolling-period analysis — PLANNED
Effort 1 wk. Owner Collin. Tools accept arbitrary date ranges; reports adapt to period summaries.

### T2.7 — Client business-context profile (reasoning-layer surfacing aid) — PLANNED
Effort 1.5–2 wk (builds on T1.3 + T2.2). Owner Terry. Extend `ClientConfig` with a structured `business_context` block; the reasoning step receives only its relevant slice and uses it to weight/annotate candidates — never to compute box figures. Feeds Layer 2 only.

Design constraints (non-negotiable): inform, never auto-bless; surfaces, never asserts — even with context (caps at J+); profile is reference data, not arithmetic (never enters tools/boxes/gates; `orchestrator/` stays pure-Python and context-free); profile provenance is auditable. Re-triggers the V0→V3 loop. DoD includes a blind-spot test (seed a miscoded transaction matching a profile expectation; confirm it is still surfaced), a confidence-inflation test (no verdict asserted regardless of profile strength), and byte-identical box figures with/without the profile.

> Distinction: T2.7 improves candidate quality from the line-item data Layer 2 already sees. It does NOT give Layer 2 new inputs. The document adapter (T2.8) is what gives Layer 2 inputs it is currently blind to. Complementary.

### T2.8 — Source / document-ingestion adapter — DONE (built, flag-gated, unvalidated; B1 attachment byte-download UNVERIFIED; upload path working)
Completed 2026-06-08 on branch `t2.8-document-ingestion`. Owner Terry.

Business reason: the entire 👤 → J+ band in coverage-analysis Document 4 is blocked by input availability. Today the system sees SAP line items only. An adapter that ingests source documents (tax-invoice PDFs, transport/export docs, import permits — via `Attachments2` or manual upload) lets Layer 2 surface cross-reference candidates it is currently blind to: listing-vs-source amount agreement (3A.3.1, 3D.3 B5), Reg 11 validity (3D.3 B1), export-evidence presence (3B.3.2), permit-under-business-name (3E), correct-period (3D.3 B6 → firms to D+).

**What was built (2026-06-08):**
- `documents/` package: `ingest.py` (born-digital pdfplumber + multimodal Claude fallback), `reconcile.py` (4 checks: gst_amount_mismatch J+, correct_period D+, total_inconsistency J+, reg11_supplier_gst_absent J+), `doc_pass.py` (SI line iterator), `provider.py` (DocumentProvider protocol + 4 implementations).
- `UnifiedCandidatesSection` in `report/sections.py` — merges T2.7 reasoning candidates and T2.8 document candidates with mandatory per-row `basis` tag; gated by `show_ai_candidates` (default False).
- `--upload-dir` and `--show-ai-candidates` CLI flags in `run_agent.py`.
- 13 AGENTASSIST_SEED docs (DocNums 612–624) on vendor V21000 (Sea Corp) for end-to-end demo; `scripts/seed_manifest.json` as seed identity record.
- **1161 passed, 1 skipped** (T2.7 +434 vs T1.5; T2.8 +312; T2.9 +19 in `test_check_declared_f5.py`; T2.13 +92 in `test_t2_13_fixture_schema.py`; T2.10 +61 in `test_check_listing.py`; T2.9-V +17 in `tests/test_declared_f5_section.py`; T2.10-V +52: 31 hermetic + 21 crafted-chain; Check A float-robustness +5 `[A-FP]` in `test_check_declared_f5.py`).

**Caveats and open items:**
- `B1AttachmentProvider` metadata chain verified; `/$value` byte-download UNVERIFIED (SBODEMOSG `AttachmentsFolderPath` not configured). Provider is correct-by-construction, not live-proven. Upload path (`UploadProvider`) is the working path.
- AGENTASSIST_SEED Remarks marker does not persist on read-back — seed identity depends on `seed_manifest.json`; cleanup must be by DocEntry.
- Isolation invariant confirmed: box figures and gates are byte-identical with and without `--show-ai-candidates`.
- Plumbing demonstrated on seeded data only; `validation_status: unvalidated`; `show_ai_candidates` stays False for deliverables pending T2.11.
- Document legibility/confidence gate not yet built — see T2.14.

> Note: SBODEMOSG carries **no** real attachments. The `Attachments2` path is supported by the code but returns None on SBODEMOSG; real pilot testing requires a SAP B1 instance with `AttachmentsFolderPath` configured and at least one purchase invoice with a PDF attachment.

Why it caps at J+: extraction is probabilistic — reading raises recall, not authority. The sole exception is invoice-date → correct-period (B6 → D+). Legal characterisations (export, exemption, Reg 26/27) stay J+ regardless. Extracted values never enter Layer 1, boxes, or gates; the deterministic listing stays the authoritative anchor. DoD achieved: byte-identical box figures/gate results with and without the adapter confirmed on SBODEMOSG Q3 2024 + T2.8 seeds.

### T2.9 — Filed-F5-return ingestion (declared-vs-computed reconciliation) — DONE (built, flag-gated, UNVALIDATED)
Completed 2026-06-09 on `master`. Owner Terry.

**What was built:** `orchestrator/check_declared_f5.py` — two deterministic checks:
- **Check A** (declared internal consistency): Box 4 == Box 1+Box 2+Box 3; Box 8 == Box 6−Box 7. Inconsistency surfaces as a finding; run always completes and seals normally.
- **Check B** (declared-vs-computed per independent box): Compares the client's declared figures (from a `declared-f5.json` input file) to the chain's computed figures on each of the six independent boxes (Box 1, 2, 3, 5, 6, 7). Box 4 and Box 8 are derived consequence notes, not primary flagged items (avoids double-counting accumulated rounding).

**`--declared-f5 <path>` CLI flag** in `run_agent.py` supplies the declared input file. Off by default (flag-gated); when absent, the chain result is unchanged.

**Honest qualifier:** DONE = built on master, deterministic, unit-tested. **UNVALIDATED end-to-end** — the F5-box filing rounding convention could NOT be verified against IRAS source, so the $1.00 per-box default tolerance is a **materiality floor** (grounded in IRAS ASK Annual Review Guide s10.1(d)(iii) fn33, which explicitly excludes "rounding differences" from the declared-vs-computed indicator), not a confirmed IRAS F5 filing rounding convention. Findings, never verdicts; surfaces, never asserts; does not affect F5 boxes, gates, or `validation_status`.

**19 new tests** in `tests/test_check_declared_f5.py` (isolation invariant, Check A/B, tolerance boundary, load validation). Partially closes the recurring ◐ across Steps 1, 3A.1.a, 3B.1.a, 3C.1.a, 3D.1.1.a — but validation against real filed-return data has not occurred.

**Check A float-robustness (commit 40c9024, 2026-06-10):** Original Check A equality comparisons used exact float equality; IEEE-754 artefacts (e.g. `0.1+0.2 ≠ 0.30` in float) could produce false positives when values were to-the-cent consistent. Fix: `_quantize_cent()` converts operands to `Decimal` via `ROUND_HALF_UP`; values equal iff they agree at the cent; off-by-one-cent still flags; Check B and $1.00 tolerance untouched. 5 new `[A-FP]` tests. This fixes our internal arithmetic only — it does NOT confirm the IRAS F5 filing rounding convention (cousin task, still open; coverage cells stay ◐). Suite total: **1161 passed, 1 skipped**.

### T2.9-V — Declared-vs-computed validation — DONE (mechanism validated on demo; rounding-convention confirmation STILL PENDING)
Completed 2026-06-10 on `master` (merge commit `0741dab`). Owner Terry. **NOT the binding constraint** — T2.11 (reasoning layer) remains that; T2.9-V is independent of it.

**(a) Scenario test — DONE:** Three isolated `declared-f5.json` fixtures run against the live chain on SBODEMOSG Q3 2024. Fixture A (Check A isolation: Box 4 identity violated +$100, independent boxes within tolerance) → 1 Check A finding on Box 4. Fixture B (Check B isolation: Box 1 over-declared +$5,000, internally consistent) → 1 Check B primary (Box 1, delta=+5000.03, direction=over_declared) + 1 derived consequence (Box 4). Fixture C (control: all declared within $1.00 of computed) → 0 findings (false-positive check). 22 assertions verified: correct finding types, box-isolation held (computed boxes byte-identical to baseline for all three runs), gate `all_passed` unchanged, `render_declared_f5_section` correct in both states, Section 6 suppression correct. Report section delivers Check A/B findings in PDF and text; Section 6 "Not Examined" retains the placeholder when `--declared-f5` absent — correct behaviour (no filed return to compare against by default).

**(b) Rounding-convention confirmation — STILL PENDING:** Whether F5 boxes are filed whole-dollar or to the cent has not been confirmed against IRAS source. The $1.00 default tolerance remains a materiality floor per ASK Guide s10.1(d)(iii) fn33 — NOT a confirmed IRAS convention. This is the one remaining external dependency — a cousin task.

**DoD achieved (partial):** Scenario test passes (seeded divergences surfaced, zero clean-box false positives); report section renders; 17 new hermetic tests in `tests/test_declared_f5_section.py`. **DoD NOT YET achieved:** rounding convention documented with its source — coverage cells stay ◐, not unconditionally covered.

### T2.10 — Listing checks: SEQ_GAP + DUP_CLAIM + ZP E2 extension — DONE (built, positive-detection validated on synthetic cases via T2.10-V, report-rendered; merged to master 2026-06-10)
Completed 2026-06-09/10. Owner Terry. Merged to master, commit `4f52b20`, merge commit `9434f00`.

**What was built:**
- **SEQ_GAP** (`orchestrator/check_listing.py` → `detect_seq_gaps(period_records, all_records)`): DocNum sequence-gap detection over sales invoices. Two-argument API with company-wide existence semantics — a DocNum is a gap only if absent from ALL company records (all periods, all statuses) AND within the reviewed-period active range. Period-boundary false-positive fix: the initial algorithm would have flagged ~617 DocNums (357–956) on SBODEMOSG Q3 2024 that exist in earlier periods; corrected by fetching the full company-wide document set. Groups by SAP `Series` integer. IRAS basis: §10.1(c)(i).
- **DUP_CLAIM** (`orchestrator/check_listing.py` → `detect_dup_claims(records)`): Duplicate input-tax claim detection over purchase invoices. Key = `(CardCode, NumAtCard, DocTotal)`; blank `NumAtCard` excluded. **INERT on SBODEMOSG** — `NumAtCard` is 0% populated (all null). Built + unit-tested; requires client AP operators to populate vendor invoice reference. **Client-onboarding data-quality precondition.** IRAS basis: §10.1(d)(i).
- **ZP E2 extension**: `"ZP"` added to `_E2_ZERO_RATE_CODES` in `mcp-servers/custom/sap_b1_server.py` and `E2_ZERO_RATE_CODES` in `scripts/run_baseline_tests.py`. DocNum 610 (ZP, LineTotal=1,200.00, TaxTotal=84.00, DocTotal=1,284.00) is the confirmed SBODEMOSG fixture — now correctly flagged as E2. IRAS basis: §10.1(d)(iv). Resolves open item #22 from Appendix C.
- **Chain wiring**: `fetch_listing_data` + `detect_seq_gaps` + `detect_dup_claims` after gate_5 in `orchestrator/chain.py`. Results in `CompileOutput.listing_findings`. BOX-ISOLATION runtime assertion (snapshots boxes before, asserts equal after; RuntimeError on mutation). Non-halting — exceptions suppress findings.
- **AUDIT-NOT-PARTNER**: `orchestrator/check_listing.py` and `scripts/check_listing_reference.py` share zero functions; agreement verified by agreement test classes.
- **`page_size=20` workaround**: SAP B1 server-side page cap; follow-on is @odata.nextLink cursor pagination.
- **61 new tests** in `tests/test_check_listing.py` + `tests/conftest.py` (dummy creds for hermetic import).

**Honest qualifier:** DONE = merged to master, deterministic, unit-tested. **Positive-detection validated on SYNTHETIC crafted cases (T2.10-V); report-rendered; live zero-FP on SBODEMOSG.** SBODEMOSG is a demo/synthetic DB — NOT real-client validation. DUP_CLAIM inert where `NumAtCard` unpopulated (client-onboarding precondition). Findings not gates; does not affect `validation_status` or `show_ai_candidates`.

**Not built in T2.10 (deferred):** claim-outside-period (3D.1.1.c → D+, needs cross-period history); time-of-supply anomaly (3A.1.b → J+, needs payment-date ingestion); purchase-side SEQ_GAP (separate scope decision); @odata.nextLink pagination.

### T2.10-V — Listing-checks positive-detection validation — DONE (positive-detection validated on synthetic cases; live zero-FP on SBODEMOSG; NOT real-client validated)
Completed 2026-06-10. Owner Terry. Merged to master, commit `bf7f2f3`, merge commit `037c271`.

**(a) SEQ_GAP positive-detection — DONE:** Crafted-input full-chain test (`tests/test_t210_crafted_chain.py`). `fetch_listing_data` patched; real `detect_seq_gaps` exercised. DocNum 8002 (truly absent company-wide within active range [8001,8004]) → **FLAGGED**. DocNum 8003 (within range, present in `all_records` as other-period slot — the period-boundary discriminating case) → **NOT flagged**. Zero false positives confirmed on SBODEMOSG live Q3 2024 FP check (1005 company-wide sales headers).

**(b) DUP_CLAIM positive-detection — DONE:** Crafted-input full-chain test. DocNums 7001+7002 (same CardCode + NumAtCard + DocTotal) → **FLAGGED**. DocNum 7003 (same CardCode + DocTotal, different NumAtCard — near-miss) → **NOT flagged**. Note: live positive detection not possible on SBODEMOSG because `NumAtCard` is 0% populated; positive-detection path exercised via crafted `period_purch_headers` payload.

**(c) PDF report section — DONE:** `ListingFindingsSection` dataclass + `render_listing_findings_section` in `report/sections.py`; `_listing_findings` renderer in `report/render.py`; `listing_findings` field in `ReportModel`. Section renders only when findings present; Not-Examined items suppressed independently. Both T2.9 (`declared_f5`) and T2.10 (`listing_findings`) sections coexist in one PDF. **PDF section heading renamed to "Invoice Listing Completeness Checks"** (commit 958ed3d — internal task ID removed from client-facing PDF; no functional change).

**Honest qualifier:** SBODEMOSG is a demo/synthetic database — NOT real-client validation. SEQ_GAP cannot be seeded live (SAP B1 assigns DocNums sequentially). DUP_CLAIM stays inert where `NumAtCard` is unpopulated (client-onboarding precondition). `page_size=20` pagination confirmed working at scale; @odata.nextLink remains the robustness follow-on. `validation_status` and `show_ai_candidates` unchanged.

**52 new tests.** Master total after T2.10-V merge: **1156 passed, 1 skipped**.

### T2.11 — Reasoning-layer validation + indeterminate-queue reconciliation — PROVISIONAL → validate (the binding constraint)
Effort PROPOSED 2–3 wk engineering + specialist review time. Owner Terry (harness) + independent specialist (async reconciliation).

The reasoning layer is built and provisionally measured but unvalidated; the 2026-06-03 numbers are against an Opus-labelled fixture, so they are a smoke test, not validation. `show_ai_candidates` stays `False` for deliverables and `validation_status` stays `unvalidated` until an independent GST specialist reconciles the candidate queue. This calendar-gated review — not further build — is the binding constraint.

Scope: extend the T2.3 harness to compute the accuracy basket against T2.13's labelled set — FP (<5%), recall (>95%), severity calibration (>90% agreement), engineering reliability — tracked separately, never as one number; assemble the indeterminate/contested queue for review; on reconciliation, update `validation_status` and decide `show_ai_candidates` per client. Hardest part: keep validation independent from rule-authoring (the labeller of the validation-of-record must not be a rule author — circular validation; agreement ≠ correctness). DoD: measured basket; reconciled queue; auditable `show_ai_candidates` decision; canonical doc updated.

> Inspection vs validation: inspecting raw reasoning output in a dev/scratch run is fine (pre-validation). What stays gated is letting candidates into a signed working paper or describing them as validated. Looking ≠ blessing. Inspection artefacts marked `UNVALIDATED / DRAFT`.

### T2.12 — Extract-based delivery adapter (advisory-firm channel) — PLANNED (NEXT BUILD; extract pivot decided + in progress)
Effort PROPOSED 3–4 wk. Owner Terry/Collin. Advisory firms access client data via extracts, not live B1. Add an input adapter mapping CSV/Excel (later PINT-SG) to the same internal line-item schema so the chain/gates/report run unchanged. The MCP connector becomes one input adapter among several. DoD: a CSV extract produces identical chain output to the equivalent MCP run on the same data. **This refactor (decoupling input adapter from engine behind a stable schema/API) is also the architectural prerequisite for any future platform — see Tier 4.** The stable `review(client, period, inputs) → ReviewResult` interface produced by this refactor is also the seam consumed by the Tier 5 agent shell (T5.1).

**Dependency satisfied (T2.23, 2026-06-16):** the Surface-B chain source seam (`ChainReader` / `run_chain(reader=...)`) is built and offline-replay-validated, so T2.12 now binds to an **injectable per-surface read provider** rather than rewriting `run_chain`. T2.12's job narrows to a `ChainReader` implementation that maps a CSV/Excel extract to the five surfaces, plus the Surface-B field-absence decisions (NumAtCard / FederalTaxID / Series / company-wide coverage) that T2.23 explicitly deferred here.

**Extract-pivot status (2026-06-16): decided + in progress — NOT complete.** The strategic decision to move **primary ingestion to client Excel/CSV extracts** is made, and T2.12 is the **next build**. Evidence the path is viable: the engine seam (T5.1, `review()` over `ReviewInputs`), the Surface-B chain source seam (**T2.23**, `run_chain(reader=...)`), and the **offline-replay harness (T2.12a)** — which already proves the deterministic chain re-derives byte-for-byte from frozen extract surfaces with no live B1. **This does NOT flip the roadmap to Excel-primary**: T2.12 is unbuilt; the deterministic path still runs on the MCP connector (and, for acceptance, the frozen `sbodemosg-extract` fixtures). **DoD extension (carried from T2.12a's validation-substrate work):** the offline-replay shim is the **reusable acceptance mechanism**, so T2.12's acceptance is the round-trip `adapter(synthetic-export) == frozen fixtures`. That round-trip carries a **format-assumption gap** — the synthetic export is our guess at the client's column shape — which closes only when a **real client export** is obtained. The gap is **GTM-gated, not infra-gated**.

**Slice A status (2026-06-17, branch `t2.12a-extract-feeder`, PR pending — NOT merged): BUILT, synthetic-format-validated.** The feeder + its parse proof landed: `feeders/ExtractChainReader` — a `ChainReader` that satisfies the T2.23 seam **structurally** (duck-typed; neither imports nor widens the Protocol) and reads a client Excel/CSV GST export into the same five shaped surfaces the live `SapChainReader` emits. One machine, two feeders: normalise AT THE FEEDER, hand off to the unchanged checking core; tax codes still flow through `normalize_vat_group` (T2.19), never re-implemented. Built: a single `feeders/extract_schema.py` column⇄field source of truth; a synthetic exporter (`tests/synth_extract_export.py`) that writes the frozen ground truth into this slice's *guessed* client column shape (a combined sales/purchase × invoice/credit-note transaction register + BP master + document-number listing) as LF-pinned CSV (and `.xlsx`); a round-trip asserting `ExtractChainReader(synthetic-export) == frozen S1/S2/S3/S5` **field-for-field** over the canonical projection; a coverage-declaration seam (`coverage()` **beside** the Protocol — NOT a widening) proving full coverage on a complete export; +19 tests (branch full suite **1826 passed, 1 skipped**, zero regression; offline-replay still byte-identical to oracle; PDF-render retained). **The count trap:** `ExtractChainReader.count()` returns the export's **true** row count (50/34/1/1 documents), unit-tested against the known count — deliberately NOT asserted against the frozen S0 / oracle (which encode the dormant `@odata.count` → None; that comparison stays gated on the re-freeze — backlog #5 untouched). **Module placement decision:** a new top-level **leaf** package `feeders/` (not `orchestrator/`, not in `sap_b1_server.py`) — pure stdlib (+ lazy `openpyxl` on the `.xlsx` path), imports nothing upward, injected-only; recorded in `docs/merge-gates.md`. **Honest-status ladder position:** built + adapter-round-trip-validated-on-synthetic — **NOT real-client-export-validated** (the format-assumption gap: the export columns are our guess, GTM-gated on a real client export), **NOT accuracy-validated** (T2.11 still gates). Deferred to slice 2B: the coverage→check-status mapping, the three field-absence/degradation cases, and the working-paper coverage flow. Adapter-vs-oracle byte-identity (full `run_chain` over the feeder) remains gated on the `@odata.count` re-freeze.

**Follow-up — Gap A closed (2026-06-17, branch `t2.12a-doctotal-gap`):** a projection-completeness recon on merged master found the doc-level `DocTotal` silently dropped — `calculate_f5_return` reads `doc.get("DocTotal")` for the `fx_invoices_requiring_conversion` advisory list, but `project_document`/`DOCUMENT_COLUMNS` never carried it, so a feeder-fed run reported `0.00` for those FX totals (live = 10 FX docs in the frozen extract, so **live not latent**; the symmetric-projector round-trip couldn't see it). **Bound:** advisory FX figure only — feeds no F5 box and no finding; box math + all findings + oracle byte-identity unaffected. Fix: added `DocTotal` to `DOCUMENT_COLUMNS` + `project_document` (float-coerced), mirrored in `extract_reader._build_documents`, emitted from the synthetic exporter (frozen-sourced), fixture regenerated; failing-test-first with an **independent-value** assertion (FX doc 958 = `1131.53`) that breaks projector symmetry. Honest-status unchanged (still synthetic-format-validated). The **durable** closure — a feeder-vs-oracle FX-list byte-identity check — stays gated on the `@odata.count` re-freeze. The per-doc-vs-listing `DocTotal` coverage-seam distinction is a **2B** concern (`COVERAGE_FIELDS` is keyed by field name; left untouched).

### T2.12a — Ground-truth capture + offline-replay gate — DONE (2026-06-16; on master)
Owner Terry. **Frozen ground truth + a passing offline-replay gate for the deterministic chain** — the validation substrate for the deterministic path, distinct from (and a prerequisite-grade input to) the T2.12 product adapter.

**Capture (`63bf32d` + LF/manifest pin `0084031`):** the six SBODEMOSG read surfaces the chain consumes (S0–S5) are frozen verbatim under `tests/fixtures/sbodemosg-extract/` — `invoices.raw.json` (50), `purchase-invoices.raw.json` (34), `credit-notes.raw.json` (1), `purchase-credit-notes.raw.json` (1), `business-partners.raw.json` (9), `si-purchase-lines.json` (61), `listing-headers.json` (50/34 period + 1005/624 company-wide), `inline-counts.json` — plus the same-session `_replay-oracle.compiled.json` and `capture-manifest.json` (per-fixture SHA-256 + `source_function` provenance). EOL pinned (`.gitattributes eol=lf`) for cross-platform SHA stability; hermetic integrity test. **SBODEMOSG is demo/synthetic data — no PDPA; fixtures committable.**

**Offline-replay gate PASSED (`b61f219`):** `tests/test_t2_12a_offline_replay.py` runs `run_chain` off the frozen fixtures with **SAP physically unreachable** (a tripwire fails the test on any real SAP contact) and asserts **byte-identical** to the oracle via `canonical_json`. Proves (a) the freeze is sufficient and (b) the chain is reproducible offline; `rederivation_grade: "same-SAP-state"` is achieved offline for the deterministic chain.

**Honest caveats:** freeze-sufficiency + offline reproducibility **only** — NOT accuracy-validated (T2.11), NOT the Excel adapter (T2.12); **S4 (reasoning-pass surface) was OUT OF SCOPE** — frozen but not replay-validated, because `run_chain` does not read it; it is a **test harness, not the product adapter** (`orchestrator/` untouched). **T2.19 provenance:** the oracle was captured with the tax-code normalization layer **present-but-passthrough** (empty `tax_code_mappings` for SBODEMOSG), so the oracle is unaffected.

**Methodology (validation-substrate shift):** SOP **step 2 "live recon" → fixture recon**; SOP **step 5 "seed live SBODEMOSG / chain acceptance" → offline-replay acceptance** (PDF-render check retained); **B1 is expendable for the deterministic path**. Honest-status ladder: built ≠ hermetic ≠ offline-replay-validated ≠ adapter-round-trip-validated-on-synthetic ≠ real-client-export-validated ≠ accuracy-validated (T2.11).

### T2.23 — Chain source seam (per-surface injectable read provider) — DONE (2026-06-16; merged to master, PR #39, merge commit `5c48ccb`)
Owner Collin. The Surface-B counterpart to T5.1's `line_source` seam, **one layer down**: an injectable per-surface read provider for `run_chain`'s raw SAP reads, defaulting to the current SAP implementation, **changing no behaviour**. This is the dependency that lets **T2.12 become a clean adapter against a seam** rather than a rewrite of the deterministic backbone. (T5.1's `line_source` only feeds Surface A — the reduced 9-key line-dict for the Reg 26/27 + documents passes; `run_chain` reads Surface B — the full raw S1/S2/S3/S5 payload — which T2.23 now makes injectable.)

**The seam (`ChainReader` Protocol, in `mcp-servers/custom/sap_b1_server.py`):** one method per recon read surface, returning already-shaped record lists (the OData wire shape stays inside the default impl — what B2 altitude buys T2.12):
- `count(entity, start, end)` — S0 record-count probe (Gate 1)
- `fetch_invoices(entity, start, end)` — S1 full line-level documents
- `fetch_credit_notes(entity_type, start, end)` — S2 credit notes (tags `is_credit_note=True`)
- `get_business_partner(card_code)` — S3 BusinessPartner master (`FederalTaxID` → NO_GST_REG)
- `fetch_listing(period)` — S5 four header-only listing queries (period + company-wide)

`SapChainReader` is the default implementation, wrapping the existing fetch primitives **verbatim** (a wrapper, not a rewrite); `_fetch_headers_paginated` relocated from `orchestrator/steps.py` to sit next to the other primitives. The type lives in `sap_b1_server.py` (**top-level, NOT `engine/`**) so the `engine/ → orchestrator/` import direction holds and the MCP tool functions can default-construct it with no circular import.

**DI wiring (param-threading; NO module-global swap):** `reader=None` added to `run_chain` and to the three tool functions `calculate_f5_return` / `validate_invoice_tax_codes` / `detect_gst_errors` (`None → SapChainReader()`). The `reader` param on the `@mcp.tool` functions is left **untyped** — a `ChainReader`-typed annotation breaks FastMCP/pydantic JSON-schema generation at tool registration; it is internal DI never set by MCP/agent callers (the agent connects to its own read-tools/engine servers, not these). When a reader is injected `run_chain` threads the one instance through every surface; on the default path each step constructs its own stateless reader. The four step functions patched by `test_chain.py` keep their `(client_config, period)` call shape (reader passed only when injected), so step-level tests pass **unchanged**.

**Byte-identity (DoD spine):** `tests/test_t2_12a_offline_replay.py` rewired to inject a `FrozenExtractReader` through the **public seam param** (no more monkeypatching `_fetch_*`/`SAPB1Client.get` internals; only the no-contact guards + `_FrozenClock` remain patched, in `tests/replay_shim.py`); `run_chain` off the frozen extract == `_replay-oracle.compiled.json` byte-for-byte (`canonical_json`), SAP unreachable. `test_seam_param_is_load_bearing` proves every surface routes through the injected reader. A genuinely **stronger rung than T5.1** reached, because the frozen Surface-B fixtures + oracle now exist (T2.12a). The per-call-freshness hazard (`is_credit_note` leak) is designed out: both `SapChainReader` (fresh HTTP payload per call) and `FrozenExtractReader` (deepcopy-per-call) return fresh objects.

**Scope/honest:** behaviour-preserving refactor; no extract/CSV logic, no new source adapter, no check-disabling, **no Surface-B field-absence decision** (NumAtCard/FederalTaxID/Series/company-wide coverage all remain T2.12); the `@odata.count` dormancy (backlog #5) is **preserved verbatim, not fixed**. `config/loader.py` and `check_listing_reference.py` untouched; BOX-ISOLATION intact (boxes sit above the seam). Nothing customer-facing moves (**T2.11 still gates**).

### T2.13 — Validation dataset construction (synthetic-paired + pilot-derived) — DONE (dataset built, blank-labelled; NOT validated)
Completed 2026-06-09 on `master`. Owner Terry (build) + independent specialist (labels — pending).

**CRITICAL framing (mandatory):** T2.13 DONE means the validation DATASET is BUILT and BLANK-LABELLED only. `expected_candidate` fields are present in both fixture files but **empty** — labels will be assigned only after an independent GST specialist reviews each case against IRAS sources. This does NOT mean:
- Any specialist has reviewed or assigned labels
- `validation_status` has changed — it stays `"unvalidated"`
- T2.11 (independent specialist reconciliation) is complete — **it is not; T2.11 is the binding constraint**
- `show_ai_candidates` may be set to `true` in any client YAML

**What was built:**
- `tests/fixtures/reg2627-representative-v1.json` — representative validation fixture (stratified Reg 26/27 cases covering all six §6.1.6 categories)
- `tests/fixtures/reg2627-adversarial-v1.json` — adversarial validation fixture (edge cases, near-misses, ambiguous descriptions)
- `tests/fixtures/SCHEMA-reg2627-v1.md` — fixture schema documentation
- `tests/fixtures/export_specialist_copy.py` — specialist-export script; strips `resolution_hint` field so the labeller receives only the case, not the model's suggestion (strip guard — ensures independent labelling)
- `exploration-notes/t2.13/labelling-protocol.md` — labelling protocol for independent specialist review
- **92 new tests** in `tests/test_t2_13_fixture_schema.py` (fixture schema invariants, strip guard, blank-label invariant)

Business reason (unchanged): Expert labelling of representative cases, not "real" data — a synthetic SG-GST case labelled by an accredited specialist is better ground truth than foreign real data, because the system is judged against IRAS rules. For the current reasoning layer (Reg 26/27): labelled LINE ITEMS only are required (it reads the line description; no invoice needed).

Uses of the labelled set (all evaluation, **not training**): (1) the validation gate / accuracy basket (T2.11); (2) the regression-eval reference re-run on every model/prompt change (T2.3); (3) few-shot exemplars to sharpen the reasoning layer (in-context, not weight updates); (4) the eval substrate that lets a check be packaged as an agent skill with a known accuracy and definition-of-done. The data never trains or fine-tunes a model — Claude is used via API.

### T2.14 — Document legibility/confidence gate — PLANNED (NEW)
Effort PROPOSED 0.5 wk. Owner Terry. The born-digital extraction path in `documents/ingest.py` produces `fields_present` indicators but no confidence gate. A partial regex match or low-quality scan can produce a field value that is extracted but wrong — which would then surface a false candidate in the reconciliation pass. Required behaviour: when key fields (`gst_amount`, `invoice_date`) are absent, or when the multimodal extraction returns null for more than a threshold number of fields, the document should be routed to "manual review required" rather than fed through reconcile with incomplete/unreliable fields. DoD: zero confident-wrong-field candidates surfaced from illegible PDFs; illegible PDFs flagged explicitly in the unified section as "manual review required." Prerequisite for T2.8 being used on any real (non-seeded) invoices. See open item #28 in `AGENTASSIST_TECHNICAL_STATE.md`.

### T2.15 — Automation-bias override tracking — PLANNED (NEW)
Effort PROPOSED 0.5 wk engineering + process design. Owner Terry/Collin. The reviewer sign-off model requires genuine adjudication of surfaced candidates. A reviewer who accepts 100% of J+ candidates without override is a red flag for automation bias — professional responsibility is being transferred without oversight. Add per-engagement reviewer override/edit-rate tracking to the engagement workflow. Flag 100% accept rates as anomalous. This is primarily a process control; the code component is adding a reviewer-action field to the candidate adjudication workflow (which belongs in T3.2). DoD: override tracking defined in the engagement workflow specification; 100% accept rate flagged as anomalous in the engagement review; included in the T3.2 PDPA/compliance framework. See open item #29 in `AGENTASSIST_TECHNICAL_STATE.md`.

### T2.16 — Annual analytical review: TP/TS ratio (ASK Step 1.3d) — DONE (2026-06-11)
DONE (2026-06-11). TP/TS ratio (ASK 1.3d) over the FY (Box 5 ÷ Box 4 > 1.2), opt-in
--analytical-review pass, Annual Analytical Review report section. Demo-validated on
SBODEMOSG: live FY ratio computes + renders + zero findings on clean run + box-isolation;
>1.2 flag-fire validated via crafted input (not live-seedable — demo ratio ~0.50).
RC/OVR approximation caveat: Total Supplies not adjusted for Boxes 14–16 (not computed).
NOT real-client validated. 19 tests (test_check_analytical_review.py).

### T2.17 — Annual analytical review: period-over-period fluctuations (ASK Step 1.3a) — DONE (2026-06-11)
DONE (2026-06-11). Period-over-period fluctuation (ASK 1.3a) on Boxes 1/2/3/5, ±50%
non-regulatory surfacing threshold; wired into the Annual Analytical Review section
(integration branch t2.17b, PR #7). Demo-validated on SBODEMOSG: live FY render of real
Q1→Q2→Q3 movements; all-zero quarters excluded (Q4 empty on demo). Surfaces candidates,
never asserts. NOT real-client validated. 31 tests (18 test_check_period_fluctuation.py +
13 test_analytical_review_integration.py).

### T2.18 — ClientConfig scheme & treatment block — DONE (config infrastructure only; synthetic/unit validated, not real-client validated)
Built on branch `t2.18-config-scheme-block`. Owner Collin. Config infrastructure ONLY — no check logic.

**What was built:**
- Four flat top-level `bool = False` GST scheme-status fields on `ClientConfig` (`config/loader.py`): `actively_makes_exempt_supplies` (**promoted** from the former `getattr(client_config, "actively_makes_exempt_supplies", False)` read — default `False` == prior behaviour), `participates_in_mes` (Major Exporter Scheme), `participates_in_igds` (Import GST Deferment Scheme), `reverse_charge_applicable` (imported services / LVG; a single bool, not split into per-code RC families).
- `load_client_config()` Step 10 reads + validates each flag with the `show_ai_candidates` `isinstance(bool)` guard (non-bool YAML value → `ConfigError`; absent/null → `False`); the loader docstring's numbered step list bumped 9 → 10.
- All four added to `audit_bundle/config_redaction.py`'s `_ALLOW_LIST` (scheme status is engagement-relevant, not secret); they survive redaction even when `False` (`redact_config` drops only `None`). `_DENY_ALWAYS` untouched.
- `config/clients/example.yaml` documents the four flags as the onboarding schema template.
- **Field names are the contract T5.2c `config_keys` and the downstream D+ checks (3E.1, ME/MC reverse charge, Template-4 routing) bind to** — those consumers are separate downstream tasks; this task ships NO check logic and no per-VatGroup-code treatment (that is T2.2).

**Testing:** synthetic/unit only — present-true / present-false / invalid-type (`ConfigError`) per flag; backward-compat (`sbodemosg.yaml` + example.yaml load with all four `False`); Template-4 routing activates on the real (promoted) field via a `ClientConfig` constructor kwarg; allow-list test fails if any of the four is absent from the redacted config. Not validated against a real client (T2.11 still gates anything customer-facing). The one behavioural surface (Template-4 routing) stays default-`False` == current behaviour, so existing clients are unaffected.

---

#### Original PLANNED scope (retained for reference)
Effort PROPOSED 0.5–1 wk. Owner Collin. Config infrastructure ONLY — extends ClientConfig
with the principal's scheme-status facts the scheme-dependent D+ checks will read. Builds NO
check logic (the consumers — 3E.1, 3D.1.1.b ME/MC, reverse charge, Template-4 routing — are
separate downstream tasks). Scope: (1) promote actively_makes_exempt_supplies from the
getattr-default-False to a real, validated ClientConfig field (Known-State B; activates
Template-4 routing when set); (2) add scheme-status fields — MES (Major Exporter Scheme),
IGDS (Import GST Deferment Scheme), reverse-charge applicability — defaulting off, validated
in loader.py, round-tripped through per-client YAML; (3) document the schema. Boundary vs
T2.2: T2.2 persists per-VatGroup-code treatments; T2.18 adds scheme-level flags — distinct
categories, no overlap. Backward-compatible: existing YAMLs without the new fields load with
defaults. DoD: each field present/absent/invalid tested; loader validation step added + step
count updated; Template-4 routing activates on the real field; existing clients unaffected;
canonical docs updated. Branch t2.18-config-scheme-block.

### T2.19 — Tax code normalization layer (non-SAP-B1 source systems) — DONE (synthetic-fixture validated; not yet tested against a real non-SAP-B1 client)
Committed 2026-06-10 on branch `t2.2-vat-discovery` (commits `47e31a0`, `19a6f86`). Owner Collin.

**What was built:**
- `normalize_vat_group(raw_code, mappings)` in `mcp-servers/custom/sap_b1_server.py` — translates a source-system tax code (e.g. Xero `OUTPUT`, `INPUT`) to the canonical AgentAssist VatGroup code (e.g. `SO`, `SI`) before any F5-box routing or E1–E4 detection runs. Case-insensitive; an unmapped code passes through unchanged, so it still lands in `anomalies` via the existing `F5_BOX_MAPPING.get(vg) is None` path rather than being silently dropped.
- `tax_code_mappings: dict[str, str]` and `source_system: str` fields added to `ClientConfig` (`config/loader.py`). Validated at load time — target codes must be valid canonical VatGroup codes (`ValueError` on an unrecognised target); mapping keys normalized to uppercase. Absent block → `tax_code_mappings == {}`, `source_system` defaults to `"sap_b1"`.
- `configure_client()` updated to accept and store `tax_code_mappings`, threading it into module-level state so normalization is active wherever the three custom tools (Tools 12/13/14) classify a `VatGroup`.
- `audit_bundle/config_redaction.py` allow-list extended with `tax_code_mappings` and `source_system` so the translation table applied to an engagement is part of the auditable `config.json` in the sealed bundle (and stays absent from `_DENY_ALWAYS`).
- `config/clients/example.yaml` updated with a documented `tax_code_mappings`/`source_system` block as the schema template for onboarding a non-SAP-B1 client.

**Three-stage testing discipline applied:**
- **Stage 1 (unit)** — `normalize_vat_group()` passthrough/mapping/case-insensitivity; `ClientConfig` validation (bad target raises, keys uppercased, absent block defaults); allow-list membership; an end-to-end `_classify_line()` check with Xero-style codes (`OUTPUT`→`SO` clean line, `INPUT`→`SI` E3 line carrying the canonical code in `issues[].vat_group`).
- **Stage 2 (synthetic-fixture integration)** — new static fixture `tests/fixtures/chain-run-normalization-sample.json` (a copy of `tests/fixtures/chain-run-sample.json` with `classify`/`detect` VatGroups renamed to Xero-style `OUTPUT`/`INPUT` codes plus a `config.tax_code_mappings`/`source_system` block); asserts the fixture's Xero codes normalize to canonical codes and resolve in `F5_BOX_MAPPING`. A separate `sbodemosg` passthrough test loads the real `sbodemosg.yaml` via `load_client_config()`, confirms `tax_code_mappings == {}` / `source_system == "sap_b1"`, runs `seal_bundle`/`verify_bundle` against the existing `chain-run-sample.json` fixture, and confirms the sealed `config.json` round-trips `tax_code_mappings: {}` and `source_system: "sap_b1"` with no `password`.
- **Stage 3 (live non-SAP-B1 injection)** — not performed; no Xero/MYOB/QuickBooks client engagement exists yet to test against.

**28 new tests** in `tests/test_tax_code_normalization.py`. Zero network calls — fully offline/deterministic (no live SAP, no `run_agent.py`, no `seed_test_data.py`).

**SAP B1 clients unaffected:** `sbodemosg.yaml` carries no `tax_code_mappings`; `normalize_vat_group()` is a no-op passthrough for every existing client, so all baseline F5 figures and existing test results are unchanged.

**What it enables:** onboarding a Xero, MYOB, or QuickBooks client requires only adding a `tax_code_mappings` block (source code → canonical VatGroup) and `source_system` to that client's YAML — no code changes to `sap_b1_server.py`, `orchestrator/`, or `report/`.

**Honest qualifier:** validated on synthetic fixtures only (Stage 1 + Stage 2). Not yet tested against a real non-SAP-B1 client engagement — Stage 3 (live injection against an actual Xero/MYOB/QuickBooks export) is pending the first such engagement. The same pair of commits also resolved the 209 pre-existing PDF-fixture test failures (see build-state snapshot above); suite total: **1184 passed, 0 failed, 1 skipped**.

### T2.20 — Annex E vocabulary migration: discovery audit — DONE (2026-06-12)
Owner Collin. Read-only discovery audit for "Option C" — migrating
AgentAssist's internal VatGroup vocabulary from the current 18-code SAP B1 set
to the 35-code IRAS Annex E GST Category Code set, per the e-Tax Guide
*"Adopting GST InvoiceNow Requirement for GST-Registered Businesses"* (Second
Edition, 9 Mar 2026), Annex E. No source files changed. Artefact:
`exploration-notes/t2.20/vocabulary-migration-inventory.md`.

**Findings:**
- The 18-code vocabulary is carried in **≥7 independently-maintained
  locations** (sap_b1_server.py's `F5_BOX_MAPPING` + `_vg_category`,
  run_baseline_tests.py's three reference structures, system-prompts/base.md's
  two tables, report/routing.py's frozensets, report/sections.py's
  `_BOX_VATGROUPS` + judgment literals, config/loader.py's
  `_STANDARD_VAT_GROUPS`, knowledge-base/sg-tax-code-mappings.md). Only
  `F5_BOX_MAPPING` plus two module-level sets (`_E2_ZERO_RATE_CODES`,
  `_STANDARD_RATE_SALES`) form the single shared core consumed by Tools
  12/13/14 — everything else is documentation, an audit-not-partner reference
  re-implementation, or an independent partial duplicate that can drift.
- Code-by-code Annex E mapping: of 35 Annex E codes, **13 are direct
  carryovers** (DS, ZR, ES33, ESN33, OS, IM, ME, IGDS, ZP, BL, EP, OP, NR),
  **2 are renames** (SO→SR, SI→TX), **2 are NAME COLLISIONS** with the current
  codes of the same name but conflicting box-treatment semantics (TX-N33,
  TX-RE), and **18 have no current equivalent** (Customer Accounting,
  Overseas Vendor Registration/Low-Value-Goods, and reverse-charge families,
  plus `NA`/`NG`/`TXNA`/`TXRC-TS` pending IRAS-text confirmation). One current
  code (TX-E33) has no target in the given Annex E list.
- **T2.18 dependency:** T2.18 as currently scoped (MES/IGDS/reverse-charge
  flags + `actively_makes_exempt_supplies` promotion) is necessary but not
  sufficient for Option C — it unblocks `ME`/`IGDS` validation and is a
  building block for the `TX-RE`/`IM-RE`/`TXRC-RE` residual-input-tax family,
  but the Customer Accounting and OVR/LVG families (8 codes) need either an
  extended T2.18 scope or a "manual review" fallback. Recommend sequencing
  T2.18 immediately before/with the remaining T2.21 build (buckets 3+4+8) —
  see T2.21 entry below. **Confirmed by T2.21b (2026-06-15):** buckets 1+2
  (16 codes, the `SO`→`SR`/`SI`→`TX` renames + 14 direct carryovers) needed no
  T2.18 input at all — the T2.18 dependency is specific to buckets 3+4+8.
- Surfaced two pre-existing drift bugs (not fixed, per task scope):
  `system-prompts/base.md`'s E2 condition set and `report/routing.py`'s
  `_ZERO_RATED_VGS` are both missing `ZP`, added to the production E2 set in
  T2.10 but never propagated to these two locations. Also a 3-way `TX-RE`
  label inconsistency (`_vg_category` says "Tourist refund — retail";
  `KNOWN_VATGROUPS`/base.md say "Residual input tax") that becomes load-bearing
  (not just inconsistent) once Annex E's `TX-RE` semantics are adopted.
- Test fixture impact: 7 JSON fixtures + `generate_invoices.py` carry
  hardcoded VatGroup strings (`SI` alone appears ~265 times across the
  reg2627 fixture family); the 18+2 codes with no current equivalent have
  zero existing fixture coverage.
- First-pass effort estimate for the build task: **~9-13.5 days excl. T2.18,
  ~11-17.5 days incl. T2.18** — explicitly a first-pass estimate, subject to
  revision once the IRAS Annex E text is consulted directly. Recommends a
  follow-on task (T2.22) for genuine transaction-level detection logic for
  the 13 Customer-Accounting/OVR/reverse-charge codes that no client-level
  config flag can resolve.

See T2.2 (above) for the resulting sequencing note.

### T2.21 — Annex E vocabulary migration: build — buckets 1+2 DONE, buckets 3+4+8 remaining scope (blocked on T2.18)

**Buckets 1+2 — DONE (2026-06-15).** Committed `21c70e9` on branch
`t2.21a-annex-e-baseline-vocab` (NOT yet merged to master). Owner Collin.
Implements T2.20 Section 2d's buckets 1+2 (16 of the 35 Annex E codes): the 14
direct-carryover codes (`DS`, `ZR`, `ES33`, `ESN33`, `OS`, `IM`, `ME`, `IGDS`,
`ZP`, `BL`, `EP`, `OP`, `NR`, `NG`) plus the 2 renamed codes `SO`→`SR`
(sales standard-rated) and `SI`→`TX` (purchase standard-rated), edited/synced
across the ~7 load-bearing locations identified in T2.20 Section 1. Also
fixes two T2.20 Section 0 drift findings — `ZP` was missing from
`_E2_ZERO_RATE_CODES` (`sap_b1_server.py`) and `_ZERO_RATED_VGS`
(`report/routing.py`), both now include it; and `_vg_category`'s `ME`/`TX-RE`
human-readable labels were corrected to match `base.md`/`KNOWN_VATGROUPS`.
Wires `effective_tax_code_mappings` live:
`config/loader._SAP_B1_DEFAULT_TAX_CODE_MAPPINGS = {"SO": "SR", "SI": "TX"}`
is now applied by `normalize_vat_group()` for every SAP B1 client that
declares no `tax_code_mappings` override (i.e. `sbodemosg.yaml` and
`example.yaml` as shipped); `audit_bundle/config_redaction.py`'s
`_ALLOW_LIST` gains `effective_tax_code_mappings`.

**Chain-accepted (SOP step 5, 2026-06-15)** via live, read-only SBODEMOSG
validation, period 2024-07-01..2024-07-07 (T2.20 Section 0's window), diffing
`8ccc2e8` (pre-rename) against `21c70e9` (post-rename): F5 box totals
byte-identical before/after; `vatgroup_inventory` shows `SR`(13)/`TX`(1) in
place of `SO`/`SI`, `known_to_mapping: true`, `lt_box`/`tt_box`/`side`
unchanged; `detect_gst_errors` returns the same single E1 finding (doc_num
958) with only the VatGroup token in the description text changed; a full
`run_chain` → `build_report` → `render_pdf` produced a 4-page PDF with
`SR`/`TX` visible and zero occurrences of standalone `SO`/`SI`/"unknown";
`effective_tax_code_mappings == {"SO": "SR", "SI": "TX"}` confirmed live via
both the module-load and `run_chain`/`configure_client` paths. `ZP`/`ME`/
`TX-RE` did not appear in this period's live data — those fixes remain
fixture/unit-test-validated only. **1490 passed, 1 skipped on the branch**
(+9 net new vs master's 1387/1 — 10 new tests, 1 prior characterization test
superseded by the rename; branch not yet merged, so master's test count is
unchanged). Findings:
`exploration-notes/t2.21/t2.21b-chain-acceptance-findings.md`. See
`AGENTASSIST_TECHNICAL_STATE.md` Appendix C #32.

**Remaining scope (buckets 3+4+8, 8 codes) — blocked on T2.18, no scheduled
follow-on task.** T2.20 Section 2d's buckets 3+4+8 were explicitly out of
scope for T2.21b: bucket 3 (`TX-N33`, `TX-RE`, `TX-E33`→`TX-ESS` — name
collisions in the T2.18-attribution family), bucket 4 (`IM-N33`, `IM-RE`,
`IM-ESS` — partial-`IM` carryover, T2.18-attribution), and bucket 8 (`NA`,
`TXNA` — scheme-participation). Per T2.20 Section 3's analysis, confirmed by
T2.21b's experience (buckets 1+2 needed no T2.18 input at all): all 8 of
these codes require T2.18's `actively_makes_exempt_supplies`/scheme-status
config, which is still PLANNED (see T2.18 entry above — this finding does not
change T2.18's own scope). This remaining scope therefore has **no scheduled
follow-on task** pending a T2.18 sequencing decision — it is deliberately
*not* labelled "T2.21c" here, since whether it becomes its own numbered entry
or stays an annotation on this entry is an open question for Collin/Terry.
Buckets 5-7 (11 T2.22-deferred codes — Customer Accounting, Reverse Charge,
OVR/LVG families) remain untouched and tracked under T2.22.

---

## Tier 3 — Required Before Specific External Milestones

### T3.1 — SOC 2 readiness documentation — PLANNED
Trigger: enterprise procurement. Effort 4–6 wk docs (audit separate). Mostly documenting existing practices now that T1.5 exists. SG interim: DPTM (SS 714:2025), a year-2 goal.

### T3.2 — PDPA compliance framework — PLANNED
Trigger: first paid engagement on real client data, or Anthropic Partner Network application. Effort 2–3 wk with legal input. Purpose limitation, data minimisation, retention (≈7-year for tax workpapers per IRAS, then destruction), client-facing DPA template, Anthropic DPA evaluation. **Prerequisite for any pilot-derived ground truth (T2.13) and for the platform handling real client data (Tier 4).**

**PDPA specifics confirmed 2026-06-08** (document these before the first engagement, not after):

- **AgentAssist is a data intermediary** (PDPA s.26) when processing client financial data. The client is the data controller; AgentAssist processes on their behalf. A data intermediary agreement must be in place before any real client data is processed.
- **Overseas transfer obligation**: Sending SAP line-item data to the Claude API is an overseas transfer under PDPA s.26. Anthropic's commercial API DPA provides comparable contractual protection; confirm it applies before engaging. Obtain the applicable DPA from Anthropic and present it to the client as part of the engagement DPA.
- **Residency via Bedrock/Vertex (preferred for regulated pilots)**: AWS Bedrock (Asia-Pacific region) or Google Cloud Vertex AI (asia-southeast1 = Singapore) provide in-region inference and can satisfy the Transfer Limitation Obligation without requiring a DPA transfer mechanism. This is the preferred architecture for a Singapore-regulated pilot.
- **Commercial API does not train; ZDR available**: The Anthropic commercial API (not free tier) does not use input/output to train or improve models. Default data retention is 7 days; Zero Data Retention (ZDR) eliminates this window and is available on eligible plans. Confirm ZDR eligibility and document it in the engagement DPA.
- **Private cloud does not stop transmission**: Hosting the orchestrator on a private cloud or on-premises server does NOT prevent data leaving that environment — as long as `reasoning/reg2627.py` or `documents/ingest._extract_multimodal()` call the Anthropic API, line-item data is transmitted externally. The only technical residency mitigation is Bedrock/Vertex in-region; private cloud alone is insufficient.
- **Automation-bias guard** (see T2.15): reviewer override/edit-rate tracking is a compliance-adjacent process control; include it in the T3.2 framework design alongside the technical controls above.

### T3.3 — BIG application technical exhibit — PLANNED
Trigger: BIG submission. Effort 2 wk. Architecture doc, V0→V3 narrative, 30/30 outcomes, commercial roadmap, demo walk-through. Lead with the validated deterministic story (v0-vs-v3 contrast); present the reasoning/document-ingestion layer as emerging, unvalidated, human-gated.

### T3.4 — Anthropic Partner Network application artefacts — PLANNED
Trigger: AP application. Effort 1–2 wk. Case study (V0→V3), technical write-up, sanitised SBODEMOSG sample deliverable.

### T3.5 — Singapore SAP B1 reseller channel materials — PLANNED
Trigger: conversations with named resellers. Effort 2 wk. Co-branded one-pager, pricing structure, engagement template, consultant training.

### T3.6 — InvoiceNow / GST InvoiceNow (PINT-SG) ingestion path — PLANNED
Trigger-gated; effort future. Owner Terry. As structured invoice fields arrive via Peppol, several J+ document-reads convert to D+ field-comparisons. Shares the T2.12 adapter seam. Phased mandate: voluntary registrants Apr 2026 → all GST-registered by Apr 2031.

---

## Tier 4 — Platform vision (north-star, GATED — do not start before the gate below)

### T4.1 — Consolidated multi-vertical agent platform / dashboard — VISION, NOT SCHEDULED
Owner Terry. Effort: large; not estimated until the gate is met.

**The vision.** A single platform/dashboard (analogous in spirit to Odoo or SAP B1) where an end user accesses multiple industry-vertical agents and pays per agent, with the Singapore GST accounting agent as the first vertical. A polished UI/dashboard fronting the engine, with per-agent metering for pricing.

**Gate (all must be true before any platform UI build begins):**
1. The GST agent's reasoning layer is **validated** (T2.11 complete) — not just built.
2. There is at least one **paying pilot** and evidence of demand for a dashboard delivery surface (customers who would log in and self-serve), not an assumption of it.
3. The **who-signs** question is resolved for the self-serve context: the GST agent surfaces candidates; an SCTP-accredited human signs the ASK working paper. A dashboard does not remove the reviewer of record — the platform must route to one (the firm's certifier, or the in-house team's external certifier).

**Why gated (honest flag).** The documented moat is **distribution + domain trust, not the tooling**, and the model is consulting/channel, **not pure SaaS**. A dashboard is a packaging/distribution surface; it does not address the distribution bottleneck and earns its build only once there is a validated, sold vertical to put in it. Building the container before the contents are proven spreads effort away from validation and first revenue. This is also the future state where the Anthropic Skill abstraction (Reminder #5) finally earns its place — but that, too, is post-validation.

**What to do now toward it (near-zero-cost option-keeping):** nothing UI. Keep the engine cleanly separable behind a stable internal schema/API (the T2.12 input-adapter refactor), and keep per-agent boundaries clean, so a dashboard can wrap the engine later without a rewrite. Architecture readiness is the only platform work that belongs in the present. Tier 5 (the agentic shell) is the engineering substrate of this platform vision — reusable shell + per-vertical validated cores — and the T4.1 gate is unchanged.

**Surface vs platform (2026-06-17).** The end-user intent SURFACE is roadmapped separately as **T5.9** and pulled forward to **pre-demo** — decoupled from the paying-customer gate — because it is product-intrinsic UX, not a delivery-model feature. Only the multi-vertical PLATFORM / dashboard (this T4.1) stays gated. **Pulling the surface forward != pulling the platform forward** (Invariant 6 amendment). The menu T5.9 exposes is the cage at the product layer; T4.1 is the metered, multi-vertical container that menu eventually lives in, and it earns its build only at the gate above.

---

## Tier 5 — Agentic shell — bounded-autonomy junior layer (PLANNED, GATED)

Design sentence (verbatim): "The compliance computation is a workflow forever. Agency is added only where dynamism pays: gathering context, assembling evidence, and proposing actions. The agent drives the process; it never owns an outcome."

Framing: per Anthropic's workflow/agent distinction (Building Effective Agents, anthropic.com/engineering/building-effective-agents), the existing system is a workflow — LLMs and tools orchestrated through predefined code paths. Tier 5 adds an agent layer (LLM dynamically directing process and tool use) AROUND the workflow, never inside it. Authority lives only in the Tier-2 executor behind human approval and in the reviewer's signature; no tool in the agent's registry carries authority.

### Action-tier model (the core of bounded autonomy)
- Tier 0 — Observe: read-only tools (SAP reads, ledger reads, KB reads). Autonomous; every call logged via PostToolUse hook.
- Tier 1 — Work in staging: chain invocation, dossier drafting, report-section drafting; effects confined to a staging workspace. Every Tier-1 tool takes a mandatory `justification` parameter; a PreToolUse hook writes it to the justification ledger BEFORE execution and BLOCKS the call if absent or trivial. The agent cannot act silently.
- Tier 2 — Propose and hold: anything crossing the staging boundary (seal bundle, emit final PDF, reviewer-facing sends, decision-ledger writes). The agent emits a schema-validated proposal artifact (action + justification + evidence refs); a human approves; approval triggers a DETERMINISTIC EXECUTOR (plain Python) that performs the action. The agent never executes Tier 2, even after approval — a compromised agent can at worst produce a bad proposal, never a bad action.
- Tier 3 — Structurally impossible: SAP writes, git operations, IRAS filing, client-config edits, edits to its own ledger/labels/permission rules. These tools DO NOT EXIST in the agent's registry (absent, not denied), and the agent process holds no write-capable credentials (privilege separation backstops the registry).

### Invariants — enforced (graduated to `docs/merge-gates.md` Gate e, 2026-06-12)
1. Every autonomy rule exists three times: stated in the system prompt, enforced in a hook, proven by a test. A rule that exists only in a prompt is not a rule.
2. The agent process holds no write-capable credentials to SAP or git.
3. Atomicity: the agent orchestrates BETWEEN sealed components, never WITHIN one. run_review_chain is exposed as a single atomic tool (gates included); the agent never invokes individual chain steps. (Rationale: T1.6 — "Claude decided to skip validate_invoice_tax_codes" is not defensible.)
4. The agent may INVOKE a reasoning check (reg2627 pass, documents pass) as a versioned, separately-measured tool; it may never PERFORM judgment in its own voice. Agent-voiced compliance opinions are a lint failure. Measured accuracy baskets attach to the packaged passes only; T2.11 gating is inherited unchanged (show_ai_candidates governs dossier visibility too).
5. Decision-ledger entries are context for annotation/demotion only — never suppression, never training. Known-accepted recurring findings render annotated and demoted, never hidden.
6. Bounded task surface: the product interface is a fixed menu of intents mapping to tier-classified action sequences; free text is permitted only within a task and is treated as untrusted input. Note: input bounding is a product/evaluability measure, NOT a safety mechanism — any safety property that fails under adversarial user input was never a safety property. **Input-surface note (Collin reconciliation):** the front door accepts free text; an intent ROUTER maps it to the bounded intent space; on a miss, the system asks for clarification rather than guessing. Free text is untrusted input — the router classifies, never obeys. This is the agreed reconciliation of the "chatbot" front-end idea with the bounded-task-surface invariant: a natural-language front door is fine; unconstrained LLM-to-tool chaining inside the product is not. **Surface-forward amendment (2026-06-17):** the intent SURFACE — the end-user front door onto this fixed menu — is pulled forward to **pre-demo as T5.9**, decoupled from the paying-customer gate; the multi-vertical PLATFORM (the T4.1 dashboard) it eventually fronts **stays gated**. Pulling the surface forward is NOT pulling the platform forward — a product feature (how a user drives bounded autonomy) is distinct from the delivery model (who pays). Agreed demo narrative: **"the menu is the cage at the product layer"** — the bounded intent menu is itself the containment the user sees.
7. Agent-layer failure is non-blocking to the deterministic deliverable. If the agent errors, crashes, or hits its loop/cost cap, the deterministic chain output and the signed working paper still complete — exactly as a reasoning-pass failure is logged but never prevents the audit bundle from sealing. The agent shell may add to the deliverable; it must never be able to prevent it.

### T5.1 — Engine API seam — DONE (2026-06-12)
Completed 2026-06-12, merge commit `e30f795`, branch `t5.1-engine-seam`. Owner: Terry.

Stable callable interface `review(client_config, period, inputs) → ReviewResult` delivered in `engine/review.py`. The agent shell (T5.3) is the first consumer; `run_agent.py` is the current thin-CLI consumer.

**What was built:**
- `engine/` package: `review()` entry point; `ReviewResult` (11 fields incl. `analytical_review_data`); `ReviewInputs` (4 fields: `line_source` / `provider` / `declared_f5` / `analytical_review`); `GateHalt(message, checked)` plain serialisable record.
- `ReviewInputs` is the forward-compatible source-adapter seam: today `line_source` wraps `fetch_si_purchase_lines` (SAP B1 only); a T2.12 CSV/Excel adapter substitutes a different callable without changing `review()`'s signature. Deep source substitution stays T2.12 — the seam is at signature level only.
- `run_agent.py` reduced to a thin CLI — delegates to `engine.review.review()`; no pipeline logic remains there; `review()` is SILENT; the CLI prints from the returned `ReviewResult`.
- `engine/__init__.py` re-exports `ReviewResult`, `ReviewInputs`, `GateHalt` but does NOT re-export `review` (submodule-shadow avoidance — would break `patch("engine.review.run_chain", …)` in tests).
- Import-scan gate extended: `docs/merge-gates.md` Gate a Check 2 and CI import-scan now bar `orchestrator/` from importing `engine/`. Dependency direction: `engine/ → orchestrator/`, never reverse.
- **15 new tests** in `tests/test_engine_review.py` (T1–T5: composition order, ReviewResult shape, halted path, reasoning non-blocking, behavior equivalence). `tests/test_run_agent_e2e.py` patch targets updated; 3 pre-existing tests pass unchanged.

**Honest qualifier:** behavior-preserving refactor; built + unit-tested; stdout content-equivalent (NOT byte-identical interleaving — mid-run progress lines print after `review()` returns); **NOT demo-validated end-to-end** (live SBODEMOSG CLI run pending/Terry-supervised); no agent loop (T5.3); nothing customer-facing changes until T2.11. Master total: **1387 passed, 1 skipped**.

Cross-ref: T2.12 (deep source-adapter substitution — `line_source` is the seam, wiring is T2.12's job); T5.3 (first real agent loop using this seam).

### T5.2 — Action-tier framework + justification ledger — DONE (2026-06-12)
Completed 2026-06-12, PRs #12 (T5.2a) and #13 (T5.2b). Owner: Terry.

**Honest qualifier:** DONE = cage built + hermetically unit-tested; **NOT demo-validated** (no live agent loop); `seal` and `emit` executor handlers are NotImplemented stubs deferred to T5.3. 133 new tests (89 T5.2a + 44 T5.2b); 1372 passed, 1 skipped at T5.2 merge (master total after T5.1: 1387 passed, 1 skipped). See `AGENTASSIST_TECHNICAL_STATE.md` §T5.2 for full detail.

**What was built:**
- `agent/` package: Tier enum (0/1/2/3); ToolSpec/CheckSpec/LedgerEntry/ProposalArtifact/RunBudget schemas; tool registry (8 tools: 4 Tier-0 read-only, 4 Tier-1 staging, zero Tier-2-executing); justification gate (heuristic backstop); append-only hash-chained justification ledger (reuses `canonical.py`); StagingStore (CLI-first approve/reject); deterministic Tier-2 executor (`test_noop` handler + NotImplemented stubs for seal/emit); RunBudget with BudgetExceededSignal → invariant-7 non-blocking path.
- SDK integration: `agent/hooks.py` (make_hooks → PreToolUse/PostToolUse); `agent/harness.py` (build_options → ClaudeAgentOptions, deferred SDK import); `agent/approve_cli.py` (CLI over StagingStore + Executor); `audit_bundle/seal.py` extended with `agent_ledger` parameter → `steps/agent-ledger.json` in bundle.
- CheckSpec v0/PROVISIONAL — 14 entries; NOT wired to consumers; Collin ratifies after T2.18.
- First runtime dependency: `claude-agent-sdk==0.2.99`. On `ubuntu-latest` pip selects the `manylinux` wheel, which bundles the Linux `claude` binary (`_bundled/claude`), so `pip install` auto-provisions the runtime — no npm/`cli_path`/env var (corrected D11; the earlier "builds from sdist" note was inaccurate — pip never reaches the sdist on glibc; no musllinux wheel, so keep CI on glibc). CLI binary only exercised at `query()` time (T5.3). `orchestrator/` unchanged; Gate a extended in `docs/merge-gates.md` to forbid `agent/` imports in `orchestrator/`.

### T5.2c — Check-registry contract — DONE (2026-06-17; reconciled + frozen v1; NOT real-client validated; awaiting Collin ratification at merge)
Sequenced after T2.18 (config scheme block). T5.2c graduated the CheckSpec registry from v0/PROVISIONAL to **v1**, the coordination contract T5.4 (check planner) consumes. RECONCILE-TO-REALITY + ADD `config_keys`, not a redesign:
- **`config_keys` added** (additive, default `[]`) — an **applicability gate**: which T2.18 ClientConfig scheme flags must be True for a check to *run* for a client; `[]` == always applies. NOT routing (the exempt Template-4/5 split stays in `report/routing.py`). All 14 current checks are unconditional (`config_keys=[]`); the field is reserved for future MES/IGDS/reverse-charge checks.
- **iras_basis / finding_schema reconciled** against each real check. E1–E4 `finding_schema` now encodes the enriched detect shape `extract_findings` reads at the loop boundary. E1/E2 citations corrected and **verified against the in-repo IRAS guide PDF** (s21(3) §5.8; §5.8–5.9 + Regs 26/27); `correct_period` statutory section unverifiable from repo guides → original `s20` kept + TODO flagged for Collin/specialist.
- **inputs_needed**: one corrective edit — E3 +`purchase_invoices` (fires on purchase TX zero-tax). Engine-seeded; the round-2-validated slot contract (NO_GST_REG → supplier_catalog; document checks → document_pdfs) is **intact**.
- **`CHECKSPEC_STATUS` flipped `"v0/PROVISIONAL" → "v1"`**. Stale-code scan clean (no SO/SI in the registry).
- Failing-test-first (`tests/test_t52c_checkspec_finalisation.py`, +18 tests) then implement; full suite **1662 passed / 1 skipped**, zero regression; `orchestrator/` purity intact. The reconciliation table in `AGENTASSIST_TECHNICAL_STATE.md` §T5.2 is Collin's ratification artifact. Honest status: contract finalised + reconciled, **NOT real-client validated** (T2.11 gates customer-facing); frozen T2.18 flags untouched. Hard dependency: T2.18 (met). Owner: Terry + Collin. **MERGE GATE: CI green AND Collin's ratification (he co-owns CheckSpec); Terry merges.**

### T5.3 — Case-file builder (Slice 1 + Slice 2) — DONE (2026-06-14; built + hermetically tested; NOT validated)
**DONE = built on master + hermetically tested (FakeTransport / no live model, no SAP, no tokens). NOT live-validated; nothing customer-facing until T2.11.** Delivered in two slices.

**Slice 1 — engine-tool plumbing** (merge `458e33b`): `agent/engine_tool.py` exposes the deterministic `review()` pipeline as ONE atomic in-process MCP tool (`mcp__engine__run_review_chain`) — no sub-step (run_chain / gate / seal) is reachable. MCP-prefix-aware `get_tier()` resolves the namespaced name back to the Tier-1 `run_review_chain` registry entry, so the justification gate applies. `agent/executor.py::make_tier2_handlers` builds the real `seal_bundle`/`emit_final_pdf` handlers (wired via `extra_handlers`; defaults stay NotImplemented) that fire ONLY on `status="approved"`. Three new Tier-0 dossier reads: `get_source_document`, `read_vendor_gst_status`, `read_prior_period_treatment`. **SEALED-CHAIN routing (locked):** Tier-2 post-approval seal/emit outcomes → sealed hash-chained agent-ledger; Tier-0 reads → unsealed audit_log; ledger entries are recorded facts (box-isolation / compile-output re-derivability unaffected). +21 tests → **1408 passed, 1 skipped**.

**Slice 2 — case-file loop** (PR #17): `agent/loop.py::run_casefile_loop` is a plain-Python gather→act→verify driver — the model is invoked WITHIN it (via an injected `AgentTransport`) and NEVER drives it; the deterministic completeness checklist + `RunBudget` decide termination. Per finding it assembles a dossier from the Slice-1 Tier-0 reads. Verification is a CODE-DEFINED completeness checklist keyed to `CheckSpec.inputs_needed` (`agent/completeness.py`) — never model self-assessment. `agent/lint.py` is a deterministic language-lint (brittle backstop, NOT a replacement for the structural cage). `agent/dossier.py` adds the `DossierArtifact` schema; `agent/proposals.py` adds the additive `compute_inputs_hash` shared by dossier ⇄ proposal. The loop can ONLY ever stage a PENDING proposal (no Tier-2 tool exists); `cost_usd_used` is written to the ledger as the auditable cost-per-review COGS field; budget-exceeded routes non-blocking (Invariant 7); a poisoned PDF can at worst become a PENDING proposal a human reads — nothing is sealed or emitted. +38 tests (branch standalone off the 1408 base → 1446; combined with T5.7a, master total → **1479 passed, 1 skipped**).

**Slice 3 — live transport adapter (T5.3c) — DONE (2026-06-15, PR #21, commit `5cb9fd3`).** `agent/live_transport.py::LiveAgentTransport` is the live-model counterpart of the hermetic `FakeTransport`/`ScriptedLoopTransport` — the one piece the loop needed to run against a real model. It implements the `agent.loop.AgentTransport` Protocol: `stream(prompt, finding)` runs ONE `claude_agent_sdk.query()` per turn (drained via `asyncio.run`; the driver then does `budget.increment(turns=1)`) and maps the SDK stream → the loop's `AgentEvent`s — `ToolUseBlock→ToolUseEvent` (name + `input` verbatim, carrying the model's `justification`+`evidence_slot`), `TextBlock→FramingEvent`, `ResultMessage→ResultEvent(cost_usd=total_cost_usd)` (the priceable per-turn COGS); thinking/tool-result/user/system messages ignored. It changes NO loop logic (`run_casefile_loop` already takes an injected transport). **Relay-only** — it translates the model's tool *requests* into events and nothing else; it executes no tool, seals/emits nothing, adds no Tier-2 surface; `allowed_tools()`/`validation_status`/`show_ai_candidates` untouched. The opt-in factory `make_live_transport` raises unless env `AGENT_LIVE_TRANSPORT == "1"`, so the token-burning live path cannot run by accident; the injected `ClaudeAgentOptions` is passed through verbatim (hook-free-vs-hook-bearing deferred to T5.3-V). **SDK confinement:** the import is confined to this module and deferred to call time (`_resolve_query()`) — a third deferred-SDK site in core `agent/` after `harness.py` and `eval/transport.py`; `import agent`/`agent.live_transport` do not load the SDK, and the module lives in core (not `agent/eval/`) so the eval hermetic source-scan gate is untouched. **This unblocks T5.3-V — the supervised, opt-in, token-burning live run — which remains a SEPARATE step** (it exercises a live model, decides hook-free vs hook-bearing options, and sets `AGENT_LIVE_TRANSPORT=1`). **Honest:** built + hermetically tested with a MOCKED SDK stream (no live model, no `claude` binary, no tokens), failing-test-first; **mock-tested only, NOT live-model-validated; T2.11 still gates customer-facing.** +14 tests (`tests/test_t53c_live_transport.py`) → **1513 passed, 1 skipped** (authoritative master total). See `AGENTASSIST_TECHNICAL_STATE.md` §T5.3 Slice 3.

**T5.3-V live validation — round 1 (2026-06-15, crafted-finding).** After T5.3d (hook-free option), T5.3e (MCP reads server) and T5.3f (loop rewire to in-turn evidence) merged, the arch-A loop was run live against `claude-opus-4-8` at master `af79296` (~$1.08; hand-built ReviewResult + fixture ctx — **machinery only; NOT demo-DB, NOT real-client, NOT accuracy-validated**; SBODEMOSG SAP creds unprovisioned + no live `LoopContext` builder). **Validated live:** the model calls the `mcp__reads__*` tools in-turn (SDK runs the T5.3e handlers, sink fills — not prose-only); the cage held (Tier-0 allowed, leaked CLI built-in `ToolSearch` denied Tier-3, zero Tier-2, nothing sealed/emitted); driver-decided staging (A1) correctly withheld. **Open gaps:** 0 PENDING staged (the model used invented `evidence_slot` names so code-defined completeness was unmet → slot-contract fix is **T5.3g**); live read-ledger names are namespaced (`mcp__reads__…`) vs the bare form the fakes write (T5.7b parity); leaked CLI built-ins need suppression. Frozen flags untouched; the complete→stage path is NOT yet shown on a live model (T5.3-V round-2, after T5.3g). Evidence: `exploration-notes/live-loop-run-20260615/`; full detail in `AGENTASSIST_TECHNICAL_STATE.md` §T5.3 "Live validation (T5.3-V)".

**T5.3-V live validation — round 2 (2026-06-16, real ctx + real findings).** The round-1 gap closed: the arch-A `run_casefile_loop` was run live against `claude-opus-4-8` at master `19eb62e` over a **REAL `LoopContext`** (T5.3h `build_loop_context`) and **REAL findings** (offline-replayed deterministic chain off the frozen SBODEMOSG extract, SAP unreachable). Finding set (option B): the first 3 `NO_GST_REG` findings (Acme Associates 605, Far East Imports 592, SMD Technologies 594), chosen to exercise the T5.3g `supplier_catalog` slot live. **MECHANISM validated:** **3 PENDING `ProposalArtifact`s staged**, 1 attempt each (round-1 staged 0); the T5.3g code-bound slot fix worked **live on real data** — the model passed only `card_name`, the canonical `supplier_catalog` slot filled non-null, completeness satisfied (`dossier_completeness_rate`/`language_lint_pass_rate` = 1.0); cost **$1.013447 ≤ $3.00** cap (`max_turns=12`), non-blocking. **Cage held:** 16 ledger entries (1 Tier-1 gather + 3×[3 Tier-0 reads + budget + Tier-1 `propose_action`]), **zero Tier-2**, nothing sealed/emitted, **zero Tier-3 denials** (Opus stayed in the `READ_TOOLS_QUALIFIED` allowlist; `ToolSearch` disallowed + hook backstop). **Honest scope:** `supplier_catalog` validated live ×3; **`document_pdfs` NOT live-exercised through complete→stage** — `get_source_document` fired and wrote the canonical slot, but `AbsentDocumentProvider` returned ABSENT and no document-requiring check was in the set, so only the slot *binding* (not the path) is shown. **MECHANISM, not accuracy** (T2.11 unchanged); frozen flags untouched (`validation_status="unvalidated"`, `show_ai_candidates=False`); no source/test change (new files under `exploration-notes/` only). Evidence: `exploration-notes/live-loop-run-20260616-round2/`; full detail in `AGENTASSIST_TECHNICAL_STATE.md` §T5.3 "Live validation (T5.3-V) — round-2 real-ctx".

**SEALED-CHAIN lean (recorded):** the Tier-2 seal produces the FINAL reviewed bundle, which references the engine's own deterministic bundle (`review()`'s internal seal) as sealed evidence. The loop only ever stages PENDING proposals; the final bundle is sealed by the deterministic executor AFTER a human approves — outside the loop. **Honest caveats:** built + hermetically tested, NOT live-model-validated end-to-end; loop QUALITY (dossier completeness rate, language-lint pass rate) is measured by T5.7b, not yet run; the phrase-list lint is brittle. See `AGENTASSIST_TECHNICAL_STATE.md` §T5.3 for full detail.

**T5.3h — real LoopContext from the frozen extract — DONE (2026-06-16, PR #35, feat `8785f92`).** Closes the round-1 gap (*"no live `LoopContext` builder exists"*): `agent/loop_context.py::build_loop_context(period, *, review_result)` assembles a REAL case-file-loop ctx from the frozen SBODEMOSG extract (the T2.12a ground truth), so the loop runs over REAL deterministic findings rather than a hand-crafted ReviewResult. **Decision A1:** the real `ReviewResult` is produced OFFLINE and INJECTED — the builder is a pure assembler (no SAP, no monkeypatch, no SDK import) so it serialises cleanly for the T5.8 RealEngine path. `build_vendor_catalog` reads the S3 business-partners surface and re-keys it by CardName, surfacing only `gst_registered`/`gst_reg_no` (from `FederalTaxID`); `AbsentDocumentProvider` + empty prior-period store are the honest SBODEMOSG degraded case (reads return ABSENT, never fabricated). **Decision B1 (chain-only):** `tests/replay_shim.py::replay_review` builds a `ReviewResult` with `reasoning_artefact=None`/`document_candidates=None` — the probabilistic surfaces are honestly absent; the findings the loop consumes live in `compile_output.detect.issues`. `tests/replay_shim.py` is a byte-preserving extraction of the inline T2.12a fixture (`install_replay_patches`/`frozen_extract_sap`/`replay_chain`/`replay_review`), so the **T2.12a byte-identity gate is intact**. **Honest:** built + hermetic/scripted via the byte-identity-gated offline replay (SAP unreachable); **NOT live-validated** (the live complete→stage path is still PENDING — T5.3-V round-2 + the T5.3g slot-contract fix); **NOT accuracy-validated** (findings read as-is); T2.11 still gates customer-facing. Surfaced an open `finding_id`-collision decision (Appendix C #33 / backlog item 6 — 23 raw detect findings collapse to 20 unique ids on the frozen extract). +11 tests; full suite **1588 passed, 1 skipped** on the branch (authoritative current master total **1608/1**). See `AGENTASSIST_TECHNICAL_STATE.md` §T5.3h.

### T5.4 — Check planner — DONE (2026-06-17; built + hermetically tested; NOT live/real-client validated)
Routing, not invention: `agent/planner.py::plan_checks(client_config)` selects the applicable subset of the FIXED v1 `CHECK_REGISTRY` given the client profile. First plan per client is a Tier-2 proposal; an identical plan re-executes at Tier 1; plan drift re-escalates to Tier 2 automatically. The planner never composes new logic — output is provably ⊆ registry check_ids. **Applicability gate:** a CheckSpec is in-plan iff its `config_keys` ⊆ the client's satisfied T2.18 scheme flags; empty `config_keys` (all 14 current checks) == always applies, so today every check is in every plan — the gate is built correct for future MES/IGDS/RC-gated checks but bites nothing now (proven by a SYNTHETIC `config_keys=["participates_in_mes"]` mechanism test included iff the flag is True). **Fingerprint:** sha256 over (sorted applicable check_ids + the four flags) via the shared public `compute_inputs_hash`; period is metadata, NOT in the fingerprint. **Tier model:** `ApprovedPlanStore` (in-memory, keyed by client_id) records the approved fingerprint ON HUMAN APPROVAL of the Tier-2 proposal (`confirm_approved_plan`), never on generation; the Tier-2 proposal is emitted via the relay-only `build_proposal`+`StagingStore` path (the model never calls `propose_action`). +21 hermetic tests; full suite 1683 passed, 1 skipped. Effort ~1 wk after T5.2. See `AGENTASSIST_TECHNICAL_STATE.md` §T5.4.

### T5.5 — Decision ledger — DONE (CORE + demo-wired; panel-write loop is a follow-on) (branch `t5.5-decision-ledger`, 2026-06-17; demo-wired by **T5.5b** `t5.5b-decision-ledger-demo-wiring`, off `bc8a831`)
Append-only reviewer adjudications keyed by a deterministic finding fingerprint. Annotate-and-demote only (Invariant 5: NEVER suppress, NEVER train). **DONE = the PURE HERMETIC CORE built + hermetically tested on branch `t5.5-decision-ledger`** (the way the T5.2 cage core preceded T5.3 wiring): `agent/decision_ledger.py` — `compute_finding_fingerprint` + append-only hash-chained `DecisionLedger` (mirrors `agent/ledger.py`, reuses `compute_inputs_hash`) + cardinality-preserving `annotate_and_demote`. +32 hermetic tests → full suite **1715 passed, 1 skipped** on the branch. **NOT wired** to loop/demo/executor (follow-on slice). **Fingerprint key correction (load-bearing):** the nominal key `(error code, VatGroup, CardCode, amount band)` PREDATES the real finding shape — a `detect.issues` entry carries only `error_code` + `card_name` (no `vat_group`, no structured `card_code`, no amount; those are dropped at the detect layer and need the deferred classify↔detect reconciliation, steps.py:438-440). v0 key is therefore `FINGERPRINT_KEYS = (error_code, counterparty)` (counterparty = card_name normalized; `doc_num` excluded as too specific). **v0/PROVISIONAL — disposition vocab (KNOWN_ACCEPTED→demote+annotate; ACCEPTED/REJECTED→annotate-only) and the fingerprint key both flag for Collin/specialist** (enrichment priority: VatGroup → CardCode → amount_band). Honest limitation: without amount in the key, a known-accepted pattern carries forward regardless of magnitude — a sudden large instance renders DEMOTED (still visible, human still adjudicates), not re-promoted. Agent cannot write the ledger (Tier-2 write = absent from registry = Tier-3 for the agent); a READ, if later registered, is Tier-0. T2.11 still gates customer-facing. **T5.5b (demo wiring, mock-first, GATED):** the CORE is now CALLED — `ui/artifacts.py::annotated_adjudication_items` runs `annotate_and_demote` at view-model time over the panel's DETERMINISTIC findings (re-keyed to their counterparty-bearing `detect.issues` payload via `finding_id`), so a SEEDED prior-period `KNOWN_ACCEPTED` entry (`demo-artifacts/decision-ledger.json`, real fingerprint of the unregistered doc-592 "Far East Imports" `NO_GST_REG` finding) renders that finding DEMOTED + annotated yet STILL PRESENT (cardinality preserved, never baked into `dossiers.json`); and `make_tier2_handlers(..., decision_ledger=)` adds the Tier-2 approved-only `record_adjudication` WRITE handler (append-before-act onto the hash-chained `DecisionLedger`; `get_tier`→Tier.THREE). v0/PROVISIONAL shim: `build_adjudication_proposal` overloads the schema-pinned `ProposalArtifact` (inputs_hash=fingerprint, evidence_refs[0]={disposition,reviewer,period}, justification=reason) — a TODO flags giving it a typed carrier. +12 tests → **1727 passed, 1 skipped** on the branch. The live panel-adjudicate→append loop is a FOLLOW-ON (render-time-mutation/freeze boundary).

### T5.6 — Trigger layer — PLANNED, HARD-GATED
Cadence/period-close detection initiating Tier-1 runs whose outputs hold at Tier 2. Gates (all required): credentials scrubbed from git history (aec650f9); GCP 0.0.0.0/0 firewall closed; an always-on deployment target existing at all. Build last; lowest value per risk.

### T5.7 — Agent-behaviour eval harness — DONE (a + b) (2026-06-14)
Operationalises cross-cutting requirement (a): the scenario harness that makes "no entry advances past built without evals" executable. This is offline test/measurement infrastructure (analogous to the reasoning layer's measurement.py), NOT a production agent workflow. Built in two baskets — the cage-invariant basket (T5.7a) and the loop-quality basket (T5.7b) — both now DONE and on master. **Honest:** both baskets are hermetic + scripted; NEITHER is live-model or real-data validation; T2.11 still gates everything customer-facing.

**T5.7a — cage-invariant metrics — DONE (2026-06-14, PR #16).** `agent/eval/`: `FakeTransport` (a concrete subclass of the SDK `Transport` ABC) replays scripted streams with zero tokens / zero binary; the runner drives the REAL cage (`build_options` + the Slice-1 in-process engine server, hooks-only, engine invoker bound to a TRIPWIRE that raises if ever called); four cage-invariant metrics — justification-gate hold rate, zero-Tier-2-self-execution count, Tier-3 denial correctness, sealed-chain routing integrity — score an adversarial scenario library; `report.py` renders a scorecard with DEFERRED rows reserved for T5.7b. **Honest:** measurement infra — gates "built → validated" for the CAGE invariants but is NOT itself loop validation. +33 tests → **1479 passed, 1 skipped** (master total with T5.3 Slice 2). See `AGENTASSIST_TECHNICAL_STATE.md` §T5.7a.

**T5.7b — loop-quality metrics — DONE (2026-06-14, PR #18, commit `a24337a`).** The two previously-deferred basket metrics now land: **`dossier_completeness_rate`** (fraction of findings whose dossier reached CODE-defined completeness, `dossier.completeness["satisfied"] is True`; target `== 1.0`) and **`language_lint_pass_rate`** (fraction of `candidate_framing_text` passing `agent.lint.lint_framing`; target `== 1.0`), scored over the `FindingOutcome`s the REAL Slice-2 `run_casefile_loop` produces. They are driven over `agent/eval/loop_runner.py::ScriptedLoopTransport` — an `agent.loop.AgentTransport` that replays scripted `AgentEvent`s per finding (bounded re-entry via a per-finding `deque`) and **never touches the SDK**, distinct from T5.7a's SDK-ABC `FakeTransport`. The scorecard now renders **6 rows** (4 cage + 2 loop, the DEFERRED rows filled); `run_basket()` runs both baskets. `make_hooks` now exposes `audit_log` via a public `.audit_log` handle on the PostToolUse callback (additive; the runner no longer introspects `__closure__`). **Tech-debt (deferred):** three scripted transports now exist (`FakeTransport`, the Slice-2 loop fixture `tests/fixtures/agent_loop.py`, `ScriptedLoopTransport`); (2)+(3) overlap as a future consolidation candidate, the `FakeTransport` consolidation was deliberately deferred (different altitude). **Honest:** the loop-quality metrics pass on SCRIPTED scenarios — NOT real-data validation; T2.11 still gates customer-facing. T5.7a = cage invariants; T5.7b = loop quality; neither is live-model validation. +20 tests → **1499 passed, 1 skipped** (authoritative master total). See `AGENTASSIST_TECHNICAL_STATE.md` §T5.7b.

### T5.8 — Demo showcase UI — DONE (2026-06-16; mock-first; showcase-not-product; GATED, distinct from T4.1)
**DONE = built on master (PR #36, feat `79e451f`; T5.8b shim PR #37, feat `0f3b20a`). Built ≠ demo-validated — mock-first, showcase-not-product, GATED; nothing customer-facing until T2.11.** Mock-first, view-over-artifacts: a local Streamlit UI that visualises the agent tier model in action — ledger timeline (Tier-0/1 entries with justifications), pending proposals queue (propose→approve gate), executor dispatch log, and an adjudication panel. MockEngine/RealEngine seam (`ui/engine_seam.py`) so the UI runs against frozen fixture artifacts without a live SAP connection; **MockEngine is the default** (loads `tests/fixtures/demo-artifacts/`, no SAP/model/tokens) and **RealEngine is a lazy drop-in** over `engine.review.review` — NOT wired live in this slice.

`ui/app.py` is fixed navigation (NOT an intent router) over four views; the T5.8b `sys.path` shim makes **`streamlit run ui/app.py`** work from a fresh checkout (launch-smoke verified). `ui/artifacts.py` is a pure, headlessly-testable view-model layer with the frozen `VALIDATION_STATUS="unvalidated"` badge (never flipped by the UI). `ui/sign.py` renders the signed working paper via the EXISTING report path (`report.build_report`→`render_pdf`) with **`show_ai_candidates` RESPECTED** (read from YAML, default False), no secrets (empty-credential demo `ClientConfig`), and box-isolation (renders from frozen `compile_output`, never recomputes F5 boxes). A build-time `freeze()` (runs the real Slice-2 loop once) vs render-time boundary is guarded by a schema-stability tripwire; the Mock+Sign path imports no `anthropic`/SDK/`agent.loop` (guard-tested).

**This is EXPLICITLY a showcase tool, NOT the T4.1 production platform.** Its purpose is to make agent-tier mechanics visible and debuggable during T5.3/T5.4/T5.5 development, and to demonstrate the bounded-autonomy model to stakeholders without requiring a live engagement. It does not address the distribution bottleneck (T4.1's gate). Owner: Terry. Effort: ~1 wk (Streamlit local; no production deployment). See `AGENTASSIST_TECHNICAL_STATE.md` §T5.8.

**T5.8c — demo convergence: real frozen-extract-derived vendor ctx — DONE (2026-06-16, branch `t5.8c-demo-loopcontext-converge`).** The demo freezer's `build_context` (`tests/fixtures/demo_artifacts_builder.py`) no longer fabricates the vendor catalog; it now sources it from the T5.3h assembler `agent.loop_context.build_vendor_catalog` over the frozen `sbodemosg-extract` business-partners surface — **real frozen-extract-derived vendor ctx, not live SAP / real-client data**. Hermetic (no SAP, no model, no tokens); MockEngine/RealEngine boundary untouched; source-doc provider stays `FakeProvider`. The 7 `NO_GST_REG` findings are genuinely unregistered in the extract, so their `supplier_catalog` evidence is byte-unchanged (`dossiers.json`/`review_result.json` identical); regenerated `proposals.json`/`ledger.json` differ only in volatile ids/timestamps/hashes. Frozen flags + token-gating untouched. +2 tests (`tests/test_t58_real_vendor_ctx.py`), full suite **1641 passed, 1 skipped**.

**On the horizon — RealEngine ← T5.3h convergence (not yet scheduled).** T5.8's `RealEngine` seam (`ui/engine_seam.py`, currently a lazy drop-in over `engine.review.review`) and T5.3h's real `BuiltLoopContext` (`agent/loop_context.py`) are the two halves of a real (non-mock) demo. The convergence step is to feed a `build_loop_context`-driven `run_casefile_loop` through `RealEngine` so the UI renders REAL findings/dossiers instead of frozen artifacts — a configuration wiring, not a rewrite. It stays GATED behind the same caveats (NOT live-validated until T5.3-V round-2 + T5.3g; NOT accuracy-validated until T2.11) and is out of scope for the current showcase slice.

### T5.9 — Intent surface (end-user) — T5.9a/b/c/d DONE, GATED ON THE DEMO (not a paying customer)
Owner Terry. Effort PROPOSED — needs Terry confirmation. Sequenced AFTER T5.4.

**The end-user-facing intent surface** — the front door through which a user expresses what they
want done, mapped onto the bounded, tier-classified action sequences the cage already enforces
(Invariant 6). **Pulled forward to pre-demo, decoupled from the paying-customer gate.**
**Rationale:** this is product-intrinsic UX, not a delivery-model feature; the prior paying-pilot
gate conflated a product feature (how an end user drives the bounded autonomy) with the delivery
model (who pays and how). The SURFACE earns its build for the demo; the multi-vertical PLATFORM
(T4.1) it eventually fronts stays gated — see the Invariant 6 amendment and the T4.1 entry.

**Explicitly NOT T5.4.** T5.9 (the end-user intent surface — how a human expresses intent into the
bounded menu) is a different task from T5.4 (the check planner — internal selection/sequencing of
which deterministic checks run given the client profile). T5.4 routes *checks* inside the engine;
T5.9 routes a *human's expressed intent* onto a bounded action sequence. T5.9 depends on T5.4 (the
menu's intents map onto the planner's check sequences) and is sequenced after it. Naming the
distinction is deliberate — the two are easy to conflate and must not be.

**Three slices:**
- **T5.9a — bounded intent menu + dispatch — DONE (2026-06-17, branch `t5.9a-intent-surface`;
  built + hermetically tested; NOT live/accuracy validated).** `agent/intent.py` is the FIXED
  `INTENT_MENU` (v0/PROVISIONAL: `RUN_REVIEW`→`run_review_chain` [Tier 1]; `SHOW_LEDGER`,
  `SHOW_PROPOSALS`→`read_ledger` [Tier 0]; `SHOW_PRIOR_ADJUDICATIONS`→`read_prior_period_treatment`
  [Tier 0]) plus a deterministic `dispatch(intent, params)` router. This is Invariant 6's "fixed
  menu of intents mapping to tier-classified action sequences" made into a surface — **"the menu is
  the cage at the product layer."** Two structural guarantees, the T5.9 twins of the planner's
  ⊆-registry: (1) **⊆-MENU** — `dispatch` asserts `intent ∈ INTENT_MENU` (else `IntentError`; a raw
  tool name is not an intent), and a build-time check asserts every menu action is a real registry
  tool (`get_tier(action) is not Tier.THREE`); (2) **no tier escalation** — `DispatchResult.tiers`
  is READ from `registry.get_tier` per action, never assigned, so the surface dispatches only to the
  registry's existing Tier-0/1 actions (never a Tier-2 effect — that stays behind `propose_action` +
  human approval — never a Tier-3 absent action). Identity-bearing slots are never guessed: a missing
  or blank `client_id`/`period` yields a structured `NeedsClarification`, not a fabricated default.
  Failing-test-first; `agent/` purity (orchestrator/ imports nothing from agent/; zero
  anthropic/SDK/SAP/network). NO NL classifier (T5.9b) and NO chat UI (T5.9b/c) here; `INTENT_MENU`
  is v0/PROVISIONAL. `SHOW_PROPOSALS` shares the Tier-0 `read_ledger` with `SHOW_LEDGER` because no
  dedicated proposals-read tool exists yet (proposals are staged/ledgered) — distinct intents, same
  in-tier read, no added authority. +29 tests (`tests/test_t59a_intent_surface.py`), full suite
  **1744 passed, 1 skipped**. T2.11 still gates customer-facing; T4.1 platform stays gated. See
  `AGENTASSIST_TECHNICAL_STATE.md` §T5.9a.
- **T5.9a1 — menu correction: honest routing for SHOW_PROPOSALS + SHOW_PRIOR_ADJUDICATIONS — DONE
  (2026-06-17, branch `t5.9a1-menu-correction`; hermetic).** T5.9a routed two intents to the WRONG
  tool: `SHOW_PROPOSALS`→`read_ledger` (the justification ledger is NOT the pending-proposals queue)
  and `SHOW_PRIOR_ADJUDICATIONS`→`read_prior_period_treatment` (a per-key prior-period store, NOT the
  T5.5 decision ledger). This slice registered two semantically-correct Tier-0 reads in
  `agent/registry.py` — `read_proposals` (wraps `StagingStore.list_pending`) and
  `read_decision_ledger` (wraps `DecisionLedger.lookup` by finding fingerprint; list-all when
  omitted), both pure Tier-0 reads in `agent/read_tools.py` — and rewired the two intents so all four
  dispatch honestly (`SHOW_LEDGER` ≠ `SHOW_PROPOSALS` routing proven; conflation gone). Menu-integrity
  (`_assert_menu_well_formed`) holds. **v0/PROVISIONAL menu gap flagged:** `SHOW_PRIOR_ADJUDICATIONS`
  still declares `(client_id, period)` but `read_decision_ledger`'s only axis is the per-finding
  fingerprint (the T5.5 ledger has no client field) — they reconcile later via a
  `client/period → findings → fingerprints` lookup or an explicit fingerprint slot. Failing-test-first;
  +11 tests (`tests/test_t59a1_menu_correction.py`); over-broad T5.5 write-guard narrowed to its
  documented intent (no adjudication-WRITE tool; a Tier-0 READ helper is allowed). Full suite
  **1770 passed, 1 skipped**. INTENT_MENU still v0/PROVISIONAL; NOT live/accuracy validated; no NL
  classifier / chat UI here. See `AGENTASSIST_TECHNICAL_STATE.md` §T5.9a.
- **T5.9b — NL classifier + clarify-on-miss — DONE (2026-06-17, branch `t5.9b-nl-classifier`;
  classifier BUILT + hermetically tested via a scripted backend; LIVE backend built but accuracy
  measured in T5.9c, NOT here).** `agent/intent_classifier.py` is the natural-language front door —
  the ONE model-bearing piece of the intent surface. `IntentClassifier(backend).classify(utterance,
  menu)` maps a free-text utterance onto the FIXED `INTENT_MENU` and returns a VALIDATED
  `ClassificationResult = Classified(intent ∈ menu, candidate_params) | NeedsClarification |
  OutOfScope` that feeds `agent.intent.dispatch` UNCHANGED. It **classifies, it never obeys**:
  classify-never-obey is STRUCTURAL via two independent guards — (1) the live backend's call is a
  single constrained `messages.create` with ONE forced structured-output tool and NO executable
  tools (`claude-haiku-4-5-20251001`, v0/PROVISIONAL), so the model can only EMIT a label; (2)
  **⊆-MENU AT THE BOUNDARY** (`_enforce_menu_boundary`, PURE) validates every backend's raw label
  against `INTENT_MENU` before return — an off-menu / hallucinated intent (even a raw tool name) is
  REJECTED to `OutOfScope`, and candidate params are RESTRICTED to the bound intent's declared
  `required_params`. The slot set IS exactly the intent's declared `required_params`: the classifier
  **NEVER guesses identity-bearing slots (client / period)** — absent/blank → `NeedsClarification` —
  and **never extracts a `fingerprint` nor attempts the `client/period → fingerprint` reconciliation**
  (that v0/PROVISIONAL menu gap, recorded in `agent.intent` by T5.9a1, stays DOWNSTREAM of this
  slice — dispatch-execution, not yet built — and is deliberately NOT "fixed" here). The model sits
  behind a `ClassifierBackend` seam with a SCRIPTED fake (every test uses it — zero tokens); the live
  backend imports `anthropic` lazily/confined (`agent/intent.py` stays pure; `agent/intent_classifier.py`
  is the only new `anthropic` importer, permitted in `agent/` per `docs/merge-gates.md`). Untrusted-input
  discipline holds: free text is untrusted input to a tool-bearing system (the Collin reconciliation in
  Invariant 6); unconstrained LLM-to-tool chaining inside the product stays forbidden. Failing-test-
  first; +37 tests (`tests/test_t59b_nl_classifier.py`: clear→Classified→dispatch; missing/ambiguous→
  clarify-never-guess; out-of-scope; injection contained; off-menu backend→OutOfScope; prior-adjudications
  declared-slots-only/no-fingerprint; hermetic live-backend parse + named import-scan checks), full suite
  **1807 passed, 1 skipped**. NO chat UI (T5.9c); not live/accuracy validated; T2.11 gates customer-facing.
  See `AGENTASSIST_TECHNICAL_STATE.md` §T5.9b.
- **T5.9c — demo hardening: classifier command bar into the review surface + routing-accuracy eval —
  DONE (2026-06-17, branch `t5.9c-demo-chatbot`; demo command bar MOCK-wired, routing-accuracy eval
  OPT-IN/tokened).** The chatbot front door: the T5.9b classifier (over the T5.9a/a1 menu) is wired
  into the T5.8d review surface as a quiet command bar ("one way in"; review still happens on the
  dashboard). MOCK-FIRST — the demo command bar uses `IntentClassifier(ScriptedClassifierBackend(curated))`
  ONLY (canned answers for a curated utterance set; NO live model, NO tokens in the demo path) + a
  buttons fallback (the four menu intents as buttons; zero typing). A `Classified` intent maps to WHICH
  review-surface SECTION to open (`RUN_REVIEW`→Review queue, `SHOW_LEDGER`→Justification ledger,
  `SHOW_PROPOSALS`→PENDING proposals, `SHOW_PRIOR_ADJUDICATIONS`→Adjudication panel); `NeedsClarification`
  →inline clarify (never guess client/period); `OutOfScope`→polite message + buttons. It maps
  intent→section, it does NOT execute the read tools (dispatch-EXECUTION is downstream; the
  client/period→fingerprint gap stays untouched). classify-never-obey holds in the demo via the SAME
  ⊆-menu boundary — a HOSTILE backend output (a raw registry tool name claimed as an "intent") is
  contained to `OutOfScope`, never an action. Separately, a curated-utterance ROUTING-ACCURACY eval
  (`agent/eval/intent_routing.py`, OUTSIDE `ui/`) measures the LIVE Haiku backend: hermetic scripted
  path scores 100% (SANITY only); opt-in/env-gated (`INTENT_ROUTING_LIVE=1` + `ANTHROPIC_API_KEY`,
  TOKENED) live run scores a basket (per-intent accuracy, clarify precision/recall, out-of-scope recall,
  injection containment) with raw outputs saved as evidence BEFORE scoring. This is **ROUTING accuracy
  (utterance→intent), NOT GST-truth** — distinct from T2.11, needs no accredited specialist. The curated
  set is AUTHOR-CONSTRUCTED and SMALL (~2/cell), so the basket is a **smoke/repertoire sanity measure,
  NOT a generalization claim** — a real routing number needs a larger independently-sourced set; the set
  is EVAL-ONLY, never training. Failing-test-first; **+13 tests** (`tests/test_t59c_demo_chatbot.py`,
  all hermetic): Classified→section; missing-slot→clarify-never-guess; out-of-scope→polite+buttons-never-
  tool; injection contained incl. the hostile raw-tool-name backend output; buttons dispatch the four
  intents directly; scripted eval 100% sanity; + NAMED import-scans (`ui/` no-anthropic; eval harness the
  only `AnthropicClassifierBackend` toucher, deferred; `orchestrator/` purity unchanged). Full suite
  **1829 passed, 1 skipped** (origin/master `b9901b3` baseline 1817 collected + 13). NOT live/accuracy
  validated; demo command bar robust without a live model; T2.11 gates customer-facing; T4.1 platform
  stays gated. See `AGENTASSIST_TECHNICAL_STATE.md` §T5.9c.
- **T5.9d — dispatch-execution: pure module surfaced at C2 — DONE (2026-06-18, branch
  `t5.9d-dispatch-execution`; hermetic over frozen artifacts).** Lane A. T5.9a's `dispatch` returns an
  intent's tier-classified SEQUENCE but executes nothing; T5.9c only routes a `Classified` intent to a
  review-surface SECTION. This slice adds `agent/dispatch_exec.py::execute_intent(intent, params, *,
  artifacts, engine=None) -> ExecutionResult` — a PURE, framework-free executor that actually RUNS the
  Tier-0 read(s) / RUN_REVIEW over the FROZEN artifacts and returns a serialisable record. **No surface
  wiring** — the production surface is React (Lane C1); this is surfaced later by the React API's
  `POST /command` (Lane C2), NOT Streamlit (building it pure is what lets Lanes A/B/C1 run with zero
  file overlap). Routes: `SHOW_LEDGER`→`read_ledger` (frozen justification ledger); `SHOW_PROPOSALS`→
  `read_proposals` (frozen staging store rehydrated to `ProposalArtifact`s); `SHOW_PRIOR_ADJUDICATIONS`→
  `read_decision_ledger` **LIST-ALL**; `RUN_REVIEW`→the FROZEN engine (frozen dossiers + F5 summary; no
  live chain, no SAP). Blank `client_id`/`period` → router's `NeedsClarification` passed through (never
  guess). **`read_ledger` gap closed (option B):** the registry's long-declared Tier-0 `read_ledger`
  ToolSpec had no impl — added `read_ledger(ledger: list[dict])` to `agent/read_tools.py` so all four
  intents run via a real read tool. **v0 menu gap honoured, not fabricated:** `SHOW_PRIOR_ADJUDICATIONS`
  declares `(client_id, period)` but the decision ledger has no client field (only the per-finding
  fingerprint), so the executor lists ALL adjudications and FLAGS it in `ExecutionResult.notes`; the
  bound params do NOT filter and no client/period→fingerprint mapping is invented (a test asserts a
  different period returns identical rows). Decoupled from `ui/` by design (owns its frozen-artifact
  loader + `FrozenEngine`, twins of the `ui` ones). Failing-test-first; **+21 tests**
  (`tests/test_t59d_dispatch_exec.py`, all hermetic): each intent returns the REAL frozen rows;
  RUN_REVIEW returns frozen engine output (no SAP/live chain); NeedsClarification passthrough; unknown
  intent/raw tool name → `IntentError`; box-isolation (F5 boxes + gate_results byte-identical
  before/after + mutation isolation); purity import-scan (AST: no anthropic/streamlit/fastapi/network/
  SAP/orchestrator/ui); JSON-serialisable. Full suite **1871 passed, 1 skipped** (origin/master
  `95c6ff7` baseline 1850 + 21). `orchestrator/` untouched. Built + hermetically tested over FROZEN
  artifacts; surfaced at C2; NOT live/accuracy validated; T2.11 gates customer-facing; T4.1 platform
  stays gated. See `AGENTASSIST_TECHNICAL_STATE.md` §T5.9d.

- **T6.1 — React review surface + FastAPI seam (Lane C1) — DONE (2026-06-18, branch
  `t6.1-frontend-review-surface`; built over FROZEN artifacts; NOT demo/accuracy-validated).** A
  production-shaped **React + TypeScript (Vite)** review surface under `frontend/` over a thin
  **FastAPI** seam under `api/`, rendering the SAME frozen SBODEMOSG artifacts the Streamlit T5.8d demo
  uses — SERVE/PRESENTATION only, no engine/model/SAP/tokens. Backend (`api/viewmodel.py` +
  `api/app.py`): `GET /review/{client}/{period}` (real frozen queue via `annotated_adjudication_items`,
  demoted flagged; 404 for anything but `sbodemosg`/`2024Q3`), `POST /sign` (reproduces
  `ui.sign.sign_working_paper`, carries reviewer name, **box-isolation preserved**), `GET /audit`. The
  exported `*_KEYS` tuples are the single source of truth for the key set the TS client mirrors (pinned
  by a contract test). Frontend: `TopBar`/`CommandBar`/`Queue`/`FindingDetail`/`AuditTrail`/`SignModal`,
  clay-paper aesthetic (Newsreader/Inter/IBM Plex Mono) lifted from the target mock — **data is the real
  frozen output, not the mock's fictional findings.** Renders ONLY real check types
  (E1/NO_GST_REG/E2/gst_amount_mismatch = 21 rows); the genuinely-seeded **doc-592 NO_GST_REG "Far East
  Imports"** entry renders demoted-but-present under *Marked known* (T5.5b); the mock's **DUP_CLAIM /
  SEQ_GAP / FLUX never appear**. All four trust signals preserved (UNVALIDATED badge, "AgentAssist flags
  — you decide", reviewer-name-on-sign, illustrative-IRAS-citation caveat). **Command bar is an INERT
  shell — classify+execute is Lane C2 (deferred, gated on Lanes A + B).** CI stays **pytest-only**;
  `fastapi`+`uvicorn` added to `requirements.txt`; the frontend `vitest`/build is a **separate
  optional/local** job (no Node job added to `ci.yml`). Failing-test-first: **+11 pytest**
  (`tests/test_t61_frontend_api.py`: real frozen shape; doc-592 present+demoted; no fictional types;
  sign box-isolation + reviewer name; contract test; AST no-anthropic import-scan) + **+4 vitest** render
  smoke. Full pytest suite **1861 passed, 1 skipped**; `tsc --noEmit` + `vite build` green. Built ≠
  demo-validated ≠ accuracy-validated; IRAS citations unvalidated; T2.11 gates customer-facing. See
  `AGENTASSIST_TECHNICAL_STATE.md` §T6.1.

**Honest caveat:** the intent surface ROUTES TO UNVALIDATED machinery. `show_ai_candidates` stays
`False`; the demo shows **bounded autonomy + human-in-the-loop, NOT validated accuracy.** T2.11
still gates anything customer-facing. The surface makes the bounded-autonomy model drivable and
visible; it changes nothing about what is or is not validated underneath.

**Missing-data handling:** mid-task missing-data handling is the T5.3 completeness mechanism; the
interactive request-resume loop is a separate GAP gated on document ingestion — see
`operational-backlog.md`.

### Tier-5 cross-cutting requirements
(a) Agent-behavior evals: the honest-status taxonomy (built ≠ unit-tested ≠ demo-validated ≠ real-client-validated) applies to agent BEHAVIORS. Scenario eval harness with fixed fixtures measuring: dossier completeness rate, justification-gate hold rate, zero Tier-2 self-executions over N adversarial runs, language-lint pass rate. No entry above advances past "built" without it. Build deliverable: T5.7.
(b) Prompt-injection resistance: once the agent reads client documents, every vendor PDF is untrusted input to a tool-bearing system. Injection fixtures (adversarial instructions embedded in invoice descriptions/PDF text) are a mandatory eval category. The tier system is the structural containment (worst case: a poisoned proposal a human reads).
(c) System prompt / procedure-packaging / tools / hooks stack: system prompt = standing constitution (role, tier rules stated, language contract, escalation); per-procedure packages = versioned modules pairing a code-defined completeness checklist with a prompt template (e.g. E2-dossier assembly), independently eval-able. Near-term these are plain versioned modules, NOT the formal Agent Skill abstraction — which stays gated per Final Architectural Reminder #5 (introduce Skills only when the product expands beyond one workflow, post-validation). When that gate is met these packages are the natural unit to graduate into Skills and the unit of cross-vertical reuse. tools = tier-classified actions; hooks = enforcement. Vertical generalisation: shell + procedure-packaging pattern reuse; each new vertical re-pays its own deterministic core + knowledge base + independent validation.
(d) Honesty flags (verbatim): "junior accountant" is internal design language only — customer-facing it is "automated evidence assembly with human-controlled actions" until behavior evals and T2.11 exist. The agent adds nondeterminism to a product whose pitch is determinism; containment is architectural (agent artifacts in labelled sections; sealed chain output never agent-touched). Nothing in Tier 5 accelerates T2.11.

---

## Documentation tasks

### D1 — Update `AGENTASSIST_TECHNICAL_STATE.md` for the reasoning layer — DONE (2026-06-08, on T2.7 branch)
The canonical doc was reconciled against the repo: reasoning layer documented as branch-only (`t2.7-reasoning-reg2627`), `show_ai_candidates` wiring with line refs, provisional measurement marked UNVALIDATED, harness status updated, the 110 figure resolved as a 110-LINE fixture (not 110 invoices). Verify the diff and the second-modified-file (`v3` roadmap working-tree change) before committing.

### D2 — Document the `reasoning/` layer (T2.7 branch) — PLANNED
Mirror the deterministic-script docs for the reasoning layer; Document 4 of the coverage analysis is the conceptual basis. Capture what gaps it fills, the J+ ceiling, the two gates, and the validation status.

### D3 — Update canonical docs for T2.8 + re-derived baseline — DONE (2026-06-08, on T2.8 branch)
`AGENTASSIST_TECHNICAL_STATE.md`: T2.8 section added (`documents/` package, B1 attachment BLOCKER, seed record, `UnifiedCandidatesSection`, CLI flags, isolation invariant, validation status, 4 new test files); Appendix B third table added (post-T2.8-seeds Box 8 = 12,663.87); Box 8 reconciliation note added (authoritative pre-T2.8 = 17,045.87; 17,395.87 = pre-T1.x-seeds; delta explained); Appendix C #25 PDPA expanded with data-intermediary/overseas-transfer/residency/ZDR specifics; #28 legibility gate and #29 automation-bias guard added; exec summary and test count updated; repo tree updated for `documents/`, `scripts/seed*`, and T2.8 test files; footer updated. Roadmap: T2.8 marked DONE with caveats; T2.14 and T2.15 added; T3.2 expanded with confirmed PDPA specifics; build-state snapshot updated; D3 added.

### D4 — Update canonical docs for T2.10 — DONE (2026-06-10, on master post-merge)
`AGENTASSIST_TECHNICAL_STATE.md`: T2.10 section added (SEQ_GAP + DUP_CLAIM + ZP E2, chain wiring, BOX-ISOLATION, smoke run, honest-status block, 61 new tests; test count updated to 1087/1). Roadmap: T2.10 entry updated from PLANNED to DONE; build-state snapshot and test count updated; T2.10-V (positive-detection validation) added as PLANNED. Coverage analysis (`iras-ask-coverage-analysis.md`): 3A.1.c, 3B.1.b, 3C-1.b (SEQ_GAP) and 3D.1.1.d (DUP_CLAIM) updated from "not built" to plumbing-demonstrated; known-limitations T2.10 bullet added.

**Pre-merge gate protocol** for all future branches is codified in `docs/merge-gates.md` (gates a–d: no-anthropic-import regex, full-suite green, isolation invariant, clean tree). Gate-a uses import-only regex to avoid false positives on docstrings. Run all four gates from `docs/merge-gates.md` before any merge to master — do not re-describe them here.

### D5 — Update canonical docs for T2.9-V — DONE (2026-06-10, on master)
`AGENTASSIST_TECHNICAL_STATE.md`: T2.9 section — "Validation (T2.9-V)" subsection added (3-fixture scenario test, 22 assertions, box-isolation, report section, mandatory rounding-convention caveat); exec summary updated with T2.9-V summary; test count updated to 1104/1; T1.5 test-count line updated. Roadmap: T2.9-V marked DONE (mechanism validated; rounding convention pending cousin); build-state snapshot T2.9 entry updated; test count 1087 → 1104. Coverage analysis (`iras-ask-coverage-analysis.md`): Step 1 declared-vs-computed cells (1.3b, 1.3c) and Step 3 listing-reconciliation cells (3A.1.a, 3B.1.a, 3C.1.a, 3D.1.1.a) graduated from "BUILT, UNVALIDATED — pending T2.9-V" to "mechanism validated on demo; renders when filed F5 supplied; rounding/tolerance convention unconfirmed"; cells stay ◐ (not unconditionally covered); known-limitations note updated.

### D6 — Update canonical docs for T2.10-V — DONE (2026-06-10, on master)
`AGENTASSIST_TECHNICAL_STATE.md`: T2.10 section — "Validation (T2.10-V)" subsection added (crafted-input full-chain, SEQ_GAP period-boundary discriminating case 8003, DUP_CLAIM pair vs near-miss, 52 new tests, live zero-FP on SBODEMOSG, mandatory caveats); status table updated (plumbing-demonstrated → positive-detection validated on synthetic; report-rendered); honest-qualifier block updated; `listing_findings` note updated; exec summary updated with T2.10-V; test count updated 1104 → 1156; T1.5 master-total line updated. Roadmap: T2.10-V marked DONE; T2.10 entry header updated; honest qualifier updated; build-state snapshot test count 1104 → 1156. Coverage analysis (`iras-ask-coverage-analysis.md`): 3A.1.c, 3B.1.b, 3C-1.b (SEQ_GAP) and 3D.1.1.d (DUP_CLAIM) graduated from "plumbing-demonstrated; positive-detection not validated on live SAP; no PDF report section yet" to "positive-detection validated on synthetic cases; renders when present; live zero-FP on demo; NOT validated on real client data"; known-limitations T2.10 bullet updated.

### D7 — Doc-sync for CI self-provisioning, report header rename, synthetic demo, Check A float-robustness, report styling — DONE (2026-06-10, on master)
`AGENTASSIST_TECHNICAL_STATE.md`: exec summary updated (CI self-provisioning note, report header rename, synthetic demo SYNTHETIC caveat, Check A float-robustness, report styling normalization, test count 1156 → 1161); repo tree updated (`infra/` + `demo-scenario/` added); T1.5 master total updated (1156 → 1161); Check A float-robustness subsection added to T2.9 (cent-quantized Decimal, framing that it does NOT resolve IRAS convention, 5 `[A-FP]` tests); T2.10-V report section heading rename noted; standalone "Report styling normalization" section added; footer updated with D7 entry. Roadmap: build-state snapshot test count 1156 → 1161 and new items added (CI, demo, Check A, styling); T2.9 Check A float-robustness note added; T2.10-V PDF section heading rename noted; D7 added. Coverage analysis (`iras-ask-coverage-analysis.md`): no Check A comparison-semantics statement found — **no change required**. Declared-vs-computed cells stay ◐ (rounding-convention confirmation still the cousin task; cent-quantization resolves our internal arithmetic only, NOT the IRAS F5 filing convention question).

### D9 — T5.2 post-cage docs-sync — DONE (2026-06-12, branch t5.2-postcage-docsync)
`docs/merge-gates.md`: Gate a extended to include `agent/` in the orchestrator forbidden-imports list (Check 2 pattern updated); explicit "agent/ IS allowed the SDK" note added to prevent incorrect re-restriction; allowed/forbidden table added; Gate b updated with flake8 CI selectors as mandatory local pre-push check + F824 lesson documented; Gate e added (agentic-cage invariants 1/2/3/7 graduated from roadmap as enforced gates with verification steps); CI automated import-scan step noted.
`.github/workflows/ci.yml`: Import-scan step added (CHANGE-2 — the only code-behaviour change): fails build if `orchestrator/` imports anthropic/reasoning/documents/agent; mirrors Gate a exactly.
`AGENTASSIST_TECHNICAL_STATE.md`: T5.2 section added after T2.17 (T5.2a: registry/tiers/justification/ledger/proposals/executor/budget; CheckSpec v0/PROVISIONAL 14 entries; T5.2b: hooks/harness/approve_cli; Ledger.from_entries; seal.py agent-ledger.json integration; deferred-to-T5.3 table); first runtime dep `claude-agent-sdk==0.2.99` documented with cross-platform note; honest status: cage built + hermetically unit-tested, NO live loop, seal/emit stubs deferred T5.3; exec summary updated; T1.5 master total updated 1211 → 1372; T2.17 test count line updated; footer D9 added.
Roadmap: T5.2 marked DONE (honest qualifier: cage built + unit-tested; NOT demo-validated; no live loop; seal/emit + loop are T5.3); T5.2c added (check-registry contract, sequenced after T2.18, CheckSpec PROVISIONAL until then, co-designed with Collin); T5.8 added (Demo showcase UI, mock-first Streamlit, MockEngine/RealEngine seam, GATED showcase-not-product); invariant 6 input-surface note added (free-text front door + intent router + clarify-on-miss, Collin reconciliation); invariants header updated (graduated to merge-gates.md).
`knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** The Tier-5 cage (action tiers, justification ledger, SDK-hook enforcement) does not affect VatGroup → F5-box routing, zero-rating rules, or any accounting-domain content in this file.

### D10 — T5.1 engine-seam docs-sync — DONE (2026-06-12, branch t5.1-docsync)
`AGENTASSIST_TECHNICAL_STATE.md`: T5.1 section added between T2.17 and T5.2 (`engine/` package; `review(client_config, period, inputs) → ReviewResult` contract; `ReviewResult` 11 fields incl. `analytical_review_data`; `ReviewInputs` 4 fields / source-adapter seam / SAP wired only / deep substitution is T2.12; `GateHalt(message, checked)` plain serialisable record; thin CLI; `review()` is SILENT; `engine/__init__` no-re-export-of-`review` note; import-scan gate; honest qualifier); exec summary updated (T5.1 paragraph + test count 1372 → 1387); T1.5 master total updated; T2.17 test count line updated; footer D10 added.
Roadmap: T5.1 marked DONE (honest qualifier: behavior-preserving refactor; built+unit-tested; NOT demo-validated; no agent loop; SAP wired only; T2.12/T2.11/T5.3 caveats); build-state snapshot updated with T5.1 bullet + test count 1387; T5.2 honest-qualifier test count clarified (1372 at T5.2 merge; 1387 after T5.1); D10 added.
`docs/merge-gates.md`: **verified correct — no change required.** Gate a Check 2 already includes `engine/` in the `orchestrator/` forbidden-imports list (updated in the T5.1 build PR, commit `134d8db`). History bullet already present.
`knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** The T5.1 engine seam is a packaging refactor only. It does not touch VatGroup → F5-box routing, zero-rating rules, or any accounting-domain content in this file.

### D11 — T5.3 SDK-runtime docs-sync — DONE (2026-06-14, branch t5.3-sdk-docsync)
Corrects the inaccurate Linux-CI install claim for `claude-agent-sdk==0.2.99`. Verified finding: the `manylinux_2_17_x86_64` wheel BUNDLES the Linux `claude` binary at `_bundled/claude` (CLI 2.1.175 > the SDK's 2.0.0 floor); on `ubuntu-latest` pip selects the WHEEL, not the sdist, so `pip install` auto-provisions the binary — no `npm install`, no `cli_path`, no env var; pin holds at 0.2.99. Caveat: no musllinux wheel, so an Alpine runner falls back to the binary-less sdist and fails at `query()` call time — keep CI on glibc (`ubuntu-latest`) and assert `_bundled/claude` post-install. Test seam: `query()`/`ClaudeSDKClient` accept a custom `transport=`, so the hermetic suite injects a FakeTransport (no binary, no tokens); any live-in-CI loop is opt-in (`workflow_dispatch`) and burns real tokens.
`AGENTASSIST_TECHNICAL_STATE.md`: false "builds from sdist" claim removed from all three occurrences (exec-summary paragraph, §T5.2b Cross-platform note, footer); full corrected finding stated ONCE in the §T5.2b Cross-platform note; exec-summary carries a brief accurate pointer; footer D11 added. Docs-only; test count unchanged (1387/1).
Roadmap: T5.2 entry SDK-dependency bullet corrected (brief accurate version, no sdist claim); T5.3 entry SDK-runtime blocker marked RESOLVED (manylinux wheel bundles the binary; pin holds; Alpine caveat) with T5.3 remaining PLANNED pending the build; D11 added.
`knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** The SDK wheel/binary-provisioning finding is infrastructure only. It does not touch VatGroup → F5-box routing, zero-rating rules, or any accounting-domain content in this file.

### D12 — T5.3 (Slice 1 + Slice 2) + T5.7a docs-sync — DONE (2026-06-14, branch t5.3-t5.7a-docsync)
Verification-first: read the merged code on master (engine-tool bridge + `make_tier2_handlers` + 3 Tier-0 reads + MCP-prefix-aware `get_tier`; `agent/loop.py` + `completeness.py` + `lint.py` + `dossier.py` + additive `compute_inputs_hash`; `agent/eval/` subpackage) and ran the full suite once before writing — authoritative count **1479 passed, 1 skipped**.
`AGENTASSIST_TECHNICAL_STATE.md`: T5.3 section added (Slice 1 engine-tool plumbing — `review()` as ONE atomic MCP tool, no sub-step reachable, MCP-prefix-aware `get_tier()`, approved-only seal/emit via `extra_handlers`, 3 new Tier-0 reads, SEALED-CHAIN routing locked + lean recorded; Slice 2 case-file loop — plain-Python gather→act→verify driver / model invoked within never drives, CODE-DEFINED completeness checklist keyed to `CheckSpec.inputs_needed`, deterministic language-lint brittle backstop, `DossierArtifact`, `compute_inputs_hash`, `cost_usd_used` ledger COGS, budget-exceeded invariant-7 non-blocking, prompt-injection containment); T5.7a section added (`agent/eval/` — FakeTransport SDK-ABC subclass, runner over REAL cage with tripwire'd engine invoker, 4 cage-invariant metrics, adversarial scenario library, scorecard; honest measurement-infra qualifier; loop-quality metrics deferred T5.7b); exec summary running-count paragraphs + master-total line updated 1387 → 1479; footer D12 added.
Roadmap: T5.3 entry PLANNED → DONE (Slice 1 + Slice 2; built + hermetically tested, NOT validated; sealed-chain lean recorded; honest caveats); T5.7 split — T5.7a DONE (cage-invariant metrics), T5.7b REMAINING (loop-quality metrics, now unblocked since the loop exists); build-state snapshot updated with T5.2/T5.3/T5.7a bullets + test count → 1479; D12 added.
`docs/merge-gates.md`: **checked — no change required.** Gate a already bars `orchestrator/` from importing `agent/` + `engine/`, and `agent/eval/` is covered as part of `agent/` (the orchestrator forbidden-imports pattern matches the `agent` package prefix). No new package boundary introduced.
`knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** T5.3/T5.7a are agentic-shell infrastructure and do not touch VatGroup → F5-box routing, zero-rating rules, or any accounting-domain content.
`exploration-notes/iras-ask-coverage-analysis.md`: **checked — no change required.** T5.3/T5.7a add the agent loop + its measurement harness; they do not change any deterministic IRAS-ASK coverage cell.
Pedagogical reference docs (`accounting-domain-knowledge` / `technical-understanding`): **NOT found in the repo** — searched by name and content across all `.md` files; the only "accounting-domain" references are descriptions of `sg-tax-code-mappings.md`. Reported rather than guessing a path; step 3 edits skipped.

### D13 — T5.7b loop-quality-metrics docs-sync — DONE (2026-06-15, branch t5.7b-docsync)
Verification-first: confirmed T5.7b on master (PR #18, commit `a24337a`) and read the merged code (`agent/eval/loop_runner.py` `ScriptedLoopTransport`; `agent/eval/metrics.py` `dossier_completeness_rate` + `language_lint_pass_rate`; `agent/eval/report.py` 6-row scorecard; `agent/hooks.py` + `agent/eval/runner.py` public `.audit_log` handle, no `__closure__` introspection) before writing; ran the full suite once — authoritative count **1499 passed, 1 skipped**; flake8 `E9,F63,F7,F82` clean.
`AGENTASSIST_TECHNICAL_STATE.md`: §T5.7b added (ScriptedLoopTransport drives the REAL `run_casefile_loop` and never touches the SDK; two loop-quality metrics; scorecard 6 rows = 4 cage + 2 loop with the DEFERRED rows filled; `make_hooks` public `.audit_log` handle, runner no longer introspects `__closure__`; 3-transports tech-debt with `FakeTransport` consolidation deferred); exec summary + master-total line updated 1479 → 1499; §T5.7a reference line updated; footer D13 added. Honest qualifier: loop-quality metrics pass on SCRIPTED scenarios, NOT real-data validation; T2.11 gates customer-facing; T5.7a = cage invariants, T5.7b = loop quality, neither is live-model validation.
Roadmap: T5.7 heading SPLIT → **DONE (a + b)**; T5.7b block REMAINING → DONE with merged facts + scripted-not-real qualifier; build-state snapshot T5.7b bullet added + count → 1499; D13 added.
`exploration-notes/iras-ask-coverage-analysis.md`: **checked — no change required.** T5.7b is agent-eval infra (loop-quality measurement) and changes no deterministic IRAS-ASK coverage cell.
`docs/merge-gates.md`: **checked — no change required.** Gate a already covers `agent/eval/` as part of `agent/`; Gate e covers any `agent/`-touching branch; T5.7b introduces no new package boundary or credential.
Pedagogical reference docs (`accounting-domain-knowledge` / `technical-understanding`): **NOT in the repo** — out of scope, not chased.

### D14 — T5.3c LiveAgentTransport docs-sync — DONE (2026-06-15, branch t5.3c-docsync)
Verification-first: confirmed T5.3c on master (PR #21, commit `5cb9fd3`) and read the merged `agent/live_transport.py` + `tests/test_t53c_live_transport.py` before writing; ran the full suite once — authoritative count **1513 passed, 1 skipped**; flake8 `E9,F63,F7,F82` clean.
`AGENTASSIST_TECHNICAL_STATE.md`: §T5.3 Slice 3 added (`LiveAgentTransport` implements `agent.loop.AgentTransport`, one `query()` per `stream()` == one turn via `asyncio.run`; SDK→AgentEvent mapping with `ResultMessage.total_cost_usd→cost_usd`; structural `_translate` needs no SDK import; opt-in `make_live_transport` gated behind `AGENT_LIVE_TRANSPORT`; options passed verbatim, hook choice deferred to T5.3-V; relay-only — no tool exec, no Tier-2 surface; SDK confined + deferred, third deferred-SDK site in core `agent/`, eval hermetic gate untouched; +14 mock-tested). Corrected the stale "a FUTURE live adapter wraps `claude_agent_sdk.query`" phrasing on the `agent/loop.py` row (→ present-tense, names `live_transport.py`) and added a pointer on the `agent/harness.py` row that the live `query()` call now lives there. Exec summary + master-total line updated 1499 → **1513 passed / 1 skipped**; footer D14 added. Honest qualifier: mock-tested only, NOT live-validated; the live run is the separate supervised opt-in T5.3-V (now unblocked); T2.11 still gates customer-facing.
Roadmap: T5.3 Slice 3 (T5.3c) DONE block added; summary-list T5.3c bullet + build-state snapshot count → 1513; T5.3-V noted as unblocked and a separate supervised opt-in step; D14 added.
`exploration-notes/iras-ask-coverage-analysis.md`: **checked — no change required.** T5.3c is agent-layer infra (live transport adapter) and changes no deterministic IRAS-ASK coverage cell.
`docs/merge-gates.md`: **checked — no change required.** `agent/` is already permitted the SDK (lazy) with the import boundary at `orchestrator/`; T5.3c adds no new package boundary or credential and does not alter the allowed/forbidden map.
Pedagogical reference docs (`accounting-domain-knowledge` / `technical-understanding`): **NOT in the repo** — out of scope, not chased.

### D16 — post-offline-replay status + methodology docs-sync — DONE (2026-06-16, branch tdocs-post-replay-sync)
Verification-first: read the merged code/fixtures on master (`tests/fixtures/sbodemosg-extract/`, `tests/test_t2_12a_offline_replay.py`, `orchestrator/steps.py:156`, `agent/read_tools_server.py`, the parity test) before writing.
`AGENTASSIST_TECHNICAL_STATE.md`: §T2.12a section added (six frozen read surfaces + oracle + manifest provenance, EOL pin, hermetic integrity test, demo-data/no-PDPA; offline-replay gate PASSED `b61f219` byte-identical via `canonical_json` with SAP unreachable; honest caveats incl. **S4 out of scope**; T2.19 oracle-passthrough provenance; validation-substrate shift + honest-status ladder + B1-expendable). **Gate-1 `@odata.count` attribution corrected** everywhere it appeared (dormancy bullet ~689, smoke-run table ~1326, live-FP note ~1365): v2 SL returns `@odata.count`; `steps.py:156` reads the unprefixed key → Gate 1 warn-passes unconditionally, incomplete pagination uncaught; v1→v2 key-prefix bug, not a missing SAP feature; cross-ref backlog #5; fix out of scope. T2.19 reflected merged (PR #8/`3cc379c`) + passthrough note (exec summary + Appendix C #30); re-derivability boundary + Appendix C #16 updated (offline-replay capability demonstrated; product adapter T2.12 still future). **T5.7c (ledger-name parity)** reflected merged (PR #32/`67c8f09`; `t5.7b-` branch label collides with loop-quality T5.7b/#18, tracked as T5.7c) — namespaced `mcp__reads__` fakes, T5.3g slot binding byte-unchanged, +5 tests. Footer D16 added.
Roadmap: T2.12a entry added (DONE); T2.12 annotated as NEXT BUILD with the extract-pivot-decided-but-not-complete status + DoD round-trip extension; build-state snapshot gains a "Validated offline (deterministic chain)" block (T2.12a + T5.7c) + an "Extract pivot — decided + in progress" note + T2.19 flipped to merged; open-doc-debt fixtures flag updated; D16 added.
**Extract pivot NOT flipped to Excel-primary** — recorded as decided + in progress, T2.12 next. Test count not recomputed (docs-only; 1513 the authoritative T5.3c figure, T5.7c +5 / T2.12a +1 additive).
`docs/merge-gates.md`: **checked — no change required.** The Gate-1 `@odata.count` issue is a latent code bug (out-of-scope fix), not a merge gate; the offline-replay harness adds no package boundary or credential.
`exploration-notes/iras-ask-coverage-analysis.md`: **checked — no change required.** Capture/offline-replay + the Gate-1 correction change no deterministic IRAS-ASK coverage cell.
`exploration-notes/operational-backlog.md`: Gate-1 item #5 verified present + accurate; no edit.
Pedagogical reference docs (`accounting-domain-knowledge` / `technical-understanding`): out of repo — not chased. Docs-only; no source/test change.

### D17 — T5.8 demo UI + T5.3h real LoopContext docs-sync — DONE (2026-06-16, branch tdocs-t58-t53h-sync)
Verification-first: confirmed BOTH merged to master (T5.3h PR #35/`8785f92`, T5.8 PR #36/`79e451f`, T5.8b shim PR #37/`0f3b20a`; master ff'd to `426185b`) and read the merged code (`agent/loop_context.py`, `tests/replay_shim.py`, `ui/` package, `tests/fixtures/demo_artifacts_builder.py`, `agent/dossier.py`) before writing. Recounted the suite once in the worktree: **1608 passed, 1 skipped** (authoritative; not assumed).
`AGENTASSIST_TECHNICAL_STATE.md`: **§T5.3h** subsection added (A1 inject offline-replayed `ReviewResult`, pure assembler no SAP/monkeypatch/SDK; `build_vendor_catalog` from S3 business-partners re-keyed by CardName, `gst_registered`/`gst_reg_no` only; `AbsentDocumentProvider` + empty prior-period = honest degraded case; `BuiltLoopContext`; B1 chain-only — `reasoning_artefact`/`document_candidates` `None`; reusable byte-preserving `tests/replay_shim.py`; honest — hermetic/scripted, NOT live-validated/accuracy-validated, T2.12a gate intact). **§T5.8** section added (`ui/` MockEngine default / RealEngine lazy drop-in; four views; `sign.py` adjudication→Sign over existing report path with `show_ai_candidates` RESPECTED + no secrets + box-isolation; build/render freeze boundary + schema tripwire; `streamlit run ui/app.py` via the T5.8b shim; Mock+Sign imports no anthropic/SDK/`agent.loop`, guard-tested; honest — mock-first, showcase-not-product, GATED, built ≠ demo-validated). Exec-summary running-count + master-total line updated 1513 → **1608/1**. **Appendix C #33** added — `finding_id` collision on `(source, check_id, doc_num)` (23→20 unique on the frozen extract, 23→21 staged in the demo; open T2.11 collapse-vs-keep decision). Footer D17 added.
Roadmap: **T5.3h** DONE paragraph added under §T5.3; **T5.8** flipped PLANNED → DONE; build-state snapshot T5.3h + T5.8 bullets added + count → **1608**; an "On the horizon — RealEngine ← T5.3h convergence" note added after the T5.8 entry; D17 added.
`docs/merge-gates.md`: **doc-note added (no CI gate).** A `ui/` row added to the allowed/forbidden map (may import `agent/`/`engine/`/`report/`; must NOT import `anthropic` directly) with a note that the posture is enforced by the T5.8 guard test (`tests/test_t58_mock_engine.py`), NOT by Gate a's `orchestrator/` grep, and a "consider promoting to a grep gate later" pointer. No CI gate added (that would be a code change, out of scope).
`exploration-notes/operational-backlog.md`: item 6 (`finding_id` collision) + item 7 (Streamlit launch-smoke process note — acceptance was headless, the `streamlit run` entrypoint wasn't exercised until T5.8b added the `sys.path` shim) added.
`exploration-notes/iras-ask-coverage-analysis.md` + `knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** T5.8/T5.3h are UI/agent-layer infra; they change no deterministic IRAS-ASK coverage cell and touch no VatGroup→F5-box routing or tax-domain content.
Pedagogical reference docs (`accounting-domain-knowledge` / `technical-understanding`): out of repo — not chased. Docs-only; staged diff `.md`-only.

### D18 — T5.3-V round-2 real-ctx live run + docs-sync — DONE (2026-06-16, branch t5.3v-round2-live-loop)
Supervised, attended live MECHANISM-validation run (not a feature build): the arch-A `run_casefile_loop` driven by `claude-opus-4-8` over a REAL `LoopContext` (T5.3h `build_loop_context`) and REAL findings (offline `replay_review` off the frozen SBODEMOSG extract, SAP unreachable), master `19eb62e`, `RunBudget(max_turns=12, max_cost_usd=3.00)`. Finding set option B = first 3 `NO_GST_REG` (Acme Associates 605 / Far East Imports 592 / SMD Technologies 594). **Result: 3 PENDING staged** (round-1 0-PENDING gap CLOSED), 1 attempt each, completeness 1.0 / lint 1.0, cost **$1.013447** (under cap), cage held (16 ledger entries; **zero Tier-2**, nothing sealed/emitted, **zero Tier-3 denials**). T5.3g `supplier_catalog` slot fix validated **live on real data** ×3; `document_pdfs` slot binding structurally correct but NOT live-exercised through complete→stage (AbsentDocumentProvider + no document-needing finding). Raw evidence saved BEFORE scoring: `exploration-notes/live-loop-run-20260616-round2/` (`SESSION-REPORT.md`, `summary.json`, `raw/ledger.json`, `raw/stream.json` 64.8 KB, `run_round2_realctx.py`). **MECHANISM not accuracy** (T2.11 unchanged); frozen flags untouched (`git diff` empty on `config/`/`engine/`/`ui/`); **no source/test change** — new files under `exploration-notes/` only, so the master test count is unchanged.
`AGENTASSIST_TECHNICAL_STATE.md`: §T5.3 "Live validation (T5.3-V) — round-2 real-ctx live run (2026-06-16)" subsection added. Roadmap: §T5.3 T5.3-V round-2 paragraph added; D18 added.
`exploration-notes/iras-ask-coverage-analysis.md` + `knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** This is an agent-layer live run; it changes no deterministic IRAS-ASK coverage cell and touches no VatGroup→F5-box routing or tax-domain content.
Pedagogical reference docs: out of repo — not chased. Docs + exploration-notes only.

### D19 — T5.9a intent surface (bounded menu + dispatch) build + docs-sync — DONE (2026-06-17, branch t5.9a-intent-surface)
Build (not docs-only): `agent/intent.py` — the FIXED `INTENT_MENU` (v0/PROVISIONAL) + deterministic `dispatch(intent, params)` router; `IntentSpec`/`DispatchResult`/`NeedsClarification`/`IntentError`. The product front door as Invariant 6 made into a surface ("the menu is the cage at the product layer"): dispatch routes a validated intent + explicitly-bound params to its declared tier-classified sequence of EXISTING registry actions, granting no out-of-tier authority and emitting no non-menu intent. **⊆-MENU** (`dispatch` asserts `intent ∈ INTENT_MENU` else `IntentError`; build-time `_assert_menu_well_formed` asserts every action is a real registry tool via `get_tier ≠ Tier.THREE`) and **no tier escalation** (`DispatchResult.tiers` READ from `get_tier`, never assigned). Identity-bearing slots never guessed — missing/blank `client_id`/`period` → structured `NeedsClarification`. v0 menu: `RUN_REVIEW`→`run_review_chain` [T1], `SHOW_LEDGER`/`SHOW_PROPOSALS`→`read_ledger` [T0], `SHOW_PRIOR_ADJUDICATIONS`→`read_prior_period_treatment` [T0]; `SHOW_PROPOSALS` shares `read_ledger` (no proposals-read tool yet — Terry approved option (a)). Failing-test-first; **+29 tests** (`tests/test_t59a_intent_surface.py`), full suite **1744 passed, 1 skipped** (origin/master `dffed8f`/T5.5 base 1715 + 29). NO NL classifier (T5.9b), NO chat UI (T5.9b/c); hermetic; NOT live/accuracy validated; T2.11 gates customer-facing; T4.1 platform stays gated. Provisioning: branched off `origin/master` `dffed8f` (local master stale ahead-1/behind-6); cherry-picked the local-only docs-only `3f5fe3b` (T5.9 roadmap entry + Invariant 6 amendment, absent from origin) forward as `18fe954`.
`AGENTASSIST_TECHNICAL_STATE.md`: **§T5.9a** subsection added under §T5.9; §T5.9 heading/status flipped to "T5.9a DONE; T5.9b/c PLANNED"; footer D19 added. Roadmap: **T5.9a slice PLANNED→DONE** (T5.9b/c stay PLANNED); D19 added.
`exploration-notes/iras-ask-coverage-analysis.md` + `knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** T5.9a is a product-surface routing layer; it changes no deterministic IRAS-ASK coverage cell and touches no VatGroup→F5-box routing or tax-domain content.
Pedagogical reference docs: out of repo — not chased.
### D20 — T2.23 merge-status correction — DONE (2026-06-17, branch tdocs-t2.23-merge-status)
Docs-only status flip off fresh `origin/master` `f3ef8af`. T2.23 (chain source seam) **merged to master via PR #39, merge commit `5c48ccb`, 2026-06-16** — verified in `origin/master` history with the seam symbols present (`class ChainReader`/`SapChainReader` in `mcp-servers/custom/sap_b1_server.py`, `run_chain(reader=…)`); the canonical docs had been recording it as "PR-open / NOT merged". A prior loose-working-tree flip of the same two status lines was reverted and redone cleanly through this D-numbered envelope (D6–D19 convention).
`AGENTASSIST_TECHNICAL_STATE.md`: §T2.23 heading + Status sentence flipped PR-open → merged (`5c48ccb`); D20 footer entry added. Roadmap: T2.23 entry heading flipped → merged (`5c48ccb`); a **T2.23 bullet added to the build-state snapshot** "Validated offline (deterministic chain) — on master" block (it was absent), consistent with T2.12a/T5.7c; D20 added.
The `rewired by T2.23` cross-refs and the `operational-backlog.md` #5 location note are descriptive, not status claims — left unchanged (re-verified). **No code/test change; test count UNCHANGED at 1715 passed / 1 skipped** (current-master authoritative figure: T5.5 baseline 1683 + 32).
`docs/merge-gates.md` + `knowledge-base/sg-tax-code-mappings.md` + `exploration-notes/iras-ask-coverage-analysis.md`: **checked — no change required.** A merge-status label correction changes no merge-gate, no VatGroup→F5-box routing, and no deterministic IRAS-ASK coverage cell. Pedagogical reference docs out of repo — not chased. Docs-only; `.md`-only staged diff.

### D22 — T5.9b NL classifier + clarify-on-miss build + docs-sync — DONE (2026-06-17, branch t5.9b-nl-classifier)
Build (not docs-only): `agent/intent_classifier.py` — the natural-language front door, the ONE model-bearing piece of the intent surface. `IntentClassifier(backend).classify(utterance, menu)` maps a free-text utterance onto the FIXED `INTENT_MENU` and returns a VALIDATED `ClassificationResult = Classified(intent ∈ menu, candidate_params) | NeedsClarification | OutOfScope` that feeds `agent.intent.dispatch` UNCHANGED. **Classify-never-obey is STRUCTURAL via two independent guards:** (1) the LIVE backend (`AnthropicClassifierBackend`) is one constrained `messages.create` with a SINGLE forced structured-output tool and NO executable tools (`claude-haiku-4-5-20251001`, v0/PROVISIONAL) — the model can only EMIT a `{verdict,intent,params}` label; (2) **⊆-MENU AT THE BOUNDARY** (`_enforce_menu_boundary`, PURE) validates every backend's raw label against `INTENT_MENU` before return — an off-menu/hallucinated intent (even a raw tool name) is REJECTED to `OutOfScope`, candidate params RESTRICTED to the bound intent's declared `required_params`. The slot set IS exactly the declared `required_params`; the classifier never guesses `client_id`/`period` (absent/blank → `NeedsClarification`) and never extracts a `fingerprint` nor attempts `client/period → fingerprint` reconciliation (that v0 menu gap stays DOWNSTREAM, untouched). The model sits behind a `ClassifierBackend` seam with a SCRIPTED fake (`ScriptedClassifierBackend`) — every test uses it, zero tokens; `anthropic` imported lazily/confined so `agent/intent.py` stays pure and `intent_classifier.py` is the only new `anthropic` importer (permitted in `agent/` per `docs/merge-gates.md`). Failing-test-first; **+37 tests** (`tests/test_t59b_nl_classifier.py`: (a) clear→Classified→dispatch; (b) missing/ambiguous→clarify-never-guess; (c) out-of-scope; (d) injection contained; (e) off-menu backend→OutOfScope; (f) prior-adjudications declared-slots-only/no-fingerprint; + hermetic live-backend parse/forced-tool + named import-scan checks). Full suite **1807 passed, 1 skipped** (origin/master `ba4cd85` base 1770 + 37). Hermetic; provisioning off fresh `origin/master` `ba4cd85` (local master known-stale; worktree per STEP 0).
`AGENTASSIST_TECHNICAL_STATE.md`: **§T5.9b** subsection added under §T5.9; §T5.9 heading/status flipped to "T5.9a/b DONE; T5.9c PLANNED"; footer D22 added. Roadmap: **T5.9b slice PLANNED→DONE** (T5.9c stays PLANNED); D22 added.
`exploration-notes/iras-ask-coverage-analysis.md` + `knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** T5.9b is a product-surface NL-routing layer; it changes no deterministic IRAS-ASK coverage cell and touches no VatGroup→F5-box routing or tax-domain content. Honest scope: classifier built + hermetically tested; LIVE backend built but NOT measured (curated-utterance accuracy is T5.9c); model choice v0/PROVISIONAL; NO chat UI (T5.9c); not live/accuracy validated; T2.11 gates customer-facing; T4.1 platform stays gated.

### D23 — T5.9c demo command bar (chatbot front door) + routing-accuracy eval build + docs-sync — DONE (2026-06-17, branch t5.9c-demo-chatbot)
Build (not docs-only). Phase-1 STOP-and-report first: on first check T5.8d (`ui/views/review.py`) was UNMERGED so the slice STOPPED; once PR #53 (`b9901b3`) merged it re-confirmed BOTH preconditions (T5.9b `intent_classifier.py` + T5.8d `review.py`), live-verified importing `IntentClassifier`/`ScriptedClassifierBackend` pulls NO `anthropic`, reported the intent→section map + eval location (outside `ui/`), then stopped. Terry approved with two additions, both honoured: (1) docs/honest-status state the curated set is AUTHOR-CONSTRUCTED + SMALL (~2/cell) → smoke/repertoire sanity NOT a generalization claim (a real number needs a larger independently-sourced set); (2) the injection test scripts a HOSTILE backend output (raw registry tool name `emit_final_pdf` claimed as "intent") and asserts the ⊆-menu boundary contains it (→`OutOfScope`) + the command bar shows the polite message + buttons, NO action. Built: `agent/intent_curated.py` (pure data, anthropic-free) — the curated set, each entry carrying BOTH the scripted `RawClassification` (canned answer) AND the expected `ClassificationResult` (gold label), one source for demo answers + eval labels; spans 4 intents + clarify + out-of-scope + injection (incl. hostile); EVAL-ONLY never training. `ui/views/review.py` — command bar (quiet input) + four-intent buttons fallback over pure `route_intent`/`handle_command`/`handle_button`: `Classified`→section, `NeedsClarification`→clarify-never-guess, `OutOfScope`→polite+buttons; uses `ScriptedClassifierBackend` ONLY (MUST NOT instantiate `AnthropicClassifierBackend`); classify-never-obey via the SAME ⊆-menu boundary. `agent/eval/intent_routing.py` (OUTSIDE `ui/`) — hermetic scripted path 100% (SANITY); opt-in/env-gated (`INTENT_ROUTING_LIVE=1`+`ANTHROPIC_API_KEY`, TOKENED) LIVE basket (per-intent accuracy, clarify P/R, out-of-scope recall, injection containment) with raw evidence saved BEFORE scoring; ROUTING-not-GST accuracy. Failing-test-first; **+13 tests** (`tests/test_t59c_demo_chatbot.py`: Classified→section; missing-slot→clarify-never-guess; out-of-scope→polite+buttons-never-tool; injection contained incl. hostile raw-tool-name backend output; buttons dispatch 4 intents directly; scripted eval 100% sanity; + NAMED import-scans `ui/` no-anthropic / eval-only-`AnthropicClassifierBackend`-toucher-deferred / `orchestrator/` purity). Full suite **1829 passed, 1 skipped** (origin/master `b9901b3` base 1817 collected + 13). Hermetic demo path (no live model/tokens); provisioning off fresh `origin/master` `b9901b3` (worktree per STEP 0).
`AGENTASSIST_TECHNICAL_STATE.md`: **§T5.9c** subsection added under §T5.9; §T5.9 heading/status flipped to "T5.9a/b/c DONE"; footer D23 added. Roadmap: **T5.9c slice PLANNED→DONE**; §T5.9 heading flipped to "T5.9a/b/c DONE"; D23 added.
`exploration-notes/iras-ask-coverage-analysis.md` + `knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** T5.9c is a product-surface demo/eval layer; it changes no deterministic IRAS-ASK coverage cell and touches no VatGroup→F5-box routing or tax-domain content. Honest scope: demo command bar MOCK/scripted (no live model/tokens in the demo path); live routing-accuracy OPT-IN/tokened, v0/PROVISIONAL, ROUTING-not-GST (distinct from T2.11, no accredited specialist); scripted 100% is sanity NOT the accuracy claim; curated set AUTHOR-CONSTRUCTED/SMALL/EVAL-ONLY never training; classify-never-obey enforced; "one way in", review on the dashboard; T2.11 gates customer-facing; T4.1 platform gated.

### D24 — T5.9d dispatch-execution (pure module, surfaced at C2) build + docs-sync — DONE (2026-06-18, branch t5.9d-dispatch-execution)
Build (not docs-only). Two-phase: Phase-1 read-only recon (HEAD `95c6ff7`, T5.9c merged via PR #55; the four INTENT_MENU intents + tool/tier/required-param shapes; `read_proposals`/`read_decision_ledger` signatures; frozen-artifact loader + MockEngine; the v0 `SHOW_PRIOR_ADJUDICATIONS` client/period→fingerprint gap) → STOP. Flagged that the menu's `read_ledger` (SHOW_LEDGER) had NO implementation (registry ToolSpec only); Terry approved **option B** — add a real `read_ledger` Tier-0 read so all four intents execute via a `read_tools` function. Built: `agent/dispatch_exec.py` — PURE, framework-free `execute_intent(intent, params, *, artifacts, engine=None) -> ExecutionResult` running the Tier-0 read(s)/RUN_REVIEW over FROZEN artifacts; routes `SHOW_LEDGER`→`read_ledger`, `SHOW_PROPOSALS`→`read_proposals` (staging store rehydrated to `ProposalArtifact`s), `SHOW_PRIOR_ADJUDICATIONS`→`read_decision_ledger` LIST-ALL (menu-gap FLAGGED in `notes`, no client/period→fingerprint mapping fabricated), `RUN_REVIEW`→`FrozenEngine` (frozen dossiers + F5 summary, no live chain/SAP); blank identity slots → router `NeedsClarification` passthrough. Decoupled from `ui/` (owns `load_frozen_artifacts`/`FrozenArtifacts`/`FrozenEngine`, twins of the `ui` ones) so it can be surfaced at Lane C2's React `POST /command` (NOT Streamlit); `ExecutionResult` serialisable (`to_dict`), no rendering logic; RUN_REVIEW deep-copies for box isolation. Added `read_ledger(ledger: list[dict])` to `agent/read_tools.py`. Failing-test-first; **+21 tests** (`tests/test_t59d_dispatch_exec.py`): each intent → REAL frozen rows; RUN_REVIEW → frozen engine output (no SAP/live chain); NeedsClarification passthrough; unknown intent/raw tool name → `IntentError`; box-isolation (F5 boxes + gate_results byte-identical before/after + mutation isolation); purity AST import-scan (no anthropic/streamlit/fastapi/requests/urllib/socket/SAP/orchestrator/ui); JSON-serialisable. Full suite **1871 passed, 1 skipped** (origin/master `95c6ff7` base 1850 + 21). `orchestrator/` untouched; provisioning off fresh `origin/master` `95c6ff7` (worktree per STEP 0).
`AGENTASSIST_TECHNICAL_STATE.md`: **§T5.9d** subsection added under §T5.9; §T5.9 heading/status flipped to "T5.9a/b/c/d DONE"; footer test-count line refreshed to 1871; D24 here. Roadmap: **T5.9d slice PLANNED→DONE**; §T5.9 heading flipped to "T5.9a/b/c/d DONE"; D24 added.
`exploration-notes/iras-ask-coverage-analysis.md` + `knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** T5.9d is a product-surface routing/execution layer over frozen artifacts; it changes no deterministic IRAS-ASK coverage cell and touches no VatGroup→F5-box routing or tax-domain content. Honest scope: built + hermetically tested over FROZEN artifacts; surfaced at C2 (not this slice); NOT live/accuracy validated; SAP off, mock engine, no tokens; v0 `SHOW_PRIOR_ADJUDICATIONS` gap honoured (list-all + flagged) not closed; T2.11 gates customer-facing; T4.1 platform gated.
### D24 — T6.1 React review surface + FastAPI seam (Lane C1) build + docs-sync — DONE (2026-06-18, branch t6.1-frontend-review-surface)
Build (not docs-only). Two-phase, Phase-1 STOP-and-report first: confirmed HEAD `95c6ff7` + T5.8d (`744e10f`) and T5.9c (`b4339e5`) merged; reported the exact `ui/artifacts.py` view-model shapes, the real frozen finding inventory (E1×8/NO_GST_REG×7/E2×5/gst_amount_mismatch×1 = 21; doc-592 demoted), the `merge-gates.md` `ui/` posture + pytest-only CI, and the proposed API contract; then STOPPED for `approved`. Built: **`api/`** (FastAPI seam, imports `ui`/`agent`/`engine`/`report` only — NO `anthropic`; `orchestrator/`+`engine/` untouched): `api/viewmodel.py` PURE serialisers with `REVIEW_KEYS`/`QUEUE_ITEM_KEYS`/`AUDIT_ROW_KEYS`/`SIGN_KEYS` as the single source of truth for the FE key set; `api/app.py` `GET /review/{client}/{period}` (real frozen queue, demoted flagged, 404 off the frozen pair), `POST /sign` (reproduces `ui.sign.sign_working_paper`, reviewer name carried, box-isolation preserved), `GET /audit`, `GET /health`; **no `/command` endpoint (Lane C2 deferred)**. **`frontend/`** (Vite + React + TS): TopBar/CommandBar(INERT)/Queue/FindingDetail/AuditTrail/SignModal + typed `src/api.ts` mirroring the contract; clay-paper aesthetic (Newsreader/Inter/IBM Plex Mono) lifted from the target mock, REAL frozen data underneath; only real check types render; doc-592 "Far East Imports" demoted-but-present under Marked known; DUP_CLAIM/SEQ_GAP/FLUX never appear; all four trust signals preserved. Failing-test-first: **+11 pytest** (`tests/test_t61_frontend_api.py`: real frozen shape; doc-592 present+demoted; no fictional types; sign box-isolation + reviewer name + empty-reviewer reject; QUEUE_ITEM_KEYS contract; AST `api/` no-anthropic import-scan) + **+4 vitest** render smoke (`frontend/src/test/App.smoke.test.tsx`). Full pytest suite **1861 passed, 1 skipped** (the skip is the import-isolation guard that no-ops when `anthropic` is already loaded — by design); `tsc --noEmit` + `vite build` green. `fastapi`+`uvicorn` added to `requirements.txt`. Provisioning off fresh `origin/master` `95c6ff7` (worktree per STEP 0).
`AGENTASSIST_TECHNICAL_STATE.md`: **§T6.1** section added (after §T5.9c). Roadmap: **T6.1 DONE** bullet added under Tier 5 (after T5.9c); D24 added. `docs/merge-gates.md`: **`api/` row + posture note added** to the allowed/forbidden map (may import `agent`/`engine`/`report`/`ui` view-models; must NOT import `anthropic`/SDK; enforced by the AST import-scan test, not a CI grep) + a **CI/Node-separation note** (Python suite stays the merge gate; frontend vitest/build separate optional/local; no Node job in `ci.yml`).
`exploration-notes/iras-ask-coverage-analysis.md` + `knowledge-base/sg-tax-code-mappings.md`: **checked — no change required.** T6.1 is a serve/presentation layer over FROZEN artifacts; it changes no deterministic IRAS-ASK coverage cell and touches no VatGroup→F5-box routing or tax-domain content. Honest scope: frontend + API built over FROZEN artifacts (built ≠ demo-validated ≠ accuracy-validated); the per-finding IRAS citations are themselves UNVALIDATED; command bar inert (Lane C2 deferred); T2.11 gates customer-facing.

---

## Final Architectural Reminders

1. Three-layer separation is non-negotiable. Tools do arithmetic; KB is reference content; system prompt orchestrates.
2. The reference script is the audit, not the partner. Independent implementation; no shared code; divergence flags bugs.
3. Claude does not assert compliance positions unilaterally. Never assert without tool-confirmed evidence. Preserve "candidate for review" vs "confirmed error."
4. The reviewer signs off on every finding before submission. No automatic filing or IRAS contact, at any tier — including any future platform.
5. Don't add the Skill abstraction until the product expands beyond one workflow (this is the Tier 4 / multi-vertical future, post-validation).
6. The knowledge base is modular per chain-step. Data flows forward; regulatory context stays sliced per step.
7. The engine's orchestration is a predefined code path, not autonomous agents — the deterministic chain, its gates, and the reasoning passes are never under LLM runtime control. The Tier 5 agent shell operates AROUND the engine (deciding when to invoke it, which registry checks to plan, what evidence to assemble, what to propose), never WITHIN it: it invokes the chain as a single atomic tool and never selects individual chain steps.
8. Document ingestion expands recall, never authority. A read-derived finding caps at J+ (sole exception: invoice-date → correct-period → D+). Extracted fields never enter Layer 1, boxes, or gates. What converts J+ → D is structured data at source (InvoiceNow/PINT-SG), not reading a PDF.
9. The MCP connector is one input adapter, not the product. The engine accepts live MCP, CSV/Excel extracts, and (future) PINT-SG against one internal schema. This separability is also the platform prerequisite.
10. **(NEW) Labelled data is for evaluation, not training.** It powers validation, regression eval, few-shot exemplars, and skill definition-of-done. Claude is used via API; no weights are ever updated.

---

## Open integrity / doc-debt flags

- **Reasoning-layer numbers are a smoke test, not validation** — measured against an Opus-labelled (AI-generated) fixture. `show_ai_candidates` stays `False` for deliverables until an independent specialist reconciles ground truth (T2.11 + T2.13).
- **Document-layer candidates are plumbing-demonstrated on seeded data, not validated** — T2.8 is correct-by-construction and wired end-to-end on 13 AGENTASSIST_SEED docs. No validation against real IRAS-compliant ground truth has occurred. `show_ai_candidates` stays `False` for deliverables pending T2.11.
- **B1 attachment byte-download (T2.8) is unverified** — `B1AttachmentProvider` Steps 1–2 (metadata chain) verified; Step 3 (`/$value` download) unverified because SBODEMOSG `AttachmentsFolderPath` is not configured. The upload path (`UploadProvider`) is the working path for current testing. Cannot be verified without a SAP B1 instance that has both `AttachmentsFolderPath` configured and at least one purchase invoice with a PDF attachment.
- **AGENTASSIST_SEED Remarks marker does not persist** — the SAP demo instance does not return the `Remarks` field on read-back; seed identity depends solely on `scripts/seed_manifest.json`. Cleanup of the 13 seeds (DocEntries 615–627) must be by DocEntry, not by Remarks filter.
- **Box 8 is DB-state-dependent** — post-T2.8-seeds Box 8 = 12,663.87 (current state, run_baseline_tests.py 2026-06-08). Any future seed or cancellation on SBODEMOSG will change this figure. Pre-T2.8 authoritative Box 8 = 17,045.87. The 17,395.87 in v0–v3 test scoring is from the earliest 2026-05-25 run (before T1.x seeds). See Appendix B of `AGENTASSIST_TECHNICAL_STATE.md` for the full reconciliation.
- **SBODEMOSG has no document attachments** — any T2.8 document-ingestion demo/build must supply its own invoice PDFs (the 13 seeded PDFs in `scripts/seed_uploads/` serve this role for the SBODEMOSG demo).
- **Test fixtures are live-seeded into SBODEMOSG and ephemeral** (tied to the SAP CAL instance). Static, repo-resident fixtures (open item #21): **PARTIALLY RESOLVED by T2.13 for the Reg 26/27 reasoning layer** — `reg2627-representative-v1.json` and `reg2627-adversarial-v1.json` are now static, repo-resident fixtures — **and further by T2.12a (2026-06-16) for the deterministic chain's SBODEMOSG Q3-2024 ground truth**: the six read surfaces (S0–S5) + compiled oracle are now frozen, repo-resident under `tests/fixtures/sbodemosg-extract/` with a passing offline-replay gate (`b61f219`), so the deterministic chain re-derives with **no live SAP**. Still **OPEN**: synthetic deterministic-chain edge-case fixtures (rate-transition, partial exemption, reverse-charge, custom VatGroup) — these are crafted cases, distinct from the frozen real-SBODEMOSG capture. Preserve the captured v0-vs-v3 evidence (it cannot be re-run identically once the DB changes).
- **Gate-1 `@odata.count` latent bug (found T2.12a recon, 2026-06-16)** — `orchestrator/steps.py:156` reads the unprefixed `odata.count`, but the v2 Service Layer returns the total under `@odata.count`; Gate 1 therefore warn-passes unconditionally and incomplete pagination is currently uncaught. Doc attribution corrected in this sync; the code fix is a separate failing-test-first task. See `exploration-notes/operational-backlog.md` item #5.
- **All Singapore tax specifics** (materiality thresholds, Step-4 reconciliation thresholds, paragraph numbers) must be re-verified against the current IRAS e-Tax Guide edition before any customer-facing claim.
- **Strategy watch:** the platform vision (Tier 4) is a north-star, not a near-term build. Guard against drifting effort into a dashboard before one vertical is validated and sold; the bottleneck remains distribution + trust.
