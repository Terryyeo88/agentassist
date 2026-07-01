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

9. **Stale `expected_rate=0.07` default (DEBT-4).**
   - Verify the current GST rate against the IRAS e-Tax Guide and config-thread it; do **not** trust the hardcoded `0.07` default.
   - **Independent of the Xero work; affects the LIVE path.** Cross-ref `KNOWN-LIMITATIONS-xero-demo.md` DEBT-4/DEBT-5 and roadmap **OD-8** (rate-threading).
   - **Scope:** verify-before-encode; not a tax assertion here.

10. **Manual-journal Xero-F5 behaviour — capture + freeze before building T2.24.**
   - The "a manual journal drops out of the SG Xero F5 report" behaviour is a platform-behaviour claim demonstrated once by Avinash.
   - Capture it from a **real Xero export** and **freeze as a fixture** before the **T2.24** control-ledger ↔ F5-report reconciliation check is built (cross-ref roadmap T2.24 / ASK cell 1.3e).
   - **Scope:** prerequisite; verify-before-encode (NR-in-Box-5 precedent).
