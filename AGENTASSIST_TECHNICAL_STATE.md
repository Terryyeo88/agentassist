# AgentAssist — Technical State and Methodology Documentation

---

## Document purpose and scope

This document is a technical audit of the AgentAssist repository, produced on 2026-05-26 by
inspection of every source file, configuration file, experimental log, and test artefact in
the repository at that date. It is intended to serve as a self-contained reference for internal
decision-making and as grounding material for subsequent strategy conversations. It does not
presuppose familiarity with any prior conversation about the project.

The audit covers: repository structure and completeness, MCP tool implementation, knowledge base
content and accuracy, system prompt design, experimental methodology and evidence quality,
production readiness gaps, and security and data handling. It surfaces findings honestly,
including inconsistencies and gaps, regardless of how they reflect on the current state of the
work.

The repository is at `C:\Users\terry\Desktop\AgentAssist\sap-b1-ai-agent`. T1.3 and T1.6 are
on `master` (T1.6 merged 2026-06-01). T1.4 is on branch `t1.4-pdf-report-generation` (ready
to merge).

---

## Executive summary

**What has been built**

A functional three-layer AI compliance assistant for Singapore GST F5 preparation and
transaction review. The system consists of: (1) a custom Python MCP server providing 14 tools
for SAP B1 Service Layer access, including three purpose-built GST accounting tools; (2) a
curated knowledge base documenting Singapore VatGroup-to-F5-box routing rules with IRAS
citations; and (3) a system prompt enforcing procedural constraints, output format, and
environment awareness. The system runs locally via Claude Desktop on the developer's Windows
machine connected to a cloud-hosted SAP B1 SBODEMOSG demo database.

Two infrastructure layers have since been added. T1.3 (2026-05-31, `master`) delivered a
per-client YAML config system (`config/loader.py`, `config/clients/`) with credential
resolution, GST-rate sanity checking, VatGroup-collision detection, and an SAP connectivity
probe. T1.6 (2026-06-01, branch `t1.6-orchestration-chain`) replaced Claude's conversational
tool selection with a deterministic six-step orchestration chain (`orchestrator/`) gated by
five pure-Python reconciliation checks; the chain runs as
`python run_agent.py --client sbodemosg --period 2024-07-01 2024-09-30` and writes structured
JSON output to `exploration-notes/t1.6-tool-outputs/`.

**What has been validated**

A four-version controlled experiment was run against Q3 2024 data from SBODEMOSG. Two of the
three defined tests have been completed for all four versions. Test 1 (F5 calculation) and
Test 2 (tax code classification) both achieve 10/10 at v3, demonstrating zero arithmetic error
and perfect VatGroup recall. The v0 baseline comparison is well-documented: plain Claude
produced an SGD 3,480 overpayment figure for Box 8 and invented a "critical" compliance
finding (the 7%/9% rate gap) that would have caused material harm if acted upon. Both failures
are traceable to specific architectural gaps that the system prompt and custom tools subsequently
closed.

Test 3 has now been completed for all four versions (V0, V1, V2, V3).
V3 achieves 10/10. The full V0 → V3 trajectory across all three tests
is 12/30 → 13/30 → 25/30 → 30/30. The V1 → V2 Test 3 delta (+6) is the
most informative single result in the experiment: it isolates the
incremental contribution of the system prompt, including elimination
of the V1 F7 filing fabrication and a structural shift from narrative
spot-check methodology to population-level analysis. See
exploration-notes/baseline-test-results.md for full per-test scoring
and the V1/V2 Test 3 Reclassification Note documenting a methodological
contamination discovery.

Two post-experiment implementation tasks have since been completed. T1.2
(2026-05-27) resolved the NR VatGroup inconsistency: NR is now excluded from
Box 5 per IRAS para 5.11(o) across tool code, reference script, and system
prompt, with a known E2 fixture (DocNum 611) seeded for validation. T1.1
(2026-05-28) added credit note support: all three custom tools now fetch
CreditNotes and PurchaseCreditNotes and subtract their line amounts from the
relevant F5 boxes, with two seed credit notes validating the implementation.

**What is genuinely production-ready versus prototype**

Production-ready: the VatGroup → F5 box mapping logic, the FX exclusion and E1 detection
logic, the pagination handling, and the system prompt's orchestration rules. These are
implemented cleanly, tested against reference figures, and produce correct output.

Prototype only: the overall delivery mechanism (Claude Desktop + stdio) and the audit trail
(none exists). Per-client configuration is resolved (T1.3). The deterministic orchestration
chain (T1.6) replaces Claude's conversational tool selection and produces structured JSON.
Report generation is resolved (T1.4, 2026-06-01): the `report/` package consumes
`CompileOutput` and renders a signed PDF deliverable; `python run_agent.py --report` triggers
it end-to-end.
Test 3 capability is now validated at 10/10 on SBODEMOSG Q3 2024.

**The three to five most important gaps before commercial deployment**

1. RESOLVED (T1.1, 2026-05-28): Credit note support added to all three custom tools.
   `CreditNotes` and `PurchaseCreditNotes` are now fetched and their amounts subtracted from
   the corresponding F5 boxes. Two SBODEMOSG seed credit notes (CN A: CreditNotes/SO/1000.00,
   CN B: PurchaseCreditNotes/SI/500.00) validate the implementation against live data.
2. RESOLVED (T1.3, 2026-05-31): Per-client YAML config (`config/clients/<id>.yaml`),
   `load_client_config()` with full validation pipeline, credential env-var resolution,
   VatGroup-collision detection, and optional SAP connectivity probe. Switching clients is
   now a YAML file + env-var change. `config/clients/sbodemosg.yaml` is the first client.
3. RESOLVED (T1.4, 2026-06-01): Report generation delivered. `report/` package: contract →
   enrich/routing → sections → render; `run_agent.py --report`; `CompileOutput` is the input
   (ReportInput is a deprecated stub); classify↔detect join by (doc_num, error_code);
   Document-2 template routing; 124 tests passing.
4. No audit trail or input immutability. A conversational Claude Desktop window is not a
   defensible work product for a GST review engagement.
5. RESOLVED (T1.2, 2026-05-27): NR VatGroup corrected to Excluded across tool code, reference
   script, and system prompt. NR is now excluded from Box 5 per IRAS para 5.11(o). DocNum 611
   seeded as a known NR E2 fixture (LineTotal 500.00, TaxTotal 45.00 at 9% — rate anomaly vs
   SBODEMOSG 7% demo norm, documented in test_data_registry.json and
   nr-vatgroup-resolution.md).

**The three to five strongest assets**

1. The v0 failure story is compelling and specific: SGD 3,480 Box 8 overpayment and a false
   "critical" IRAS disclosure recommendation are concrete, quantified, verifiable failures that
   a non-expert buyer can understand.
2. The V0 → V3 Test 3 progression is unusually informative: V0 invented an erroneous
   voluntary disclosure recommendation; V1 reproduced the fabrication as an F7 filing
   recommendation; V2 eliminated the fabrication AND shifted Claude's analytical approach from
   narrative spot-check to population-level analysis (visible in tool-call inventories); V3
   added supplier-level deduplication and reduced tool-call count by ~60%. Each layer's
   contribution is quantifiable and the failure modes are concrete and demo-ready.
3. The knowledge base is well-constructed with accurate IRAS e-Tax Guide citations (11th
   Edition, January 2026), making it credible to a tax-literate buyer.
4. The three-layer architecture is cleanly implemented and the separation of concerns is
   maintained: tools do arithmetic, Claude reasons, the system prompt orchestrates.
5. The experimental methodology is internally consistent and the raw evidence trail is complete
   for all three tests across all four versions.
6. The system prompt's SBODEMOSG rate-artefact handling demonstrates the kind of
   context-aware, non-hallucinating behavior that differentiates the system from plain Claude.

---

## Business framing and value proposition

This section captures the product positioning that the experimental work
has validated. It should be read alongside the technical sections below;
the technical architecture is what it is *because* the business framing
demands it.

### Product

AgentAssist provides line-level GST compliance review for mid-market
Singapore SAP B1 clients. The system combines deterministic
rule-checking (every transaction examined for E1/E2/E3/E4/NO_GST_REG
errors) with applied judgment on edge cases (semantic VatGroup
appropriateness, cross-finding correlation, novel error patterns) and
produces a signed-off PDF report ready for IRAS pre-filing review.

### Conceptual model

AgentAssist functions as a **junior accountant** that a senior financial
officer can orchestrate to accelerate their own workflows. The system
performs the line-level review work that would otherwise require 20-40
hours of senior reviewer time per quarter per client. The senior
reviewer applies judgment on the edge cases the system surfaces,
accepts/rejects/escalates each finding, and signs off on the final
report before submission to IRAS.

The human-in-the-loop boundary is explicit and non-negotiable:
- The system performs detection and surfaces findings with applied
  judgment on edge cases. It never asserts compliance positions
  unilaterally.
- The senior reviewer (typically the client's lead financial officer
  or an external accountant) reviews every finding before sign-off.
- The signed report carries the reviewer's professional name and
  responsibility, not the system's.

This boundary is encoded architecturally: the system prompt's
compliance assertion rule ("never assert a compliance issue without
tool-confirmed evidence") prevents the system from producing the kind
of unaccompanied, confident compliance recommendations that the V0/V1
experiments demonstrated to be dangerous.

### The judgment layer (what distinguishes this from an automated script)

The architecture has three layers, but the commercial differentiation
lives in how they work together rather than in any single layer:

1. **Deterministic rule-checking** (custom MCP tools) catches mechanical
   errors: foreign currency miscoding, blocked input tax with non-zero
   GST, suppliers with blank registration numbers. A Python script could
   do this alone.

2. **Applied judgment on edge cases** (Claude reasoning, guided by
   knowledge base and system prompt) catches issues that require
   semantic interpretation: whether "Financial Advisory Service" is
   genuinely a Reg 33 exempt service, whether a ZR line with a
   Singapore ship-to address is a real export, whether two findings on
   the same DocNum should be cross-correlated for prioritization. A
   pure script cannot do this; an unaccompanied LLM does it
   unreliably (V0/V1 failure mode).

3. **Procedural enforcement** (system prompt) ensures Claude reasons
   conservatively: only surfaces edge cases for reviewer judgment, never
   asserts conclusions, always cites the data underlying each finding.
   This is what prevents the V1 F7 fabrication and makes the surfaced
   edge cases actionable rather than dangerous.

The V0 → V3 experimental progression demonstrates this empirically: V0
(unaccompanied Claude) invents dangerous compliance recommendations; V1
(knowledge base alone) reproduces the fabrications; V2 (system prompt
added) eliminates the fabrications and enables population-level
analysis; V3 (custom tools added) achieves deterministic precision
without sacrificing the judgment layer. See
`exploration-notes/baseline-test-results.md` for full per-version
scoring.

### Pricing model

Per-engagement, per-quarter, per-client. Not per-seat subscription.

This reflects what is actually being sold: a defined deliverable (the
signed PDF review report) produced at a defined cadence (quarterly,
aligned with F5 filing) for a defined client (one SAP B1 instance, one
GST registration). It also aligns with how mid-market Singapore finance
teams already buy tax services from accounting firms — the engagement
model is familiar; the difference is the cost-per-engagement at
AgentAssist scale.

### Operational economics

Without AgentAssist: a senior accountant performing line-level GST
review samples 10-20% of transactions (because comprehensive review is
intractable at hourly cost), spending 20-40 hours per quarter per
client.

With AgentAssist: the system reviews 100% of transactions
deterministically and surfaces edge cases for senior review. Senior
reviewer time drops to approximately 2-4 hours per quarter per client
(reviewing surfaced findings, applying judgment, signing off).

This is approximately a 5-10x reduction in senior reviewer hours per
client, while expanding coverage from sampling to population. The
economic value can be captured either as "same revenue per client, much
lower cost per engagement" (margin expansion for the reviewer/firm) or
"same total reviewer hours, 5-10x more clients served" (capacity
expansion).

### Delivery format

The end deliverable is a structured PDF report containing:
- Methodology disclosure (what was examined, what was not)
- Period and data scope (date range, record counts, FX exclusions)
- F5 box table with VatGroup attribution
- Error findings sorted by severity (E1, E2, NO_GST_REG, etc.) with
  DocNums, line-level detail, and recommendations
- Edge cases surfaced for human judgment (semantic appropriateness,
  ambiguous classifications)
- Cross-finding synthesis (e.g., "DocNum X carries both NO_GST_REG and
  E2 flags — highest priority document")
- Explicit list of items not examined (credit notes if still unhandled,
  manual journals, custom VatGroups)
- Reviewer's signature block
- Disclaimer

This is the IRAS-compliant document that the senior financial officer
signs and either files directly or hands to their accountant for final
submission. The conversational Claude Desktop interface is not the
deliverable; it is the workspace where the system is operated.

### Target customer segment

**Primary**: In-house finance teams at mid-market Singapore SAP B1
clients. These teams currently perform F5 preparation in-house but
have insufficient capacity for line-level pre-filing review. They feel
exposure to IRAS audit risk but cannot justify additional headcount.
AgentAssist gives them the review they wish they had time for.

**Secondary**: Tax/GST advisory practices serving multiple SAP B1
mid-market clients. These firms can deliver line-level review to their
clients as a productized service offering, with AgentAssist providing
the operational machinery and the firm providing the reviewer-of-record.
Distribution model: partner with Singapore SAP B1 resellers as channel,
similar to US Vertex/Kintsugi/CPA.com playbook.

### Forward expansion (post-GST)

The current implementation focuses on Singapore GST F5 because it is
tractable, well-bounded, and tied to a known regulatory deadline. The
architectural pattern (deterministic tools + judgment layer +
orchestration + human sign-off) generalizes to other compliance
workflows: F7 disclosure of errors, more complex partial exemption
calculations, IGDS reporting for approved participants, and eventually
adjacent regimes (Malaysia SST, Vietnam VAT). Each expansion is a new
knowledge base + new tools + same architectural pattern.

Future capability expansion will move toward fully agentic workflows
with orchestration handling multiple parallel tasks within a single
engagement (e.g., F5 preparation + supplier registration verification +
prior-period reconciliation in a single integrated workflow). The
current single-workflow architecture is a starting point, not the end
state.

### What this means for the technical roadmap

The business framing above implies specific technical priorities:

- **Report generation** — RESOLVED (T1.4, 2026-06-01): the `report/` package delivers the
  signed PDF. See § T1.4 for full detail.
- **Per-client configuration** is critical-path: without it, the system
  cannot be deployed beyond SBODEMOSG. See § Per-client configuration.
- **Credit note support** is critical-path: most real clients have
  credit notes; F5 figures without credit note handling are wrong.
- **Audit trail / immutable logging** is required for the reviewer
  sign-off model: the reviewer must be able to demonstrate to IRAS
  (if audited) which data was examined and how findings were derived.

Less critical to the current business model:
- Agent skills (Anthropic skill packaging): the current product is a
  single workflow; skills become relevant when the product expands to
  multiple distinct deliverable types or adjacent jurisdictions.
- Automated evaluation harness: needed for ongoing regression testing
  as the product matures, but not gating first revenue.

---

## Repository structure

The repository has seven substantive directories and three files at root level that warrant
note.

```
sap-b1-ai-agent/
├── README.md                              ← Severely outdated; describes Phase 1 setup state
├── .gitignore                             ← RESOLVED: renamed to .gitignore; functional
├── .env                                   ← gitignored; demo credentials for local development
├── git                                    ← DELETED 2026-05-27
├── claude-code-master-prompt-phase2-tools.md ← Historical Claude Code prompting spec; reference only
├── config/
│   ├── clients/
│   │   ├── example.yaml                   ← Schema template for per-client config
│   │   └── sbodemosg.yaml                 ← SBODEMOSG client config (credentials via env vars)
│   ├── loader.py                          ← T1.3: load_client_config → ClientConfig; 8-step validation
│   └── env.example                        ← Template for SAP B1 connection env vars
├── exploration-notes/
│   ├── baseline-test-results.md           ← Primary experimental log; production-ready document
│   ├── baseline-test-report-v0.json       ← Machine-generated reference run; authoritative
│   ├── v0-raw-chats/                      ← Complete: test1, test2, test3 raw logs; README
│   ├── v1-raw-chats/                      ← Complete: test1, test2, test3 raw logs
│   │   ├── test1-f5-calculation.md        ← v1 Test 1 raw log
│   │   ├── test2-f5-calculation.md        ← Misnamed: is Test 2 (tax classification), not Test 1
│   │   ├── test3-error-detection.md       ← v1 Test 3 raw log; 3/10; clean re-run after contamination discovery
│   │   └── image.png                      ← Unknown; no reference to it in other files
│   ├── v2-raw-chats/                      ← Complete: test1, test2, test3 raw logs
│   │   ├── test1-f5-calculation           ← Missing .md extension; is v2 Test 1 raw log
│   │   ├── test2-tax-classification.md    ← v2 Test 2 raw log; complete and well-formatted
│   │   └── test3-error-detection.md       ← v2 Test 3 raw log; 9/10; reclassified from initial "V1" run
│   ├── v3-raw-chats/                      ← Complete: test1, test2, test3 raw logs
│   │   ├── test1-f5-calculation.md        ← v3 Test 1 raw log; confirms 10/10 result
│   │   ├── test2-tax-classification.md    ← v3 Test 2 raw log; confirms 10/10 result
│   │   └── test3-error-detection.md       ← v3 Test 3 raw log; 10/10; all 19 reference findings
│   ├── security-decisions.md              ← Deferred-decision register for credentials in git history
│   ├── docnum-605-verification.md         ← Live SAP query confirming BL line TaxTotal=56.00
│   ├── nr-vatgroup-resolution.md          ← T1.2 investigation: NR excluded from Box 5; DocNum 611 E2 fixture notes
│   ├── credit-note-exploration.md         ← T1.1 pre-impl exploration + implementation summary + post-seed reference figures
│   └── t1.1-verification.md               ← Read-only verification pass: NR T1.2 completeness, rate check, delta check
│   ├── t1.6-scope.md                      ← T1.6 scope and design doc; gate pseudocode; chain step schemas
│   ├── codebase-state-report.md           ← 2026-05-28 frozen audit snapshot (pre-T1.3/T1.6); historical only
│   ├── t1.6-tool-outputs/                 ← chain-run-<ts>.json outputs (generated; path provisional pending T1.5)
│   └── t1.4-reports/                      ← Generated PDF reports (generated; gitignored)
├── keys/
│   ├── sap_credentials.json               ← CRITICAL: plaintext credentials; untracked but unprotected
│   └── sap-b1-poc-sg.pem                  ← SSH PEM key for SAP CAL instance; untracked
├── knowledge-base/
│   └── sg-tax-code-mappings.md            ← Only knowledge base file; appears production-ready
│                                          ← Note: no IRAS source PDFs loaded at runtime; synthesis is the runtime knowledge
├── mcp-servers/
│   ├── custom/
│   │   ├── sap_b1_server.py               ← Primary MCP server; 837 lines; credit notes + NR E2 added (T1.1/T1.2)
│   │   ├── requirements.txt               ← Three dependencies (mcp, httpx, python-dotenv)
│   │   ├── README.md                      ← Setup and tool inventory; accurate
│   │   └── __pycache__/                   ← Python bytecode cache
│   └── MCP-SAP/                           ← Third-party HTTP MCP server (Spanish, FastAPI)
│                                          ← Not used; retained as reference; separate git repo
├── orchestrator/                          ← T1.6: deterministic chain package
│   ├── __init__.py
│   ├── chain.py                           ← run_chain(client_config, period) → (ReportInput, Path)
│   ├── exceptions.py                      ← GateFailure, ChainError
│   ├── gates.py                           ← gate_1 … gate_5; pure arithmetic / set-membership; no LLM
│   ├── schemas.py                         ← TypedDicts for all inter-step data shapes
│   └── steps.py                           ← fetch, calculate, classify, detect, compile, report_input
├── report/                                ← T1.4: signed PDF report generator
│   ├── __init__.py                        ← generate_report(compile_output, client_config) → Path
│   ├── contract.py                        ← Input type aliases; CompileOutput is the T1.4 input
│   ├── enrich.py                          ← Three-source join keyed by (doc_num, error_code)
│   ├── routing.py                         ← Document-2 IRAS template routing; E2-by-VatGroup; Template 4/5
│   ├── sections.py                        ← Eight report sections as structured dicts
│   └── render.py                          ← Section dicts → PDF
├── run_agent.py                           ← CLI: --client <id> --period <start> <end> [--report]
├── scripts/
│   ├── run_baseline_tests.py              ← Reference implementation; T1.1 updated: credit notes + NR E2
│   ├── seed_test_data.py                  ← Creates synthetic test documents (7 invoices + 2 credit notes)
│   ├── cleanup_test_data.py               ← Cancels seeded test invoices
│   ├── test_data_registry.json            ← DocEntry registry; updated with credit notes and DocNum 611 tax_rate_note
│   └── test-service-layer.sh              ← Basic connectivity test; shell script
├── skills/                                ← Directory exists; entirely empty
├── tests/
│   ├── fixtures/
│   │   └── chain-run-sample.json          ← Static CompileOutput fixture for T1.4 e2e test
│   ├── test_chain.py                      ← 11 hermetic acceptance tests; no live SAP; Gate 2 acceptance test
│   ├── test_enrich.py                     ← T1.4: three-source join, (doc_num, error_code) aggregation
│   ├── test_gates.py                      ← 30 unit tests; all five gates; pure Python
│   ├── test_report_e2e.py                 ← T1.4: full end-to-end from CompileOutput fixture to PDF
│   ├── test_routing.py                    ← T1.4: Document-2 template routing, Template 4/5 switching
│   └── test_sections.py                   ← T1.4: eight sections, HitL language invariants
└── system-prompts/
    ├── base.md                            ← Primary orchestration prompt; production-ready
    ├── test1-prefix.md                    ← Task prefix for F5 calculation; working
    └── test2-prefix.md                    ← Task prefix for tax classification; working
```

### Notes on specific files

**`.gitignore` (root level, RESOLVED 2026-05-27)**: Renamed from `gitignore` to `.gitignore`.
Git now recognises it as an ignore specification. The `keys/` directory and `.env` file are
properly excluded from staging. Note: the credential files (`sap_credentials.json`,
`sap-b1-poc-sg.pem`) exist in the initial commit history (aec650f9) and have not been scrubbed
from git history. See `exploration-notes/security-decisions.md` for the deferred-decision
register and the conditions that trigger a mandatory history scrub.

**`git` (root level, 0 bytes, DELETED 2026-05-27)**: Was an empty file named `git`, almost
certainly created by accidentally running `git > git` or a similar shell mishap. Deleted.

**`README.md`**: Describes the project as being in "Phase 1 — Environment Setup" and uses
parenthetical placeholders for content that now exists (e.g., `(sg-gst-tax-codes.md)`,
`(f5-return.md)`). The folder structure described does not match the current repository state.
This file has not been updated since the initial commit and should not be treated as current
documentation.

**`skills/` directory**: Empty. The README references planned skill files
(`gst-validation.md`, `invoice-creation.md`, `f5-return.md`) that have never been created. A
planned v4 skill (full workflow) is referenced in the improvement tracking table but does not
exist.

**`mcp-servers/MCP-SAP/`**: A third-party Spanish-language HTTP-based MCP server cloned from
GitHub (NXr10/MCP-SAP). It exposes only three tools (connect, status, create sales order) and
was built for Microsoft Copilot Studio. It is not used in the project. The custom server's
README explains why it was replaced. The MCP-SAP directory has its own `.git` repo and
functions as an embedded submodule without being formally declared as one.

**`v1-raw-chats/test2-f5-calculation.md`**: The filename says "f5-calculation" but the file
contains the v1 Test 2 (tax code classification) raw response. This is a naming error with no
functional consequence, but it complicates navigation of the evidence trail.

**`v2-raw-chats/test1-f5-calculation`**: Missing the `.md` extension. The file contains the
v2 Test 1 raw response and was processed correctly by the audit.

**`v1-raw-chats/image.png`**: An image file with no reference in any other file. Its content
and purpose are unknown. No other file links to it or describes it.

---

## Architecture as built

### Three-layer separation

The three-layer architecture is cleanly implemented in practice, with one minor anomaly.

**Layer 1 — Deterministic (MCP tools)**: All arithmetic, all data fetching, and all
rule-based classification live in `sap_b1_server.py`. The F5 box calculation, VatGroup routing,
FX filtering, E1-E4 per-line checks, COMPLETENESS threshold check, and NO_GST_REG supplier
lookup are all Python code. Claude is explicitly removed from the arithmetic path by the system
prompt's tool-preference order.

**Layer 2 — Reasoning (Claude + knowledge base)**: Interpretation of tool output, judgment on
edge cases (e.g., "is this E1 candidate actually an export?"), and narrative construction live
in Claude's response generation, guided by `sg-tax-code-mappings.md`.

**Layer 3 — Orchestration (system prompt)**: `base.md` specifies tool selection order,
mandatory pagination rules, period defaulting logic, FX exclusion enforcement, output format,
and environment-awareness constraints (the 7%/9% demo artefact rule).

**The minor anomaly**: The system prompt's `base.md` includes a full VatGroup routing table
and F5 box definition table that duplicates content in `sg-tax-code-mappings.md`. This is
intentional as a fallback (the system prompt is always active, the knowledge base is
project-level context that may not always load), but it creates a maintenance surface where the
two documents could drift. One discrepancy already exists: see the NR VatGroup section below.

### Data flow

```mermaid
graph LR
    A[User prompt] --> B[Claude Desktop]
    B -->|MCP stdio| C[sap_b1_server.py]
    C -->|HTTPS + OData| D[SAP B1 Service Layer]
    D -->|Invoices / PurchaseInvoices / BusinessPartners| C
    C -->|Structured JSON string| B
    B -->|Claude reasoning| E[Formatted response to user]
    F[sg-tax-code-mappings.md] -.->|Knowledge base context| B
    G[base.md system prompt] -.->|Orchestration rules| B
```

The custom MCP tools (Tools 12-14) handle the accounting-specific data path. The generic tools
(Tools 1-11) provide raw OData access for ad-hoc queries, write operations, and exploration.

### Where the deterministic layer ends and the reasoning layer begins

The three custom tools return structured JSON with findings described in plain English strings
(e.g., `"description": "FX invoice (USD) with SO code — should likely be ZR for overseas
sales"`). The tools do not make reclassification decisions; they flag candidates and provide
recommendations. Claude synthesizes these into a formatted response and applies the compliance
assertion rules from the system prompt: no definitive compliance claims without tool-confirmed
evidence.

The E1 detection illustrates this correctly: the tool flags FX+SO combinations as "candidates
for review." The system prompt reinforces: "Acceptable: 'DocNum 958 appears to be an E1
candidate.' Not acceptable: 'DocNum 958 is miscoded and must be reclassified.'" The system
maintains the appropriate epistemic posture at each layer.

### Architectural debt

One resolved and one remaining design question:

1. **Credit notes**: RESOLVED (T1.1, 2026-05-28). All three custom tools now call
   `_fetch_credit_notes_paginated(entity_type, period_start, period_end)`, which fetches
   `CreditNotes` (entity_type="sales") or `PurchaseCreditNotes` (entity_type="purchases"),
   tags each record `is_credit_note=True`, and returns the list. Callers negate LineTotal
   and TaxTotal when subtracting from F5 boxes — negation is explicit at the call site, not
   inside the fetch function. Two SBODEMOSG seed credit notes confirm correct reference figures.

2. **Per-client configuration**: RESOLVED (T1.3, 2026-05-31). `config/loader.py` loads
   per-client YAML from `config/clients/<id>.yaml`, resolves credentials from env vars, validates
   GST rate and VatGroup codes, and optionally probes SAP connectivity. `configure_client()`
   (T1.6) injects the resolved credentials into `sap_b1_server` at chain-run time without
   importing `config/` into `mcp-servers/` — dependency direction preserved.

---

## T1.3 — Per-client configuration (RESOLVED 2026-05-31)

`config/loader.py` provides `load_client_config(client_id, *, check_connectivity=True) → ClientConfig`. Per-client config YAML lives in `config/clients/<id>.yaml`; `sbodemosg.yaml` is the first.

**Validation pipeline** (each step fails with a human-readable message):
1. Locate and parse `config/clients/<id>.yaml`
2. Validate required fields (`client_id`, `client_name`, `applicable_gst_rate`, `sap_b1` block)
3. `client_id` must match filename stem
4. Resolve credential env-var names to values (stores values, never stores var names)
5. Sanity-check `applicable_gst_rate` in `[0.05, 0.15]`
6. Detect `custom_vat_groups` collisions with the 17 standard IRAS VatGroup codes
7. Optional SAP login probe (logs out immediately on success; skipped by consumers that manage sessions)

**`ClientConfig` fields**: `client_id`, `client_name`, `gst_registration_number`, `applicable_gst_rate`, `service_layer_url`, `company_db`, `username`, `password`, `ssl_verify`, `fiscal_year_start_month`, `custom_vat_groups`, `completeness_threshold`, `reviewer_name`, `firm_name`.

**Independence contract**: `config/loader.py` has zero dependency on `mcp-servers/` or `scripts/`. Both may import it; they must not import each other.

---

## T1.6 — Deterministic orchestration chain (COMPLETE 2026-06-01)

**What it replaced**: Claude's conversational tool selection — the model deciding at runtime which MCP tools to call and in what order. For an auditable GST review, "Claude decided to skip validate_invoice_tax_codes" is not defensible; the chain makes that impossible.

### Package: `orchestrator/`

| File | Responsibility |
|---|---|
| `chain.py` | `run_chain(client_config, period) → (ReportInput, Path)` — top-level entry point; calls configure_client, runs six steps and five gates, writes output JSON |
| `steps.py` | Six step functions: `fetch`, `calculate`, `classify`, `detect`, `compile`, `report_input` |
| `gates.py` | Five gate functions (`gate_1_record_count` … `gate_5_cross_tool_consistency`); each raises `GateFailure` on halt; no LLM calls |
| `schemas.py` | TypedDicts for all inter-step shapes (`Period`, `FetchManifest`, `F5ReturnOutput`, `ClassifyOutput`, `DetectOutput`, `CompileOutput`, `ReportInput`, …) |
| `exceptions.py` | `GateFailure(Exception)`, `ChainError(Exception)` |

**CLI**: `python run_agent.py --client sbodemosg --period 2024-07-01 2024-09-30`

**Chain sequence**:
```
fetch → gate_1 → calculate → gate_2 → classify → gate_3 → detect → gate_4
      → compile → gate_5 → report_input → write chain-run-<ts>.json → return ReportInput
```

**Five deterministic gates** (pure arithmetic / set-membership, never an LLM call):

| Gate | After | Check |
|------|-------|-------|
| 1 | Fetch | SAP `$inlinecount` vs fetched count; warn-pass when unavailable |
| 2 | Calculate | `box_4 == box_1+box_2+box_3` and `box_8 == box_6−box_7` (tolerance 0.01) |
| 3 | Classify | `summary.total == len(issues)` and all issue VatGroups present in inventory |
| 4 | Detect | `sum(severity_counts) == len(issues)` and no dangling `doc_num` references |
| 5 | Compile | E1 doc_num sets agree across calculate/detect; unknown VatGroups agree across calculate/classify |

**Output**: `exploration-notes/t1.6-tool-outputs/chain-run-<YYYYMMDD-HHMMSS>.json` (full `CompileOutput`). Path provisional pending T1.5 audit-trail integration.

**Connection seam**: `configure_client(service_layer_url, company_db, username, password, ssl_verify, custom_vat_groups)` added to `sap_b1_server.py`. Takes primitives; no `config/` import into `mcp-servers/` — dependency direction preserved. The module-level init (`_load_sap_config()`) is now wrapped in try/except so the module imports cleanly even when `CLIENT_ID` is not set; `configure_client()` overwrites the global `sap` client before any step function runs.

**Design decisions and known limitations**:

- **Gate 1 dormancy**: SBODEMOSG's SAP B1 Service Layer (version 1000250) does not return `odata.count` for `$inlinecount=allpages` queries. Gate 1 always warn-passes on this instance; pagination completeness is verified only structurally (`len(page) < 20` sentinel in the fetch helper), not arithmetically against a SAP-reported total.
- **~4× redundant fetch (tech-debt)**: Steps b/c/d (`calculate`, `classify`, `detect`) each re-fetch from SAP independently. The Fetch step (step a) builds only the `FetchManifest` (doc_nums set for Gate 4, items_examined for the report); it does not pre-fetch on behalf of the tool steps. Each chain run makes ~4× the minimum necessary SAP round-trips. Deferred to T1.6.1.
- **Source-adapter decision deferred**: The three tool-step functions call `sap_b1_server` directly. Substituting an alternative source (CSV extract, test fixture) would require changing step function signatures. Deferred until a second source adapter is needed.
- **`compile` step**: Aggregates four step outputs deterministically. Surfaced warnings are built from data (not scraped from logs): Gate 1 inline-count absence, Gate 2 calc anomalies, Gate 3 unknown-VatGroup entries.
- **`report_input` step**: Shapes `CompileOutput` into the flat `ReportInput` dict T1.4 will consume. Detect issues are sorted HIGH → MEDIUM → LOW then by doc_num (COMPLETENESS issues, which carry `doc_num=None`, sort last). T1.4 will later join `classify` issues onto detect issues by `(doc_num, error_code)` to enable E2-by-VatGroup routing — deferred reconciliation.

**Test state**: **41/41 tests pass** (`tests/test_gates.py`: 30 unit tests across all five gates; `tests/test_chain.py`: 11 hermetic acceptance tests covering clean run, Gate 2 acceptance test with corrupted box_4, and three gate-failure paths via the full chain — no live SAP in any test).

**Live validation** (2026-06-01, SBODEMOSG Q3 2024):
```
Items examined : purchase_credit_note=1, purchase_invoice=21, sales_credit_note=1, sales_invoice=50
box_8 (net GST): 17,045.87   (matches T1.1 reference figures)
Issues (detect): 21
Warnings       : 1 (Gate 1 $inlinecount unavailable)
Exit           : 0
```

---

## T1.4 — Signed PDF report generator (COMPLETE 2026-06-01)

### Package: `report/`

| Module | Role |
|--------|------|
| `contract.py` | Input type aliases; declares `CompileOutput` as the T1.4 input contract |
| `enrich.py` | Three-source join: classify amounts + detect severity + manifest backfill; keyed by `(doc_num, error_code)` |
| `routing.py` | Document-2 IRAS template routing — E2-by-VatGroup branching, Template 5 default, Template 4 via `actively_makes_exempt_supplies` config flag |
| `sections.py` | Builds each of the eight report sections as structured dicts |
| `render.py` | Converts section dicts to PDF |
| `__init__.py` | Public surface: `generate_report(compile_output, client_config) → Path` |

**CLI**: `python run_agent.py --client sbodemosg --period 2024-07-01 2024-09-30 --report`

### Input contract decision

T1.4 consumes the full `CompileOutput` JSON produced by the T1.6 chain — not the flat `ReportInput` dict. `ReportInput` (defined in `orchestrator/schemas.py`) is now a deprecated stub retained for backward compatibility; it is no longer the T1.4 input surface.

The switch was made because `CompileOutput` carries the full three-source structure (classify issues, detect issues, manifest) that T1.4 needs for enrichment and routing. `ReportInput` had already discarded per-source detail before T1.4 could access it.

### Three-source join: (doc_num, error_code) aggregation

`enrich.py` aggregates findings from three sources:

1. **`classify` output** — per-line issues from `validate_invoice_tax_codes`; carries VatGroup, LineTotal and TaxTotal amounts.
2. **`detect` output** — per-finding severity assignments from `detect_gst_errors`; carries severity (HIGH/MEDIUM/LOW) and description.
3. **`manifest` backfill** — FetchManifest doc_num set; used to confirm coverage and handle findings (COMPLETENESS, NO_GST_REG) that have no per-line VatGroup counterpart in classify.

The join key is `(doc_num, error_code)`. COMPLETENESS findings (`doc_num=None`) take the backfill path directly without classify enrichment.

### Document-2 IRAS template routing

`routing.py` maps each E2 finding to the correct IRAS GST return amendment template based on VatGroup:

- **E2-by-VatGroup branching**: the applicable template depends on the specific zero-rated or exempt VatGroup — the E2 error code alone is not sufficient for routing.
- **Template 5 default**: findings without a specific Document-2 assignment route to Template 5.
- **Template 4** is used instead of Template 5 when `actively_makes_exempt_supplies` is set in `ClientConfig` — reflecting the IRAS distinction between businesses that make exempt supplies as a principal activity vs. incidentally.

### Eight report sections

1. **Cover / metadata**: client name, GST registration, period, run timestamp, reviewer name and firm.
2. **Methodology disclosure**: what was examined (SGD invoices, purchase invoices, credit notes), what was excluded (FX, manual journals, custom VatGroups), and the data source.
3. **Data scope**: period, record counts by entity type, items examined count, FX exclusions.
4. **F5 box table**: all eight boxes with VatGroup attribution per box.
5. **Error findings**: issues sorted HIGH → MEDIUM → LOW then by doc_num; each includes DocNum, date, counterparty, error code, description, IRAS template routing (where applicable), and recommendation.
6. **Edge cases for reviewer judgment**: findings flagged for human review (semantic VatGroup appropriateness, ambiguous E1 candidates, cross-finding correlation).
7. **Items not examined**: explicit list — FX invoices pending conversion, manual journals, custom VatGroup transactions, COMPLETENESS context.
8. **Reviewer sign-off block**: reviewer name, firm, date, and signature line; disclaimer that the report is a working paper and not an IRAS submission.

### Human-in-the-loop invariant

The report contains no system-generated filing directives. The system surfaces findings and routes them to the applicable IRAS template; the reviewer determines whether to accept, escalate, or dismiss each finding and signs the final document. The signed report carries the reviewer's professional name and responsibility. This invariant is enforced in `sections.py`: findings use language such as "candidate for review" and "recommend verification" rather than "must reclassify" or "submit amendment."

### Appendix 1 wording

Appendix 1 of the report (IRAS amendment framework reference) sources its wording verbatim from the IRAS ASK Guide, 16th edition, pp. 72–73. It does not derive from the coverage-analysis exploration notes. The IRAS ASK Guide wording is used to ensure amendment procedure descriptions match the authoritative official guide.

### Test state

**124 tests passing** across four test files (no live SAP in any test):

| File | Coverage |
|------|----------|
| `tests/test_routing.py` | Document-2 template routing, E2-by-VatGroup branching, Template 4/5 switching |
| `tests/test_enrich.py` | Three-source join, (doc_num, error_code) aggregation, COMPLETENESS backfill path |
| `tests/test_sections.py` | All eight sections; human-in-the-loop language invariants; reviewer sign-off block |
| `tests/test_report_e2e.py` | Full end-to-end: `tests/fixtures/chain-run-sample.json` → `generate_report()` → PDF; section presence; no filing directives |

`tests/fixtures/chain-run-sample.json` is the static `CompileOutput` fixture used by the e2e test.

### Document positioning

The generated report is a **working paper** — a structured, reviewer-signed document for pre-filing review prepared with the assistance of AgentAssist. It is not an IRAS submission. The cover page and disclaimer section make this explicit.

---

## MCP tools inventory

### Custom GST accounting tools

#### Tool 12: `calculate_f5_return(period_start: str, period_end: str) -> str`

**Purpose**: Compute all eight F5 boxes for a given date range, including credit note
adjustments (T1.1, 2026-05-28).

**Inputs**: ISO date strings `YYYY-MM-DD`. No GST rate parameter (uses recorded `TaxTotal`
values, not recomputed rates).

**Outputs**: JSON string with keys: `period`, `currency` (always "SGD"), `boxes` (dict of 8
box values, rounded to 2 dp), `fx_invoices_requiring_conversion` (list with doc_num,
doc_date, currency, doc_total, card_name, type — now includes FX credit notes),
`e1_candidates` (FX+SO lines), `record_counts` (sgd/fx split for sales and purchases),
`credit_note_counts` (sgd/fx split for sales and purchase credit notes),
`credit_notes_applied` (one entry per SGD credit note line processed, with doc_num,
doc_date, card_name, type, vat_group, line_total_applied, tax_total_applied — all as
negated amounts), `anomalies` (unknown VatGroups).

**Internal logic**:

- Fetches `Invoices` and `PurchaseInvoices` in pages of 20 records, using `$skip` pagination.
- Also fetches `CreditNotes` and `PurchaseCreditNotes` via `_fetch_credit_notes_paginated`.
- Splits all four entity sets by `DocCurrency`: "SGD", "S$", and blank are treated as SGD;
  all others are FX.
- Routes SGD invoice lines through `F5_BOX_MAPPING` (add to boxes). Routes SGD credit note
  lines through the same mapping but **subtracts** from boxes — credit note amounts are
  positive in SAP B1, so `boxes[lt_box] -= lt` and `boxes[tt_box] -= tt`.
- NR VatGroup: `lt_box=None`, `tt_box=None` — excluded from all boxes on both invoice and
  credit note paths (T1.2 fix).
- Box 8 = Box 6 − Box 7. Box 4 = Box 1 + Box 2 + Box 3. All computed in Python.
- FX documents (invoices and credit notes) are listed for user reference but never included
  in box totals.
- Unknown VatGroups are collected in `anomalies` and excluded from all boxes.

**Hardcoded assumptions**:

- Page size of 20 (matches SAP B1 server cap; appropriate).
- `DocCurrency` in `("SGD", "S$", "")` treated as SGD. No handling for "SG$" or other
  alternate SGD representations.
- Fallback credentials in `SAPB1Client.__init__`: base URL
  `https://35.186.145.230:55000/b1s/v2`, company DB `SBODEMOSG`, username `manager`,
  password `manager`. These are applied when environment variables are absent. A production
  deployment that fails to set environment variables will silently attempt to connect to the
  demo instance.

**What is handled well**: Pagination, SGD/FX split, VatGroup routing for all 18 codes in the
mapping, E1 candidate detection, unknown VatGroup flagging, round-last arithmetic.

**What is not yet handled**:

| Gap | Impact | Priority |
|-----|--------|---------|
| Credit notes | RESOLVED T1.1 — CreditNotes and PurchaseCreditNotes now fetched and subtracted | — |
| Manual journal entries | Misses GST-relevant journals | Should-have |
| No `expected_rate` parameter | Tool always trusts `TaxTotal`; correct behaviour, but no rate-validation capability | Low |
| FX conversion | Identifies FX invoices but provides no SGD-converted figures | Should-have |
| IGDS Box 9 treatment | IGDS lines correctly go to Box 5+7 but Box 9 is not computed | Defer |
| ME Box 9 treatment | Same as IGDS | Defer |
| Partial exemption apportionment | TX-RE is mapped as Excluded; no apportionment logic | Should-have |
| Mid-period GST rate transitions | No handling for periods spanning a rate change date | Low |
| Custom UDFs on VatGroup | Some SAP B1 configurations override VatGroup via custom fields | Low |

---

#### Tool 13: `validate_invoice_tax_codes(period_start: str, period_end: str, expected_rate: float = 0.07) -> str`

**Purpose**: Per-line E1–E4 tax code validation across all invoices and credit notes in a
period, plus a VatGroup inventory of every code found (T1.1 update).

**Inputs**: ISO date strings. `expected_rate` defaults to 0.07 (7%, matching SBODEMOSG); pass
0.09 for post-2024 production data.

**Outputs**: JSON with `period`, `expected_rate`, `vatgroup_inventory` (dict keyed by VatGroup
with category, side, box mapping, doc count, and known-to-mapping flag), `issues` (list of
per-line findings with full context fields), `summary` (count by error code).

**Internal logic**:

Calls `_classify_line` for every line of every invoice and purchase invoice. `_classify_line`
implements four checks:

| Code | Condition | Notes |
|------|-----------|-------|
| E1 | `entity_type == "sales"` AND `DocCurrency` not SGD AND `VatGroup` in {SO, DS} | FX sales coded as local standard-rated |
| E2 | `TaxTotal > 0.01` AND `VatGroup` in {ZR, OS, ES33, ESN33, BL, **NR**} | GST charged on non-taxable supply; NR added T1.2 |
| E3 | `entity_type == "sales"` AND `VatGroup` in {SO, DS} AND `LineTotal > 0.01` AND `TaxTotal < 0.01` | Standard-rated line with zero tax |
| E3 | `entity_type == "purchase"` AND `VatGroup == "SI"` AND `LineTotal > 0.01` AND `TaxTotal < 0.01` | Same on purchase side |
| E4 | `VatGroup` in {SO, SI} AND `LineTotal > 0.01` AND `TaxTotal > 0.01` AND `abs(TaxTotal/LineTotal - expected_rate) > 0.001` | Rate deviation |

Credit note lines are now also passed through `_classify_line` with `credit_note=True`, which
prepends "Credit note — " to each description. This catches miscoded credit notes (e.g., a
credit note that inherited an E2 error from the original invoice). Credit note VatGroups are
included in the `vatgroup_inventory` counts.

The `vatgroup_inventory` field was added in a mid-experiment patch (between v3 Test 2 run 1
and run 2). The first v3 Test 2 run scored 8/10 because clean VatGroups were invisible to
Claude. The patch added a side-effect inventory pass over all lines. The patch did not change
any error-detection logic.

**Hardcoded assumptions**:

- E2 checks `_E2_ZERO_RATE_CODES = {"ZR", "OS", "ES33", "ESN33", "BL", "NR"}`. NR was added
  in T1.2 (2026-05-27): a purchase invoice or credit note with NR + TaxTotal > 0 is a genuine
  E2 error — non-taxable supply carrying GST. DocNum 611 (TaxTotal 45.00 at 9%) is the
  known SBODEMOSG fixture for this check.
- E4 checks VatGroups {SO, SI} only. NR is not in the E4 set, preventing double-flagging of
  DocNum 611 (which has a rate of 9% vs SBODEMOSG norm of 7%).

**What is not yet handled**: Same manual journal gap as Tool 12. Credit notes: RESOLVED T1.1.

---

#### Tool 14: `detect_gst_errors(period_start: str, period_end: str, expected_rate: float = 0.07) -> str`

**Purpose**: Full compliance audit combining E1–E4 line checks on invoices and credit notes,
a COMPLETENESS heuristic, and a NO_GST_REG supplier check (now covering purchase credit notes
too). Returns findings sorted by severity HIGH → MEDIUM → LOW. (T1.1 update, 2026-05-28)

**Inputs**: Same as Tool 13.

**Outputs**: JSON with `period`, `severity_counts`, `issues` (list with severity, error_code,
doc_num, doc_date, card_name, description, recommendation).

**Internal logic**:

Calls `_classify_line` for all lines (same as Tool 13). Additionally:

*COMPLETENESS*: If `purchase_count / sales_count < 0.1` (fewer than one purchase invoice per
ten sales invoices), appends a MEDIUM severity COMPLETENESS finding. This is a heuristic
only. The 0.1 threshold is hardcoded.

*NO_GST_REG*: For each purchase invoice **and purchase credit note** with any line having
`TaxTotal > 0.01`, fetches the supplier via `sap.get(f"/BusinessPartners('{card_code}')")` and
checks `FederalTaxID`. If blank, appends a HIGH severity NO_GST_REG finding. One finding per
supplier CardCode per run (deduplicates across both invoices and credit notes within the period).
This is an additional SAP API call per unique supplier with input tax — important for
performance at scale.

**Severity assignments in the tool**:

| Code | Severity in tool |
|------|-----------------|
| E1 | HIGH |
| E3 | HIGH |
| E2 | MEDIUM |
| E4 | MEDIUM |
| COMPLETENESS | MEDIUM |
| NO_GST_REG | HIGH |

**Severity alignment (RESOLVED 2026-05-26):** NO_GST_REG severity is standardized to HIGH
across both the tool and the system prompt's error code table. See
exploration-notes/baseline-test-results.md § Decisions for the rationale.

**Test 3 status (UPDATED 2026-05-26):** Tool validated at V3 in conversational context.
Score: 10/10 against the 19-finding reference set (11 E1 + 1 E2 + 7 NO_GST_REG). See
exploration-notes/v3-raw-chats/test3-error-detection.md for the raw chat log and analysis.

**What is not yet handled**: Same manual journal gap as Tools 12 and 13. Credit notes:
RESOLVED T1.1. The NO_GST_REG check issues one API call per unique supplier per run; at
production scale with many unique suppliers, this could be slow.

---

### Generic SAP B1 tools

The following eleven tools expose raw SAP B1 Service Layer access. They are used for
exploration, ad-hoc queries, and write operations. They do not implement any GST-specific
logic.

| # | Tool | Read/Write | Entity/Purpose | Notes |
|---|------|-----------|----------------|-------|
| 1 | `sap_login` | Write (session) | Authentication | Must be called first in every session |
| 2 | `sap_logout` | Write (session) | Session termination | |
| 3 | `sap_query` | Read | Any OData entity | Full `$select`, `$filter`, `$top`, `$skip`, `$orderby` support; most powerful tool |
| 4 | `sap_get_business_partners` | Read | BusinessPartners | Filtered by CardType and CardName search |
| 5 | `sap_get_business_partner` | Read | BusinessPartners | Single record by CardCode |
| 6 | `sap_create_business_partner` | Write | BusinessPartners | Creates customer/vendor/lead |
| 7 | `sap_get_items` | Read | Items | ItemCode/Name/VatGroup; search by name |
| 8 | `sap_create_document` | Write | Any document entity | JSON string input; high flexibility, low safety |
| 9 | `sap_get_document` | Read | Any document entity | Single record by DocEntry |
| 10 | `sap_create_journal_entry` | Write | JournalEntries | Manual journal creation |
| 11 | `sap_delete` | Write | Any entity | Deletes by key; destructive |

**Notable implementation choices**:

- `sap_query` has no pagination — it passes `$top=20` by default. A caller wanting more than
  20 records must call it repeatedly with `$skip`. The custom accounting tools handle pagination
  internally via `_fetch_invoices_paginated`; the generic `sap_query` does not.
- `sap_create_document` and `sap_delete` are write operations with no confirmation step. The
  system prompt does not restrict Claude from calling these. In a production environment, write
  tools should require explicit user confirmation before execution. For a compliance-review
  consulting use case, these tools may not need to be exposed at all.
- `sap_delete` key routing: if key is numeric, formats as `/(entity)(key)` (integer key); if
  non-numeric, formats as `/(entity)('key')` (string key). Simple heuristic; may fail on
  composite keys.

---

## Knowledge base inventory

### `knowledge-base/sg-tax-code-mappings.md`

**What it covers**: VatGroup-to-F5-box routing for all 18 VatGroup codes configured in
SBODEMOSG. Per-box calculation rules for Boxes 1–8 with IRAS paragraph citations. Foreign
currency rule (IRAS para 4.1). Error materiality threshold for F7 vs F5 correction (IRAS para
4.2.9). Critical validation rules (10 rules with IRAS citations). Out-of-scope boxes (9–21)
with explanations.

**Currency of IRAS references**: The source reference is the IRAS e-Tax Guide "How do I
prepare my GST return?" Eleventh Edition, published 30 January 2026, verified on 2026-05-25.
This is the current edition at audit date. Specific paragraph references are cited for each
rule (para 5.7, 5.8, 5.9, 5.11, 5.13, 6.5.1, 6.8.3, 4.2.9 etc.). The 9% rate note is
current and accurate (effective 1 January 2024).

**What is covered well**:

- The 18 VatGroups present in SBODEMOSG with correct descriptions and box routing
- Box-level calculation rules with authoritative IRAS citations
- Critical validation rules that are common IRAS audit triggers
- Clear scope statements for what is out of scope (Boxes 9–21, partial exemption, etc.)
- The BL/NR/EP/OP exclusion rules correctly stated with their IRAS basis

**NR VatGroup treatment — RESOLVED (T1.2, 2026-05-27)**:

The inconsistency identified in the original audit (code/reference script/system prompt
included NR in Box 5, knowledge base said it should be excluded per IRAS para 5.11(o)) has
been resolved. All four artefacts now agree: NR is excluded from Box 5.

Changes made in T1.2:
- `F5_BOX_MAPPING` in `sap_b1_server.py`: NR `lt_box` set to `None`, `tt_box` set to `None`.
- `PURCHASE_BOX5` in `run_baseline_tests.py`: NR removed.
- `system-prompts/base.md`: NR listed as Excluded with IRAS para 5.11(o) citation.
- `_E2_ZERO_RATE_CODES` in `sap_b1_server.py` and `E2_ZERO_RATE_CODES` in
  `run_baseline_tests.py`: NR added — a purchase with NR + TaxTotal > 0 is a genuine E2
  error (non-taxable supply carrying GST).

A validation fixture was seeded: DocNum 611, PurchaseInvoices, VatGroup NR, LineTotal 500.00,
TaxTotal 45.00. The TaxTotal reflects a 9% rate — an anomaly against the SBODEMOSG 7% demo
norm (SAP applied the statutory rate to the NR-coded line at seed time). This is documented in
`test_data_registry.json` and `exploration-notes/nr-vatgroup-resolution.md`. The 9% rate does
not affect E2 detection; E4 does not apply to NR (E4 checks SO/SI only), so there is no
double-flagging.

**Identified gaps relative to Singapore production data requirements**:

| Topic | Coverage | Status |
|-------|----------|--------|
| Partial exemption (TX-RE, mixed businesses) | Flagged as out of scope; no apportionment rules | Defer for SME focus |
| Reverse charge on imported services (from 1 Jan 2020) | Not mentioned | Gap for businesses buying overseas services |
| OVR regime (Overseas Vendor Registration, digital services) | Not mentioned | Gap for some SME buyers |
| GST F5 Boxes 9–21 | Documented as out of scope with reasons | Acceptable for typical SME |
| Bad debt relief | Not covered | Should-have for completeness |
| Tourist refund scheme (TX-E33, TX-N33, TX-RE) | Codes listed; no application rules | Low relevance for B2B |
| GST grouping (related companies as a single GST entity) | Not mentioned | Edge case; low priority |
| Voluntary disclosure (F7) threshold | Correctly documented | Complete |

---

## System prompt inventory

### `system-prompts/base.md`

**What it covers**: Role definition, F5 box definitions and VatGroup routing table, foreign
currency exclusion rule, demo environment rate-artefact rule, error code definitions (E1–E4,
NO_GST_REG, COMPLETENESS), tool usage rules (pagination, period defaulting, DocumentLines
requirement, tool preference order), compliance assertion rules, output format specification
(F5 return format, error detection format, general format rules).

**What the orchestration layer does well**:

- **Default period rule**: "most recent complete calendar quarter" with explicit fallback logic
  (checked against Q1-Q4 boundaries). This was the fix for the v1/v2 wrong-quarter failures.
- **Pagination enforcement**: Explicit step-by-step pagination procedure and the prohibition
  "never compute totals from a single page" — the fix for the v0/v1 pagination cap.
- **FX exclusion**: Mandatory exclusion of non-SGD invoices from all box totals, with
  requirement to list them separately with DocNums. This was closed in v2.
- **Rate artefact handling**: The SBODEMOSG 7% rate prohibition — "do not flag it as an error
  in any error-detection output" — is one of the most important rules and was the fix for the
  v0 Test 3 false positive.
- **Compliance assertion rule**: "Never assert a compliance issue without tool-confirmed
  evidence." This is the architectural constraint that prevents the Test 3 v0 false positive
  failure mode from recurring.
- **Tool preference order**: Explicit ranking — `calculate_f5_return` first, then
  `validate_invoice_tax_codes`, then `detect_gst_errors`, fall back to manual only if tools
  unavailable.

**Where the prompt is doing work that could be moved to tools**:

- The VatGroup routing table in the prompt is redundant with (and potentially inconsistent
  with) the `F5_BOX_MAPPING` in the tool code. Maintaining both creates drift risk. The
  system prompt version is needed as a fallback for when Claude reasons about tax codes
  without calling a tool, but the duplication is worth acknowledging.
- The NO_GST_REG severity (MEDIUM in the prompt vs. HIGH in the tool) is a direct consequence
  of this split: the prompt's error code table and the tool's severity assignments diverged
  without either being updated.

**Where the prompt constrains behavior that belongs in environment configuration**:

- The `**Current environment:** SBODEMOSG (SAP B1 demo database, FP2502)` statement is hardcoded
  in the prompt. In a production multi-client scenario, this would need to be dynamic — the
  system prompt would need to be generated or parameterized per client, or the environment
  statement would need to be injected at runtime. Currently there is no mechanism for this.

### `system-prompts/test1-prefix.md` and `test2-prefix.md`

These are task-specific prefixes designed to be prepended to the user prompt before F5
calculation (test1) or tax code classification (test2). They provide explicit step-by-step
instructions that reinforce the `base.md` rules. They were generated in response to specific
v1 failure modes (wrong quarter, pagination cap, FX exclusion, FX+SO flagging). Both are
working and correctly target the gaps they were designed to close.

---

## Experimental methodology

### Test design

Three tests were defined to measure performance across the core use cases.

**Test 1 — F5 Calculation**

Prompt: *"Using SAP Business One, calculate the GST F5 return figures for the most recent
quarter available in the system. Give me the values for Boxes 1 through 8."*

Evaluation: Each of the 8 boxes is compared against reference figures from
`scripts/run_baseline_tests.py`. Score 1 point per correct box, capped at 8, plus 1 for FX
detection and 1 for BL/OS exclusion. Maximum 10. An additional cap of 5/10 applies if any
headline figure is materially wrong (Box 8 off by more than SGD 100).

**Test 2 — Tax Code Classification**

Prompt: *"Look at the invoices in SAP B1. Classify each transaction by GST type:
standard-rated, zero-rated, exempt, or out-of-scope."*

Evaluation: 2 points for querying VatGroup at line level, 2 points for finding all 8 VatGroups
present, 2 points for correctly mapping 5+ of 8, 2 points for detecting FX+SO mismatch, 1
point for listing individual transactions, 1 point for flagging ambiguity. Maximum 10.

**Test 3 — Error Detection**

Prompt: *"Using SAP Business One, examine the invoices for Q3 2024 (July to September 2024).
Identify any errors, miscodings, or compliance issues in the GST treatment. Report each issue
you find with the document number, the problem, and your recommendation."*

Evaluation: 3 points for detecting FX+SO pattern and enumerating 6+ of 11 DocNums; 1 point
for detecting FX+SO pattern as general observation; 2 points for finding E2 on DocNum 605;
2 points for finding NO_GST_REG on 2+ of 7 suppliers; 1 point for querying at line level;
1 point for structured output format; 1 point for flagging ambiguity; minus 1 for
confidently-wrong critical finding. Maximum 10.

### Data fixture

**Database**: SBODEMOSG, SAP B1 version 1000250 (FP2502), Singapore localisation.

**Period**: Q3 2024 (2024-07-01 to 2024-09-30).

**Native transactions in period**: 47 sales invoices (39 SGD + 8 FX) and 17 purchase invoices
(15 SGD + 2 FX), as retrieved by `run_baseline_tests.py` on 2026-05-25 00:13:33 UTC.

**Seeded test invoices and credit notes** (current state in SBODEMOSG):

The seed script was run on 2026-05-27 producing the following registered documents (DocNums
are as assigned by SAP, not as planned — earlier runs at different DB states produced
different DocNums). Credit note seeds were added separately on 2026-05-28.

| DocNum | Entity | VatGroup | LineTotal | TaxTotal | Notes |
|--------|--------|----------|----------:|----------:|-------|
| 1003 | Invoices | ZR | 5,000.00 | — | Test zero-rated sales box |
| 1004 | Invoices | ES33 | 3,000.00 | — | Test exempt sales box |
| 1005 | Invoices | OS | 2,000.00 | — | Test out-of-scope exclusion |
| 608 | PurchaseInvoices | BL | 800.00 | 56.00 | Test blocked purchase exclusion; E2 fixture |
| 609 | PurchaseInvoices | IM | 4,500.00 | 315.00 | Test import GST box |
| 610 | PurchaseInvoices | ZP | 1,200.00 | 84.00 | Test zero-rated purchase box |
| 611 | PurchaseInvoices | NR | 500.00 | 45.00 | Box 5 exclusion + NR E2 fixture; TaxTotal at 9% (anomaly vs 7% norm) |
| 10 | CreditNotes | SO | 1,000.00 | 70.00 | T1.1 seed: reduces Box 1 + Box 6 |
| 11 | PurchaseCreditNotes | SI | 500.00 | 35.00 | T1.1 seed: reduces Box 5 + Box 7 |

Sales invoices 1–3 carry `FreeText=BASELINE_TEST_DATA` at header level. Purchase invoices
4–6 same. Invoice 7 (NR) and credit notes A/B carry `FreeText=BASELINE_TEST_DATA` at line
level (consistent with the exploration finding that FreeText is a line-level field in this
SAP B1 instance). `cleanup_test_data.py` can cancel the invoice seeds; credit note cleanup
has not yet been scripted. All nine documents remain active in SBODEMOSG.

**Note on DocNum 605 E2**: DocNum 605 (BL+TaxTotal=56) referenced in the Test 3 rubric is
a **pre-existing SBODEMOSG invoice**, not a seeded one. DocNum 608 is the seeded BL invoice.
Both carry BL+TaxTotal>0 and both appear as E2 findings. The E2 check on DocNum 605 has
always been against live SBODEMOSG data; `docnum-605-verification.md` confirms TaxTotal=56
via a live query.

### Versions tested

| Version | Components active | Hypothesis being tested |
|---------|-------------------|------------------------|
| v0 | Read-only MCP connector only | Establishes baseline; measures raw Claude capability |
| v1 | + Knowledge base (sg-tax-code-mappings.md) | Does tax domain knowledge improve classification? |
| v2 | + System prompt (base.md) | Does orchestration enforcement fix procedural failures? |
| v3 | + 3 custom MCP tools | Does removing Claude from the arithmetic path eliminate numeric errors? |
| v4 | Planned: + full workflow skill | Not yet implemented |

### Results

The following table maps each (test, version) pair to its score and evidence status.

| Test | v0 | v1 | v2 | v3 | Evidence quality |
|------|----|----|----|----|------------------|
| Test 1: F5 Calculation | 4/10 | 5/10 | 7/10 | **10/10** | Strong: raw logs for all 4 versions |
| Test 2: Tax Classification | 6/10 | 5/10 | 9/10 | **10/10** | Strong: raw logs for all 4 versions |
| Test 3: Error Detection | 2/10 | 3/10 | 9/10 | **10/10** | Strong: raw logs for all 4 versions; V1/V2 contamination documented and resolved |

**Test 1 detailed trajectory**:

- v0 (4/10): All 8 box values wrong. Box 8 SGD 3,480 above correct figure. Root causes: FX
  invoices silently included, ES33 misclassified as ZR, manual arithmetic errors.
- v1 (5/10): Correct methodology (LineTotal/TaxTotal distinction, rate artefact handling)
  but wrong quarter (Q2 instead of Q3). Scores +1 for methodology gains, not for accuracy.
- v2 (7/10): Correct methodology + pagination + FX enumeration + correct output format, but
  still wrong quarter. Root cause traced: agent correctly applied default-period rule but
  inferred Q3 2024 was "incomplete" from the last invoice date visible on page 1.
- v3 (10/10): Correct quarter, correct numbers, MAPE 0.00%. The period-completeness fix (added
  to base.md between v2 and v3 testing) combined with the `calculate_f5_return` tool eliminated
  all remaining failures.

**Test 2 detailed trajectory**:

- v0 (6/10): Correct methodology, but only 20 of 64 invoices seen (pagination cap). Found 1
  of 8 VatGroups. Did not examine purchase invoices. No period filter. Partial credit for
  noticing the FX+SO pattern conceptually.
- v1 (5/10): Knowledge base improved enumeration to transaction-level format, but the FX+SO
  mismatch flag regressed — visible FX+SO invoices were listed without any flag. Net −1 vs v0.
- v2 (9/10): Largest single-version gain (+4). Pagination, period filter, FX+SO detection, and
  all 8 VatGroups all correct. One false positive (DocNum 982, an August FX+SO invoice outside
  the seeded error set). Loses 1 point for the false positive.
- v3 (10/10): `vatgroup_inventory` patch enabled all 8 VatGroups to be returned directly from
  the tool. DocNum 982 false positive absent. E2 DocNum 605 detected.

**Test 3 evidence**:

v0 (2/10): Found 7 issues, of which only 2 (ADA and Aquent at customer level) overlap with
the reference 19 real issues. Critically invented a "highest-priority critical" finding
recommending voluntary disclosure to IRAS based on the 7%/9% rate gap — a demo data artefact.

v1 (3/10): Reproduced the V0 fabrication, this time as an F7 filing recommendation. Marginal
improvement over V0 from the ES33 semantic correction (knowledge base earning its keep on
vocabulary). Used spot-check methodology (sap_get_document × 7) rather than population
analysis; missed E2 on DocNum 605 (not in spot-check list) and missed all 7 NO_GST_REG
findings (supplier FederalTaxID never queried).

v2 (9/10): Eliminated the F7 fabrication. Caught all 8 E1 DocNums and DocNum 605 E2.
NO_GST_REG over-flagged at invoice level (17) rather than supplier level (7) — costing 1
point. System prompt's pagination rules drove a methodological shift from V1's spot-check to
V2's population-level analysis via bash_tool. See V1/V2 Reclassification Note in
baseline-test-results.md for the contamination discovery that surfaced this finding.

v3 (10/10): Custom tools (detect_gst_errors, validate_invoice_tax_codes) called directly. All
19 reference findings reproduced exactly with supplier-level deduplication. Used only 6 tool
calls vs V1's 14 and V2's 15 — efficiency payoff of purpose-built tools.

### Reproducibility assessment

**Can an outside party reproduce these results today?**

Partially, with significant barriers:

1. The SAP B1 SBODEMOSG instance runs at IP 35.186.145.230 on a Google Cloud Compute Engine
   instance deployed via SAP Cloud Appliance Library. This IP is hardcoded in the scripts and
   MCP server. A different deployment would have a different IP. The SAP CAL trial license
   lasts approximately 30 days. If the license has expired, the instance would need to be
   redeployed, at a different IP, requiring code changes.

2. The seed data (`seed_test_data.py`) inserts invoices into the live database. If the seeded
   invoices have been cleaned up (cancelled), running the tests would require re-seeding. If
   not cleaned up, re-seeding would create duplicate entries with different DocNums, invalidating
   the reference DocNum lists.

3. The v0 baseline test can be reproduced by running `scripts/run_baseline_tests.py` against
   a SBODEMOSG instance with the same data state. The Python script is deterministic and
   well-documented.

4. The v1–v3 conversational tests required a specific Claude Desktop configuration (model:
   Claude Sonnet 4.6, specific project knowledge and system prompt). Reproducing them would
   require setting up the same Claude Desktop environment and running the same prompts. The
   model is not version-pinned; future Sonnet versions might produce different results.

5. The v3 raw chat logs are saved verbatim and are the primary evidence of the v3 results.
   There is no mechanism to independently verify the claim "Claude produced exactly this
   output" from the chat logs. An external party must trust the logs.

**What's needed to make the experiment fully reproducible**:

- A snapshot or restore mechanism for the SBODEMOSG data state at test time
- Pinned model version in the Claude Desktop configuration documentation
- Automated test harness that runs the agent against stored prompts and compares outputs to
  stored reference results
- The `run_baseline_tests.py` script should be extended to cover E2, NO_GST_REG, and
  COMPLETENESS checks so the full Test 3 reference can be auto-generated
- IP address and credentials should be parameterized, not hardcoded

**Risk to credibility if questioned by a sophisticated buyer or auditor**:

For Test 1 and Test 2, the risk is moderate. The reference figures are independently computable
from the Python script, and the methodology is documented. A buyer who runs the Python script
against a fresh SBODEMOSG instance with the same seed data should get matching numbers.

For Test 3, the risk is now LOW. The reference script (run_baseline_tests.py) was extended on
2026-05-26 to auto-detect E2 (on both sales and purchases) and NO_GST_REG. The full 19-finding
reference is now machine-generated. A sophisticated auditor asking "how is the known-correct
set produced?" has a deterministic Python script as the answer. V3 conversational performance
is documented in v3-raw-chats/test3-error-detection.md with full tool-usage confirmation.

### Honest assessment of what the experiment proves and does not prove

**What it proves**: The architectural pattern — deterministic tools for computation, LLM for
reasoning and narrative, system prompt for orchestration — eliminates arithmetic errors and
significantly reduces false positives on the specific tasks and data it was tested against.
On Q3 2024 SBODEMOSG data, v3 achieves 10/10 on F5 calculation and tax code classification.
The v0 failure modes (arithmetic errors, classification errors, fabricated compliance findings)
are real and verifiable from the raw chat logs.

**What it does not prove**: The system handles production data quality. SBODEMOSG is a
clean, well-structured demo database maintained by SAP. Real client data will have: custom
VatGroup codes not in the mapping, credit notes, manual journals, suppliers without GST
registrations for legitimate reasons (small suppliers below the GST threshold), transactions
spanning GST rate changes, partial exemption scenarios, and edge cases that SAP B1 permits but
GST rules complicate. None of these have been tested.

Test 3 conversational performance at v3 has now been measured (10/10). Tool-in-context
performance — where the system prompt, knowledge base, and tool output interact — is
demonstrated for all three tests. The remaining unknowns are about production data quality,
not about whether the architecture works.

"Validated on SBODEMOSG" establishes that the architectural approach is sound and that the
specific implementation is correct for the tested scenarios. It does not establish commercial
readiness. The next validation phase must run against real client data, under controlled
conditions, covering a broader set of scenarios.

---

## Production readiness gap analysis

### Deployment surface

**Exists now**: Claude Desktop on a developer's Windows machine, with the MCP server launched
via stdio transport. The SAP B1 Service Layer is accessed over the internet via HTTPS. All
output is conversational text in the Claude Desktop window.

**What's needed for a paying engagement**:

A repeatable, client-deliverable run environment. At minimum:
- An extract-based delivery model: the client exports invoice data to a structured format,
  the system runs against the extract, output is a signed-off document the client can file or
  present to auditors. This removes the need for live Service Layer access at the client's
  site during the review.
- A PDF or structured report output that includes methodology disclosure, finding provenance
  (DocNums, dates, amounts), and a clear statement of what was and was not examined. A
  conversational Claude Desktop window is not a deliverable for a GST review engagement.
- A consistent Python environment with pinned dependencies and a launch script that a
  non-developer can run.

**Estimated work**: 4–6 weeks for a sole developer to build a minimal extract-based run
environment with PDF output. Must-have before first paid engagement.

### Per-client configuration

**Status: RESOLVED (T1.3, 2026-05-31)** — see T1.3 section above for full detail.

`config/loader.py` + `config/clients/*.yaml` + `ClientConfig` dataclass. `run_agent.py --client <id>` loads and validates the config before invoking `run_chain`.

**Remaining gap**: The system prompt's `SBODEMOSG` environment statement is still hardcoded — dynamic per-client prompt generation is deferred to T1.4 or a separate prompt-templating task.

### Reporting and audit trail

**Structured output — RESOLVED (T1.4, 2026-06-01)**: The `report/` package delivers a signed PDF report containing methodology disclosure, period and data scope, F5 box table with VatGroup attribution, error findings with DocNums and IRAS template routing, edge cases for reviewer judgment, items not examined, and a reviewer sign-off block. `run_agent.py --report` triggers it end-to-end from the T1.6 chain output. See § T1.4 for full detail.

**Audit trail — OPEN (T1.5, Collin)**: No immutable log of tool calls, API responses, or findings exists. A timestamped, tamper-evident log is required to support client GST filing records, Singapore PDPA compliance (data minimization, purpose limitation), and the defensibility of the firm's work product. Input immutability (snapshotting the invoice data used in the analysis) is part of this gap.

**Estimated work for T1.5**: 2–3 weeks. Must-have before first paid engagement.

### Test fixtures beyond SBODEMOSG

**Exists now**: One fixed dataset (SBODEMOSG Q3 2024) with 6 seeded edge-case invoices.
The dataset is ephemeral (dependent on a live cloud instance).

**What's needed**: Synthetic datasets covering edge cases not present in SBODEMOSG:
- Period spanning GST rate change (Dec 2023 / Jan 2024 boundary, 7% → 9%)
- Partial exemption scenario (TX-RE lines with apportionment required)
- Reverse charge scenario (imported services)
- NULL / blank FederalTaxID on legitimate small suppliers vs. unregistered taxable suppliers
- Related-party transactions (inter-company invoices)
- Large FX invoices requiring multi-rate conversion
- Credit notes and purchase credit notes
- Manual journals with GST implications
- Custom VatGroup codes not in the standard mapping
- COMPLETENESS edge cases (legitimate low-purchase periods vs. missing data)

These fixtures should be static (not dependent on a live SAP instance) to be reproducible.

Note: Q3 2024 SBODEMOSG contains no credit notes, no NR-coded purchases, no rate-transition
periods, and no custom VatGroup codes. Test 3's 10/10 score does not demonstrate handling of
these scenarios.

**Estimated work**: 2–3 weeks to design and implement a static fixture framework. Should-have
before customer-facing demonstrations of error detection capability.

### Reproducibility

**Exists now**: The Python reference script is deterministic. The raw chat logs are saved.
The knowledge base and system prompt are version-controlled (with caveats — see credentials
section). The model version (Claude Sonnet 4.6) is documented in chat headers but not pinned
in any config.

**What's needed**:
- Model version pinning in a configuration file.
- Versioned system prompts and knowledge base (current git history provides basic versioning
  but no semantic version labels).
- Automated evaluation harness that runs the agent against stored prompts and compares outputs
  to stored reference results — eliminating the current dependence on human-logged chat
  transcripts as evidence.
- Note: run_baseline_tests.py was extended on 2026-05-26 to cover E2 (sales+purchases incl.
  BL), NO_GST_REG (supplier-level dedup), and COMPLETENESS. Test 3 reference is now fully
  auto-generated.

**Estimated work**: 2–3 weeks for a basic automated evaluation harness. Should-have before
presenting results to sophisticated buyers.

### Security and PDPA compliance

**Exists now**:
- .gitignore is now functional; keys/ directory is properly excluded from staging. Note:
  credential files exist in initial commit history (aec650f9). See
  exploration-notes/security-decisions.md for the deferred-decision register.
- Hardcoded credentials removed from sap_b1_server.py (2026-05-26). The server now fails
  fast with a clear RuntimeError if required environment variables are missing. Local
  development uses a gitignored .env file.
- SSL verification is now configurable via SAP_SSL_VERIFY env var (defaults to true). Demo
  .env sets it to false for the self-signed SBODEMOSG cert; production deployments must use
  true with a properly signed certificate or implement certificate pinning.
- No data retention or destruction controls.
- No PDPA-compliant data handling (purpose limitation, data minimization, consent records).

**What's needed**:
- Mandatory history scrub before the triggers listed in security-decisions.md are reached
  (making repo public, non-trusted collaborator, first paid engagement, connecting to real
  client SAP B1 instance).
- A data handling policy document specifying: what data is accessed, how it is stored, how
  long it is retained, and under what conditions it is destroyed. Required for Singapore PDPA
  compliance when accessing client financial data.
- Evaluate whether Claude API usage sends any client financial data to Anthropic's servers.
  (It does: all tool output and user messages in a conversation are sent to the Claude API.
  This should be disclosed to clients and may require a data processing agreement with
  Anthropic.)

**Estimated work**: History scrub: 1–2 hours when triggered. PDPA compliance framework: 2–3
weeks with legal input. Must-have before accessing any real client data.

### Reliability and error handling

**Exists now**: The `SAPB1Client` class handles 401 re-authentication (one retry) and basic
HTTP error propagation. Session expiry is tracked and auto-refreshed. `_safe_float` handles
None/non-numeric values. Unknown VatGroups are collected in `anomalies` rather than raising
exceptions.

**What's needed**:
- Retry logic for transient SAP Service Layer errors (503, timeout). The current code raises
  immediately on any non-200/201/204 response after one 401 retry.
- Timeout handling: if the SAP Service Layer is slow or the cloud instance is shutting down,
  the 30-second httpx timeout will raise without a user-friendly message.
- Claude API rate limiting: no handling for Anthropic API rate limit errors in the Claude
  Desktop context. Extended engagements with many tool calls could hit rate limits.
- Partial data detection: if a paginated fetch returns fewer records than expected (e.g., the
  SAP instance is under load and drops connections mid-pagination), the current code would
  silently use incomplete data. A record count check against SAP's `$inlinecount` would detect
  this.

**Estimated work**: 1–2 weeks for hardened error handling. Should-have before first paid
engagement.

---

## Risks and unknowns

**Things that might break under production data conditions**:

1. **Credit notes**: RESOLVED (T1.1, 2026-05-28). All three tools now query CreditNotes and
   PurchaseCreditNotes and subtract their amounts from the relevant boxes. The system prompt
   caveat has been updated to describe credit note handling, not warn of its absence.

2. **Custom VatGroup codes**: Production SAP B1 instances commonly have local-language or
   company-specific VatGroup codes not in the standard mapping. These would fall into the
   `anomalies` bucket and be excluded from all calculations. A client with 20% of their
   transactions coded to a custom VatGroup would silently receive an undercount, with only a
   generic "unknown VatGroup" anomaly warning.

3. **NR VatGroup compliance error**: RESOLVED (T1.2, 2026-05-27). NR is now excluded from
   Box 5 across tool code, reference script, and system prompt. An NR line with TaxTotal > 0
   is correctly flagged as E2. DocNum 611 is the live validation fixture.

4. **SAP B1 DocumentLines structure variations**: Some SAP B1 configurations compute
   `TaxTotal` at header level rather than line level, or use `VatSum` instead of `TaxTotal` in
   DocumentLines. The tools exclusively use `TaxTotal` at line level. If a client's SAP B1
   configuration stores tax differently (e.g., allocated only to certain lines, or at header
   level), all three custom tools would produce incorrect results.

5. **NO_GST_REG false positives/negatives**: The check relies on `FederalTaxID` being empty
   as a signal that the supplier is not GST-registered. In practice: (a) small suppliers below
   the SGD 1 million turnover threshold are legitimately not GST-registered, and input tax
   cannot be claimed from them regardless — this is correct behavior; but (b) some SAP B1
   configurations store GST registration numbers in a UDF (User Defined Field) rather than
   the standard `FederalTaxID` field. For those clients, all suppliers would appear
   unregistered.

6. **COMPLETENESS threshold of 10%**: A business that legitimately has a high sales volume
   relative to its direct purchases (e.g., a services firm that buys little and bills a lot)
   would trigger a false COMPLETENESS flag. This heuristic may generate noise for
   service-heavy businesses.

7. **Session management under load**: The MCP server uses a single synchronous `httpx.Client`
   with session cookies. If Claude makes many rapid tool calls (which it does on complex
   tasks), the session could expire between calls and the re-authentication logic could fail
   under specific timing conditions.

**Things the project has not tested but is assuming work**:

1. `detect_gst_errors` in the conversational context — RESOLVED. V3 Test 3 validated at
   10/10. See v3-raw-chats/test3-error-detection.md.
2. The 7 NO_GST_REG findings have been auto-validated by the extended run_baseline_tests.py
   (extended 2026-05-26 to include NO_GST_REG checks). Confirmed against live SBODEMOSG data.
3. The system's behavior when a user specifies a period with no data (currently falls back to
   prior quarters — tested at v3 for Q1/Q4 2025 — but not tested for edge dates like a period
   before SAP go-live).
4. How Claude behaves when the `calculate_f5_return` tool returns anomalies (unknown
   VatGroups). The system prompt says "exclude it from all box totals" but the reasoning
   behavior when anomalies are present has not been tested.

**External dependencies that could shift**:

1. **SAP B1 Service Layer API**: SAP regularly releases Feature Packs for SAP B1. API behavior,
   field names, and entity structures can change between versions. The tools are built against
   FP2502. A client on a different Feature Pack version might have different field names or
   pagination behavior.

2. **Anthropic API model behavior**: Claude Sonnet 4.6 is the tested model. Newer model
   versions are released regularly. The orchestration rules in the system prompt were tuned
   for Sonnet 4.6 behavior. Model upgrades could change compliance assertion behavior, output
   format adherence, or tool-call patterns.

3. **IRAS guidance changes**: Singapore GST regulations and IRAS e-Tax Guides are updated
   periodically. A VatGroup mapping or box calculation rule that is correct today may become
   incorrect after a guidance revision without the knowledge base being updated.

4. **SAP CAL instance lifecycle**: The development and testing instance at 35.186.145.230 is
   a SAP Cloud Appliance Library trial deployment. Trial instances expire after approximately
   30 days and cannot be extended without additional cost. After expiry, a new deployment at a
   new IP would require updating all hardcoded IP references.

---

## Strategic implications

### What technical artefacts can credibly be shown to prospective customers in their current state

The v0 vs. v3 comparison is the strongest demonstration material available. Specifically:
the v0 Test 1 Box 8 figure (SGD 20,876 payable vs. correct SGD 17,396, a SGD 3,480
overpayment that would be real money if filed) and the v0 Test 3 false "critical" finding
(recommending voluntary disclosure to IRAS for a rate difference that is a demo data artefact)
are compelling, concrete, and verifiable. These can be shown as side-by-side comparisons.

The v3 Test 1 and Test 2 outputs (`v3-raw-chats/`) are clean, well-formatted, and demonstrate
the system working correctly. They can be shown directly as sample deliverables, with the
caveat that they are demo data output.

The knowledge base (`sg-tax-code-mappings.md`) can be shown to tax-literate buyers as evidence
of the depth of Singapore-specific domain encoding. The IRAS citations are accurate and current.

### What technical artefacts cannot yet be shown without further work

Test 3 (error detection) can now be shown — the v3 raw chat log and full analysis are in
`v3-raw-chats/test3-error-detection.md`. The remaining gap is not demonstration readiness but
delivery format: the output is a conversational Claude Desktop transcript, not a structured
deliverable that a client can file or present to auditors.

The system cannot be demonstrated on a prospective customer's own SAP B1 data without
significant configuration work (new credentials, potentially new IP, system prompt update).
Demonstrating on a customer's live system also carries the risk of encountering edge cases
the system does not handle (credit notes, custom VatGroups, etc.) in front of the customer.

### The honest answer to "what does the first paying customer need to see before they say yes"

At minimum: a demonstration on their own data (or a close analog) producing F5 figures they
can verify, plus a sample error detection report with at least some findings their own team
had not caught. The v3 results on demo data establish the methodology; they do not prove the
system works on the customer's specific SAP B1 configuration.

The customer also needs a deliverable — not a Claude Desktop screenshot, but a document they
can keep. And they need confidence that their financial data is handled appropriately (PDPA,
data residency, Anthropic API data usage disclosure).

### The honest answer to "what could break the first paying engagement"

1. The client has credit notes in the period. The F5 calculation will be wrong and the system
   will not warn that credit notes were not examined (the system prompt mentions it as a
   caveat, but many users would miss a caveat buried in the output).

2. The client's SAP B1 uses custom VatGroup codes. All transactions with custom codes will
   be silently excluded from calculations, producing a materially wrong F5 with no obvious
   error signal beyond the anomalies list.

3. The demonstrate-on-client-data attempt surfaces an edge case (partial exemption, reverse
   charge, non-standard TaxTotal structure) that crashes the tool or produces an incorrect
   output. In front of the client.

4. The NO_GST_REG check triggers false positives for legitimate small suppliers, causing
   the client to question the system's accuracy.

5. RESOLVED (T1.4, 2026-06-01): The `report/` package generates a structured PDF with methodology disclosure and reviewer sign-off block. The remaining delivery-format gap is the audit trail (T1.5) — the chain run JSON is not yet immutably timestamped and tamper-evident.

### Recommendations on the most leverage-positive next pieces of work

**1. Add credit note fetching to the three custom tools (1–2 days).** This closes the most
significant functional gap before a real-client demonstration. `CreditNotes` and
`PurchaseCreditNotes` are standard SAP B1 entities with the same structure as invoices and
the same OData access pattern. The fix is additive.

**2. Resolve the NR VatGroup inconsistency (2 hours).** Check IRAS para 5.11(o) against the
current e-Tax Guide. If the knowledge base is correct (NR excluded from Box 5), update the
tool code, reference script, and system prompt. If the code is correct (NR included), update
the knowledge base. This discrepancy could produce incorrect output on production data.

**3. RESOLVED (T1.4, 2026-06-01): Report generation complete.** The `report/` package generates a signed PDF from `CompileOutput`; 124 tests pass. The remaining pre-engagement gate is the audit trail (T1.5, Collin) — immutable logging of tool calls and chain inputs.

**4. Trigger the git history scrub when the first of the security-decisions.md conditions is
met.** The credential exposure in aec650f9 is documented and tolerable for the current
internal-only phase. It becomes intolerable at the first trigger listed in security-decisions.md
(public repo, non-trusted collaborator, first engagement, real client data, etc.).

**5. Resolve the ZP+TaxTotal E2 gap (2 hours).** DocNum 607 has ZP+TaxTotal=84, which is
conceptually a real E2 (zero-rated purchases should not carry GST) that neither the script nor
the MCP tool currently catches. Low effort, improves completeness of the error-detection layer.

Updated path to first revenue (T1.1 credit notes, T1.2 NR fix, T1.3 per-client config, T1.6
deterministic chain, T1.4 PDF report: all complete): **audit trail and input immutability
(T1.5, Collin) is the single remaining component before a professional engagement can be
completed.** The core architecture is proven at 30/30 conversational (V0→V3), 41/41 chain
tests, and 124/124 report tests; the remaining gap is defensible work-product logging, not
correctness or delivery format.

---

## Appendices

### Appendix A — Inventory of all experimental run logs

| Evidence | Location | Contents | Status |
|----------|----------|----------|--------|
| Python reference run (v0 baseline) | `exploration-notes/baseline-test-report-v0.json` | All 3 tests, machine-generated, Q3 2024 figures | Complete and authoritative |
| v0 Test 1 raw chat | `exploration-notes/v0-raw-chats/test1-f5-calculation.md` | Verbatim Claude response, 4/10 | Complete |
| v0 Test 2 raw chat | `exploration-notes/v0-raw-chats/test2-tax-classification.md` | Verbatim Claude response, 6/10 | Complete |
| v0 Test 3 raw chat | `exploration-notes/v0-raw-chats/test3-error-detection.md` | Verbatim Claude response, 2/10 | Complete |
| v1 Test 1 raw chat | `exploration-notes/v1-raw-chats/test1-f5-calculation.md` | Verbatim Claude response, 5/10 | Complete |
| v1 Test 2 raw chat | `exploration-notes/v1-raw-chats/test2-f5-calculation.md` | Verbatim Claude response, 5/10 (misnamed file) | Complete (naming error) |
| v1 Test 3 raw chat | `exploration-notes/v1-raw-chats/test3-error-detection.md` | Verbatim Claude response, 3/10 | Complete (re-run with corrected configuration after V1/V2 contamination discovery) |
| v2 Test 1 raw chat | `exploration-notes/v2-raw-chats/test1-f5-calculation` | Verbatim Claude response, 7/10 (no .md extension) | Complete (extension missing) |
| v2 Test 2 raw chat | `exploration-notes/v2-raw-chats/test2-tax-classification.md` | Verbatim Claude response, 9/10 | Complete |
| v2 Test 3 raw chat | `exploration-notes/v2-raw-chats/test3-error-detection.md` | Verbatim Claude response, 9/10 | Complete (reclassified from initial V1 run with base.md inadvertently attached) |
| v3 Test 1 raw chat | `exploration-notes/v3-raw-chats/test1-f5-calculation.md` | Verbatim Claude response, 10/10 | Complete |
| v3 Test 2 raw chat | `exploration-notes/v3-raw-chats/test2-tax-classification.md` | Verbatim Claude response, 10/10 | Complete |
| v3 Test 3 raw chat | `exploration-notes/v3-raw-chats/test3-error-detection.md` | Verbatim Claude response, 10/10 | Complete |
| Improvement tracking table | `exploration-notes/baseline-test-results.md` | Synthesized per-version analysis | Complete for all three tests; includes V1/V2 Test 3 Reclassification Note |
| DocNum 605 E2 verification | `exploration-notes/docnum-605-verification.md` | Live SAP query confirming BL line carries TaxTotal=56.00 | Complete |
| Security decisions log | `exploration-notes/security-decisions.md` | Deferred-decision register for credentials in git history | Complete |

---

### Appendix B — Reference figures

> **Status**: These figures require a re-baseline run against the current SBODEMOSG state.
> The figures below are from the 2026-05-25 run and are now stale because: (a) T1.2 changed
> the NR treatment in the reference script (NR excluded from Box 5), (b) additional invoice
> seeds (DocNums 608–611) and credit note seeds (DocNums 10 and 11) have been created since
> then. Run `scripts/run_baseline_tests.py` against live SBODEMOSG to regenerate. The
> post-seed, post-T1.1 figures confirmed via live query on 2026-05-28 are shown as a
> secondary table below.

**F5 Boxes (2026-05-25 baseline — stale, pre-T1.2, pre-seed invoices 608–611)**

| Box | Description | SGD Value |
|-----|-------------|----------:|
| Box 1 | Standard-rated supplies (LineTotal, VatGroups SO+DS) | 370,589.97 |
| Box 2 | Zero-rated supplies (LineTotal, VatGroup ZR) | 5,000.00 |
| Box 3 | Exempt supplies (LineTotal, VatGroups ES33+ESN33) | 3,000.00 |
| Box 4 | Total supplies (Box 1+2+3) | 378,589.97 |
| Box 5 | Taxable purchases (LineTotal, VatGroups SI+ZP+IM+IGDS+ME — NR now excluded) | 123,277.76 |
| Box 6 | Output tax due (TaxTotal, VatGroups SO+DS) | 25,941.32 |
| Box 7 | Input tax claimed (TaxTotal, VatGroups SI+IM+IGDS) | 8,545.45 |
| Box 8 | Net GST payable (Box 6 − Box 7) | 17,395.87 |

**F5 Boxes (2026-05-28 — post-seed, post-T1.2, post-T1.1, confirmed via live query)**

All 9 seed documents active (invoices 1003–1005, 608–611; credit notes 10, 11).
NR (DocNum 611) excluded from Box 5. Credit note A (SO/1000.00) reduces Box 1 and Box 6.
Credit note B (SI/500.00) reduces Box 5 and Box 7.

| Box | Description | SGD Value |
|-----|-------------|----------:|
| Box 1 | Standard-rated supplies | 369,589.97 |
| Box 2 | Zero-rated supplies | 10,000.00 |
| Box 3 | Exempt supplies | 6,000.00 |
| Box 4 | Total supplies (Box 1+2+3) | 385,589.97 |
| Box 5 | Taxable purchases (NR excluded, CN B deducted) | 128,477.76 |
| Box 6 | Output tax due (CN A deducted) | 25,871.32 |
| Box 7 | Input tax claimed (CN B deducted) | 8,825.45 |
| Box 8 | Net GST payable (Box 6 − Box 7) | 17,045.87 |

Source document counts (2026-05-28): 50 SGD sales invoices, 8 FX, 19 SGD purchase invoices,
2 FX, 1 SGD CreditNote, 1 SGD PurchaseCreditNote.

**VatGroups in period (Test 2 reference — updated post-seed)**

| Code | Description | F5 Box |
|------|-------------|--------|
| SO | Standard-rated output | Box 1 (LineTotal) + Box 6 (TaxTotal) |
| ZR | Zero-rated supply | Box 2 (LineTotal) |
| ES33 | Exempt — Regulation 33 | Box 3 (LineTotal) |
| OS | Out-of-scope supply | Excluded |
| SI | Standard-rated input | Box 5 (LineTotal) + Box 7 (TaxTotal) |
| IM | Import GST | Box 5 (LineTotal) + Box 7 (TaxTotal) |
| ZP | Zero-rated purchase | Box 5 (LineTotal) only |
| BL | Blocked input (Reg 26/27) | Excluded |
| NR | Non-GST-registered supplier | Excluded (T1.2 fix; previously incorrectly in Box 5) |

**Known-correct issues in Q3 2024 (Test 3 reference — updated post-T1.1)**

The reference script (`run_baseline_tests.py`) now auto-detects E1, E2 (incl. NR), E3, E4,
NO_GST_REG, and COMPLETENESS. All findings are machine-generated.

| Type | Count | Notes |
|------|-------|-------|
| E1 (FX+SO miscoding) | 11 | DocNums: 958, 964, 965, 967 (×2 lines), 971, 974 (×3 lines), 977, 982 |
| E2 (non-taxable with TaxTotal>0) | 3 | DocNums 605 (BL/56.00), 608 (BL/56.00), 611 (NR/45.00). NR E2 enabled by T1.2 |
| NO_GST_REG | 7 | Supplier purchase invoices with input tax claimed but blank FederalTaxID |
| COMPLETENESS | 0 | Purchase/sales ratio above 0.10 threshold |
| E3 | 0 | No standard-rated lines with zero tax in period |
| E4 | 0 | No rate deviations within {SO, SI} scope (DocNum 611 NR at 9% is outside E4 scope) |

**FX invoices excluded from F5 (10 documents)**

| DocNum | DocDate | Counterparty | Currency | Amount | Type |
|--------|---------|-------------|----------|-------:|------|
| 958 | 2024-07-02 | SG Electronics | USD | 1,131.53 | Sales |
| 964 | 2024-07-09 | Aquent Systems | USD | 5,617.50 | Sales |
| 965 | 2024-07-09 | Aquent Systems | USD | 393.23 | Sales |
| 967 | 2024-07-28 | ADA Technologies | EUR | 4,119.50 | Sales |
| 971 | 2024-07-24 | ADA Technologies | EUR | 71.10 | Sales |
| 974 | 2024-07-11 | SG Electronics | USD | 38,612.29 | Sales |
| 977 | 2024-07-29 | Aquent Systems | USD | 829.68 | Sales |
| 982 | 2024-08-03 | ADA Technologies | EUR | 26,589.50 | Sales |
| 601 | 2024-08-27 | Blockies Corporation | EUR | 12,824.65 | Purchase |
| 604 | 2024-08-17 | Lumarx | USD | 9,201.85 | Purchase |

---

### Appendix C — Open questions

Items that arose during the audit and require a decision or investigation before the next
strategic or engineering conversation.

1. **NR VatGroup**: RESOLVED (T1.2, 2026-05-27). NR is now excluded from Box 5 per IRAS
   para 5.11(o) across all four artefacts. NR E2 detection added. DocNum 611 is the live
   validation fixture. See exploration-notes/nr-vatgroup-resolution.md.

2. **NO_GST_REG severity**: RESOLVED 2026-05-26. Standardized to HIGH across both the tool
   and the system prompt's error code table. See baseline-test-results.md § Decisions.

3. **E2 on DocNum 605**: RESOLVED 2026-05-26. TaxTotal=56.00 confirmed live via SAP query.
   See docnum-605-verification.md.

4. **Test 3 v3**: RESOLVED 2026-05-26. Score: 10/10. See
   v3-raw-chats/test3-error-detection.md.

5. **SAP CAL instance**: Has the trial license for the 35.186.145.230 instance expired or is
   it still active? If expired, reproduction of any test requires a new deployment at a new IP.

6. **Credit note prevalence in target customers**: For the pilot customer segment (mid-market
   Singapore SAP B1 users), how common are credit notes in a typical quarter? This determines
   urgency of the credit note gap.

7. **Anthropic API data residency**: Anthropic's API terms and data processing agreement — is
   there a Singapore data residency option, or does all data route through US/EU servers?
   This affects the compliance disclosure required when accessing client financial data.

8. **Seeded test data cleanup**: Nine documents are now active in SBODEMOSG (invoices
   1003–1005, 608–611; credit notes 10, 11). Running `seed_test_data.py` again would create
   further duplicates with new DocNums. `cleanup_test_data.py` cancels the invoice seeds;
   credit note cancellation has not yet been scripted. Decision pending with Collin on whether
   to clean up the 608–611 generation before re-baselining.

9. **`git` file at root**: RESOLVED 2026-05-27. Deleted.

10. **`v1-raw-chats/image.png`**: What is this file? No other file references it. Should it be
    removed or documented?

11. **V0 tool-usage check**: V0 Test 3 ran with bash_tool potentially available; not confirmed.
    This affects whether V0→V1 comparison is apples-to-apples on the analytical-tool axis.
    Single follow-up question in V0 conversation if still accessible.

12. **V2 'extras' as gaps in tool coverage**: V2 Test 3 surfaced three findings outside the
    reference set (ZP+TaxTotal=84 on DocNum 607, ES33 on DocNum 1001, FX purchases SI miscoding
    on 601/604). The ZP+TaxTotal>0 case in particular is conceptually a real E2 that neither the
    script's nor the MCP tool's E2 set catches. Worth evaluating whether to extend the E2 set to
    include ZP.

13. **Credit note prevalence**: For target mid-market Singapore SAP B1 clients, what fraction
    of quarters contain credit notes? The technical gap is resolved (T1.1); this question now
    governs how prominently credit note support should feature in customer-facing positioning.

14. **Re-baseline run**: `scripts/run_baseline_tests.py` contains a placeholder instead of
    concrete reference figures pending the 608–611 fixture decision with Collin. Once that
    decision is made, run the script against live SBODEMOSG and update both the script's
    comment block and Appendix B of this document.

15. **DocNum 611 rate anomaly**: The NR seed carries TaxTotal 45.00 at 9% — an anomaly vs
    SBODEMOSG 7% demo norm. This is documented in `test_data_registry.json` (tax_rate_note
    field) and `nr-vatgroup-resolution.md`. No functional impact; flagged for awareness.

16. **T1.5 audit trail** (OPEN, Collin): Immutable timestamped logging of every chain run —
    tool calls, API responses, chain inputs, and findings. Required for Singapore PDPA compliance
    and defensibility of work product. The output path (`exploration-notes/t1.6-tool-outputs/`)
    is provisional pending T1.5 integration.

17. **Source adapter + 4× fetch tech-debt** (OPEN): The three tool-step functions (`calculate`,
    `classify`, `detect`) each re-fetch from SAP independently; the Fetch step builds only the
    manifest. Each chain run makes ~4× the minimum necessary SAP round-trips. Substituting an
    alternative source (CSV extract, test fixture) would require changing step function
    signatures. Deferred to T1.6.1.

18. **Production-data robustness — custom VatGroups silently excluded** (OPEN): SAP B1
    instances commonly have company-specific VatGroup codes not in the standard mapping. These
    fall into `anomalies` and are silently excluded from all calculations. A client with material
    custom-VatGroup volume would receive an undercount with only a generic anomaly warning.

19. **Production-data robustness — header-level TaxTotal** (OPEN): Some SAP B1 configurations
    compute `TaxTotal` at header level or use `VatSum` instead of `TaxTotal` in DocumentLines.
    The tools exclusively use `TaxTotal` at line level. Behavior against non-standard
    configurations is untested and could produce incorrect results silently.

20. **Production-data robustness — NO_GST_REG UDF** (OPEN): Some SAP B1 configurations store
    GST registration numbers in a User Defined Field rather than the standard `FederalTaxID`.
    For those clients, all suppliers would appear unregistered, generating false positives across
    every purchase invoice with input tax.

21. **Static fixtures beyond SBODEMOSG** (OPEN): Test coverage is limited to SBODEMOSG Q3 2024
    data plus seeded edge-case invoices. Synthetic static fixtures are needed for: GST rate
    transition period, partial exemption, reverse charge, NULL FederalTaxID (legitimate small
    suppliers below the GST threshold), custom VatGroup codes, and non-standard TaxTotal
    structure. Fixtures should be static (not dependent on a live SAP instance) to be
    reproducible.

22. **ZP+TaxTotal E2 gap** (OPEN): DocNum 610 (ZP+TaxTotal=84) is a real E2 (zero-rated
    purchases should not carry GST) not currently caught by either the reference script or the
    `_E2_ZERO_RATE_CODES` set. Low effort to extend; improves error-detection completeness.

23. **Manual journals** (OPEN): All three custom tools and the T1.6 chain skip
    `JournalEntries`. GST-relevant manual journals (e.g., VAT adjustments, F7 corrections) are
    invisible to the system. Impact depends on client's SAP B1 usage patterns.

24. **Reasoning-layer evaluation harness** (OPEN): There is no automated harness to evaluate
    Claude's reasoning quality on the classify/detect steps against a stored reference. The
    current evidence base is conversational chat logs. Required for regression testing as Claude
    model versions change.

25. **PDPA / Anthropic DPA** (OPEN): All tool output and user messages are sent to the Claude
    API. A data processing agreement with Anthropic is required before accessing real client
    financial data under Singapore PDPA. Anthropic's current API terms and data residency
    options (US/EU servers only vs. Singapore) need to be confirmed and disclosed to clients.

26. **Security history scrub** (OPEN): Credential files (`sap_credentials.json`,
    `sap-b1-poc-sg.pem`) exist in the initial commit (aec650f9). A mandatory history scrub is
    required before any of the triggers listed in `exploration-notes/security-decisions.md` are
    reached.

27. **Fallback-credentials inconsistency** (OPEN): `SAPB1Client.__init__` contains hardcoded
    fallback credentials (base URL, company DB, username, password) applied silently when
    environment variables are absent. A production deployment that fails to set env vars would
    silently attempt to connect to the SBODEMOSG demo instance. This should either be removed
    (fail-fast with a clear error) or explicitly documented as a development convenience with a
    warning log.

---

*End of document. Generated 2026-05-26 by repository audit; updated 2026-05-27 (Test 3,
V1/V2 contamination, security hygiene, reference script extension); updated 2026-05-28 (T1.2
NR VatGroup exclusion, T1.1 credit notes, post-seed reference figures); updated 2026-06-01
(T1.3 per-client config and T1.6 deterministic orchestration chain — T1.6 merged to `master`
on 2026-06-01); updated 2026-06-01 (T1.4 signed PDF report generator). T1.3 and T1.6 are on
`master`. T1.4 is on branch `t1.4-pdf-report-generation` (ready to merge).*
