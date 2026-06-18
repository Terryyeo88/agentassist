# Check → canonical-field map (T2.12 recon)

**Status:** verified against source 2026-06-18 (branch `t2.12-coverage-fieldmap-recon`, off
`origin/master` @ `6d759c4`). Read-only discovery — NO code/test/chain change.

**Provenance note:** the task framed this as *verifying an existing draft* at
`exploration-notes/check-canonical-field-map.md`. **No such draft existed** in any branch,
in working trees, or under any variant name (searched 2026-06-18). This document is therefore
**authored from source**, not corrected from a draft; every cell carries a `file:line`
citation and the Recon change-log lists each as `AUTHORED (source)`.

This is the single source of truth for (a) the Task-2 coverage extension and (b) the adapter
normalization contract. Every field below is what the **detection code** actually reads — not
the registry prose.

---

## A. Check enumeration (14 checks)

Confirmed: `agent/registry.py` `CHECK_REGISTRY` holds exactly 14 `CheckSpec` entries
(`agent/registry.py:187-379`). Each maps to live detection code; no orchestrator check is
missing from the registry and no registry check is orphaned.

| # | check_id | Detection site (file:line) | finding_type | registry inputs_needed |
|---|----------|----------------------------|--------------|------------------------|
| 1 | E1 | `mcp-servers/custom/sap_b1_server.py:787` (`_classify_line`) | deterministic | sales_invoices, vat_group_mapping |
| 2 | E2 | `sap_b1_server.py:793` | deterministic | sales_invoices, purchase_invoices, vat_group_mapping |
| 3 | E3 | `sap_b1_server.py:798,801` | deterministic | sales_invoices, purchase_invoices, vat_group_mapping |
| 4 | E4 | `sap_b1_server.py:806` | deterministic | sales_invoices, purchase_invoices, applicable_gst_rate |
| 5 | NO_GST_REG | `sap_b1_server.py:1461-1492` (`detect_gst_errors`) | deterministic | purchase_invoices, supplier_catalog |
| 6 | COMPLETENESS | `sap_b1_server.py:1431-1446` | deterministic | invoice_counts, completeness_threshold |
| 7 | SEQ_GAP | `orchestrator/check_listing.py:63` (`detect_seq_gaps`) | deterministic | sales_invoices, all_period_invoices |
| 8 | DUP_CLAIM | `orchestrator/check_listing.py:167` (`detect_dup_claims`) | deterministic | purchase_invoices |
| 9 | declared_A | `orchestrator/check_declared_f5.py:384` (`run_declared_f5_checks`) | deterministic | declared_f5 |
| 10 | declared_B | `orchestrator/check_declared_f5.py:384` | deterministic | declared_f5, computed_boxes |
| 11 | gst_amount_mismatch | `documents/reconcile.py:124-145` | probabilistic | document_pdfs, sap_listing |
| 12 | correct_period | `documents/reconcile.py:147-166` | probabilistic | document_pdfs, sap_listing |
| 13 | total_inconsistency | `documents/reconcile.py:168-179+` | probabilistic | document_pdfs |
| 14 | reg11_supplier_gst_absent | `documents/reconcile.py` (reg11 branch) | probabilistic | document_pdfs |

Notes:
- E1's registry `inputs_needed` omits `purchase_invoices`; correct — E1 fires on **sales**
  lines only (`entity_type == "sales"`, `sap_b1_server.py:787`).
- E2/E3 registry lists `purchase_invoices` because the same `detect_gst_errors` pass classifies
  purchase lines (`sap_b1_server.py:1407-1409`); E3 has an explicit purchase-TX branch
  (`sap_b1_server.py:801`), E2's code set includes purchase codes (BL/NR/ZP/IM-side).
- The four document checks share one **T2.8 pre-pass** (`documents/doc_pass.py`
  `run_documents_pass`), gated in `engine/review.py:230-235` on `inputs.provider is not None`.
  Registry `inputs_needed` is at **pre-pass granularity**; per-check actual reads are in §B.

---

## B. Canonical fields each check consumes (from detection code)

Canonical record shapes are the projections in `feeders/extract_schema.py:144-209` — the same
shapes `SapChainReader` yields. Field names below are the canonical (post-projection) names.

### E1 — FX standard-rated sales (`sap_b1_server.py:786-789`)
| Field | Surface | Read at | Notes |
|-------|---------|---------|-------|
| VatGroup | doc line | `:767-768` | normalized via `normalize_vat_group`; fires when ∈ `{SR, DS}` (`_STANDARD_RATE_SALES`, `:384`) |
| DocCurrency | document | `:771` | drives `is_fx` (`:773`); FX = currency ∉ `{SGD, S$, ""}` |
| DocNum, DocDate, CardName | document | `:776-783` | finding identity (base dict) |

**E1 FX path / DocCurrency-absent behaviour (recon question):** `:771`
`currency = (doc.get("DocCurrency") or "SGD").strip().upper()`. **If `DocCurrency` is absent
or empty/None → defaults to `"SGD"` → `is_fx = False` (`:773`) → E1 silently CANNOT fire**
(document treated as domestic; no error, no caveat). This is a silent-miss surface: an export
that omits `DocCurrency` suppresses E1 without any signal. (`DocCurrency` IS in the canonical
set and IS mappable from an export — see §C — so coverage extension can flag it.)

### E2 — GST charged on non-taxable supply (`sap_b1_server.py:791-795`)
| Field | Surface | Read at | Notes |
|-------|---------|---------|-------|
| TaxTotal | doc line | `:770,793` | fires when `> 0.01` |
| VatGroup | doc line | `:767-768,793` | fires when ∈ `{ZR, OS, ES33, ESN33, BL, NR, ZP}` (`_E2_ZERO_RATE_CODES`, `:382`) |
| DocNum, DocDate, CardName | document | base dict | finding identity |

### E3 — standard-rated line with zero tax (`sap_b1_server.py:797-803`)
| Field | Surface | Read at | Notes |
|-------|---------|---------|-------|
| VatGroup | doc line | `:798,801` | sales: ∈ `{SR,DS}`; purchase: `== TX` |
| LineTotal | doc line | `:769,798,801` | fires when `> 0.01` |
| TaxTotal | doc line | `:770,798,801` | fires when `< 0.01` |
| entity_type | (call arg) | `:798,801` | sales vs purchase branch |

### E4 — GST rate deviation (`sap_b1_server.py:805-811`)
| Field | Surface | Read at | Notes |
|-------|---------|---------|-------|
| VatGroup | doc line | `:806` | only `{SR, TX}` |
| LineTotal, TaxTotal | doc line | `:806-807` | ratio = TaxTotal/LineTotal |
| expected_rate | (call arg) | `:806,809` | default 0.07; deviation tol 0.001 |

### NO_GST_REG — input tax from unregistered supplier (`sap_b1_server.py:1461-1492`)
| Field | Surface | Read at | Notes |
|-------|---------|---------|-------|
| FederalTaxID | BusinessPartner (S3) | `:1476` via `reader.get_business_partner` `:1475` | LOAD-BEARING; blank/None → flagged |
| CardCode | purchase doc | `:1467` | dedup key; one finding per supplier |
| TaxTotal | doc line | `:1470` | `has_input_tax` precondition (`> 0.01`) |
| DocNum, DocDate, CardName | purchase doc | `:1484-1486` | finding identity |

Covers purchase invoices **and** purchase credit notes (`:1462`). **Coverage gate:** the
entire NO_GST_REG loop is skipped (empty doc list) unless
`_reader_field_covered(reader, "business_partners", "FederalTaxID")` is True (`:1461-1465`) —
when the surface is declared unavailable the check does **not** run a degraded variant; it
emits nothing and the chain surfaces the caveat (§E).

### COMPLETENESS — purchase volume vs sales volume (`sap_b1_server.py:1430-1446`)
| Field | Surface | Read at | Notes |
|-------|---------|---------|-------|
| `len(invoices)` (sales count) | fetched records | `:1431` | NOT `@odata.count` |
| `len(purchases)` (purchase count) | fetched records | `:1432` | NOT `@odata.count` |
| threshold `0.1` | hardcoded | `:1434` | NOT a config key despite registry `completeness_threshold` |

**`invoice_counts` (recon question):** the count is the **fetched record count**
(`len(invoices)`, `len(purchases)`), NOT the SAP `@odata.count` inline probe. Fires when
`sales_count > 0 and purchase_count / sales_count < 0.1`. Period-level finding:
`doc_num/doc_date/card_name = None` (`:1438-1440`).

**Gate-1 `@odata.count` dormancy (recon question):** the inline-count probe is
`SapChainReader.count` at **`sap_b1_server.py:676-695`** (relocated from `orchestrator/steps.py`;
`steps.py:142` only *calls* `reader.count`). Line **`690`** reads
`count_resp.get("odata.count")` — **no `@` prefix** — while the v2 Service Layer returns the
total under `@odata.count` (with `@`). The probe therefore yields `None`, and **Gate 1
warn-passes unconditionally** (`orchestrator/gates.py:50-83`, `orchestrator/steps.py:403`,
`orchestrator/chain.py:198-202`). Preserved deliberately (backlog #5, frozen-oracle contract,
`sap_b1_server.py:678-681`). This dormancy is INDEPENDENT of the COMPLETENESS check, which
uses fetched counts and is unaffected.

### SEQ_GAP — sequence gap (`orchestrator/check_listing.py:63-160`)
| Field | Surface | Read at | Notes |
|-------|---------|---------|-------|
| DocNum (int) | listing header | `:111,123` | gap candidate value |
| Series (int) | listing header | `:112,114,124` | per-series range |
| Cancelled (str) | listing header | `:121` via `_is_cancelled` `:55` | non-cancelled defines period range |

**Two-arg, company-wide:** `detect_seq_gaps(period_records, all_records)` (`:63-66`). `all_records`
is the company-wide population across ALL periods/statuses (`:106-116`); a DocNum present there
is never a gap (`:141`). Range comes from period **active** (non-cancelled) docs (`:118-129`).

### DUP_CLAIM — duplicate input-tax claim (`orchestrator/check_listing.py:167-244`)
| Field | Surface | Read at | Notes |
|-------|---------|---------|-------|
| CardCode (str) | purchase listing | `:213,216` | part of dedup key |
| NumAtCard (str) | purchase listing | `:208,216` | part of key; **blank/None → row SKIPPED** (`:209-210`) |
| DocTotal (float) | purchase listing | `:214,216` | part of key; `round(...,2)` |
| DocNum (int) | purchase listing | `:212` | reported (occurrence + `duplicate_of`) |

**Key = `(CardCode, NumAtCard, DocTotal)`** (`:216`). Confirmed.

### declared_A / declared_B (`orchestrator/check_declared_f5.py:384`)
| Field | Surface | Read at | Notes |
|-------|---------|---------|-------|
| declared_f5 (dict) | input file `declared-f5.json` | `load_declared_f5` `:47` | A: internal consistency Box4/Box8 |
| computed_boxes (dict) | chain `calculate` output | passed by chain | B: declared-vs-computed, 6 independent boxes (`:73-75`) |

**Off-by-default (recon question):** both run only when a `declared_f5` dict is supplied —
`orchestrator/chain.py:259` `if declared_f5 is not None:` → `run_declared_f5_checks`
(`chain.py:260`). Default `ReviewInputs.declared_f5 = None` (`engine/review.py:115`); default
`declared_f5_findings: []` (`orchestrator/steps.py:423`). Tolerance default `1.00`/box,
configurable in the input file (`check_declared_f5.py:67`).

### Document checks (T2.8 pre-pass) — per-check reads (`documents/reconcile.py`)
The pre-pass pairs each ingested PDF (`extracted: ExtractedInvoice`) with a SAP listing line
(`line_item`, from `reasoning/sap_lines`); `doc_num` comes from `line_item` (`:101`), so the
**SAP listing is required for pairing** in all four, even where the comparison itself is
PDF-internal.

| check_id | PDF field(s) read | SAP-listing field read | Read at |
|----------|-------------------|------------------------|---------|
| gst_amount_mismatch | `extracted.gst_amount` | `line_item["tax_total"]` | `:128-145` |
| correct_period | `extracted.invoice_date` | (period bounds; listing only for pairing) | `:152-166` |
| total_inconsistency | `total_excl_gst` + `gst_amount` vs `total_incl_gst` | none (PDF-internal) | `:172-179+` |
| reg11_supplier_gst_absent | supplier GST reg-no on PDF face | none (PDF-internal) | reg11 branch |

All emit `DocumentCandidate` (`documents/reconcile.py:62-72`): `doc_num, check_id, severity,
message, extracted_value, listing_value, extraction_source, determinability,
validation_status="unvalidated"`.

---

## C. Canonical field set + mappability (`feeders/extract_schema.py`)

The canonical set the checking core consumes (`extract_schema.py:9-19`, projections `:144-209`):

- **doc line** (`project_line` `:144`): `VatGroup`, `LineTotal`, `TaxTotal`
- **document** (`project_document` `:153`): `DocNum`, `DocDate`, `CardCode`, `CardName`,
  `DocCurrency`, `DocTotal`, `DocumentLines` (+ `is_credit_note` tag)
- **BusinessPartner** (`project_business_partner` `:176`): `CardCode`, `FederalTaxID`
- **listing min** (`project_listing_sales` `:187`): `DocNum`, `Series`, `Cancelled`
- **listing period-purch** (`project_listing_period_purch` `:200`): + `CardCode`, `NumAtCard`,
  `DocTotal`

**Mappability of the five recon-flagged fields** (export column → canonical, `:100-114`):

| Field | Mapped from export? | Sheet / column | Coercer |
|-------|---------------------|----------------|---------|
| Series | YES | `listing` / `Series` (`:113`) | `to_int` (`:191,204`) |
| Cancelled | YES | `listing` / `Cancelled` (`:113`) | `to_str` (`:192,205`) |
| NumAtCard | YES | `listing` / `NumAtCard` (`:113`) | `to_opt_str` (`:207`) — preserves None |
| DocCurrency | YES | `documents` / `DocCurrency` (`:102`) | `to_str` (`:164`) |
| FederalTaxID | YES | `business_partners` / `FederalTaxID` (`:107`) | `to_opt_str` (`:183`) — preserves None |

All five are present in the canonical set and mappable from an export.

---

## D. Oracle / fixture presence (`tests/fixtures/sbodemosg-extract/`)

Frozen verbatim per `capture-manifest.json` (period 2024-07-01…2024-09-30, SBODEMOSG):

| Surface | Fixture | Records |
|---------|---------|---------|
| S0 (inline count) | `inline-counts.json` | Invoices 50, PurchaseInvoices 34, CreditNotes 1, PurchaseCreditNotes 1 |
| S1 (line-level) | `invoices.raw.json` / `purchase-invoices.raw.json` | 50 / 34 |
| S2 (credit notes) | `credit-notes.raw.json` / `purchase-credit-notes.raw.json` | 1 / 1 |
| S3 (BP master) | `business-partners.raw.json` | 9 (V10000…V70000) |
| S5 (listing headers) | `listing-headers.json` | period_sales 50, period_purch 34, all_sales 1005, all_purch 624 |
| (reasoning) | `si-purchase-lines.json` | 61 |
| (oracle) | `_replay-oracle.compiled.json` | compiled CompileOutput + gate_results |

**S0 caveat:** `inline-counts.json` stores the count under the `@odata.count` key (the `@`-prefix),
which the production reader does NOT read (`:690`) → dormant → Gate 1 warn-passes (see §B).

**NumAtCard 0% populated (recon question):** CONFIRMED. Of 34 `NumAtCard` occurrences in both
`purchase-invoices.raw.json` and `listing-headers.json` (period_purch), **0 are non-empty**
(all `None`). DUP_CLAIM therefore returns empty findings on SBODEMOSG and reads `degraded`
under the extract feeder (§E).

---

## E. Coverage status today (T2.12 slice 2B)

Code: `feeders/coverage_status.py` (`derive_coverage_statuses` `:70-103`) + the seam
`feeders/extract_reader.py:233-244` (`coverage_status`), surfaced into the chain DUCK-TYPED at
`orchestrator/chain.py:310-329` (`_emit_check_coverage` → `result["check_coverage"]`).

Exactly **three** `CoverageStatus` entries are emitted (one per in-scope check). Levels:
`full` / `degraded(reason)` / `unavailable` (`coverage_status.py:29-31`); a non-`full` MUST
carry a non-empty reason, `full` carries none (`:49-55`).

| Check | Coverage signal | `full` when | non-`full` level | exact reason string |
|-------|-----------------|-------------|------------------|---------------------|
| DUP_CLAIM | `(listing, NumAtCard)` `is_covered` (present **AND** populated) | `coverage.is_covered(LISTING_SHEET, "NumAtCard")` (`:86`) | `degraded` (`:89`) | `"NumAtCard absent or unpopulated — DUP_CLAIM under-detects."` (`:63`) |
| NO_GST_REG | `(business_partners, FederalTaxID)` `is_covered` | `coverage.is_covered(BUSINESS_PARTNERS_SHEET, "FederalTaxID")` (`:92`) | `unavailable` (`:95`) | `"FederalTaxID absent — NO_GST_REG cannot run; require supplier-master sheet at onboarding."` (`:64-66`) |
| SEQ_GAP | company-wide population present | `company_wide_population_present` = `bool(all_sales_headers)` (`extract_reader.py:241`, used `:98`) | `degraded` (`:101`) | `"company-wide document population absent — SEQ_GAP limited to within-period."` (`:67`) |

- `is_covered` is **value-aware**: present-AND-populated (`extract_reader.py:75-82`). A
  present-but-0%-populated column (e.g. NumAtCard in SBODEMOSG) is NOT covered → `degraded`.
- SEQ_GAP's signal is NOT a `COVERAGE_FIELDS` (surface,field) entry — it's the presence of any
  `all`-scope sales rows (`extract_reader.py:241`), the surface `detect_seq_gaps` needs to tell
  "issued in another period" from "never issued anywhere".
- **Everything else is implicit-full**: only these three are derived (`:83-103`). The other 11
  checks emit no coverage status (no key). `check_coverage` is absent entirely on readers
  without the seam — live `SapChainReader` and frozen replay (`chain.py:318-324`) — so those
  paths stay byte-identical.

---

## F. The DocTotal collision — REFUTED in current source

Draft hypothesis (item #6): `COVERAGE_FIELDS` is keyed by field NAME only and cannot represent
the same field on two surfaces (per-doc DocTotal vs listing DocTotal).

**REFUTED as a current risk.** `COVERAGE_FIELDS` is keyed by a **`(surface, field)` tuple**, not
a bare field name (`feeders/extract_schema.py:234-253`). The two DocTotal surfaces are DISTINCT
entries:
- `(DOCUMENTS_SHEET, "DocTotal")` → doc-level, FX-conversion advisory (`:246`)
- `(LISTING_SHEET, "DocTotal")` → DUP_CLAIM key (`:252`)

The code comment (`:226-231`) documents the bare-field key as the **prior** shape that silently
collapsed the two DocTotal surfaces (Gap A) and records that the `(surface, field)` key was
adopted to keep them distinct. `ExtractCoverage.fields`/`populated` are likewise `(surface,
field)`-keyed (`extract_reader.py:41-82`). So the collision was a real historical bug, **already
fixed**; no shape-risk remains in current source. (Flag for Terry: resolved — no action.)

---

## G. Import invariant (adapter-contract relevant)

CONFIRMED: `orchestrator/` and `report/` import **nothing** from `feeders/`. A repo grep finds
only *comments* referencing feeders in those trees (`orchestrator/chain.py:286,313,316`,
`orchestrator/schemas.py:402`) — no `from feeders` / `import feeders` statements. The coverage
status is read **duck-typed** via `getattr(reader, "coverage_status", None)`
(`orchestrator/chain.py:322`), so the emitter is structural, not an import dependency. `feeders`
is a leaf (imports nothing upward, `coverage_status.py:20`).

---

## Recon change-log

No prior draft existed (see Provenance note), so every entry is `AUTHORED (source)` — there were
no pre-existing cells to correct. Citations are the authoritative source for each claim.

| § / cell | Value | Justified by |
|----------|-------|--------------|
| A. 14-check enumeration | AUTHORED (source) — 14 `CheckSpec`, all live, no orphans | `agent/registry.py:187-379` |
| A. E1 inputs (sales-only) | AUTHORED — E1 fires on sales lines only | `sap_b1_server.py:787` |
| B. E1 reads VatGroup/DocCurrency/identity | AUTHORED | `sap_b1_server.py:767-789` |
| B. **E1 DocCurrency-absent → SGD → silent miss** | AUTHORED — defaults `"SGD"`, `is_fx=False`, E1 cannot fire | `sap_b1_server.py:771-773,787` |
| B. E2 codes/TaxTotal | AUTHORED | `sap_b1_server.py:382,791-795` |
| B. E3 sales+purchase branches | AUTHORED | `sap_b1_server.py:384,797-803` |
| B. E4 SR/TX + rate | AUTHORED | `sap_b1_server.py:805-811` |
| B. NO_GST_REG ← FederalTaxID + gate | AUTHORED — `get_business_partner`, coverage-gated | `sap_b1_server.py:1461-1492` |
| B. **COMPLETENESS = fetched counts, not @odata.count; threshold hardcoded** | AUTHORED | `sap_b1_server.py:1431-1434` |
| B. **Gate-1 dormancy at `count()` reading `odata.count` (no @)** | AUTHORED — in `sap_b1_server.py:690`, not steps.py | `sap_b1_server.py:676-695`; `steps.py:142,403`; `gates.py:50-83` |
| B. SEQ_GAP two-arg company-wide; DocNum/Series/Cancelled | AUTHORED | `check_listing.py:63-160` |
| B. DUP_CLAIM key `(CardCode,NumAtCard,DocTotal)`; blank NumAtCard skipped | AUTHORED | `check_listing.py:208-217` |
| B. declared_A/B inputs + **off-by-default** | AUTHORED — `if declared_f5 is not None` | `chain.py:259-260`; `review.py:115`; `steps.py:423` |
| B. 4 document checks per-check reads via T2.8 pre-pass (document_pdfs + sap_listing) | AUTHORED | `documents/reconcile.py:79-179`; `doc_pass.py`; `review.py:230-235` |
| C. canonical field set | AUTHORED | `extract_schema.py:144-209` |
| C. Series/Cancelled/NumAtCard/DocCurrency/FederalTaxID all mappable | AUTHORED | `extract_schema.py:100-114,164,183,191-208` |
| D. frozen surfaces S0/S1/S2/S3/S5 | AUTHORED | `tests/fixtures/sbodemosg-extract/capture-manifest.json` |
| D. **NumAtCard 0% populated (34/34 None)** | AUTHORED — counted in fixtures | `purchase-invoices.raw.json`, `listing-headers.json` |
| E. 3 emitted CoverageStatus + exact strings | AUTHORED | `coverage_status.py:63-103`; `extract_reader.py:233-244`; `chain.py:310-329` |
| E. everything else implicit-full | AUTHORED — only 3 derived | `coverage_status.py:83-103` |
| F. **DocTotal collision REFUTED — `(surface,field)` keyed** | AUTHORED — distinct entries `:246`/`:252` | `extract_schema.py:234-253`; `extract_reader.py:41-82` |
| G. orchestrator/report import nothing from feeders (duck-typed) | AUTHORED | grep clean; `chain.py:322` |
