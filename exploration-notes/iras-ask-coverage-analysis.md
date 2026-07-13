# AgentAssist — IRAS ASK Coverage Analysis

*Coverage gap analysis, findings-to-template mapping, and deterministic-vs-judgment matrix for AgentAssist's GST compliance detection, benchmarked against the IRAS Assisted Self-Help Kit (ASK) Annual Review methodology.*

**Sources (IRAS only):** GST: Assisted Self-Help Kit (ASK) Annual Review Guide (`gst_askannualreviewguide.pdf`), incl. the 5-step process (§9), Steps 1–5, Appendix 1 "List of Errors and Areas where Error may Occur" (p.72–74), and the Step 3 substantive-test legends (p.80); ASK Templates 1–7; IRAS e-Tax Guide "How do I prepare my GST return?" (Eleventh Edition, 30 Jan 2026); `sg-tax-code-mappings.md`.

**AgentAssist detection layer (definitions per `AGENTASSIST_TECHNICAL_STATE.md`, authoritative):** three read-only Python MCP tools against SAP B1 Service Layer —
- `calculate_f5_return(period_start, period_end)` — F5 boxes 1–8 from invoice + credit-note line items; FX invoices excluded from box totals and listed separately; credit notes subtracted; NR excluded from Box 5; flags E1 candidates and unknown-VatGroup anomalies.
- `validate_invoice_tax_codes(period_start, period_end, expected_rate=0.07)` — per-line E1–E4 checks across invoices + credit notes; returns a `vatgroup_inventory`.
- `detect_gst_errors(period_start, period_end, expected_rate=0.07)` — E1–E4 + COMPLETENESS + NO_GST_REG, severity-sorted.

**Error codes (locked to the tool code):** E1 = FX sale coded local standard-rated (SR/DS); E2 = GST charged on a non-taxable supply (TaxTotal>0 with ZR/OS/ES33/ESN33/BL/NR); E3 = standard-rated line carrying zero tax (SR/DS sales or TX purchases); E4 = rate deviation within {SR, TX}; NO_GST_REG = purchase with input tax but supplier `FederalTaxID` blank; COMPLETENESS = purchase/sales count ratio < 0.1.

**Scope caveat:** AgentAssist has been validated only on the SBODEMOSG demo database. Production data may contain custom VatGroups, partial-exemption scenarios, manual journals, and scheme-specific imports not yet handled. This analysis describes designed/validated capability, not production-proven behaviour. AgentAssist performs *post-submission* transaction review, which corresponds to the ASK Annual Review Steps 3A–3E substantive testing rather than the pre-submission Pre-Filing Checklist.

---

# Document 1 — Coverage Gap Analysis (by ASK step)

**Legend:** ✓ Full — a tool produces exactly the check IRAS describes · ◐ Partial — covers part; missing piece stated · ✗ Gap — needs new tool/extension · 👤 Human-only — requires accountant judgment or physical source documents (correctly not automatable).

## Step 1 — Review your GST Declarations for a Financial Year (Guide §Step 1; Template 1)

Analytical review across the financial year's filed returns. AgentAssist computes the underlying figures from SAP transactions but does **not** retrieve the *filed* F5 returns (the guide's Step 1.1 uses the IRAS e-Service "Retrieve Past GST Returns/Assessments for ASK Review"), so "declared vs computed" comparisons require the filed return as a second input AgentAssist does not currently ingest.

| ASK check (¶) | What it requires | Coverage | AgentAssist function | What's missing |
|---|---|---|---|---|
| 1.3a — Major fluctuations in SR/ZR/exempt supplies & taxable purchases across the year | Period-over-period comparison of Boxes 1/2/3/5 | ◐ | `calculate_f5_return` per period; T2.17 `detect_period_fluctuations()` in `check_period_fluctuation.py` | **BUILT + DEMO-VALIDATED (T2.17, 2026-06-11)** — QoQ movements in Boxes 1/2/3/5 detected; renders when `--analytical-review` supplied; all-zero quarters excluded. **Surfacing threshold ±50% is NOT IRAS-defined** (IRAS §Step 1.3a gives no number; 50% is a non-regulatory tuning parameter). NOT real-client validated. Business-cycle vs error assessment is 👤. |
| 1.3b — Declared vs computed output tax (flag if diff ≤ −$10,000) | Computed Box 6 vs *declared* Box 6 | ◐ | `calculate_f5_return` computes Box 6; T2.9 `check_declared_f5.py` Check B ingests declared Box 6 via `--declared-f5` flag | **MECHANISM VALIDATED ON DEMO (T2.9-V, 2026-06-10)** — Check B confirmed end-to-end on SBODEMOSG Q3 2024 (Fixtures A/B/C, 22 assertions, box-isolation held). Renders findings when `--declared-f5` supplied with divergences; Section 6 retains placeholder otherwise. **Rounding/tolerance convention still unconfirmed vs IRAS source**: $1.00 per-box tolerance is a materiality floor per ASK Guide s10.1(d)(iii) fn33 — NOT a confirmed IRAS F5 filing convention. A surfaced divergence is a candidate for reviewer attention, not a confirmed discrepancy. Coverage cell stays ◐ — not unconditionally covered. |
| 1.3c — Declared vs computed input tax (flag if diff significant) | Computed Box 7 vs *declared* Box 7 | ◐ | `calculate_f5_return` computes Box 7; T2.9 `check_declared_f5.py` Check B ingests declared Box 7 via `--declared-f5` flag | **MECHANISM VALIDATED ON DEMO (T2.9-V, 2026-06-10)** — same as 1.3b. Check B confirmed end-to-end; renders findings when `--declared-f5` supplied with divergences; Section 6 retains placeholder otherwise. Rounding/tolerance convention still unconfirmed; coverage cell stays ◐ — not unconditionally covered. |
| 1.3d — TP/TS ratio > 1.2 evaluation | Box 5 ÷ Box 4 | ◐ | Both boxes computed by `calculate_f5_return`; T2.16 `run_analytical_review_pass()` in `check_analytical_review.py` | **BUILT + DEMO-VALIDATED (T2.16, 2026-06-11)** — TP/TS ratio (Box 5 ÷ Box 4) computed over FY; >1.2 flag-fire validated via crafted input; renders when `--analytical-review` supplied. **RC/OVR approximation caveat:** IRAS defines Total Supplies to exclude Boxes 14–16 (not computed by AgentAssist) — ratio is approximate for RC/OVR clients. NOT real-client validated. Reasonableness assessment is 👤. |
| 1.3e — GST control-account ledger ↔ F5-report reconciliation + manual-journal catch | The GST control-account ledger + the F5 report (distinct from 1.3b/1.3c, which are computed-vs-*declared*; this is ledger-vs-report) | ◐ | **BUILT — T2.24 PR-1 (Signal A) + PR-2 (Signal B + `parse_declared_return`, CLI end-to-end) + PR-3 (PDF/report surface):** `orchestrator/check_gst_ledger_recon.py` (pure; adds `run_not_included_checks` in PR-2) + `feeders/xero_ledger_reader.py::load_gst_ledger` (side-input loader, NOT a ChainReader) + `feeders/xero_f5_reader.py::parse_declared_return` / `parse_not_included` (PR-2 product parsers), wired via the optional `gst_ledger` seam in `orchestrator/chain.py` and runnable via `run_agent.py --gst-ledger / --xero-f5`; PR-3 renders it via `report/sections.py::build_ledger_recon_section` + `report/render.py::render_ledger_recon_section`/`_ledger_recon` + optional `report/report.py::ReportModel.ledger_recon` + a Section-6 NOT_EXAMINED line in `report/constants.py` | **BUILT (T2.24 PR-1 Signal A + PR-2 + PR-3) — candidate-not-verdict, findings-never-gates.** The ledger-vs-declared-return mechanism runs **END-TO-END on the CLI**: PR-2's `parse_declared_return` reads declared Box 6/Box 7 off the Xero **Return** sheet and **retires PR-1's caller-supplied-boxes ceiling** (`run_agent.py --gst-ledger / --xero-f5`, `--period` authoritative with a period-consistency guard). PR-2 also adds **Signal B** (`parse_not_included` + `run_not_included_checks` — the control-account **raw-GL drop** surface from the F5 *"Transactions not included"* section) as an optional additive `not_included_findings` key. **PR-3 makes the recon REVIEWER-VISIBLE on the signed PDF working paper**: Signal A + B now **RENDER** (three-state per-signal mirroring the T2.10 listing model, **empty-string-when-empty — no fabricated all-clear**), coordinated with a Section-6 NOT_EXAMINED line (**suppressed when the recon was performed, present when it was never run** — both directions tested). Descriptions render **verbatim from the checks** in candidate framing (surfaces-never-asserts at the render layer). PR-3 is **ADDITIVE to the sealed artifact** — `compile_output` shape untouched, offline-replay oracle byte-identical (no re-freeze), BOX-ISOLATION untouched (render-only). PR-2/PR-3 are **strictly ADDITIVE** (reader byte-identical, count-pins unchanged). **Coverage stays ◐ PARTIAL, NOT full** — the **API upload endpoint + review-screen queue surface is PR-4** (not yet done). **Step-mapping stays PROPOSED — confirm against the ASK Annual Review Guide before treating as the anchor** (may sit under **Step 4** books-vs-return as much as Step 1). This is an **INTERNAL-CONSISTENCY check, NOT accuracy validation** — a consistently-wrong tax code is invisible to it. **Prerequisite (verify-before-encode) — SATISFIED:** the manual-journal-drops-from-Xero-F5 behaviour has been reproduced from a real-FORMAT Xero export and **frozen as a fixture** (real-FORMAT over SYNTHETIC content, NOT real-client-export-validated; cross-ref `operational-backlog.md` #10). **T2.11 remains the binding customer-facing gate.** Surfaces a candidate, never asserts. |

## Step 2 — Select GST Return(s) for Review (Guide §9)

Procedural step: choose which filed return(s) to subject to substantive testing. This is a scoping decision, not a data check.

| ASK check | Coverage | Notes |
|---|---|---|
| Selection of return(s) for substantive review | 👤 | A reviewer-scoping decision. AgentAssist runs against whatever period it is given; it does not decide which return warrants review. Correctly human-owned. |

## Step 3A — Check Standard-rated Supplies and Output Tax (Guide §Step 3A; Template 2)

| ASK check (¶) | What it requires | Coverage | AgentAssist function | What's missing |
|---|---|---|---|---|
| 3A.1.a — Listing tallies to Boxes 1, 6 (and 14/15/16/17 where applicable) | Sum SR lines = declared box values | ◐ | `calculate_f5_return` (Box 1, 6); T2.9 Check B provides declared-vs-computed for Box 1 and Box 6 | Computes the listing total; T2.9 adds declared reconciliation (**MECHANISM VALIDATED ON DEMO, T2.9-V 2026-06-10** — flag-gated; renders findings when `--declared-f5` supplied with divergences). Rounding/tolerance convention still unconfirmed; a surfaced divergence is a candidate, not a confirmed discrepancy. Boxes 14–17 (RC/OVR/LVG) not computed. Coverage cell stays ◐ — not unconditionally covered. |
| 3A.1.b — Time-of-supply compliance (earlier of invoice issued / payment received) | Invoice date vs payment date | ✗ / 👤 | — | No payment-date ingestion; time-of-supply is a documentary judgment |
| 3A.1.c — Missing invoice numbers in listing | Sequence-gap analysis | ✗ | — | Not implemented; feasible as a future extension over `DocNum` sequences |
| 3A.1.d — Transactions reducing sales recorded via valid credit/debit notes | Credit/debit-note linkage | ◐ | `calculate_f5_return` / `validate_invoice_tax_codes` (credit notes fetched & subtracted; CN lines classified) | Subtraction is handled; matching a CN to its original invoice and confirming single-use is not |
| Detection of FX sales miscoded as local standard-rated (relates to 3A.1.k "correct GST treatment") | FX + SR/DS line detection | ✓ | E1 in `validate_invoice_tax_codes` / `detect_gst_errors`; E1 candidates in `calculate_f5_return` | — |
| Output GST charged at the correct rate / zero-tax on standard-rated lines (3A.3.1.i) | Per-line rate validation | ✓ | E3 (zero tax on SR/DS) and E4 (rate deviation on SR) | E4 needs the correct `expected_rate` per period (config) |
| 3A.1.e–j, l–m — Customer accounting; EM-operator remote services; OVR/LVG; reverse-charge output tax | Scheme-specific output-tax treatment | ✗ / 👤 | — | Boxes 14–17 and customer-accounting/RC/OVR logic not implemented; largely out of scope for a typical SME |
| 3A.3 — Source-document checks on sampled transactions (valid tax invoice, GST in SGD, amounts agree to listing) | Inspect physical tax invoices | 👤 | — | Requires the source documents; AgentAssist can supply the population the sample is drawn from |

## Step 3B — Check Zero-rated Supplies (Guide §Step 3B; Template 3)

| ASK check (¶) | What it requires | Coverage | AgentAssist function | What's missing |
|---|---|---|---|---|
| 3B.1.a — Listing tallies to Box 2 | Sum ZR lines = declared Box 2 | ◐ | `calculate_f5_return` (Box 2); T2.9 Check B provides declared-vs-computed for Box 2 | Reconciliation to declared figure: T2.9 adds declared Check B (**MECHANISM VALIDATED ON DEMO, T2.9-V 2026-06-10** — flag-gated; renders findings when `--declared-f5` supplied with divergences). Rounding/tolerance convention still unconfirmed; coverage cell stays ◐ — not unconditionally covered. |
| 3B.1.b — Missing invoice numbers | Sequence-gap analysis | ✗ | — | Not implemented |
| 3B.3.1 — No GST amount on zero-rated invoices | Per-line GST = 0 on ZR | ◐ / J+ | E2 flags ZR + TaxTotal>0 | Catches the inverse error (GST wrongly charged on ZR); confirming a ZR line is *legitimately* zero-rated needs export evidence |
| 3B.3.2.1 — Export evidence (bill of lading, air waybill, export permit, etc.) proves goods exported | Inspect transport documents | 👤 | — | Documentary; AgentAssist can surface ZR lines with a Singapore ship-to as suspicious candidates (J+) but cannot verify export |
| 3B.3.2.2 — Services qualify as international services (s21(3)) | Legal characterisation | 👤 | — | Semantic/legal judgment |
| Out-of-scope supplies wrongly classified as zero-rated | OS vs ZR distinction | J+ | E2 logic touches OS; classification appropriateness | AgentAssist can flag candidates; reviewer decides |

## Step 3C — Check Exempt Supplies (Guide §Step 3C-1 / 3C-2; Templates 4 & 5)

| ASK check (¶) | What it requires | Coverage | AgentAssist function | What's missing |
|---|---|---|---|---|
| 3C.1.a / 3C-2.a — Listing tallies to Box 3 | Sum exempt lines = declared Box 3 | ◐ | `calculate_f5_return` (Box 3, ES33/ESN33); T2.9 Check B provides declared-vs-computed for Box 3 | Reconciliation to declared figure: T2.9 adds declared Check B (**MECHANISM VALIDATED ON DEMO, T2.9-V 2026-06-10** — flag-gated; renders findings when `--declared-f5` supplied with divergences). Rounding/tolerance convention still unconfirmed; coverage cell stays ◐ — not unconditionally covered. |
| 3C-1.b — Missing invoice numbers | Sequence-gap analysis | ✗ | — | Not implemented |
| Exempt value reported correctly (e.g., interest, FX gains, residential property) | Per-transaction-type valuation (Reg 33 / 4th Schedule) | ✗ / 👤 | — | `sg-tax-code-mappings.md` notes financial-services valuation has 9 transaction types out of POC scope; valuation is judgment-heavy |
| Supplies genuinely qualify as exempt | Legal characterisation | J+ | E2 flags ES33/ESN33 + TaxTotal>0 (GST wrongly charged on exempt) | Confirming a supply *is* exempt is semantic; AgentAssist surfaces candidates |

## Step 3D — Check Input Tax and Refunds Claimed (Guide §Step 3D; Template 6) — AgentAssist's strongest area

| ASK check (¶) | What it requires | Coverage | AgentAssist function | What's missing |
|---|---|---|---|---|
| 3D.1.1.a — Listing tallies to Boxes 5, 7 (10, 11) | Sum purchase lines = declared boxes | ◐ | `calculate_f5_return` (Box 5, 7); T2.9 Check B provides declared-vs-computed for Box 5 and Box 7 | Boxes 10/11 (TRS, bad-debt/RC refunds) not computed; declared reconciliation: T2.9 adds Check B (**MECHANISM VALIDATED ON DEMO, T2.9-V 2026-06-10** — flag-gated; renders findings when `--declared-f5` supplied with divergences). Rounding/tolerance convention still unconfirmed; coverage cell stays ◐ — not unconditionally covered. |
| 3D.1.1.b — Import permits beginning "ME"/"MC" wrongly used without MES/IGDS approval | Permit-prefix scan + scheme status | ✗ / D+ | — | No import-permit data ingested; would need permit feed + per-client scheme config |
| 3D.1.1.c — Input tax claimed outside the accounting period | Date-window + cross-period dedup | ✗ | — | No cross-period claim tracking |
| 3D.1.1.d — Duplicate input-tax claims | Cross-transaction dedup | ✗ | — | Not implemented |
| 3D.1.1.f — Credit notes received / debit notes issued reduce purchases & GST | CN/DN linkage | ◐ | Purchase credit notes fetched & subtracted; CN lines classified | Subtraction handled; original-document matching not |
| 3D.1.1.h — Input tax on disallowed expenses (Reg 26/27: medical, motor cars, club, family benefits) | Expense-category + GST disallowance | ◐ / J+ | E2 flags BL + TaxTotal>0 | Catches GST wrongly carried on a BL-coded line; does not *classify* a TX-coded expense as disallowable from its description (J+: surface candidates) |
| 3D.1.1.h — Purchases from non-GST-registered suppliers | Supplier GST-registration status | ✓ | NO_GST_REG (`detect_gst_errors`): purchase with input tax + blank `FederalTaxID` | Relies on `FederalTaxID`; clients storing GST reg no. in a UDF would mis-flag (config) |
| 3D.1.2 — Partial-exemption apportionment required & correct | De Minimis + apportionment formula | ✗ / 👤 | — | TX-RE mapped as Excluded; no apportionment logic. Judgment-heavy |
| 3D.1.3 — Reverse charge on imported services/LVG accounted for | RC scope + output tax | ✗ | — | RC not implemented |
| 3D.3 (B1–B8) — Source-document checks: invoice addressed to business, Reg 11 compliant, in furtherance of business, classified correctly, SGD agreement, correct period, consignee on imports | Inspect physical invoices/permits | 👤 | — | Documentary. AgentAssist supplies the population and pre-flags B4 (classification) and B5 (SGD value) candidates |

## Step 3E — Check Imports with GST Suspended (MES) or Deferred (IGDS) (Guide §Step 3E; Template 7)

| ASK check (¶) | What it requires | Coverage | AgentAssist function | What's missing |
|---|---|---|---|---|
| 3E.1.1.a — Listing tallies to Box 9 (suspended) & included in Box 5 | Import value reconciliation | ✗ | — | Box 9 not computed; IM/ME/IGDS routing exists in the mapping but scheme boxes (9/19/21) are not produced |
| 3E.1.2.a — Listing tallies to Box 19/21 (IGDS deferred) | Deferred-GST reconciliation | ✗ | — | Boxes 19/21 not computed |
| 3E.1.1.b–c / 3E.1.2.b–c — Import permits under business's name; dates within period | Permit data + dates | ✗ / 👤 | — | No permit ingestion |
| 3E.3 — Trace subsequent sale/movement of imported goods (s33(2)/s33A agents) | Inventory/movement tracing | 👤 | — | Documentary and judgment-heavy |

## Step 4 — Review Financial Statements / Management Accounts (Guide §Step 4; Template 1)

| ASK check (¶) | What it requires | Coverage | AgentAssist function | What's missing |
|---|---|---|---|---|
| 4.1 — Compare Sales/Turnover (financial statements) to annual Total Supplies (Box 4); reconcile if Total Supplies < Sales (threshold: diff > $150k if SR/TS ratio ≥ 75%, else > $500k) | Financial-statement figure + Box 4 | ✗ / 👤 | `calculate_f5_return` provides Box 1 and Box 4 (so the SR/TS ratio side is computable) | No access to financial statements / management accounts; the comparison and reconciliation are out of scope and judgment-led |

## Step 5 — Quantify Errors and Submit Findings (Guide §Step 5)

| ASK check (¶) | What it requires | Coverage | AgentAssist function | What's missing |
|---|---|---|---|---|
| Identify error(s) discovered in Steps 1, 3, 4 | Findings enumeration | ◐ | `detect_gst_errors` enumerates findings with DocNum, amounts, severity | Covers Step 3 detection; Step 1/4 macro errors not produced |
| Classify error: GST vs non-GST; isolated vs recurring | Error-nature judgment | J+ | Severity tiers approximate this | Isolated-vs-recurring and GST-vs-non-GST classification is reviewer judgment |
| Quantify error and decide F5-correction vs F7 (≤ $3,000 net GST and ≤ 5% of Box 4 → next F5; else F7) | Materiality threshold (e-Tax Guide ¶4.2.9) | ◐ / J+ | Per-finding amounts available; threshold is documented in `sg-tax-code-mappings.md` | Cross-period consolidation and the formal F5/F7 decision are judgment + filing actions (👤) |
| Complete Declaration Form / Disclosure of Errors / Administrative Concessions; submit to IRAS | Form completion + filing | 👤 | — | Filing is a human, accountable act (reviewer-of-record signs) |

## Coverage tally

Counting the discrete prescribed checks above (excluding the two purely procedural items, Step 2 and Step-5 filing):

| Symbol | Meaning | Count (approx.) |
|---|---|---|
| ✓ Full | 2 (E1 detection; non-GST-registered-supplier detection) |
| ◐ Partial | 11 |
| ✗ Gap | 9 |
| 👤 Human-only | 7 |

**Honest reading of the number.** Of the ~29 prescribed checks, AgentAssist contributes meaningfully (✓ or ◐) to **~13 (~45%)**. But that flat figure understates the picture in both directions, so two framings are clearer:

1. **Of the checks answerable from transaction data at all** (i.e. excluding the 7 👤 document-inspection / financial-statement / filing checks, which are correctly human-owned): AgentAssist touches 13 of ~22, **~59%**, and fully automates 2.
2. **Where AgentAssist is genuinely strong** is a narrow, high-value band: Step 3D input-tax integrity (non-GST-registered suppliers ✓, blocked-input GST ◐, listing reconciliation ◐) and Step 3A output-tax miscoding (FX miscoding ✓, rate/zero-tax errors ✓). These are exactly the mechanical, population-wide checks a human reviewer cannot do exhaustively by sampling — which is the product thesis.

The defensible public claim is **not** "AgentAssist automates the ASK Annual Review." It is: *AgentAssist automates population-level execution of the reconciliation and tax-code-integrity checks within Steps 1, 3A and 3D, and pre-screens candidates for the classification checks in Steps 3B/3C — leaving export-evidence verification, partial-exemption apportionment, scheme-specific imports (3E), financial-statement reconciliation (Step 4), and all source-document and filing steps to the human reviewer of record.*

---

# Document 2 — AgentAssist Findings → ASK Template Mapping

This drives the T1.4 PDF report layout: findings are grouped so a reviewer sees them in the same structure as the IRAS template they belong to. "Appendix 1 category" quotes the wording of the ASK guide's *List of Errors and Areas where Error may Occur* (p.72–74).

**Template index:** Template 1 = Steps 1, 2, 4 (declaration review + financial-statement reconciliation). Template 2 = Step 3A standard-rated supplies & output tax. Template 3 = Step 3B zero-rated. Template 4 = Step 3C-1 exempt (actively making). Template 5 = Step 3C-2 exempt (general business). Template 6 = Step 3D input tax & refunds. Template 7 = Step 3E imports suspended/deferred.

| AgentAssist finding | IRAS Template | Template section / row | Appendix 1 error category (verbatim) |
|---|---|---|---|
| **E1** — FX sale coded local standard-rated (SR/DS) | Template 2 | Step 3A.1.a (listing reconciliation) and 3A.3.1.ii–iii (amounts/SGD recording) | *General:* "Incorrect recording of value(s) from source document to listing … due to the use of different exchange rates for tax invoices issued in foreign currency"; and "Wrong classification of supplies made" |
| **E2 (output side)** — GST charged on a ZR / OS / ES33 / ESN33 supply | Template 3 (ZR) / Templates 4–5 (exempt) | 3B.3.1.a (no GST on ZR invoice) / 3C exempt-qualification checks | *Zero-rated:* "Supplies previously treated as zero-rated supplies but cannot qualify"; *Exempt:* "Supplies previously treated as exempt supplies but cannot qualify for exemption" |
| **E2 (input side)** — GST carried on a BL (blocked) line | Template 6 | Step 3D.1.1.h (disallowed input tax) | *Taxable Purchases and Input Tax:* "Input tax to be disallowed – Not for business purposes and/or specific expenses disallowed under GST (General) Regulations 26 and 27" |
| **E2 (input side)** — GST carried on an NR (non-registered) line | Template 6 | Step 3D.1.1.h | *Taxable Purchases and Input Tax:* "Input tax to be disallowed – Purchases from non-GST registered suppliers and/or non-taxable purchases … which do not attract GST" |
| **E3** — standard-rated sales line (SR/DS) with zero output tax | Template 2 | Step 3A.3.1.i (GST charged at correct rate) | *General:* "Over- / Under-reporting of value in GST return"; *Standard-rated:* output-tax under-reporting |
| **E3** — standard-rated purchase line (TX) with zero tax | Template 6 | Step 3D.3 (B2 — input tax supported by Reg 11 invoice) | *Taxable Purchases and Input Tax:* "Over-/Under-reporting" of input tax |
| **E4** — rate deviation on SR/TX | Template 2 (SR) / Template 6 (TX) | 3A.3.1.i / 3D source-doc checks | *General:* "Over- / Under-reporting of value in GST return (e.g., due to calculation error …)" |
| **NO_GST_REG** — input tax claimed on a purchase from a supplier with blank GST reg no. | Template 6 | Step 3D.1.1.h | *Taxable Purchases and Input Tax:* "Input tax to be disallowed – Purchases from non-GST registered suppliers and/or non-taxable purchases" |
| **COMPLETENESS** — purchase/sales ratio below threshold (possible omission) | Template 1 | Step 1.3a (fluctuations) and 1.3d (TP/TS ratio) | *General:* "Over- / Under-reporting of value in GST return (e.g., due to … omission of transactions)" |
| **F5 box-level errors** — computed box ≠ declared box | Template 1 | Step 1.3b/1.3c (declared vs computed output/input tax) | *General:* "Over- / Under-reporting of value in GST return" |
| **FX invoices excluded / pending conversion** (informational, from `calculate_f5_return`) | Template 6 (purchases) / Template 2 (sales) | 3A.3.1.iii / 3D B5 (SGD value agreement) | *Taxable Purchases and Input Tax:* "Tax invoices in foreign currency – Input tax claim … not made based on the SGD amounts or the supplier's exchange rate shown on tax invoice" |
| **Unknown-VatGroup anomalies** (from `calculate_f5_return`) | Template 1 | Step 1 analytical review | *General:* "Wrong classification of supplies made" |

**Notes for report design.** (1) E2 produces up to four distinct report rows depending on the VatGroup, routed to different templates — the report generator must branch on VatGroup, not on the error code alone. (2) The Appendix 1 wording should be quoted in the report so a tax-literate reviewer recognises the IRAS category immediately. **[Realized 2026-07-13, presentation-only report redesign, branch `t-report-redesign-avinash`, UNMERGED]** — `report/render.py` now leads each Section-3/Section-4 finding row with the Appendix 1 wording (`finding.appendix1_category`) as the primary label, demoting the raw internal code to a "(CODE)" tag; it reuses the existing `APPENDIX1_WORDING` map (no new tax wording). This is a **rendering change only** — it moves NO coverage cell (◐/●) in this document, changes no VatGroup→F5-box routing, and does not touch tax-domain content. (3) Findings AgentAssist does **not** produce (export-evidence failures, duplicate claims, apportionment errors, scheme-import errors) should appear in the report's "Not examined" section so the reviewer knows the coverage boundary.

---

# Document 3 — Steps 3A–3E Deterministic-vs-Judgment Matrix

Classifies each substantive check in the ASK Annual Review's transaction-testing steps. This is the "second pair of eyes" evidence base: it shows where the machine is authoritative (D/D+) and where the human reviewer remains essential (J/J+).

**Legend:** **D** — deterministic from data alone · **D+** — deterministic with per-client config (e.g. which GST schemes apply, where the GST reg no. is stored) · **J** — judgment; not automatable · **J+** — judgment-with-assist; AgentAssist surfaces candidates, human decides.

## Step 3A — Standard-rated Supplies & Output Tax

| Check (¶) | Class | Rationale / AgentAssist contribution |
|---|---|---|
| 3A.1.a Listing reconciles to Box 1/6 | D | Pure summation; `calculate_f5_return` |
| 3A.1.b Time-of-supply (earlier of invoice/payment) | J+ | Deterministic only if payment dates are ingested; otherwise documentary. AgentAssist could flag invoice-date anomalies if fed payment data |
| 3A.1.c Missing invoice numbers | D | SEQ_GAP over `DocNum` built in T2.10 (`orchestrator/check_listing.py`). Two-argument API with company-wide existence semantics (period-boundary fix applied). **Positive-detection validated on synthetic cases (T2.10-V):** DocNum 8002 truly-absent → flagged; DocNum 8003 within range but present company-wide (period-boundary discriminating case) → not flagged. Renders in signed PDF when findings present; Not-Examined item suppressed independently. Live zero-FP on SBODEMOSG Q3 2024 (1005 company-wide headers). **NOT validated on real client data.** SEQ_GAP cannot be seeded live on SAP B1; positive cases were crafted. |
| 3A.1.d Sales reductions via valid credit/debit notes | D+ | Deterministic once CN/DN linkage is modelled; single-use rule needs cross-document state |
| 3A.1.k FX/standard-rate correct treatment (→ E1) | D | FX + SR/DS detection is fully deterministic |
| 3A.3.1.i GST at correct rate (→ E3/E4) | D+ | Deterministic given the correct `expected_rate` (per-period config) |
| 3A.1.e–j, l–m Customer accounting / EM / OVR / RC | J / D+ | Scheme-specific; mostly judgment and out of SME scope |
| 3A.3 Valid tax invoice exists / Reg 11 compliant / SGD shown | J | Requires the physical document |

## Step 3B — Zero-rated Supplies

| Check (¶) | Class | Rationale / AgentAssist contribution |
|---|---|---|
| 3B.1.a Listing reconciles to Box 2 | D | `calculate_f5_return` |
| 3B.1.b Missing invoice numbers | D | SEQ_GAP over `DocNum` built in T2.10 (sales-side only; see 3A.1.c). Positive-detection validated on synthetic cases; renders when present; live zero-FP on demo. NOT validated on real client data. |
| 3B.3.1 No GST on ZR invoice (→ E2 inverse) | D | GST-on-ZR is deterministically detectable |
| 3B.3.2.1 Export evidence proves goods exported | J | Transport documents; documentary verification |
| 3B.3.2.2 Services qualify as international services | J | Legal characterisation |
| OS wrongly classified as ZR | J+ | AgentAssist flags ZR lines with SG ship-to as candidates; reviewer decides |

## Step 3C — Exempt Supplies (3C-1 / 3C-2)

| Check (¶) | Class | Rationale / AgentAssist contribution |
|---|---|---|
| 3C.a Listing reconciles to Box 3 | D | `calculate_f5_return` (ES33/ESN33) |
| 3C-1.b Missing invoice numbers | D | SEQ_GAP over `DocNum` built in T2.10 (sales-side only; see 3A.1.c). Positive-detection validated on synthetic cases; renders when present; live zero-FP on demo. NOT validated on real client data. |
| Exempt value reported correctly (Reg 33 valuation) | J | Per-transaction-type valuation; out of POC scope |
| Supply genuinely qualifies as exempt | J+ | AgentAssist flags ES33/ESN33 lines carrying GST (→ E2); qualification is judgment |

## Step 3D — Input Tax and Refunds Claimed

| Check (¶) | Class | Rationale / AgentAssist contribution |
|---|---|---|
| 3D.1.1.a Listing reconciles to Box 5/7 | D | `calculate_f5_return` |
| 3D.1.1.b "ME"/"MC" permit misuse | D+ | Deterministic given import-permit feed + scheme-status config |
| 3D.1.1.c Claim outside accounting period | D+ | Deterministic with cross-period claim history |
| 3D.1.1.d Duplicate claims | D | DUP_CLAIM built in T2.10 (`orchestrator/check_listing.py`). Key = (CardCode, NumAtCard, DocTotal); blank NumAtCard excluded. **Positive-detection validated on synthetic cases (T2.10-V):** dup pair 7001/7002 (same CardCode + NumAtCard + DocTotal) → flagged; near-miss 7003 (different NumAtCard) → not flagged. Renders in signed PDF when findings present; Not-Examined item suppressed independently. Live zero-FP on SBODEMOSG (NumAtCard 0% populated — all excluded per design). **INERT on SBODEMOSG and any company where AP operators do not populate NumAtCard** — client-onboarding data-quality precondition. NOT validated on real client data. |
| 3D.1.1.f Purchase reductions via CN/DN | D+ | CN subtraction handled; matching needs document state |
| 3D.1.1.h GST on disallowed (BL) expense (→ E2) | D | BL + GST is deterministically detectable |
| 3D.1.1.h Expense category disallowable under Reg 26/27 | J+ | Classifying a TX expense as disallowable from its description is judgment; AgentAssist can surface keyword candidates |
| 3D.1.1.h Purchase from non-GST-registered supplier (→ NO_GST_REG) | D+ | Deterministic from `FederalTaxID`; the "+" is config for clients storing reg no. in a UDF |
| 3D.1.2 Partial-exemption apportionment | J | De Minimis + apportionment; judgment-heavy, not built |
| 3D.1.3 Reverse charge accounted for | J / D+ | Scheme-dependent; not built |
| 3D.3 B1–B8 source-document tests | J | Physical invoices/permits. B4 (classification) and B5 (SGD value) are J+ — AgentAssist pre-screens |

## Step 3E — Imports with GST Suspended / Deferred

| Check (¶) | Class | Rationale / AgentAssist contribution |
|---|---|---|
| 3E.1 Listing reconciles to Box 9 / 19 / 21 | D+ | Deterministic if scheme boxes are computed (not built) + scheme config |
| 3E.1 Import permits under business name, dates in period | J+ | Needs permit feed; AgentAssist could reconcile if fed permit data |
| 3E.3 Trace subsequent sale/movement (s33(2)/s33A) | J | Inventory tracing; documentary and judgment-heavy |

## Summary

Across Steps 3A–3E, the substantive checks distribute roughly as: **D** ≈ 8, **D+** ≈ 7, **J+** ≈ 6, **J** ≈ 10. The deterministic and config-deterministic checks (D + D+ ≈ 15) cluster in **listing reconciliation, tax-code integrity, and registration verification** — precisely AgentAssist's E1–E4 / NO_GST_REG band. The judgment checks (J + J+ ≈ 16) cluster in **document verification, export/exemption qualification, apportionment, and scheme imports** — where the reviewer-of-record's professional judgment is irreducible and, for liability, must remain so. This is the structural basis for "second pair of eyes": AgentAssist executes the deterministic band exhaustively across 100% of transactions, and routes the judgment band to the human as pre-screened candidates rather than raw data.

---

# Document 4 — Reasoning-Layer Coverage Extension (Roadmap, not validated capability)

Documents 1–3 describe **validated, deterministic** coverage — what the Python tools do today, tested to 10/10 on SBODEMOSG. This section maps where the *reasoning layer* (Claude + the curated knowledge base + future agent skills) can **extend** coverage into checks currently marked ✗ Gap or 👤 Human-only. Everything here is roadmap; none of it is claimed as current capability.

**The architectural invariant (non-negotiable).** The reasoning layer expands **recall**, never **authority**. Every reasoning-layer output is a *candidate surfaced for human vetting* — never an asserted compliance conclusion, and never an auto-correction passed through to a return. This is enforced by the system prompt's compliance-assertion rule ("never assert a compliance issue without tool-confirmed evidence") and by mandatory reviewer sign-off. The v0/v1 experiments are the evidence for *why* this is non-negotiable: unaccompanied reasoning fabricated a critical IRAS voluntary-disclosure finding and an F7 recommendation. A reasoning-layer check therefore **caps at J+** — it raises what the human sees, never what the system concludes on its own.

**Two gates apply to every extension below:**
1. **Input availability** — the reasoning layer can only check what it can see. Most of these checks require ingesting *source documents* (tax-invoice PDFs, transport/export documents, import permits) the system does not read today. This means building a document-ingestion path (SAP attachments or uploads). A few need only additional structured fields (e.g. payment dates).
2. **Measurement before claiming** — a reasoning-layer check earns a place in a coverage *claim* only after its false-positive rate (<5%), recall (>95%), and severity calibration are measured. Until then it is roadmap, not capability, and must not be represented to a customer as validated.

| ASK check (¶) | Today | Extended (reasoning layer) | Enabler required | Why it caps at J+ |
|---|---|---|---|---|
| 3A.3.1 — Valid tax invoice; GST shown; amounts agree to listing | 👤 | J+ | Invoice-document ingestion (multimodal read) | Document authenticity & completeness is a probabilistic read; reviewer confirms |
| 3D.3 B1 / B4 / B5 — Invoice addressed to business; classified correctly; SGD value agrees | 👤 | J+ | Invoice/permit ingestion | Same; B3 (in furtherance of business) remains judgment-heavy |
| 3D.3 B6 — Captured in correct accounting period | 👤 | D+ (not J+) | Invoice dates in feed | This one is genuinely deterministic once dates are present — the exception that firms up |
| 3B.3.2 — Export evidence proves goods exported; business name as exporter | 👤 | J+ | Transport-document ingestion (bill of lading, permit) | Reading a document ≠ legal certainty of export; reviewer confirms |
| 3B.3.2.2 / 3C — Services qualify as international / supply genuinely exempt | J / J+ | J+ (strengthened) | Knowledge base (Reg 33, s21(3)); optionally contract ingestion | Legal characterisation; the KB sharpens the candidate, human decides |
| 3A.1.b — Time of supply (earlier of invoice / payment) | ✗ | J+ | Payment-date ingestion | Anomaly flag, not a determination |
| 3D.1.1.h — Expense category disallowable under Reg 26/27 | J+ | J+ (strengthened) | Knowledge base + description reasoning | Classifying an expense from its description is inherently probabilistic |
| 3E — Import permits under business name; trace movement | 👤 | J+ | Permit/inventory-document ingestion | Documentary + judgment |

**InvoiceNow / PINT-SG convergence.** As structured invoice data (GST registration number, GST amount, SGD value, line description) arrives via the InvoiceNow feed at source, several of the checks above stop requiring a *document read* and become checks against *structured fields* — moving a handful of today's J+ candidates toward D+ over time. The mandate is quietly building part of this roadmap.

**Agent skills are the productionisation path.** Packaging each extension as a discrete, eval-able skill (e.g. a "Reg 33 exempt classification" skill, an "export-evidence verification" skill) is what makes a J+ capability *measurable and consistent* — and therefore eventually claimable under the accuracy basket. Skills do not change the J+ ceiling; they make the J+ contribution reliable enough to depend on. The end-state design goal is explicit: the reasoning layer flags every candidate that needs human vetting and passes nothing through on its own.

---

## Known limitations of this analysis

- **Validated only on SBODEMOSG.** Coverage symbols describe designed/validated behaviour on clean demo data. Production data may include custom VatGroup codes (silently excluded today), partial-exemption scenarios, manual journals, and scheme-specific imports — none yet tested.
- **"Declared vs computed" gap (partially addressed by T2.9 + T2.9-V).** Several Step 1 and Step 3 listing-reconciliation checks are marked ◐ because AgentAssist computes box figures from SAP transactions but does not natively ingest the *filed* F5 return. T2.9 adds declared-vs-computed Check B via `--declared-f5` flag. **T2.9-V (2026-06-10) validated the mechanism end-to-end** on SBODEMOSG Q3 2024: three isolated fixtures (Check A isolation, Check B isolation, control), 22 assertions, box-isolation held, report section renders. Coverage cells graduate from "BUILT, UNVALIDATED — pending T2.9-V" to **"mechanism validated on demo; renders when filed F5 supplied; tolerance convention unconfirmed."** Cells stay ◐ — NOT unconditionally covered. **One external dependency remains**: whether F5 boxes are filed whole-dollar or to the cent has not been confirmed against IRAS source; $1.00 per-box tolerance is a materiality floor (ASK Guide s10.1(d)(iii) fn33), not a confirmed IRAS convention. A surfaced divergence is a candidate for reviewer attention, not a confirmed discrepancy. Confirmation is a pending cousin task.
- **Sequence-gap and duplicate-claim checks (T2.10 + T2.10-V, merged to master 2026-06-10).** 3A.1.c, 3B.1.b, 3C-1.b (SEQ_GAP) and 3D.1.1.d (DUP_CLAIM) are implemented in `orchestrator/check_listing.py` and positive-detection validated on synthetic crafted cases (T2.10-V, merge `037c271`). Coverage matrix cells graduated from "plumbing-demonstrated" to "positive-detection validated on synthetic cases; renders when present; live zero-FP on demo." **Mandatory caveats:** SBODEMOSG is a demo/synthetic database — NOT real-client validation. SEQ_GAP cannot be seeded live on SAP B1 (DocNums assigned sequentially); positive cases were crafted inputs. DUP_CLAIM is inert on any company where AP operators do not populate `NumAtCard` (client-onboarding data-quality precondition). `page_size=20` pagination confirmed working at scale (1005/624 headers pulled); @odata.nextLink remains the robustness follow-on. Sections render only when findings present; when empty, Not-Examined items remain in Section 6.
- **Citation scheme.** References use the ASK Annual Review Guide's step/paragraph numbering and Appendix 1 wording as loaded in Project Knowledge. Confirm the guide edition on its cover (expected: Sixteenth Edition, 30 Jan 2026) and re-verify paragraph numbers if a later edition is substituted.
- **Pre-Filing Checklist not used.** Per the agreed approach, Document 3 maps to the Annual Review Steps 3A–3E (post-submission substantive testing), which matches AgentAssist's workflow, rather than the separate Section 2 Pre-Filing Checklists.
- **Not legal advice.** This is an engineering coverage analysis, not a determination of ASK compliance. Final ASK certification rests with an SCTP-accredited ATA (GST) / ATP (GST).
