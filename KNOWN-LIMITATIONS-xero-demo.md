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
are now IMPLEMENTED as honest degradation but the checks remain degraded/unavailable. The E4
`0.07`-default removal (DEBT-4, PR-C) is now **DONE** (branch `t-debt4-remove-rate-default`,
commit `c41d0a8`); the loader `sap_b1`-block requirement (DEBT-9, PR-D) is now also **DONE**
(branch `t-debt9-sap-decouple`, commit `8daf757`). The Xero E4 rate-threading concern (DEBT-5)
and `xero_demo.yaml` citations (PR-E) remain open.

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
end-to-end. Out of scope for PR-B: E4 `0.07` default removal (PR-C — since **DONE**, branch
`t-debt4-remove-rate-default`, commit `c41d0a8`), `sap_b1` optional in the loader (PR-D),
`xero_demo.yaml` citations (PR-E).

**BUILD 2 status (branch `t-build2-xero-central-review`, built ≠ validated, UNMERGED).** Build 2
resolves the **findings-dropped UI defect**: PR-B's engine-wired Xero upload already computed real
line-level findings server-side, but the `XeroUploadPanel` frontend rendered **coverage only** and
type-erased the findings, so a real Xero F5 upload never surfaced them. They now render.
**Contract reshape (supersedes PR-B's `findings` key — PR-B history above is NOT rewritten).** The
`POST /review/upload` **xero_f5** branch response is RESHAPED: the old flat `findings` (the 7-key
detector rows in the PR-B section above) is REPLACED by `queue: QueueItem[]` — the `findings` key is
REMOVED. A new `api/viewmodel.serialize_xero_queue()` reuses `serialize_queue_item` /
`check_reference`, so E2/E3/E4 carry their REAL `CHECK_REGISTRY` `iras_basis` — the SAME citation as
the SAP path, NOT manufactured — and `finding_id` uses SAP semantics `detect:{code}:{doc_num}`.
**A1 (shared central review screen):** the Xero findings route into the SAME `<ReviewScreen>`
(extracted `Queue` + `FindingDetail`) the SAP path uses; decision/sign is an INJECTED capability —
the SAP path injects it (behaviour-preserving), the Xero upload path OMITS it (no server-side store
to sign an uploaded review against) and shows an honest review-only note *"sign-off for uploads not
yet available"* — no dead controls. **B1 (companion-sheet ask):** the panel surfaces a
supplier-master (companion) sheet ask when a check is degraded/unavailable — a **COVERAGE FACT ONLY**
(no IRAS rationale); providing/ingesting the sheet is NOT built (deferred, net-new). **Dark checks
unchanged:** NO_GST_REG (unavailable), DUP_CLAIM/SEQ_GAP (degraded) and the doc-pre-pass
(unavailable) remain surfaced ONLY in `coverage_status`, NEVER fabricated into the queue. **NO
engine/chain change** — offline-replay stays byte-identical to the frozen oracle; F5 box-isolation
intact (18 isolation tests pass); `validation_status="unvalidated"` + `show_ai_candidates=False`
UNCHANGED. **Honest status:** moves NO rung toward T2.11 — the Xero findings remain **CANDIDATES,
unvalidated** (offline-replay-validated for the deterministic chain only; NOT a real client file,
NOT accuracy-validated). **Test counts:** vitest **32 → 37** (+5: `ReviewScreen.test.tsx` ×2,
`XeroFindings.test.tsx` ×3); new `tests/test_xero_queue_contract.py` (+3: BT1 queue contract, BT2
Decision-4 honesty, `finding_id` semantics). Full pytest suite on this branch: **2095 passed, 1
skipped, and 1 EXPECTED-RED** —
`tests/test_xero_engine_upload.py::test_xero_upload_runs_engine_and_returns_findings`, a pre-existing
test that asserts the SUPERSEDED `findings` contract; per the append-only-test boundary the builder
did NOT edit it. Terry authors its amendment as a SEPARATE commit onto this branch; the failure is
**SHAPE-only** (queue vs findings key-set), finding VALUES unchanged and re-locked by the new BT1 —
once the amendment lands the suite is fully green. This branch is **UNMERGED**; Build 2 closes NONE
of the debts below.

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

### DEBT-4 — SAP-path E4 `expected_rate` defaults to 0.07 — **RESOLVED** (commit `c41d0a8`)
*Historical (found bug, NOT fixed at Xero-recon time):* `_classify_line`
(`mcp-servers/custom/sap_b1_server.py:747`) and the call sites at `:1224`, `:1364` default
`expected_rate` to `0.07`. This was surfaced during recon and deliberately left untouched by the
Xero work (no opportunistic fix), tracked here for separate remediation.

**RESOLVED (branch `t-debt4-remove-rate-default`, commit `c41d0a8`):** the `= 0.07` default is
removed on all three functions — `_classify_line`, `validate_invoice_tax_codes`,
`detect_gst_errors` — so `expected_rate` is now REQUIRED, and a `None`-guard raises a clear
`ValueError` naming `applicable_gst_rate`. Because only a no-default arg marks a parameter
REQUIRED in the FastMCP tool schema, the manual MCP surface is now schema-hardened too (a caller
omitting the rate fails tool-call validation).

**Correction to the original "pre-existing SAP-path bug" framing (imprecise):** the automated
review chain already threaded `client_config.applicable_gst_rate`
(`orchestrator/steps.py:321/348`), so the 0.07 default was NEVER consumed on the automated path.
The real exposure was the **manual MCP (Claude Desktop stdio) surface** — now schema-hardened.
Behaviour-preserving on every automated path; the offline-replay chain is byte-identical to the
frozen oracle (box path `calculate_f5_return` takes no rate). Covered by
`tests/test_debt4_expected_rate_required.py` (6 tests); full suite **2075 passed, 1 skipped**.
Honest status: correctness/hygiene fix to the deterministic path's tool layer; moves NO rung
toward T2.11; `show_ai_candidates` / `validation_status="unvalidated"` UNCHANGED.

### DEBT-5 — Xero E4 rate threading not wired
The client's `applicable_gst_rate` (0.09) is not threaded into `_classify_line`. Until
the feeder build wires it (subject to Terry's rate-threading ruling), E4 compares
against the 0.07 default and fires spuriously on every clean 9% line. This is the one
unresolved seam gating the Phase-2 build.

> **FLAG for Terry (DEBT-5 is Terry-owned; not touched or closed here).** The DEBT-5
> description above is **STALE vs the verified code** and this doc is **internally inconsistent**:
> - The automated chain **does** thread the config rate via `run_chain` /
>   `orchestrator/steps.py:321/348` — so the claim that `applicable_gst_rate` "is not threaded …
>   E4 compares against the 0.07 default and fires spuriously on every clean 9% line" no longer
>   matches the code (and, post-`c41d0a8`, there is no 0.07 default to fall back to at all).
> - This same doc contradicts itself: line ~42 (PR-B section) states "E4 compares against
>   `applicable_gst_rate=0.09`" (threaded), while the DEBT-5 text says "not threaded".
> - `config/clients/xero_demo.yaml:21` carries a "NB: not yet threaded" comment that is likewise
>   stale.
> These are recorded as a FLAG for Terry to reconcile as part of the separate DEBT-5 item; no
> Xero behaviour is changed here and DEBT-5 is **NOT** closed.

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

### DEBT-9 — Loader requires a `sap_b1` block + credential env vars for a Xero-only client — RESOLVED (branch `t-debt9-sap-decouple`, commit `8daf757`)
`config/loader.py:273-277, 295-302` (historically) required a `sap_b1` block and resolved its
credential env vars at load, even when `source_system != "sap_b1"`. The demo config used a
**dummy `sap_b1` block** as a workaround. A cleaner fix — making `sap_b1` optional when
`source_system != "sap_b1"` — touches shared config validation and needed its own
invariant review; historically deferred.
*PR-B update (was NOW A LIVE RUNTIME DEPENDENCY):* PR-B wired the engine-review
upload path, so `load_client_config("xero_demo")` (and therefore `POST /review/upload`'s Xero
branch) hard-required `SAP_USERNAME`/`SAP_PASSWORD` env vars at runtime even though **NO
SAP call is made** on this path — `XeroF5ChainReader` short-circuits every read. That made the
upload-review path require those env vars (dummy values sufficed) at runtime.
*RESOLVED (`8daf757`):* the `sap_b1` block + creds are now required **iff**
`source_system == "sap_b1"` (the default — SAP clients keep the loud load-time guard).
File-import clients (`source_system: xero`/`myob`/`quickbooks`/…) omit the block; their SAP
connection fields default to `""` (not `None` — `run_chain` calls `configure_client`
unconditionally, so `""` is the tolerated no-contact state). A **typo-guard** rejects only
values confusable with `sap_b1` (canonical-lowercased-alnum ∈ {`sapb1`,`sap`} and != `sap_b1`)
with a "did you mean sap_b1?" error, so a mistyped `sapb1` cannot silently switch off the SAP
requirement; `source_system` otherwise stays an OPEN label (no closed allow-list). The dummy
`sap_b1` block was deleted from `config/clients/xero_demo.yaml`. This is **no longer a runtime
dependency for the Xero path**. **Honest status:** pure plumbing; built → hermetically-tested
→ offline-replay-validated on the SAP path (offline-replay **byte-identical** to the frozen
oracle — SAP spine undisturbed). Moves NO rung toward T2.11; `validation_status="unvalidated"`
and `show_ai_candidates=False` UNCHANGED; no tax semantics. Verified by
`tests/test_debt9_sap_decouple.py` (18 tests, incl. a real-`run_chain` zero-SAP-contact proof);
full suite **2093 passed, 1 skipped**. This debt is now CLOSED.

### DEBT-10 — `source_system` docstring understates its effect — RESOLVED (commit `8daf757`)
`config/loader.py:114-116` (historically) documented `source_system` as "logging/display
only", but it is functionally load-bearing via `effective_tax_code_mappings` (`:195-197`),
where any value other than `"sap_b1"` suppresses the SAP SO/SI defaults.
*RESOLVED (`8daf757`):* the docstring is corrected and `source_system` is now formally
LOAD-BEARING — it drives `effective_tax_code_mappings` AND (as of DEBT-9) gates the `sap_b1`
block/creds requirement. This debt is now CLOSED.
