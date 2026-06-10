# Documentation Staleness Report — Post T2.9 + T2.13 Merge

**Audit date:** 2026-06-09  
**Master state:** `683b9d7` (T2.13 merged) — 1026 passed, 1 skipped (1027 collected)  
**Branches merged in:** `t2.9-declared-vs-computed` (`583bd76`), `t2.13-validation-dataset` (`683b9d7`)  
**Scope:** Read-only inventory only. NO edits, NO commits made.

---

## What T2.9 and T2.13 added (reference)

### T2.9 — declared-vs-computed F5 divergence detection

| File | Change |
|---|---|
| `orchestrator/check_declared_f5.py` | NEW — Check A (declared internal consistency: Box4==1+2+3, Box8==6−7) + Check B (declared-vs-computed per independent box, tolerance per IRAS ASK Guide s10.1(d)(iii) fn33) |
| `orchestrator/chain.py` | declared-f5 integration |
| `orchestrator/schemas.py` | DeclaredF5 schema additions |
| `orchestrator/steps.py` | step wiring |
| `audit_bundle/seal.py` | seals declared-f5 findings |
| `run_agent.py` | `--declared-f5` CLI flag |
| `tests/test_check_declared_f5.py` | 18 new tests (isolation, Check A/B, tolerance, load validation) |
| `tests/test_audit_seal_verify.py` | additions covering declared-f5 seal path |

Net test delta: **+19 tests** (915 → 934).  
Validation status: **UNVALIDATED / flag-gated**. Findings, not gates. Does not affect F5 boxes.

### T2.13 — Reg 26/27 validation dataset construction

| File | Change |
|---|---|
| `tests/fixtures/reg2627-representative-v1.json` | NEW — representative validation fixture (stratified Reg 26/27 cases) |
| `tests/fixtures/reg2627-adversarial-v1.json` | NEW — adversarial validation fixture |
| `tests/fixtures/SCHEMA-reg2627-v1.md` | NEW — fixture schema documentation |
| `tests/fixtures/export_specialist_copy.py` | NEW — specialist-export script; strips `resolution_hint` field (strip guard) |
| `exploration-notes/t2.13/labelling-protocol.md` | NEW — labelling protocol for independent specialist review |
| `tests/test_t2_13_fixture_schema.py` | 92 new tests (fixture schema invariants, specialist-export strip guard) |
| `.gitignore` | minor addition |
| `README.md` | +30 lines: "Fresh worktree or clone setup" section (bootstrap instructions) |

Net test delta: **+92 tests** (934 → 1026).  
Validation status: **UNVALIDATED**. Dataset is BUILT and BLANK-LABELLED — labels are empty, awaiting independent specialist review. T2.11 is the binding constraint; it is NOT done.

---

## CRITICAL framing for eventual doc updates

**T2.13 DONE ≠ validated.**

"T2.13 done" means the validation dataset is **built** (two JSON fixture files) and **blank-labelled** (`expected_candidate` fields are present but empty — filled only after a human GST specialist reviews each case against IRAS sources). It does NOT mean:

- That any specialist has reviewed or assigned labels
- That `validation_status` has changed (it stays `"unvalidated"`)
- That T2.11 (independent specialist reconciliation) is complete
- That `show_ai_candidates` may be set to `true` in any client YAML

Any doc language that lets "T2.13 done" read as "the reasoning layer is validated" is dangerous and must be explicitly guarded against. T2.11 remains the binding constraint.

---

## Stale claims inventory

### 1. `AGENTASSIST_TECHNICAL_STATE.md`

| # | Line(s) | Stale claim (quoted) | What it should now say | Driven by |
|---|---------|----------------------|------------------------|-----------|
| 1.1 | 90 | `"Current test state: 915 passed, 1 skipped."` | 1026 passed, 1 skipped | T2.9 + T2.13 |
| 1.2 | 90 | `"T2.8 (branch \`t2.8-document-ingestion\`) added the source-document cross-reference pre-pass — built and flag-gated … unvalidated pending T2.11."` | T2.8 is now on master (merged `c19a765`). Branch reference should be removed. T2.9 and T2.13 should also be noted in the exec summary. | T2.9, T2.13 (T2.7/T2.8 branch references pre-existing staleness) |
| 1.3 | 329–481 | Repo tree — `orchestrator/` section lists no `check_declared_f5.py` | Add `check_declared_f5.py ← T2.9: declared-vs-computed Check A/B, tolerance-grounded, findings not gates` | T2.9 |
| 1.4 | 329–481 | Repo tree — `tests/` section lists no `test_check_declared_f5.py` | Add `test_check_declared_f5.py ← T2.9: 18 tests — isolation, Check A/B, tolerance boundary, load validation` | T2.9 |
| 1.5 | 329–481 | Repo tree — `tests/fixtures/` shows no T2.13 fixture files | Add `reg2627-representative-v1.json`, `reg2627-adversarial-v1.json`, `SCHEMA-reg2627-v1.md`, `export_specialist_copy.py` | T2.13 |
| 1.6 | 329–481 | Repo tree — `tests/` shows no `test_t2_13_fixture_schema.py` | Add `test_t2_13_fixture_schema.py ← T2.13: 92 tests — fixture schema invariants, specialist-export strip guard` | T2.13 |
| 1.7 | 329–481 | Repo tree — `exploration-notes/` shows no `t2.13/` subdirectory or `doc-audit/` | Add both | T2.13 |
| 1.8 | 843–845 | `"T2.7 — Reg 26/27 reasoning pass (BRANCH ONLY — \`t2.7-reasoning-reg2627\`, unvalidated as of 2026-06-08)"` | T2.7 is on master. Remove "BRANCH ONLY". Update date. | Pre-existing (not T2.9/T2.13-driven) |
| 1.9 | 998–1000 | `"T2.8 — Source-document cross-reference pre-pass (BRANCH ONLY — \`t2.8-document-ingestion\`, unvalidated as of 2026-06-08)"` | T2.8 is on master. Remove "BRANCH ONLY". Update date. | Pre-existing (not T2.9/T2.13-driven) |
| 1.10 | 1116 | `"**915 collected (914 passed, 1 skipped)** on branch \`t2.8-document-ingestion\` as of 2026-06-08. T2.8 adds 4 new test files (~312 additional tests vs. the T2.7 state)."` | 1026 passed, 1 skipped on master as of 2026-06-09. T2.9 added `test_check_declared_f5.py` (+18) + seal additions; T2.13 added `test_t2_13_fixture_schema.py` (+92). | T2.9 + T2.13 |
| 1.11 | 2250–2269 | Footer ends at `"…915 tests; validation_status unvalidated; not merged to master"` — no mention of T2.9 or T2.13 | Footer should be extended with T2.9 and T2.13 update entries; test count updated to 1026; "not merged to master" qualifier removed for T2.9/T2.13 | T2.9 + T2.13 |
| 1.12 | 2204–2206 | Appendix C #22: `"**ZP+TaxTotal E2 gap** (OPEN): DocNum 610 (ZP+TaxTotal=84) is a real E2…"` | Still OPEN. T2.10 scope. Must NOT be read as done due to T2.9 — declared-vs-computed is a different check. | Note only — confirm status |

---

### 2. `knowledge-base/AgentAssist-Technical-Roadmap-v5.md`

| # | Line(s) | Stale claim (quoted) | What it should now say | Driven by |
|---|---------|----------------------|------------------------|-----------|
| 2.1 | 31–34 | `"Built but unvalidated (branches \`t2.7-reasoning-reg2627\` and \`t2.8-document-ingestion\`, not merged to master):"` | T2.7 and T2.8 are on master. T2.9 (declared-vs-computed, findings not gates, flag-gated) is now also on master. T2.13 (validation dataset built + blank-labelled, NOT validated) is on master. Section needs expansion. | T2.9 + T2.13 (T2.7/T2.8 pre-existing) |
| 2.2 | 94 | `"915 tests passing (4 new T2.8 test files)."` | 1026 passed, 1 skipped (+19 from T2.9, +92 from T2.13) | T2.9 + T2.13 |
| 2.3 | 107–109 | `"### T2.9 — Filed-F5-return ingestion (declared-vs-computed reconciliation) — PLANNED"` | **DONE** (built, flag-gated, UNVALIDATED / findings-not-gates). Closes the recurring ◐ across Steps 1.3b, 1.3d, 3A.1.a, 3B.1.a, 3C.1.a, 3D.1.1.a. `--declared-f5` CLI flag; findings surface in report; never affect F5 boxes or gates. | T2.9 |
| 2.4 | 125–137 | `"### T2.13 — Validation dataset construction (synthetic-paired + pilot-derived) — PLANNED (NEW)"` | **DONE** — with MANDATORY framing: dataset is BUILT and BLANK-LABELLED. `expected_candidate` fields are present but empty. No labels assigned. `validation_status: "unvalidated"` — unchanged. T2.11 is still required and is the binding constraint. `show_ai_candidates` stays False. | T2.13 |
| 2.5 | 226–232 | Open integrity flag: `"**Test fixtures are live-seeded into SBODEMOSG and ephemeral** … Static, repo-resident fixtures (open item #21) still do not exist."` | T2.13 partially addresses this for the Reg 26/27 reasoning layer — `reg2627-representative-v1.json` and `reg2627-adversarial-v1.json` are now static repo-resident fixtures. However, open item #21 for the **deterministic chain** (rate-transition, partial exemption, reverse-charge, custom VatGroup fixtures) remains open. Clarify the two distinct fixture gaps. | T2.13 (partial) |

---

### 3. `README.md`

| # | Line(s) | Stale claim (quoted) | What it should now say | Driven by |
|---|---------|----------------------|------------------------|-----------|
| 3.1 | 65 | `"**Test suite: 169 tests passing** (1 skipped: read-only advisory, Windows; no live SAP required)."` | 1026 passed, 1 skipped | T2.9 + T2.13 (massively pre-stale; T2.7/T2.8 had already taken it to 915 before these merges) |
| 3.2 | 49–57 | Milestone table ends at T1.5/T1.6; no T2.x milestones listed | Add T2.7 (reasoning layer, on master, UNVALIDATED), T2.8 (document ingestion, on master, UNVALIDATED), T2.9 (declared-vs-computed, on master, UNVALIDATED / flag-gated), T2.13 (validation dataset built + blank-labelled, on master, NOT validated) | T2.9 + T2.13 (T2.7/T2.8 pre-existing) |
| 3.3 | 171–215 | Repository layout — `orchestrator/` section missing `check_declared_f5.py` | Add `check_declared_f5.py ← T2.9 declared-vs-computed checks` | T2.9 |
| 3.4 | 171–215 | Repository layout — `tests/` section shows `"└── test_*.py ← 169 tests; no live SAP required"` | Update count; add `test_check_declared_f5.py`, `test_t2_13_fixture_schema.py` | T2.9 + T2.13 |
| 3.5 | 171–215 | Repository layout — `tests/fixtures/` section shows only `chain-run-sample.json` | Add `reg2627-representative-v1.json`, `reg2627-adversarial-v1.json`, `SCHEMA-reg2627-v1.md`, `export_specialist_copy.py` | T2.13 |

---

### 4. `exploration-notes/operational-backlog.md`

| # | Line(s) | Stale claim (quoted) | What it should now say | Driven by |
|---|---------|----------------------|------------------------|-----------|
| 4.1 | 5 | `"All six Tier-1 items are done; 169 tests passing."` | 1026 tests passing (T2.9 +19, T2.13 +92, plus pre-existing T2.7/T2.8 additions) | T2.9 + T2.13 |

---

### 5. `exploration-notes/swe-audit-2026-06-08.md`

**This file is a frozen historical snapshot** (explicitly dated 2026-06-08, branch `t2.8-document-ingestion`). It should NOT be updated. Listed here only for awareness.

| # | Line(s) | Stale claim | Note |
|---|---------|-------------|------|
| 5.1 | 63–64 | `"tests/ pytest suite (18 files, 602 tests)"` | Historical: current is more test files, 1026 tests. **Frozen snapshot — do not update.** |
| 5.2 | 354 | `"The README states 'Test suite: 169 tests passing'. The actual current count is 602 passed."` | Both the stated count and the observed count are now stale. The README count is still wrong (now should be 1026); the observed count at audit time was 602. **Frozen snapshot — do not update.** |

---

### 6. Pre-merge gate definition (doc-debt item — no existing canonical location)

**The plain-string gate check produces false positives and must be replaced.**

| Finding | Detail |
|---------|--------|
| Stale gate definition | `grep -r "anthropic" orchestrator/ -> must be empty` — this is the informal / in-practice pre-merge gate for the "orchestrator has no Anthropic imports" invariant |
| Why it fails | `orchestrator/check_declared_f5.py:44` contains the docstring line `"No SAP calls; no anthropic import. Pure Python, import-safe from orchestrator/."` — this exact string triggered a false-positive gate failure during the T2.9 merge gate run on 2026-06-09 |
| Correct gate definition | Two greps, both must return nothing (exit 1): |
| | `grep -rnE "^[[:space:]]*(import[[:space:]]+anthropic\|from[[:space:]]+anthropic[[:space:]]+import)" orchestrator/` |
| | `grep -rnE "^[[:space:]]*(import[[:space:]]+(reasoning\|documents)\|from[[:space:]]+(reasoning\|documents)[[:space:]]+import)" orchestrator/` |
| Why the revised form is correct | Matches only actual import statements (top-level, aliased, indented/deferred); ignores comments and docstrings, which can never be violations |
| Where this should be documented | Whatever process documentation or runbook captures the pre-merge gate protocol (does not exist as a dedicated file yet — candidate locations: a `CONTRIBUTING.md`, a dedicated `docs/merge-gates.md`, or in `AGENTASSIST_TECHNICAL_STATE.md` under a process section) |
| Driven by | T2.9 |

---

## UNSURE — flag for Terry's call

The following files **may** need updating but require Terry's judgment to confirm scope or framing. Not calling them stale outright.

| File | Uncertainty |
|------|------------|
| `exploration-notes/iras-ask-coverage-analysis.md` | T2.9 closes the recurring ◐ across declared-vs-computed reconciliation steps in the ASK coverage framework (Steps 1.3b output-tax threshold, 1.3d, 3A.1.a, 3B.1.a, 3C.1.a, 3D.1.1.a per roadmap). The coverage-analysis tables likely still show those steps as ◐ or ✗. However, because T2.9 is UNVALIDATED, the correct mark is arguably ◑ (built, not validated) rather than ✓ (validated). Terry's call on whether to update coverage marks for unvalidated builds. |
| `exploration-notes/t2.7-measurement/known-limitations.md` | May reference T2.13 as planned work in a roadmap-section. If so, those references are now outdated (T2.13 has been built). However, the known-limitations doc covers T2.7-specific measurement constraints — T2.13 does not resolve any of the listed T2.7 limitations (fixture labels still need specialist review; entertainment inconsistency still open; per-batch retry still absent). Likely needs only a minor note that the T2.13 substrate now exists. |
| `AGENTASSIST_TECHNICAL_STATE.md` — Appendix C #24 | Quote: `"NOT MERGED TO MASTER as of 2026-06-08."` (referring to T2.7 measurement harness). T2.7 is now on master. This qualifier is stale but the item is about T2.7-specific measurement state, not T2.9/T2.13. Flagging for Terry's review — the item may need broader update to reflect current harness state. |
| `AGENTASSIST_TECHNICAL_STATE.md` — Appendix C #21 | Quote: `"Static, repo-resident fixtures (open item #21) still do not exist."` T2.13 added two static JSON fixtures for Reg 26/27 reasoning. For the **reasoning layer** the claim is now partially wrong. For the **deterministic chain** (rate-transition, partial exemption, reverse-charge fixtures) it remains open. Terry's call on whether to split #21 into two sub-items or add a "PARTIALLY RESOLVED by T2.13 for reasoning layer" qualifier. |

---

## Summary table — what to update, in what order

| Priority | File | Staleness type | Driven by |
|----------|------|---------------|-----------|
| P1 | `knowledge-base/AgentAssist-Technical-Roadmap-v5.md` | T2.9/T2.13 task status (PLANNED → DONE), build-state snapshot, test count, open-items partial resolution | T2.9 + T2.13 |
| P1 | `AGENTASSIST_TECHNICAL_STATE.md` | Test count (×2 locations), footer, repo tree (missing 7+ files) | T2.9 + T2.13 |
| P2 | `README.md` | Test count (169), milestone table (missing T2.x), repo layout (missing files) | T2.9 + T2.13 |
| P2 | Pre-merge gate definition | Plain-string grep → import-only grep (wherever this is written down) | T2.9 |
| P3 | `exploration-notes/operational-backlog.md` | Test count (169) | T2.9 + T2.13 |
| P3 | `AGENTASSIST_TECHNICAL_STATE.md` | T2.7/T2.8 "BRANCH ONLY" labels — branches are now on master | Pre-existing |
| Review | `exploration-notes/iras-ask-coverage-analysis.md` | Possible coverage-mark updates for T2.9 declared-vs-computed steps | Terry's call |
| Review | `exploration-notes/t2.7-measurement/known-limitations.md` | Possible minor note re: T2.13 substrate exists | Terry's call |

---

## What NOT to update

- `exploration-notes/swe-audit-2026-06-08.md` — frozen historical snapshot; update would corrupt the audit trail
- `exploration-notes/codebase-state-report.md` — explicitly documented as "2026-05-28 frozen audit snapshot (pre-T1.3/T1.6); historical only"
- `exploration-notes/baseline-test-results.md` — V0→V3 experimental log; self-contained historical evidence; T2.9/T2.13 don't affect the v0–v3 scoring narrative
- `validation_status` fields anywhere — must stay `"unvalidated"` until T2.11 completes
- `show_ai_candidates` flag in any client YAML — must stay `False` pending T2.11

---

*Report generated 2026-06-09. Read-only pass — no source files edited, no commits made.*
