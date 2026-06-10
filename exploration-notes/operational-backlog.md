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
