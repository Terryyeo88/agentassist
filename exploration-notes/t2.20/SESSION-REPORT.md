# T2.20 Session Report

**Branch**: `t2.20-annex-e-vocab-audit`
**Date**: 2026-06-12
**Run status**: COMPLETE — read-only discovery audit; awaiting Collin's review before any PR

---

## Summary

T2.20 is a read-only discovery audit for "Option C" — migrating AgentAssist's
internal VatGroup vocabulary from the current 18-code SAP B1 set to the
35-code IRAS Annex E GST Category Code set (e-Tax Guide *"Adopting GST
InvoiceNow Requirement for GST-Registered Businesses"*, Second Edition,
9 Mar 2026, Annex E). No migration was implemented. The deliverable is:

**`exploration-notes/t2.20/vocabulary-migration-inventory.md`** — 7 sections
(0-6) covering live recon, a load-bearing-reference inventory, a code-by-code
Annex E mapping, T2.18 dependency analysis, test fixture impact, reference
script divergence cost, and a first-pass T2.21 effort estimate.

---

## What was done

1. **Live recon** (SOP step 2): ran `calculate_f5_return`,
   `validate_invoice_tax_codes`, and `detect_gst_errors` (Tools 12/13/14) over
   2024-07-01..2024-07-07 against live `SBODEMOSG`, via direct Python import.
   Confirmed all three tools share **one** core vocabulary structure
   (`F5_BOX_MAPPING` + `_E2_ZERO_RATE_CODES` + `_STANDARD_RATE_SALES` +
   `_classify_line`), plus **one** secondary independent 18-code dict
   (`_vg_category`, used only by Tool 13 for human-readable labels). Live data
   in the recon window contained only `SO` (13 docs) and `SI` (1 doc) —
   vocabulary coverage in this codebase is driven by test fixtures, not by
   live SBODEMOSG data.

2. **Static inventory** (Section 1): found the current 18-code vocabulary is
   carried across **23 numbered references** spanning ≥7 independently
   maintained locations (sap_b1_server.py ×2, run_baseline_tests.py ×3,
   base.md ×3, report/routing.py ×2 (+2 consumers), report/sections.py ×2,
   config/loader.py ×2, config YAML ×1, sg-tax-code-mappings.md ×1,
   orchestrator ×2, audit_bundle ×1). Classified each as
   single-source-of-truth, duplicate-could-drift, audit-not-partner
   reference, documentation, or low-impact consumer.

3. **Annex E mapping** (Section 2, 35 codes): 13 direct carryovers, 2 renames
   (`SO`→`SR`, `SI`→`TX`), **2 name collisions** (`TX-N33`, `TX-RE` — same
   string as current codes but conflicting box-treatment semantics), 18 codes
   with no current equivalent (Customer Accounting, OVR/LVG, reverse-charge
   families, plus `NA`/`NG`/`TXNA`/`TXRC-TS` pending IRAS-text confirmation).
   Also found current code `TX-E33` has no target in the given Annex E list.

4. **T2.18 dependency analysis** (Section 3): T2.18 (PLANNED — MES/IGDS/
   reverse-charge flags + `actively_makes_exempt_supplies` promotion) is
   necessary but not sufficient. Recommends sequencing T2.18 immediately
   before/with the build task, and flags that Customer Accounting (3 codes)
   and OVR/LVG (5 codes) need either an extended T2.18 scope or a
   "manual review" fallback in the build task.

5. **Fixture impact** (Section 4): 7 JSON fixtures + `generate_invoices.py`
   carry hardcoded VatGroup strings (`SI` alone ~265 times across the reg2627
   fixture family). The 18+2 codes needing new/remapped semantics have zero
   existing fixture coverage.

6. **Reference script divergence cost** (Section 5): confirmed the "2x"
   (production + `run_baseline_tests.py`) cost model for the ~4 mirrored
   structures, plus 0.5-1 day of re-verification/reconciliation, consistent
   with the existing 3 documented E4 divergences.

7. **First-pass T2.21 effort estimate** (Section 6): ~9-13.5 days excluding
   T2.18, ~11-17.5 days including it. Recommends a follow-on task (T2.22) for
   the 13 codes needing genuine transaction-level detection (CA/OVR/reverse
   charge) that no client-level config flag can resolve.

---

## New findings surfaced (flagged, not fixed — per task scope)

- **`system-prompts/base.md:119`** and **`report/routing.py:59`**
  (`_ZERO_RATED_VGS`) are both missing `ZP`, which was added to
  `_E2_ZERO_RATE_CODES`/`E2_ZERO_RATE_CODES` in T2.10 but never propagated to
  these two locations. A `detect_gst_errors` E2 finding on a `ZP` line
  currently falls through `report/routing.py`'s E2 dispatch to the generic
  Template 1 / `UNKNOWN_VATGROUP` fallback instead of Template 3 / `E2_ZR`.
- **`TX-RE` label is inconsistent across 3 locations**:
  `sap_b1_server._vg_category` says "Tourist refund — retail";
  `run_baseline_tests.KNOWN_VATGROUPS` and `system-prompts/base.md` both say
  "Residual input tax / requires manual apportionment". Annex E's `TX-RE`
  (residual input tax / partial exemption) matches the latter, not
  `_vg_category`'s — meaning `_vg_category`'s label becomes actively wrong
  (not just inconsistent) once Annex E is adopted, and per Section 2 of the
  inventory should be corrected **as part of** the T2.21 migration.
- **`_vg_category`'s `ME` label** ("Minor/miscellaneous exempt") also appears
  to be a mislabel vs. base.md/`KNOWN_VATGROUPS`'s "Major Exporter Scheme" —
  same drift pattern, noted in Section 2c.
- **`TX-E33`'s label** in `_vg_category` ("Tourist refund — Reg 33") follows
  the same drift pattern as `TX-RE` — a third instance, not previously
  documented.

None of these were corrected, per the explicit constraint that IRAS source is
the only authority and out-of-scope corrections should be flagged, not fixed.

---

## Docs updated (the only other changes besides the inventory file)

- **`knowledge-base/AgentAssist-Technical-Roadmap-v5.md`**:
  - Added a new `### T2.20 — Annex E vocabulary migration: discovery audit —
    DONE (2026-06-12)` entry after T2.19, summarizing the findings above.
  - Annotated `### T2.2 — Custom VatGroup discovery and reporting — PLANNED`
    as "(sequenced behind T2.20)" with a note explaining why T2.2 should not
    be scoped against "the 18-code standard set" until the Annex E migration
    lands or is explicitly deferred.
- **`AGENTASSIST_TECHNICAL_STATE.md`**:
  - Added Appendix C item **#31** documenting T2.20 as DONE (audit complete,
    build task OPEN), summarizing the same findings.
  - Added a trailing "Updated 2026-06-12 (T2.20: …)" changelog line.

`git diff --stat` confirms only these two `.md` files were modified (68
insertions, 1 deletion total), plus the new `exploration-notes/t2.20/`
directory (inventory + this report).

---

## Housekeeping note

A venv directory `.venv-t2.20/` was created in the repo root for this audit
(per SOP step 1, "New venv"). It is **untracked** (not in `git status`'s
tracked-file diff) but exists on disk in the working tree. No fixtures were
regenerated via `generate_invoices.py` — this was a static-analysis task plus
the one live recon query described in Section 0, both read-only by nature.

---

## What's NOT done (by design — out of scope for T2.20)

- No source code, config, fixtures, or system prompts were modified.
- No Annex E mappings were implemented.
- The two pre-existing drift bugs (ZP-missing-from-E2 in base.md/
  report/routing.py) and the TX-RE/ME/TX-E33 label inconsistencies were
  **not fixed** — flagged for T2.21 per the inventory.
- IRAS Annex E text itself was not available/fetched; Section 2's mappings are
  the auditor's best-effort interpretation based on standard IRAS GST
  category-code naming conventions and need verification before T2.21 build
  work begins (see the "Open Items Requiring IRAS Text Confirmation" list at
  the end of the inventory document).

---

## Next steps (for Collin)

1. Review `exploration-notes/t2.20/vocabulary-migration-inventory.md`.
2. Decide whether T2.18's scope needs extending (Customer Accounting flag +
   split reverse-charge flags + the new `NA`/`TXNA` scheme-participation
   flags, see addendum below) before T2.21, per Section 3's recommendation.
3. ~~Obtain/verify the actual IRAS Annex E text~~ — **done, see addendum
   below**.
4. If approved, merge this branch's doc updates + the inventory artifact via
   PR (no source-code changes to review beyond docs).

---

## Addendum (2026-06-12): Section 2 rewritten against the actual Annex E text

The IRAS e-Tax Guide became available locally as
`etaxguide_gst_invoicenow_requirement.pdf`, with Annex E ("GST Category Codes
Accepted by IRAS") on **PDF pages 81-85** (printed pages 79-83). Using
`pdfplumber` to extract those 5 pages as the sole source of truth (no memory
or general GST-convention knowledge), **Section 2 (2a-2d) was rewritten** to
resolve all 9 items the original audit had flagged as "not currently
available" / "flagged, not resolved." Sections 3-6 and the "Open Items"
section were updated for consistency with Section 2's revised counts.

**All 9 originally-flagged items resolved** (full detail in Section 2c):

1. `NA` (supply) — confirmed: AMFT/A3PL/GMS/Discounted-Sales-Price-Scheme
   taxable supplies, distinct from `OS`.
2. `NG` (supply) — confirmed: output-side counterpart to `NR`, but for a
   *non-GST-registered reporting business*. Reclassified from "needs new
   context" to "direct carryover, recognized but not expected" — AgentAssist's
   clients are GST-registered by definition.
3. `TXNA` (purchase) — confirmed: purchase-side mirror of `NA` (same
   scheme family), **not** related to `NR` as the original draft guessed.
4. `TXRC-TS` — confirmed: the general/base reverse-charge-claimable-input
   code ("TS" ≈ "Taxable Supplies"), distinct from the `*-ESS`/`*-N33`/`*-RE`
   attribution-specific RC variants.
5. `TX-N33` (Annex E meaning) — confirmed genuine collision: Annex E's
   `TX-N33` is a fully-claimable attribution-context input, the *opposite* box
   treatment of the current `TX-N33` (fully excluded).
6. `TX-RE` — confirmed: matches the base.md/`KNOWN_VATGROUPS` "residual input
   tax / apportionment" reading, not `_vg_category`'s "Tourist refund" reading
   (which is confirmed wrong and must be corrected in T2.21). Box treatment
   flips from "fully excluded" to "partially claimable via apportionment."
7. **`TX-ESS`/`IM-ESS`/`TXRC-ESS` — CORRECTION to the original draft.** "ESS"
   means "Regulation 33 **Exempt Supplies**", not "Imported Services". This
   moved `TX-ESS`/`IM-ESS` out of the OVR/LVG grouping and into the
   T2.18-attribution family (alongside `TX-N33`/`TX-RE`/`IM-N33`/`IM-RE`).
8. `TX-E33` → `TX-ESS` — resolved as a **third collision** (not an orphan):
   same Reg-33-exempt-attribution concept, but Annex E's `TX-ESS` is
   partially-claimable vs. current `TX-E33`'s fully-excluded.
9. `OP` (purchase) — confirmed: Annex E's description is broader (also covers
   "chooses not to claim input tax from a GST-registered supplier"), but
   routes to the same "excluded" box treatment — doc-wording refinement only.

**New finding (not one of the 9):** Annex E lists `NR` twice — once for
GST-registered businesses' purchases from non-GST-registered suppliers
(AgentAssist's current `NR`), and again for purchases made by a
non-GST-registered reporting business (N/A to AgentAssist, parallel to `NG`).

**Net effect on Section 2d's mapping summary:** the 35 codes now split into
**8 buckets**: 14 direct carryovers (was 13 — `NG` added with caveat), 2
renames, **3** collisions (was 2 — `TX-E33`→`TX-ESS` added), 3
T2.18-attribution partial-`IM` codes (`IM-N33`/`IM-RE`/`IM-ESS`), 3
Customer-Accounting (T2.22), 5 Reverse-Charge (T2.22), 3 OVR/LVG (T2.22), 2
scheme-participation (`NA`/`TXNA`, new T2.18 scope addition). **T2.22-deferred
count drops from 13 to 11** (CA 3 + RC 5 + OVR/LVG 3) — `TX-ESS`/`IM-ESS`
reclassified into T2.21 scope via item 7. Section 6's only numeric change is
T2.18's estimate growing by +0.5 day (`NA`/`TXNA` scheme flags); all other
day-estimates are unchanged (the other resolutions were reclassifications
within totals already counted).

No source files were modified in this addendum beyond
`vocabulary-migration-inventory.md` and this session report — still read-only
per T2.20's scope.
