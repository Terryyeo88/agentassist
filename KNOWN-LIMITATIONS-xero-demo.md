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
yet available"* — no dead controls **(SUPERSEDED by B3a-2 — see the UPDATE box after this paragraph)**. **B1 (companion-sheet ask):** the panel surfaces a
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

> **UPDATE — B3a-2 upload-panel adjudication (`D-2026-07-22-b3a2-xero-adjudication`, branch `t-b3a2-xero-adjudication`, code commit `a68655f` (base: t-b3a2-test-amendment `9e23a53` = master `ec2dc7f` + the hand-amended test), UNMERGED; built + suite-verified ≠ validated).**
> Build 2's *"sign-off for uploads not yet available"* review-only state is **SUPERSEDED**. The Xero upload panel now **injects the
> shared adjudication capability**: Accept / Decline / Not-an-issue / Mark-known **persist** via the EXISTING `POST /decision`
> (per-config store keyed by a frontend `source_kind → client_id` map — `xero_f5_upload → xero_demo`, `extract_review →
> extract_demo`, `xero_sales_upload → xero_sales_demo`; the upload response's frozen key set carries no `client_id`, so the map is
> the frontend half of the contract) and **RE-APPLY** on re-upload of the retained workbook. **Sign is enabled for
> `xero_f5_upload` ONLY** (`POST /sign/upload` **422s** any other format); **sales / extract uploads get decisions but NOT sign**
> (stated in the panel copy). **No silent dead buttons:** a row **without a deterministic fingerprint** — a ledger-reconciliation
> finding or a probabilistic finding — renders **DISABLED** decision controls with a **visible per-cause reason** (never hidden,
> never a button recording into evaporating state), on BOTH the upload panel and the SAP `/review` surface. The enabler is
> **fingerprint-always** in `api/viewmodel.serialize_xero_queue` (every DETECT row stamps its deterministic fingerprint regardless of
> store contents; **ledger-recon rows stay un-fingerprinted** — #46 migration territory). **Reviewer identity** is a panel-local
> **free-text "Reviewer of record"** input — the same free-text concept as the SAP surface, so spelling can vary across sessions
> (a **data-quality note, not a correctness claim**). **Open item #45 (multi-tenant ship-blocker) is UNCHANGED** — panel decisions
> write to the **SHARED** per-config stores (`decisions/xero_demo/` etc.), so it is now more reachable from the UI, but is not
> resolved and not made worse. **+7 pytest** (new `tests/test_b3a2_fingerprint_always_uploads.py`; Terry's red baseline
> `tests/test_decision_reapply_upload.py` flipped green): branch full suite **2759 passed, 1 skipped, 6 xfailed, 2 xpassed**
> (+7 over master `ec2dc7f`'s 2752/1/6/2); frontend **vitest 55 pass across 16 files**. Real-Xero-FORMAT over SYNTHETIC data —
> **NOT real-client-validated, NOT accuracy-validated** (routing/persistence working is not a GST-accuracy claim);
> `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; offline-replay byte-identical; T2.11 unmoved;
> closes NONE of the debts below.

> **UPDATE — dossier content on the Xero upload surface (`D-2026-07-23-dossier-xero`, branch `t-dossier-xero`, code commit `5c588c2` on base `064b2fb`, UNMERGED; built + suite-verified ≠ validated).**
> The Xero UPLOAD paths (F5 + sales) now carry hermetic **case-file DOSSIER content** on their detect rows: the three ALREADY-PRESENT
> `QUEUE_ITEM_KEYS` fields `candidate_framing_text` / `completeness` / `inputs_hash` — which defaulted to `""`/empty/`—` on these paths
> before — are now populated by running the REAL `agent.loop.run_casefile_loop` over the upload's `ReviewResult` with a **deterministic
> AUTHORED template transport (NO model, NO network, $0)**; the framing string derives from the check's `CHECK_REGISTRY` `display_name`
> (the only tax language on it), is candidate-shaped, and is language-lint-pinned. **Cage stays PENDING-only** (a request-scoped
> `StagingStore` that is discarded — nothing approves/seals/emits). New module `agent/upload_dossiers.py`; `serialize_xero_queue` gained
> an OPTIONAL `dossiers=` kwarg (**VALUE-only, ZERO key churn** — `QUEUE_ITEM_KEYS` and the 5-key upload literals unchanged, absent/falsy
> dossiers → byte-identical defaults).
> - **FULL (satisfied) on Xero: E2 / E3 / E4** — every required slot is engine-seeded, so completeness is `{required==present per registry
>   `inputs_needed`, missing [], satisfied True}` and the row carries a real `sha256:` inputs_hash.
> - **INCOMPLETE-if-they-ran (both DARK on Xero today):** NO_GST_REG (needs `supplier_catalog`) and the document checks (need
>   `document_pdfs`) — surfaced only in `coverage_status`, never fabricated into the queue.
> - **DEFERRED — the EXTRACT branch is deliberately NOT wired** (Terry's "do F5 and REPORT why" fallback). Extract uploads yield NO_GST_REG
>   findings whose `supplier_catalog` slot is agent-gathered, and the extract SOURCE genuinely carries the supplier data (`FederalTaxID`
>   sheet) — so for an unwired gather neither R5 reason would be honest ("not gatherable" is false; "gathering failed" is false); the
>   reader's canonical BP projection also carries no `CardName` to key an honest catalog. Extract rows keep today's defaults, PINNED by a
>   test so a dishonest half-wiring cannot slip in. Catalog plumbing = follow-up.
> - **R5 note (Terry's condition, stated honestly):** completeness `missing` entries render as reason-suffixed plain strings
>   (`"<slot> - not gatherable on this source (…)"` for `supplier_catalog`/`document_pdfs`, else `"<slot> - gathering failed"`), but this
>   qualifier fires for **ZERO finding types on the wired upload paths** — its presence is NOT evidence anything is incomplete; it is
>   pinned before any finding type needs it.
> - **Bounded work (R2):** a finding count above `_MAX_DOSSIER_FINDINGS=1000` skips generation and APPENDS an honest degraded
>   `{"check":"case_file_dossiers","level":"degraded",…}` coverage row; queue fields stay at defaults.
> - **Sales endpoint population is serializer-exercised only** — the committed clean sales fixture yields no **E-check** findings (it does
>   legitimately fire the **COMPLETENESS** purchase-volume check — zero purchase invoices on a sales-only export); a finding-bearing
>   **E-check** sales fixture is a follow-up. The sales-route DEMO work (crafted ES33 + captured live exempt run) is DEMO-PREP, out of this build.
> - **Provider deferred (open item #47 in `AGENTASSIST_TECHNICAL_STATE.md`)** with the recorded **INV-INV trap**: `documents/provider.py`
>   hardcodes `INV-{doc_num}.pdf`, which against Xero STRING doc_nums (`INV-2003`, `BILL-3002`) would form `INV-INV-2003.pdf` — a future
>   Xero directory provider must key `{doc_num}.pdf`. E2/E3/E4 don't request `document_pdfs`, so this changes no current Xero dossier.
> - **DEBT-3 restated:** NO real Xero export has ever been read — all fixtures are real-FORMAT / SYNTHETIC; the dossier content is
>   **real-mechanism over synthetic data**, NOT real-client-validated and NOT accuracy-validated. **+8 pytest**
>   (`tests/test_dossier_xero_uploads.py`) → branch full suite **2774 passed, 1 skipped, 6 xfailed, 2 xpassed** (+8 over base
>   `064b2fb`'s 2766/1/6/2); offline-replay byte-identical; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED;
>   T2.11 unmoved; closes NONE of the debts below.

**XERO-SALES INBOUND status (branch `t-xero-sales-feeder`, built ≠ validated, UNMERGED).** A NEW,
SEPARATE inbound path — an INBOUND Xero **sales-invoice** feeder — now EXISTS alongside the F5
reader: `feeders/xero_sales_reader.py` (`XeroSalesInvoiceChainReader`) parses a flat,
one-row-per-invoice-line Xero sales-invoice export (CSV or `.xlsx`), groups by `InvoiceNumber` into
canonical sales-invoice documents (multi-line invoice → one doc, ordered lines, synthesized
`line_index`), and threads through the SAME engine chain via a new `POST /review/upload` branch
(`source_kind:"xero_sales_upload"`, `config_scope:"xero_sales_demo"`) checked AFTER the F5 detector
(`is_xero_f5_workbook` keeps precedence) and BEFORE the `ExtractChainReader` fallback, via the new
`is_xero_sales_invoice_workbook` router detector. Absent surfaces (supplier master, listing, credit
notes, purchase side, source PDFs) degrade honestly through the EXISTING `derive_coverage_statuses`
seam — **NO_GST_REG unavailable, DUP_CLAIM/SEQ_GAP degraded** — mirroring `xero_f5_reader.py`;
`DocNum` carries the non-numeric `InvoiceNumber` string (XeroF5 treatment). Its `tax_code_mappings`
are **TERRY-AUTHORED against IRAS Annex E** (`knowledge-base/etaxguide_gst_invoicenow_requirement.pdf`,
Annex E) — provenance **DISTINCT** from the F5 demo's DEBT-1 deferral (that stays deferred).
Verified by `tests/test_xero_sales_feeder.py` (10), `tests/test_xero_sales_upload.py` (1),
`tests/test_xero_sales_loader_config.py` (2) over the committed synthetic fixture
`tests/fixtures/xero-sales-export/` (+ helper `tests/synth_xero_sales_export.py`); full suite
**2170 passed, 1 skipped** (+13). **HONEST RUNG (T2.11 UNMOVED):** built → hermetically-tested →
real-Xero-FORMAT parsing over SYNTHETIC content — **NOT real-client-export-validated, NOT
accuracy-validated**; frozen flags UNCHANGED (`validation_status="unvalidated"`,
`show_ai_candidates=False`); offline-replay byte-identical (no chain change). This branch is
**UNMERGED**; it closes NONE of the debts below and carries its own new debt (XS-1/-2/-3 below).

> **UPDATE — Xero SALES sign-off now EXISTS (`D-2026-07-23-demo-prep-xero`, branch `t-demo-prep-xero`, on base `6742fdc`, UNMERGED; built + suite-verified ≠ validated).**
> The Xero SALES path is now **SIGNABLE at the API level.** `POST /sign/upload` **FORMAT-ROUTES**: the Xero-F5 detector keeps precedence (F5 sign byte-identical), then `is_xero_sales_invoice_workbook` routes a Xero sales-invoice workbook to a SALES branch that loads the **`xero_sales_demo`** config with the reviewer **stamped BEFORE `review()` renders**, derives the period from the documents' own DocDate range, and threads a **`sales_line_source`** so the **Phase-2b exempt pass** runs and its artefact **seals into the signed bundle at `steps/exempt-supply-candidates.json`**. Response: the SAME 7-key `SIGN_UPLOAD_KEYS`, **`source_kind` `"xero_sales_signed"`** (VALUE-only). A neither-format upload still **422s** (both detectors self-guard `False` on garbage — the existing F5-only-garbage 422 pin passes UNAMENDED).
> - **HERMETIC BY DEFAULT.** Over the committed ES33-free sales fixture the exempt pass **short-circuits `ok`/0-candidates with NO model call** (socket-guard-pinned) — the sales sign needs no key and no network.
> - **AI-candidate section only under the demo kit's TRANSIENT flag.** Every COMMITTED config keeps `show_ai_candidates=False`; the AI-candidates section renders ONLY when the uncommitted, gitignored `demo-kit/` replay server flips `show_ai_candidates=True` **transiently, in-process, for the `xero_sales_demo` config ONLY**. A render-layer fix (`report/sections.py`) makes `build_ai_candidates_section` tolerate Xero **string** doc_nums (e.g. `"INV-9001"`) — it previously crashed (`ValueError`) coercing them with `int()`; this is the render-layer cousin of open item #47's `INV-{doc_num}.pdf` trap.
> - **EXTRACT sign-off STILL PENDING** — only the sales half of the B4 extract/sales sign-off follow-up is delivered.
> - **DEFECT — the per-slice SALES (and extract) signed paper presents PARTIAL figures as a COMPLETE return (open item #48, HIGH PRIORITY, `D-2026-07-23-accumulated-sign`).** *[UPDATE, `D-2026-07-26-box-capability` (branch `t-box-capability`, UNMERGED, built + hermetically tested ≠ validated): **#48 is RESOLVED for the SALES signed paper** — boxes a sales export cannot populate now render "Not available from this source" (no figure), Box 8 renders its figure marked derived-from-incomplete naming Box 7, and a PDF-text pin now exists (`tests/test_sales_paper_box_pin.py`). **NOT resolved for extract** (no extract sign exists on master), and the extract engine path carries a SEPARATE, WORSE defect — see the SO/SI open item below.]* Terry's exact framing: *"today's per-slice sales/extract signed papers render all 8 F5 boxes with the missing side as 0.00 — partial figures presented as a complete return, on a SIGNED deliverable, live on master (shipped with #134's sales sign). A correctness/honesty defect, not cosmetics. HIGH PRIORITY."* This **affects the demo**, which signs a sales export via the uncommitted `demo-kit/`. The NEW accumulated-sign path (`POST /review-session/{id}/sign`) **AVOIDS** the defect by requiring an F5 primary (the F5 slice alone supplies the boxes, so a sales/extract-only session cannot produce a paper); the **per-slice `POST /sign/upload` sales/extract papers still carry it** and are NOT fixed here. Filed as open item #48 in `AGENTASSIST_TECHNICAL_STATE.md`.
> - **DEBT-3 restated:** NO real Xero export has ever been read — the sales fixture is real-FORMAT / SYNTHETIC. The sales sign is **real-mechanism over synthetic data**, NOT real-client-validated and NOT accuracy-validated; the **one-time supervised live capture has NOT been run** (blocked on `ANTHROPIC_API_KEY`). **+7 pytest** (`tests/test_sign_upload_sales.py`) → branch full suite **2781 passed, 1 skipped, 6 xfailed, 2 xpassed** (+7 over base `6742fdc`'s 2774/1/6/2); offline-replay byte-identical; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED in every committed config; T2.11 unmoved; closes NONE of the debts below (XS-4 real-Xero-vocabulary pinning stands).

> **UPDATE — uploads can now ACCUMULATE into an explicit review session (`D-2026-07-23-review-accumulation`, branch `t-review-accumulation`, on base `25a31ed`, UNMERGED; built + suite-verified ≠ validated).**
> Uploads previously REPLACED each other. A NEW append-only `agent/review_store.py` (stdlib-only, zero `anthropic`/SDK; the `agent/decision_store.py` precedent — monkeypatchable `_REVIEWS_ROOT`, `^[a-z0-9_]+$` guard, gitignored `reviews/<review_id>/slices.jsonl` whose runtime-absence is CI-load-bearing) plus `POST/GET /review-session` let several exports ATTACH to ONE session. A `review_id: str = Form(None)` field on `POST /review/upload` is **REQUEST-ONLY**: absent → the upload response is **byte-identical** to today (no new response key anywhere — `test_xero_queue_contract.py:89` untouched); malformed → 422; unknown → 404; valid → the upload's already-serialized queue/coverage rows append as a slice.
> - **WHAT ACCUMULATES:** each upload's `{source_kind, sha256, client_id` (provenance only)`, period` (F5 when cheaply known)`, queue` (incl. dossier fields)`, coverage_status, branch extras}`. `GET /review-session/{id}` returns the **R6 grouped-slices merged view** — active slices (two sightings from two export types stay TWO rows, never a flattened queue), a VISIBLE `superseded` list with `superseded_at` (R2 — a reviewer never wonders why a finding vanished), and a `coverage_matrix` with **PER-SOURCE attribution** per check (`NO_GST_REG` unavailable-from-F5 + unavailable-from-sales as separate entries). **R2:** same `(source_kind, sha256)` → idempotent skip; different `sha256` same `source_kind` → supersede-in-view, BOTH lines retained on disk (append-only).
> - **KEYING:** a review keys on a **server-generated `review_id`** (`r_<hex>`), NEVER on `client_id` (that would MERGE different clients' uploads — worse than #45). The per-slice `client_id` is PROVENANCE ONLY — the structural hook for the eventual #45 fix.
> - **TWO HONEST LIMITATIONS (stated plainly, not footnotes):** **(a) R3 — ACCUMULATE-AND-VIEW ONLY.** The signed working paper stays **PER-SLICE**: a reviewer who accumulates four exports still signs ONE paper PER export — nothing in `engine/`/`report/`/`audit_bundle/` merges `compile_output`s; an accumulated sign is a render-architecture follow-up. *[UPDATE, `D-2026-07-23-accumulated-sign`, branch `t-accumulated-sign`, UNMERGED, built + suite-verified ≠ validated: the accumulated (one-paper-for-the-whole-review) sign now EXISTS — `POST /review-session/{id}/sign`. It does NOT merge `compile_output`s: the accumulated paper's boxes/structure/period come from the DESIGNATED PRIMARY (active F5) slice ALONE, re-executed over its RETAINED bytes (byte-identical to a solo `/sign/upload`, test-pinned), while every non-primary slice contributes FINDINGS ONLY from the #136 STORED rows with visible provenance. F5-required (a sales/extract-only session refuses). The per-slice papers remain available. See `AGENTASSIST_TECHNICAL_STATE.md` §Accumulated-sign.]* **(b) R5 — cross-slice decisions do NOT carry.** Within one review, adjudicating a finding on the F5 slice does NOT demote the same-fingerprint finding on the sales slice: the slices load decisions from DIFFERENT config stores (`decisions/xero_demo/` vs `decisions/xero_sales_demo/`). A genuine UX surprise; **#45 territory** — its stateful-uploads precondition has now ARRIVED, but the tenant-identity work REMAINS (#45 neither solved nor worsened).
> - **DEBT-3 restated:** NO real Xero export has ever been read — every fixture is real-FORMAT / SYNTHETIC. Accumulation is **real-mechanism over synthetic data**, NOT real-client-validated and NOT accuracy-validated. **+8 pytest** (`tests/test_review_accumulation.py`, T1–T8, failing-first 8 red → 8 green; T8 pins the cross-slice non-carry structurally) → branch full suite **2789 passed, 1 skipped, 6 xfailed, 2 xpassed** (+8 over base `25a31ed`'s 2781/1/6/2); offline-replay byte-identical; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; T2.11 unmoved; closes NONE of the debts below. **Frontend UNTOUCHED (Collin's lane):** create-session call, `form.append("review_id")` when a session is active, merged-view fetch + `ReviewSessionPayload` type, and an optional session-list selector are enumerated for him.

> **UPDATE — fingerprint key WIDENED to v1 (`D-2026-07-24-fingerprint-v1`, branch `t-fingerprint-v1`, HEAD `89b80a5` off base `e13987d`, UNMERGED; BUILT + hermetically tested + layer-proven ≠ accuracy-validated ≠ live-validated).**
> The `serialize_xero_queue` **fingerprint-always** enabler (B3a-2 above) stamps every DETECT row's deterministic fingerprint; that fingerprint's KEY now widens from v0 `(error_code, counterparty)` to **v1 `(error_code, counterparty, doc_num)`** in `agent/decision_ledger.py`. This CLOSES the v0 **collision property**: two DIFFERENT Xero findings sharing a counterparty + error code (e.g. `BILL-3002` and `BILL-3999` under OldRate Supplies Pte Ltd, which both hashed to `sha256:265e9b4e…`) no longer collapse onto ONE fingerprint. `doc_num` canonicalises as **`str(doc_num).strip()` — NO casefold, NO `int()` coercion** (Xero string doc_nums like `"INV-2003"` / `"BILL-3002"` preserved as-is; absent → the named `_ABSENT_DOC_NUM` empty string, never `"None"`); counterparty normalisation now ALSO collapses internal whitespace runs.
> - **The proof is AT THE FINGERPRINT LAYER, honestly scoped.** The collision is proven at the fingerprint layer; the engine-path double-proof was **honestly skipped**; the **frequency** claim (how often real returns actually collide) **stays unproven until a real client export exists**. This is NEVER "proven end-to-end on engine output". **DEBT-3 restated:** NO real Xero export has ever been read.
> - **v0 stored decisions are INERT BY CONSTRUCTION, not migrated.** A `fingerprint_version` field (`"v1"`) is hashed into `entry_hash` with ABSENCE-AWARE hashing, so historical v0 `entry_hash` literals are UNCHANGED and a stored v0 entry (2-key hash) can never equal a v1 recompute (3-key) — it simply never matches (NOT a version filter). Non-application is surfaced AS DATA — `count_superseded_entries()` + an additive `superseded_decisions` `{client_id: count}` key on `GET /review-session/{id}`. **This is exactly the key-widening event open item #46 warned of:** a migration that RE-APPLIES stored v0 decisions under v1 is still NOT built (#46 realised, still open).
> - **#45 (multi-tenant ship-blocker) UNCHANGED — unsoftened.** The widening adds **NO client component** to the key, so two REAL tenants routed through one config store (`decisions/xero_demo/` etc.) still CROSS-APPLY each other's dispositions. #45 remains a ship-blocker.
> - **Tamper-evidence narrowed on record.** The decision-ledger hash chain is tamper-evident against **in-place edits and genesis drops, NOT against tail truncation** (a truncated chain is a valid shorter chain). Two open items are filed by this build: (a) the `verify()` tail-truncation gap; (b) the two-verb/one-disposition collapse (UI Accept/Reject both persist today's single-disposition vocabulary).
> - **This build RENDERS NOTHING** — no `report/` change, no UI change, disposition vocabulary UNCHANGED; the panel's disabled-controls / visible-reason behaviour is unaffected. Terry's hand-amendment package (6 test files) + a Terry-directed `tests/fixtures/demo-artifacts/` regen reseed the doc-592 demote seed under v1 (fingerprint `sha256:3d87ffc0…` → `sha256:46b42541…`, now carrying `fingerprint_version "v1"`). **+11 pytest** (`tests/test_fingerprint_v1.py`) **+1 net** in `tests/test_t55_decision_ledger.py` → branch full suite **2809 passed, 1 skipped, 6 xfailed, 2 xpassed** (+12 net over base `e13987d`'s 2797/1/6/2); offline-replay byte-identical; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; T2.11 unmoved; closes NONE of the debts below.

> **UPDATE — signed working papers now RENDER stored reviewer adjudications (`D-2026-07-24-decision-render`, branch `t-decision-render`, off base `6a506a3`, commits `21c6976` + `be787ad`, UNMERGED; built + hermetically tested ≠ accuracy-validated ≠ live-validated).**
> A signed working paper previously **never rendered decision/demotion state** — a reviewer who declined five findings signed a paper still listing all five unchanged. This build renders the reviewer's stored adjudications onto the paper **on the full-arg render paths**, and states VERBATIM which paths stay silent. A decision view is built in `api/viewmodel.build_adjudication_view` and passed **AS DATA** into `build_report` (the `accumulated=` bounded-seam precedent — the api layer composes, `report/` only renders), via a new `AdjudicationSection` / `build_adjudication_section` (`report/sections.py`), an `_adjudications` renderer (`report/render.py`), `ReportModel.adjudications`, and a `build_report(adjudications=…)` kwarg.
> - **PATH SCOPE (do NOT write "the paper now renders decisions" unqualified):** `POST /sign/upload` **AND** `POST /review-session/{id}/sign` render adjudications; the frozen **`POST /sign` does NOT** — its papers stay **SILENT** (no seam in the reduced-arg `ui/sign.py` builder; pinned by test).
> - **WHAT RENDERS:** the **full ordered disposition history per finding** (`disposition`, `reviewer`, `timestamp`, `period` — structured `AdjudicationEntry` fields, append-ordered, last = most recent), **DISPOSITIONS only** (`ACCEPTED` / `REJECTED` / `KNOWN_ACCEPTED` as set-aside) — **never the UI verb**: "Not an issue" and "Mark known" both store `KNOWN_ACCEPTED` and are **not distinguishable** from the structured fields (the verb lives only in the never-rendered free-text note; the two-verb collapse stays an open item).
> - **SUPERSEDED decisions = an AGGREGATE count line only** (rendered when > 0): *"N stored adjudication(s) for this client do not apply to this review because they were recorded under a superseded finding-identity version."* Per-finding attribution is **STRUCTURALLY IMPOSSIBLE** (a v0 2-key hash can never equal a v1 3-key recompute; inert by construction — see the fingerprint-v1 UPDATE above) and is not attempted.
> - **NON-FILTERING:** the section is **ADDITIVE** — a `REJECTED` (declined) finding **STILL renders**; **demote is not drop**; the paper never contradicts the sealed, UNFILTERED `detect.issues`.
> - **`/sign/upload` cost (honest):** a NON-EMPTY decision store costs one EXTRA pure deterministic chain run (`persist_artifacts=False`) before the persisting run — the per-finding join needs the run's findings, born inside `review()`; an EMPTY store keeps the single-run flow and a silent paper. Bounded engine seam: `ReviewInputs.adjudications` (defaulted, ZERO-logic pass-through; `None` → byte-identical); the T5.8 `ReviewInputs`-contract tripwire was **re-pinned by Terry's own hand** (commit `be787ad`, separation of duties). The section is **UNGATED** (`show` derives from content only, never `show_ai_candidates`); **response contracts on both endpoints UNCHANGED; `frontend/` UNTOUCHED**.
> - **#45 (multi-tenant ship-blocker) UNCHANGED — now USER-FACING.** Fingerprints carry NO client component, so two REAL tenants routed through one client config would render **tenant A's adjudication on tenant B's signed paper** — rendering makes the existing hazard VISIBLE on a distributable artefact. **#45 remains a ship-blocker.**
> - **FILED (not fixed):** a same-second signed-PDF overwrite — `engine/review.py`'s `pdf_path` is seconds-resolution (`%Y%m%d-%H%M%S`, derived from `fetched_at`), so two persist runs in the same second overwrite ONE PDF (the SAME collision family PR #132 fixed for the seal dir and `ui/sign.py`); surfaced live by this build's T5; NOT fixed here.
> - **NEW GUARD:** `tests/test_leaf_import_purity.py` (AST scan incl. lazy imports) pins `report/` imports none of `agent`/`reasoning`/`documents`/`anthropic` and `engine/` imports neither `agent` nor `anthropic` — closing the Gate-a blind spot (the CI grep covers `orchestrator/` only). **+13 pytest** (`tests/test_decision_render.py`) **+2** (`tests/test_leaf_import_purity.py`) → branch full suite **2824 passed, 1 skipped, 6 xfailed, 2 xpassed** (+15 over base `6a506a3`'s 2809/1/6/2); offline-replay byte-identical; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; T2.11 unmoved; closes NONE of the debts below. It renders STORED HUMAN decisions and asserts **nothing about correctness** — NOT real-client-validated, NOT accuracy-validated.

> **UPDATE — the Xero F5 upload response now carries the recomputed boxes WITH their honest basis label (`D-2026-07-26-xero-f5-basis`, branch `t-xero-f5-basis`, off base `7cc490e`, UNMERGED; BUILT + hermetically tested ≠ accuracy-validated ≠ live-validated; renders NO UI — Collin's lane).**
> The `xero_f5_upload` response (`POST /review/upload`) gains **ONE top-level key** — `recomputed_client_coded_f5_boxes` — so the response is now **6 keys, not 5** (the prior `source_kind`/`validation_status`/`disclaimer`/`coverage_status`/**`queue`** plus the new key). *[CORRECTED at `D-2026-07-27-dup-window` docs-sync (H2): this line originally said `findings` — the stale PR-B-era shape; `queue` superseded `findings` at BUILD 2/A1 and the locked queue-contract pin asserts `"findings" not in body`. Run-verified.]* `XERO_UPLOAD_KEYS` at `api/app.py:151-153` is **documentation-only** — the handlers return dict literals; the REAL contract is the exact-set test pins, now amended to 6 keys by Terry's hand across **seven** test files. The new key's value is `{boxes` (all 8, from the upload's OWN just-computed `compile_output.calculate.boxes`)`, basis` (the REQUIRED constant **`XERO_F5_BOX_BASIS` — not a builder parameter, unforgeable**)`, period {start, end}, source_file {filename, sha256` of the uploaded bytes`}, currency` (conditional)`}`.
> - **WHY THE KEY IS NAMED THIS WAY (R1 basis statement, verbatim):** on the Xero F5 path the chain RECOMPUTES the boxes from transactions the client's own export already grouped by their own tax-code assignments. The arithmetic is ours; the classification is theirs. Agreement with the filed return is TAUTOLOGICAL, not confirmatory (chain.py says this in-code). Neither the bare word "computed" (implies independent derivation, as on SAP) nor "declared" (implies we read the figures off the return) describes these boxes. **R2 failure asymmetry:** the key name deliberately does **NOT** contain `f5_summary`, so old code hunting an `f5_summary`-shaped key on an upload response finds NOTHING rather than something SAP-styled — failing-to-render is the honest failure.
> - **THE WRONG-SOURCE HAZARD this key defuses (verbatim):** `viewmodel.f5_summary(artifacts)` reads the FROZEN SBODEMOSG artifacts — right name, right shape, WRONG DATA for any upload path; now test-pinned (the response boxes must differ from the frozen boxes and equal the upload's own).
> - **#48 NOT WIDENED (verbatim):** sales and extract responses deliberately carry NO boxes — the all-8-boxes-with-0.00 one-sided artefact stays confined to signed papers; the gate is structural (the builder is called only inside the F5 handler), not a flag.
> - **CURRENCY — OMIT-NEVER-DEFAULT (verbatim) + an UNVERIFIED, NOT-ENCODED open question:** currency is read from the export's own "Source currency" column (the reader's RAW DocCurrency); emitted only when the export uniformly states exactly one; OMITTED entirely when unstated or mixed; never defaulted to "SGD". PLUS the open question, recorded as UNVERIFIED and NOT ENCODED: the F5 return is filed in SGD regardless of an org's base currency, so a non-SGD F5 currency may itself be finding-worthy — verify against the IRAS exchange-rates guide before anyone encodes it; it must not be model-inferred (NO-TAX-SEMANTICS). **doc_currency POISONING (verbatim):** `orchestrator/steps.py:130` defaults doc_currency to "SGD" at fetch-normalisation, so `compile_output`'s copy CANNOT be used for an honest currency statement — the reader's raw DocCurrency column is the only honest source (recorded because the next person to want a currency will reach for `compile_output` first).
> - **RULING M2 IS SUPERSEDED (recorded so it cannot be silently re-litigated):** the retired rule, verbatim — *"both Xero source_kinds share one disclaimer text"* — is REPLACED by: the F5 entry carries basis-correct wording, DISTINCT from sales, because the shared "Computed from your uploaded Xero export" claim becomes actively FALSE the moment boxes ship on the F5 response, while staying TRUE for sales. Why the record matters: a superseded ruling with no record of its supersession can be silently re-litigated. The in-file record lives at `tests/test_source_provenance.py` (the inverted pin). The `xero_f5_upload` disclaimer is corrected accordingly; the sales/extract disclaimers are **byte-identical** (source-aware selection, not a blanket rewrite).
> - **DEBT-3 restated:** NO real Xero export has ever been read — every fixture is real-FORMAT / SYNTHETIC; the boxes are TAUTOLOGICALLY in agreement with the filed return (their classification is the client's own, the arithmetic is ours), so this labels the basis but proves NO accuracy. **+11 pytest** (`tests/test_xero_f5_basis.py`) → branch full suite **2845 passed, 1 skipped, 6 xfailed, 2 xpassed** (+11 over base `7cc490e`'s 2834/1/6/2); offline-replay byte-identical; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; T2.11 unmoved; closes NONE of the debts below. **Frontend UNTOUCHED (Collin's lane):** the wiring that would display the boxes with their basis label is enumerated for him in the PR body; this build renders NO UI.

> **UPDATE — the SALES signed paper is now CAPABILITY-AWARE: #48 RESOLVED for sales (`D-2026-07-26-box-capability`, branch `t-box-capability`, off base `97e8158`, UNMERGED; BUILT + hermetically tested ≠ accuracy-validated ≠ live-validated).**
> Readers declare which SIDES their FORMAT can populate (`populatable_sides()` beside `coverage_status()`); `orchestrator.chain` projects sides → per-box status via `F5_BOX_MAPPING`'s OWN `side` field (no authored side→box table) into `compile_output["box_capability"]`; the paper renders a structurally-unknowable box as **"Not available from this source"** (no figure, summary AND breakdown), and Box 8 renders its figure marked *"Derived from an incomplete input: Box 7 — Input tax and refunds claimed is not available from this source."* — naming the term, claiming NO bound and NO direction. All 8 rows still render (suppression is the DEAD shape per `D-2026-07-24-decision-render`). A PDF-text pin now exists (`tests/test_sales_paper_box_pin.py` — `test_sign_upload_sales.py` had NO such pin, which is how a fabricated statutory figure passed CI; Terry F2 ruled the pin stays in the new file).
> - **THE THREE-WAY ARTEFACT SPLIT (deliberate — do not "fix" one into agreement with another):** on a one-sided source the JSON response carries NO boxes (`D-2026-07-26-xero-f5-basis` R3), the sealed compile-output carries the raw computed 0.00, and the signed paper renders "Not available from this source". Three audiences — working screen, machine record, signed artefact. The paper GLOSSES the seal; it does not contradict it (the sealed `box_capability` justifies the marker in the same bundle).
> - **CAPABILITY, NOT EMPTINESS:** a legitimately one-sided F5 export (no purchases in the period) renders Box 5/7 as genuine **0.00 figures**, never markers (pinned by a constructed no-purchase F5 workbook). The F5 and SAP papers are text-identical to before under BOTH pdfplumber and pdfminer.
> - **THE "available" DEFAULT:** a reader declaring no sides renders every box available — correct today only because both non-declaring readers (live SAP, frozen replay) are two-sided; now pinned structurally (F3 named-allowlist test) so a future one-sided reader cannot skip the declaration silently.
> - **EXTRACT — NEW OPEN ITEM (provisional #49), priority ABOVE #48's remaining half; DO NOT DEMO THE EXTRACT BRANCH:** the extract engine path understates BOTH sides via unmapped SO/SI (measured: extract Box 1 = 0.00 vs the frozen oracle's 369,589.97 over the SAME data; Box 5 = 11,400.00 vs 191,077.76) — cause: the SAP-default `{"SO": "SR", "SI": "TX"}` mapping applies only when `source_system == "sap_b1"` (`config/loader.py:216-218`) and `extract_demo.yaml` declares no SO/SI mapping. FILED AND UNFIXED by this build. #48 itself: **RESOLVED for sales, NOT resolved for extract** (no extract sign exists on master).
> - **+20 pytest** (`tests/test_box_capability.py` 16, `tests/test_sales_paper_box_pin.py` 4) → branch full suite **2865 passed, 1 skipped, 6 xfailed, 2 xpassed** (+20 over base `97e8158`'s 2845/1/6/2); box-isolation runtime-pinned via canonical_json; offline-replay byte-identical; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; T2.11 unmoved; closes NONE of the debts below (XS-4 real-Xero-vocabulary pinning stands; the capability declaration is a FORMAT claim, never validated against IRAS).

> **UPDATE — the DUP_WINDOW check now RENDERS on the signed xero_demo paper (`D-2026-07-27-dup-window`, branch `t-dup-window`, off base `1a13685`, UNMERGED; BUILT + hermetically tested ≠ accuracy-validated).**
> `xero_demo.yaml` declares `dup_window_enabled: true` + `dup_window_days: 7` and the working paper gains a four-state "Windowed Duplicate-Purchase Review" section beside the same-day review. **The BILL-3004/3005 bait pair now renders** (supplier, both dates, delta, both doc_nums). Paper-only: no queue row, no coverage row, no registry entry, no other config.
> - **THE WINDOW IS FIXTURE-FITTED (G4c):** the committed corpus fires only at window >= 7 — exactly the bait pair's gap — so the demo value is selected BY the fixture. Stated (in the YAML comment AND on the paper), it is a demo parameter; unstated, it would be contamination. The loader still refuses to default one.
> - **THE ZERO-FP MEASUREMENT IS VACUOUS (G7):** zero false positives on every committed clean fixture — but no legitimate recurring-charge (standing-order) fixture exists; that class is **UNTESTED, not absent** (FIXTURE_NOTES also corrects: 3004/3005 is a quotation + tax-invoice double-entry, not a standing order).
> - **NON-ADJUDICABLE (G8):** pair-shaped findings (two doc_nums, no `error_code`, no singular `doc_num`) cannot be fingerprinted under the v1 decision key — panel actions do not apply; the paper says so.
> - **CITE + LABEL (G2):** ASK Step 3D.1.1(d) (the question), never without "non-regulatory tuning parameter, not an IRAS rule" (the method is OURS) — same paragraph, test-pinned. NOT §10.1(d)(i) (invoice identity ≠ supplier+amount+proximity); NOT "—" (IRAS demonstrably asks the question — D51's lesson).
> - **DUP_CLAIM vs DUP_WINDOW:** different predicates, different units, not one check. **DUP_CLAIM has still NEVER fired on any reader** (vendor-reference unpopulated everywhere — DEBT-6 unchanged).
> - **+18 pytest** → branch **2883 passed, 1 skipped, 6 xfailed, 2 xpassed**; frozen replay oracle byte-identical, NO re-freeze; six-key F5 response byte-identical (run-proven); SAP/no-position papers text-identical under both extraction libraries; locked `test_document_dup_section.py` passes UNAMENDED; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; T2.11 unmoved; closes NONE of the debts below.

> **UPDATE — the Xero readers' coverage POPULATION is now OBSERVED, not asserted by fiat (`D-2026-07-27-xero-coverage-derived`, branch `t-xero-coverage-derived`, commit `fedf19d` off base `dff24dd` (the PR #153 merge), UNMERGED; **PR-1 of 2**; BUILT + hermetically tested ≠ accuracy-validated; MOVES NO VALIDATION RUNG).**
> Both Xero readers gain `_observed_populated_keys()` and compute `populated` from the loaded documents using `ExtractCoverage`'s exact cell predicate. **Nothing a reviewer reads changes** — rendered papers are text-identical pre-vs-post on both Xero paths under BOTH pdfplumber and pdfminer (run-proven). Scope: `feeders/` + `tests/` only.
> - **THE BY-FIAT HAZARD (what was removed):** both readers computed `fields = {key: (key in _COVERED_FIELDS) ...}` then `populated = dict(fields)` — **"present implies populated", asserted by fiat, never observed** — while the extract reader in the same family computes population from the actual data (`_compute_populated_columns`). A present-but-all-empty column read as populated, which is the distinction that keeps a silently-partial check from reading as full.
> - **THIS IS A REFACTOR, NOT A DEFECT FIX (the measurement gate — do NOT cite this build as a bug found and fixed):** before implementation, a gate compared the by-fiat populated map against a genuinely-observed one on BOTH committed Xero fixtures: **the two agree on EVERY field, and all 11 coverage rows are byte-identical both ways on both readers.** The fiat has been telling the truth ON THE COMMITTED FIXTURES. Independently re-verified by the invariant-auditor (zero differences in the full populated dict).
> - **NO_GST_REG IS STILL UNAVAILABLE ON XERO — NOT a capability change:** `fields` (header/format presence) stays constant-driven because presence is a FORMAT fact; only `populated` became instance-observed. `FederalTaxID` stays outside the covered set, so the NO_GST_REG row stays **"unavailable"** with its existing reason **byte-identical**. **NO_GST_REG still cannot run on Xero and this build does not make it run.**
> - **PR-1 OF 2:** PR-2 (the supplier-master surface) is gated on Terry's rulings **D-3 through D-8** — join key, coverage-row correction, dark-check pins, claimability text, fingerprint stability, Contacts shape.
> - **UNPINNED, run-proven (auditor caveat, PR-2):** a Xero export parsing to **ZERO documents** now reports every covered field unpopulated, flipping **E1–E4 to degraded** — correct semantics (parity with the extract reader over zero rows) but unpinned; **a genuinely-zero-period upload would show four new degraded rows.** Also unguarded: the walked field-name tuples are duplicated literals with no drift guard vs `_COVERED_FIELDS` (drift is fail-safe toward degrade, but silent).
> - **NEW GUARD:** a T6 `feeders/` leaf-purity AST sweep (auto-discovering, incl. lazy imports of `anthropic`/`agent`/`engine`/`orchestrator`/`reasoning`/`documents`) closes the auditor's Inv-7 gap — `feeders/` purity was **docstring-only** before.
> - **+9 test items** (7 tests in `tests/test_xero_coverage_derived.py`; T3/T4 parametrized over both readers) → branch **2892 passed, 1 skipped, 6 xfailed, 2 xpassed** (+9 over base `dff24dd`'s 2883/1/6/2); offline-replay oracle byte-identical, NO re-freeze; hand-amendment package **EMPTY** (25 locked pin files, 217 passed, unamended); import scans clean; flake8 zero; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; T2.11 unmoved; **closes NONE of the debts below** (NO real Xero export has ever been read — DEBT-3 stands).

> **UPDATE — the Xero upload surface now wears the SAP shell chrome + an opt-in source-tag guard (branch `t-xero-shell-parity`, rebased onto `origin/master 6342ab1`, UNMERGED; FRONTEND-ONLY; built + hermetically tested (vitest) ≠ demo-validated ≠ accuracy-validated).**
> A FRONTEND-ONLY build (two commits, ZERO `.py` touched). The Xero upload surface now shares the SAP shell chrome — shared **TopBar** (brand + UNVALIDATED badge + reviewer pill) and **Sidebar** (tallies off the upload findings); TopBar's three view-tabs are **OPTIONAL and OMITTED** on the Xero surface (a single non-tab-gated flow — no dead affordances); the bare `<h1>` is removed and the single reviewer-of-record input relocated into the shell; a **branch-aware scripted-mode banner** carries Xero copy, never the SAP prose. **SAP-only surfaces (Command bar / Audit trail / Filters) render as present-but-DISABLED static placeholders with honest reasons — NEVER the live components — so the Xero page fires NO SAP fetch** (source-isolation preserved). A new opt-in **source-tag guard** (`frontend/src/lib/sourceGuard.tsx`) lets the shared review components (`ReviewScreen`/`Queue`/`FindingDetail`) WITHHOLD data and render an honest `role="alert"` "data source mismatch" state on a source-family mismatch (or absent/unrecognised `sourceKind`) — **defence-in-depth BEHIND Root's still-intact mutually-exclusive mount separation** (NOT dismantled), with **no response-key / contract change**.
> - **PENDING frontend gap (routed to Terry — do NOT read as done): the upload F5 box strip is NOT built.** `recomputed_client_coded_f5_boxes` EXISTS on the backend (PR #151 — `api/viewmodel.py` `build_recomputed_client_coded_f5_boxes`, emitted on the `xero_f5_upload` branch), but the FRONTEND does NOT consume it: `frontend/src/api.ts` `UploadCoverageResponse` carries NO box key, so no upload F5 box strip renders. NOT stubbed, NOT claimed — a PENDING frontend gap.
> - **Test counts:** frontend **vitest 25 files / 84 tests, all green** (+2 files / +15 tests: `SourceTagGuard.test.tsx` 8, `XeroShellParity.test.tsx` 7). **pytest UNCHANGED — 2892 passed, 1 skipped, 6 xfailed, 2 xpassed** (the rebased base; zero `.py` touched); vitest is NOT the merge gate (CI is pytest-only). Moves NO rung toward T2.11; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; offline-replay byte-identical (nothing on this path reaches it); closes NONE of the debts below; NO real Xero export has ever been read (real-FORMAT / SYNTHETIC only, DEBT-3).

> **UPDATE — MERGED as PR #155 (master `0d71a9b`), and a post-merge audit found a REGRESSION in it, now fixed on branch `t-xero-sign-gate-fix` (UNMERGED; FRONTEND-ONLY; built + hermetically tested ≠ demo-validated ≠ accuracy-validated).**
> The shell-parity build added a SECOND sign entry point — the shared **TopBar reviewer pill** — and
> wired it **unconditionally**, bypassing the `canSign` gate the in-panel path honours. Sign is
> **F5-only** (`POST /sign/upload` 422s any other format). Because `SignModal`'s render gate checks
> the uploaded FILE and never the `source_kind`, the ungated pill (a) **no-oped pre-upload** — a
> silent dead control — and (b) **opened the sign modal after an `extract_review` /
> `xero_sales_upload`**, offering sign-off for a format the backend refuses. The suite stayed green
> because the test pinning this queries `/Sign working paper/i`, while the pill is named
> `reviewerName || "Sign in"` — **the rule was enforced at one of two entry points, and the test
> pinning it did not cover the new one.**
> - **Fix:** `onOpenSign` is now an OPTIONAL `TopBar` prop (the same pattern that build used for
>   `view`/`setView`); the pill degrades to a **non-interactive identity chip** when omitted, and
>   `XeroUploadPanel` supplies it only when `canSign`. The **SAP surface is unchanged** and keeps its
>   live pill. A `TopBar` comment overstating the SAP-side source-tag guard was also corrected — that
>   guard hardcodes BOTH sides on the SAP mount, so it is **tautological and can never trip** there;
>   it does real work only on the Xero mount, where the tag is payload-derived.
> - **Test counts:** frontend **vitest 26 files / 90 tests, all green** (+1 file / +6 tests:
>   `XeroSignGate.test.tsx`), written failing-first — 4 of 6 RED before the fix. **pytest UNCHANGED**
>   (zero `.py` touched); vitest is NOT the merge gate (CI is pytest-only). Moves NO rung toward
>   T2.11; `validation_status="unvalidated"` + `show_ai_candidates=False` UNCHANGED; closes NONE of
>   the debts below. **The upload F5 box strip is still NOT built** (unchanged by this branch — the
>   PENDING gap above stands).

Companion files:
- Reader: `feeders/xero_f5_reader.py` (PR-A — real-FORMAT, SYNTHETIC-data, UNWIRED)
- Tests: `tests/test_xero_f5_reader.py` (PR-A — 8 tests over the fixture)
- Config: `config/clients/xero_demo.yaml` (PROPOSED/DEMO, deferred citations)
- Fixture: `tests/fixtures/xero-f5-export/AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx`
- Inbound sales reader: `feeders/xero_sales_reader.py` (`XeroSalesInvoiceChainReader` +
  `is_xero_sales_invoice_workbook`; real-FORMAT over SYNTHETIC data, engine-wired, UNMERGED)
- Sales config: `config/clients/xero_sales_demo.yaml` (Terry-authored IRAS Annex E — 19 rows
  loaded, 13 PARKED as comments; `out_of_scope_codes` ×4)
- Sales tests: `tests/test_xero_sales_feeder.py` (10), `tests/test_xero_sales_upload.py` (1),
  `tests/test_xero_sales_loader_config.py` (2); fixture `tests/fixtures/xero-sales-export/`

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
*Residuals closed (branch `t-debt9-xero-creds`, commit `08d8877`):* two loose ends left after
`8daf757` are now tied off. (1) A **stale in-code docstring** in `api/app.py`'s
`_xero_f5_review_response` still asserted the old "DEBT-9 runtime dependency … deferred (PR-D)"
claim, which had been false since `8daf757`; it now states the `source_system`-gated resolution.
(2) An **endpoint-level creds-absent pin** was added — `tests/test_debt9_endpoint_creds_absent.py`
(**3 tests**): (a) `SAP_USERNAME`/`SAP_PASSWORD` `delenv`'d (overriding the conftest session
stubs), a real Xero F5 fixture POSTed to `/review/upload` → HTTP 200 + the locked 5-key
`xero_f5_upload` shape + `QUEUE_ITEM_KEYS` queue; (b) SAP-direction pin — `sbodemosg` load still
raises `ConfigError` naming the missing vars (the loud SAP guard is NOT weakened); (c) `xero_demo`
loads with empty SAP fields. **Honest status:** these are regression **PINS of behaviour already
on `master`** since `8daf757` — they **passed immediately** (built + pinned ≠ accuracy-validated;
T2.11 unmoved). Branch full suite **2673 passed, 1 skipped** (6 xfailed, 2 xpassed); a single
**pre-existing** `tests/test_motorcar_statute_source.py` manifest-sha256 failure reproduces
identically on clean `master` `0f56f5c` (from PR #123) and is unrelated to this branch — flagged
to Terry separately.

### DEBT-10 — `source_system` docstring understates its effect — RESOLVED (commit `8daf757`)
`config/loader.py:114-116` (historically) documented `source_system` as "logging/display
only", but it is functionally load-bearing via `effective_tax_code_mappings` (`:195-197`),
where any value other than `"sap_b1"` suppresses the SAP SO/SI defaults.
*RESOLVED (`8daf757`):* the docstring is corrected and `source_system` is now formally
LOAD-BEARING — it drives `effective_tax_code_mappings` AND (as of DEBT-9) gates the `sap_b1`
block/creds requirement. This debt is now CLOSED.

---

## Xero-SALES inbound debt items (branch `t-xero-sales-feeder`, UNMERGED)

These are DISTINCT from the F5 DEBT-1..10 items above — the inbound sales-invoice feeder
(`feeders/xero_sales_reader.py` + `config/clients/xero_sales_demo.yaml`) carries its own debt.
Cross-ref `exploration-notes/operational-backlog.md` item #18 and
`AGENTASSIST_TECHNICAL_STATE.md` §T-xero-sales-feeder.

### XS-1 — 13 Terry-mapped Xero sales TaxTypes PARKED pending T2.21 vocabulary resumption
Terry ruled **Option 3**: ship the **19** accepted `tax_code_mappings` rows now (canonical VatGroup
target already in `config/loader.py` `_STANDARD_VAT_GROUPS`), and **PARK 13** rows whose target is
NOT yet a canonical code — TXCA, SRCA-S, IM-N33, IM-ESS, IM-RE, SROVR-LVG, SRLVG, TX-ESS, SROVR-RS,
TXRC-N33, TXRC-ESS, TXRC-RE, TXRC-TS — pending **T2.21** (adding the codes to `_STANDARD_VAT_GROUPS`
+ their F5 box routing; Terry's timeline). The parked 13 live as **COMMENTS** in
`config/clients/xero_sales_demo.yaml` (never loaded); a Xero sales line carrying one **fails LOUD**
(`ValueError`) at the parse boundary until T2.21 resumes — the documented, accepted behaviour.
**Sales-side exposure:** SRCA-S, SROVR-LVG, SRLVG, SROVR-RS lines fail loud until then. **Owner:
Terry.** This is a PARK, not a bug — the mapping is Terry-authored (IRAS Annex E), NOT DEBT-1's
deferral.

### XS-2 — TX-ESS possible rename of the existing TX-E33 (Terry open question)
`"Partially Exempt Traders Regulation 33 Exempt": TX-ESS` (parked, XS-1) is a **POSSIBLE RENAME** of
the already-canonical `TX-E33`. Unresolved — recorded as Terry's open question, to be reconciled
when T2.21 authors the parked codes. Not resolved here.

### XS-3 — E-check coverage-gap finding (report-only, for Terry)
The face-rate-0 code families — reverse-charge `TXRC-*` and import `IM*`/`IGDS`/`ME` — sit **OUTSIDE
every E-check's `vg` set** (`_STANDARD_RATE_SALES={SR,DS}`, E4 only `{SR,TX}`). Consequence on a
`TaxAmount=0` line: they produce **NO false positives**, but they also get **NO E-check coverage at
all** — **uncovered, NOT validated-and-passed**. This is a report-only finding surfaced for Terry, not
a code change; do not read absence-of-flag on these families as a pass. **Owner: Terry.**

### XS-4 — real-Xero vocabulary / column-header pinning still PENDING
The feeder parses the real Xero sales-invoice EXPORT FORMAT over SYNTHETIC content only. The exact
real column-header set / TaxType vocabulary have **NOT** been pinned against a genuine client export
(same GTM gate as the inbound F5 DEBT-3). Until then: demo only, real-Xero-FORMAT over SYNTHETIC
data, NOT real-client-export-validated and NOT accuracy-validated.

## Audit view on the Xero upload surface (`D-2026-07-28-xero-views`)

The Xero surface's **Audit** view is titled **"Decisions — this session"** and is **empty on
load, always**. That is a limitation, not a design preference:

- **No decision from a prior session can ever be listed.** There is no read endpoint for the
  decision store. Decisions ARE saved (append-only, hash-chained) — they simply cannot be read
  back. They resurface only as the per-finding "previously adjudicated" annotation after the same
  workbook is re-uploaded.
- **There is no "When" column and no "Reviewer" column.** `POST /decision` returns ten keys and
  neither a timestamp nor a reviewer name. The store records both; the response does not return
  them. A browser clock would be the page's guess at when something happened, not the ledger's
  record of it.
- **There is no agent justification ledger for an upload.** `GET /audit` returns the SAP agent's
  Tier-1/Tier-2 tool chain; an uploaded export runs no agent, so there is nothing to hash-chain
  but the reviewer's own decisions. The view says this in plain words rather than showing an
  empty SAP table.

Two backend fixes are filed against this: return `timestamp` + `reviewer` from `POST /decision`,
and add `GET /decisions` (`backend-gaps.md` §B1).

## Ledger-reconciliation rows are indistinguishable by their own fields

With the 820 ledger attached, an F5 upload returns two `ledger_recon:*` rows. **Of their 24
fields exactly three differ** (`finding_id`, `description`, `recommendation`) — and of the six
fields the review queue renders, **none**. The UI distinguishes them by rendering `finding_id`'s
terminal segment (`output` / `input`); it deliberately does NOT scrape "Box 6" / "Box 7" out of
the description prose. A backend fix is filed: these rows need a distinguishing display field.

They also carry `fingerprint: null`, so they remain **non-adjudicable** — decision controls render
disabled with the honest per-cause reason (`#46` territory).

## `NO_GST_REG`'s citation is corrected; its recommendation is not (`D-2026-07-28-nogstreg-recite`, ruling D-24)

`agent/registry.py:250` now cites **`GST (General) Regulations [2026 Ed.], reg 11 — Conditions for
claiming input tax`**, replacing `IRAS GST Act s19(1) / Regulation 11 — …`. The dropped half rested on
a document this repo **did not hold at the time** (`knowledge-base/sources.md:64`: GST Act
**ABSENT / UNVERIFIED**); the kept half is held and version-pinned (`sources.md:65`: **CURRENT**,
227 pages, sha256 `d7534d60…`, `[2026 Ed.]`).

> **SUPERSEDED IN PART, same day (2026-07-28).** The rule-author supplied the GST Act —
> `knowledge-base/statute/gst-act-1993-2020ed.pdf`, `[2020 Ed.]`, 319 pages, sha256
> `30bddc8f6303e35045698baefdf0df9f603e23b00d295fa63b60305dee6d145d`, stamp "Informal Consolidation –
> version in force from 8/12/2025" on 319 of 319 pages — and `sources.md:64` is now **CURRENT**.
> **The Act is HELD.** `s19(1)` is **NOT** restored on `NO_GST_REG` and must not be restored
> automatically: D-24 stands as a **substantive** authoring decision, not an evidentiary workaround —
> reg 11 is arguably the more precise authority for *conditions for claiming* input tax, and
> entitlement (s19) and conditions (reg 11) are different things. Restoring it is a fresh rule-author
> decision under NO-TAX-SEMANTICS, never an undo, and would fail loud at the full-string golden pin.

**This changed nothing about detection.** Same documents flagged, same order, same description, same
recommendation. `validation_status` stays `unvalidated`; T2.11 unmoved. The new citation is
**Terry-authored and itself UNVALIDATED** — the constant `iras_basis_caveat` still ships on every
queue item saying exactly that.

**On Xero this is invisible.** `NO_GST_REG` remains **UNAVAILABLE on the Xero upload path** — the
supplier-master surface (`FederalTaxID`) is outside the covered set, per
`D-2026-07-27-xero-coverage-derived`. Verified from a run: `POST /review/upload` over the committed F5
fixture returns `check_ids=['E2','E3','E4']` and **no `NO_GST_REG` row**. The corrected citation
reaches a reviewer only on the SAP/extract route today.

### STILL OPEN — the recommendation reword (D-25) is an ORACLE RE-FREEZE

`mcp-servers/custom/sap_b1_server.py:1514`'s recommendation text is **not** corrected and was
deliberately out of scope. It is embedded **verbatim** in the offline-replay oracle (7 rows), which
`tests/test_t2_12a_offline_replay.py:127` compares **byte-for-byte** against a sha pinned in
`capture-manifest.json`. Rewording it forces a re-freeze plus staleness in `review_result.json`,
`dossiers.json` (including 7 `inputs_hash` values) and both `chain-run-*.json` — all hook-blocked
under `tests/`. **Do not read the `NO_GST_REG` text as fully corrected.**

### KNOWINGLY CREATED DRIFT — `frontend/src/test/fixtures.ts` (owner: Collin, C-8)

`fixtures.ts:59` is a **hand-copy** of the registry citation and now **diverges** from
`agent/registry.py:250`. No test asserts it, so nothing goes red.

Fix it **WITH a binding test** — an unbound copy is how this drift arose — and **batch it with
`fixtures.ts:53-54`, which are ALREADY stale against production today**, independently of this build:

| fixtures.ts | fixture carries | production emits |
|---|---|---|
| `:53` description | `…without a GST registration number.` | `…without a GST registration number — may not be claimable.` (`sap_b1_server.py:1510-1512`) |
| `:54` recommendation | `Obtain a valid tax invoice with the supplier's GST registration number.` | `Obtain a valid tax invoice with the supplier's GST registration number, or reverse the input tax claim.` (`:1514`) |
| `:59` iras_basis | `IRAS GST Act s19(1) / Regulation 11 — …` | `GST (General) Regulations [2026 Ed.], reg 11 — …` (`registry.py:250`) |

**Three divergent strings in one fixture object; two of them pre-existing and undetected.**

### OPEN ITEM, ELEVATED — two independent citation surfaces, nothing reconciles them

1. **Registry → screen:** `agent/registry.py` `iras_basis`, live-resolved via `check_reference`
   (`ui/artifacts.py:316`) into every queue item (`api/viewmodel.py:302`).
2. **Report layer → signed paper:** its own hard-coded prose — `report/sections.py:866`
   (`"… per IRAS s21(3). …"`), `report/constants.py:80`
   (`"expenses disallowed under GST (General) Regulations 26 and 27"`).

**No test checks that the two agree.** This build demonstrates the gap: the registry citation changed
and the rendered paper did not move by a byte (verified under both pdfplumber and pdfminer). Here that
was desired — but structurally **a citation can differ between the screen a reviewer reads and the
document they sign, and nothing fails.** Filed for a ruling; no mechanism proposed.

### THE CITATION PROBLEM IS NOT SOLVED — six remain on the GST Act *(unheld when written; HELD as of the same day)*

Measured from `CHECK_REGISTRY` after this build: `E1` (s21(3)), `E3` (s10), `E4` (bare `"GST Act"`,
no section), `gst_amount_mismatch` (s19), `correct_period` (s20), `total_inconsistency` (s19).

**Six, not three.** `sources.md:64` listed four legs (`s10`, `s19(1)`, `s20`, `s21(3)`); it never
recorded `E4`'s bare cite or the two `s19` cites (distinct from `s19(1)`). That row's list has been
corrected in place. **One of six is corrected.**

**UPDATE, same day — the problem changed shape rather than persisting.** `sources.md:64` is now
**CURRENT** (the Act was supplied: `[2020 Ed.]`, 319 pp, sha256 `30bddc8f…`). **All six citations above
are SUPPORTED** — they rest on a held, version-pinned copy. The remaining gap is narrower and
different: their **wording**. `E4` cites no section at all; the two `s19` cites are unpinned as to
subsection. That is a rule-author authoring question, not an evidentiary one.

## The `NO_GST_REG` recommendation no longer tells a reviewer to alter the books (`D-2026-07-28-nogstreg-reword`, rulings D-25/D-26)

The working paper used to print:

> "Obtain a valid tax invoice with the supplier's GST registration number, **or reverse the input tax
> claim.**"

The second clause is an **instruction to change the client's records**, and it assumes the claim is
already invalid. It now prints:

> "Obtain a valid tax invoice bearing the supplier's GST registration number; whether the conditions
> for claiming input tax are met is for the reviewer to determine."

**Nothing about detection changed.** Same documents flagged, same count, same severity, same
description ("may not be claimable" was already correctly hedged and is untouched). No F5 box moved.
`validation_status` stays `unvalidated`; T2.11 unmoved. The wording is rule-author authored under
NO-TAX-SEMANTICS and echoes the title of GST (General) Regulations reg 11, this check's citation
since D-24.

**On Xero this is invisible** — `NO_GST_REG` remains UNAVAILABLE on the Xero upload path (no
supplier-master surface), per `D-2026-07-27-xero-coverage-derived`. The corrected wording reaches a
reviewer only on the SAP/extract route today.

### The offline-replay oracle was RE-FROZEN

Stated plainly so nobody meets it first in a diff.

```
  OLD  sha256:59fbdbb827dee933b4c79e8557852047d2465d6cb155b00d3d3cb58b92eddc45   31,919 bytes
  NEW  sha256:0225df39c8ea6054d45f72199aa510e970c385587e557e1160407ea744f6cd5f   32,332 bytes
```

Permitted under **D-22** only because the change was proven field by field first: both oracles parsed,
every path walked, **7 differing paths, all 7 the recommendation, 0 added, 0 removed** — no box, no
gate, no manifest field. The re-freeze and every `tests/` artefact are the rule-author's own commits.

**D-27:** `scripts/capture_sbodemosg_extract.py` is a **RE-CAPTURE, not a regenerator, and is
forbidden** as a re-freeze instrument — it is live-SAP and rewrites all eight raw surfaces plus the
manifest. The offline replay shim is the only permitted route; a banner now says so in the script.

**D-28:** every future re-freeze must first regenerate with the change **not** applied and prove
byte-identity against the committed oracle. The oracle is regenerable only through the harness it
exists to verify; that proof is what stops the test checking the harness against itself.

### P4 is complete — both halves

`D-24` corrected the **citation** (merged, PR #161, moved no frozen bytes). `D-25`/`D-26` corrected
the **recommendation** (this build, a full re-freeze). They were deliberately split because their
evidentiary footprints differ; together, the re-freeze would have masked the citation change.

### Open item #50 — why four artefacts could carry dead text indefinitely

`review_result.json`, `dossiers.json` and both `chain-run-*.json` all held the old wording and **no
test failed**: `test_t58_artifact_contract.py:97-118` pins **key sets, not values**. A shape tripwire
cannot see text drift. `dossiers.json` is worse — the recommendation sits inside the evidence dict
that `inputs_hash` is computed over, so seven hashes drift with it, and no test asserts a literal
`inputs_hash`.

`frontend/src/test/fixtures.ts` was the same defect one step worse: `:53` and `:54` were **already
stale against production before this build**, `:59` since D-24. All three corrected here, each with a
comment naming its source at file:line.

**The origin is T1.2 (2026-05-27).** The NR VatGroup error sat in **three of four artefacts — tool
code, reference script and system prompt — and all three agreed with each other.** One unverified
belief copied three times, presenting as corroboration. The knowledge base was the lone outlier, and
the only artefact that had been checked against source.

**Agreement among derived artefacts is not evidence.** The family: T1.2 NR (origin),
`XERO_UPLOAD_KEYS`, the T2.12c hand-built reason copy, the frontend fixtures, `sources.md:64`'s own
incomplete registry-citation list, the four demo artefacts, `run_baseline_tests.py:125`, and the two
citation surfaces (`report/sections.py:866` / `report/constants.py:80` vs the registry). **A copy with
no binding test is not a copy, it is a fork.** Filed for a ruling; no mechanism proposed here.


## D-2026-07-29 — source-document viewer: refuse, never substitute (D-34)

> `GET /document/{doc_ref}` previously resolved ANY reference by its last digit run against the
> SAP fixture corpus: `BILL-3002` → 200 serving `INV-3002.pdf` (sha `98d08a5e…`, Office Essentials
> Pte Ltd, 2024-08-20) as the source document for the Xero E4 finding — while the committed Xero
> document `BILL-3002.pdf` is sha `9107458253…` (OldRate Supplies Pte Ltd, 2026-04-22).
> Wrong-document-with-200 was the one state neither the viewer nor the route could detect. A
> reference is now served only when the full string is the document's own identity (`"3005"` /
> `"INV-3005"`); `BILL-*` / `Q-*` / `#N` refuse with the SAME honest 404 as an absent document.
> **The Xero path still shows NO source documents — it now does so honestly; that is the whole
> change.** Ingestion (an upload slot, a namespace-keyed provider) is T-E: see open item #47's
> INV-INV trap and NEW open item #51 — the committed `source_invoices/source_invoices/` double
> nesting + `<XeroReference>.pdf` naming needs a canonical-layout ruling before T-E reads it.


## D-2026-07-29 — source-document ingestion (T-E(1)): documents arrive; checks still don't run

> Documents can now be uploaded with a Xero export (`documents` multipart list, review_id
> REQUIRED — D-37's honest 422), persist at `reviews/<rid>/documents/<sha256>.pdf` with a
> stem-keyed `document_map.json` (D-36), and serve back via the review-scoped
> `GET /review/{rid}/document/{ref}` (D-42 — separate route, no shared resolver with the
> SAP fixture route; D-34's lesson applied structurally). Caps: 10 MiB/file, 50 MiB/upload,
> 50 files, honest 413s (D-39).
>
> **STILL TRUE: the four document checks (gst_amount_mismatch / correct_period /
> total_inconsistency / reg11_supplier_gst_absent) DO NOT RUN.** Coverage honestly reads
> `unavailable` for all four even when documents are attached, because nothing compares
> the document to the books — that is T-E(2), gated on D-40 (a bool cannot honestly
> describe a 10-documents-for-38-baits partial set). **D-41 pilot preconditions,
> unresolved:** no auth on any route, no rate limit, client documents persisting on disk
> indefinitely — fine on localhost with synthetic data, blocking before a real client's
> documents arrive. C-8 (Collin): frontend must send review_id and use the new route.


## D-2026-07-29 — C-8: the viewer asks the right route (surface selection, not fallback)

> The Xero surface now creates a review session on every upload (D-43), sends attached
> source-document PDFs as repeated `documents` parts (D-44 api.ts, Terry-edited), and the
> DocumentViewer fetches `GET /api/review/{rid}/document/{ref}` — verified end to end in a
> REAL browser: the E4 BILL-3002 finding renders beside the genuine OldRate Supplies
> invoice (9% / 360.00 on the face vs the ledger's 8% / 320.00). With a reviewId a 404 is
> FINAL — no second fetch, no reach into the SAP corpus (D-34 at the client). Without one
> (the SAP surface) the legacy route serves as before. **Still true: the checks do not
> compare that document to the books — T-E(2), which now carries D-45 (the sign path
> cannot see uploaded documents; a T-E(2) paper would omit what the screen shows) and
> D-40 (coverage shape for a partial document set).**
