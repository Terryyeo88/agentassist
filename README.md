# AgentAssist — GST F5 Compliance Review for SAP B1

AgentAssist performs line-level Singapore GST F5 compliance review for mid-market SAP
Business One clients. It combines deterministic rule-checking (every transaction examined for
E1/E2/E3/E4/NO_GST_REG errors) with a Claude reasoning layer for semantic edge cases, and
produces a reviewer-signed PDF working paper structured around the IRAS ASK Guide. The output
is not an IRAS submission — it is a pre-filing review document that a senior financial officer
or accountant reviews, annotates, and signs before filing.

---

## Architecture

**Layer 1 — Deterministic tools** (`mcp-servers/custom/sap_b1_server.py`): all arithmetic,
data fetching, and rule-based classification. Three custom GST tools (`calculate_f5_return`,
`validate_invoice_tax_codes`, `detect_gst_errors`) compute F5 boxes, classify every invoice
line against 18 VatGroup codes, and detect E1–E4, NO_GST_REG, and COMPLETENESS findings.
Claude is explicitly removed from the arithmetic path.

**Layer 2 — Reasoning + knowledge base** (`knowledge-base/sg-tax-code-mappings.md`,
`system-prompts/base.md`): Claude interprets tool output, applies judgment on edge cases
(semantic VatGroup appropriateness, E1 candidate validation, cross-finding correlation), and
follows the procedural constraints in the system prompt. The system never asserts a compliance
position without tool-confirmed evidence.

**Layer 3 — Orchestration chain** (`orchestrator/`): a deterministic six-step chain
(`fetch → gate_1 → calculate → gate_2 → classify → gate_3 → detect → gate_4 → compile →
gate_5`) replaces Claude's conversational tool selection. Each gate is pure arithmetic or
set-membership with no LLM call; a failing gate halts the chain before any downstream step
runs. Returns `(CompileOutput, gate_results)`.

**Audit bundle** (`audit_bundle/`): every successful run is sealed into a tamper-evident
bundle under `audit/<client_id>/`. SHA-256 per artefact + root hash over canonical JSON of
the manifest. `python -m audit_bundle.verify <bundle-dir>` re-hashes everything and confirms
nothing changed after sealing.

**Report package** (`report/`): consumes the `CompileOutput` JSON and renders a signed PDF.
The three-source join (classify amounts + detect severity + manifest backfill) is keyed by
`(doc_num, error_code)`; E2 findings are routed to the correct IRAS Document-2 amendment
template by VatGroup. No filing directives are generated — the reviewer signs and certifies.

---

## Status

All implementation milestones complete. Validated on SBODEMOSG (SAP B1 FP2502, Singapore
localisation) Q3 2024.

| Milestone | Description | Status |
|-----------|-------------|--------|
| T1.1 | Credit notes (`CreditNotes`, `PurchaseCreditNotes`) in all three tools | COMPLETE 2026-05-28 |
| T1.2 | NR VatGroup excluded from Box 5 per IRAS para 5.11(o); NR E2 detection | COMPLETE 2026-05-27 |
| T1.3 | Per-client YAML config (`config/clients/<id>.yaml`), 8-step validation pipeline | COMPLETE 2026-05-31 |
| T1.6 | Deterministic six-step chain with five gates; `run_agent.py` CLI | COMPLETE 2026-06-01 |
| T1.4 | Signed PDF report generator (`report/` package) | COMPLETE 2026-06-01 |
| T1.5 | Sealed audit bundle (`audit_bundle/`); SHA-256 tamper-evident; verify CLI | COMPLETE 2026-06-02 |

**Live validation figures (SBODEMOSG Q3 2024):**
```
Items examined : purchase_credit_note=1, purchase_invoice=21, sales_credit_note=1, sales_invoice=50
box_8 (net GST): 17,045.87
Issues (detect): 21
```

**Test suite: 169 tests passing** (1 skipped: read-only advisory, Windows; no live SAP required).

```
tests/test_gates.py              30 unit tests — all five gates
tests/test_chain.py              11 acceptance tests — chain + gate-failure paths
tests/test_routing.py            T1.4 — Document-2 template routing, E2-by-VatGroup
tests/test_enrich.py             T1.4 — three-source join, (doc_num, error_code) aggregation
tests/test_sections.py           T1.4 — eight sections, HitL language invariants
tests/test_report_e2e.py         T1.4 — full e2e from CompileOutput fixture to PDF
tests/test_audit_canonical.py    T1.5 — canonical_json, sha256_bytes/file
tests/test_audit_redaction.py    T1.5 — allow-list credential exclusion
tests/test_audit_seal_verify.py  T1.5 — seal/verify round-trip, tamper detection
tests/test_gate_record.py        T1.5 — gate_results shaping; GateFailure.checked
tests/test_run_agent_e2e.py      T1.5 — e2e seal from fixture; T7 determinism
```

**Validated on demo data only.** All results are against SBODEMOSG, an SAP-maintained demo
database. This is not a production validation.

---

## How to Run

### 1. Configure a client

Copy `config/clients/example.yaml` to `config/clients/<client_id>.yaml` and fill in
`service_layer_url`, `company_db`, `applicable_gst_rate`, and the env-var names for
credentials. The SBODEMOSG client is already at `config/clients/sbodemosg.yaml`.

Copy `config/env.example` to `.env` at repo root and set `SAP_USERNAME` and `SAP_PASSWORD`.

```bash
cp config/env.example .env
# edit .env: SAP_USERNAME=manager  SAP_PASSWORD=manager
```

### 2. Run the chain and seal a bundle

```bash
python run_agent.py --client sbodemosg --period 2024-07-01 2024-09-30
```

Every successful run renders the PDF and writes a sealed audit bundle:

```
=== CHAIN COMPLETE ===
  Items examined : {...}
  box_8 (net GST): 17,045.87
  Issues (detect): 21
  Report PDF     : exploration-notes/t1.4-reports/sbodemosg-2024-07-01-2024-09-30-<ts>.pdf

=== BUNDLE SEALED ===
  Bundle         : audit/sbodemosg/2024-07-01_2024-09-30/<run-ts>/
  Verify         : python -m audit_bundle.verify audit/sbodemosg/2024-07-01_2024-09-30/<run-ts>/
```

On `GateFailure` (arithmetic reconciliation failure), the chain halts with a message and no
bundle is written. The report requires `config/clients/<id>.yaml` to have `report.reviewer_name`
and `report.firm_name` set.

### 3. Audit bundles

Each bundle under `audit/<client_id>/<period>/<run-ts>/` contains eight artefacts covered by
`manifest.json` (per-artefact SHA-256 + root hash). To verify integrity after the fact:

```bash
python -m audit_bundle.verify audit/sbodemosg/2024-07-01_2024-09-30/<run-ts>/
# PASS  (or FAIL with a list of mismatched artefacts / root_hash mismatch)
```

The `audit/` directory is gitignored. Bundles contain no SAP credentials.

---

## Repository Layout

```
sap-b1-ai-agent/
├── config/
│   ├── clients/
│   │   ├── example.yaml          ← Schema template
│   │   └── sbodemosg.yaml        ← SBODEMOSG client (credentials via env vars)
│   ├── loader.py                 ← load_client_config() — 8-step validation
│   └── env.example               ← Env-var template
├── orchestrator/
│   ├── chain.py                  ← run_chain() — six steps + five gates
│   ├── gates.py                  ← gate_1 … gate_5 — pure arithmetic, no LLM
│   ├── steps.py                  ← fetch / calculate / classify / detect / compile
│   └── schemas.py                ← TypedDicts for all inter-step shapes
├── report/
│   ├── contract.py               ← CompileOutput input contract
│   ├── enrich.py                 ← Three-source join keyed by (doc_num, error_code)
│   ├── routing.py                ← Document-2 IRAS template routing
│   ├── sections.py               ← Eight report sections
│   └── render.py                 ← Section dicts → PDF
├── mcp-servers/custom/
│   └── sap_b1_server.py          ← 14 MCP tools; custom GST tools 12–14
├── knowledge-base/
│   └── sg-tax-code-mappings.md   ← VatGroup → F5 box routing; IRAS e-Tax Guide citations
├── system-prompts/
│   └── base.md                   ← Orchestration rules; compliance assertion constraints
├── scripts/
│   ├── run_baseline_tests.py     ← Reference implementation; auto-generates Test 3 reference
│   └── seed_test_data.py         ← Inserts SBODEMOSG test invoices + credit notes
├── audit/                        ← sealed audit bundles (generated; gitignored)
├── audit_bundle/                 ← T1.5: seal / verify / gate-record package
│   ├── canonical.py              ← canonical_json, sha256_bytes/file
│   ├── config_redaction.py       ← redact_config; allow-list; _DENY_ALWAYS
│   ├── gate_record.py            ← build_gate_results; gates.json schema
│   ├── manifest.py               ← build_manifest; root-hash construction
│   ├── provenance.py             ← gather_provenance; git SHA; file hashes
│   ├── seal.py                   ← seal_bundle; _AUDIT_ROOT; mark_readonly
│   └── verify.py                 ← verify_bundle; python -m audit_bundle.verify CLI
├── tests/
│   ├── fixtures/
│   │   └── chain-run-sample.json ← Static CompileOutput for e2e tests
│   └── test_*.py                 ← 169 tests; no live SAP required
└── exploration-notes/
    ├── baseline-test-results.md  ← V0→V3 experimental log; all three tests
    └── t1.4-reports/             ← PDF reports (generated; gitignored)
```

---

## Limitations and Known Gaps

- **Custom VatGroup codes**: transactions coded to non-standard VatGroups fall into `anomalies`
  and are silently excluded from all F5 calculations. A client with material custom-VatGroup
  volume will receive an undercount.
- **Header-level TaxTotal**: the tools use `TaxTotal` at `DocumentLines` level. SAP B1
  configurations that store tax at header level or in `VatSum` will produce incorrect results.
- **NO_GST_REG false positives**: the check uses `FederalTaxID` on `BusinessPartners`. Clients
  whose SAP B1 stores GST registration numbers in a UDF will see false positives on every
  purchase invoice with input tax.
- **Re-derivability boundary**: the sealed bundle records what the chain saw, not a frozen
  SAP snapshot. Full offline replay from frozen line bytes is deferred to the Tier-2 source
  adapter (`rederivation_grade: "same-SAP-state"`).
- **Live SAP B1 only**: there is no CSV/extract source adapter. The chain requires a live SAP
  B1 Service Layer connection. Substituting an alternative source requires changes to step
  function signatures.
- **Manual journals not examined**: `JournalEntries` are not fetched. GST-relevant manual
  journals are invisible to the system.
- **Demo data only**: all validation is against SBODEMOSG Q3 2024. Behavior on production data
  (partial exemption, reverse charge, rate-transition periods, multi-company configurations)
  has not been tested.

Items not examined in any given run are listed explicitly in the report's "Items Not Examined"
section. For the full gap register see `AGENTASSIST_TECHNICAL_STATE.md`.

---

*Not legal or tax advice. Not reviewed or approved by IRAS. The generated PDF is a working
paper; the reviewer of record certifies its contents before any filing or submission.*
