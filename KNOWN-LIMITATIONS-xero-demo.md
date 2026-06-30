# Known limitations — Xero demo path (T2.12-Xero)

**Status: PROPOSED / DEMO — not authored, not validated.**

This document tracks the known debt carried by the Xero F5 feeder demo path so the
items are *tracked, not orphaned*. The Xero path ships as a **format-synthetic demo**:
it parses the real Xero "GST F5 Return → Transactions by box number" export format
against a committed synthetic fixture. It is **not** real-client validated and **not**
accuracy-validated, and its tax-code mapping citations are **deferred**.

**PR-A status (branch `t-xero-f5-reader`, built ≠ validated).** A real-**FORMAT** Xero F5
reader now EXISTS as an **UNWIRED feeder**: `feeders/xero_f5_reader.py`
(`XeroF5ChainReader`) parses the genuine "Transactions by box number" export (4-row
title-block skip / structural row-5 header; `" (NN%)"` tax-rate suffix strip incl.
double-suffix; value-box-only structural selection that SKIPS the tax/restatement boxes —
Box 6/7/19 — so value↔tax duplication is removed by box-section membership, NOT a content
hash) and satisfies the same structural `ChainReader` contract as `ExtractChainReader`.
`tests/test_xero_f5_reader.py` (**8 tests, all pass**) validates it over the committed
fixture; full suite **2062 passed, 1 skipped**. **This is real-FORMAT validation over
SYNTHETIC data — NOT accuracy-validated (T2.11) and NOT a real client file.** The reader
is **NOT wired into the engine** (`POST /review/upload` stays coverage-only;
`engine/review.py` still calls `run_chain` with no reader) — threading it in is **PR-B
(deferred, separate PR)**, so uploads do not yet produce real findings. PR-A closes **none**
of the debts below: the tax-rate→VatGroup mapping is still PROPOSED/UNVALIDATED (DEBT-1),
real-client validation is still pending (DEBT-3), the absent-surface degrades (DEBT-6/-7/-8)
are now IMPLEMENTED as honest degradation but the checks remain degraded/unavailable, and
the E4 rate (DEBT-4/-5, PR-C), loader `sap_b1`-block requirement (DEBT-9, PR-D) and
`xero_demo.yaml` citations (PR-E) remain open.

**PR-B status (branch `t-xero-engine-wire`, built ≠ validated).** The PR-A reader is now
**WIRED into the engine**: `engine/review.py`'s `ReviewInputs` gained an optional `reader`
field that `review()` threads into `run_chain` (the live-SAP path is **byte-identical** —
`reader=None`), `orchestrator/steps.py` carries a tolerant `_coerce_doc_num` (numeric →
`int()`, **SAP path byte-identical**; non-numeric external reference → string fallback for a
non-SAP feeder), and `POST /review/upload` is now **format-routed**: a real Xero
"Transactions by box number" export → `XeroF5ChainReader` → `load_client_config("xero_demo")`
→ `review()` → a 5-key response `{source_kind:"xero_f5_upload", validation_status:"unvalidated",
disclaimer, coverage_status, findings}`. ANY OTHER `.xlsx` stays the UNCHANGED coverage-only
`ExtractChainReader` path (4 keys, `source_kind:"extract_upload"`, engine NOT run —
byte-identical). On the committed fixture exactly **3** real line-level findings surface — **E2**
(`INV-2003`, GST on zero-rated), **E3** (`INV-2002`, standard-rated with zero tax), **E4**
(`BILL-3002`, 8% vs the configured 9%; E4 compares against `applicable_gst_rate=0.09`, so clean
9% lines do **not** false-fire). **DUP_CLAIM (degraded), NO_GST_REG (unavailable) and SEQ_GAP
(degraded) remain DARK on this path** — surfaced honestly in `coverage_status`, never silent
absence and never fabricated. Full suite **2066 passed, 1 skipped** (+4 over PR-A's 2062).
**The reader→engine wiring deferred in PR-A is now DONE; this branch is UNMERGED.**
**HONEST STATUS — these are real-Xero-FORMAT findings over SYNTHETIC data: CANDIDATES, never
verdicts.** It is **NOT a real client file** and asserts **NO GST/accuracy verdict** (T2.11
unmoved — `validation_status` stays `"unvalidated"`). The tax-rate→VatGroup mapping is still
**PROPOSED / UNVALIDATED** (DEBT-1). PR-B closes **NONE** of the debts below (DEBT-1/-3/-4/-5/
-7/-10 stay open); it makes the Xero ingestion path produce real (unvalidated) findings
end-to-end. Out of scope for PR-B: E4 `0.07` default removal (PR-C), `sap_b1` optional in the
loader (PR-D), `xero_demo.yaml` citations (PR-E).

Companion files:
- Reader: `feeders/xero_f5_reader.py` (PR-A — real-FORMAT, SYNTHETIC-data, UNWIRED)
- Tests: `tests/test_xero_f5_reader.py` (PR-A — 8 tests over the fixture)
- Config: `config/clients/xero_demo.yaml` (PROPOSED/DEMO, deferred citations)
- Fixture: `tests/fixtures/xero-f5-export/AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx`

Ground truth for the line/file references below is re-recon commit `294490e`;
re-verify before acting on any line number.

---

## Debt items

### DEBT-1 — IRAS citations deferred for the five tax-code mappings
The five `tax_code_mappings` entries in `xero_demo.yaml` carry `cite DEFERRED` markers
instead of confirmed IRAS authority. Each must be traced to a confirmed IRAS Annex E
row before the mapping is gate-clean. Per the NR-in-Box-5 rule, model inference is not
authority. **Owner: Terry.** Blocks: treating the Xero mapping as "authored".
*PR-A update (still OPEN):* the PR-A reader now carries its OWN name-stem→VatGroup map
(`feeders/xero_f5_reader.py` `_PROPOSED_VAT_GROUP_MAP` / `tax_rate_to_vat_group`) as a
**PROPOSED / UNVALIDATED CANDIDATE** that **fails loud** (`ValueError`) on an unmapped
name rather than guessing. This is a candidate, NEVER a verdict; the IRAS Annex E
citations remain DEFERRED — this debt is NOT closed.

### DEBT-2 — Category assignments are Terry-provided demo values, not gate-clean
`STANDARD-RATED SUPPLIES→SR`, `STANDARD-RATED PURCHASES→TX`, `SR-NOGST→SR`,
`ZR-BROKEN→ZR`, `SI-STALE→TX` are demo categories supplied by Terry. They are plausible
but unconfirmed against the IRAS guide; the config header and status are
**PROPOSED/DEMO**, not authored. Resolved together with DEBT-1.

### DEBT-3 — Not real-client validated
The path is validated only against the committed synthetic fixture in the real Xero
*format*. Real-client validation awaits Avinash's NDA'd Xero export. Until then: demo
only, not customer-facing.
*PR-A update (still OPEN):* the PR-A reader (`feeders/xero_f5_reader.py`) is exercised by
`tests/test_xero_f5_reader.py` over that synthetic fixture — **real-FORMAT-validated, NOT
accuracy-validated** and NOT a real client file. Real-client validation remains pending;
this debt is NOT closed.

### DEBT-4 — SAP-path E4 `expected_rate` defaults to 0.07 (found bug, NOT fixed here)
`_classify_line` (`mcp-servers/custom/sap_b1_server.py:747`) and the call sites at
`:1224`, `:1364` default `expected_rate` to `0.07`. This is a pre-existing SAP-path bug
surfaced during recon. It is **deliberately left untouched** by the Xero work (no
opportunistic fix). Tracked here for separate remediation.

### DEBT-5 — Xero E4 rate threading not wired
The client's `applicable_gst_rate` (0.09) is not threaded into `_classify_line`. Until
the feeder build wires it (subject to Terry's rate-threading ruling), E4 compares
against the 0.07 default and fires spuriously on every clean 9% line. This is the one
unresolved seam gating the Phase-2 build.

### DEBT-6 — DUP_CLAIM basis differs on the Xero path
`detect_dup_claims` (`orchestrator/check_listing.py:167`) keys on
`(CardCode, NumAtCard, DocTotal)` and skips blank `NumAtCard`. The Xero export has no
`NumAtCard`, and the true duplicate pair (BILL-3004/3005) has the same Contact +
amount but *different* References. The Xero path must source the dup key from
`(Contact, amount)` and declare DUP_CLAIM **degraded**. Prefer an additive Xero-specific
path over editing the SAP detector (box-isolation/determinism).
*PR-A update (still OPEN):* the PR-A reader has no listing surface — `fetch_listing`
returns the four canonical buckets EMPTY and `coverage_status()` marks DUP_CLAIM
**degraded** through the shared `derive_coverage_statuses` seam (honest degradation, no
fabricated listing). The additive `(Contact, amount)` Xero dup detector is NOT built; this
debt is NOT closed.
*PR-B update (still OPEN):* now that the reader is engine-wired (`POST /review/upload` Xero
branch), DUP_CLAIM stays **DARK on this path** — it surfaces as **degraded** in the response
`coverage_status`, never as a silent absence and never fabricated. NOT closed.

### DEBT-7 — NO_GST_REG unreachable on the Xero path
The export has no business-partner master and no `FederalTaxID` column, so NO_GST_REG
cannot run — it surfaces as coverage **unavailable** (`feeders/coverage_status.py:145-148`).
BILL-3003 ("NoReg Trading") therefore cannot be flagged; this is honest degradation,
not a missed finding.
*PR-A update (still OPEN):* the PR-A reader honours this — `get_business_partner` RAISES
`KeyError` (never fabricates a BP) and `coverage_status()` marks NO_GST_REG **unavailable**.
The honest degrade is implemented; the check remains unavailable — this debt is NOT closed.
*PR-B update (still OPEN):* on the engine-wired upload path NO_GST_REG stays **DARK** —
surfaced as **unavailable** in the response `coverage_status`, never a silent miss. NOT closed.

### DEBT-8 — SEQ_GAP out of scope on the Xero path
No `Series`, `Cancelled`, or company-wide listing in the export → SEQ_GAP is out of
scope (degraded/unavailable via the coverage seam). No within-period sequence range is
testable.
*PR-A update (still OPEN):* the PR-A reader carries the reference string in `DocNum` (no
numeric series) and returns an EMPTY listing, so `coverage_status()` degrades SEQ_GAP via
the shared seam. The honest degrade is implemented; the check remains degraded — this debt
is NOT closed.
*PR-B update (still OPEN):* on the engine-wired upload path SEQ_GAP stays **DARK** — surfaced
as **degraded** in the response `coverage_status`, never a silent absence. NOT closed.

### DEBT-9 — Loader requires a `sap_b1` block + credential env vars for a Xero-only client
`config/loader.py:273-277, 295-302` require a `sap_b1` block and resolve its credential
env vars at load, even when `source_system != "sap_b1"`. The demo config uses a **dummy
`sap_b1` block** as a workaround. A cleaner fix — making `sap_b1` optional when
`source_system != "sap_b1"` — touches shared config validation and needs its own
invariant review; deferred.
*PR-B update (NOW A LIVE RUNTIME DEPENDENCY, still OPEN):* PR-B wired the engine-review
upload path, so `load_client_config("xero_demo")` (and therefore `POST /review/upload`'s Xero
branch) now hard-requires `SAP_USERNAME`/`SAP_PASSWORD` env vars at runtime even though **NO
SAP call is made** on this path — `XeroF5ChainReader` short-circuits every read. **The
upload-review path requires those env vars (dummy values suffice) at runtime.** PR-B touches
ZERO loader code; making `sap_b1` optional for non-SAP clients remains **deferred to PR-D** —
this debt is NOT closed.

### DEBT-10 — `source_system` docstring understates its effect
`config/loader.py:114-116` documents `source_system` as "logging/display only", but it
is functionally load-bearing via `effective_tax_code_mappings` (`:195-197`), where any
value other than `"sap_b1"` suppresses the SAP SO/SI defaults. The docstring should be
corrected; do not rely on it for the three-times rule.
