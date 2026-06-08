"""
Structural-only tests for tests/fixtures/reg2627-labelled-lines.DRAFT.json.

These tests verify schema integrity and composition constraints ONLY.
They do NOT verify whether any proposed label is correct against IRAS.
Label correctness is the responsibility of the human reviewer working
through exploration-notes/t2.7-measurement/fixture-review-worksheet.md.

VALIDATION INTEGRITY: No test here may be adjusted to accommodate a
label change that would make a gate pass.  These tests validate the
fixture's structure, not the model's recall or FP rate.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_DRAFT_PATH = (
    Path(__file__).parent / "fixtures" / "reg2627-labelled-lines.DRAFT.json"
)
_TRUSTED_PATH = (
    Path(__file__).parent / "fixtures" / "reg2627-labelled-lines.json"
)

# All valid expected_category values (incl. medical_insurance from the labelling-pass split)
_CATEGORIES = {
    "medical_expenses",     # §6.1.6 item 2 — treatment costs
    "medical_insurance",    # §6.1.6 item 3 — insurance premiums (labelling-pass split)
    "motor_car_s_plate",
    "club_subscriptions",
    "family_benefits",
    "entertainment",
    "other_disallowed",
}

# Categories that must be represented among positives in a complete fixture.
# Omissions:
#   medical_insurance — valid but both items 2+3 may be bucketed under
#                       medical_expenses in the initial DRAFT.
#   entertainment     — §6.1.3 correction: entertainment is claimable per IRAS;
#                       after the labelling pass all entertainment lines are
#                       expected_candidate=False, so it correctly has no positives.
_REQUIRED_CATEGORIES = _CATEGORIES - {"medical_insurance", "entertainment"}

# After the opus-4-8 labelling pass, family_benefits has 8 positives because
# SPOUSE CLUB MBR (2035) was reclassified to club_subscriptions and FAMILY MED
# STAFF (2036) to medical_expenses — both more precise. Floor lowered to 8.
_MIN_POSITIVES_PER_CATEGORY = 8
_MIN_NEGATIVES = 45


@pytest.fixture(scope="module")
def draft() -> dict:
    return json.loads(_DRAFT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lines(draft) -> list[dict]:
    return draft["lines"]


# ---------------------------------------------------------------------------
# T1 — File exists and parses as valid JSON
# ---------------------------------------------------------------------------

class TestFileExists:
    def test_draft_file_exists(self):
        assert _DRAFT_PATH.exists(), (
            f"DRAFT fixture not found at {_DRAFT_PATH}. "
            "Run the fixture generation step first."
        )

    def test_draft_is_valid_json(self):
        data = json.loads(_DRAFT_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_trusted_fixture_unchanged(self):
        """The 18-line trusted fixture must not have been modified."""
        assert _TRUSTED_PATH.exists(), "Trusted fixture reg2627-labelled-lines.json is missing"
        trusted = json.loads(_TRUSTED_PATH.read_text(encoding="utf-8"))
        assert len(trusted["lines"]) == 18, (
            f"Trusted fixture must remain at 18 lines; got {len(trusted['lines'])}. "
            "Do NOT modify the trusted fixture to pass any test."
        )


# ---------------------------------------------------------------------------
# T2 — Meta block present and clearly marked as DRAFT
# ---------------------------------------------------------------------------

class TestMetaBlock:
    def test_meta_present(self, draft):
        assert "_meta" in draft

    def test_proposed_flag_true(self, draft):
        assert draft["_meta"].get("proposed") is True

    def test_ground_truth_set_by_is_draft(self, draft):
        gtsb = draft["_meta"].get("ground_truth_set_by", "")
        assert "DRAFT" in gtsb, (
            "ground_truth_set_by must clearly state DRAFT until human review is complete"
        )

    def test_warning_present(self, draft):
        warning = draft["_meta"].get("warning", "")
        assert len(warning) > 20, "A meaningful warning must be present in _meta"

    def test_labelling_basis_references_iras(self, draft):
        basis = draft["_meta"].get("labelling_basis", [])
        assert len(basis) >= 2, "labelling_basis must cite at least two IRAS sources"
        joined = " ".join(basis)
        assert "§6.1.6" in joined or "6.1.6" in joined


# ---------------------------------------------------------------------------
# T3 — Every line has the required schema fields
# ---------------------------------------------------------------------------

_REQUIRED_LINE_FIELDS = {
    "doc_num", "doc_type", "doc_date", "card_name", "line_index",
    "vat_group", "line_description", "line_total", "tax_total",
    "expected_candidate",
    # DRAFT-specific additions
    "proposed", "needs_human_review", "iras_basis",
    "determinability",
}

class TestLineSchema:
    def test_all_lines_have_required_fields(self, lines):
        for i, line in enumerate(lines):
            missing = _REQUIRED_LINE_FIELDS - set(line.keys())
            assert not missing, (
                f"Line {i} (doc_num={line.get('doc_num')}, "
                f"line_index={line.get('line_index')}) "
                f"is missing fields: {sorted(missing)}"
            )

    def test_vat_group_always_si(self, lines):
        for line in lines:
            assert line["vat_group"] == "SI", (
                f"doc_num={line['doc_num']} line_index={line['line_index']}: "
                f"vat_group must be 'SI', got {line['vat_group']!r}"
            )

    def test_expected_candidate_is_bool(self, lines):
        for line in lines:
            assert isinstance(line["expected_candidate"], bool), (
                f"doc_num={line['doc_num']} line_index={line['line_index']}: "
                f"expected_candidate must be bool, got {type(line['expected_candidate'])}"
            )

    def test_proposed_always_true(self, lines):
        for line in lines:
            assert line.get("proposed") is True, (
                f"doc_num={line['doc_num']} line_index={line['line_index']}: "
                f"proposed must be True on every DRAFT line"
            )

    def test_needs_human_review_is_bool(self, lines):
        for line in lines:
            nhr = line.get("needs_human_review")
            assert isinstance(nhr, bool), (
                f"doc_num={line['doc_num']} line_index={line['line_index']}: "
                f"needs_human_review must be bool, got {type(nhr)}"
            )

    def test_iras_basis_is_nonempty_string(self, lines):
        for line in lines:
            basis = line.get("iras_basis", "")
            assert isinstance(basis, str) and len(basis) > 5, (
                f"doc_num={line['doc_num']} line_index={line['line_index']}: "
                f"iras_basis must be a non-empty string"
            )

    def test_positive_lines_have_expected_category(self, lines):
        for line in lines:
            if line["expected_candidate"]:
                assert "expected_category" in line, (
                    f"doc_num={line['doc_num']} line_index={line['line_index']}: "
                    f"positive line must have expected_category"
                )
                assert line["expected_category"] in _CATEGORIES, (
                    f"doc_num={line['doc_num']} line_index={line['line_index']}: "
                    f"expected_category {line['expected_category']!r} is not a valid category"
                )

    def test_line_total_is_positive_number(self, lines):
        for line in lines:
            assert isinstance(line["line_total"], (int, float)) and line["line_total"] > 0, (
                f"doc_num={line['doc_num']}: line_total must be a positive number"
            )

    def test_tax_total_is_nonnegative(self, lines):
        for line in lines:
            assert isinstance(line["tax_total"], (int, float)) and line["tax_total"] >= 0, (
                f"doc_num={line['doc_num']}: tax_total must be a non-negative number"
            )

    def test_doc_date_format(self, lines):
        import re
        pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for line in lines:
            assert pattern.match(line["doc_date"]), (
                f"doc_num={line['doc_num']}: doc_date {line['doc_date']!r} "
                f"must be YYYY-MM-DD"
            )

    def test_line_description_nonempty(self, lines):
        for line in lines:
            assert isinstance(line["line_description"], str) and len(line["line_description"].strip()) > 0, (
                f"doc_num={line['doc_num']} line_index={line['line_index']}: "
                f"line_description must be a non-empty string"
            )


# ---------------------------------------------------------------------------
# T4 — (doc_num, line_index) uniqueness
# ---------------------------------------------------------------------------

class TestUniqueness:
    def test_doc_num_line_index_pairs_unique(self, lines):
        pairs = [(line["doc_num"], line["line_index"]) for line in lines]
        seen: set = set()
        duplicates: list = []
        for p in pairs:
            if p in seen:
                duplicates.append(p)
            seen.add(p)
        assert not duplicates, (
            f"Duplicate (doc_num, line_index) pairs found: {duplicates}"
        )


# ---------------------------------------------------------------------------
# T5 — Minimum count requirements
# ---------------------------------------------------------------------------

class TestMinimumCounts:
    def test_total_line_count_at_least_100(self, lines):
        assert len(lines) >= 100, (
            f"Expected at least 100 lines in the DRAFT fixture; got {len(lines)}"
        )

    def test_minimum_negatives(self, lines):
        negatives = [ln for ln in lines if not ln["expected_candidate"]]
        assert len(negatives) >= _MIN_NEGATIVES, (
            f"Expected at least {_MIN_NEGATIVES} negative lines; "
            f"got {len(negatives)}"
        )

    def test_all_six_categories_present_among_positives(self, lines):
        positives = [ln for ln in lines if ln["expected_candidate"]]
        present = {ln["expected_category"] for ln in positives}
        missing = _REQUIRED_CATEGORIES - present
        assert not missing, (
            f"Missing categories among positives: {sorted(missing)}"
        )

    def test_minimum_positives_per_category(self, lines):
        positives = [ln for ln in lines if ln["expected_candidate"]]
        from collections import Counter
        counts = Counter(ln["expected_category"] for ln in positives)
        below_floor = {
            cat: counts[cat]
            for cat in _REQUIRED_CATEGORIES
            if counts[cat] < _MIN_POSITIVES_PER_CATEGORY
        }
        assert not below_floor, (
            f"Categories below {_MIN_POSITIVES_PER_CATEGORY} positives: {below_floor}"
        )


# ---------------------------------------------------------------------------
# T6 — needs_human_review present on all lines (schema completeness)
# ---------------------------------------------------------------------------

class TestNeedsHumanReviewPresent:
    def test_needs_human_review_on_every_line(self, lines):
        """Structural: field must be present and bool on every line."""
        missing_nhr = [
            (ln["doc_num"], ln["line_index"])
            for ln in lines
            if "needs_human_review" not in ln
            or not isinstance(ln["needs_human_review"], bool)
        ]
        assert not missing_nhr, (
            f"Lines missing valid needs_human_review: {missing_nhr}"
        )

    def test_some_lines_flagged_for_review(self, lines):
        """Sanity: at least some lines should require human review (ambiguous cases)."""
        flagged = [ln for ln in lines if ln.get("needs_human_review") is True]
        assert len(flagged) >= 5, (
            f"Expected at least 5 lines flagged for human review; got {len(flagged)}. "
            "Hard boundary cases must be flagged."
        )


# ---------------------------------------------------------------------------
# T7 — DRAFT / trusted fixture isolation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# T8 — determinability field (new in T2.7 determinability-axis refactor)
# ---------------------------------------------------------------------------

_VALID_DETERMINABILITY = {"determinable", "indeterminate"}


class TestDeterminability:
    """Verify that every DRAFT fixture line has a valid determinability field
    and that the _meta block carries the required provisional note."""

    def test_fixture_note_in_meta(self, draft):
        note = draft["_meta"].get("fixture_note", "")
        assert isinstance(note, str) and len(note) > 20, (
            "_meta must contain a non-empty 'fixture_note' documenting that "
            "determinability values are provisional"
        )

    def test_fixture_note_mentions_provisional(self, draft):
        note = draft["_meta"].get("fixture_note", "").lower()
        assert "provisional" in note, (
            "fixture_note must state that determinability values are provisional"
        )

    def test_all_lines_have_determinability(self, lines):
        missing = [
            (ln["doc_num"], ln["line_index"])
            for ln in lines
            if "determinability" not in ln
        ]
        assert not missing, f"Lines missing 'determinability' field: {missing}"

    def test_all_determinability_values_valid(self, lines):
        invalid = [
            (ln["doc_num"], ln["line_index"], ln.get("determinability"))
            for ln in lines
            if ln.get("determinability") not in _VALID_DETERMINABILITY
        ]
        assert not invalid, (
            f"Lines with invalid determinability (must be one of "
            f"{sorted(_VALID_DETERMINABILITY)}): {invalid}"
        )

    def test_determinability_is_string(self, lines):
        bad = [
            (ln["doc_num"], ln["line_index"])
            for ln in lines
            if not isinstance(ln.get("determinability"), str)
        ]
        assert not bad, f"Lines where determinability is not a string: {bad}"

    def test_at_least_one_determinable(self, lines):
        det = [ln for ln in lines if ln.get("determinability") == "determinable"]
        assert len(det) >= 1, "At least one line must be determinable"


# ---------------------------------------------------------------------------
# T9 — LLM input leakage guard (tested against the REAL DRAFT fixture)
# ---------------------------------------------------------------------------

# Mirrors _LLM_INPUT_FIELDS in run_measurement.py — the only fields the model
# is allowed to see.  Keep these two in sync.
_LLM_ALLOW = frozenset({
    "doc_num", "doc_type", "doc_date", "card_name",
    "line_index", "vat_group", "line_description",
    "line_total", "tax_total",
})

# Fields that encode the ground-truth answer and must NEVER reach the LLM.
_FORBIDDEN_LLM_FIELDS = frozenset({
    "expected_candidate",
    "expected_category",
    "determinability",
    "needs_human_review",
    "proposed",
    "iras_basis",
    "_label_note",
})


def _strip_to_llm_input(line: dict) -> dict:
    """Apply the same allow-list as run_measurement._load_fixture."""
    return {k: line[k] for k in _LLM_ALLOW if k in line}


class TestLLMInputLeakage:
    """Verify that the LLM input path contains no annotation or ground-truth fields.

    These tests must FAIL if any forbidden field is reintroduced into the
    allow-list or if the stripping logic reverts to a deny-list approach.

    VALIDATION INTEGRITY: Do not weaken these assertions.
    """

    @pytest.fixture(scope="class")
    def si_lines(self, lines):
        return [_strip_to_llm_input(ln) for ln in lines]

    def test_no_expected_candidate_in_llm_input(self, si_lines):
        leaking = [ln for ln in si_lines if "expected_candidate" in ln]
        assert not leaking, (
            f"{len(leaking)} LLM-input line(s) contain 'expected_candidate' (ground truth)"
        )

    def test_no_expected_category_in_llm_input(self, si_lines):
        leaking = [ln for ln in si_lines if "expected_category" in ln]
        assert not leaking, (
            f"{len(leaking)} LLM-input line(s) contain 'expected_category' (ground truth)"
        )

    def test_no_determinability_in_llm_input(self, si_lines):
        leaking = [ln for ln in si_lines if "determinability" in ln]
        assert not leaking, (
            f"{len(leaking)} LLM-input line(s) contain 'determinability' (annotation)"
        )

    def test_no_needs_human_review_in_llm_input(self, si_lines):
        leaking = [ln for ln in si_lines if "needs_human_review" in ln]
        assert not leaking, (
            f"{len(leaking)} LLM-input line(s) contain 'needs_human_review' "
            "(answer-encoding annotation)"
        )

    def test_no_proposed_in_llm_input(self, si_lines):
        leaking = [ln for ln in si_lines if "proposed" in ln]
        assert not leaking, (
            f"{len(leaking)} LLM-input line(s) contain 'proposed' (annotation)"
        )

    def test_no_iras_basis_in_llm_input(self, si_lines):
        leaking = [ln for ln in si_lines if "iras_basis" in ln]
        assert not leaking, (
            f"{len(leaking)} LLM-input line(s) contain 'iras_basis' "
            "(answer-encoding annotation)"
        )

    def test_no_label_note_in_llm_input(self, si_lines):
        leaking = [ln for ln in si_lines if "_label_note" in ln]
        assert not leaking, (
            f"{len(leaking)} LLM-input line(s) contain '_label_note' (annotation)"
        )

    def test_no_forbidden_fields_at_all(self, si_lines):
        """Catch-all: none of the forbidden fields appear in any LLM-input line."""
        violations: list[tuple] = []
        for ln in si_lines:
            leaked = _FORBIDDEN_LLM_FIELDS & set(ln.keys())
            if leaked:
                violations.append((ln.get("doc_num"), ln.get("line_index"), sorted(leaked)))
        assert not violations, (
            f"Ground-truth / annotation fields leaked into LLM input: {violations}"
        )

    def test_llm_input_contains_only_allowed_fields(self, si_lines):
        """Positive assertion: every key in every LLM-input line is in the allow-list."""
        violations: list[tuple] = []
        for ln in si_lines:
            extra = set(ln.keys()) - _LLM_ALLOW
            if extra:
                violations.append((ln.get("doc_num"), ln.get("line_index"), sorted(extra)))
        assert not violations, (
            f"Unexpected fields in LLM input (not in allow-list): {violations}"
        )

    def test_llm_input_has_expected_observable_fields(self, si_lines):
        """Every LLM-input line contains the core observable SI fields."""
        required = {"doc_num", "line_index", "vat_group", "line_description",
                    "line_total", "tax_total"}
        missing: list[tuple] = []
        for ln in si_lines:
            absent = required - set(ln.keys())
            if absent:
                missing.append((ln.get("doc_num"), sorted(absent)))
        assert not missing, f"LLM-input lines missing core observable fields: {missing}"

    def test_llm_input_line_count_matches_fixture(self, lines, si_lines):
        assert len(si_lines) == len(lines), (
            "Stripped LLM-input list must have same length as full fixture"
        )


class TestIsolation:
    def test_draft_doc_nums_do_not_overlap_trusted(self):
        """DRAFT lines must use different doc_nums than the 18-line trusted fixture."""
        trusted = json.loads(_TRUSTED_PATH.read_text(encoding="utf-8"))
        trusted_nums = {ln["doc_num"] for ln in trusted["lines"]}
        draft = json.loads(_DRAFT_PATH.read_text(encoding="utf-8"))
        draft_nums = {ln["doc_num"] for ln in draft["lines"]}
        overlap = trusted_nums & draft_nums
        assert not overlap, (
            f"DRAFT fixture doc_nums overlap with trusted fixture: {sorted(overlap)}. "
            "DRAFT lines must use distinct doc_nums to avoid measurement confusion."
        )
