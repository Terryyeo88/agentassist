# T2.7 Reg 26/27 Reasoning Pass — Acceptance Gate Decision

**Dated:** 2026-06-02  
**Author:** Terry Yeo  
**Status:** GATE FIXED — fully locked before measurement on the v2 fixture (recall > 95% hard floor; FP rate < 20% soft ceiling). Set 2026-06-02 by Terry Yeo.

> **Integrity note:** This document records the acceptance thresholds that were chosen
> *before* running the measurement harness on the promoted v2 fixture.  The numbers here
> may not be changed after results are seen.  Adjusting a threshold to make a borderline
> result pass is a post-hoc rationalisation and invalidates the gate.  If results are
> borderline, the correct action is to improve the KB slice or system prompt, re-run, and
> compare against this unchanged document.

---

## 1. Hard Floor — Recall > 95 %

**Threshold:** recall must be **strictly greater than 0.95** (i.e. > 95 %) over the full
promoted fixture.

**Definition:** recall = TP / (TP + FN), where a False Negative is a fixture line labelled
`expected_candidate: true` that the model did not surface.

**Justification:**

A False Negative is a missed disallowed expense.  If input tax was claimed on that line
and it is genuinely disallowed under Reg 26/27, the business has an under-declared GST
liability — real IRAS exposure, potentially with interest and penalties.  The reviewer
cannot catch what the tool does not surface.

The 95 % floor means the tool may miss at most 1 positive in every 20.  Given that the
human reviewer signs off the final filing, a small FN rate is acceptable; a large one
defeats the purpose of the pass.

This threshold is a **hard gate**.  A result of exactly 0.950 fails.  No exceptions.

---

## 2. Soft Ceiling — FP Rate < 20 %

**Threshold:** FP rate must be **strictly less than 0.20** (i.e. < 20 %) over the full
promoted fixture.

**Definition:** FP rate = FP / (FP + TN), where a False Positive is a fixture line labelled
`expected_candidate: false` that the model surfaced as a candidate.

### 2.1  Rationale for the soft ceiling

**Why "soft":** A False Positive costs the reviewer a few seconds — read the candidate,
confirm it is a claimable expense, dismiss it.  The reviewer does not re-file anything,
does not write a memo, and does not carry any IRAS risk.  A FP is therefore far less costly
than a FN, which justifies the asymmetry between the hard recall floor and the softer
precision ceiling.

**Why there is a ceiling at all:** If the FP rate is too high, reviewers begin ignoring
the candidates list — they assume most entries are noise and stop reading carefully.  At
that point recall is effectively degraded even if the model surfaces every genuine positive,
because a disregarded candidate is as bad as a missed one.  Alert fatigue is the real risk,
not precision aesthetics.

**What drives the choice of number:**

- At the current fixture composition (63 positives / 47 negatives), a 20 % FP rate means
  roughly 9–10 false alarms per run alongside the genuine candidates.
- A 15 % FP rate means roughly 7 false alarms.
- A 25 % FP rate means roughly 12 false alarms.

A reviewer who sees 12 extra rows per quarter alongside ~60 genuine candidates will, in
practice, spend about 2 minutes dismissing them.  That is probably still acceptable.  A
reviewer who sees 40 extra rows will start skimming, which is not.

**Decision:** 20 % was chosen as the ceiling — roughly 9–10 false alarms per run alongside
~60 genuine candidates, costing the reviewer about 2 minutes per quarter.  Tighten after
the first live quarter if alert fatigue emerges in practice.

---

## 3. Per-Category Considerations

The six Reg 26/27 categories differ substantially in how determinable they are from a terse
SAP description alone.  The overall recall and FP rates are the gate, but per-category
breakdowns must be reviewed alongside the aggregate numbers.

| Category | Determinability from description | Expected model behaviour | Acceptable miss pattern? |
|---|---|---|---|
| **club_subscriptions** | High — keywords: "MBR", "SUBSCRIPTION", "JOINING FEE", "TRANSFER FEE", club name | Should achieve near-100 % recall; FPs mostly from "club" in supplier name for non-membership invoices | Misses here are real IRAS risk; zero tolerance preferred |
| **other_disallowed** (betting/lottery/games) | High — Singapore Pools, "BET", "TOTO", "4D", "LOTTERY", "CASINO", "SWEEP" are distinctive | Should achieve near-100 % recall; very low FP risk | Same as club — description is unambiguous |
| **motor_car_s_plate** | Medium-high — "S-PLATE", "SBC/SBP-prefix plates", "COE", "SEASON PKG", car rental keywords are reliable; "VAN", "LORRY" should NOT fire | Main FP risk is commercial vehicles; main FN risk is non-standard descriptions omitting "S-plate" | FNs here are material; FPs from commercial-vehicle confusion are common model failure mode |
| **family_benefits** | Medium — explicit "SPOUSE", "CHILD", "FAMILY", "RELATIVE" keywords help; implicit family context may be missed | Recall likely moderate; description must mention family relationship | A miss is real IRAS risk; but terse lines with no family keyword (e.g. "PRIVATE DINING DOC 2037") are legitimately undeterminable |
| **entertainment** | Medium — "CLIENT", "GUEST", "PROSPECT", "ENTERTAINMENT" reliable; bare "DINNER" or "F&B" without external-party reference is ambiguous and should NOT fire | Main FP risk is internal-staff meals; main FN risk is entertainment invoices with no "CLIENT" keyword | FNs on external-entertainment lines without an explicit external-party indicator are expected; the KB instructs caution on bare F&B |
| **medical_expenses** | Low-medium — descriptions like "STAFF MEDICAL", "GP CONSULT", "HEALTH SCREEN" are common but WICA exceptions are knowable only from payroll/HR context, not the SAP line itself | The model is expected to surface these as candidates; the human reviewer decides WICA status | **Per the fixture-review-worksheet methodology call:** if the firm chooses "surface-all, human-decides" for ambiguous medical lines, then FNs on medical lines with no WICA indicator should be treated as expected misses, not gate failures. |

### 3.1  Categories where "surface-all, human-decides" is appropriate

For **medical_expenses** and, to a lesser extent, **motor_car_s_plate** (vehicle-type ambiguous),
the correct system behaviour is to surface the candidate and let the reviewer confirm or dismiss
using context the SAP line does not contain (WICA letters, vehicle registration).  For these
categories, a high per-category recall (≥ 90 %) is more important than per-category precision.
No separate precision sub-gate is set for these categories.

### 3.2  Categories where per-category recall matters independently

For **club_subscriptions** and **other_disallowed**, the descriptions are nearly always
conclusive.  A low per-category recall in either of these two categories — even if the aggregate
recall clears 95 % — is a signal that the KB or system prompt is missing something.  Flag this
for investigation even if the overall gate passes.

---

## 4. What Happens if the Gate Fails

| Outcome | Action |
|---|---|
| Recall ≤ 0.95 | Do NOT enable `show_ai_candidates`.  Diagnose which categories were missed; improve KB slice or system prompt.  Re-run measurement.  Do not loosen the floor. |
| FP rate ≥ ceiling | Investigate which negative categories drove FPs (commercial vehicles? internal meals? generic insurance?).  Tighten the EXCEPTIONS discipline in the KB slice.  Re-run.  Do not raise the ceiling. |
| Both pass | Set `show_ai_candidates: true` in the client YAML for the next live quarter.  Record the measured recall and FP rate in a "measurement-record.md" alongside this file. |

---

## 5. Fixture Version This Gate Applies To

This gate applies to **`tests/fixtures/reg2627-labelled-lines.json`** — the promoted
(human-reviewed) fixture, not the DRAFT.  Running measurement against the DRAFT file and
claiming a gate pass is invalid.  The DRAFT must be fully reviewed and renamed per the
fixture-review-worksheet sign-off checklist before this gate is evaluated.

**Fixture composition at time of gate-writing (from DRAFT):**
- 110 lines total
- 63 proposed positives (10–11 per category across all six categories)
- 47 proposed hard negatives (including genuine WICA exceptions, commercial vehicles,
  internal meals, business insurance)

The promoted fixture composition may differ after Terry's accounting review; the gate
thresholds do not depend on the exact composition.

---

## 6. PROVISIONAL Measurement Record — 2026-06-03

> **INTEGRITY NOTE: This section records a PROVISIONAL, UNVALIDATED measurement run against
> the Opus-labelled DRAFT fixture. It is informational only. It is NOT a gate result.
> Clearing the gate against provisional labels is NOT validation. The gate defined in §§1–3
> above applies to the PROMOTED fixture after independent human GST-specialist review.**

**Date:** 2026-06-03
**Fixture:** `tests/fixtures/reg2627-labelled-lines.DRAFT.json`
**Fixture labels:** Opus-4-8 two-pass labelling pass (provisional; LLM-derived; unvalidated)
**Fixture composition:** 110 lines; 55 positive (determinable), 55 negative; 98 determinable, 12 indeterminate
**Measurement run:** `exploration-notes/t2.7-measurement/measurement-20260603-091632.json`

### Results

| Model | Recall | FP rate | Gate (against provisional labels) | Cost/run |
|---|---|---|---|---|
| claude-haiku-4-5-20251001 | 1.000 | **0.065** | FAIL | $0.09 |
| claude-sonnet-4-6 | 1.000 | **0.000** | PASS | $0.34 |
| claude-opus-4-8 | 1.000 | **0.022** | PASS | $1.66 |

All three models achieved **perfect recall (1.000)** on the 52 determinable positives.
The spread is entirely in FP rate.

### Per-model detail

**Haiku — FAIL (fp_rate=0.065)**
3 false positives: WICA MED EXAM MAND (medical_expenses, determinable/claimable), WICA INS PREM
(medical_insurance, determinable/claimable), and one n/a line. Haiku does not reliably apply the
WICA carve-out when "WICA" or "MANDATORY" appears in the description. All other categories clean.

**Sonnet — provisional PASS (fp_rate=0.000)**
Zero false positives across all categories. Correctly skips WICA lines. Surfaces 4/6 indeterminate
medical lines (67%). Provisional lead; Sonnet is cross-model and therefore the most independent
result in this run.

**Opus — provisional PASS (fp_rate=0.022)**
One false positive in entertainment (likely YACHT CHARTER CLIENT or CORP BOX SPORTS EVT — non-food
item where both models see ambiguity). Surfaces 2/6 indeterminate medical lines (33%).

### Caveats — why this is NOT a gate result

1. **Circularity.** Opus labels vs Opus surface-pass: the recall=1.000 and low fp_rate for Opus
   partly reflect self-consistency rather than accuracy against IRAS ground truth. The Opus row
   is the least independent data point.

2. **Unvalidated labels.** The fixture's `validation_status` is `"unvalidated"`. Labels were
   produced by an Opus two-pass run on 2026-06-03 and have not been reviewed by a human GST
   specialist against IRAS source documents.

3. **Specialist queue outstanding.** 12 indeterminate lines require specialist adjudication before
   the fixture can be promoted. See `specialist-queue-20260603.xlsx`.

4. **Entertainment labels pending.** All 11 entertainment lines in the fixture are `expected_candidate=False`
   (claimable, per the §6.1.3 correction). The original DRAFT had them as positives. This wholesale
   change has not been independently verified.

5. **Fixture test floors adjusted post-hoc.** The `_MIN_POSITIVES_PER_CATEGORY` floor was lowered
   from 10→8 to match the Opus relabelling; test coverage is not independent of the labels.

### Next actions to achieve a real gate result

1. Specialist adjudication of the 12-line queue (`specialist-queue-20260603.xlsx`) → reconcile
   into the fixture.
2. Stratified spot-check of a sample of the 98 determinable lines against IRAS source documents.
3. Independent review of the 11 entertainment relabellings (§6.1.3 basis confirmed).
4. Promote the fixture: rename to `reg2627-labelled-lines.json`, update `_meta.ground_truth_set_by`.
5. Re-run measurement against the promoted fixture.  Only then does a PASS constitute a gate result.

Until step 5 is complete, `show_ai_candidates` must remain `False` and `validation_status` must
remain `"unvalidated"`.
