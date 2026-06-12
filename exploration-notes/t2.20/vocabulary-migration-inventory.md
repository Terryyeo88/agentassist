# T2.20 — Annex E Vocabulary Migration: Discovery Audit & Inventory

**Status:** Read-only discovery audit. No source files were modified as part of
producing this inventory. This document is the sole deliverable of T2.20 and
is the input to a future build task (tentatively T2.21).

**Scope reminder:** This audit does **not** implement any part of "Option C"
(migrating AgentAssist's internal VatGroup vocabulary from the current 18-code
SAP B1 set to the IRAS Annex E GST Category Code set, per the e-Tax Guide
*"Adopting GST InvoiceNow Requirement for GST-Registered Businesses"*, Second
Edition, 9 Mar 2026, Annex E). It produces an inventory and gap analysis only.

**Section 2 update (2026-06-12):** The original version of Section 2 (written
without access to the IRAS e-Tax Guide text) flagged 9 items — `NA`, `NG`,
`TXNA`, `TXRC-TS`, the `TX-N33`/`TX-RE` collisions, `TX-ESS`, `IM-ESS`, and
`TX-E33`'s fate — as "not currently available" / "flagged, not resolved." The
e-Tax Guide is now available locally as `etaxguide_gst_invoicenow_requirement.pdf`,
with Annex E ("GST Category Codes Accepted by IRAS") on **PDF pages 81-85**
(printed pages 79-83). Section 2 below was rewritten by extracting those 5
pages with `pdfplumber` and using the extracted text as the sole source of
truth — no part of the rewritten Section 2 relies on memory, training data, or
general GST-category-code conventions. All 9 originally-flagged items are
resolved in **Section 2c**, and the "Open Items Requiring IRAS Text
Confirmation" section at the end of this document has been updated to reflect
this.

**Code-count discrepancy:** The task brief describes "34 codes" but lists 35
(14 supply-side + 21 purchase-side = 35). This document treats the list as
authoritative (35 codes) and notes the discrepancy here rather than silently
reconciling it.

---

## Section 0 — Live Recon Finding

**SOP step 2 method:** Ran `calculate_f5_return`, `validate_invoice_tax_codes`,
and `detect_gst_errors` (Tools 12, 13, 14 in
`mcp-servers/custom/sap_b1_server.py`) over the same one-week period
(2024-07-01 to 2024-07-07) against the live `SBODEMOSG` company database
(`CLIENT_ID=sbodemosg`), via direct Python import (FastMCP `@mcp.tool()`
decorators do not prevent the underlying functions from being called directly).

**Finding: the three tools share ONE core vocabulary structure, plus ONE
secondary duplicate used only by Tool 13.**

| Construct | Location | Used by |
|---|---|---|
| `F5_BOX_MAPPING` (18-code dict, box routing) | `sap_b1_server.py:348-369` | Tool 12 (`calculate_f5_return`, 4 inline loops), Tool 13 (`validate_invoice_tax_codes`, via `vg_inventory` lt_box/tt_box/side fields), Tool 14 indirectly (via `_classify_line`) |
| `_E2_ZERO_RATE_CODES` | `sap_b1_server.py:376` | Tool 14 (`detect_gst_errors`, E2 check) |
| `_STANDARD_RATE_SALES` | `sap_b1_server.py:378` | Tool 12 (E1 candidates), Tool 14 (E3/E4 sales side) |
| `_classify_line` (shared E1-E4 helper) | `sap_b1_server.py:560-626` | Tool 13, Tool 14 |
| `_vg_category` (SECOND, independent 18-code dict — human-readable labels) | `sap_b1_server.py:997-1027` | **Tool 13 only** |

This means: a code-routing change (which box a code feeds) is **single-sourced**
through `F5_BOX_MAPPING` + the two module-level sets and will automatically
propagate to all three tools. A code-*label* change (the human-readable
"GST category" string returned in Tool 13's `vg_inventory`) is **not**
single-sourced — `_vg_category` is a second, independently-maintained 18-code
dictionary that only Tool 13 consults. **Section 1 below is structured around
this distinction**: every row is marked either "single-source-of-truth" (an
edit here propagates everywhere that matters) or "duplicate — could drift" (an
edit here does *not* automatically update the other copies).

**Live data observation (informational, not a finding about correctness):**
over the recon window, the only VatGroup codes that appeared in live
`SBODEMOSG` data were `SO` (13 sales docs) and `SI` (1 purchase doc) — i.e.,
16 of the current 18 codes (and by extension most of the new Annex E codes)
are not exercised by live demo data at all. Vocabulary coverage in this
codebase is driven almost entirely by **test fixtures** (see Section 4), not
by the live SBODEMOSG dataset. Any Annex E migration will be validated mostly
against fixtures.

**Drift already discovered during this audit (pre-existing, not introduced by
T2.20, listed here because it directly affects the Section 1 table structure):**

1. `system-prompts/base.md:119`'s E2 condition lists
   `VatGroup ∈ {ZR, OS, ES33, ESN33, BL, NR}` — **missing `ZP`**, which was
   added to `_E2_ZERO_RATE_CODES` (sap_b1_server.py) and `E2_ZERO_RATE_CODES`
   (run_baseline_tests.py) in T2.10. base.md was never updated.
2. `report/routing.py`'s `_ZERO_RATED_VGS = frozenset({"ZR", "OS"})` (line 59)
   also does not include `ZP`. A `detect_gst_errors` E2 finding on a `ZP` line
   (which Tool 14 *will* raise, per finding #1's set) falls through
   `_template_number`'s E2 branch to the generic Template 1 fallback (line
   101) instead of Template 3, and through `_appendix1_key` to
   `UNKNOWN_VATGROUP` (line 184) instead of `E2_ZR`. This is the same
   "ZP added in T2.10, downstream consumers not updated" pattern as #1, in a
   second location.
3. `TX-RE`'s human-readable label is **inconsistent across three locations**:
   `sap_b1_server._vg_category` (line 1025) calls it *"Tourist refund — retail
   (purchases)"*; `run_baseline_tests.KNOWN_VATGROUPS` (line 124) and
   `system-prompts/base.md` (line 76) both call it *"Residual input
   tax"* / *"requires manual apportionment"*. These describe different GST
   concepts. This becomes directly relevant in Section 2, because Annex E's
   `TX-RE` ("residual input tax", partial exemption / Reg 33 apportionment)
   matches the base.md/KNOWN_VATGROUPS reading, not `_vg_category`'s.

Per the task constraint ("flag but do not fix… that's out of scope"), none of
these three items have been corrected. They are recorded here because Section
6 must account for fixing #3 as part of the Annex E migration (see Section 2,
`TX-RE` row) — not as a standalone bugfix, but because Annex E adoption makes
the wrong label actively misleading rather than merely inconsistent.

---

## Section 1 — Load-Bearing VatGroup References Inventory

Status legend:
- **SSOT** = single source of truth; downstream consumers read this directly
  or are mechanically derived from it.
- **DUP-DRIFT** = an independent copy of (part of) the vocabulary; edits here
  do not propagate automatically, and can silently diverge from SSOT.
- **REF (audit-not-partner)** = an independent re-implementation in a
  reference/audit script. Per project convention, divergence between this and
  production is a bug to *find*, never resolved by editing the reference to
  match production.
- **DOC** = documentation/prompt text consumed by the LLM or by humans, not
  by code at runtime, but describes the vocabulary and can drift from it.
- **CONSUMER** = reads box-level or VatGroup-keyed data but does not itself
  enumerate the 18-code vocabulary; low migration impact if the *shape* of
  inputs (8 F5 boxes, VatGroupEntry fields) is preserved.

| # | File : Lines | Construct | Usage | Status |
|---|---|---|---|---|
| 1.1 | `mcp-servers/custom/sap_b1_server.py:348-369` | `F5_BOX_MAPPING` (18-code dict: lt_box/tt_box/side per code) | Box-routing for Tools 12, 13, 14 (see Section 0) | **SSOT** |
| 1.2 | `mcp-servers/custom/sap_b1_server.py:376` | `_E2_ZERO_RATE_CODES = {ZR,OS,ES33,ESN33,BL,NR,ZP}` | Tool 14 E2 check | **SSOT** (for Tool 14); mirrored in 1.8 (REF) and partially in 1.12 (DUP-DRIFT, missing ZP) |
| 1.3 | `mcp-servers/custom/sap_b1_server.py:378` | `_STANDARD_RATE_SALES = {SO, DS}` | Tool 12 E1 candidates; Tool 14 E3/E4 sales side | **SSOT** |
| 1.4 | `mcp-servers/custom/sap_b1_server.py:308-326` | `normalize_vat_group(raw_code, mappings)` (T2.19) | Translates non-SAP-B1 source codes to canonical VatGroup before any of the above are consulted | **SSOT** for the translation step; depends on `config/loader._STANDARD_VAT_GROUPS` (1.17) as its validation authority |
| 1.5 | `mcp-servers/custom/sap_b1_server.py:560-626` | `_classify_line()` — shared E1-E4 line classifier | Tools 13 & 14 | **SSOT** |
| 1.6 | `mcp-servers/custom/sap_b1_server.py:997-1027` | `_vg_category()` — SECOND independent 18-code dict (human-readable GST category labels) | Tool 13 only (`vg_inventory.gst_category`) | **DUP-DRIFT** — see Section 0 finding #3 (TX-RE label) |
| 1.7 | `scripts/run_baseline_tests.py:69-82` | `SALES_BOX1/2/3/EXCLUDED`, `PURCHASE_BOX5/7/EXCLUDED`, `STANDARD_RATE_CODES`, legacy `ZERO_RATE_SALES` | Independent re-derivation of F5 box routing for baseline verification | **REF (audit-not-partner)** — mirrors 1.1 + 1.3 |
| 1.8 | `scripts/run_baseline_tests.py:91` | `E2_ZERO_RATE_CODES = {ZR,OS,ES33,ESN33,BL,NR,ZP}` | Independent E2 check | **REF (audit-not-partner)** — mirrors 1.2; currently in sync |
| 1.9 | `scripts/run_baseline_tests.py:106-125` | `KNOWN_VATGROUPS` — THIRD independent 18-code dict (box + description) | Reference-script labels/descriptions | **REF (audit-not-partner)** — mirrors 1.6 in *purpose* but currently has the *correct* TX-RE label (Section 0 finding #3) |
| 1.10 | `scripts/check_listing_reference.py` | (n/a) | Confirmed **not** VatGroup-load-bearing — only SEQ_GAP/DUP_CLAIM document-numbering checks | not applicable to this migration |
| 1.11 | `system-prompts/base.md:35-44` | "F5 Box Definitions and Sources" table | Prompt text — informs LLM reasoning about box routing | **DOC** — mirrors 1.1 |
| 1.12 | `system-prompts/base.md:48-79` | "Complete VatGroup Routing Table" (sales + purchase) | Prompt text — mirrors 1.1 + 1.6 labels | **DOC / DUP-DRIFT** |
| 1.13 | `system-prompts/base.md:119` | E2 condition set in "Common GST Error Codes" table | Prompt text — mirrors 1.2 | **DOC / DUP-DRIFT** — see Section 0 finding #1 (missing ZP) |
| 1.14 | `report/routing.py:59-62` | `_ZERO_RATED_VGS`, `_EXEMPT_VGS`, `_BLOCKED_INPUT_VGS`, `_SR_SALES_VGS` (4 frozensets) | Drive `_template_number` (lines 65-118) and `_appendix1_key` (lines 153-202) — report template/wording dispatch for E2/E3/E4 findings | **DUP-DRIFT** — see Section 0 finding #2 (`_ZERO_RATED_VGS` missing ZP) |
| 1.15 | `report/sections.py:53-62` | `_BOX_VATGROUPS: dict[str, list[str]]` | Static mirror of F5 box→VatGroup routing, used to populate the F5 box table's "contributing VatGroups" column | **DUP-DRIFT** — comment cites `F5_BOX_MAPPING` as source but is not programmatically derived from it |
| 1.16 | `report/sections.py:629-651` | Judgment-section literals: `f.vat_group in {"ES33","ESN33"}` (line 632), `f.vat_group == "BL"` (line 651) | Builds "Exemption Qualification" and "Business Purpose (Reg 26/27)" judgment groups | **DUP-DRIFT** — additional vocabulary-keyed literals beyond 1.14 |
| 1.17 | `config/loader.py:63-67` | `_STANDARD_VAT_GROUPS` (frozenset of all 18 codes) | Validates `custom_vat_groups` collisions (line 255) and `tax_code_mappings` targets (line 300) — THE canonical validation set for the whole config layer | **SSOT** (for config validation) — second-most-central structure after 1.1 |
| 1.18 | `config/loader.py` `ClientConfig` dataclass | `custom_vat_groups: dict`, `tax_code_mappings: dict`, `source_system: str` | T2.19 extensibility point — per-client vocabulary extension/translation | **SSOT** (schema); instances in 1.19 |
| 1.19 | `config/clients/example.yaml`, `config/clients/sbodemosg.yaml` | `custom_vat_groups` / `tax_code_mappings` example + live config | Per-client config instances. `example.yaml`'s comment says "17 canonical" but lists all 18 codes (pre-existing minor inconsistency, not fixed per task scope) | **DOC / config instance** |
| 1.20 | `knowledge-base/sg-tax-code-mappings.md` | Full prose documentation of the 18-code vocabulary with IRAS paragraph citations (5.7-5.14, 6.5.1, 6.8.3, 4.2.9) | Reference documentation cited by base.md and reports as the internal source of truth for *why* each code routes the way it does | **DOC** — FIFTH location carrying the 18-code vocabulary |
| 1.21 | `orchestrator/check_listing.py`, `check_analytical_review.py`, `check_period_fluctuation.py` | Consume F5 box-level aggregates (`box_1`…`box_8`) | No VatGroup-keyed literals found (confirmed via grep) | **CONSUMER** — low impact assuming the 8-box F5 structure is unchanged under Annex E |
| 1.22 | `orchestrator/schemas.py:95-119` | `VatGroupEntry` TypedDict (`gst_category`, `side`, `lt_box`, `tt_box`, `doc_count`, `known_to_mapping`) | Structural type for Tool 13's `vg_inventory` | **CONSUMER** — field *shapes* are vocabulary-agnostic; only the *values* (e.g. `side: Literal["sales","purchase","unknown"]`) need new codes to fit the existing enum |
| 1.23 | `audit_bundle/config_redaction.py:30-44` | `_ALLOW_LIST` includes `"custom_vat_groups"`, `"tax_code_mappings"`; `_DENY_ALWAYS = {"username","password","ssl_verify"}` | Redaction allow-list for audit bundle export | **SSOT (for redaction)** — any *new* T2.18/T2.21 ClientConfig field (e.g. scheme flags) would need adding here to avoid being redacted-by-default |

**Summary count:** the 18-code vocabulary is carried in **at least 7
independently-maintained locations** (1.1/1.6 in sap_b1_server.py, 1.7-1.9 in
run_baseline_tests.py, 1.11-1.13 in base.md, 1.14 in report/routing.py, 1.15-1.16
in report/sections.py, 1.17 in config/loader.py, 1.20 in
sg-tax-code-mappings.md — note 1.6 and 1.9 are two *separate* dicts, so the
"7 locations" figure undercounts files but the per-construct count is higher).
Only 1.1 (`F5_BOX_MAPPING`) + 1.2/1.3 (the two module-level sets) +
1.5 (`_classify_line`) constitute the **single shared core**; everything else
is either documentation, a reference re-implementation, or an independent
partial duplicate. This is the basis for Sections 5 and 6.

---

## Section 2 — Code-by-Code Annex E Mapping Table

Current 18-code set (for reference): `SO, SI, ZR, ES33, ESN33, OS, DS, ZP, EP,
OP, IM, IGDS, ME, NR, BL, TX-E33, TX-N33, TX-RE`.

**Source for this section:** `etaxguide_gst_invoicenow_requirement.pdf`,
Annex E ("GST Category Codes Accepted by IRAS"), PDF pages 81-85 (printed
pages 79-83), extracted with `pdfplumber`. All Annex E descriptions quoted
below are verbatim from that extraction.

### 2a. Supplies (14 Annex E codes)

| Annex E Code | Rate | Annex E Description (verbatim, pp. 81-82) | Current SAP equivalent | → 2d bucket |
|---|---|---|---|---|
| `SR` | 9% | "Standard-rated supply of goods or services" | `SO` | 2. Rename (`SO`→`SR`) |
| `SRCA-S` | NA | "Customer accounting supply made by supplier" | None | 5. Customer Accounting (T2.22) |
| `SRCA-C` | 9% | "Customer accounting supply accountable by the customer on supplier's behalf" | None | 5. Customer Accounting (T2.22) |
| `SRLVG` | 9% | "Own supply of Low-Value Goods (\"LVG\")" | None | 7. OVR/LVG/marketplace (T2.22) |
| `NA` | NA¹ | "Taxable supplies where GST need not be charged under specific schemes such as AMFT scheme, A3PL scheme. Taxable supplies where GST is accounted for on a different basis under specific schemes, such as GMS and Discounted Sales Price Scheme." | None — distinct from `OS` (item 1, 2c) | 8. Scheme-participation (T2.18 addition) |
| `SRRC` | 9% | "Imported services and LVG accountable by the GST-registered customer under reverse charge" | None | 6. Reverse Charge (T2.22) |
| `SROVR-RS` | 9% | "Supply of remote services accountable by the electronic marketplace on behalf of third-party suppliers" | None | 7. OVR/LVG/marketplace (T2.22) |
| `SROVR-LVG` | 9% | "Supply of LVG accountable by the redeliverer or electronic marketplace on behalf of third-party suppliers" | None | 7. OVR/LVG/marketplace (T2.22) |
| `DS` | 9% | "Deemed supplies" | `DS` — direct 1:1 match | 1. Direct carryover |
| `ZR` | 0% | "Zero-rated supplies" | `ZR` — direct 1:1 match | 1. Direct carryover |
| `ES33` | NA | "Regulation 33 Exempt Supplies" | `ES33` — direct 1:1 match | 1. Direct carryover |
| `ESN33` | NA | "Non-Regulation 33 Exempt Supplies" | `ESN33` — direct 1:1 match | 1. Direct carryover |
| `OS` | NA | "Supplies outside the scope of the GST Act" | `OS` — direct 1:1 match | 1. Direct carryover |
| `NG` | NA | "Supplies made by non-GST registered business, i.e. the non-GST registered business is not required to determine GST treatment, charge GST, or file any GST returns." | None | 1. Direct carryover — recognized, not expected (item 2, 2c) |

¹ Footnote 21 (p. 81): "IRSPs should enable businesses to record and transmit
output tax amounts to IRAS that may not be 9% of the value of standard-rated
supplies, due to the special rules accorded under the specific GST schemes."

**Supply-side tally:** 6 direct carryovers (`DS`, `ZR`, `ES33`, `ESN33`, `OS`,
`NG`* — `NG` carries the "recognized, not expected" caveat from item 2), 1
rename (`SO`→`SR`), 2 Customer-Accounting-family (`SRCA-S`, `SRCA-C`), 1
Reverse-Charge-family (`SRRC`), 3 OVR/LVG-family (`SRLVG`, `SROVR-RS`,
`SROVR-LVG`), 1 scheme-participation (`NA`). Total: 6+1+2+1+3+1 = 14.

### 2b. Purchases (21 Annex E codes — task brief says 20, lists 21; see
code-count discrepancy note at top of document)

| Annex E Code | Rate | Annex E Description (verbatim, pp. 83-85) | Current SAP equivalent | → 2d bucket |
|---|---|---|---|---|
| `TX` | 9% | "Standard-rated taxable purchases" | `SI` | 2. Rename (`SI`→`TX`) |
| `IM` | 9% | "Import of goods (9% GST paid to Singapore Customs on the import of goods into Singapore)" | `IM` — direct 1:1 match | 1. Direct carryover |
| `ME` | 0% | "Import of goods under the Major Exporter Scheme (\"MES\"), A3PL scheme or other approved schemes²" | `ME` — direct 1:1 match | 1. Direct carryover (T2.18 validation caveat, unchanged) |
| `IGDS` | 9% | "Import of goods under the Import GST Deferment Scheme (\"IGDS\")" | `IGDS` — direct 1:1 match | 1. Direct carryover (T2.18 validation caveat, unchanged) |
| `TXCA` | 9% | "Standard-rated purchases of prescribed goods subject to customer accounting" | None | 5. Customer Accounting (T2.22) |
| `TXNA` | NA¹ | "Purchases made where no GST is charged under specific GST schemes, such as AMFT scheme, A3PL scheme. Purchases made where GST is accounted for on a different basis under specific schemes, such as GMS and Discounted Sales Price Scheme." | None — purchase-side mirror of `NA`, NOT `NR` (item 3, 2c) | 8. Scheme-participation (T2.18 addition) |
| `TXRC-TS` | 9% | "Imported services and LVG claimable by the GST-registered customer under reverse charge" | None — general/base RC-claimable-input code (item 4, 2c) | 6. Reverse Charge (T2.22) |
| `TX-ESS` | 9% | "Standard-rated purchases directly attributable to Regulation 33 exempt supplies" | `TX-E33` (collision/remap, items 7+8, 2c) | 3. Collision — `TX-E33`→`TX-ESS` |
| `TXRC-ESS` | 9% | "Imported services and LVG claimable by the GST-registered customer under reverse charge and that are directly attributable to Regulation 33 exempt supplies" | None | 6. Reverse Charge (T2.22) |
| `IM-ESS` | 9% | "Import of goods with GST paid to Singapore Customs that are directly attributable to Regulation 33 exempt supplies" | Partial: `IM` exists, undifferentiated by attribution (item 7, 2c) | 4. T2.18-attribution, partial `IM` carryover |
| `TX-N33` | 9% | "Standard-rated purchases directly attributable to non-Regulation 33 exempt supplies" | `TX-N33` (collision, item 5, 2c) | 3. Collision — `TX-N33` |
| `TXRC-N33` | 9% | "Imported services and LVG claimable by the GST-registered customer under reverse charge that are directly attributable to non-Regulation 33 exempt supplies" | None | 6. Reverse Charge (T2.22) |
| `IM-N33` | 9% | "Import of goods with GST paid to Singapore Customs that are directly attributable to non-Regulation 33 exempt supplies" | Partial: `IM` exists, undifferentiated by attribution | 4. T2.18-attribution, partial `IM` carryover |
| `TX-RE` | 9% | "Residual input tax – purchases from GST-registered suppliers that are subject to GST at 9% and are either: (a) Attributable to the making of both taxable and exempt supplies; or (b) Incurred for the overall running of the business" | `TX-RE` (collision, item 6, 2c) | 3. Collision — `TX-RE` |
| `TXRC-RE` | 9% | "Imported services and LVG claimable by the GST-registered customer under reverse charge that are residual" | None | 6. Reverse Charge (T2.22) |
| `IM-RE` | 9% | "Import of goods with GST paid to Singapore Customs that are residual" | Partial: `IM` exists, undifferentiated by attribution | 4. T2.18-attribution, partial `IM` carryover |
| `ZP` | 0% | "Zero-rated purchases" | `ZP` — direct 1:1 match | 1. Direct carryover |
| `BL` | 9% | "Disallowed expenses" | `BL` — direct 1:1 match | 1. Direct carryover |
| `EP` | NA | "Exempt purchases" | `EP` — direct 1:1 match | 1. Direct carryover |
| `OP` | NA | "Out-of-scope purchases received from GST-registered suppliers. Purchases from GST-registered suppliers where input tax is not claimed (e.g. not for business purposes, invalid tax invoices, not claiming input tax out of prudence etc.)" | `OP` — direct 1:1 match, doc-wording refinement (item 9, 2c) | 1. Direct carryover |
| `NR` | NA | "Purchases received from non-GST registered suppliers" | `NR` — direct 1:1 match, per IRAS para 5.11(o) | 1. Direct carryover |

² Footnote 22 (p. 83): "This refers to approved schemes that specifically
requires the reporting of the total value of goods imported in Box 9 of the
GST return."

**Purchase-side tally:** 8 direct carryovers (`IM`, `ME`, `IGDS`, `ZP`, `BL`,
`EP`, `OP`, `NR`), 1 rename (`SI`→`TX`), 3 collisions (`TX-ESS`, `TX-N33`,
`TX-RE`), 3 T2.18-attribution partial-`IM`-carryover (`IM-ESS`, `IM-N33`,
`IM-RE`), 1 Customer-Accounting-family (`TXCA`), 4 Reverse-Charge-family
(`TXRC-TS`, `TXRC-ESS`, `TXRC-N33`, `TXRC-RE`), 1 scheme-participation
(`TXNA`). Total: 8+1+3+3+1+4+1 = 21.

### 2c. Resolution of the 9 originally-flagged items (verified against Annex E, pp. 81-85)

**1. `NA` (supply-side) — CONFIRMED, distinct from `OS`.** Per p. 81: "Taxable
supplies where GST need not be charged under specific schemes such as AMFT
scheme, A3PL scheme. Taxable supplies where GST is accounted for on a
different basis under specific schemes, such as GMS and Discounted Sales
Price Scheme." Footnote 21 confirms these are real output-tax amounts that
may differ from the standard 9% due to scheme-specific rules — i.e. `NA`
covers supplies that **are** taxable (genuine output tax, possibly
scheme-modified) but fall under AMFT/A3PL/GMS/Discounted-Sales-Price-Scheme
treatment. This is categorically different from `OS` ("Supplies outside the
scope of the GST Act" — not taxable supplies at all). → bucket 8
(scheme-participation, T2.18 addition).

**2. `NG` (supply-side) — CONFIRMED, reclassified to "recognized but not
expected."** Per p. 82: "Supplies made by non-GST registered business, i.e.
the non-GST registered business is not required to determine GST treatment,
charge GST, or file any GST returns." This is the OUTPUT-side counterpart to
the purchase-side `NR` — but it describes a scenario where the **reporting
business itself** is not GST-registered. AgentAssist's entire toolset
presumes a GST-registered reporting client (F5 returns, box totals,
`actively_makes_exempt_supplies`, etc. are all GST-registration-contingent
concepts), so `NG` could never appear in one of AgentAssist's clients' own
sales records. Reclassified from "needs new context" (original 2a) to
**bucket 1 (direct carryover — recognized, not expected to occur)**:
AgentAssist should not treat `NG` as an "unknown VatGroup" anomaly if it ever
appears, but no new detection logic is needed.

**3. `TXNA` (purchase-side) — CONFIRMED, purchase-side mirror of `NA`, not
related to `NR`.** Per p. 83: "Purchases made where no GST is charged under
specific GST schemes, such as AMFT scheme, A3PL scheme. Purchases made where
GST is accounted for on a different basis under specific schemes, such as GMS
and Discounted Sales Price Scheme." This is the exact purchase-side mirror of
item 1's `NA` — same AMFT/A3PL/GMS/Discounted-Sales-Price-Scheme family. The
original audit's guess that `TXNA` might relate to `NR` ("non-GST-registered
supplier") is **incorrect** — `TXNA` is about the *AgentAssist client's own*
scheme participation, not the supplier's GST-registration status. → bucket 8,
same T2.18 scheme-participation addition as `NA`.

**4. `TXRC-TS` (purchase-side) — CONFIRMED, general/base reverse-charge-
claimable-input code.** Per p. 83: "Imported services and LVG claimable by the
GST-registered customer under reverse charge." `TXRC-TS` is listed **first**
in the "Standard-rated purchases (Additional for input tax attribution and
apportionment)" group (pp. 83-84), immediately before the attribution-specific
RC variants `TXRC-ESS`/`TXRC-N33`/`TXRC-RE`. "TS" most plausibly abbreviates
"Taxable Supplies" — i.e. `TXRC-TS` is the RC-claimable input attributed to
(general) taxable supplies, as distinguished from the `*-ESS`/`*-N33`/`*-RE`
attribution-specific RC variants. → bucket 6 (Reverse Charge, T2.22) —
requires RC detection generally, same as `SRRC` and the other `TXRC-*` codes.

**5. `TX-N33` (Annex E meaning) — CONFIRMED genuine collision, opposite box
treatment.** Per p. 84: "Standard-rated purchases directly attributable to
non-Regulation 33 exempt supplies", 9%, listed in the "input tax attribution
and apportionment" group. This is a **fully-claimable standard input** (box
5/box 7-eligible, subject to attribution) — the **opposite** box treatment
from the CURRENT `TX-N33` (per `_vg_category`/base.md/`KNOWN_VATGROUPS`:
"Non-Regulation-33 exempt purchase, excluded from all boxes"). Confirmed: this
cannot be a string-preserving carryover; T2.21 must deliberately remap the
current `TX-N33` semantics elsewhere (see item 8) while the `TX-N33` string is
repurposed for Annex E's attribution-context input. → bucket 3 (collision,
T2.18-attribution family).

**6. `TX-RE` — CONFIRMED, matches base.md/`KNOWN_VATGROUPS` reading, not
`_vg_category`'s.** Per p. 84: "Residual input tax – purchases from
GST-registered suppliers that are subject to GST at 9% and are either: (a)
Attributable to the making of both taxable and exempt supplies; or (b)
Incurred for the overall running of the business." This confirms the
base.md/`KNOWN_VATGROUPS` reading ("Residual input tax / requires manual
apportionment"), **not** `_vg_category`'s "Tourist refund — retail
(purchases)" — `_vg_category`'s label is confirmed wrong and must be corrected
as part of T2.21 (Section 0 finding #3). On box treatment: the CURRENT
`TX-RE` is fully excluded (`F5_BOX_MAPPING`: `lt_box=None, tt_box=None`).
Annex E's `TX-RE` describes GST on purchases that genuinely relates (in part)
to taxable-supply-making — i.e. a **partial** claim via an apportionment
ratio, not a flat exclusion. This is a box-treatment flip from "fully
excluded" to "partially claimable via apportionment," and is only meaningful
for clients with `actively_makes_exempt_supplies=True` (T2.18). → bucket 3
(collision, T2.18-attribution family).

**7. `TX-ESS` — CORRECTION to the original draft's guess; "ESS" = Reg-33
Exempt Supplies, not "Imported Services."** The original (pre-Annex-E-text)
Section 2 guessed `TX-ESS` was an "Imported Services, standard-rated" code (an
OVR-for-B2B-services gap). The actual text, pp. 83-84: "Standard-rated
purchases directly attributable to **Regulation 33 exempt supplies**."
`TX-ESS` is the Reg-33 sibling of `TX-N33` (non-Reg-33, item 5) and `TX-RE`
(residual, item 6) — all three are in the same "input tax attribution and
apportionment" group, 9%, attribution-context partially-claimable inputs.
**This correction propagates to `IM-ESS` and `TXRC-ESS`**, whose `-ESS` suffix
carries the same "Reg-33-exempt-supply attribution" meaning (p. 84: "directly
attributable to Regulation 33 exempt supplies"), not "imported services":

- `TX-ESS` → becomes `TX-E33`'s collision target (item 8) → bucket 3.
- `IM-ESS` → moves out of the OVR/LVG grouping into bucket 4
  (T2.18-attribution, partial `IM` carryover), alongside `IM-N33`/`IM-RE`.
- `TXRC-ESS` → remains in bucket 6 (Reverse Charge, T2.22) — it additionally
  requires RC detection, same as `TXRC-N33`/`TXRC-RE`.

**8. `TX-E33` → `TX-ESS` — RESOLVED, third collision (not an orphan).** The
original Section 2c framed `TX-E33` (current meaning: "Regulation 33 exempt
purchase, excluded" per base.md/`KNOWN_VATGROUPS`, or "Tourist refund — Reg
33" per `_vg_category` — a third instance of the label-drift pattern from
Section 0 finding #3) as having **no Annex E target**. With item 7's
correction, `TX-E33` *does* have a conceptual target: `TX-ESS` ("Standard-rated
purchases directly attributable to Regulation 33 exempt supplies") — same
Reg-33-exemption-attribution concept as `TX-E33`'s current meaning. But Annex
E's `TX-ESS` is a 9%, attribution-context, **partially-claimable** input (same
family as `TX-N33`/`TX-RE`), whereas the current `TX-E33` is **fully excluded**
(`lt_box=None, tt_box=None`). So `TX-E33`→`TX-ESS` is a **third collision** in
the T2.18-attribution family, with the same "fully excluded → apportionment-
based partial claim" box-treatment flip as `TX-N33` and `TX-RE`.
`_vg_category`'s "Tourist refund — Reg 33" label is also confirmed wrong
(third instance of Section 0 finding #3's drift pattern) and must be
corrected. → bucket 3.

**9. `OP` (purchase-side) — CONFIRMED, broader wording, no box-treatment
change.** Per p. 85: "Out-of-scope purchases received from GST-registered
suppliers. Purchases from GST-registered suppliers where input tax is not
claimed (e.g. not for business purposes, invalid tax invoices, not claiming
input tax out of prudence etc.)." The current `OP` ("Out-of-scope purchase,
excluded" per base.md/`KNOWN_VATGROUPS`/`_vg_category`) is narrower in
wording — Annex E's `OP` *additionally* covers GST-registered-supplier
purchases where input tax is validly chargeable but the business **chooses**
not to claim it (prudence, invalid tax invoice, not-for-business-purpose).
Both readings route to "excluded from box 5/7" — **no box-treatment change**.
This is a doc-wording refinement only (broaden `OP`'s description in base.md /
`sg-tax-code-mappings.md` during T2.21), not a new code or collision. →
bucket 1 (direct carryover).

**Additional finding (not one of the original 9): Annex E lists `NR` twice,
with different scope.** Page 85 lists `NR` ("Purchases received from
non-GST registered suppliers") under "Non-reportable purchases" — this is the
code AgentAssist's current `NR` maps to (item 21 of 2b). Immediately after,
under a separate major heading, **"Purchases received by non-GST registered
business"** → "Non-reportable purchases" → `NR`: "Purchases received by
non-GST registered business, i.e. the non-GST registered business is not
allowed to claim any input tax and not required to file any GST returns."
This second `NR` describes purchases made by a reporting business that is
**itself** not GST-registered — exactly parallel to `NG` (item 2) on the
supply side, and for the same reason (AgentAssist's clients are
GST-registered) it is N/A to AgentAssist and is **not** part of the 21-code
purchase list counted in 2b/2d. Flagged for completeness; no action needed.

### 2d. Overall mapping summary (35 Annex E codes → 8 buckets)

| Bucket | Count | Codes | T2.21 / T2.22 disposition |
|---|---|---|---|---|
| 1. Direct 1:1 carryover | 14 | `DS`, `ZR`, `ES33`, `ESN33`, `OS`, `IM`, `ME`*, `IGDS`*, `ZP`, `BL`, `EP`, `OP`*, `NR`, `NG`* | T2.21 — vocabulary/box-routing edit only |
| 2. Rename only | 2 | `SO`→`SR`, `SI`→`TX` | T2.21 — vocabulary edit + fixture rename |
| 3. Name collision — T2.18-attribution family, box-treatment flip | 3 | `TX-N33`, `TX-RE`, `TX-E33`→`TX-ESS` | T2.21 — deliberate semantic remap, needs T2.18's `actively_makes_exempt_supplies` |
| 4. T2.18-attribution family, partial `IM` carryover, new attribution dimension | 3 | `IM-N33`, `IM-RE`, `IM-ESS` | T2.21 — extend `IM`'s box routing with an attribution dimension |
| 5. Customer Accounting family | 3 | `SRCA-S`, `SRCA-C`, `TXCA` | **T2.22** — needs per-transaction prescribed-goods/CA detection |
| 6. Reverse Charge family | 5 | `SRRC`, `TXRC-TS`, `TXRC-ESS`, `TXRC-N33`, `TXRC-RE` | **T2.22** — needs RC detection |
| 7. OVR/LVG/marketplace family | 3 | `SRLVG`, `SROVR-RS`, `SROVR-LVG` | **T2.22** — needs counterparty OVR-registration data |
| 8. Scheme-participation family | 2 | `NA`, `TXNA` | T2.21 (extends T2.18 scope, +0.5 day, Section 6) — AMFT/A3PL/GMS/Discounted-Sales-Price flags |
| **Total** | **35** | | |

\* `ME`/`IGDS` carry the unchanged T2.18-validation caveat from the original
audit; `OP` carries the doc-wording refinement (item 9); `NG` carries the
"recognized, not expected" caveat (item 2).

**T2.21-in-scope codes (buckets 1+2+3+4+8):** 14+2+3+3+2 = **24**.

**T2.22-deferred codes (buckets 5+6+7):** 3+5+3 = **11** — down from the
original audit's 13. `TX-ESS` and `IM-ESS` moved out of "no current
equivalent" into buckets 3/4 respectively (item 7's correction); they were
already counted in the original "18 no-equivalent" bucket, so this is a
reclassification, not new scope. None of these 11 are addressable by a pure
vocabulary/box-routing edit — each requires either new per-transaction data, a
new ClientConfig scheme flag, or both. This is the basis for Section 3 (T2.18)
and Section 6 (effort).

---

## Section 3 — T2.18 Dependency Analysis

**Question:** does Option C require T2.18 ("ClientConfig scheme & treatment
block" — PLANNED, not built) first?

**T2.18's currently-described scope** (per
`knowledge-base/AgentAssist-Technical-Roadmap-v5.md`): promote
`actively_makes_exempt_supplies` from a getattr-default-False to a real
`ClientConfig` field, and add MES (Major Exporter Scheme) / IGDS
participation flags + a reverse-charge-applicability flag.

**Mapping T2.18's fields against Section 2d's buckets 3-8 (the 19 codes
needing more than a pure carryover/rename edit):**

| T2.18 field (as currently scoped) | Annex E codes it would help with | Sufficient on its own? |
|---|---|---|
| `actively_makes_exempt_supplies` (promoted to real field) | `TX-RE`, `IM-RE`, `TXRC-RE` (partial-exemption / residual-input attribution family) | **Necessary but not sufficient** — confirms *whether* apportionment logic applies to a client, but does not itself classify which purchases need apportionment (that's transaction-level) |
| MES participation flag | `ME` (validation against current carryover, not a new code) | Yes, for its narrow purpose (anomaly: `ME` used by a non-MES client) |
| IGDS participation flag | `IGDS` (validation against current carryover) | Yes, for its narrow purpose |
| Reverse-charge-applicability flag (single boolean, as currently scoped) | `SRRC`, `TXRC-TS`, `TXRC-ESS`, `TXRC-N33`, `TXRC-RE` (all `*RC*` codes) | **Only as a coarse exclusion gate.** If `False`, any RC-prefixed code appearing in source data is itself an anomaly (same pattern as "unknown VatGroup" today). It cannot *classify* which specific purchases are RC vs. directly-charged — that's transaction-level and the regime has at least two distinct sub-flavours (imported-services RC since 2020 vs. LVG/OVR-related RC since 2023) that a single flag conflates |

**Codes T2.18 (as currently scoped) does NOT help with at all:**

- **Customer Accounting family** (`SRCA-S`, `SRCA-C`, `TXCA`) — not mentioned
  in T2.18's roadmap entry at all. Would need either a new client-level
  "customer-accounting-applicability" flag (a T2.18 scope *extension*) or
  per-transaction detection of prescribed-goods sales.
- **OVR/LVG family** (`SRLVG`, `SROVR-RS`, `SROVR-LVG`) — these depend on the
  **counterparty's** (overseas vendor's/electronic marketplace's) OVR
  registration status, which is fundamentally per-transaction/per-vendor data,
  not a fact about the AgentAssist client itself. No client-level ClientConfig
  flag, however scoped, can resolve these — they need either richer
  source-document data (a document-ingestion-level change, outside
  ClientConfig entirely) or a "manual review" fallback. (`TX-ESS`/`IM-ESS`,
  previously grouped here on the assumption "ESS" meant "Imported Services",
  have been moved to the T2.18-attribution family per Section 2c item 7 — they
  are Reg-33-exempt-attribution codes, not OVR/LVG codes.)
- **`NA`, `TXNA` (scheme-participation family, Section 2d bucket 8)** —
  confirmed (Section 2c items 1/3) as a small T2.18 scope *extension*:
  AMFT/A3PL/GMS/Discounted-Sales-Price-Scheme participation flags, analogous
  to the existing MES/IGDS flags. Adds ~0.5 day to T2.18 (Section 6).
- **`SRRC`, `TXRC-TS`** — confirmed (Section 2c items 4) as ordinary members of
  the Reverse Charge family, covered by the reverse-charge-applicability flag
  row above (same "coarse exclusion gate" caveat). `NG` (Section 2c item 2) is
  confirmed "recognized but not expected" and needs no T2.18 field at all.

**Recommendation:**

1. T2.18, in its currently-described scope, is a **useful but only partial**
   prerequisite. It directly unblocks correct handling of `ME`/`IGDS`
   (validation) and is a necessary (not sufficient) building block for the
   `TX-RE`/`IM-RE`/`TXRC-RE` residual-input-tax family.
2. T2.18 and T2.21 will touch overlapping files (`config/loader.py`'s
   `ClientConfig`/`_STANDARD_VAT_GROUPS`, `audit_bundle/config_redaction.py`'s
   allow-list, `report/routing.py`'s template dispatch for `actively_makes_exempt`).
   **Sequencing T2.18 immediately before or combined with T2.21** avoids a
   second edit pass over the same surfaces.
3. T2.18 alone does **not** fully unblock Option C. Before T2.21 begins,
   confirm whether T2.18's scope should be **extended** (a "T2.18b"?) to add
   a customer-accounting-applicability flag, AMFT/A3PL/GMS/Discounted-Sales-
   Price-Scheme participation flags (Section 2c items 1/3, `NA`/`TXNA`), and to
   split the single reverse-charge flag into the imported-services-RC vs.
   LVG/OVR-RC sub-flavours — or whether T2.21 should simply ship the CA family
   (3 codes), OVR/LVG family (3 codes), and Reverse Charge family (5 codes) —
   11 codes total (Section 2d buckets 5-7) — as "insufficient data → manual
   review" anomalies for v1, deferring real detection to a later task (see
   Section 6).
4. **T2.2** ("Custom VatGroup discovery and reporting", PLANNED, references
   "the 18-code standard set") is sequenced **behind** T2.20's findings: T2.2
   should not be scoped against the 18-code set if T2.21 (Annex E migration)
   is expected to land first, since T2.2's "standard set" reference would
   immediately need rework. This is reflected in the roadmap update at the
   end of this document.

---

## Section 4 — Test Fixture Impact

Searched `tests/fixtures/**/*.json` for hardcoded VatGroup code strings
(`SO`, `SI`, `ZR`, `DS`, `ES33`, `ESN33`, `OS`, `ZP`, `IM`, `IGDS`, `ME`, `NR`,
`BL`, `EP`, `OP`, `TX-E33`, `TX-N33`, `TX-RE`).

| File | Codes present | Approx. occurrence count |
|---|---|---|
| `tests/fixtures/chain-run-sample.json` | `SO`(69), `SI`(17), `BL`(5), `ZR`(3), `ES33`(3), `OS`(3), `IM`(3), `ZP`(3), `NR`(3) | ~109 (9 distinct codes) |
| `tests/fixtures/chain-run-normalization-sample.json` | `SO`(58), `SI`(17), `BL`(5), `ZR`(3), `ES33`(3), `OS`(3), `IM`(3), `ZP`(3), `NR`(3) | ~98 (9 distinct codes) |
| `tests/fixtures/reg2627-representative-v1.json` | `SI`(63) | ~63 (1 code) |
| `tests/fixtures/reg2627-adversarial-v1.json` | `SI`(66) | ~66 (1 code) |
| `tests/fixtures/reg2627-labelled-lines.DRAFT.json` | `SI`(110) | ~110 (1 code) |
| `tests/fixtures/reg2627-labelled-lines.json` | `SI`(18) | ~18 (1 code) |
| `tests/fixtures/documents/fixtures_manifest.json` | `SI`(8) | ~8 (1 code) |
| `tests/fixtures/documents/generate_invoices.py` | `SI` hardcoded for all 8 generated invoices (`vat_group: "SI"`, lines 96/127/159/194/229/267/303/338) | generator script, not a fixture file, but feeds `fixtures_manifest.json` + the 8 `INV-30xx.pdf` fixtures |
| `tests/fixtures/declared-f5-fixture-{a,b,c}.json` | none — these contain only `box_1`..`box_8` declared totals, no VatGroup keys | **not impacted** unless the 8-box F5 structure itself changes under Annex E (Section 1 / 1.21 suggests it shouldn't) |

**Impact assessment:**

- **If Option C is a hard rename** (`SO`→`SR`, `SI`→`TX`, no legacy aliasing):
  all 7 fixture JSON files plus `generate_invoices.py` need updating — roughly
  **472 code-string occurrences** across the reg2627 family alone (63+66+110+
  18+8 = 265 `SI`→`TX` replacements) plus ~207 occurrences across the two
  chain-run fixtures (mixed 9-code set, including the `SO`→`SR` and `SI`→`TX`
  renames plus the `TX-N33`/`TX-RE`/`TX-E33`→`TX-ESS` collision codes if those
  appear — they do not currently appear in any fixture, so the 3 collision
  rows in Section 2d (bucket 3) have **zero existing fixture coverage** to
  migrate, only new coverage to add).
- **If Option C is additive** (new Annex E codes coexist with the current
  18-code set via aliasing in `F5_BOX_MAPPING`/`_STANDARD_VAT_GROUPS`, e.g.
  `SR` and `SO` both route to box_1/box_6): existing fixtures remain valid
  as-is, and only **new** fixtures are needed for the 17 brand-new codes
  (Section 2d buckets 4-8) plus the 3 collision codes (bucket 3).
- Either way, **new fixture coverage is needed for the 17+3 = 20 codes** that
  either don't exist today or need remapped semantics — none of these appear
  in any current fixture.
- `generate_invoices.py`'s hardcoded `"SI"` (used to produce all 8 PDF
  invoice fixtures) is a single edit site but gates regeneration of 8 binary
  PDF fixtures if `SI`'s meaning or string changes.

---

## Section 5 — Reference Script Divergence Cost

Per Section 0 / Section 1, the **only** location subject to the
"audit-not-partner" rule is `scripts/run_baseline_tests.py` (rows 1.7-1.9).
Everything else duplicating the vocabulary (base.md, report/routing.py,
report/sections.py, sg-tax-code-mappings.md) is a direct consumer or
documentation — these need keeping in sync but are not part of the
independent-verification process.

**What must be mirrored in `run_baseline_tests.py` for every vocabulary
change:**

1. `SALES_BOX1/2/3/EXCLUDED`, `PURCHASE_BOX5/7/EXCLUDED` (lines 69-77) — mirror
   of `F5_BOX_MAPPING` (1.1)
2. `STANDARD_RATE_CODES` (line 82) — mirror of `_STANDARD_RATE_SALES` (1.3,
   extended to purchase-side `SI`/`TX`)
3. `E2_ZERO_RATE_CODES` (line 91) — mirror of `_E2_ZERO_RATE_CODES` (1.2)
4. `KNOWN_VATGROUPS` (lines 106-125) — mirror of `_vg_category` (1.6)

**Cost model:** for each of the ~16 directly-mappable codes (14 carryovers +
2 renames, Section 2d bucket 1-2), the edit must be made in **both** the production
location (`sap_b1_server.py`, structures 1.1/1.2/1.3/1.6) **and**
independently re-derived in `run_baseline_tests.py` (structures 1.7-1.9) —
this confirms Section 0's "not 3x, but at least 2x" framing: `_vg_category`
(1.6) is a second *production* consumer (not a reference duplicate), while
`run_baseline_tests.py`'s four structures are the genuine **2x
(production + reference)** cost.

On top of the 2x edit cost, **re-verification** is required: running
`run_baseline_tests.py` against fixtures/live data after the edits and
reconciling any newly-introduced divergences — the same exercise already
performed for the 3 currently-documented intentional divergences (E4
threshold 0.005 vs 0.001; E4 purchase scope SI+IM+IGDS vs SI-only; E4 sales
scope SO+DS vs SO-only, per `run_baseline_tests.py:417-420`'s docstring).
Estimate **0.5-1 day** of dedicated reconciliation on top of the 2x edit
multiplier, assuming no *new* intentional divergences are introduced by the
Annex E vocabulary itself (if the new RC/CA/OVR codes need different
treatment in the reference script — e.g. because the reference script
operates on raw codes without `normalize_vat_group`, line 1.4 — that would
add to this estimate).

The 17+3 = 20 codes in Section 2d buckets 3-8 have **no existing
reference-script logic to diverge from** — they are new additions to both
sides, so their cost is pure 2x-authorship, not 2x-edit-plus-reconciliation.

---

## Section 6 — First-Pass T2.21 Effort Estimate

**This is a first-pass estimate based on this audit's findings and is
explicitly subject to revision** — particularly once (a) T2.21 scoping decides
the additive-vs-hard-rename question from Section 4, and (b) T2.18's scope
extension (Section 3 recommendation 3) is finalized. Section 2's ambiguities
(`NA`, `NG`, `TXNA`, `TX-N33`/`TX-RE`/`TX-E33` collisions, `TXRC-TS`, `TX-ESS`,
`IM-ESS`) are now resolved against the extracted Annex E text (Section 2c);
the numeric changes from that resolution are limited to the `NA`/`TXNA`
scheme-participation addition to T2.18 (+0.5 day, see below) — the other
resolutions were reclassifications within the totals already estimated, per
Section 2d.

| Component | Scope | Estimate |
|---|---|---|
| Core vocabulary expansion | `F5_BOX_MAPPING`, `_vg_category`, `_E2_ZERO_RATE_CODES`, `_STANDARD_RATE_SALES`, `config/loader._STANDARD_VAT_GROUPS` (rows 1.1-1.3, 1.6, 1.17 from Section 1) — add 14 carryovers (incl. `NG`, recognized-but-not-expected), 2 renames, resolve the 3 T2.18-attribution-family collisions (`TX-N33`, `TX-RE`, `TX-E33`→`TX-ESS`), fix `_vg_category`'s `TX-RE`/`ME`/`TX-E33` label drift (Section 0), add the 3 T2.18-attribution partial-`IM` codes (`IM-N33`/`IM-RE`/`IM-ESS`) and the 2 scheme-participation codes (`NA`/`TXNA`), and scaffold the 11 T2.22-deferred codes (CA/RC/OVR-LVG families, Section 2d buckets 5-7) as `custom_vat_groups`/`tax_code_mappings` passthrough targets or "insufficient context" anomalies | 2-3 days |
| `report/routing.py` + `report/sections.py` updates | Extend `_ZERO_RATED_VGS`/`_EXEMPT_VGS`/`_BLOCKED_INPUT_VGS`/`_SR_SALES_VGS` (1.14) and `_BOX_VATGROUPS` + judgment-group literals (1.15-1.16) for new/renamed codes; fix the pre-existing `ZP`-missing-from-`_ZERO_RATED_VGS` drift (Section 0 finding #2) while in the area | 1-1.5 days |
| `system-prompts/base.md` sync | Rewrite "F5 Box Definitions" and "Complete VatGroup Routing Table" (1.11-1.12); fix the `ZP`-missing-from-E2 drift (Section 0 finding #1); broaden `OP`'s description per Section 2c item 9; add guidance for new codes | 1 day |
| Reference script parity | Mirror all updated structures in `run_baseline_tests.py` (1.7-1.9); re-run and reconcile divergences (Section 5) | 1.5-2 days |
| Config/docs sync | `config/clients/example.yaml`, `knowledge-base/sg-tax-code-mappings.md` (1.19-1.20); `audit_bundle/config_redaction.py` allow-list (1.23) if T2.18 adds new fields | 0.5 day |
| Fixture regeneration | 7 JSON fixtures + `generate_invoices.py` (Section 4) — lower bound if additive/aliased, upper bound (~472 occurrences) if hard rename; plus new fixtures for the 20 codes (17 brand-new + 3 collision-remapped, Section 2d) with no current coverage | 1-2 days |
| New test coverage | Config validation for expanded `_STANDARD_VAT_GROUPS`; `normalize_vat_group` passthrough/anomaly tests for the 11 T2.22-deferred codes (Section 2d buckets 5-7); `F5_BOX_MAPPING`/`report/routing.py` unit tests for the 24 T2.21-in-scope codes (buckets 1-4, 8) | 1.5-2.5 days |
| **Subtotal (excl. T2.18)** | | **9-13.5 days (~2-2.5 weeks)** |
| T2.18 (if folded into T2.21, per Section 3 recommendation) | `actively_makes_exempt_supplies` promotion, MES/IGDS/RC-applicability flags, possible CA-applicability flag + RC-flag split (Section 3) — roadmap's original 0.5-1 week estimate, extended scope pushes toward the upper end; **+ AMFT/A3PL/GMS/Discounted-Sales-Price-Scheme participation flags for `NA`/`TXNA`** (Section 2c items 1/3, Section 2d bucket 8) — a small, well-scoped addition | +2.5-4.5 days |
| **Total (incl. T2.18)** | | **~11.5-18 days (~2.5-3.5 weeks, unchanged at this granularity)** |

**Explicitly out of scope for T2.21** (recommend a follow-on task, tentatively
T2.22): genuine transaction-level *detection* logic for the Customer
Accounting family (`SRCA-S`, `SRCA-C`, `TXCA`), the OVR/LVG/marketplace family
(`SRLVG`, `SROVR-RS`, `SROVR-LVG`), and full reverse-charge classification
(`SRRC`, `TXRC-TS`, `TXRC-ESS`, `TXRC-N33`, `TXRC-RE`) — these **11 codes**
(Section 2d buckets 5-7, down from the original audit's 13 — see Section 2d
for the `TX-ESS`/`IM-ESS` reclassification) require new source-document
signals that neither T2.18's client-level flags nor the existing SAP B1 /
`normalize_vat_group` data provide. T2.21 should ship these as "insufficient
data → manual review" anomalies (consistent with the existing "unknown
VatGroup → anomaly" pattern), not as fully automated classifications.

---

## Open Items Requiring IRAS Text Confirmation — RESOLVED (2026-06-12)

All 4 items below (and the 5 additional items raised during T2.20's original
review) are now resolved against the extracted Annex E text (PDF pp. 81-85);
see **Section 2c** for the full resolution of each. Summary:

1. ~~Exact semantics of `NA`, `NG`, `TXNA` and how they differ from each other
   and from `OS`.~~ **Resolved** — Section 2c items 1-3. `NA`/`TXNA` are a
   scheme-participation pair (AMFT/A3PL/GMS/Discounted-Sales-Price-Scheme),
   distinct from `OS`; `NG` is the non-GST-registered-business supply-side
   code, recognized but not expected for AgentAssist's (GST-registered)
   clients.
2. ~~Exact semantics of `TXRC-TS` (the "TS" suffix).~~ **Resolved** — Section
   2c item 4. `TXRC-TS` is the general/base reverse-charge-claimable-input
   code ("TS" likely "Taxable Supplies"), distinct from the
   `TXRC-ESS`/`TXRC-N33`/`TXRC-RE` attribution-specific RC variants.
3. ~~Confirmation that Annex E's `TX-N33` and `TX-RE` carry the box treatments
   assumed in Section 2 (fully-claimable input for `TX-N33`; residual/
   apportioned input for `TX-RE`).~~ **Confirmed** — Section 2c items 5-6. Both
   assumptions were correct; both are genuine collisions with the current
   codes of the same name (opposite/flipped box treatment).
4. ~~Whether `TX-E33`'s current meaning has any Annex E representation at all,
   or should be retired/folded into `EP`.~~ **Resolved** — Section 2c item 8.
   `TX-E33` maps to `TX-ESS` ("Standard-rated purchases directly attributable
   to Regulation 33 exempt supplies") — a third collision in the
   T2.18-attribution family, not an orphan and not folded into `EP`.

**Additionally resolved** (corrections to the original draft, not in the
original 4-item list): `TX-ESS`/`IM-ESS`'s "ESS" suffix means "Regulation 33
Exempt Supplies", not "Imported Services" (Section 2c item 7); `OP`'s Annex E
description is broader than the current label but does not change box
treatment (item 9); and Annex E lists a second, unrelated `NR` code for
purchases made by non-GST-registered businesses (N/A to AgentAssist, see the
"additional finding" at the end of Section 2c).
