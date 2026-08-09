# AgentAssist — Singapore GST Compliance Review

AgentAssist performs line-level Singapore GST review over a client's accounting export and
produces a **working paper that a named reviewer adjudicates and signs**. It examines every
transaction in the period rather than a sample, computes the F5 boxes deterministically, and
surfaces candidates for human judgment where the answer depends on facts the data does not
contain.

The output is **not** an IRAS submission. It is a pre-filing review document. A senior
reviewer — in practice an accredited tax professional — decides on each finding and certifies
the result under their own name.

The system is built around one constraint: **it surfaces, it never asserts.** No finding is a
verdict. No arithmetic passes through a language model.

---

## Honest status

Every claim below sits somewhere on this ladder, and the rungs are not interchangeable:

> **built ≠ hermetic ≠ offline-replay-validated ≠ real-client-export-validated ≠ accuracy-validated**

Where things actually stand:

| Layer | Status |
|---|---|
| Deterministic chain (F5 computation, mechanical checks, five gates) | **offline-replay-validated** — re-derives byte-identically from frozen fixtures |
| Export adapters (SAP B1 extract, Xero export) | **built, synthetic-format-validated** — no real client export has been read |
| Reasoning layer (candidate surfacing) | **built, unvalidated** — output suppressed by default |
| Accuracy against IRAS ground truth | **not established** |

`validation_status` is hard-coded to `"unvalidated"` and `show_ai_candidates` defaults to
`False`. Both stay that way until an independent SCTP-accredited GST specialist reconciles the
system's findings against their own review. That gate is unmet. **Nothing here is fit to be
relied on for a filing decision.**

---

## Architecture

Three layers, with a hard boundary between them.

**Layer 1 — Deterministic chain** (`orchestrator/`). A fixed six-step sequence with five
reconciliation gates:

```
fetch → gate_1 → calculate → gate_2 → classify → gate_3 → detect → gate_4 → compile → gate_5
```

Every gate is pure arithmetic or set membership. No model call. A failing gate **halts the
chain** — the run produces nothing rather than producing something confidently wrong. This
package contains no `anthropic` import, and CI enforces that by AST scan rather than by
convention.

Mechanical checks: tax-code errors E1–E4, unregistered-supplier input tax (`NO_GST_REG`),
period completeness, invoice sequence gaps, duplicate claims, same-day and windowed duplicate
candidates, and declared-vs-computed F5 divergence when a filed return is supplied.

**Layer 2 — Guardrailed reasoning** (`reasoning/`, `knowledge-base/slices/`). Claude reads
narrow, hand-authored slices of IRAS guidance and surfaces candidates in the form *"consider
reviewing whether…"*. It never returns a verdict, never touches an F5 box, and never enters a
gate. Every knowledge-base slice is written from named IRAS sources — no tax semantics are
derived from model output or from practitioner recollection.

**Layer 3 — Review surface** (`api/`, `frontend/`, `report/`). A FastAPI backend and React
front end present the findings as a queue. The reviewer works each item — vendor, what was
found, why it matters, the rule, the suggested action — decides, and signs. Signing renders a
PDF working paper carrying the reviewer's name. Findings lead with the IRAS ASK Appendix 1
category wording so a tax-literate reader recognises the classification immediately.

**Audit bundle** (`audit_bundle/`). Each sealed run is tamper-evident: SHA-256 per artefact
plus a root hash over canonical JSON of the manifest. `python -m audit_bundle.verify <dir>`
re-hashes everything and reports PASS or the specific mismatches.

### Ingestion

The primary path is a **period export file** from the client's accounting system — currently
SAP B1 extracts and Xero exports — normalised at the feeder and handed to an unchanged
checking core. One machine, two feeders.

A live SAP B1 Service Layer connector also exists and was the original path. It is retained,
but export-first is the direction: it requires no ERP credentials, no network access to a
production system, and no client IT involvement.

An offline-replay harness re-derives the entire deterministic chain from frozen fixtures with
no ERP reachable, byte-identical to a captured oracle. That harness is the acceptance
mechanism for every change to the deterministic path.

---

## Limitations and known gaps

Read this section before anything else. It is not exhaustive; the full register lives in
`AGENTASSIST_TECHNICAL_STATE.md`.

- **No real client export has ever been read.** Both adapters are validated against
  *synthetic* exports built to the format we believe clients produce. The format assumption
  closes only when a real export arrives.
- **The extract path currently understates F5 boxes** (open item #49). Sales `SO` and purchase
  `SI` lines fall into the anomalies bucket as unmapped tax codes for non-SAP-sourced configs,
  so Box 1 and Box 5 render materially low against the replay oracle on the same data. Filed,
  unfixed. **The extract branch must not be demonstrated until this is resolved.**
- **Accuracy is unvalidated.** No independent specialist has reconciled the findings. There is
  no measured recall, no measured false-positive rate, no per-category basket.
- **Custom tax codes are silently excluded.** Transactions on non-standard codes fall into
  `anomalies` and leave the F5 computation entirely. A client with material custom-code volume
  receives an undercount.
- **Header-level tax breaks it.** The tools read tax at line level. Configurations storing tax
  at header level, or in `VatSum`, produce incorrect results.
- **Unregistered-supplier false positives.** The check reads the supplier's registration
  number from the standard field. Clients storing it in a user-defined field will see a false
  positive on every purchase invoice carrying input tax.
- **Manual journals are invisible.** Journal entries are not fetched. GST-relevant manual
  journals are not examined.
- **Document reading raises recall, not authority.** A finding derived from reading a PDF is
  capped as judgment-assisted. Extracted values never enter the F5 boxes or the gates.
- **Untested regimes.** Partial exemption, reverse charge, rate-transition periods, and
  multi-company configurations have not been exercised against real data.

Whatever a given run did not examine is listed explicitly in the working paper's *Items Not
Examined* section, so the coverage boundary is visible to whoever signs.

---

## Design commitments

These are enforced, not aspirational. Each has a test that fails if it is violated.

- **Surfaces, never asserts.** The system flags candidates; a named human adjudicates.
- **No model on the arithmetic path.** `orchestrator/` is pure Python; the absence of an
  `anthropic` import is checked by AST scan in CI.
- **Box isolation.** F5 box values and gate results are byte-identical with and without any
  findings stream, reasoning pass, or document adapter attached. Asserted at runtime via
  canonical JSON, not merely tested.
- **Halt over guess.** A reconciliation failure stops the run. No bundle is sealed, no report
  is rendered.
- **Tax semantics from named sources only.** Knowledge-base slices cite IRAS e-Tax Guides
  directly. Practitioner observations are recorded *verify-before-encode* and are not treated
  as tax fact until checked against the guidance.
- **Labelled data is for evaluation, never training.** Claude is used through the API; no
  weights are ever updated.

---

## Running it

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# regenerate gitignored document fixtures (deterministic; safe to re-run)
python tests/fixtures/documents/generate_invoices.py

python -m pytest
```

The suite is hermetic — no live ERP, no API tokens, no network.

**Review surface:**

```bash
uvicorn api.app:app --reload          # backend on :8000
cd frontend && npm install && npm run dev   # front end on :5173
```

**Chain over a live SAP B1 connection** (optional; requires credentials):

```bash
cp config/env.example .env
# set SAP_USERNAME=<your-username> and SAP_PASSWORD=<your-password>
python run_agent.py --client <client_id> --period 2024-07-01 2024-09-30
```

A successful run renders the PDF and seals an audit bundle. On a gate failure it halts with a
message and writes nothing. Verify a sealed bundle at any later point:

```bash
python -m audit_bundle.verify audit/<client_id>/<period>/<run-ts>/
```

The `audit/` directory is gitignored and bundles carry no credentials.

---

## Repository layout

```
orchestrator/     Deterministic chain, five gates, mechanical checks — pure Python, no model
feeders/          Export adapters (SAP B1 extract, Xero) — pure stdlib leaf
reasoning/        Guardrailed candidate surfacing — the only package importing anthropic
knowledge-base/   VatGroup → F5 box routing; hand-authored IRAS guidance slices
agent/            Agentic shell: check registry, hash-chained decision ledger, eval harness
engine/           Stable review() seam over the chain
api/              FastAPI review + sign + audit endpoints
frontend/         React review surface (queue, finding detail, sign, audit trail)
report/           CompileOutput → signed PDF working paper
audit_bundle/     Canonical JSON, SHA-256 manifest, seal + verify
tests/            Hermetic suite incl. offline-replay harness and frozen fixtures
docs/             Merge gates, import boundaries, architectural invariants
```

---

## Tests

The suite runs without a live ERP, without API tokens, and without network access. It includes
the offline-replay harness, box-isolation runtime assertions, import-boundary AST scans, and
frozen-fixture regression against a captured oracle.

Run `python -m pytest` for the current count. CI is pytest-gated; the front-end `vitest` suite
runs separately and is not the merge gate.

---

*Not legal or tax advice. Not reviewed or approved by IRAS. The generated document is a
working paper; the reviewer of record certifies its contents before any filing or submission.
Accuracy is unvalidated — see Honest status above.*
