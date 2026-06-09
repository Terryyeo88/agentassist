# Labelling Protocol — Reg 26/27 Validation Fixtures v1

**Task:** T2.13 — Independent Specialist Labelling  
**Fixtures:** `tests/fixtures/reg2627-representative-v1.json` and `tests/fixtures/reg2627-adversarial-v1.json`  
**Schema:** `tests/fixtures/SCHEMA-reg2627-v1.md`

---

## What you will receive — IMPORTANT

**You will label the SPECIALIST-FACING COPIES, not the source fixture files.**

Before each labelling session, the project owner runs:

```
python tests/fixtures/export_specialist_copy.py
```

This produces two stripped files:

- `tests/fixtures/reg2627-representative-v1-specialist.json`
- `tests/fixtures/reg2627-adversarial-v1-specialist.json`

These are the files you label. **Do NOT request or accept the source fixture files
(`*-v1.json`).** The source files contain a `resolution_hint` field that encodes
the case-writer's intended resolution direction for exception-category lines. If
you see this field in any fixture handed to you, stop and report it — the export
script was not run correctly.

**Why this matters:** `resolution_hint` is build metadata only, used internally
to enforce test-suite floor requirements. It must never be visible to the labeller.
Your label is the ground truth. If you could see the case-writer's intended
direction before labelling, your label would recreate the circular validation
that this fixture exists to avoid.

The specialist-facing copies are identical to the source fixtures in every
field you need to label (`line_description`, `amount`, `category`, `stratum`,
`business_context`). All four label fields (`expected_candidate`, `determinability`,
`label_rationale`, `label_confidence`) are null in the copies you receive — fill
them in according to the instructions below.

---

## Business context assumption

**Label each line GIVEN that the filing entity is a generic trading/services SME.**

The filing entity is assumed to be a company in general trading or professional
services that purchases goods and services as overhead or staff expenditure.
These labels are NOT valid for businesses whose primary trade overlaps a Reg 26/27
disallowed category:

- A **car dealer** — vehicle purchases and running costs are trading stock /
  demonstrator inputs (claimable as trading inputs, not subject to the motor-car
  disallowance).
- A **medical clinic** — medical supplies and staff medical costs are direct
  service inputs (claimable, not staff medical expenses in the §6.1.6 sense).
- An **insurance broker** — staff medical and accident premiums may be a product
  input; seek specialist advice before applying these labels.

If you have any doubt about whether the generic-SME assumption applies to a
particular line, flag it with `label_confidence: "low"` and note the concern in
`label_rationale`.

---

## How to fill in the four label fields

For each line in the fixture, fill in:

| Field | Instruction |
|---|---|
| `expected_candidate` | `true` if this line represents a Reg 26/27 disallowed expense (should be surfaced to the reviewer). `false` if this is a claimable expense (should NOT be surfaced). |
| `determinability` | `"determinable"` if the correct answer can be established from the line description alone. `"indeterminate"` if it cannot — see the Abstention Rule below. |
| `label_rationale` | Quote the governing IRAS rule with full citation, then state the reasoning. One to three sentences. |
| `label_confidence` | `"high"` (no reasonable doubt), `"medium"` (minor uncertainty), or `"low"` (genuine ambiguity; may require invoice/HR context). |

---

## ABSTENTION RULE — READ THIS BEFORE LABELLING

> **When the line description alone cannot resolve the exception, the correct
> label is `determinability="indeterminate"` and `expected_candidate` should
> reflect what a system SHOULD do when it cannot determine the answer — which
> is to surface with low confidence or abstain, NOT to issue a positive verdict.**

Lines with `stratum="genuinely_indeterminate"` in the fixture are placed there
specifically because the description is silent on the fact needed to resolve the
exception (e.g. whether a medical expense is WICA-mandatory; whether a vehicle
is a motor car or a commercial goods vehicle). For these lines:

- Set `determinability="indeterminate"`.
- Set `expected_candidate` to reflect the **correct system behaviour**: if a
  system should surface the line as a low-confidence candidate (i.e. "flag for
  reviewer, cannot determine from description"), set `expected_candidate=true`
  with `label_confidence="low"`. If a system should NOT surface it at all
  because the description gives no signal of a blocked category, discuss with
  Terry before labelling.
- Do NOT set `expected_candidate=true` with `label_confidence="high"` for a
  genuinely_indeterminate line. That would claim more certainty than the
  description supports.

**This rule is the most important instruction in this protocol. Violations
undermine the fixture's ability to score correct abstention behaviour.**

---

## Category-by-category labelling guidance

### Category 1 — Club Subscriptions / Membership / Transfer Fees

**Governing rule:** IRAS GST General Guide for Businesses §6.1.6 item 1  
**Citation:** "Club subscription and membership fees (including transfer fees)
charged by sporting and recreational clubs" (§6.1.6 item 1, General Guide);
"Club subscription fees (including transfer fees) charged by sports and
recreation clubs" (§5.13(n), How Do I Prepare My GST Return)

**No exceptions.** If the description identifies a subscription, membership fee,
joining fee, or transfer fee charged by a sporting or recreational club, the input
tax is disallowed. There is no WICA-style carve-out for this category.

**Boundary:** The disallowance covers "sporting and recreational clubs". A
business networking organisation that is neither sporting nor recreational is
likely outside the scope of §6.1.6 item 1. If the club type cannot be determined
from the description, set `determinability="indeterminate"` and discuss with Terry.

**Do NOT confuse** a club membership fee with a purchase of goods or services
from a supplier that happens to be named "Club" (e.g. catering from a function
venue named "ABC Club"). Only the subscription / membership fee itself is
disallowed, not other purchases from the club.

---

### Category 2 — Staff Medical Expenses

**Governing rule:** IRAS GST General Guide for Businesses §6.1.6 item 2  
**Citation:** "Medical expenses incurred by your staff unless — a) they are
mandatory under the Work Injury Compensation Act or under any collective
agreement within the meaning of the Industrial Relations Act; b) the medical
treatment … is provided in connection with any health risk or requirement arising
on account of the nature of the work … and i. the medical expenses are incurred
pursuant to any written law of Singapore concerning the medical treatment …; or
ii. the medical treatment is related to COVID-19 and the staff undergoes such
medical treatment pursuant to any written advisory … issued by, or posted on the
website of, the Government or a public authority." (§6.1.6 item 2, General Guide)

**Disallowed by default** for a generic SME: GP consultations, dental, specialist
consultations, health screenings, hospitalisation, TCM, and similar staff medical
treatments.

**Claimable (exception applies)** when the description explicitly states:
- The expense is mandatory under WICA (Work Injury Compensation Act) — e.g.
  "WICA MAND MED EXAM" or "WSH REGS".
- The expense is a work-environment health requirement under a written Singapore
  law (post-Oct 2021) — e.g. "NOISE EXPOSURE HEARING TEST (WSH ACT)" if the
  statutory requirement can be inferred from the description alone.
- The expense is COVID-19 treatment under a government advisory (post-Oct 2021).

**Genuinely indeterminate** when the description does not mention WICA, mandatory
status, or a specific work-environment law — e.g. "GP CONSULT STAFF",
"OCCUPATIONAL HEALTH SCREEN", "WORK INJURY TREATMENT". These lines cannot be
resolved without the underlying payroll/HR context or the actual invoice.

---

### Category 3 — Staff Medical and Accident Insurance Premiums

**Governing rule:** IRAS GST General Guide for Businesses §6.1.6 item 3  
**Citation:** "Medical and accident insurance premiums incurred for your staff
unless the insurance or payment of compensation is mandatory under the Work
Injury Compensation Act or under any collective agreement within the meaning
of the Industrial Relations Act." (§6.1.6 item 3, General Guide; §5.13(n),
GST Return Guide)

**Disallowed by default** for a generic SME: group medical insurance, personal
accident insurance, hospitalisation insurance for staff — unless mandatory.

**Claimable (exception applies)** when the description explicitly states:
- The insurance is mandatory under WICA — e.g. "WICA INS PREM MANDATORY",
  "WICA INS PREM STAFF".
- The insurance is under a collective agreement — e.g. "INS PREM COLL AGREE".

**Genuinely indeterminate** when the description names only the type of insurance
(e.g. "STAFF INS PREM", "GRP MED INS PREM", "PA INS STAFF") with no indication
of WICA or collective-agreement status. For foreign worker insurance, the MOM
work permit requirement is a separate statutory regime from WICA; if in doubt,
set `determinability="indeterminate"` and flag for Terry.

**This category covers insurance premiums only.** Actual medical treatment costs
are Category 2 (§6.1.6 item 2).

---

### Category 4 — Benefits for Family Members / Relatives of Staff

**Governing rule:** IRAS GST General Guide for Businesses §6.1.6 item 4  
**Citation:** "Benefits provided to the family members or relatives of your
staff." (§6.1.6 item 4, General Guide; §5.13(n), GST Return Guide)

**No exceptions.** Any goods or services provided for the benefit of family
members or relatives of staff are disallowed, regardless of the nature of the
expenditure.

**Key keywords:** SPOUSE, CHILD, FAMILY, RELATIVE, DIR SPOUSE, STAFF FAMILY.

**Genuinely indeterminate** when "family" appears in a description that could
be interpreted as a type of service (e.g. "MEDICAL CLAIM FAMILY" could mean
"family medicine clinic") or where the family benefit is implicit but not stated.
In such cases, set `determinability="indeterminate"`.

---

### Category 5 — Motor Car Costs and Running Expenses

**Governing rule:** IRAS GST General Guide for Businesses §6.1.6 item 5;
Regulation 25(1) GST (General) Regulations  
**Citation:** "Costs and running expenses incurred on motor cars that are either
registered under the business' or individual's name, or hired for business or
private use, except where the car is excluded from the definition of a 'motor
car' in Regulation 25(1) of the GST (General) Regulations." (§6.1.6 item 5,
General Guide)

**Disallowed** for motor cars registered under the business/individual name
(S-plate / private plate), company cars whose COE was renewed or extended on or
after 1 Apr 1998, and rental cars hired for use on or after 1 Jul 1999.

**Claimable (Reg 25(1) exception applies)** when the description identifies a
commercial vehicle that falls outside the "motor car" definition — e.g.:
- "LORRY" or "GOODS VEH" — goods vehicles are excluded from Reg 25(1).
- "COMM VAN" with an explicit "REG 25(1) EXCL" indicator.
- "MOTORCYCLE" — motorcycles are excluded from Reg 25(1).
- "BUS" or "BUS CHARTER" — buses are excluded from Reg 25(1).

**Genuinely indeterminate** when the description does not identify the vehicle
type clearly — e.g. "VAN SERVICING" (could be commercial or private-use MPV),
"VEHICLE PETROL" (no vehicle type), "FLEET VEHICLE PARK" (fleet unknown type),
"DELIVERY VAN INS" (delivery van implies commercial but the Reg 25(1) exclusion
must be applied by the reviewer, not inferred from "delivery" alone).

**Do NOT flag** lorry, motorcycle, bus, or forklift lines as motor-car candidates
solely because the description mentions a vehicle.

---

### Category 6 — Betting, Sweepstakes, Lotteries, Fruit Machines, Games of Chance

**Governing rule:** IRAS GST General Guide for Businesses §6.1.6 item 6  
**Citation:** "Any transaction involving betting, sweepstakes, lotteries, fruit
machines or games of chance." (§6.1.6 item 6, General Guide; §5.13(n), GST
Return Guide)

**No exceptions.** Input tax on any such transaction is disallowed.

**Unambiguous indicators:** TOTO, 4D, LOTTERY, CASINO, SLOT MACHINE, FRUIT MACH,
SWEEPSTAKE, HORSE RACING BET, SCRATCH CARD, LUCKY DRAW (where it is clearly a
lottery/game of chance rather than an internal HR event).

**Genuinely indeterminate** for descriptions that could represent either a
lottery/game of chance or an ordinary business event — e.g. "CORPORATE LUCKY
DRAW" (internal HR event vs public lottery), "PRIZE DRAW ENTRY FEE" (competition
vs lottery), "GAMING PLATFORM SUBS" (video-game subscription vs betting platform).

---

### Entertainment — §6.1.3 Negative Control

**Governing rule:** IRAS GST General Guide for Businesses §6.1.3(b)(ii)  
**Citation:** "a simplified tax invoice for … (ii) entertainment expenses incurred
on food and drinks, regardless of the purchase value … This concession applies
from 1 Feb 2014 and only on entertainment expenses on food and drinks." (§6.1.3,
General Guide)

**Entertainment is NOT a Reg 26/27 disallowed category.** Lines with
`category="entertainment"` in these fixtures are negative controls — the system
must NOT surface them as Reg 26/27 candidates.

For all entertainment lines: set `expected_candidate=false` and
`determinability="determinable"` unless the description contains a Reg 26/27
trigger that is independent of the entertainment nature of the purchase (e.g.
a line that combines a club membership fee with a catering charge).

---

## Sign-off block

| Field | Value |
|---|---|
| Labeller name | |
| Professional accreditation | |
| Firm | |
| Date of labelling | |
| Fixture version reviewed | reg2627-representative-v1.json, reg2627-adversarial-v1.json |
| IRAS sources consulted | IRAS GST General Guide for Businesses (etaxguide_gst_gst-general-guide-for-businesses(1).pdf); IRAS How Do I Prepare My GST Return §5.13(n) |
| Reviewer (Terry Yeo) sign-off | |
| Date of reviewer sign-off | |

**After sign-off:** Update `_meta.ground_truth_set_by` to the labeller name and
`_meta.validation_status` to `"validated"` in both fixture files.
Rename files to `reg2627-representative-v1-validated.json` and
`reg2627-adversarial-v1-validated.json` per the promotion checklist.
