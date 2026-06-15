# T2.21a — Live Recon Findings (SOP step 2)

**Status:** Read-only discovery. No source files, configs, fixtures, or
`generate_invoices.py` were modified. This note is the sole deliverable of
this slice.

**Branch:** `worktree-t2.21a-annex-e-baseline-vocab-recon` (see "Branch
naming" note at the end — the harness's `EnterWorktree` tool auto-prefixed
the requested `t2.21a-annex-e-baseline-vocab-recon` with `worktree-`).

**Method:** Direct Python import of `mcp-servers/custom/sap_b1_server.py`
(bypassing the FastMCP `@mcp.tool()` wrapper — same approach as T2.20),
against live `SBODEMOSG` (`CLIENT_ID=sbodemosg`), period `2024-07-01`..
`2024-07-07` (same window T2.20 used, for direct comparability). Ran
`calculate_f5_return`, `validate_invoice_tax_codes`, `detect_gst_errors`,
plus a direct raw-`DocumentLines` pull (no `normalize_vat_group`) to isolate
SAP's own output from any AgentAssist-side processing.

---

## 1. What VatGroup strings SBODEMOSG returns live, today

**Raw SAP B1 `DocumentLines[].VatGroup` values, before any AgentAssist
processing:**

```
raw sales VatGroup codes seen:    {'SO'}
raw purchase VatGroup codes seen: {'SI'}
```

(13 sales lines tagged `SO`, 1 purchase line tagged `SI` — consistent with
T2.20's Section 0 counts for this window.)

**After the full `_classify_line` / `calculate_f5_return` pipeline**
(`normalize_vat_group` → `F5_BOX_MAPPING.get()`):

- `validate_invoice_tax_codes`'s `vatgroup_inventory` keys: `['SO', 'SI']`,
  both `known_to_mapping: true`, routed to `box_1_standard_rated_sales` /
  `box_6_output_tax` (SO) and `box_5_taxable_purchases` /
  `box_7_input_tax` (SI) respectively.
- `calculate_f5_return`'s `anomalies: []` — no unknown-VatGroup anomalies.
- `'SR' in F5_BOX_MAPPING` → `False`, `'TX' in F5_BOX_MAPPING` → `False`
  (neither string exists anywhere in the current vocabulary).

**Conclusion: SBODEMOSG returns `SO`/`SI` today, unchanged, identically to
T2.20's recon.** No AgentAssist-side configuration currently transforms these
strings before they reach `F5_BOX_MAPPING`.

---

## 2. Is it (a) or (b)?

**Answer: (b) is the correct model — with one important refinement (call it
(b′)) that changes where the "first failing test" should be aimed.**

### Evidence that (a) is false

(a) claims "SAP B1 itself will hand back SR/TX … because SBODEMOSG's
tax-code configuration already uses or could be repointed to these strings."

- The raw-`DocumentLines` pull (no normalization applied at all) shows SAP B1
  handing back the literal strings `"SO"` and `"SI"` — these come from
  SBODEMOSG's own `SalesTaxCodes`/tax-code master data inside the SAP company
  database, which is **SAP-side configuration that AgentAssist's codebase
  does not own, read, or write**. `mcp-servers/custom/sap_b1_server.py` has
  no code path that configures or renames SAP B1 tax codes — it only
  *consumes* the `VatGroup` field SAP already populates on each
  `DocumentLines` entry.
- Even if SBODEMOSG's tax-code master data *could* theoretically be
  "repointed" to emit `SR`/`TX` strings, that would be an out-of-band SAP
  administration change to a shared public demo company database — entirely
  outside AgentAssist's deployment surface, and not something a code-level
  rename in this repo can cause or rely on. AgentAssist must work correctly
  against SBODEMOSG (and any other SAP B1 client) **as configured today**,
  i.e. returning `SO`/`SI`.
- → (a) is rejected: a "simple key rename" in `F5_BOX_MAPPING` from `SO`/`SI`
  to `SR`/`TX`, with no other change, would make every live SBODEMOSG sales/
  purchase line an "unknown VatGroup" anomaly (see §3 below) — `calculate_f5_return`
  would report `anomalies: [{"doc_num": ..., "issue": "unknown VatGroup 'SO' —
  not in mapping"}, ...]` for all 13 sales lines and the 1 purchase line in
  this window, and `box_1`/`box_5`/`box_6`/`box_7` would all collapse to 0.

### Evidence that (b)'s *core claim* is true, but its *mechanism* needs refining

(b) claims "SAP B1 will continue returning SO/SI regardless of any
AgentAssist-side rename … F5_BOX_MAPPING must stay keyed on SAP-native codes
for ingestion, and the SR/TX rename applies at the reporting/output layer …
possibly via a default SAP-B1 `tax_code_mappings` entry … rather than a
key-rename in `F5_BOX_MAPPING` itself."

- The **first half is correct and confirmed by live data**: SAP B1 will keep
  returning `SO`/`SI` (§1), and a default `tax_code_mappings` entry
  (`{"SO": "SR", "SI": "TX"}`, `source_system: "sap_b1"`) added to
  `config/clients/sbodemosg.yaml` is exactly the T2.19 mechanism, and it
  *would* work — `normalize_vat_group(raw_code, mappings)`
  (`sap_b1_server.py:308-326`) is **already unconditionally in the pipeline**
  ahead of every `F5_BOX_MAPPING.get()` call (lines 803, 826, 851, 883, and
  inside `_classify_line` at line 581) — it is not a no-op *by position*, only
  a no-op *by configuration* (because `sbodemosg.yaml` has no
  `tax_code_mappings` key, so `_tax_code_mappings = {}` and
  `normalize_vat_group` short-circuits on `if not mappings: return raw_code`
  at line 324-325). Confirmed live:
  `normalize_vat_group('SO', {})` → `'SO'` (verified by direct call in this
  recon).

- **But the second half — "F5_BOX_MAPPING must stay keyed on SAP-native
  codes … rather than a key-rename in F5_BOX_MAPPING itself" — does not
  survive contact with T2.20's Section 2d, which classifies `SO→SR`/`SI→TX`
  as bucket 2, "**Rename** … vocabulary edit + fixture rename" (not
  "additive alias").** If `F5_BOX_MAPPING` keeps `SO`/`SI` as its *only* keys
  for the sales/purchase-input routing entries, then:
  - `_STANDARD_VAT_GROUPS` (`config/loader.py:63-67`) — the validation
    authority for `tax_code_mappings` *targets* (line 300) — would also have
    to keep `SO`/`SI` (not add `SR`/`TX`), or every client's
    `tax_code_mappings: {... -> "SR"}` (the *existing* T2.19 Xero/MYOB
    mappings, per the inventory's 1.18-1.19) would fail validation with
    "'SR' is not a canonical AgentAssist VatGroup code."
  - That in turn means **nothing in the codebase ever produces or
    canonicalizes on the strings `SR`/`TX`** — `_vg_category`,
    `vg_inventory` keys, `_classify_line`'s `vat_group` field, report
    sections, and `sg-tax-code-mappings.md` would all continue to say `SO`/
    `SI`. There would be no "SR"/"TX" anywhere for the "reporting/output
    layer" to apply the rename *to* — (b) as literally written doesn't
    actually relocate the rename, it just doesn't do it.

### The refined model (b′)

`normalize_vat_group` + `tax_code_mappings` is a **general translation layer
that sits in front of `F5_BOX_MAPPING` for every client, SAP B1 included** —
it is not "a Xero/MYOB-only thing that happens to also run for SAP B1
clients as a no-op." T2.21's rename should use exactly this existing seam:

1. **`F5_BOX_MAPPING` (and `_STANDARD_VAT_GROUPS`, `_vg_category`,
   `_STANDARD_RATE_SALES`, the `_classify_line` literals `{"SO","SI"}`/
   `=="SI"`, etc. — the whole SSOT set from T2.20 §1.1-1.3/1.5/1.6/1.17) *does*
   get its `SO`/`SI` entries renamed to `SR`/`TX`** — this is the "vocabulary
   edit" T2.20 Section 2d/6 already scoped and costed. After this rename,
   `F5_BOX_MAPPING`'s keys represent AgentAssist's **canonical (Annex E)
   vocabulary**, not "the SAP-native vocabulary."
2. **`config/clients/sbodemosg.yaml` (and any other SAP-B1-source-system
   client config) gets a *new* `tax_code_mappings: {"SO": "SR", "SI": "TX"}`
   entry** — a config change, not a code change, and the *same construct*
   T2.19 built for Xero/MYOB, just now also needed for the SAP-B1 source
   system itself, because the canonical vocabulary has moved out from under
   SAP B1's native strings. `source_system` stays `"sap_b1"` — only
   `tax_code_mappings` is populated where it was previously `{}`.
3. With both (1) and (2) in place: raw `"SO"` → `normalize_vat_group` →
   `"SR"` → `F5_BOX_MAPPING["SR"]` (same `lt_box`/`tt_box`/`side` the old
   `"SO"` entry had) → box routing unchanged numerically, but every
   downstream consumer (`vg_inventory` keys, `_classify_line`'s `vat_group`
   field, anomaly messages, reports) now sees `"SR"`/`"TX"` — i.e. the
   Annex E rename *is* visible at the reporting/output layer, but it gets
   there via the translation step, not via `F5_BOX_MAPPING` continuing to
   speak `SO`/`SI`.

---

## 3. Config-validation question: does a F5_BOX_MAPPING-only key rename break
   sbodemosg.yaml validation today?

**No — but it breaks live *ingestion* silently, which is worse.**

- `config/loader.py` has **zero runtime dependency on `F5_BOX_MAPPING`**
  (confirmed by grep — `F5_BOX_MAPPING` appears in `loader.py` only inside a
  docstring at line 462, describing a *future* Tier-2 probe that is "NOT YET
  IMPLEMENTED"). `_STANDARD_VAT_GROUPS` (`loader.py:63-67`) is an
  independently-maintained 18-code frozenset (T2.20 inventory row 1.17) — the
  "Independence contract" in `loader.py`'s module docstring (lines 8-9)
  explicitly forbids `config/loader.py` ↔ `mcp-servers/` imports in either
  direction.
- `load_client_config("sbodemosg", ...)` would therefore **still succeed**
  even if `F5_BOX_MAPPING`'s keys were renamed to `SR`/`TX` with no other
  change — `sbodemosg.yaml` has `custom_vat_groups: {}` and no
  `tax_code_mappings` key, so steps 7 and 9 (lines 250-262, 292-318) have
  nothing to check against the renamed keys. **Config validation is not the
  guard rail here.**
- The actual failure mode is at **runtime, inside `sap_b1_server.py`**: with
  `_tax_code_mappings = {}` (unchanged, because `sbodemosg.yaml` wasn't
  touched), `normalize_vat_group("SO", {})` still returns `"SO"`
  (confirmed live, §1/§2), and `F5_BOX_MAPPING.get("SO")` would now return
  `None` (key renamed to `"SR"`) →
  - `calculate_f5_return`: every sales line in `sgd_sales` hits the
    `mapping is None` branch (lines 804-811) → `anomalies` fills with
    `"unknown VatGroup 'SO' — not in mapping"` for all 13 lines, and
    `box_1`/`box_6` both stay `0.0`. Same for the 1 purchase line → `box_5`/
    `box_7` stay `0.0`.
  - `validate_invoice_tax_codes`: `vatgroup_inventory["SO"]` would show
    `known_to_mapping: false`, `lt_box: null`, `tt_box: null`.
  - This is a **silent correctness regression** against live SBODEMOSG data
    (and against the 7 fixture files T2.20 §4 catalogued, which also encode
    raw `"SO"`/`"SI"` strings) — `ConfigError`/`ValueError` would never fire,
    but F5 box totals would silently zero out for the entire standard-rated
    sales/purchase-input population.

This is the single most important takeaway for sequencing T2.21's edits: **a
`F5_BOX_MAPPING`-keys-only rename is not safe to land on its own, even as an
intermediate commit** — it must land atomically with (or immediately
followed by, within the same test run) the `tax_code_mappings` addition to
every SAP-B1-source-system client config (`sbodemosg.yaml`, and per T2.20
§1.19 also `example.yaml`'s documentation/template).

---

## 4. Where T2.21's first failing test (SOP step 3) should target

Given (b′), the first failing test should **not** assert directly on
`F5_BOX_MAPPING`'s keys (that's an internal-structure assertion and the
hard-constraint list for *this* slice already forbids touching it). Instead,
per the SOP's "write a failing test against current behaviour, then make it
pass" pattern, the first test should assert on **`normalize_vat_group`'s
current no-op behaviour for the SAP-B1 default config** — i.e. encode the gap
this recon just found:

- **Target construct:** `normalize_vat_group(raw_code, mappings)` at
  `mcp-servers/custom/sap_b1_server.py:308-326`, exercised through
  `config/clients/sbodemosg.yaml`'s `tax_code_mappings` (currently absent →
  `{}`).
- **Current (pre-T2.21) behaviour to assert as the failing case:**
  `load_client_config("sbodemosg", check_connectivity=False).tax_code_mappings`
  is `{}`, so `normalize_vat_group("SO", {})` returns `"SO"` (not `"SR"`) and
  `normalize_vat_group("SI", {})` returns `"SI"` (not `"TX"`) — i.e. a test
  that says "for the SAP B1 demo client, raw SO/SI normalize to canonical
  SR/TX" will **fail today**, demonstrating the gap.
- **What will make it pass (future slices, not this one):** adding
  `tax_code_mappings: {"SO": "SR", "SI": "TX"}` to `sbodemosg.yaml`
  (config edit) **plus** renaming the corresponding entries in
  `F5_BOX_MAPPING`/`_STANDARD_VAT_GROUPS`/`_vg_category`/
  `_STANDARD_RATE_SALES`/`_classify_line` literals from `SO`/`SI` to `SR`/
  `TX` (the T2.20 §1 SSOT set) so that `F5_BOX_MAPPING.get("SR"/"TX")`
  resolves after normalization.
- Both halves are required together (per §3); the failing test from this
  slice should be written so that it **only** starts passing once both halves
  land — e.g. assert the full round trip (`normalize_vat_group` →
  `F5_BOX_MAPPING.get()` → non-`None` mapping with the same `lt_box`/`tt_box`/
  `side` the old `SO`/`SI` entries had), not just the `normalize_vat_group`
  output in isolation. This avoids a false-green state where
  `tax_code_mappings` is added first but `F5_BOX_MAPPING` hasn't been renamed
  yet (which would reproduce exactly the §3 "unknown VatGroup" regression,
  just shifted from `SO`→nothing to `SO`→`SR`→nothing).

---

## 5. Branch naming note

The task asked for a worktree + branch named
`t2.21a-annex-e-baseline-vocab-recon`. The `EnterWorktree` harness tool
auto-prefixes worktree branches with `worktree-`, producing
`worktree-t2.21a-annex-e-baseline-vocab-recon` (visible in
`git branch --show-current`). This differs from both the requested name and
from T2.20's branch (`t2.20-annex-e-vocab-audit`, created without the
`worktree-` prefix, presumably via plain `git checkout -b`). **Flagging per
the task's request** — if a non-prefixed name is required for consistency
with T2.20's convention, this branch should be renamed (or the work
re-based onto a plain `git branch`/`git worktree add` instead of
`EnterWorktree`) before it's folded into or precedes the T2.21 build branch.

---

## Housekeeping

- venv: `.venv-t2.21a/` (untracked, same convention as T2.20's
  `.venv-t2.20/`), created via `python -m venv` with `mcp`, `httpx`,
  `requests`, `python-dotenv`, `PyYAML` installed (sufficient for the direct
  import — no `pdfplumber`/`reportlab`/etc. needed for this slice).
- `.env` was copied from the repo root into this worktree (gitignored,
  required for `load_dotenv()` to find `CLIENT_ID`/`SAP_USERNAME`/
  `SAP_PASSWORD`).
- Scratch recon script `_t221a_recon.py` (repo root of this worktree) was
  used to run the live calls; it is not part of this deliverable and should
  be deleted before any PR.
- No edits to `F5_BOX_MAPPING`, `_vg_category`, `config/loader.py`,
  `sbodemosg.yaml`, any fixture, or `generate_invoices.py` — confirmed via
  `git status` (clean except for the new `exploration-notes/t2.21/` file and
  the untracked scratch script/venv/`.env`).
