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

- **T2.19** — Tax code normalization layer for non-SAP-B1 source systems (`normalize_vat_group()` in `sap_b1_server.py`; `tax_code_mappings`/`source_system` in `ClientConfig`; audit allow-list updated). Committed 2026-06-10 on branch `t2.2-vat-discovery` (commits `47e31a0`, `19a6f86`) — **not yet merged to `master`**. 28 new tests in `tests/test_tax_code_normalization.py`, zero network calls, fully synthetic. SAP B1 clients unaffected (empty `tax_code_mappings` = passthrough; all baseline figures unchanged). Validated on synthetic fixtures only; not yet tested against a real non-SAP-B1 client engagement.

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

### T2.2 — Custom VatGroup discovery and reporting — PLANNED
Effort 1 wk. Owner Collin. Enumerate the VatGroup codes actually present in the client's transaction data, classify against the 18-code standard set, and surface unknowns with sample DocNums/counterparties — the independent completeness check that catches codes the client forgot or never declared. The enumeration produces a client-confirmation worksheet; the client declares the intended treatment of each custom/unknown code; those client-declared treatments persist to per-client config. Treatment is CLIENT-DECLARED, not auto-classified — intended treatment of a custom code cannot be inferred from data (self-report is authoritative for treatment; enumeration is authoritative for completeness). Thin slice of the future T2.12 normalization adapter.

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

### T2.12 — Extract-based delivery adapter (advisory-firm channel) — PLANNED
Effort PROPOSED 3–4 wk. Owner Terry/Collin. Advisory firms access client data via extracts, not live B1. Add an input adapter mapping CSV/Excel (later PINT-SG) to the same internal line-item schema so the chain/gates/report run unchanged. The MCP connector becomes one input adapter among several. DoD: a CSV extract produces identical chain output to the equivalent MCP run on the same data. **This refactor (decoupling input adapter from engine behind a stable schema/API) is also the architectural prerequisite for any future platform — see Tier 4.** The stable `review(client, period, inputs) → ReviewResult` interface produced by this refactor is also the seam consumed by the Tier 5 agent shell (T5.1).

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

### T2.18 — ClientConfig scheme & treatment block — PLANNED
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
6. Bounded task surface: the product interface is a fixed menu of intents mapping to tier-classified action sequences; free text is permitted only within a task and is treated as untrusted input. Note: input bounding is a product/evaluability measure, NOT a safety mechanism — any safety property that fails under adversarial user input was never a safety property. **Input-surface note (Collin reconciliation):** the front door accepts free text; an intent ROUTER maps it to the bounded intent space; on a miss, the system asks for clarification rather than guessing. Free text is untrusted input — the router classifies, never obeys. This is the agreed reconciliation of the "chatbot" front-end idea with the bounded-task-surface invariant: a natural-language front door is fine; unconstrained LLM-to-tool chaining inside the product is not.
7. Agent-layer failure is non-blocking to the deterministic deliverable. If the agent errors, crashes, or hits its loop/cost cap, the deterministic chain output and the signed working paper still complete — exactly as a reasoning-pass failure is logged but never prevents the audit bundle from sealing. The agent shell may add to the deliverable; it must never be able to prevent it.

### T5.1 — Engine API seam — PLANNED (≈ T2.12 delta)
Stable callable interface review(client, period, inputs) → ReviewResult. The agent shell is the first consumer of the T2.12 seam. Cross-ref T2.12. Effort: small delta over T2.12.

### T5.2 — Action-tier framework + justification ledger — DONE (2026-06-12)
Completed 2026-06-12, PRs #12 (T5.2a) and #13 (T5.2b). Owner: Terry.

**Honest qualifier:** DONE = cage built + hermetically unit-tested; **NOT demo-validated** (no live agent loop); `seal` and `emit` executor handlers are NotImplemented stubs deferred to T5.3. 133 new tests (89 T5.2a + 44 T5.2b); 1372 passed, 1 skipped master total. See `AGENTASSIST_TECHNICAL_STATE.md` §T5.2 for full detail.

**What was built:**
- `agent/` package: Tier enum (0/1/2/3); ToolSpec/CheckSpec/LedgerEntry/ProposalArtifact/RunBudget schemas; tool registry (8 tools: 4 Tier-0 read-only, 4 Tier-1 staging, zero Tier-2-executing); justification gate (heuristic backstop); append-only hash-chained justification ledger (reuses `canonical.py`); StagingStore (CLI-first approve/reject); deterministic Tier-2 executor (`test_noop` handler + NotImplemented stubs for seal/emit); RunBudget with BudgetExceededSignal → invariant-7 non-blocking path.
- SDK integration: `agent/hooks.py` (make_hooks → PreToolUse/PostToolUse); `agent/harness.py` (build_options → ClaudeAgentOptions, deferred SDK import); `agent/approve_cli.py` (CLI over StagingStore + Executor); `audit_bundle/seal.py` extended with `agent_ledger` parameter → `steps/agent-ledger.json` in bundle.
- CheckSpec v0/PROVISIONAL — 14 entries; NOT wired to consumers; Collin ratifies after T2.18.
- First runtime dependency: `claude-agent-sdk==0.2.99`. Linux CI green (builds from sdist); CLI binary only needed at `query()` time (T5.3). `orchestrator/` unchanged; Gate a extended in `docs/merge-gates.md` to forbid `agent/` imports in `orchestrator/`.

### T5.2c — Check-registry contract — PLANNED
Sequenced after T2.18 (config scheme block). The CheckSpec schema (check_id, iras_basis, inputs_needed, finding_schema) is v0/PROVISIONAL until T2.18 lands. T5.2c closes the loop: the registry schema is proven against real deterministic checks (E1–E4, SEQ_GAP, DUP_CLAIM, declared_A/B, document reconciliation checks) and co-designed with Collin against the then-current IRAS VatGroup remap and T2.18 config_keys. Only after T5.2c does CheckSpec graduate from PROVISIONAL to the coordination contract that T5.4 (check planner) consumes. Hard dependency: T2.18. Owner: Terry + Collin. Effort: small (~0.5 wk) once T2.18 is in.

### T5.3 — Case-file builder — PLANNED
First real agent loop (gather context → take action → verify work). Per finding: pull source PDF (T2.8 path), linked CN, vendor reg status, prior-period treatment; assemble dossier in staging. Verification is a CODE-DEFINED completeness checklist per finding type — never model self-assessment. Deterministic language lint over dossier text rejects assertive compliance phrasing (candidate framing required); lint failure = blocked artifact. Honest caveat: phrase-list lint is brittle — a backstop to prompt design, not a replacement. Effort ~2–3 wk.

### T5.4 — Check planner — PLANNED
Routing, not invention: agent selects applicable checks from the FIXED registry given the client profile. First plan per client is a Tier-2 proposal; an identical plan re-executes at Tier 1; plan drift re-escalates to Tier 2 automatically. The planner never composes new logic. Effort ~1 wk after T5.2.

### T5.5 — Decision ledger — PLANNED
Append-only reviewer adjudications keyed by deterministic finding fingerprint (error code, VatGroup, CardCode, amount band). Annotate-and-demote only (invariant 5). Effort ~1–2 wk.

### T5.6 — Trigger layer — PLANNED, HARD-GATED
Cadence/period-close detection initiating Tier-1 runs whose outputs hold at Tier 2. Gates (all required): credentials scrubbed from git history (aec650f9); GCP 0.0.0.0/0 firewall closed; an always-on deployment target existing at all. Build last; lowest value per risk.

### T5.7 — Agent-behaviour eval harness — PLANNED
Operationalises cross-cutting requirement (a): the scenario harness that makes "no entry advances past built without evals" executable. Fixed scenario fixtures + a runner that executes the agent against them in a TEST context + metric computation over the measured basket: dossier completeness rate, justification-gate hold rate, count of Tier-2 self-executions across N adversarial runs (target zero), language-lint pass rate, plus the prompt-injection fixtures from cross-cutting (b). This is offline test/measurement infrastructure (analogous to the reasoning layer's measurement.py), NOT a production agent workflow. Sequencing: built alongside T5.3 (needs an agent to measure; depends on T5.2), and is the gating dependency for any "built" → "validated" graduation of T5.3–T5.5 — it does NOT follow T5.6 despite its number. Effort ~1–2 wk.

### T5.8 — Demo showcase UI — PLANNED, GATED (showcase-not-product; distinct from T4.1)
Mock-first, view-over-artifacts: a local Streamlit UI that visualises the agent tier model in action — ledger timeline (Tier-0/1 entries with justifications), pending proposals queue (propose→approve gate), and executor dispatch log. MockEngine/RealEngine seam so the UI runs against fixture artifacts without a live SAP connection; the real engine is a drop-in replacement once T5.3 is solid.

**This is EXPLICITLY a showcase tool, NOT the T4.1 production platform.** Its purpose is to make agent-tier mechanics visible and debuggable during T5.3/T5.4/T5.5 development, and to demonstrate the bounded-autonomy model to stakeholders without requiring a live engagement. It does not address the distribution bottleneck (T4.1's gate) and earns its build only once T5.2 + T5.3 are solid enough to have meaningful artifacts to display.

**Gate:** do not start before T5.3 is built and has real ledger artifacts to show. Owner: Terry. Effort: ~1 wk (Streamlit local; no production deployment).

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
- **Test fixtures are live-seeded into SBODEMOSG and ephemeral** (tied to the SAP CAL instance). Static, repo-resident fixtures (open item #21): **PARTIALLY RESOLVED by T2.13 for the Reg 26/27 reasoning layer** — `reg2627-representative-v1.json` and `reg2627-adversarial-v1.json` are now static, repo-resident fixtures. The deterministic chain (rate-transition, partial exemption, reverse-charge, custom VatGroup fixtures) still requires live-seeded data and remains **OPEN**. Preserve the captured v0-vs-v3 evidence (it cannot be re-run identically once the DB changes).
- **All Singapore tax specifics** (materiality thresholds, Step-4 reconciliation thresholds, paragraph numbers) must be re-verified against the current IRAS e-Tax Guide edition before any customer-facing claim.
- **Strategy watch:** the platform vision (Tier 4) is a north-star, not a near-term build. Guard against drifting effort into a dashboard before one vertical is validated and sold; the bottleneck remains distribution + trust.
