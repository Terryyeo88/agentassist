# Known limitations — Xero demo path (T2.12-Xero)

**Status: PROPOSED / DEMO — not authored, not validated.**

This document tracks the known debt carried by the Xero F5 feeder demo path so the
items are *tracked, not orphaned*. The Xero path ships as a **format-synthetic demo**:
it parses the real Xero "GST F5 Return → Transactions by box number" export format
against a committed synthetic fixture. It is **not** real-client validated and **not**
accuracy-validated, and its tax-code mapping citations are **deferred**.

Companion files:
- Config: `config/clients/xero_demo.yaml` (PROPOSED/DEMO, deferred citations)
- Fixture: `tests/fixtures/xero-f5-export/AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx`

Ground truth for the line/file references below is re-recon commit `294490e`;
re-verify before acting on any line number.

---

## Debt items

### DEBT-1 — IRAS citations deferred for the five tax-code mappings
The five `tax_code_mappings` entries in `xero_demo.yaml` carry `cite DEFERRED` markers
instead of confirmed IRAS authority. Each must be traced to a confirmed IRAS Annex E
row before the mapping is gate-clean. Per the NR-in-Box-5 rule, model inference is not
authority. **Owner: Terry.** Blocks: treating the Xero mapping as "authored".

### DEBT-2 — Category assignments are Terry-provided demo values, not gate-clean
`STANDARD-RATED SUPPLIES→SR`, `STANDARD-RATED PURCHASES→TX`, `SR-NOGST→SR`,
`ZR-BROKEN→ZR`, `SI-STALE→TX` are demo categories supplied by Terry. They are plausible
but unconfirmed against the IRAS guide; the config header and status are
**PROPOSED/DEMO**, not authored. Resolved together with DEBT-1.

### DEBT-3 — Not real-client validated
The path is validated only against the committed synthetic fixture in the real Xero
*format*. Real-client validation awaits Avinash's NDA'd Xero export. Until then: demo
only, not customer-facing.

### DEBT-4 — SAP-path E4 `expected_rate` defaults to 0.07 (found bug, NOT fixed here)
`_classify_line` (`mcp-servers/custom/sap_b1_server.py:747`) and the call sites at
`:1224`, `:1364` default `expected_rate` to `0.07`. This is a pre-existing SAP-path bug
surfaced during recon. It is **deliberately left untouched** by the Xero work (no
opportunistic fix). Tracked here for separate remediation.

### DEBT-5 — Xero E4 rate threading not wired
The client's `applicable_gst_rate` (0.09) is not threaded into `_classify_line`. Until
the feeder build wires it (subject to Terry's rate-threading ruling), E4 compares
against the 0.07 default and fires spuriously on every clean 9% line. This is the one
unresolved seam gating the Phase-2 build.

### DEBT-6 — DUP_CLAIM basis differs on the Xero path
`detect_dup_claims` (`orchestrator/check_listing.py:167`) keys on
`(CardCode, NumAtCard, DocTotal)` and skips blank `NumAtCard`. The Xero export has no
`NumAtCard`, and the true duplicate pair (BILL-3004/3005) has the same Contact +
amount but *different* References. The Xero path must source the dup key from
`(Contact, amount)` and declare DUP_CLAIM **degraded**. Prefer an additive Xero-specific
path over editing the SAP detector (box-isolation/determinism).

### DEBT-7 — NO_GST_REG unreachable on the Xero path
The export has no business-partner master and no `FederalTaxID` column, so NO_GST_REG
cannot run — it surfaces as coverage **unavailable** (`feeders/coverage_status.py:145-148`).
BILL-3003 ("NoReg Trading") therefore cannot be flagged; this is honest degradation,
not a missed finding.

### DEBT-8 — SEQ_GAP out of scope on the Xero path
No `Series`, `Cancelled`, or company-wide listing in the export → SEQ_GAP is out of
scope (degraded/unavailable via the coverage seam). No within-period sequence range is
testable.

### DEBT-9 — Loader requires a `sap_b1` block + credential env vars for a Xero-only client
`config/loader.py:273-277, 295-302` require a `sap_b1` block and resolve its credential
env vars at load, even when `source_system != "sap_b1"`. The demo config uses a **dummy
`sap_b1` block** as a workaround. A cleaner fix — making `sap_b1` optional when
`source_system != "sap_b1"` — touches shared config validation and needs its own
invariant review; deferred.

### DEBT-10 — `source_system` docstring understates its effect
`config/loader.py:114-116` documents `source_system` as "logging/display only", but it
is functionally load-bearing via `effective_tax_code_mappings` (`:195-197`), where any
value other than `"sap_b1"` suppresses the SAP SO/SI defaults. The docstring should be
corrected; do not rely on it for the three-times rule.
