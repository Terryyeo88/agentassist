# Reg 26/27 Validation Fixture Schema — v1

<!-- schema_version: reg2627-v1 -->

## Business context assumption

All lines in both fixture files are labelled GIVEN that the filing entity is a
**generic trading/services SME** — not a car dealer, medical clinic, insurance
broker, or any other business whose primary trade overlaps a Reg 26/27 disallowed
category. This assumption must be stated explicitly at the top of every labelling
session and confirmed by the specialist before sign-off.

---

## Dataset-level `_meta` object

| Field | Type | Allowed values / notes |
|---|---|---|
| schema_version | string | `"reg2627-v1"` |
| business_context | string | `"generic trading/services SME"` |
| set_name | string | `"representative"` or `"adversarial_hard"` |
| validation_status | string | `"unvalidated"` — must not change until specialist sign-off |
| ground_truth_set_by | null | `null` until specialist fills this in |
| created_by | string | build-script identifier |
| created_at | ISO-8601 date | |

---

## Per-line fields

| Field | Type | Constraints |
|---|---|---|
| line_id | string | Unique; `"R"` prefix for representative set, `"A"` for adversarial |
| doc_num | integer | Document reference number (3001+ representative; 4001+ adversarial) |
| line_description | string | SAP-style, all-caps, ≤ 50 chars |
| amount | number | Line amount before GST (SGD) |
| gst_amount | number | GST amount (amount × 0.09) |
| vat_group | string | `"SI"` (Standard-rated Input) |
| business_context | string | Inherited from `_meta`; must be non-empty on every line |
| stratum | string | See stratum table below |
| category | string | See category table below |
| resolution_hint | string\|null | Build-time annotation only — see note below |

### `resolution_hint` — design annotation, NOT a label field

`resolution_hint` is set deterministically at build time for `hard_determinable`
lines belonging to the three exception categories (`staff_medical`,
`staff_medical_accident_insurance`, `motor_car`). It records the expected
resolution direction:

- `"claimable"` — the description alone is sufficient to establish that an
  exception applies, so the correct verdict is NOT a candidate.
- `"blocked"` — the description alone is sufficient to establish that the
  exception does NOT apply, so the correct verdict IS a candidate.
- `null` — all other lines (non-hard_determinable, or categories with no
  exceptions: `club_subscriptions`, `family_benefits`,
  `betting_games_of_chance`).

`resolution_hint` is used by the test suite to verify the two-direction floor
(see §Floor requirements). It is NOT a label field and is NOT filled in by the
specialist.

---

### Strata

| Value | Meaning |
|---|---|
| `clear_correct` | Claimable routine business purchase; no Reg 26/27 category applies. Forms the FP-rate denominator. `category` must be `"none"` or `"entertainment"`. |
| `clear_wrong` | Categorically blocked; description makes the disallowance unambiguous and NO exception can apply. Used for `club_subscriptions`, `family_benefits`, `betting_games_of_chance` (categories with no exceptions), and occasionally for `staff_medical`, `staff_medical_accident_insurance`, `motor_car` where the description explicitly rules out any exception. |
| `hard_determinable` | Description alone is sufficient to resolve whether an exception applies — either to **claimable** (e.g. `WICA MAND MED EXAM (WSH REGS)`) or to **blocked** (e.g. `PETROL CO CAR S-PLATE`). `resolution_hint` records the direction. |
| `genuinely_indeterminate` | Description is silent on the fact that would resolve the exception. **Correct system behaviour: ABSTAIN / surface with low confidence, NOT a positive verdict.** Used for `staff_medical`, `staff_medical_accident_insurance`, and `motor_car` lines where the WICA or Reg 25(1) status is unknowable from the SAP description alone. |

### Categories

| Value | §6.1.6 item | Exception? |
|---|---|---|
| `club_subscriptions` | Item 1 | None |
| `staff_medical` | Item 2 | WICA-mandatory; work-environment treatment post-Oct 2021 (written law) |
| `staff_medical_accident_insurance` | Item 3 | WICA-mandatory insurance or collective agreement (Industrial Relations Act) |
| `family_benefits` | Item 4 | None |
| `motor_car` | Item 5 | Reg 25(1) excluded vehicles (goods vehicles, motorcycles, buses) |
| `betting_games_of_chance` | Item 6 | None |
| `none` | N/A — claimable | N/A |
| `entertainment` | §6.1.3 — NOT a Reg 26/27 disallowed category | **NEGATIVE CONTROL**: system must NOT flag these as Reg 26/27 candidates |

---

## Label fields — MUST SHIP NULL in both fixture files

The following four fields are present on every line but **must be `null` in both
shipped fixture JSON files**. They exist solely for the independent GST specialist
to fill in during the labelling review.

| Field | Type | Specialist fills in |
|---|---|---|
| `expected_candidate` | null | `true` = this is a Reg 26/27 candidate; `false` = claimable |
| `determinability` | null | `"determinable"` or `"indeterminate"` |
| `label_rationale` | null | IRAS citation + reasoning |
| `label_confidence` | null | `"high"` \| `"medium"` \| `"low"` |

**INVARIANT**: any non-null value in these fields in a shipped fixture file is a
validation-integrity violation.

---

## JSON shape (template)

```json
{
  "_meta": {
    "schema_version": "reg2627-v1",
    "business_context": "generic trading/services SME",
    "set_name": "representative",
    "validation_status": "unvalidated",
    "ground_truth_set_by": null,
    "created_by": "t2.13-fixture-build",
    "created_at": "YYYY-MM-DD"
  },
  "lines": [
    {
      "line_id": "R001",
      "doc_num": 3001,
      "line_description": "SICC ANNUAL MBR SUBS",
      "amount": 4800.00,
      "gst_amount": 432.00,
      "vat_group": "SI",
      "business_context": "generic trading/services SME",
      "stratum": "clear_wrong",
      "category": "club_subscriptions",
      "resolution_hint": null,
      "expected_candidate": null,
      "determinability": null,
      "label_rationale": null,
      "label_confidence": null
    }
  ]
}
```

---

## Floor requirements — enforced by `tests/test_t2.13_fixture_schema.py`

| Constraint | Threshold | Applies to |
|---|---|---|
| Lines per blocked category | ≥ 6 | Both sets |
| `hard_determinable` with `resolution_hint="claimable"` for `staff_medical` | ≥ 1 | Both sets |
| `hard_determinable` with `resolution_hint="blocked"` for `staff_medical` | ≥ 1 | Both sets |
| `hard_determinable` with `resolution_hint="claimable"` for `staff_medical_accident_insurance` | ≥ 1 | Both sets |
| `hard_determinable` with `resolution_hint="blocked"` for `staff_medical_accident_insurance` | ≥ 1 | Both sets |
| `hard_determinable` with `resolution_hint="claimable"` for `motor_car` | ≥ 1 | Both sets |
| `hard_determinable` with `resolution_hint="blocked"` for `motor_car` | ≥ 1 | Both sets |
| Entertainment negatives (`category="entertainment"`) | ≥ 8 | Both sets |
| `stratum="clear_correct"` share of total lines | ≥ 40% | Both sets |
| `_meta.validation_status` | `"unvalidated"` | Both sets |
| `_meta.ground_truth_set_by` | `null` | Both sets |
| `business_context` non-empty on every line | required | Both sets |
| All four label fields null on every line | required | Both sets |
