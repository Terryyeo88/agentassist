# AgentAssist Codebase State Report
*Generated: 2026-05-28 | Branch: master | Author: Claude (read-only survey)*

---

## Part 1 — Git / Collin's Branch

### Fetch & Status

```
git fetch --all  →  already up to date (origin/master == local master at 6133864)
git status       →  On branch master, nothing to commit, working tree clean
```

### Recent Commits (last 3 days, all branches)

```
adeb85f  t1.2                                       ← Collin's branch
6133864  Add untracked documentation and verification artefacts
2f594c5  Add business framing and value proposition section to technical state
05df9bf  Update AGENTASSIST_TECHNICAL_STATE.md…
4065057  V3 Test 3 documentation: complete Test 3 experimental record
c7914a7  V1/V2 Test 3 documentation: reclassification and scoring
b65f224  Extend run_baseline_tests.py with E2, NO_GST_REG, COMPLETENESS checks
fa85517  Security hygiene and severity alignment
52aadb1  Merge phase2-accounting-workflows into master
...
```

### Branches

```
* master
  phase2-accounting-workflows          (local, already merged)
  remotes/origin/Collin's-branch       ← Collin's T1.2 work
  remotes/origin/HEAD -> origin/master
  remotes/origin/master
  remotes/origin/phase2-accounting-workflows
```

### Collin's Commit

Commit `adeb85f` (author: ChefMilo / collinteo2003@gmail.com, 2026-05-27) sits **one commit ahead** of current master tip `6133864`. The merge-base equals master tip:

```
merge-base(master, origin/Collin's-branch) == 6133864 == master HEAD
```

This is a **clean fast-forward** — no divergence, no merge commit needed.

Files changed in `adeb85f`:

```
exploration-notes/nr-vatgroup-resolution.md   +15 (new file)
mcp-servers/custom/sap_b1_server.py           +4/-1
scripts/run_baseline_tests.py                 +3/-1
scripts/seed_test_data.py                     +22
scripts/test_data_registry.json               +31/-17
system-prompts/base.md                        +7/-2
```

### Recommended Pull Command

You are on `master`. Since this is a clean fast-forward, the safe command is:

```bash
git merge --ff-only "origin/Collin's-branch"
```

This will advance master to `adeb85f` with no merge commit. If it reports "Not possible to fast-forward", do NOT proceed — fetch again and re-check. Do not use `--no-ff` unless you want a merge commit for audit purposes.

---

## Part 2 — T1.2 NR VatGroup Fix: Four-Artefact Check

**Important context**: Collin's fix is on `origin/Collin's-branch` and has **not yet been merged into master**. The artefact checks below cover both states.

### Artefact 1 — `mcp-servers/custom/sap_b1_server.py` F5_BOX_MAPPING

**On master (line 166):**
```python
"NR":     {"lt_box": "box_5_taxable_purchases",    "tt_box": None,    "side": "purchase"},
```
→ NR is **INCLUDED** in Box 5 on master.

**On Collin's branch:**
```python
"NR":     {"description": "Non-GST registered purchase", "lt_box": None, "tt_box": None, "side": "purchase"},
# NR excluded from Box 5 per IRAS para 5.11(o): purchases from non-GST registered
# traders are not taxable purchases; no input tax is claimable on these.
```
→ NR is **EXCLUDED** from Box 5 on Collin's branch. ✓

### Artefact 2 — `scripts/run_baseline_tests.py` PURCHASE_BOX5

**On master (line 38):**
```python
PURCHASE_BOX5 = {"SI", "ZP", "IM", "IGDS", "ME", "NR"}
```
→ NR is **INCLUDED** in Box 5 on master.

**On Collin's branch:**
```python
PURCHASE_BOX5 = {"SI", "ZP", "IM", "IGDS", "ME"}
# NR excluded per IRAS para 5.11(o): purchases from non-GST registered traders
```
→ NR is **EXCLUDED** from Box 5 on Collin's branch. ✓

Additionally, KNOWN_VATGROUPS entry on master still reads `"NR": ("Box 5 only", "Non-GST-registered supplier")`. On Collin's branch this is updated to match the excluded status.

### Artefact 3 — `system-prompts/base.md`

**On master (lines 39, 68):**
```
| Box 5 | Taxable purchases … | SI, ZP, IM, IGDS, ME, NR | Purchase |
...
| NR | Non-GST-registered supplier | Box 5 | — (no tax) |
```
→ NR is **INCLUDED** in Box 5 on master.

**On Collin's branch:**
```
| NR | Non-GST-registered supplier | Excluded | Excluded |
...
> **NR**: Excluded from Box 5 per IRAS para 5.11(o) — purchases from non-GST
> registered traders are not taxable purchases. Do not include NR LineTotal in Box 5.
```
→ NR is **EXCLUDED** with explicit IRAS citation. ✓

### Artefact 4 — `knowledge-base/sg-tax-code-mappings.md`

**On both master and Collin's branch** (file not modified by Collin):
```
| NR | Purchase Non-GST Registered | **Excluded** | N/A |
     **Per IRAS para 5.11(o): purchases from non-GST registered traders are EXCLUDED from Box 5**
```
→ NR is **EXCLUDED** and cites IRAS para 5.11(o). ✓ (consistent on both branches)

### Artefact 5 — `exploration-notes/nr-vatgroup-resolution.md`

**On master**: File does **not exist**.

**On Collin's branch**: File exists (15 lines). Content is a seed invoice record:

```markdown
## Seed Invoice Result (2026-05-27)

**DocEntry**: 613 | **DocNum**: 611 | **LineTotal**: 500.00
**TaxTotal**: 45.00 (preserved by SAP B1 tax engine) | **VatGroup**: NR

**Finding**: SAP B1 preserved the non-zero TaxTotal on the NR line. This invoice is
therefore both a Box 5 exclusion test and a genuine E2 error (non-taxable purchase
carrying GST). The E2 check in validate_invoice_tax_codes should flag this invoice.
```

**IRAS paragraph citation**: The file itself does **not** directly quote IRAS para 5.11(o). The IRAS para 5.11(o) citation is present in the `sap_b1_server.py` code comment and the `system-prompts/base.md` blockquote on Collin's branch, but the resolution file reads as a seed data note rather than a formal resolution document. This is a minor gap — the citation lives in the code, not the exploration note.

### Four-Artefact Verdict

| Artefact | On master | On Collin's branch |
|---|---|---|
| `sap_b1_server.py` F5_BOX_MAPPING NR | INCLUDED in Box 5 ✗ | EXCLUDED (lt_box: None) ✓ |
| `run_baseline_tests.py` PURCHASE_BOX5 | INCLUDED ("NR" in set) ✗ | EXCLUDED (NR removed) ✓ |
| `system-prompts/base.md` NR row | INCLUDED in Box 5 ✗ | EXCLUDED with IRAS cite ✓ |
| `knowledge-base/sg-tax-code-mappings.md` | EXCLUDED (IRAS 5.11(o)) ✓ | EXCLUDED (unchanged) ✓ |

**On master today (before merge): 3 say INCLUDED, 1 says EXCLUDED — inconsistent.**
**On Collin's branch: all 4 agree NR is EXCLUDED — consistent. Fix is correct.**

The fix is ready to merge. The only cosmetic gap is that `nr-vatgroup-resolution.md` is a seed-invoice note rather than a prose resolution document; IRAS para 5.11(o) is cited in the code and prompt but not in the exploration note itself.

---

## Part 3 — State-of-the-Codebase Report

### 1. Repository Structure

```
sap-b1-ai-agent/
├── .claude/
│   └── settings.local.json
├── .env                                  ← credentials (not tracked by git) ⚠
├── .gitignore
├── AGENTASSIST_TECHNICAL_STATE.md
├── README.md
├── claude-code-master-prompt-phase2-tools.md
├── config/
│   └── env.example
├── exploration-notes/
│   ├── baseline-test-report-v0.json
│   ├── baseline-test-results.md
│   ├── docnum-605-verification.md
│   ├── security-decisions.md
│   ├── v0-raw-chats/  (test1, test2, test3 .md files)
│   ├── v1-raw-chats/  (test1, test2, test3 .md + image.png)
│   ├── v2-raw-chats/  (test1, test2, test3 .md; test1 is a directory, not .md)
│   └── v3-raw-chats/  (test1, test2, test3 .md files)
├── keys/
│   ├── sap-b1-poc-sg.pem                 ← TRACKED BY GIT ⚠ (see §9)
│   └── sap_credentials.json              ← not tracked, but plaintext password ⚠
├── knowledge-base/
│   └── sg-tax-code-mappings.md
├── mcp-servers/
│   ├── MCP-SAP/                          ← third-party submodule/clone (.git inside)
│   │   └── (azure-container-app.yaml, Dockerfile, sap_client.py, server.py, etc.)
│   └── custom/
│       ├── README.md
│       ├── requirements.txt
│       └── sap_b1_server.py              ← primary MCP server
├── scripts/
│   ├── cleanup_test_data.py
│   ├── run_baseline_tests.py
│   ├── seed_test_data.py
│   ├── test-service-layer.sh
│   ├── test_data_registry.json
│   └── verify_docnum_605.py
├── skills/                               ← exists but empty / no files listed
├── system-prompts/
│   ├── base.md
│   ├── test1-prefix.md
│   └── test2-prefix.md
```

**Stale / notable items:**
- `exploration-notes/v2-raw-chats/test1-f5-calculation` is a **directory**, not a `.md` file — likely created by accident; everything else in that pattern is a `.md` file.
- `mcp-servers/MCP-SAP/` contains a nested `.git` directory — this is either a submodule or an embedded clone. It has Azure deployment files (`azure-container-app.yaml`, `Dockerfile`, `deploy-azure.ps1`) suggesting it's a separate/upstream server that is not used by the current custom server.
- `claude-code-master-prompt-phase2-tools.md` at repo root — appears to be a planning/prompt artefact, not production code.
- `skills/` directory exists but contains no files (not shown in listing).

---

### 2. Credit Notes in the Three Custom MCP Tools

| Tool | Entities fetched | Credit notes? |
|---|---|---|
| `calculate_f5_return` | `Invoices`, `PurchaseInvoices` | **No** |
| `validate_invoice_tax_codes` | `Invoices`, `PurchaseInvoices` | **No** |
| `detect_gst_errors` | `Invoices`, `PurchaseInvoices` | **No** |

All three tools call `_fetch_invoices_paginated(entity, ...)` with `"Invoices"` and `"PurchaseInvoices"` only. Neither `CreditNotes` nor `PurchaseCreditNotes` appear anywhere in `sap_b1_server.py`.

**T1.1 (credit notes) has NOT been started.**

---

### 3. Per-Client Config (T1.3)

- **No YAML client config exists.** No `config/clients/`, `config/*.yaml`, or equivalent.
- **No `run_agent.py` launcher exists.** There is only `mcp-servers/custom/sap_b1_server.py` (stdio MCP server) and stand-alone scripts.
- **No config loader class exists.**
- **Hardcoded fallbacks: REMOVED.** `SAPB1Client.__init__` now raises `RuntimeError` cleanly if any of `SAP_BASE_URL`, `SAP_COMPANY_DB`, `SAP_USERNAME`, `SAP_PASSWORD` are missing from the environment — no default values are hardcoded in the class itself. ✓
- **However, `scripts/run_baseline_tests.py` and `scripts/seed_test_data.py` still hardcode** `BASE_URL = "https://35.186.145.230:55000/b1s/v2"`, `COMPANY_DB = "SBODEMOSG"`, and `USERNAME = "manager"` as module-level constants. The password is loaded from `keys/sap_credentials.json` or prompted interactively. These scripts are standalone evaluation tools, not the MCP server, but they would need updating for any multi-client scenario.

**T1.3 (per-client config): NOT STARTED.**

---

### 4. Orchestration (T1.6)

There is **no orchestrator, chain, pipeline, or workflow code** in the repository. No files named `orchestrator.py`, `pipeline.py`, `chain.py`, or similar exist. There is no LangChain, LangGraph, or equivalent framework dependency.

The system currently operates **conversationally**: Claude Desktop receives a user prompt, selects which MCP tools to call, calls them in order, and synthesises the response. Tool sequencing is handled by Claude at inference time, not by any pre-wired pipeline.

**T1.6 (orchestration): NOT STARTED.**

---

### 5. Report Generation (T1.4)

- **No `report_generator.py`** or equivalent module.
- **No `templates/` directory.**
- **No PDF generation code** (no imports of `reportlab`, `weasyprint`, `fpdf`, `pdfkit`, etc.).
- `run_baseline_tests.py` writes a JSON file (`baseline-test-report-v0.json`) and appends markdown to `baseline-test-results.md` — this is a test harness output, not a client-facing GST return report.

**T1.4 (report generation): NOT STARTED.**

---

### 6. Audit Trail (T1.5)

- **No `audit_logger.py`** or equivalent module.
- **No `engagements/` directory.**
- **No run-sealing, hash-signing, or immutable log code.**
- `scripts/test_data_registry.json` records seeded DocNums/DocEntries with a timestamp — this is test bookkeeping, not a compliance audit trail.

**T1.5 (audit trail): NOT STARTED.**

---

### 7. `scripts/run_baseline_tests.py` — Implemented Check Types

The script (on current master) implements the following check types:

| Check | Where implemented | What it detects |
|---|---|---|
| **E1** | `run_test_3` sales loop | FX sales invoice using SO/DS (standard-rated) instead of ZR |
| **E2** | `run_test_3` sales + purchases loop | Non-zero TaxTotal on codes in `E2_ZERO_RATE_CODES` = {ZR, OS, ES33, ESN33, BL} |
| **E3** | `run_test_3` sales + purchases loop | SO/DS/SI with LineTotal > 0 and TaxTotal = 0 |
| **E4** | `run_test_3` sales + purchases loop | GST rate deviates from expected (threshold 0.005; checks SO+DS sales, SI+IM+IGDS purchases) |
| **NO_GST_REG** | `run_test_3` BP lookup | Supplier with input tax claims but no FederalTaxID in BusinessPartners |
| **COMPLETENESS** | `run_test_3` ratio check | purchase_count / sales_count < 0.10 |

Quote from line 553 (notes string): `"Checks: E1, E2(sales+purchases,incl.BL), E3, E4, NO_GST_REG, COMPLETENESS."`

**Known documented divergences from `sap_b1_server.py`** (recorded in script comments, not bugs):
- E4 threshold: script uses 0.005, MCP tool uses 0.001
- E4 purchase scope: script checks SI+IM+IGDS, MCP tool checks SI only
- E4 sales scope: script checks SO+DS, MCP tool checks SO only

---

### 8. Tests / Fixtures

**`seed_test_data.py` seeds 6 invoices:**

| # | Entity | VatGroup | Description |
|---|---|---|---|
| 1 | Invoices | ZR | Export Sale – Zero-rated sales |
| 2 | Invoices | ES33 | Financial Advisory – Exempt sales |
| 3 | Invoices | OS | Overseas Goods – Out of scope |
| 4 | PurchaseInvoices | BL | Staff Club Membership – Blocked input tax |
| 5 | PurchaseInvoices | IM | Imported Components – Import GST |
| 6 | PurchaseInvoices | ZP | International Freight – Zero-rated purchase |

No NR, SI, SO, or DS fixture exists in the seed script.

**`test_data_registry.json`** (on current master): Records the last seed run (2026-05-25). Contains 3 sales invoices (DocNums 1000–1002) and 3 purchase invoices (DocNums 605–607). **No credit note fixtures** of any kind.

Note: Collin's branch adds a 7th entry — a PurchaseInvoice with VatGroup NR (DocNum 611, DocEntry 613) — to the registry and seed script. This is the NR Box 5 exclusion test case for T1.2 verification.

---

### 9. Security Hygiene

| Item | Status |
|---|---|
| `.gitignore` present | ✓ Yes |
| `.gitignore` excludes `keys/` | ✓ Yes (`keys/` on line 5) |
| `.gitignore` excludes `.env` | ✓ Yes (line 2) |
| `.gitignore` excludes `*.pem` | ✓ Yes (line 6) |
| `.env` tracked by git | ✓ Not tracked |
| `keys/sap_credentials.json` tracked by git | ✓ Not tracked |
| **`keys/sap-b1-poc-sg.pem` tracked by git** | **⚠ YES — committed** |
| Plaintext credentials in working tree | ⚠ `keys/sap_credentials.json` contains `"password": "manager"` in plaintext; `.env` contains `SAP_PASSWORD=manager` — both excluded from git, but present on disk |
| Credentials hardcoded in scripts | ⚠ `run_baseline_tests.py` and `seed_test_data.py` hardcode `BASE_URL`, `COMPANY_DB`, `USERNAME` — password is loaded from file/prompt, not hardcoded |

**Critical finding**: `keys/sap-b1-poc-sg.pem` appears in `git ls-files keys/` — this PEM key file is **committed to the repository** despite `*.pem` and `keys/` both being in `.gitignore`. This means it was added to git before or independently of the `.gitignore` entry, and `.gitignore` does not un-track already-tracked files. The file is in git history. **Do not fix in this task** (per your instructions), but you should run `git rm --cached keys/sap-b1-poc-sg.pem` and rotate the key if it is still valid.

No other plaintext secrets were found committed in the current working tree files outside of `keys/` and `.env`.

---

### 10. Tier 1 Task Gaps Summary

| Task | Description | Status | Evidence |
|---|---|---|---|
| **T1.1** | Credit notes in F5/validate/detect tools | **NOT STARTED** | None of the 3 tools fetch CreditNotes or PurchaseCreditNotes |
| **T1.2** | NR VatGroup exclusion fix | **DONE** (on Collin's branch, pending merge) | All 4 artefacts consistent on `origin/Collin's-branch`; clean fast-forward ready |
| **T1.3** | Per-client YAML config + launcher | **NOT STARTED** | No config loader, no YAML, no run_agent.py; env-var enforcement present but no multi-client support |
| **T1.4** | GST return report generation | **NOT STARTED** | No report_generator, no templates/, no PDF library |
| **T1.5** | Audit trail / engagement sealing | **NOT STARTED** | No audit_logger, no engagements/, no run-sealing logic |
| **T1.6** | Orchestration pipeline | **NOT STARTED** | No orchestrator; system is fully conversational (Claude picks tools at inference time) |

---

*End of report. No code was modified during this survey.*
