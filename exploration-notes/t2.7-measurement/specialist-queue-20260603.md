# Specialist Review Queue

> Specialist review queue — provisional Opus labels, validation_status: unvalidated. Reviewer adjudicates; do not treat as a result until reconciled.

**Artefact:** `labelling-pass-20260603.json`  
**Generated:** 2026-06-03T09:30:18.890689+00:00  
**Total queued:** 12 lines  

## Counts by category

| Category | Lines |
|---|---|
| club_subscriptions | 1 |
| entertainment | 2 |
| medical_expenses | 6 |
| n/a | 3 |

- **Contested** (both passes disagreed): 3
- **Low-confidence** (all indeterminate lines have confidence=low by construction)

## Queue

| doc_num | desc | category | contested | model_disposition | pass1 | pass2 | iras_basis |
|---|---|---|---|---|---|---|---|
| 2044 | GOLF CLIENT GUEST | club_subscriptions | True | disallowed | disallowed/determinable | disallowed/indeterminate | §6.1.6 item 1, General Guide |
| 2046 | CORP BOX SPORTS EVT | entertainment | False | claimable | claimable/indeterminate | claimable/indeterminate | §6.1.3(b)(ii), General Guide |
| 2050 | CLIENT CRUISE ENTMT | entertainment | False | claimable | claimable/indeterminate | claimable/indeterminate | §6.1.3(b)(ii), General Guide |
| 2074 | WORK INJURY TREAT | medical_expenses | True | claimable | claimable/determinable | claimable/indeterminate | §6.1.6 item 2(a), General Guide |
| 2075 | WSH MEDICAL EXAM | medical_expenses | False | claimable | claimable/indeterminate | claimable/indeterminate | §6.1.6 item 2(b), General Guide |
| 2076 | OCC HEALTH SCREEN | medical_expenses | False | disallowed | disallowed/indeterminate | disallowed/indeterminate | §6.1.6 item 2, General Guide |
| 2079 | CHEM EXPOSURE TEST | medical_expenses | True | claimable | claimable/indeterminate | disallowed/indeterminate | §6.1.6 item 2(b), General Guide |
| 2080 | HEARING TEST OCC | medical_expenses | False | disallowed | disallowed/indeterminate | disallowed/indeterminate | §6.1.6 item 2, General Guide |
| 2081 | RADIATION HEALTH MON | medical_expenses | False | claimable | claimable/indeterminate | claimable/indeterminate | §6.1.6 item 2(b), General Guide |
| 2070 | VAN CARPARK SEASON | n/a | False | claimable | claimable/indeterminate | claimable/indeterminate | §6.1.6 item 5, General Guide; Reg 2 |
| 2104 | SUNDRY | n/a | False | claimable | claimable/indeterminate | claimable/indeterminate | §6.1.6, General Guide |
| 2105 | MISC | n/a | False | claimable | claimable/indeterminate | claimable/indeterminate | §6.1.6, General Guide (no disallowe |

## How to fill in

For each row in the Excel worksheet, complete three columns:
- **specialist_disposition:** `disallowed` | `claimable` | `unclear`
- **specialist_category:** one of the §6.1.6 Reg 26/27 categories, `entertainment`, or `n/a`
- **specialist_notes:** one sentence — the IRAS reference or context needed.

Return the completed worksheet to be reconciled into the promoted fixture.

_validation_status remains 'unvalidated' until this reconciliation is done._
