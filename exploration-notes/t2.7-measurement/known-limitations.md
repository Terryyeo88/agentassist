# T2.7 Reg 26/27 Reasoning Pass — Known Limitations

**Dated:** 2026-06-03  
**Author:** Terry Yeo  
**Status:** Living document — update when a limitation is resolved or a new one is identified.

This document records the known limitations of the T2.7 Reg 26/27 reasoning pass and its
supporting fixture.  It is an honest accounting of what the system cannot do and what the
ground-truth labels do not represent.  Read this before interpreting any recall / FP-rate
figure from the measurement harness.

---

## 1. Generic-SME Assumption

**What the assumption is.**  All fixture labels and all reasoning-pass inferences assume the
client is a **generic general-trading or professional-services SME** that buys goods and services
as **operating overhead or staff expenditure** — not as trading stock or direct inputs to a
specialist commercial activity.

**Why it matters.**  Reg 26/27 targets overhead expenditure.  When a business's primary trade
is in a category that appears in the §6.1.6 disallowance list, the disallowance may not apply
because those purchases are **trading inputs**, not overhead.

**Affected categories.** Business-type dependence is sharpest for:
- **Motor car / transport costs (Category 5):** A car dealer's vehicles and running costs are
  trading stock or demonstrator inputs — claimable.  The same invoice from a law firm is
  disallowed.  The label in this fixture assumes law-firm context.
- **Medical expenses and insurance (Categories 2 & 3):** A medical clinic's supplies, staff
  medical bills, and insurance premiums may be direct inputs to the service it sells — claimable.
  The label assumes a non-clinic overhead context.

**Scope of the limitation.** Recall and FP-rate figures measured on this fixture are valid
**only for generic-SME data**.  Running the harness against a car dealer's or clinic's ledger
would produce artificially high FP rates: the model would surface vehicles and medical bills
as candidates even though they are claimable for those clients.

**Resolution path.** See roadmap item T2.7.x (§6 of this document and the roadmap file):
a new `ClientConfig` field supplies the client's business nature to the reasoning prompt so
context-claimable lines are not surfaced.

**Reference.** `knowledge-base/slices/business-context.md` — full statement, injected into
the labelling-pass prompt.

---

## 2. Entertainment — Open Item (Verified §6.1.6 Basis)

**Current position (corrected 2026-06-03).** Entertainment of external parties is **NOT** a
Reg 26/27 disallowed category.  §6.1.6 of the IRAS GST General Guide enumerates exactly six
disallowed categories (items 1–6: club subscriptions, staff medical expenses, staff medical &
accident insurance, family benefits, motor car costs, betting/sweepstakes/games of chance).
Entertainment does not appear.

**§6.1.3 basis.** Food and drink entertainment expenses — whether for internal staff or external
parties — are **claimable** with the appropriate documentation (simplified tax invoice for
food/drink from 1 Feb 2014; full tax invoice where non-food items are included).
See `knowledge-base/slices/reg2627.md` "Entertainment Guidance" section.

**Fixture implication.** The DRAFT fixture contains 11 lines labelled `expected_category:
entertainment`.  These labels were set before the §6.1.6 correction and may need to be
revised during the labelling-pass review (L).  Do NOT promote the DRAFT fixture until the
entertainment labels have been reviewed against the corrected KB.  The labelling pass
should treat clean food/drink entertainment lines as negatives (not Reg 26/27 candidates)
unless bundled with a genuinely disallowed category (e.g. a club membership, a family benefit).

**Open question.** Whether any of the 11 entertainment fixture lines should be relabelled as
negatives or reassigned to another category (e.g. family_benefits, club_subscriptions) is a
decision for the labelling-pass review.  No label changes have been made in this commit.

---

## 3. Medical Split (§6.1.6 Items 2 and 3)

**Two separate categories in §6.1.6:**
- **Item 2 — Staff medical expenses:** treatment, consultations, dental, health screenings,
  TCM, hospitalisation.  Carve-outs: WICA/collective-agreement mandatory; post-Oct-2021
  work-environment health requirements under Singapore written law; COVID-19 treatment per
  government advisory.
- **Item 3 — Staff medical and accident insurance premiums:** group medical insurance,
  personal accident insurance.  Carve-out: insurance mandatory under WICA or collective
  agreement.

**Fixture consolidation.**  Both categories are currently labelled `expected_category:
medical_expenses` in the fixture.  This is a simplification: the fixture does not distinguish
between a treatment invoice and an insurance premium invoice.  The model output similarly uses
`medical_expenses` as a single bucket.

**Limitation.**  Per-category recall and FP-rate figures for `medical_expenses` aggregate two
legally distinct categories.  A model could achieve high recall on insurance premiums but low
recall on treatment costs (or vice versa) and the aggregate figure would not reveal this.

**Mitigation.**  During the labelling-pass review, annotate each `medical_expenses` line with
whether it is a treatment/consultation cost (§6.1.6 item 2) or an insurance premium (§6.1.6
item 3).  A post-hoc sub-category breakdown can then be computed from the `iras_basis` field.

---

## 4. Determinable vs Indeterminate — Definition and Scoring

**Definition.**
- **Determinable:** The correct Reg 26/27 treatment (disallowed or claimable) can be
  established from the SAP line description alone, by reference to IRAS source documents.
  Example: `GOLF MBR RENEWAL` — clearly a club subscription (§6.1.6 item 1), no further
  context required.
- **Indeterminate:** The correct treatment cannot be established from the line description
  alone.  A human must inspect the underlying invoice, payroll records, or vehicle
  registration to decide.  Example: `STAFF MEDICAL` — might be WICA-mandatory (claimable) or
  voluntary (disallowed); the line description does not say.

**Scoring rule.**  The measurement harness (`reasoning/measurement.py`) scores the two groups
differently:
- **Determinable lines:** scored on recall and FP rate using `expected_candidate` as truth.
  These are the primary gate metrics.
- **Indeterminate lines:** scored on `surface_rate` only (what fraction the model surfaced).
  They are excluded from recall and FP-rate computation.  `needs_human_review: true` is an
  initial guide for which lines are likely indeterminate; `determinability` must be explicitly
  labelled per line during the labelling-pass review.

**Current state.**  All 110 DRAFT lines provisionally carry `determinability: "determinable"`.
The labelling-pass review must update each `needs_human_review: true` line to either
`"determinable"` (if the correct answer is resolvable from IRAS alone) or `"indeterminate"`
(if it requires external context).  Until this is done, gate metrics are computed as if all
lines are determinable — a conservative assumption for recall, a lenient one for FP rate.

---

## 5. Provisional Ground Truth — Validation Status "Unvalidated"

**Current state of labels.**  All 110 DRAFT lines carry `proposed: true`.  Labels were
machine-proposed by Claude Code on 2026-06-02 against the IRAS KB slice.  They have **not**
been reviewed by a human accountant or GST specialist against the IRAS source documents.

**Validation status.**  The fixture is `validation_status: "unvalidated"` and will remain so
until an **independent GST-specialist review** of the contested subset is complete.  The
contested subset includes:

1. All `needs_human_review: true` lines (approx. 20 lines where WICA status, vehicle type,
   or external-party presence is ambiguous from the description alone).
2. All `expected_category: entertainment` lines (11 lines) — labels pre-date the §6.1.6
   correction and must be re-evaluated.
3. Any lines where the proposed label is inconsistent with the corrected KB slice
   (`knowledge-base/slices/reg2627.md`, corrected 2026-06-03).

**Consequence.**  Any recall or FP-rate figure computed from the DRAFT fixture is
**informational only**.  It may not be cited as a gate result, a product claim, or evidence
of model quality.  The gate applies to the **promoted** fixture (`reg2627-labelled-lines.json`)
after full human review per `fixture-review-worksheet.md`.

**Review path.**  Terry + accounting reviewer work through
`exploration-notes/t2.7-measurement/fixture-review-worksheet.md` and
`Reg26-27_GST_Review_Worksheet.xlsx`.  The worksheet now includes a specialist-review
section for the contested / indeterminate subset.  When every row is reviewed and signed off,
the file is renamed and `_meta.ground_truth_set_by` is updated to record the reviewer's name
and date.

---

## 6. Production Roadmap Item — Client Business-Nature Field

**Problem statement.**  As noted in §1, the reasoning pass currently has no way to know
whether a client is a generic SME or a specialist business (car dealer, clinic, etc.).
A car dealer's vehicle invoices will be surfaced as motor-car candidates even though they
are claimable trading stock.

**Roadmap item (T2.7.x).**  Add a `business_nature` field to `ClientConfig` (per-client
YAML).  The reasoning pass reads this field and injects it into the reg2627 system prompt
at run time, so the model can suppress context-claimable lines.  Until this field exists,
the pass must not be enabled for clients whose primary trade overlaps with any §6.1.6
disallowed category.

**See also:** `knowledge-base/AgentAssist-Technical-Roadmap-v3.md` T2.7.x section.

---

---

## 7. Measurement Run Findings (2026-06-03, PROVISIONAL)

The following limitations were discovered during the first live measurement run against
the Opus-labelled DRAFT fixture.  They do not change the `validation_status` (still
`"unvalidated"`) but must be resolved before any gate claim.

### 7a. Per-batch error isolation not implemented in `run_reg2627_pass`

**Finding.**  `run_reg2627_pass` processes SI lines in batches (batch_size=20).  If any
single batch's LLM call fails or returns invalid JSON, the entire model run is immediately
returned as `status="errored"` and the token counts for all earlier batches are discarded.
There is no partial-success path: a transient API failure on batch 3 of 6 voids the whole
run.

**Impact.**  During the measurement run with the 110-line DRAFT fixture, Claude Sonnet 4.6
initially failed on batch 1 when batch_size=30 caused a response truncation (one failed batch
= full FAIL).  After reducing to batch_size=20 all three models succeeded, but the latent
gap remains: a transient 503 or rate-limit on any batch causes the run to produce no result
rather than a partial one.

**Open TODO.**  Add per-batch retry (backoff on 503/timeout) and consider accumulating
successful batches so that a failure on the final batch doesn't discard prior results.
This is a production-robustness gap; see Gate B in the roadmap.

### 7b. Fixture test floors lowered to match the Opus-relabelled fixture

**Finding.**  After the Opus labelling pass, two fixture structure tests had to be relaxed
to keep the suite green:

1. `_MIN_POSITIVES_PER_CATEGORY` lowered from 10 → 8 in `test_fixture_draft_structure.py`.
   Reason: Opus reclassified 2035 SPOUSE CLUB MBR from `family_benefits` → `club_subscriptions`
   and 2036 FAMILY MED STAFF from `family_benefits` → `medical_expenses`, leaving only 8
   `family_benefits` positives.  Both reclassifications are arguably more precise, but the
   test floor now describes the Opus-labelled fixture rather than an independent minimum.

2. `entertainment` removed from `_REQUIRED_CATEGORIES`.  Reason: after the §6.1.3 correction,
   all entertainment lines are `expected_candidate=False`; the test for "all required categories
   must have positives" correctly stopped requiring entertainment among positives.

**Consequence.**  The fixture structural tests no longer act as an independent correctness
spec — they validate the shape of whatever labels the labelling pass produced.  When the
fixture is promoted after human review, these tests should be re-evaluated against the
reviewed labels rather than simply assumed to be correct by construction.

### 7c. Indeterminate surface-rate gap — entertainment and n/a ambiguous lines not surfaced

**Finding.**  On the 2026-06-03 measurement run, the indeterminate surface-rate tables
showed:

| Category | Haiku | Sonnet | Opus |
|---|---|---|---|
| entertainment (indet=2) | 0/2 = 0.000 | 0/2 = 0.000 | 0/2 = 0.000 |
| n/a (indet=3) | 0/3 = 0.000 | 0/3 = 0.000 | 1/3 = 0.333 |

All three models surface **zero** of the 2 indeterminate entertainment lines (CORP BOX
SPORTS EVT and CLIENT CRUISE ENTMT) and effectively zero of the 3 indeterminate n/a lines
(VAN CARPARK SEASON, SUNDRY, MISC).

**Consequence.**  A reviewer using any of the three models would not be prompted to look at
these 5 lines, despite them being genuinely ambiguous.  The "surface-all, human-decides"
policy is not being applied for these categories.  This is expected for n/a lines (the model
has no §6.1.6 basis to flag them), but the two entertainment lines in the indeterminate bucket
(non-food, contested) arguably warrant a prompt.

**Open question.**  Whether to add a dedicated "flag ambiguous non-food entertainment" pass,
or to accept that these lines are surfaced only through the specialist queue process, is a
design decision for Terry.

---

## 8. Summary Table

| Limitation | Severity | Resolution path |
|---|---|---|
| Generic-SME assumption | High for specialist clients | T2.7.x `business_nature` ClientConfig field |
| Entertainment open item | High — labels pre-date §6.1.6 correction | Labelling-pass review (L); relabel 11 lines |
| Medical not split (items 2 vs 3) | Low — aggregate metric hides sub-category divergence | Annotate during labelling-pass review |
| Determinability all provisional | Medium — gate metrics computed as all-determinable | Labelling-pass review; update `determinability` field per line |
| Labels unvalidated (LLM-proposed) | Critical for gate claims | Independent GST-specialist review; promote fixture only after full sign-off |
| Production business-nature injection | High for non-SME clients | Roadmap T2.7.x |
| Per-batch error isolation absent | Medium — transient failure voids whole run | Add retry + partial-accumulation to run_reg2627_pass (Gate B item) |
| Fixture tests now describe Opus labels | Low — tests not independent spec | Re-evaluate floors after human review and fixture promotion |
| Indeterminate entertainment/n/a not surfaced | Low — 5 ambiguous lines invisible to reviewer | Design decision: dedicated pass or accept specialist-queue-only coverage |
