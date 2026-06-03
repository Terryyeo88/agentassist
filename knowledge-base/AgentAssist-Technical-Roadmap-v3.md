# AgentAssist Technical Roadmap v3 — Tier 1 **COMPLETE**

*Revised 2026-06-02. Supersedes v2. The headline change: **all six Tier-1 items are done**.
T1.5 (audit trail + input immutability) landed 2026-06-02, closing Tier 1. Every chain run
now produces a sealed, tamper-evident audit bundle. The three remaining gates to a first paying
engagement are production-data robustness (Gate B), PDPA compliance (Gate C), and security
history scrub (Gate C) — none are build items.*

---

## What changed from v2 (read this first)

**1. Tier 1 is complete.** All six items landed. Current Tier-1 state:

| Task | Status |
|------|--------|
| T1.1 Credit notes | DONE (Collin, 2026-05-28) |
| T1.2 NR VatGroup resolution | DONE (Collin; verified — all four artefacts agree) |
| T1.3 Per-client config | DONE (Terry, 2026-05-31, master) |
| T1.6 Orchestration chain | DONE (Terry, 2026-06-01, merged to master) |
| T1.4 Signed PDF report | DONE (Terry, 2026-06-01, merged to master — 124 tests) |
| **T1.5 Audit trail + input immutability** | **DONE (Terry, 2026-06-02 — 169 tests)** |

**2. The gates have shifted from features to trust.** With the report delivered, "can we
produce a deliverable" is answered (yes). The remaining gates to a paid pilot are no longer
about capability — they are about (a) **defensibility** of the work product (T1.5), (b)
**trustworthiness on real, non-demo data** (production-data robustness), and (c) **permission
to touch real client data at all** (PDPA + Anthropic DPA + security history scrub). The forward
sections below are reorganised around those three gates.

**3. T1.4 implementation decisions worth recording (so they aren't re-litigated):**
- The report consumes the **full `CompileOutput` JSON** from the T1.6 chain, **not** the flat
  `ReportInput` (now a deprecated stub in `orchestrator/schemas.py`). `CompileOutput` preserves
  the classify and detect issue lists separately, which the report needs for enrichment.
- Findings are enriched by a **three-source join keyed by `(doc_num, error_code)`**: classify
  amounts + detect severity + manifest backfill. Line-level findings collapse to one finding
  per `(doc_num, error_code)` (e.g. doc 974's three E1 lines → one finding).
- **Document-2 IRAS template routing** is by error code *and* VatGroup. Exempt-E2 findings
  default to **Template 5**; **Template 4** is used only when `actively_makes_exempt_supplies`
  is set in the client config.
- The report's IRAS Appendix-1 wording is sourced **verbatim from the IRAS ASK Guide (16th ed,
  pp. 72–73)**, not from the coverage-analysis notes.
- The **human-in-the-loop invariant is test-enforced**: no system-generated filing directives;
  findings are "candidates for review," the reviewer signs. The output is a **working paper,
  not an IRAS submission**, and is **not "IRAS-approved"** (no such scheme exists).

**4. T1.6 realities to carry forward:**
- **Gate 1 is dormant on SBODEMOSG** — that Service Layer doesn't return `$inlinecount`, so
  pagination completeness is verified structurally (`len(page) < 20`), not arithmetically.
- **~4× redundant fetch (tech-debt, T1.6.1):** calculate/classify/detect each re-fetch from SAP
  independently. Deferred.
- **Source-adapter decision deferred:** the tool steps call `sap_b1_server` directly; swapping
  in a CSV/extract source would require changing step signatures.

**5. Housekeeping now exists as a committed artefact:** `exploration-notes/operational-backlog.md`
captures the three deferred operational items (SAP CAL lifecycle, seed cleanup + re-baseline,
fallback-credentials inconsistency), cross-referenced to `AGENTASSIST_TECHNICAL_STATE.md`
Appendix C. `requirements.txt` now pins `reportlab` and `PyYAML`. Generated outputs are
gitignored. Remote is the **private** repo `Terryyeo88/sap-b1-ai-agent`; credentials remain in
history at `aec650f9` (scrub still pending — see Gate C).

---

## Tier 1 — Required Before First Paying Customer

Everything above the line is done. The remaining task:

### T1.5 — Audit trail and input immutability (DONE — Terry, 2026-06-02)

**What was built:** `audit_bundle/` package (`canonical`, `config_redaction`, `provenance`,
`manifest`, `gate_record`, `seal`, `verify`). Every successful `run_agent.py` run now produces
a sealed bundle under `audit/<client_id>/<period>/<run-ts>/` containing `manifest.json`,
`config.json` (secrets stripped), `inputs/fetch-manifest.json`, `steps/{calculate,classify,
detect}.json`, `gates.json` (gate results with checked values), `compile-output.json`, and
`report.pdf`. SHA-256 per artefact + root hash; `python -m audit_bundle.verify <bundle-dir>`
detects any post-seal edit. On `GateFailure`, the chain halts and no bundle is written.

**Re-derivability:** `rederivation_grade: "same-SAP-state"` — re-running against the same SAP
data state reproduces `compile-output.json` byte-for-byte. Full offline replay from frozen
line bytes is deferred to the Tier-2 source adapter.

**Test state:** 169 tests passing (1 skipped: read-only advisory, Windows).

---

## The three real gates to a first paid pilot

T1.5 is necessary but **not sufficient**. There are three distinct gates, and only the first is
T1.5. Sequence them deliberately.

### Gate A — Defensibility of the deliverable → **T1.5 DONE** (above)
Engineering. The formal Tier-1 closer. **Closed 2026-06-02.**

### Gate B — Trustworthiness on real (non-demo) data → production-data robustness
This is what actually **breaks a first pilot**, and none of it is exercised by SBODEMOSG (clean
SAP-maintained demo data). Pull these forward from "before scaling" to **"before first real-data
pilot":**
- **Custom VatGroup discovery (was T2.2).** Non-standard codes currently fall into `anomalies`
  and are silently excluded → a materially wrong F5 with only a generic warning. Build a
  `discover_vat_groups` pass at engagement start that reports standard-vs-custom codes with
  sample DocNums, so the reviewer can decide treatment and capture it in config.
- **Header-level TaxTotal / `VatSum` guard.** The tools assume line-level `TaxTotal`. Some SAP B1
  configs store tax at header level or in `VatSum`; against those, all three tools produce wrong
  numbers silently. Add detection that refuses to proceed (or warns loudly) on a non-standard
  tax structure.
- **NO_GST_REG UDF configurability.** The check reads `FederalTaxID`; clients who store GST
  registration in a UDF would see every supplier flagged. Make the field source configurable.
- **Static fixtures beyond SBODEMOSG.** Synthetic, SAP-independent fixtures for custom VatGroups,
  header-level tax, rate-transition periods, partial exemption, and legitimately-unregistered
  small suppliers — so these surface in a test, not in front of a client.

### Gate C — Permission to touch real client data → compliance + security (long lead)
Non-engineering, with lead time. Start the slow ones **now, in parallel** with T1.5:
- **Security history scrub.** Credentials (PEM + demo creds) are in history at `aec650f9`. This
  becomes mandatory at the first of: public repo, non-trusted collaborator, first paid engagement,
  real client data. **Decision point today:** Collin gets repo access for T1.5 → that history
  (including the PEM) becomes visible to him. If he's trusted, that's within tolerance; if not,
  scrub first. The scrub itself is a 1–2 hour job.
- **PDPA framework + Anthropic DPA.** All tool output and messages go to the Claude API, so a
  data processing agreement and a data-handling policy (purpose limitation, minimisation,
  ~7-year tax-workpaper retention then destruction) are required before real client data. Needs
  legal input → start scoping early; this is the item most likely to cause a schedule surprise.
- **Anthropic data residency** confirmation (Singapore vs US/EU routing) for the client
  disclosure.

### Cheap wins (drop in whenever convenient)
- **ZP+TaxTotal → E2.** DocNum 610 (ZP + TaxTotal=84) is a real E2 not currently caught.
  Extend `_E2_ZERO_RATE_CODES` to include ZP. ~2 hours.
- **Fallback-credentials fail-fast.** Verify `SAPB1Client.__init__`: if it still falls back to
  demo creds when env vars are absent, change to a clear `RuntimeError` (prevents a misconfigured
  prod deploy silently hitting the demo box) and reconcile the contradicting doc sections.

---

## Tier 2 — Before Scaling Beyond Initial Pilot

*Internals per v2 except where re-tiered above. T2.2 (custom VatGroups), and the header-TaxTotal
and NO_GST_REG-UDF guards, have been promoted into Gate B (before first real-data pilot).*

- **T2.1 — Manual journal entry support.** `JournalEntries` are not fetched; GST-relevant manual
  journals are invisible. Per-client `gst_accounts` config to identify relevant lines. 1–1.5 wk.
- **T2.3 — Automated evaluation harness.** Promoted in importance: it is the durability mechanism
  for the 30/30 reliability claim — re-runs the V0–V3 battery via the API on every model/prompt/KB
  change so the result can't silently regress. Structural/numeric scoring, not text comparison.
  2–3 wk.
- **T2.4 — Hardened error handling / retry.** Backoff on 503/timeout, pagination resumption,
  mid-pagination re-auth, partial-data detection. 1–2 wk.
- **T2.5 — FX conversion (SGD-equivalent box computation).** Convert FX rather than only listing
  it; methodology choice (supply-date vs month-end) captured in config. 1.5–2 wk.
- **T2.6 — Multi-quarter / rolling-period analysis.** Arbitrary date ranges; year-end summaries.
  1 wk.
- **Source adapter + 4× fetch (T1.6.1).** Decouple the tool steps from live SAP (CSV/extract),
  which also collapses the redundant fetch. Strategic leverage: lets you demo and run without a
  client's live instance, and a richer feed unlocks declared-vs-computed and time-of-supply checks.

### T2.7 — Reasoning layer v1: Reg 26/27 disallowed-expense candidate surfacing (J+)

**Why this first.** The first genuine reasoning capability, and the chosen entry point of the Document 4 reasoning-layer roadmap. Deterministic E2 only catches GST on an already-BL-coded line; it cannot catch an expense MIScoded as SI (claimable) that should be BL (medical, S-plated motor, club subscription, family benefit, entertainment) — the VatGroup says SI and every rule passes it. Only reading the line description reveals the error. Irreducibly semantic; sits in Step 3D (highest IRAS-penalty area); something neither a rule nor exhaustive human review can do across 100% of lines.

**What it does.** Reads SI-coded purchase line descriptions and surfaces candidates that read like a Reg 26/27 disallowed category, each phrased "consider reviewing whether…" — never an assertion.

**Architectural invariant (non-negotiable, per Document 4).** Expands recall, never authority. Runs BESIDE run_chain, never inside it: touches no F5 box, no gate, no deterministic finding. Output is a separate bundle artefact steps/judgment-candidates.json; the T1.5 manifest's llm_in_run_path becomes PER-ARTEFACT — deterministic core stays false, this artefact is true with model id + prompt version + KB-slice hash. Surfaces in PDF Section 5 as a labelled "AI-surfaced candidates" subsection, separate from deterministic findings. Reviewer accepts/dismisses each; reviewer signs.

**Input.** SI-coded purchase line descriptions — already fetched. PREREQUISITE: confirm the line description field is in the SAP $select (one-field addition if not). No new ingestion path.

**Build form.** System prompt + Reg 26/27 KB slice. NOT a skill yet (invariant #5).

**Measurement gate before any customer-facing claim.** Labelled set of SI lines; FP rate <5%, recall >95%. Until measured: "additional unvalidated candidates," not a headline.

**Sequencing.** Positioning/capability, NOT a pilot gate. Build in parallel with / after Gate B; do not jump it ahead of Gate B or Gate C, which actually gate first revenue.

**Effort.** ~1 wk for v1. Follow-ons (T2.7.x): ZR/OS export-appropriateness, ES33 exempt-appropriateness candidates; client-business-nature injection (see below).

### T2.7.x — Client Business-Nature Field in ClientConfig (Production Prerequisite)

**Problem.** The v1 reasoning pass assumes a generic general-trading / services SME purchasing
goods as overhead.  A car dealer's vehicles are claimable trading stock; a clinic's medical
supplies are direct service inputs; an insurer's staff premiums may be a product input.  Without
knowing the client's business type, the pass will surface context-claimable lines as false
positives whenever it is run against a specialist firm.

**What to build.** Add a `business_nature` field to `ClientConfig` (per-client YAML).  At run
time, `run_reg2627_pass` reads this field and injects a short business-context paragraph into the
reg2627 system prompt before the KB slice.  The paragraph instructs the model to treat the named
category of purchases as claimable trading inputs rather than overhead — e.g. "this client is a
licensed motor-vehicle dealer; treat all vehicle purchase and running-cost invoices as trading
stock, not overhead, and do not surface them as Reg 26/27 candidates."

**Guard.** Until this field is implemented, `run_reg2627_pass` must not be enabled for clients
whose primary trade overlaps with any §6.1.6 disallowed category.  A pre-flight assertion in the
reasoning pass should check that `business_nature` is present and log a warning if it is absent.

**Reference.** `knowledge-base/slices/business-context.md` — full statement of the generic-SME
assumption, already wired as the labelling-pass context document.

**Effort.** ~0.5 wk (config field + prompt injection + test).

## Tier 3 — Gated by External Milestones

*Unchanged from v2.* T3.1 SOC 2 / DPTM readiness; **T3.2 PDPA framework (now started early as
Gate C)**; T3.3 BIG application exhibit; T3.4 Anthropic Partner Network artefacts; T3.5 SAP B1
reseller channel materials.

---

## Allocation (updated)

| Thread | Owner | Notes |
|--------|-------|-------|
| T1.5 audit trail | **Terry** | Executed 2026-06-02; DONE |
| Gate B robustness + static fixtures | **Terry** | Production-data correctness; needs SAP/domain judgment |
| Gate C security scrub | **Terry** | 1–2 hr; decide before Collin gets repo access |
| Gate C PDPA / DPA | **Terry** (+ legal) | Long lead; start scoping now |
| Cheap wins (ZP E2, fail-fast) | either | Drop-in |

Terry's three-in-a-row Tier-1 critical-path load is **done**. The next engineering threads
(T1.5 by Collin; Gate B by Terry) can run in parallel.

---

## Architectural reminders (carried forward, with T1.4 additions)

1. **Three-layer separation is non-negotiable.** Tools do arithmetic; KB is reference; system
   prompt orchestrates.
2. **The reference script is the audit, not the partner.** Independent implementation; no shared
   code; divergence flags bugs.
3. **Claude never asserts compliance positions unilaterally.** "Candidate for review" vs
   "confirmed error" is preserved — now test-enforced in the report (`test_sections.py`).
4. **The reviewer signs off on every finding.** No automatic filing or IRAS contact at any tier.
   The deliverable is a **working paper, not an IRAS submission**; it is not "IRAS-approved."
5. **No skill abstraction until the product spans multiple workflows.**
6. **The knowledge base is modular per chain-step.** Each step gets only its regulatory slice;
   cross-step information flows forward as data, not merged KBs.
7. **Orchestration is a predefined code path, not autonomous agents.** Gates are deterministic
   Python, never LLM calls.
8. *(new)* **The report consumes the chain's full `CompileOutput`**, not a lossy summary — input
   contracts between layers should preserve, not pre-collapse, the structure downstream needs.

---

*End of roadmap v3. Tier 1 fully complete (T1.1/T1.2/T1.3/T1.6/T1.4/T1.5 on master or
branch t1.5-audit-trail pending merge, 169 tests). The pilot is gated by three things, none
of which are build items: real-data trust (Gate B), permission to touch real data (Gate C),
and security history scrub (Gate C).*
