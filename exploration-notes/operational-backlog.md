# Operational backlog — deferred (updated 2026-06-02, post-T1.5)
Not development blockers. Action in a later session. Full detail in
AGENTASSIST_TECHNICAL_STATE.md Appendix C (item numbers below).

**T1.5 completed 2026-06-02.** All six Tier-1 items are done. T2.7, T2.8, T2.9, T2.13 merged to master 2026-06-09; 1026 tests passing. The
`audit/` directory is now the canonical output sink (gitignored). The provisional path
`exploration-notes/t1.6-tool-outputs/` was removed in P3.

1. SAP CAL instance lifecycle (Appendix C #5, #17) — trial at 35.186.145.230 may have
   lapsed; confirm it is live; parameterise the IP fully into per-client config and remove
   hardcoded fallbacks; consider a snapshot/restore so re-deploy doesn't lose seed state.
2. Seed cleanup + re-baseline (Appendix C #8, #14) — 9 seed docs are live in SBODEMOSG and
   run_baseline_tests.py holds a placeholder instead of reference figures. Decide cleanup-or-not
   with Collin; script credit-note cleanup (cleanup_test_data.py only cancels invoice seeds);
   re-run the baseline; update the script comment block + Appendix B.
3. Fallback-credentials inconsistency (Appendix C #27) — verify SAPB1Client.__init__: if it
   falls back to demo creds when env vars are absent, change to fail-fast (RuntimeError) and
   reconcile the two contradicting doc sections.
4. Audit store housekeeping — the `audit/` directory is gitignored and grows with every run.
   No retention / destruction policy exists yet (deferred to PDPA framework, Gate C). Before
   first real-client run, define: how long bundles are kept, where they live in production
   (local disk vs. object storage), and who has read access. See Appendix C #25 for the
   broader PDPA context.
5. **Gate 1 `@odata.count` key mismatch — FIXED (branch `t-gate1-odata-count`, commits `743fb0d` / `1670d5a` / `484ff5b`).** _(found T2.12a recon, 2026-06-16; historical root-cause below retained.)_
   - **CLOSURE (fix landed):** the production read is corrected — `SapChainReader.count`
     (`mcp-servers/custom/sap_b1_server.py`, `743fb0d`) now reads `@odata.count`, with a
     failing-test-first `tests/test_gate1_odata_count.py` (3 tests: probe reads the `@`-prefixed
     key; Gate 1 FAILs on a real fetched-vs-reported mismatch; a complete fetch surfaces the count
     and Gate 1 verifies it). The shim was made faithful — `tests/replay_shim.py::FrozenExtractReader.count`
     reads `@odata.count` too (`1670d5a`), no longer perpetuating the dormant read — and the
     offline-replay oracle `_replay-oracle.compiled.json` was re-frozen (its sha256 in
     `capture-manifest.json` updated, `484ff5b`). On the complete frozen data (50/34/1/1 = 86 rows
     == inline counts) Gate 1 flips **WARN_PASS → PASS** via a human-audited 5-leaf oracle diff, all
     propagations of the Gate-1 result; **BOX-ISOLATION held** (every F5 box byte-identical). Honest
     status: correctness fix to the deterministic path, offline-replay-validated — moves NO rung
     toward T2.11; `show_ai_candidates` / `validation_status="unvalidated"` unchanged.
   - **Root cause:** the count-probe reads `count_resp.get("odata.count")`, but the
     v2 Service Layer returns the total under **`@odata.count`** (with the `@` prefix). The key
     never matches → `inline_count` is always `None`. This is a v1→v2 OData key-prefix
     mismatch, not a missing SAP feature. (Probe 2026-06-16: count-probe response keys were
     `['@odata.count', '@odata.context', 'value']` — the count *is* present.)
   - **Location update (T2.23, 2026-06-16):** the probe + buggy extraction moved from
     `orchestrator/steps.py::_fetch_entity` into `SapChainReader.count` in
     `mcp-servers/custom/sap_b1_server.py` (the S0 surface of the chain source seam). The bug
     was **preserved verbatim** — T2.23 is behaviour-preserving and the frozen oracle encoded
     the `None` → Gate-1 dormancy. _(Superseded by the CLOSURE above: the fix targeted
     `SapChainReader.count` and has landed.)_
   - **Impact:** Gate 1 warn-passes **unconditionally** on this instance, so incomplete
     pagination is currently uncaught — the gate is effectively dormant; completeness rests only
     on the structural `len(page) < 20` sentinel, never on a SAP-reported arithmetic total.
   - **Doc correction owed:** `AGENTASSIST_TECHNICAL_STATE.md` (line ~689, Gate-1 dormancy) and
     line ~1326 attributed this to "Service Layer (version 1000250) does not return `odata.count`".
     That attribution was **disproven** and has since been corrected in the docs alongside the fix.
   - **Scope (historical):** at recon time the fix was out of scope — a separate failing-test-first
     task (write a test asserting Gate 1 reads `@odata.count` and FAILs on a real mismatch, then
     correct the key). _(Done — see CLOSURE above.)_
   - **T2.12 extract-feeder note (2026-06-17, slice A):** the new `feeders.ExtractChainReader.count()`
     returns the export's **TRUE** row count (an export carries every row, so it counts honestly) —
     it does NOT reproduce this dormant `None`; that honest-count behaviour is unchanged. At the
     time of this note the SAP path (`SapChainReader.count`) and the frozen oracle /
     `tests/replay_shim.py::FrozenExtractReader.count` were untouched and still mirrored the bug.
     _(Superseded by the CLOSURE above: both readers now read `@odata.count` and the re-freeze has
     landed, so the full `run_chain`-over-feeder vs-oracle byte-identity is no longer gated on it.)_
     The feeder's `count()` remains unit-tested against the known count ONLY and is **never**
     asserted against the frozen S0 / oracle.

6. **`finding_id` collision on `(source, check_id, doc_num)` (found T5.3h/T5.8, 2026-06-16).**
   - **Root cause:** `agent.dossier.extract_findings` derives `finding_id = f"detect:{code}:{doc_num}"`
     (and analogously `doc:{check_id}:{doc_num}` / `reg2627:{doc_num}:{line_index}`), ignoring line
     index for detect findings. Two deterministic findings sharing `(source, check_id, doc_num)` — e.g.
     two E1 line-items on the same invoice — get the SAME `finding_id`. The finding *list* keeps all;
     any per-finding dict keyed by `finding_id` (the T5.8 demo builder's `scripts` map in
     `tests/fixtures/demo_artifacts_builder.py`, and any downstream evidence sink keyed the same way)
     silently keeps only the last.
   - **Observed:** the T5.3h frozen-extract chain produces 23 raw detect findings that collapse to
     **20 unique** ids (`detect:E1:974` ×3, `detect:E1:967` ×2); the T5.8 demo build stages **21** of
     its 23 detect issues for the same reason. Currently masked (demo is mock/unvalidated; box totals
     unaffected — surfaces, never asserts).
   - **Decision owed (T2.11-relevant):** when two same-code findings land on one document, **collapse**
     into one dossier or **keep two distinct findings** (needs a line-discriminating id component, e.g.
     `line_index`)? Recorded as an open design decision; see `AGENTASSIST_TECHNICAL_STATE.md` Appendix C #33.
   - **Scope:** no code change here — design decision pending; the fix (id scheme + sink keying) is a
     separate task.

7. **Streamlit launch-smoke gap (process note, T5.8/T5.8b, 2026-06-16).**
   - **What happened:** T5.8's acceptance was **headless** (the `ui/` view-models + Sign path were
     unit-tested, but the `streamlit run ui/app.py` entrypoint itself was never exercised). The
     entrypoint then failed from a fresh checkout because Streamlit puts the entrypoint's own `ui/`
     dir on `sys.path[0]`, not the repo root, so the `from ui…` package imports broke. T5.8b
     (`0f3b20a`, PR #37) added a `sys.path` bootstrap to fix it, verified by an actual launch-smoke.
   - **Lesson:** for any user-runnable entrypoint, headless unit tests are necessary but not
     sufficient — exercise the real launch command at least once (a launch-smoke) before claiming the
     entrypoint works. Cheap to add; would have caught this pre-merge.

8. **Interactive missing-data request-resume loop (GAP, gated on document ingestion).**
   - Today the T5.3 completeness mechanism DETECTS and SURFACES a missing evidence slot
     (e.g. `document_pdfs` absent → dossier renders incomplete, never fabricated, never dropped),
     but there is NO interactive "system requests the missing document → user supplies it →
     loop resumes" path.
   - **Gated on:** (1) a real DOCUMENT provider replacing `AbsentDocumentProvider` (the still-owed
     `document_pdfs` slot source — shares the T2.12 adapter seam; Collin's transaction-data adapter
     is the foundation, but the document/PDF provider is a separate build), and (2) a request-resume
     interaction (UI upload + loop re-entry).
   - **Scope:** NOT part of T5.9 (front-door intent routing only). Document only; do not build.

9. **Stale `expected_rate=0.07` default (DEBT-4). — DONE (commit `c41d0a8`).**
   - Verify the current GST rate against the IRAS e-Tax Guide and config-thread it; do **not** trust the hardcoded `0.07` default.
   - **Independent of the Xero work; affects the LIVE path.** Cross-ref `KNOWN-LIMITATIONS-xero-demo.md` DEBT-4/DEBT-5 and roadmap **OD-8** (rate-threading).
   - **Scope:** verify-before-encode; not a tax assertion here.
   - **Closure (branch `t-debt4-remove-rate-default`, commit `c41d0a8`):** the `= 0.07` default is removed on `_classify_line` / `validate_invoice_tax_codes` / `detect_gst_errors`; `expected_rate` is now REQUIRED and schema-required at the FastMCP tool layer, with a `None`-guard raising a `ValueError` naming `applicable_gst_rate`. The automated chain already threaded `applicable_gst_rate` (`orchestrator/steps.py:321/348`), so this is behaviour-preserving on every automated path — the offline-replay chain is byte-identical to the frozen oracle; the real exposure closed was the manual MCP surface. Covered by `tests/test_debt4_expected_rate_required.py` (6 tests); full suite **2075 passed, 1 skipped**. Honest-status ladder: built → hermetically-tested → offline-replay-validated; moves NO rung toward T2.11; `show_ai_candidates` / `validation_status="unvalidated"` UNCHANGED.

11. **Mid-period 7%→9% GST rate-transition handling — DEFERRED.**
   - `expected_rate` is a single scalar per run; a period straddling the 2024-01-01 rate change uses one rate for all lines, so a genuinely mixed-rate period cannot be validated line-accurately.
   - **Gated on:** date-of-supply semantics sourced from an IRAS primary source; **T2.11-gated** (introduces new tax-date semantics — a tax assertion, not encodable here). Cross-ref roadmap **OD-8** and the rate-transition edge-case fixture gap.
   - **Scope:** verify-before-encode; document only, build nothing yet.

12. **Manual MCP stdio tool-surface review — DEFERRED.**
   - The DEBT-4 signature change closes the **schema level** (a manual caller omitting the rate now fails tool-call validation).
   - **Follow-up:** confirm whether/where `python sap_b1_server.py` (`mcp.run` stdio, "Claude Desktop") is actually deployed against real data, AND review `agent/read_tools_server.py` as a second, separately-served MCP tool surface not covered by the DEBT-4 fix.
   - **Scope:** review/confirm-deployment; document only, build nothing yet.

10. **Manual-journal Xero-F5 behaviour — capture + freeze before building T2.24.**
   - The "a manual journal drops out of the SG Xero F5 report" behaviour is a platform-behaviour claim demonstrated once by Avinash.
   - Capture it from a **real Xero export** and **freeze as a fixture** before the **T2.24** control-ledger ↔ F5-report reconciliation check is built (cross-ref roadmap T2.24 / ASK cell 1.3e).
   - **Scope:** prerequisite; verify-before-encode (NR-in-Box-5 precedent).

13. **Decision 2 — general-extract engine path ON — MERGED (PR #85, merge commit `e5bedbc`; built ≠ validated).**
   - The last of Terry's four pivot decisions. The general-extract upload path is changed from **coverage-only** to **UNVALIDATED findings**, run through the SAME deterministic chain via `ExtractChainReader` (**NO engine/chain change**), under a DEFAULT DEMO client config (`config/clients/extract_demo.yaml`, a copy of `xero_demo` values — **no new tax rule**). Gated by the GLOBAL kill switch `AGENTASSIST_EXTRACT_ENGINE` (**DEFAULT-ON**; OFF → pre-build coverage-only path, byte-identical); GLOBAL ONLY — the anonymous extract upload has no per-client identity, so there is deliberately NO per-client disable.
   - Response: `source_kind="extract_review"`, `queue: QueueItem[]` on the SHARED central review screen (reuses Build 2's `<ReviewScreen>`), `config_scope="default_demo"` marker; the frontend renders a LOUD three-clause caveat (unvalidated candidates / synthetic-format sample, real-client-export GTM-gated / default demo config that is NOT the uploader's — rate/tax-code-mapping findings not to be relied on, structural/arithmetic checks stand on their own). Honest-degradation UNCHANGED: the fixed-schema reader never guesses columns — off-format → degraded `coverage_status` or 422, never a fabricated finding.
   - **Honest status:** built ≠ validated, **MERGED (PR #85)**. Moves NO rung toward T2.11 (synthetic-format at best; real-client-export GTM-gated). Frozen flags UNCHANGED (`validation_status="unvalidated"`, `show_ai_candidates=False`); no `ai_candidates`; offline-replay byte-identical; F5 box-isolation intact (18 isolation tests pass). Test counts (Build 3 branch): vitest **37 → 39** (+2); new `tests/test_extract_engine_upload.py` (+4); full pytest suite **2097 passed, 1 skipped, and 3 EXPECTED-RED** (pre-existing append-only tests locking the OLD coverage-only/engine-never-runs contract that DEFAULT-ON supersedes — Terry amends them in a SEPARATE commit; behaviour change, not other regressions). See `AGENTASSIST_TECHNICAL_STATE.md` §T-build3 and roadmap "Build 3".
   - **Four-decision batch COMPLETE** — Build 3 is the last of the four pivot decisions; all four are shipped (Build 3 merged via PR #85).

14. **Doc-drift in `scripts/capture_sbodemosg_extract.py` (stale count-key comments) — code fix, recorded here only (found backlog-truth pass, 2026-07-03).**
   - The comments at ~`:60-61` ("orchestrator/steps.py reads 'odata.count' (no @) — the Gate-1 latent bug") and ~`:138-139` ("orchestrator/steps.py reads 'odata.count' (no @), so Gate 1 warn-passes unconditionally") describe a **pre-PR#81** unprefixed `@odata.count` read at `orchestrator/steps.py` — a location that **no longer performs the read**: it was relocated to `SapChainReader.count` (`mcp-servers/custom/sap_b1_server.py`) by the T2.23 chain source seam and **fixed** in PR #81 (`743fb0d`) to read `@odata.count`. A future recon reading these comments would be misled about where the count is read and whether the bug is live.
   - **Scope:** a **code edit**, not a docs edit — deliberately NOT applied in the backlog-truth docs-sync (that commit was `.md`-only). Do it on the next branch that already touches that file. No behaviour change (comment-only).

15. **`POST /review/upload` broad `except → 422` mislabel — FIXED (branch `t-upload-error-honesty`; built ≠ merged).**
   - **Was:** the upload handler wrapped its engine-path calls in a broad `except Exception → 422 "Could not read export"`, relabeling ANY failure — including engine-INTERNAL bugs downstream of a cleanly-parsed file (`serialize_xero_queue`, `compile_output` access, `coverage_status()` derivation) — as a client-input error. It blamed the user for our breakage and hid real internal failures, on a path made live by Build 3 (#85). Surfaced by the T2.12 and this item's recon (Step 6 adjacent-hazards).
   - **Fix (Option A — positional split, `api/app.py`):** only format detection + reader construction (+ the Xero period parse) stays inside the 422 boundary (genuine bad-input → "couldn't read your file"); engine execution runs below it and surfaces an internal failure as an honest, **logged 500** that does not blame the file. The helpers' deliberate reconciliation-halt `HTTPException(422)`s re-raise unchanged. **Guardrail:** `coverage_status()` encodes honest degradation as RETURNED data (`degraded`/`unavailable` rows on a 200), never a raised exception, so moving derivation below the boundary relabels no degradation as a 500.
   - **Honest status:** correctness/honesty fix on a live path — moves NO rung toward T2.11; no tax semantics; frozen flags UNCHANGED. Confined to `api/` (no engine/chain/box/finding-logic/config change); box-isolation intact (20 tests), offline-replay byte-identical, `orchestrator/` pure, `api/` anthropic-free. Failing-test-first `tests/test_upload_internal_error_honesty.py` (internal→500 RED→GREEN; degradation→200 guardrail); full suite **2102 passed, 1 skipped**. The pre-existing bad-input-still-422 pins (`test_tsource_selector_upload.py`, `test_extract_engine_upload.py` BT3) stay green.

16. **Outbound Xero export tool — real-client-export validation OPEN (built on branch `t-xero-outbound-export`, 2026-07-06, MERGED `99cc49b`).**
   - **Built:** a SEPARATE outbound tool (`exports/` leaf, OUTSIDE `orchestrator/`, zero `anthropic`) re-shapes the FULL raw SAP capture (`tests/fixtures/sbodemosg-extract/*.raw.json`) into the three Xero import CSVs (Invoices / Bills / Contacts). Crosswalk `exports/xero_crosswalk.py` maps SAP VatGroup → IRAS Annex E (18 rows, Terry-authored), cited in-repo to `knowledge-base/etaxguide_gst_invoicenow_requirement.pdf` (Annex E pp.79-83); unmapped code flags-and-halts. AccountCode emitted BLANK; zero-qty→Qty=1/UnitAmount=line-net; SAP ISO→`DD/MM/YYYY`. Translation-only; box-isolation intact; `+32` tests → branch suite **2134 passed, 1 skipped**.
   - **OPEN (GTM-gated):** validation is **DEMO/SBODEMOSG-format only** — the tool has NOT been run against a **real client SAP export** (no real full export exists in the tree; only the SBODEMOSG demo capture). Real-client-export validation awaits the first such engagement (same GTM gate as the inbound Xero DEBT-3). Until then: demo-only, not customer-facing.
   - **Open sub-items for Terry:** (i) **column spec — CORRECTED (D37a, 2026-07-06):** `INVOICE_COLUMNS`/`BILL_COLUMNS` now carry the FULL ordered Xero template headers (29 / 26 cols) with unused columns present-but-blank, and a test proves the emitted CSV header matches the template byte-for-byte; the 29/26-col lists were transcribed from Collin's real template files (NOT in-repo) — if those CSVs land in the tree, assert the constants against their header rows. **Contacts still 1 col (`ContactName`) — real template is 73 cols; whether Xero accepts a 1-col contacts import is STILL OPEN for Terry** (not guessed). (ii) Bills `InvoiceNumber` — **RESOLVED (D37b, 2026-07-06, branch `t-xero-bills-supplier-ref` / PR #89, MERGED `f47a36a`):** the bill path now prefers SAP `NumAtCard` (supplier's own ref) when present+non-empty, else falls back to internal `DocNum`, and every fallback is recorded in a new companion file `bills.fallbacks.csv` (Option A). Sales invoices untouched. **Still open (GTM gate):** SBODEMOSG has `NumAtCard` null on 100% of bills, so the prefer-`NumAtCard` branch is **synthetic-unit-tested only, NOT demo-exercised and NOT real-client-validated** — needs a real SAP export with populated supplier references to exercise + re-lock. (iii) crosswalk carries 9 Annex E targets (DS/ESN33/EP/OP/IGDS/ME/TX-ESS/TX-N33/TX-RE) not exercised by demo data — untested against real transactions.
   - **Scope decision — credit notes (sales + purchase) deliberately out of scope for the outbound export tool; build deferred (Terry, 2026-07-07).** The outbound tool exports **sales invoices and supplier bills only** — it exports no credit notes of either kind (`export_all` reads only the `Invoices` / `PurchaseInvoices` entities). This is a tracked, deliberate completeness limitation, not an oversight. (Credit notes remain handled on the **inbound** F5 review side — fetched and subtracted — so this note is scoped to the outbound `exports/` tool only.) The build is **deferred to the first real-client engagement**, gated on two entry conditions: (a) a throwaway Xero **test import** to confirm the Xero credit-note import format and whether amounts are entered **positive or negative** — Collin's manual step (observed provenance, not a tax ruling: SAP stores CN line amounts **positive**, per `exploration-notes/credit-note-exploration.md:65-83`; the Xero CN sign convention is **unconfirmed**); and (b) **Terry's confirmation** of the tax treatment for any credit-note tax codes not already confirmed against IRAS. **Offline-testable when built:** the frozen extract already carries **1 sales CN + 1 purchase CN** (VatGroups `SO` / `SI`, both already mapped in the 18-row crosswalk) — a thin but real fixture.
   - **Honest status:** moves NO rung toward T2.11; T2.11 unmoved; frozen flags UNCHANGED; no tax-accuracy verdict.

17. **Stale-local-master trap — start-of-build guard ADDED (Option 1, script-only; branch `t-preflight-base-check`, 2026-07-08).**
   - **Problem:** starting a feature on a local base already behind `origin/master` caused a recurring trap — **three merge-status mislabels + one rebase conflict**. There was no prior tracked backlog item for this; this item is newly created to record both the problem and the fix. (Dev-tooling / process, not a product rung.)
   - **Fix (Option 1, Terry-approved — script only, NO PreToolUse Bash hook):** a new standalone `scripts/preflight_base_check.py` is the Build SOP's **step-0**, run at the start of a task before the worktree/branch is created. It `git fetch`es `origin master` (updates the remote-tracking ref ONLY — no merge/checkout/local mutation) then checks `git merge-base --is-ancestor origin/master HEAD`: **PASS** (exit 0) if HEAD contains `origin/master`, **REFUSE** (non-zero, instructing `git pull origin master`) if behind. It **refuses only** — never auto-pulls/rebases/checks-out. Offline (fetch fails) → honest `UNVERIFIED` notice, exit 0 (warn-and-allow). Pure stdlib, no `anthropic`; touches no `orchestrator/`, fixture, oracle, or tax-semantics artifact; produces no finding and renders nothing in the report (offline-replay / oracle checks N/A). Documented as step-0 in `CLAUDE.md`. Lean-defaults (Terry to flip on review): Python (Windows portability); warn-and-allow offline; formal step-0 in the SOP doc.
   - **Scope — start-stale (step-0) + mid-flight (pre-PR-open) now BOTH covered.** The step-0 `preflight` guard catches a base stale **at the moment work starts**. The mid-flight case — a base that goes stale **DURING** a build (someone else merges to master mid-task, as forced the PR #92 rebase) — was originally left as a separate still-open gap; it is now **ADDRESSED** by the `--context=prepr` mode on the same script (branch `t-prepr-staleness-check`, 2026-07-08): run `python scripts/preflight_base_check.py --context=prepr` right before `gh pr create` and it TELLS you to `git rebase origin/master` (with the N-commit count) if master advanced. Same freshness primitive, mid-flight remediation (rebase, not pull); detect-and-tell only, zero mutation. **Both are advisory** (script-run, no auto-blocking hook — a human who skips the step is not blocked, by design), so read this as "the stale-master pattern now has a guard at both ends," not "mechanically impossible to hit." The default no-flag / `--context=preflight` behaviour is byte-identical to the merged step-0 guard (proven by the locked `tests/test_preflight_base_check.py` passing untouched); new `prepr` coverage is in a new file `tests/test_preflight_prepr_check.py` (3 cases: advanced→REBASE / not-advanced→safe / offline→UNVERIFIED).
   - **Honest status:** dev-tooling; built -> hermetically-tested (failing-test-first `tests/test_preflight_base_check.py`, 3 cases: base-current PASS / base-behind REFUSE / offline UNVERIFIED, all green; full suite 2154 passed, 1 skipped). Moves NO product rung; does not touch T2.11 or any customer-facing accuracy claim; frozen flags UNCHANGED.

18. **Inbound Xero SALES-INVOICE feeder — parked-vocabulary gap + open questions (branch `t-xero-sales-feeder`, 2026-07-09; built ≠ validated, UNMERGED).**
   - **Built:** an INBOUND Xero sales-invoice feeder — `feeders/xero_sales_reader.py` (`XeroSalesInvoiceChainReader`) + an `is_xero_sales_invoice_workbook` router detector — parses a flat, one-row-per-invoice-line Xero sales-invoice export (CSV or `.xlsx`), groups by `InvoiceNumber` into canonical sales-invoice documents (multi-line invoice → one doc, ordered lines, synthesized `line_index`), and threads through the SAME engine chain via a new `POST /review/upload` branch (`source_kind:"xero_sales_upload"`, `config_scope:"xero_sales_demo"`) checked AFTER the F5 detector and BEFORE the `ExtractChainReader` fallback. Absent surfaces degrade honestly via the EXISTING `derive_coverage_statuses` seam (NO_GST_REG unavailable, DUP_CLAIM/SEQ_GAP degraded); `DocNum` carries the non-numeric `InvoiceNumber` string. Mapping is **Terry-authored against IRAS Annex E** (`knowledge-base/etaxguide_gst_invoicenow_requirement.pdf`, Annex E) — provenance DISTINCT from the F5 demo's DEBT-1 deferral. NEW loader mechanism: optional `out_of_scope_codes` YAML key (uppercased, validated disjoint from `tax_code_mappings` keys) — an out-of-scope TaxType line is ACCEPTED but set aside and its count/reason surfaces VISIBLY (`out_of_scope` response field), never silent. Tests: `tests/test_xero_sales_feeder.py` (10), `tests/test_xero_sales_upload.py` (1), `tests/test_xero_sales_loader_config.py` (2); full suite **2170 passed, 1 skipped** (+13).
   - **OPEN — parked-13 vocabulary gap (Terry, Option 3).** Ship the 19 accepted `tax_code_mappings` rows now; **PARK 13** rows whose canonical VatGroup target is NOT in `config/loader.py` `_STANDARD_VAT_GROUPS` (TXCA, SRCA-S, IM-N33, IM-ESS, IM-RE, SROVR-LVG, SRLVG, TX-ESS, SROVR-RS, TXRC-N33, TXRC-ESS, TXRC-RE, TXRC-TS) pending **T2.21** vocabulary resumption (adding the codes + their F5 box routing). The parked 13 live as COMMENTS in `config/clients/xero_sales_demo.yaml` (never loaded); a Xero line carrying one fails LOUD (`ValueError`) until then. **Sales-side exposure:** SRCA-S, SROVR-LVG, SRLVG, SROVR-RS lines fail loud until T2.21 resumes.
   - **OPEN — TX-ESS possible rename of TX-E33 (Terry open question).** The parked `"Partially Exempt Traders Regulation 33 Exempt": TX-ESS` may be a rename of the existing canonical `TX-E33`; unresolved, to reconcile at T2.21.
   - **OPEN — E-check face-rate-0 coverage-gap finding (report-only, for Terry).** The face-rate-0 code families (reverse-charge `TXRC-*`, import `IM*`/`IGDS`/`ME`) sit OUTSIDE every E-check's `vg` set (`_STANDARD_RATE_SALES={SR,DS}`, E4 only `{SR,TX}`) — so on a `TaxAmount=0` line they produce NO false positives, but they also get NO E-check coverage at all (uncovered, NOT validated-and-passed). Report-only; do not read absence-of-flag as a pass.
   - **OPEN — real-Xero vocabulary / column-header pinning PENDING (GTM-gated).** The feeder parses the real Xero sales-invoice export FORMAT over SYNTHETIC content only; the exact real column-header set / TaxType vocabulary have NOT been pinned against a genuine export (same GTM gate as inbound F5 DEBT-3).
   - **Honest status:** built → hermetically-tested → real-Xero-FORMAT parsing over SYNTHETIC content; **NOT real-client-export-validated, NOT accuracy-validated.** Moves NO rung toward T2.11; frozen flags UNCHANGED (`validation_status="unvalidated"`, `show_ai_candidates=False`); offline-replay byte-identical (no chain change); `feeders/` stays a leaf. Cross-ref `KNOWN-LIMITATIONS-xero-demo.md` (XS-1/-2/-3/-4) and `AGENTASSIST_TECHNICAL_STATE.md` §T-xero-sales-feeder.


