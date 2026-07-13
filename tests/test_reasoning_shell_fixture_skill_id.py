"""
T2.27 — fixture skill-id discriminator (generic side).

The existing reg2627 fixtures (tests/fixtures/reg2627-*.json) and their schema
doc (tests/fixtures/SCHEMA-reg2627-v1.md) record skill identity ONLY in the
filename — a second skill's fixtures would collide.  This adds a generic
skill_id discriminator:

  * reasoning/fixture_schema.py exposes fixture_skill_id() and the blank-label
    invariant helper, both skill-agnostic.
  * fixture_skill_id() falls back to "reg2627" when _meta.skill_id is absent, so
    the existing reg2627 fixtures keep resolving correctly WITHOUT editing them
    (they are append-only-protected under tests/).
  * A TEST-ONLY stub fixture carries _meta.skill_id="stubskill" and proves the
    blank-label invariant still holds generically.

STOP-REPORTED separately to Terry: stamping _meta.skill_id="reg2627" into the
existing append-only reg2627 fixtures + SCHEMA doc, and generalizing the locked
blank-label test test_t2_13_fixture_schema.py, require editing files under
tests/ and must be authored by the human (append-only-test boundary).
"""
from __future__ import annotations

import json
from pathlib import Path

from reasoning.fixture_schema import (
    LABEL_FIELDS,
    SKILL_ID_FALLBACK,
    fixture_skill_id,
    label_fields_blank,
)

_STUB_FIXTURE = (
    Path(__file__).parent / "fixtures" / "reasoning-shell" / "stubskill-fixture-v1.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestFixtureSkillId:
    def test_stub_fixture_declares_skill_id(self):
        data = _load(_STUB_FIXTURE)
        assert data["_meta"]["skill_id"] == "stubskill"
        assert fixture_skill_id(data) == "stubskill"

    def test_absent_skill_id_falls_back_to_reg2627(self):
        # A fixture with no _meta.skill_id (the current reg2627 shape) resolves
        # to the legacy skill id, so nothing breaks pending the human retrofit.
        legacy = {"_meta": {"schema_version": "reg2627-v1"}, "lines": []}
        assert fixture_skill_id(legacy) == SKILL_ID_FALLBACK == "reg2627"

    def test_stub_fixture_validation_status_unvalidated(self):
        data = _load(_STUB_FIXTURE)
        assert data["_meta"]["validation_status"] == "unvalidated"
        assert data["_meta"]["ground_truth_set_by"] is None


class TestBlankLabelInvariantGeneric:
    def test_stub_fixture_all_label_fields_blank(self):
        data = _load(_STUB_FIXTURE)
        assert data["lines"], "stub fixture must have at least one line"
        for line in data["lines"]:
            assert label_fields_blank(line), (
                f"blank-label invariant violated on line {line.get('line_id')}"
            )
            for field in LABEL_FIELDS:
                assert line[field] is None

    def test_label_fields_blank_detects_a_filled_label(self):
        filled = {f: None for f in LABEL_FIELDS}
        filled["expected_candidate"] = True
        assert label_fields_blank(filled) is False
