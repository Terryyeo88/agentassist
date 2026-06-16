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
5. **Gate 1 latent bug — `@odata.count` key mismatch (found T2.12a recon, 2026-06-16).**
   - **Root cause:** the count-probe reads `count_resp.get("odata.count")`, but the
     v2 Service Layer returns the total under **`@odata.count`** (with the `@` prefix). The key
     never matches → `inline_count` is always `None`. This is a v1→v2 OData key-prefix
     mismatch, not a missing SAP feature. (Probe 2026-06-16: count-probe response keys were
     `['@odata.count', '@odata.context', 'value']` — the count *is* present.)
   - **Location update (T2.23, 2026-06-16):** the probe + buggy extraction moved from
     `orchestrator/steps.py::_fetch_entity` into `SapChainReader.count` in
     `mcp-servers/custom/sap_b1_server.py` (the S0 surface of the chain source seam). The bug
     was **preserved verbatim** — T2.23 is behaviour-preserving and the frozen oracle encodes
     today's `None` → Gate-1 dormancy. The fix still belongs to a separate failing-test-first
     task and should now target `SapChainReader.count`.
   - **Impact:** Gate 1 warn-passes **unconditionally** on this instance, so incomplete
     pagination is currently uncaught — the gate is effectively dormant; completeness rests only
     on the structural `len(page) < 20` sentinel, never on a SAP-reported arithmetic total.
   - **Doc correction owed:** `AGENTASSIST_TECHNICAL_STATE.md` (line ~689, Gate-1 dormancy) and
     line ~1326 attribute this to "Service Layer (version 1000250) does not return `odata.count`".
     That attribution is **disproven** — fix in the next doc-sync.
   - **Scope:** the fix itself is **out of scope here** — separate failing-test-first task (write
     a test asserting Gate 1 reads `@odata.count` and FAILs on a real mismatch, then correct the
     key). Found read-only during T2.12a read-surface recon; nothing changed in this commit.
