"""reasoning/fixture_schema.py — skill-agnostic labelling-fixture helpers (T2.27).

Generalizes two things that were previously implicit/hard-coded in the reg2627
fixtures + their locked schema test (tests/test_t2_13_fixture_schema.py):

  1. Skill identity.  reg2627 fixtures record which skill they belong to only in
     the filename.  A second skill's fixtures would collide.  fixture_skill_id()
     reads _meta.skill_id, falling back to the legacy "reg2627" when the field is
     absent — so the existing (append-only, un-editable) reg2627 fixtures keep
     resolving correctly WITHOUT being edited.

  2. The blank-label invariant.  The four specialist-only label fields must ship
     null (the rule-author is never the labeller).  label_fields_blank() expresses
     this check generically so any skill's fixtures can be validated the same way.

NOTE (STOP-reported to Terry): stamping _meta.skill_id="reg2627" into the existing
reg2627 fixtures + SCHEMA-reg2627-v1.md, and generalizing the locked blank-label
test, all require editing files under tests/ (append-only-test boundary) and must
be authored by the human.  This module + a new stub fixture prove the mechanism
without touching any existing protected file.
"""
from __future__ import annotations

# The four specialist-only label fields — must be null in every shipped fixture.
LABEL_FIELDS = (
    "expected_candidate",
    "determinability",
    "label_rationale",
    "label_confidence",
)

# Fixtures that predate the skill_id discriminator are Reg 26/27 fixtures.
SKILL_ID_FALLBACK = "reg2627"


def fixture_skill_id(fixture: dict) -> str:
    """Return the skill a fixture belongs to.

    Reads _meta.skill_id; falls back to SKILL_ID_FALLBACK ("reg2627") when the
    field is absent, so the existing reg2627 fixtures keep resolving without any
    edit to those append-only files.
    """
    meta = fixture.get("_meta", {}) or {}
    return meta.get("skill_id") or SKILL_ID_FALLBACK


def label_fields_blank(line: dict) -> bool:
    """True iff every specialist-only label field on the line is null/absent.

    Enforces the blank-label invariant generically: a shipped fixture line must
    carry no non-null value in any LABEL_FIELDS entry.
    """
    return all(line.get(field) is None for field in LABEL_FIELDS)
