# AgentAssist Technical Roadmap v5

Revised from v4. v5 records what the diagnostic/fix runs of 2026-06-08 established, adds an explicit validation-dataset task, and places the multi-vertical platform vision as a gated north-star. It does not change any Tier 1/2/3 task already specified in v4 except where noted in the changelog.

**Status convention:** `DONE` / `IN PROGRESS` / `PROVISIONAL (unvalidated)` / `PLANNED`. Effort estimates on new tasks are **PROPOSED — needs Terry confirmation**; first-pass sizings, not commitments.

---

## What changed from v4 (changelog)

1. **The AI-candidate forwarding bug is fixed.** `run_agent.py` now forwards `judgment_artefact=reasoning_artefact` to `build_report`. The report's "AI-surfaced candidates" section renders the real status (e.g. "No AI-surfaced candidates" when `candidate_count=0`) instead of the false "AI candidate pass did not complete." Confirmed by a live re-run on 2026-06-08.

2. **`show_ai_candidates` wiring is confirmed working (T2.7 branch).** Declared in `config/loader.py` (default `False`), read in `report/report.py`, consumed in `report/sections.py` / `render.py`. The earlier v4 flag "not visibly consumed" is resolved — it is consumed on branch `t2.7-reasoning-reg2627`; it remains absent from `master`.

3. **SBODEMOSG holds no document attachments.** The `Attachments2` entity is supported (HTTP 200) but empty; 0/21 purchase invoices and 0/50 sales invoices carry an `AttachmentEntry`. Consequence for T2.8: invoices must be attached/uploaded manually for any document-ingestion demo or build — they cannot be pulled from this demo company.

4. **New task T2.13 — Validation dataset construction** (synthetic-paired + pilot-derived). Makes explicit the ground-truth substrate that T2.11 consumes, including the line-item-only-for-now vs paired-with-invoice-for-T2.8 distinction.

5. **New Tier 4 — Platform vision (north-star, gated).** Captures the consolidated multi-vertical agent dashboard as an explicitly sequenced future state, not a near-term build.

---

## Current build-state snapshot

**Shipping today (deterministic, validated on SBODEMOSG only):**
- SAP B1 MCP connector (Python FastMCP, stdio); three custom tools: `calculate_f5_return`, `validate_invoice_tax_codes`, `detect_gst_errors`. Error codes E1–E4, NO_GST_REG, COMPLETENESS.
- T1.6 deterministic orchestration chain (fetch → classify → calculate → detect → compile) with five pure-Python reconciliation gates that halt on failure. `orchestrator/` pure-Python; `llm_in_run_path: false`.
- T1.4 signed PDF working paper (`report/`); T1.5 tamper-evident audit bundle.
- Validated 10/10 on Tests 1–3 at v3 on SBODEMOSG Q3 2024 — clean demo data, not production-proven.

**Built but unvalidated (T2.7 branch `t2.7-reasoning-reg2627`, not merged to master):**
- Reasoning layer (`reasoning/` package): Reg 26/27 disallowed-input candidate surfacing. `show_ai_candidates` flag wired and working; forwarding bug fixed 2026-06-08. The live re-run surfaced **0 candidates** over SBODEMOSG (no disallowable-looking expenses present) — a real but **unvalidated** result.
- Provisional measurement (2026-06-03, 110-line Opus-labelled fixture): Sonnet recall 1.000 / FP 0.000, Opus 1.000 / 0.022, Haiku 1.000 / 0.065. **NOT gate results** — the fixture labels are AI-generated, not human-reviewed. `validation_status: unvalidated`; `show_ai_candidates` stays `False` for any deliverable until T2.11 reconciles.

**Remaining gates to a paid pilot (none are correctness or delivery-format gaps):** production-data trust, PDPA compliance, security history scrub.

---

## Tier 1 — Required Before First Paying Customer — ALL DONE

| Task | Effort | Owner | Status |
|------|--------|-------|--------|
| T1.1 Credit note support across all three tools | ~1 wk | Collin | DONE |
| T1.2 NR VatGroup resolution (4-artefact consistency) | — | Terry (verify) | DONE |
| T1.3 Per-client configuration model (`ClientConfig`, YAML) | 1.5–2 wk | Terry | DONE |
| T1.6 Orchestration chain + 5 deterministic gates | 1.5–2 wk | Terry | DONE |
| T1.4 Signed PDF report generation | 2.5–3 wk | Terry | DONE |
| T1.5 Audit trail + input immutability (sealed bundle) | 1.5–2 wk | Collin | DONE |

The chain is the defensibility backbone: a fixed, auditable sequence with deterministic gates that halt rather than emit a confident wrong result. The report projects the chain's gated output; the audit bundle captures gate results so the trail shows reconciliation passed before the report was produced.

---

## Tier 2 — Required Before Scaling Beyond Initial Pilot

Non-blocking for the first 1–2 friendly pilots; real problems at 5+ clients or formal contracts.

### T2.1 — Manual journal entry support — PLANNED
Effort 1–1.5 wk. Owner Collin. Add `JournalEntries` queries; filter GST-relevant accounts via per-client `gst_accounts` config; per-line classification where account context is GST-input/output. Hardest part: identifying GST-relevant journal lines (inferred from GL account). Out of scope: adjusting journals that re-classify GST across boxes.

### T2.2 — Custom VatGroup discovery and reporting — PLANNED
Effort 1 wk. Owner Collin. `discover_vat_groups` tool run at engagement start: report standard vs custom VatGroups, surface sample DocNums/counterparties for custom codes, persist treatment decisions in per-client config.

### T2.3 — Automated evaluation harness — PLANNED (durability mechanism for the headline reliability claim)
Effort 2–3 wk. Owner Terry. Given stored prompt + reference output, invoke the Claude API directly, capture response, compute a scoring vector; run as CI on every meaningful change. Scoring uses structural checks, not text comparison. Protects the 30/30 across model upgrades and prompt/KB edits. T2.11 builds on it for the reasoning-layer basket.

### T2.4 — Hardened error handling and retry logic — PLANNED
Effort 1–2 wk. Owner Collin/Terry. Exponential backoff on 503/timeout; pagination resumption from `$skip`; session re-auth on 401 mid-pagination; partial-data detection via `$inlinecount`; entity-named error messages.

### T2.5 — FX conversion (box-level SGD equivalent) — PLANNED
Effort 1.5–2 wk. Owner Terry. `convert_fx_to_sgd` reading SAP's rate table or a configured source; add converted values to boxes; disclose the rate source. Hardest part: methodology (IRAS supply-date rate vs client month-end) captured in config. Until then FX stays excluded and listed for manual conversion.

### T2.6 — Multi-quarter / rolling-period analysis — PLANNED
Effort 1 wk. Owner Collin. Tools accept arbitrary date ranges; reports adapt to period summaries.

### T2.7 — Client business-context profile (reasoning-layer surfacing aid) — PLANNED
Effort 1.5–2 wk (builds on T1.3 + T2.2). Owner Terry. Extend `ClientConfig` with a structured `business_context` block; the reasoning step receives only its relevant slice and uses it to weight/annotate candidates — never to compute box figures. Feeds Layer 2 only.

Design constraints (non-negotiable): inform, never auto-bless; surfaces, never asserts — even with context (caps at J+); profile is reference data, not arithmetic (never enters tools/boxes/gates; `orchestrator/` stays pure-Python and context-free); profile provenance is auditable. Re-triggers the V0→V3 loop. DoD includes a blind-spot test (seed a miscoded transaction matching a profile expectation; confirm it is still surfaced), a confidence-inflation test (no verdict asserted regardless of profile strength), and byte-identical box figures with/without the profile.

> Distinction: T2.7 improves candidate quality from the line-item data Layer 2 already sees. It does NOT give Layer 2 new inputs. The document adapter (T2.8) is what gives Layer 2 inputs it is currently blind to. Complementary.

### T2.8 — Source / document-ingestion adapter — PLANNED (highest-leverage coverage unlock)
Effort PROPOSED 3–4 wk. Owner Terry.

Business reason: the entire 👤 → J+ band in coverage-analysis Document 4 is blocked by input availability. Today the system sees SAP line items only. An adapter that ingests source documents (tax-invoice PDFs, transport/export docs, import permits — via `Attachments2` or manual upload) lets Layer 2 surface cross-reference candidates it is currently blind to: listing-vs-source amount agreement (3A.3.1, 3D.3 B5), Reg 11 validity (3D.3 B1), export-evidence presence (3B.3.2), permit-under-business-name (3E), correct-period (3D.3 B6 → firms to D+).

> Note (2026-06-08): SBODEMOSG carries **no** attachments, so document-ingestion work must supply its own invoice PDFs (synthetic for the controlled set; real pilot documents under a DPA). The `Attachments2` path is supported but will be empty on the demo instance.

Scope: a `documents/` module that (1) accepts PDFs/images; (2) routes born-digital PDFs to deterministic text extraction (`pdfplumber`/`PyMuPDF`) and scans to a multimodal read (no bespoke OCR/CV stack — Claude reads PDFs natively); (3) extracts a structured candidate-field set; (4) hands extracted fields to the reasoning layer to reconcile against the deterministic listing and surface mismatches as candidates.

Why it caps at J+: extraction is probabilistic — reading raises recall, not authority. The sole exception is invoice-date → correct-period (B6 → D+). Legal characterisations (export, exemption, Reg 26/27) stay J+ regardless. Extracted values never enter Layer 1, boxes, or gates; the deterministic listing stays the authoritative anchor. DoD: byte-identical box figures/gate results with and without the adapter; FP (<5%) and recall (>95%) measured before any claim.

### T2.9 — Filed-F5-return ingestion (declared-vs-computed reconciliation) — PLANNED
Effort PROPOSED 1 wk. Owner Terry/Collin. Accept the filed F5 (manual entry or IRAS extract); compare declared vs computed per box; flag deltas (Step 1.3b output-tax threshold; Step 1.3d TP/TS > 1.2). Deterministic; surfaces, never auto-corrects. Closes the recurring ◐ across Steps 1, 3A.1.a, 3B.1.a, 3C.1.a, 3D.1.1.a. DoD: per-box declared-vs-computed reconciliation added to the report, replacing the current "Declared-vs-computed F5 comparison" Items-Not-Examined line.

### T2.10 — Mechanical gap-fills (deterministic checks currently ✗) — PLANNED
Effort PROPOSED 1.5–2 wk total. Owner Collin (audit-not-partner — implement in both tool and reference script). Invoice-sequence-gap over `DocNum` (3A.1.c/3B.1.b/3C.1.b → D); duplicate input-tax claims (3D.1.1.d → D); claim-outside-period (3D.1.1.c → D+, needs cross-period history); time-of-supply anomaly (3A.1.b → J+, needs payment-date ingestion); ZP+TaxTotal>0 E2 extension (open item #22, DocNum 610 → D, low effort).

### T2.11 — Reasoning-layer validation + indeterminate-queue reconciliation — PROVISIONAL → validate (the binding constraint)
Effort PROPOSED 2–3 wk engineering + specialist review time. Owner Terry (harness) + independent specialist (async reconciliation).

The reasoning layer is built and provisionally measured but unvalidated; the 2026-06-03 numbers are against an Opus-labelled fixture, so they are a smoke test, not validation. `show_ai_candidates` stays `False` for deliverables and `validation_status` stays `unvalidated` until an independent GST specialist reconciles the candidate queue. This calendar-gated review — not further build — is the binding constraint.

Scope: extend the T2.3 harness to compute the accuracy basket against T2.13's labelled set — FP (<5%), recall (>95%), severity calibration (>90% agreement), engineering reliability — tracked separately, never as one number; assemble the indeterminate/contested queue for review; on reconciliation, update `validation_status` and decide `show_ai_candidates` per client. Hardest part: keep validation independent from rule-authoring (the labeller of the validation-of-record must not be a rule author — circular validation; agreement ≠ correctness). DoD: measured basket; reconciled queue; auditable `show_ai_candidates` decision; canonical doc updated.

> Inspection vs validation: inspecting raw reasoning output in a dev/scratch run is fine (pre-validation). What stays gated is letting candidates into a signed working paper or describing them as validated. Looking ≠ blessing. Inspection artefacts marked `UNVALIDATED / DRAFT`.

### T2.12 — Extract-based delivery adapter (advisory-firm channel) — PLANNED
Effort PROPOSED 3–4 wk. Owner Terry/Collin. Advisory firms access client data via extracts, not live B1. Add an input adapter mapping CSV/Excel (later PINT-SG) to the same internal line-item schema so the chain/gates/report run unchanged. The MCP connector becomes one input adapter among several. DoD: a CSV extract produces identical chain output to the equivalent MCP run on the same data. **This refactor (decoupling input adapter from engine behind a stable schema/API) is also the architectural prerequisite for any future platform — see Tier 4.**

### T2.13 — Validation dataset construction (synthetic-paired + pilot-derived) — PLANNED (NEW)
Effort PROPOSED 1–2 wk to build the synthetic substrate; specialist labelling is external time. Owner Terry (build) + independent specialist (labels).

Business reason: T2.11 needs ground truth. Real IRAS-validated taxpayer data is not purchasable (confidential, and the literature confirms such labels are intrinsically scarce); acquiring it would import the very PDPA/confidentiality risk we are avoiding. The validation lever is **expert labelling of representative cases**, not "real" data — a synthetic SG-GST case labelled by an accredited specialist is better ground truth than foreign real data, because the system is judged against IRAS rules.

Scope:
- Construct synthetic but representative SG-GST cases spanning clearly-correct, clearly-wrong, and genuine edge cases, across the categories the reasoning layer claims (Reg 26/27 first).
- **For the current reasoning layer (Reg 26/27): labelled LINE ITEMS only are required** (it reads the line description; no invoice needed).
- **For the future document checks (T2.8): paired data is required** — synthetic invoice PDFs generated to pair with synthetic line items, with deliberate mismatches for positives (GST amount ≠ listing, wrong period, missing reg number).
- Independent specialist assigns the authoritative labels. The labeller of the validation-of-record must not be a rule author (cousin may label the dev set; an independent accredited specialist labels the holdout claimed against).
- Pilot upgrade path: once a pilot is live (under a DPA, T3.2), the firm's accredited reviewer's adjudications become real validated ground truth — the gold standard — superseding synthetic over time.

Uses of the labelled set (all evaluation, **not training**): (1) the validation gate / accuracy basket (T2.11); (2) the regression-eval reference re-run on every model/prompt change (T2.3); (3) few-shot exemplars to sharpen the reasoning layer (in-context, not weight updates); (4) the eval substrate that lets a check be packaged as an agent skill with a known accuracy and definition-of-done. The data never trains or fine-tunes a model — Claude is used via API.

---

## Tier 3 — Required Before Specific External Milestones

### T3.1 — SOC 2 readiness documentation — PLANNED
Trigger: enterprise procurement. Effort 4–6 wk docs (audit separate). Mostly documenting existing practices now that T1.5 exists. SG interim: DPTM (SS 714:2025), a year-2 goal.

### T3.2 — PDPA compliance framework — PLANNED
Trigger: first paid engagement on real client data, or Anthropic Partner Network application. Effort 2–3 wk with legal input. Purpose limitation, data minimisation, retention (≈7-year for tax workpapers per IRAS, then destruction), client-facing DPA template, Anthropic DPA evaluation. **Prerequisite for any pilot-derived ground truth (T2.13) and for the platform handling real client data (Tier 4).**

### T3.3 — BIG application technical exhibit — PLANNED
Trigger: BIG submission. Effort 2 wk. Architecture doc, V0→V3 narrative, 30/30 outcomes, commercial roadmap, demo walk-through. Lead with the validated deterministic story (v0-vs-v3 contrast); present the reasoning/document-ingestion layer as emerging, unvalidated, human-gated.

### T3.4 — Anthropic Partner Network application artefacts — PLANNED
Trigger: AP application. Effort 1–2 wk. Case study (V0→V3), technical write-up, sanitised SBODEMOSG sample deliverable.

### T3.5 — Singapore SAP B1 reseller channel materials — PLANNED
Trigger: conversations with named resellers. Effort 2 wk. Co-branded one-pager, pricing structure, engagement template, consultant training.

### T3.6 — InvoiceNow / GST InvoiceNow (PINT-SG) ingestion path — PLANNED
Trigger-gated; effort future. Owner Terry. As structured invoice fields arrive via Peppol, several J+ document-reads convert to D+ field-comparisons. Shares the T2.12 adapter seam. Phased mandate: voluntary registrants Apr 2026 → all GST-registered by Apr 2031.

---

## Tier 4 — Platform vision (north-star, GATED — do not start before the gate below)

### T4.1 — Consolidated multi-vertical agent platform / dashboard — VISION, NOT SCHEDULED
Owner Terry. Effort: large; not estimated until the gate is met.

**The vision.** A single platform/dashboard (analogous in spirit to Odoo or SAP B1) where an end user accesses multiple industry-vertical agents and pays per agent, with the Singapore GST accounting agent as the first vertical. A polished UI/dashboard fronting the engine, with per-agent metering for pricing.

**Gate (all must be true before any platform UI build begins):**
1. The GST agent's reasoning layer is **validated** (T2.11 complete) — not just built.
2. There is at least one **paying pilot** and evidence of demand for a dashboard delivery surface (customers who would log in and self-serve), not an assumption of it.
3. The **who-signs** question is resolved for the self-serve context: the GST agent surfaces candidates; an SCTP-accredited human signs the ASK working paper. A dashboard does not remove the reviewer of record — the platform must route to one (the firm's certifier, or the in-house team's external certifier).

**Why gated (honest flag).** The documented moat is **distribution + domain trust, not the tooling**, and the model is consulting/channel, **not pure SaaS**. A dashboard is a packaging/distribution surface; it does not address the distribution bottleneck and earns its build only once there is a validated, sold vertical to put in it. Building the container before the contents are proven spreads effort away from validation and first revenue. This is also the future state where the Anthropic Skill abstraction (Reminder #5) finally earns its place — but that, too, is post-validation.

**What to do now toward it (near-zero-cost option-keeping):** nothing UI. Keep the engine cleanly separable behind a stable internal schema/API (the T2.12 input-adapter refactor), and keep per-agent boundaries clean, so a dashboard can wrap the engine later without a rewrite. Architecture readiness is the only platform work that belongs in the present.

---

## Documentation tasks

### D1 — Update `AGENTASSIST_TECHNICAL_STATE.md` for the reasoning layer — DONE (2026-06-08, on T2.7 branch)
The canonical doc was reconciled against the repo: reasoning layer documented as branch-only (`t2.7-reasoning-reg2627`), `show_ai_candidates` wiring with line refs, provisional measurement marked UNVALIDATED, harness status updated, the 110 figure resolved as a 110-LINE fixture (not 110 invoices). Verify the diff and the second-modified-file (`v3` roadmap working-tree change) before committing.

### D2 — Document the `reasoning/` layer (T2.7 branch) — PLANNED
Mirror the deterministic-script docs for the reasoning layer; Document 4 of the coverage analysis is the conceptual basis. Capture what gaps it fills, the J+ ceiling, the two gates, and the validation status.

---

## Final Architectural Reminders

1. Three-layer separation is non-negotiable. Tools do arithmetic; KB is reference content; system prompt orchestrates.
2. The reference script is the audit, not the partner. Independent implementation; no shared code; divergence flags bugs.
3. Claude does not assert compliance positions unilaterally. Never assert without tool-confirmed evidence. Preserve "candidate for review" vs "confirmed error."
4. The reviewer signs off on every finding before submission. No automatic filing or IRAS contact, at any tier — including any future platform.
5. Don't add the Skill abstraction until the product expands beyond one workflow (this is the Tier 4 / multi-vertical future, post-validation).
6. The knowledge base is modular per chain-step. Data flows forward; regulatory context stays sliced per step.
7. Orchestration is a predefined code path, not autonomous agents. Gates are deterministic Python, never LLM calls.
8. Document ingestion expands recall, never authority. A read-derived finding caps at J+ (sole exception: invoice-date → correct-period → D+). Extracted fields never enter Layer 1, boxes, or gates. What converts J+ → D is structured data at source (InvoiceNow/PINT-SG), not reading a PDF.
9. The MCP connector is one input adapter, not the product. The engine accepts live MCP, CSV/Excel extracts, and (future) PINT-SG against one internal schema. This separability is also the platform prerequisite.
10. **(NEW) Labelled data is for evaluation, not training.** It powers validation, regression eval, few-shot exemplars, and skill definition-of-done. Claude is used via API; no weights are ever updated.

---

## Open integrity / doc-debt flags

- **Reasoning-layer numbers are a smoke test, not validation** — measured against an Opus-labelled (AI-generated) fixture. `show_ai_candidates` stays `False` for deliverables until an independent specialist reconciles ground truth (T2.11 + T2.13).
- **SBODEMOSG has no document attachments** — any T2.8 document-ingestion demo/build must supply its own invoice PDFs.
- **Test fixtures are live-seeded into SBODEMOSG and ephemeral** (tied to the SAP CAL instance). Static, repo-resident fixtures (open item #21) still do not exist. Seeding reasoning-bait for a demo will change Box 5/7 and document counts and so invalidate the stored deterministic reference figures — isolate in a separate client/period or re-baseline, and preserve the captured v0-vs-v3 evidence (it cannot be re-run identically once the DB changes).
- **All Singapore tax specifics** (materiality thresholds, Step-4 reconciliation thresholds, paragraph numbers) must be re-verified against the current IRAS e-Tax Guide edition before any customer-facing claim.
- **Strategy watch:** the platform vision (Tier 4) is a north-star, not a near-term build. Guard against drifting effort into a dashboard before one vertical is validated and sold; the bottleneck remains distribution + trust.
