"""
T2.13 fixture schema tests.

Validates both reg2627-representative-v1.json and reg2627-adversarial-v1.json
against SCHEMA-reg2627-v1.md invariants and floor requirements.

Also validates the specialist-export pipeline (item 1c):
  TestSpecialistExport asserts that the specialist-facing export contains
  NO resolution_hint key AND no non-null label fields on any line.

NO Anthropic API calls. NO imports from reasoning/, orchestrator/, or report/.
This file is self-contained: it reads JSON and asserts structural properties.
"""

import importlib.util
import json
import os
import pathlib

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

REPRESENTATIVE = os.path.join(FIXTURES_DIR, "reg2627-representative-v1.json")
ADVERSARIAL = os.path.join(FIXTURES_DIR, "reg2627-adversarial-v1.json")

# ---------------------------------------------------------------------------
# Import export_specialist_copy without adding fixtures/ to sys.path globally
# ---------------------------------------------------------------------------
_export_spec = importlib.util.spec_from_file_location(
    "export_specialist_copy",
    pathlib.Path(__file__).parent / "fixtures" / "export_specialist_copy.py",
)
_export_mod = importlib.util.module_from_spec(_export_spec)
_export_spec.loader.exec_module(_export_mod)
strip_construction_intent = _export_mod.strip_construction_intent
CONSTRUCTION_INTENT_FIELDS = _export_mod.CONSTRUCTION_INTENT_FIELDS

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

BLOCKED_CATEGORIES = {
    "club_subscriptions",
    "staff_medical",
    "staff_medical_accident_insurance",
    "family_benefits",
    "motor_car",
    "betting_games_of_chance",
}

EXCEPTION_CATEGORIES = {
    "staff_medical",
    "staff_medical_accident_insurance",
    "motor_car",
}

ALL_CATEGORIES = BLOCKED_CATEGORIES | {"none", "entertainment"}

VALID_STRATA = {"clear_correct", "clear_wrong", "hard_determinable", "genuinely_indeterminate"}

LABEL_FIELDS = ("expected_candidate", "determinability", "label_rationale", "label_confidence")

MIN_LINES_PER_BLOCKED_CATEGORY = 6
MIN_ENTERTAINMENT_LINES = 8
MIN_CLEAR_CORRECT_FRACTION = 0.40


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def representative():
    return _load(REPRESENTATIVE)


@pytest.fixture(scope="module")
def adversarial():
    return _load(ADVERSARIAL)


@pytest.fixture(params=["representative", "adversarial"])
def fixture_data(request, representative, adversarial):
    return representative if request.param == "representative" else adversarial


# ---------------------------------------------------------------------------
# Meta invariants
# ---------------------------------------------------------------------------


class TestMetaInvariants:
    def test_skill_id_is_reg2627(self, fixture_data):
        assert fixture_data["_meta"]["skill_id"] == "reg2627", (
            "_meta.skill_id must be 'reg2627' in shipped reg2627 fixtures"
        )
        
    def test_schema_version(self, fixture_data):
        assert fixture_data["_meta"]["schema_version"] == "reg2627-v1"

    def test_validation_status_unvalidated(self, fixture_data):
        assert fixture_data["_meta"]["validation_status"] == "unvalidated", (
            "_meta.validation_status must be 'unvalidated' in shipped fixtures"
        )

    def test_ground_truth_set_by_null(self, fixture_data):
        assert fixture_data["_meta"]["ground_truth_set_by"] is None, (
            "_meta.ground_truth_set_by must be null in shipped fixtures"
        )

    def test_set_name_valid(self, fixture_data):
        assert fixture_data["_meta"]["set_name"] in ("representative", "adversarial_hard")

    def test_business_context_non_empty(self, fixture_data):
        bc = fixture_data["_meta"].get("business_context", "")
        assert bc, "_meta.business_context must be non-empty"


# ---------------------------------------------------------------------------
# Per-line schema: required fields present and typed correctly
# ---------------------------------------------------------------------------


class TestLineSchema:
    REQUIRED_FIELDS = [
        "line_id", "doc_num", "line_description", "amount", "gst_amount",
        "vat_group", "business_context", "stratum", "category",
        "resolution_hint",
        "expected_candidate", "determinability", "label_rationale", "label_confidence",
    ]

    def test_all_required_fields_present(self, fixture_data):
        for line in fixture_data["lines"]:
            for field in self.REQUIRED_FIELDS:
                assert field in line, (
                    f"Line {line.get('line_id', '?')} missing field '{field}'"
                )

    def test_line_ids_unique(self, fixture_data):
        ids = [line["line_id"] for line in fixture_data["lines"]]
        assert len(ids) == len(set(ids)), "Duplicate line_id values found"

    def test_doc_nums_integer(self, fixture_data):
        for line in fixture_data["lines"]:
            assert isinstance(line["doc_num"], int), (
                f"Line {line['line_id']}: doc_num must be an integer"
            )

    def test_amounts_non_negative(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line["amount"] >= 0, f"Line {line['line_id']}: amount must be >= 0"
            assert line["gst_amount"] >= 0, f"Line {line['line_id']}: gst_amount must be >= 0"

    def test_gst_amount_matches_9_percent(self, fixture_data):
        for line in fixture_data["lines"]:
            expected_gst = round(line["amount"] * 0.09, 2)
            actual_gst = round(line["gst_amount"], 2)
            assert abs(actual_gst - expected_gst) < 0.02, (
                f"Line {line['line_id']}: gst_amount {actual_gst} does not match "
                f"amount × 0.09 = {expected_gst}"
            )

    def test_vat_group_is_SI(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line["vat_group"] == "SI", (
                f"Line {line['line_id']}: vat_group must be 'SI'"
            )

    def test_stratum_valid_enum(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line["stratum"] in VALID_STRATA, (
                f"Line {line['line_id']}: invalid stratum '{line['stratum']}'"
            )

    def test_category_valid_enum(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line["category"] in ALL_CATEGORIES, (
                f"Line {line['line_id']}: invalid category '{line['category']}'"
            )

    def test_business_context_non_empty_every_line(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line.get("business_context"), (
                f"Line {line['line_id']}: business_context must be non-empty"
            )

    def test_line_description_non_empty(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line.get("line_description", "").strip(), (
                f"Line {line['line_id']}: line_description must be non-empty"
            )

    def test_line_description_max_50_chars(self, fixture_data):
        for line in fixture_data["lines"]:
            assert len(line["line_description"]) <= 50, (
                f"Line {line['line_id']}: line_description '{line['line_description']}' "
                f"exceeds 50 characters"
            )


# ---------------------------------------------------------------------------
# INVARIANT: all label fields must be null in shipped fixtures
# ---------------------------------------------------------------------------


class TestLabelFieldsShipNull:
    def test_expected_candidate_null(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line["expected_candidate"] is None, (
                f"INTEGRITY VIOLATION — Line {line['line_id']}: "
                f"expected_candidate must be null in shipped fixture "
                f"(got {line['expected_candidate']!r})"
            )

    def test_determinability_null(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line["determinability"] is None, (
                f"INTEGRITY VIOLATION — Line {line['line_id']}: "
                f"determinability must be null in shipped fixture"
            )

    def test_label_rationale_null(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line["label_rationale"] is None, (
                f"INTEGRITY VIOLATION — Line {line['line_id']}: "
                f"label_rationale must be null in shipped fixture"
            )

    def test_label_confidence_null(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line["label_confidence"] is None, (
                f"INTEGRITY VIOLATION — Line {line['line_id']}: "
                f"label_confidence must be null in shipped fixture"
            )


# ---------------------------------------------------------------------------
# resolution_hint constraints
# ---------------------------------------------------------------------------


class TestResolutionHint:
    VALID_HINTS = {"claimable", "blocked", None}

    def test_resolution_hint_valid_values(self, fixture_data):
        for line in fixture_data["lines"]:
            assert line["resolution_hint"] in self.VALID_HINTS, (
                f"Line {line['line_id']}: resolution_hint must be 'claimable', "
                f"'blocked', or null (got {line['resolution_hint']!r})"
            )

    def test_resolution_hint_only_on_hard_determinable_exception_categories(self, fixture_data):
        for line in fixture_data["lines"]:
            hint = line["resolution_hint"]
            if hint is not None:
                assert line["stratum"] == "hard_determinable", (
                    f"Line {line['line_id']}: resolution_hint is set but "
                    f"stratum is '{line['stratum']}' (must be hard_determinable)"
                )
                assert line["category"] in EXCEPTION_CATEGORIES, (
                    f"Line {line['line_id']}: resolution_hint is set but "
                    f"category is '{line['category']}' which has no exceptions"
                )

    def test_hard_determinable_exception_lines_have_hint(self, fixture_data):
        for line in fixture_data["lines"]:
            if (
                line["stratum"] == "hard_determinable"
                and line["category"] in EXCEPTION_CATEGORIES
            ):
                assert line["resolution_hint"] in ("claimable", "blocked"), (
                    f"Line {line['line_id']}: hard_determinable exception-category line "
                    f"must have resolution_hint set to 'claimable' or 'blocked'"
                )


# ---------------------------------------------------------------------------
# Stratum consistency rules
# ---------------------------------------------------------------------------


class TestStratumConsistency:
    def test_clear_correct_category_is_none_or_entertainment(self, fixture_data):
        for line in fixture_data["lines"]:
            if line["stratum"] == "clear_correct":
                assert line["category"] in ("none", "entertainment"), (
                    f"Line {line['line_id']}: clear_correct stratum requires "
                    f"category 'none' or 'entertainment' (got '{line['category']}')"
                )

    def test_no_exceptions_categories_have_no_hard_det_claimable(self, fixture_data):
        no_exception_cats = BLOCKED_CATEGORIES - EXCEPTION_CATEGORIES
        for line in fixture_data["lines"]:
            if line["category"] in no_exception_cats and line["stratum"] == "hard_determinable":
                assert line["resolution_hint"] != "claimable", (
                    f"Line {line['line_id']}: category '{line['category']}' has no "
                    f"exceptions; a hard_determinable line cannot resolve to claimable"
                )


# ---------------------------------------------------------------------------
# Floor requirements — per blocked category
# ---------------------------------------------------------------------------


class TestCategoryFloors:
    def test_min_lines_per_blocked_category(self, fixture_data):
        lines = fixture_data["lines"]
        for cat in BLOCKED_CATEGORIES:
            count = sum(1 for l in lines if l["category"] == cat)
            assert count >= MIN_LINES_PER_BLOCKED_CATEGORY, (
                f"Category '{cat}' has {count} lines; minimum is "
                f"{MIN_LINES_PER_BLOCKED_CATEGORY}"
            )

    def test_entertainment_floor(self, fixture_data):
        count = sum(1 for l in fixture_data["lines"] if l["category"] == "entertainment")
        assert count >= MIN_ENTERTAINMENT_LINES, (
            f"entertainment has {count} lines; minimum is {MIN_ENTERTAINMENT_LINES}"
        )

    def test_clear_correct_fraction(self, fixture_data):
        lines = fixture_data["lines"]
        total = len(lines)
        clear_correct_count = sum(1 for l in lines if l["stratum"] == "clear_correct")
        fraction = clear_correct_count / total
        assert fraction >= MIN_CLEAR_CORRECT_FRACTION, (
            f"clear_correct fraction is {fraction:.1%} ({clear_correct_count}/{total}); "
            f"minimum is {MIN_CLEAR_CORRECT_FRACTION:.0%}"
        )


# ---------------------------------------------------------------------------
# Hard-determinable two-direction floor (refinement from T2.13 approval)
# For staff_medical, staff_medical_accident_insurance, motor_car:
# must have >=1 hard_determinable with resolution_hint="claimable"
# AND >=1 hard_determinable with resolution_hint="blocked"
# ---------------------------------------------------------------------------


class TestHardDeterminableTwoDirectionFloor:
    @pytest.mark.parametrize("category", sorted(EXCEPTION_CATEGORIES))
    def test_has_hard_det_claimable(self, fixture_data, category):
        lines = fixture_data["lines"]
        claimable_lines = [
            l for l in lines
            if l["category"] == category
            and l["stratum"] == "hard_determinable"
            and l["resolution_hint"] == "claimable"
        ]
        assert len(claimable_lines) >= 1, (
            f"Category '{category}': must have >= 1 hard_determinable line with "
            f"resolution_hint='claimable' (exception applies → NOT a candidate). "
            f"Found {len(claimable_lines)}."
        )

    @pytest.mark.parametrize("category", sorted(EXCEPTION_CATEGORIES))
    def test_has_hard_det_blocked(self, fixture_data, category):
        lines = fixture_data["lines"]
        blocked_lines = [
            l for l in lines
            if l["category"] == category
            and l["stratum"] == "hard_determinable"
            and l["resolution_hint"] == "blocked"
        ]
        assert len(blocked_lines) >= 1, (
            f"Category '{category}': must have >= 1 hard_determinable line with "
            f"resolution_hint='blocked' (exception does not apply → IS a candidate). "
            f"Found {len(blocked_lines)}."
        )

    @pytest.mark.parametrize("category", sorted(EXCEPTION_CATEGORIES))
    def test_has_genuinely_indeterminate(self, fixture_data, category):
        lines = fixture_data["lines"]
        indet_lines = [
            l for l in lines
            if l["category"] == category
            and l["stratum"] == "genuinely_indeterminate"
        ]
        assert len(indet_lines) >= 1, (
            f"Category '{category}': must have >= 1 genuinely_indeterminate line "
            f"(description silent on exception — scores abstention behaviour). "
            f"Found {len(indet_lines)}."
        )


# ---------------------------------------------------------------------------
# Cross-fixture sanity: line_id prefixes match set_name
# ---------------------------------------------------------------------------


class TestLineIdPrefixes:
    def test_representative_line_ids_start_with_R(self, representative):
        for line in representative["lines"]:
            assert line["line_id"].startswith("R"), (
                f"Representative fixture line {line['line_id']} should start with 'R'"
            )

    def test_adversarial_line_ids_start_with_A(self, adversarial):
        for line in adversarial["lines"]:
            assert line["line_id"].startswith("A"), (
                f"Adversarial fixture line {line['line_id']} should start with 'A'"
            )

    def test_no_id_overlap_between_fixtures(self, representative, adversarial):
        rep_ids = {l["line_id"] for l in representative["lines"]}
        adv_ids = {l["line_id"] for l in adversarial["lines"]}
        overlap = rep_ids & adv_ids
        assert not overlap, f"line_id overlap between fixtures: {overlap}"

    def test_doc_num_ranges_do_not_overlap(self, representative, adversarial):
        rep_nums = {l["doc_num"] for l in representative["lines"]}
        adv_nums = {l["doc_num"] for l in adversarial["lines"]}
        overlap = rep_nums & adv_nums
        assert not overlap, f"doc_num overlap between fixtures: {overlap}"


# ---------------------------------------------------------------------------
# Specialist export — validation-integrity guard (item 1c)
#
# Asserts that strip_construction_intent():
#   1. Removes resolution_hint entirely (key must not exist, not merely be null)
#   2. Leaves all four label fields null (they are already null in source;
#      the export must not accidentally fill them)
#   3. Removes ALL fields listed in CONSTRUCTION_INTENT_FIELDS
#
# This is the check that guards against circular validation: the labeller
# must never see the case-writer's intended direction.
# ---------------------------------------------------------------------------


class TestSpecialistExport:
    @pytest.fixture(scope="class")
    def stripped_representative(self, representative):
        return strip_construction_intent(representative)

    @pytest.fixture(scope="class")
    def stripped_adversarial(self, adversarial):
        return strip_construction_intent(adversarial)

    @pytest.fixture(params=["representative", "adversarial"])
    def stripped(self, request, stripped_representative, stripped_adversarial):
        return (
            stripped_representative
            if request.param == "representative"
            else stripped_adversarial
        )

    def test_resolution_hint_key_absent(self, stripped):
        """resolution_hint must not appear as a key at all — not even as null."""
        for line in stripped["lines"]:
            assert "resolution_hint" not in line, (
                f"INTEGRITY VIOLATION — Line {line.get('line_id', '?')}: "
                f"resolution_hint key must be absent from specialist copy "
                f"(found: {line.get('resolution_hint')!r})"
            )

    def test_all_construction_intent_fields_absent(self, stripped):
        """Every field in CONSTRUCTION_INTENT_FIELDS must be absent from all lines."""
        for line in stripped["lines"]:
            for field in CONSTRUCTION_INTENT_FIELDS:
                assert field not in line, (
                    f"INTEGRITY VIOLATION — Line {line.get('line_id', '?')}: "
                    f"construction-intent field '{field}' must be absent from "
                    f"specialist copy"
                )

    def test_label_fields_still_null_after_strip(self, stripped):
        """Stripping must not accidentally fill in any label field."""
        for line in stripped["lines"]:
            for field in LABEL_FIELDS:
                assert field in line, (
                    f"Line {line.get('line_id', '?')}: label field '{field}' "
                    f"must still be present (as null) in specialist copy"
                )
                assert line[field] is None, (
                    f"INTEGRITY VIOLATION — Line {line.get('line_id', '?')}: "
                    f"label field '{field}' must be null in specialist copy "
                    f"(got {line[field]!r})"
                )

    def test_specialist_copy_meta_flag(self, stripped):
        assert stripped["_meta"].get("specialist_copy") is True

    def test_stripped_fields_recorded_in_meta(self, stripped):
        recorded = stripped["_meta"].get("construction_intent_stripped", [])
        for field in CONSTRUCTION_INTENT_FIELDS:
            assert field in recorded, (
                f"_meta.construction_intent_stripped must list '{field}'"
            )

    def test_rep_line_count_unchanged(self, stripped_representative, representative):
        """Stripping must not drop any lines — representative set."""
        assert len(stripped_representative["lines"]) == len(representative["lines"])

    def test_adv_line_count_unchanged(self, stripped_adversarial, adversarial):
        """Stripping must not drop any lines — adversarial set."""
        assert len(stripped_adversarial["lines"]) == len(adversarial["lines"])

    def test_rep_non_intent_fields_preserved(self, stripped_representative, representative):
        """All non-intent fields must survive stripping — representative set."""
        preserved = ("line_id", "doc_num", "line_description", "amount", "gst_amount",
                     "vat_group", "business_context", "stratum", "category")
        src_lines = {l["line_id"]: l for l in representative["lines"]}
        for line in stripped_representative["lines"]:
            src = src_lines[line["line_id"]]
            for field in preserved:
                assert line[field] == src[field], (
                    f"Line {line['line_id']}: field '{field}' changed during strip "
                    f"(was {src[field]!r}, now {line[field]!r})"
                )

    def test_adv_non_intent_fields_preserved(self, stripped_adversarial, adversarial):
        """All non-intent fields must survive stripping — adversarial set."""
        preserved = ("line_id", "doc_num", "line_description", "amount", "gst_amount",
                     "vat_group", "business_context", "stratum", "category")
        src_lines = {l["line_id"]: l for l in adversarial["lines"]}
        for line in stripped_adversarial["lines"]:
            src = src_lines[line["line_id"]]
            for field in preserved:
                assert line[field] == src[field], (
                    f"Line {line['line_id']}: field '{field}' changed during strip "
                    f"(was {src[field]!r}, now {line[field]!r})"
                )
