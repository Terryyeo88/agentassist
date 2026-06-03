"""
Tests for reasoning/measurement.py — deterministic scorer.

No API calls, no SAP, no I/O.  All inputs are hand-built in this file with
known TP/FP/FN/TN values so expected scores are computed analytically.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from reasoning.measurement import score

# ---------------------------------------------------------------------------
# Helpers — minimal line/candidate builders
# ---------------------------------------------------------------------------

def _line(
    doc_num: int,
    line_index: int,
    expected_candidate: bool,
    expected_category: str | None = None,
    line_description: str = "test line",
) -> dict:
    d: dict = {
        "doc_num": doc_num,
        "line_index": line_index,
        "line_description": line_description,
        "vat_group": "SI",
        "expected_candidate": expected_candidate,
    }
    if expected_candidate and expected_category is not None:
        d["expected_category"] = expected_category
    return d


def _candidate(
    doc_num: int,
    line_index: int,
    suspected_category: str = "medical_expenses",
) -> dict:
    return {
        "doc_num": doc_num,
        "line_index": line_index,
        "suspected_category": suspected_category,
        "phrasing": "Consider reviewing whether this is disallowed.",
        "confidence": "high",
    }


# ---------------------------------------------------------------------------
# T1 — Basic scoring with known TP/FP/FN/TN
# ---------------------------------------------------------------------------

class TestBasicScoring:
    """
    Labelled set: pos=(1,0), pos=(2,0), pos=(3,0), neg=(4,0), neg=(5,0), neg=(6,0)
    Predicted:    (1,0)→TP  (3,0)→TP  (5,0)→FP
    Expected:     tp=2  fn=1  fp=1  tn=2
    recall = 2/(2+1) = 0.667
    fp_rate = 1/(1+2) = 0.333
    """

    @pytest.fixture
    def labelled(self):
        return [
            _line(1, 0, True,  "medical_expenses"),
            _line(2, 0, True,  "club_subscriptions"),
            _line(3, 0, True,  "motor_car_s_plate"),
            _line(4, 0, False),
            _line(5, 0, False),
            _line(6, 0, False),
        ]

    @pytest.fixture
    def predicted(self):
        return [
            _candidate(1, 0, "medical_expenses"),   # TP + correct category
            _candidate(3, 0, "entertainment"),       # TP + wrong category
            _candidate(5, 0, "club_subscriptions"),  # FP
        ]

    def test_tp(self, labelled, predicted):
        assert score(predicted, labelled)["tp"] == 2

    def test_fp(self, labelled, predicted):
        assert score(predicted, labelled)["fp"] == 1

    def test_fn(self, labelled, predicted):
        assert score(predicted, labelled)["fn"] == 1

    def test_tn(self, labelled, predicted):
        assert score(predicted, labelled)["tn"] == 2

    def test_recall(self, labelled, predicted):
        result = score(predicted, labelled)
        assert abs(result["recall"] - 2/3) < 1e-5

    def test_fp_rate(self, labelled, predicted):
        result = score(predicted, labelled)
        assert abs(result["fp_rate"] - 1/3) < 1e-5

    def test_category_accuracy(self, labelled, predicted):
        # 2 TPs: (1,0) correct, (3,0) wrong → accuracy = 0.5
        result = score(predicted, labelled)
        assert abs(result["category_accuracy"] - 0.5) < 1e-5

    def test_per_line_length(self, labelled, predicted):
        result = score(predicted, labelled)
        assert len(result["per_line"]) == 6

    def test_per_line_dispositions(self, labelled, predicted):
        per = {(r["doc_num"], r["line_index"]): r["disposition"]
               for r in score(predicted, labelled)["per_line"]}
        assert per[(1, 0)] == "TP"
        assert per[(2, 0)] == "FN"
        assert per[(3, 0)] == "TP"
        assert per[(4, 0)] == "TN"
        assert per[(5, 0)] == "FP"
        assert per[(6, 0)] == "TN"


# ---------------------------------------------------------------------------
# T2 — Edge: zero positives in labelled set (no recall denominator)
# ---------------------------------------------------------------------------

class TestZeroPositives:
    @pytest.fixture
    def labelled(self):
        return [_line(1, 0, False), _line(2, 0, False)]

    def test_recall_zero_when_no_positives(self, labelled):
        # tp+fn==0 (no positives at all) → recall denominator is 0 → None
        assert score([], labelled)["recall"] is None

    def test_fp_rate_correct_when_no_positives_but_predicted(self, labelled):
        predicted = [_candidate(1, 0)]
        result = score(predicted, labelled)
        # fp=1, tn=1 → fp_rate = 0.5
        assert abs(result["fp_rate"] - 0.5) < 1e-5

    def test_category_accuracy_zero_when_no_tps(self, labelled):
        predicted = [_candidate(1, 0)]
        assert score(predicted, labelled)["category_accuracy"] == 0.0


# ---------------------------------------------------------------------------
# T3 — Edge: zero predictions
# ---------------------------------------------------------------------------

class TestZeroPredictions:
    @pytest.fixture
    def labelled(self):
        return [
            _line(1, 0, True,  "medical_expenses"),
            _line(2, 0, False),
        ]

    def test_recall_zero_when_nothing_predicted(self, labelled):
        assert score([], labelled)["recall"] == 0.0

    def test_fp_rate_zero_when_nothing_predicted(self, labelled):
        assert score([], labelled)["fp_rate"] == 0.0

    def test_fn_equals_number_of_positives(self, labelled):
        result = score([], labelled)
        assert result["fn"] == 1
        assert result["tn"] == 1

    def test_tp_fp_zero(self, labelled):
        result = score([], labelled)
        assert result["tp"] == 0
        assert result["fp"] == 0


# ---------------------------------------------------------------------------
# T4 — Edge: all correct (perfect recall, zero FP)
# ---------------------------------------------------------------------------

class TestAllCorrect:
    @pytest.fixture
    def labelled(self):
        return [
            _line(1, 0, True,  "club_subscriptions"),
            _line(2, 0, True,  "motor_car_s_plate"),
            _line(3, 0, False),
            _line(4, 0, False),
        ]

    @pytest.fixture
    def predicted(self):
        return [
            _candidate(1, 0, "club_subscriptions"),
            _candidate(2, 0, "motor_car_s_plate"),
        ]

    def test_perfect_recall(self, labelled, predicted):
        assert score(predicted, labelled)["recall"] == 1.0

    def test_zero_fp_rate(self, labelled, predicted):
        assert score(predicted, labelled)["fp_rate"] == 0.0

    def test_perfect_category_accuracy(self, labelled, predicted):
        assert score(predicted, labelled)["category_accuracy"] == 1.0

    def test_confusion_matrix(self, labelled, predicted):
        result = score(predicted, labelled)
        assert result["tp"] == 2
        assert result["fp"] == 0
        assert result["fn"] == 0
        assert result["tn"] == 2


# ---------------------------------------------------------------------------
# T5 — Edge: all wrong (flags only negatives, misses all positives)
# ---------------------------------------------------------------------------

class TestAllWrong:
    @pytest.fixture
    def labelled(self):
        return [
            _line(1, 0, True,  "medical_expenses"),
            _line(2, 0, True,  "entertainment"),
            _line(3, 0, False),
            _line(4, 0, False),
        ]

    @pytest.fixture
    def predicted(self):
        return [
            _candidate(3, 0),  # FP
            _candidate(4, 0),  # FP
        ]

    def test_zero_recall(self, labelled, predicted):
        assert score(predicted, labelled)["recall"] == 0.0

    def test_full_fp_rate(self, labelled, predicted):
        # fp=2, tn=0 → fp_rate=1.0
        assert score(predicted, labelled)["fp_rate"] == 1.0

    def test_zero_category_accuracy(self, labelled, predicted):
        assert score(predicted, labelled)["category_accuracy"] == 0.0

    def test_confusion_matrix(self, labelled, predicted):
        result = score(predicted, labelled)
        assert result["tp"] == 0
        assert result["fp"] == 2
        assert result["fn"] == 2
        assert result["tn"] == 0


# ---------------------------------------------------------------------------
# T6 — Structural matching: rename description, scoring unchanged
# ---------------------------------------------------------------------------

class TestStructuralMatching:
    """Matching is on (doc_num, line_index) ONLY.  Text fields are irrelevant."""

    def test_different_description_same_key_still_matches(self):
        labelled = [_line(10, 2, True, "medical_expenses",
                           line_description="Original description from fixture")]
        predicted = [_candidate(10, 2, "medical_expenses")]
        # Change description in predicted candidate — should still be TP
        predicted[0]["line_description"] = "Completely different text"
        result = score(predicted, labelled)
        assert result["tp"] == 1
        assert result["recall"] == 1.0

    def test_same_description_different_key_does_not_match(self):
        labelled = [_line(10, 2, True, "medical_expenses",
                           line_description="Annual health screening")]
        predicted = [_candidate(10, 3, "medical_expenses")]  # line_index differs
        predicted[0]["line_description"] = "Annual health screening"  # same text
        result = score(predicted, labelled)
        # No match: (10,3) != (10,2) → FN + out-of-fixture prediction
        assert result["fn"] == 1
        assert result["tp"] == 0

    def test_same_doc_num_different_line_index_is_distinct(self):
        labelled = [
            _line(20, 0, True,  "club_subscriptions"),
            _line(20, 1, False),
        ]
        predicted = [_candidate(20, 1, "club_subscriptions")]  # predicts line 1 (negative)
        result = score(predicted, labelled)
        assert result["tp"] == 0
        assert result["fp"] == 1
        assert result["fn"] == 1


# ---------------------------------------------------------------------------
# T7 — Out-of-fixture predictions are counted but not scored
# ---------------------------------------------------------------------------

class TestOutOfFixture:
    def test_out_of_fixture_count_nonzero(self):
        labelled = [_line(1, 0, True, "medical_expenses")]
        predicted = [
            _candidate(1, 0, "medical_expenses"),   # in fixture → TP
            _candidate(999, 5, "entertainment"),    # NOT in fixture → out-of-fixture
        ]
        result = score(predicted, labelled)
        assert result["out_of_fixture_predictions"] == 1
        # Only the in-fixture prediction is scored
        assert result["tp"] == 1
        assert result["fp"] == 0

    def test_out_of_fixture_zero_when_all_within_fixture(self):
        labelled = [_line(1, 0, False)]
        predicted = [_candidate(1, 0)]
        assert score(predicted, labelled)["out_of_fixture_predictions"] == 0


# ---------------------------------------------------------------------------
# T8 — Category accuracy detail
# ---------------------------------------------------------------------------

class TestCategoryAccuracy:
    def test_all_categories_correct(self):
        labelled = [
            _line(1, 0, True, "club_subscriptions"),
            _line(2, 0, True, "motor_car_s_plate"),
        ]
        predicted = [
            _candidate(1, 0, "club_subscriptions"),
            _candidate(2, 0, "motor_car_s_plate"),
        ]
        assert score(predicted, labelled)["category_accuracy"] == 1.0

    def test_no_categories_correct(self):
        labelled = [
            _line(1, 0, True, "club_subscriptions"),
            _line(2, 0, True, "motor_car_s_plate"),
        ]
        predicted = [
            _candidate(1, 0, "entertainment"),
            _candidate(2, 0, "family_benefits"),
        ]
        assert score(predicted, labelled)["category_accuracy"] == 0.0

    def test_partial_category_accuracy(self):
        labelled = [
            _line(1, 0, True, "club_subscriptions"),
            _line(2, 0, True, "medical_expenses"),
            _line(3, 0, True, "entertainment"),
        ]
        predicted = [
            _candidate(1, 0, "club_subscriptions"),   # correct
            _candidate(2, 0, "motor_car_s_plate"),    # wrong
            _candidate(3, 0, "entertainment"),         # correct
        ]
        result = score(predicted, labelled)
        # 2 out of 3 TPs have correct category → 0.6667
        assert abs(result["category_accuracy"] - 2/3) < 1e-5

    def test_category_correct_flag_in_per_line(self):
        labelled = [_line(1, 0, True, "medical_expenses")]
        predicted = [_candidate(1, 0, "medical_expenses")]
        per = score(predicted, labelled)["per_line"][0]
        assert per["category_correct"] is True

    def test_category_wrong_flag_in_per_line(self):
        labelled = [_line(1, 0, True, "medical_expenses")]
        predicted = [_candidate(1, 0, "entertainment")]
        per = score(predicted, labelled)["per_line"][0]
        assert per["category_correct"] is False

    def test_category_correct_none_for_fn(self):
        labelled = [_line(1, 0, True, "medical_expenses")]
        per = score([], labelled)["per_line"][0]
        assert per["disposition"] == "FN"
        assert per["category_correct"] is None

    def test_category_correct_none_for_fp(self):
        labelled = [_line(1, 0, False)]
        predicted = [_candidate(1, 0)]
        per = score(predicted, labelled)["per_line"][0]
        assert per["disposition"] == "FP"
        assert per["category_correct"] is None

    def test_category_correct_none_for_tn(self):
        labelled = [_line(1, 0, False)]
        per = score([], labelled)["per_line"][0]
        assert per["disposition"] == "TN"
        assert per["category_correct"] is None


# ---------------------------------------------------------------------------
# T9 — per_line fields
# ---------------------------------------------------------------------------

class TestPerLineFields:
    def test_per_line_has_all_required_fields(self):
        labelled = [_line(5, 3, True, "entertainment")]
        predicted = [_candidate(5, 3, "entertainment")]
        per = score(predicted, labelled)["per_line"][0]
        for field in ("doc_num", "line_index", "line_description",
                      "expected_candidate", "expected_category",
                      "predicted", "predicted_category",
                      "disposition", "category_correct"):
            assert field in per, f"Missing per_line field: {field}"

    def test_per_line_doc_num_and_line_index_are_ints(self):
        labelled = [_line(7, 2, False)]
        per = score([], labelled)["per_line"][0]
        assert isinstance(per["doc_num"], int)
        assert isinstance(per["line_index"], int)

    def test_per_line_predicted_false_for_tn(self):
        labelled = [_line(1, 0, False)]
        per = score([], labelled)["per_line"][0]
        assert per["predicted"] is False

    def test_per_line_predicted_true_for_fp(self):
        labelled = [_line(1, 0, False)]
        predicted = [_candidate(1, 0)]
        per = score(predicted, labelled)["per_line"][0]
        assert per["predicted"] is True


# ---------------------------------------------------------------------------
# T10 — Full fixture sanity check (structural only — no actual LLM)
# ---------------------------------------------------------------------------

class TestFixtureStructure:
    """Verify the labelled fixture file has the expected structure."""

    FIXTURE = Path(__file__).parent / "fixtures" / "reg2627-labelled-lines.json"

    def test_fixture_file_exists(self):
        assert self.FIXTURE.exists()

    def test_fixture_loads(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        assert "lines" in data

    def test_fixture_line_count(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        assert len(data["lines"]) == 18

    def test_fixture_positive_count(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        positives = [l for l in data["lines"] if l["expected_candidate"]]
        assert len(positives) == 8

    def test_fixture_negative_count(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        negatives = [l for l in data["lines"] if not l["expected_candidate"]]
        assert len(negatives) == 10

    def test_all_positives_have_expected_category(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        for line in data["lines"]:
            if line["expected_candidate"]:
                assert "expected_category" in line, (
                    f"Positive line {line['doc_num']} missing expected_category"
                )

    def test_all_lines_have_required_shape_fields(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        required = {"doc_num", "doc_type", "doc_date", "card_name",
                    "line_index", "vat_group", "line_description",
                    "line_total", "tax_total"}
        for line in data["lines"]:
            missing = required - set(line.keys())
            assert not missing, (
                f"Line {line.get('doc_num')} missing: {missing}"
            )

    def test_all_lines_vat_group_SI(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        for line in data["lines"]:
            assert line["vat_group"] == "SI"

    def test_doc_num_line_index_pairs_unique(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        pairs = [(l["doc_num"], l["line_index"]) for l in data["lines"]]
        assert len(pairs) == len(set(pairs)), "Duplicate (doc_num, line_index) pairs"

    def test_expected_categories_are_valid(self):
        valid = {"medical_expenses", "medical_insurance", "motor_car_s_plate",
                 "club_subscriptions", "family_benefits", "entertainment", "other_disallowed"}
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        for line in data["lines"]:
            cat = line.get("expected_category")
            if cat is not None:
                assert cat in valid, f"Unknown expected_category: {cat!r}"

    def test_per_category_present_in_result(self):
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        lines = data["lines"]
        result = score([], lines)
        assert "per_category" in result

    def test_score_on_perfect_predictions_gives_recall_1(self):
        """If we predict exactly the positives, recall==1 and fp_rate==0."""
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        lines = data["lines"]
        perfect_preds = [
            {
                "doc_num": l["doc_num"],
                "line_index": l["line_index"],
                "suspected_category": l.get("expected_category", "other_disallowed"),
            }
            for l in lines if l["expected_candidate"]
        ]
        result = score(perfect_preds, lines)
        assert result["recall"] == 1.0
        assert result["fp_rate"] == 0.0
        assert result["tp"] == 8
        assert result["fn"] == 0
        assert result["tn"] == 10
        assert result["fp"] == 0


# ---------------------------------------------------------------------------
# T11 — per_category breakdown
# ---------------------------------------------------------------------------
#
# Hand-built fixture (6 lines) with deterministic known values:
#
#   (1,0) pos  medical_expenses      → predicted TP
#   (2,0) pos  medical_expenses      → not predicted FN
#   (3,0) pos  club_subscriptions    → predicted TP
#   (4,0) neg  expected_category=medical_expenses  → predicted FP
#   (5,0) neg  (no category → n/a)   → not predicted TN
#   (6,0) neg  (no category → n/a)   → predicted FP
#
# Expected per-category:
#   medical_expenses:    sp=2 sn=1  tp=1 fn=1 fp=1  recall=0.5   fp_rate=1.0
#   club_subscriptions:  sp=1 sn=0  tp=1 fn=0 fp=0  recall=1.0   fp_rate=0.0
#   n/a:                 sp=0 sn=2  tp=0 fn=0 fp=1  recall=0.0   fp_rate=0.5
# ---------------------------------------------------------------------------

class TestPerCategory:

    @pytest.fixture
    def labelled(self):
        return [
            _line(1, 0, True,  "medical_expenses"),
            _line(2, 0, True,  "medical_expenses"),
            _line(3, 0, True,  "club_subscriptions"),
            # negative WITH expected_category
            {
                "doc_num": 4, "line_index": 0,
                "expected_candidate": False,
                "expected_category": "medical_expenses",
                "line_description": "neg bucketed to medical",
                "vat_group": "SI",
            },
            _line(5, 0, False),   # n/a (no expected_category)
            _line(6, 0, False),   # n/a
        ]

    @pytest.fixture
    def predicted(self):
        return [
            _candidate(1, 0, "medical_expenses"),    # TP on medical
            _candidate(3, 0, "club_subscriptions"),  # TP on club
            _candidate(4, 0, "medical_expenses"),    # FP on medical negative
            _candidate(6, 0, "club_subscriptions"),  # FP on n/a negative
        ]

    @pytest.fixture
    def result(self, labelled, predicted):
        return score(predicted, labelled)

    # ── presence / structure ────────────────────────────────────────────────

    def test_per_category_key_present(self, result):
        assert "per_category" in result

    def test_per_category_has_correct_buckets(self, result):
        assert set(result["per_category"].keys()) == {
            "medical_expenses", "club_subscriptions", "n/a"
        }

    def test_per_category_entry_has_all_required_keys(self, result):
        required = {"tp", "fp", "fn", "recall", "fp_rate",
                    "support_positive", "support_negative",
                    "indeterminate_surface_rate", "indeterminate_support"}
        for cat, entry in result["per_category"].items():
            missing = required - set(entry.keys())
            assert not missing, f"Category {cat!r} missing keys: {missing}"

    def test_per_category_sorted_alphabetically(self, result):
        keys = list(result["per_category"].keys())
        assert keys == sorted(keys)

    # ── medical_expenses (sp=2, sn=1, tp=1, fn=1, fp=1) ────────────────────

    def test_medical_tp(self, result):
        assert result["per_category"]["medical_expenses"]["tp"] == 1

    def test_medical_fn(self, result):
        assert result["per_category"]["medical_expenses"]["fn"] == 1

    def test_medical_fp(self, result):
        assert result["per_category"]["medical_expenses"]["fp"] == 1

    def test_medical_support_positive(self, result):
        assert result["per_category"]["medical_expenses"]["support_positive"] == 2

    def test_medical_support_negative(self, result):
        assert result["per_category"]["medical_expenses"]["support_negative"] == 1

    def test_medical_recall(self, result):
        assert abs(result["per_category"]["medical_expenses"]["recall"] - 0.5) < 1e-5

    def test_medical_fp_rate(self, result):
        assert abs(result["per_category"]["medical_expenses"]["fp_rate"] - 1.0) < 1e-5

    # ── club_subscriptions (sp=1, sn=0, tp=1, fn=0, fp=0) ──────────────────

    def test_club_recall_perfect(self, result):
        assert result["per_category"]["club_subscriptions"]["recall"] == 1.0

    def test_club_fp_rate_zero_no_negatives(self, result):
        # sn=0 → fp_rate denominator is 0 → None (not ZeroDivisionError)
        assert result["per_category"]["club_subscriptions"]["fp_rate"] is None

    def test_club_support_negative_zero(self, result):
        assert result["per_category"]["club_subscriptions"]["support_negative"] == 0

    # ── n/a (sp=0, sn=2, tp=0, fn=0, fp=1) ─────────────────────────────────

    def test_na_recall_zero_no_positives(self, result):
        # sp=0 → recall denominator is 0 → None (not ZeroDivisionError)
        assert result["per_category"]["n/a"]["recall"] is None

    def test_na_fp_rate(self, result):
        assert abs(result["per_category"]["n/a"]["fp_rate"] - 0.5) < 1e-5

    def test_na_support_positive_zero(self, result):
        assert result["per_category"]["n/a"]["support_positive"] == 0

    def test_na_fp(self, result):
        assert result["per_category"]["n/a"]["fp"] == 1

    # ── top-level fields unchanged ───────────────────────────────────────────

    def test_existing_top_level_fields_all_present(self, result):
        for key in ("tp", "fp", "fn", "tn", "recall", "fp_rate",
                    "category_accuracy", "per_line", "out_of_fixture_predictions",
                    "determinable_support", "indeterminate"):
            assert key in result, f"Top-level key {key!r} missing after per_category added"

    def test_overall_tp_unaffected(self, result):
        assert result["tp"] == 2

    def test_overall_fp_unaffected(self, result):
        assert result["fp"] == 2

    # ── edge: category absent from fixture doesn't appear ───────────────────

    def test_only_represented_categories_in_per_category(self):
        labelled = [
            _line(1, 0, True, "medical_expenses"),
            _line(2, 0, False),
        ]
        result = score([], labelled)
        assert "club_subscriptions" not in result["per_category"]
        assert "motor_car_s_plate" not in result["per_category"]

    # ── edge: all predictions wrong within a category ───────────────────────

    def test_perfect_miss_gives_zero_recall(self):
        labelled = [
            _line(1, 0, True, "entertainment"),
            _line(2, 0, True, "entertainment"),
        ]
        result = score([], labelled)
        assert result["per_category"]["entertainment"]["recall"] == 0.0
        assert result["per_category"]["entertainment"]["tp"] == 0
        assert result["per_category"]["entertainment"]["fn"] == 2

    # ── edge: perfect within one category ───────────────────────────────────

    def test_perfect_recall_within_category(self):
        labelled = [
            _line(1, 0, True, "other_disallowed"),
            _line(2, 0, True, "other_disallowed"),
            _line(3, 0, False),
        ]
        predicted = [
            _candidate(1, 0, "other_disallowed"),
            _candidate(2, 0, "other_disallowed"),
        ]
        result = score(predicted, labelled)
        assert result["per_category"]["other_disallowed"]["recall"] == 1.0
        # sn=0 for other_disallowed (line 3 goes to n/a) → fp_rate denominator=0 → None
        assert result["per_category"]["other_disallowed"]["fp_rate"] is None


# ---------------------------------------------------------------------------
# T12 — validate_fixture_lines
# ---------------------------------------------------------------------------

class TestValidateFixtureLines:
    """Tests for the fixture schema validator."""

    def _import(self):
        from reasoning.measurement import validate_fixture_lines
        return validate_fixture_lines

    def test_valid_determinable_passes(self):
        vfl = self._import()
        vfl([{"doc_num": 1, "line_index": 0, "determinability": "determinable"}])

    def test_valid_indeterminate_passes(self):
        vfl = self._import()
        vfl([{"doc_num": 1, "line_index": 0, "determinability": "indeterminate"}])

    def test_both_valid_values_in_same_list(self):
        vfl = self._import()
        vfl([
            {"doc_num": 1, "line_index": 0, "determinability": "determinable"},
            {"doc_num": 2, "line_index": 0, "determinability": "indeterminate"},
        ])

    def test_missing_determinability_raises_valueerror(self):
        vfl = self._import()
        with pytest.raises(ValueError, match="determinability"):
            vfl([{"doc_num": 1, "line_index": 0}])

    def test_invalid_determinability_raises_valueerror(self):
        vfl = self._import()
        with pytest.raises(ValueError, match="determinability"):
            vfl([{"doc_num": 1, "line_index": 0, "determinability": "unknown_value"}])

    def test_none_determinability_raises_valueerror(self):
        vfl = self._import()
        with pytest.raises(ValueError):
            vfl([{"doc_num": 1, "line_index": 0, "determinability": None}])

    def test_error_message_includes_doc_num(self):
        vfl = self._import()
        with pytest.raises(ValueError, match="doc_num=42"):
            vfl([{"doc_num": 42, "line_index": 3}])

    def test_first_invalid_line_triggers_error(self):
        vfl = self._import()
        with pytest.raises(ValueError):
            vfl([
                {"doc_num": 1, "line_index": 0, "determinability": "determinable"},
                {"doc_num": 2, "line_index": 0},  # missing
            ])

    def test_empty_list_passes(self):
        vfl = self._import()
        vfl([])  # no lines → nothing to validate


# ---------------------------------------------------------------------------
# T13 — Determinability axis in score()
# ---------------------------------------------------------------------------
#
# Synthetic mini-fixtures with explicit determinability.
# No API calls, no file I/O.
#
# Coverage:
#   A. Determinable-positive: surfaced→TP, not-surfaced→FN
#   B. Determinable-negative: surfaced→FP, not-surfaced→TN
#   C. Indeterminate: counted only in surface_rate; excluded from recall/fp_rate
#   D. Zero-denominator: returns None without raising
#   E. Mixed-category fixture: correct per_category splits
# ---------------------------------------------------------------------------

def _det_line(
    doc_num: int,
    line_index: int,
    expected_candidate: bool,
    expected_category: str | None = None,
    determinability: str = "determinable",
    line_description: str = "test line",
) -> dict:
    d: dict = {
        "doc_num": doc_num,
        "line_index": line_index,
        "line_description": line_description,
        "vat_group": "SI",
        "expected_candidate": expected_candidate,
        "determinability": determinability,
    }
    if expected_candidate and expected_category is not None:
        d["expected_category"] = expected_category
    return d


class TestDeterminabilityA:
    """A — determinable positives → TP / FN."""

    def test_determinable_positive_surfaced_is_tp(self):
        labelled = [_det_line(1, 0, True, "club_subscriptions")]
        predicted = [_candidate(1, 0, "club_subscriptions")]
        r = score(predicted, labelled)
        assert r["tp"] == 1
        assert r["fn"] == 0

    def test_determinable_positive_not_surfaced_is_fn(self):
        labelled = [_det_line(1, 0, True, "club_subscriptions")]
        r = score([], labelled)
        assert r["fn"] == 1
        assert r["tp"] == 0

    def test_determinable_positive_tp_contributes_to_recall(self):
        labelled = [
            _det_line(1, 0, True, "medical_expenses"),
            _det_line(2, 0, True, "medical_expenses"),
        ]
        predicted = [_candidate(1, 0)]   # 1 of 2 surfaced
        r = score(predicted, labelled)
        assert abs(r["recall"] - 0.5) < 1e-5

    def test_determinable_positive_fn_counted_against_recall(self):
        labelled = [
            _det_line(1, 0, True, "entertainment"),
            _det_line(2, 0, True, "entertainment"),
        ]
        r = score([], labelled)
        assert r["recall"] == 0.0
        assert r["fn"] == 2


class TestDeterminabilityB:
    """B — determinable negatives → FP / TN."""

    def test_determinable_negative_surfaced_is_fp(self):
        labelled = [_det_line(1, 0, False)]
        predicted = [_candidate(1, 0)]
        r = score(predicted, labelled)
        assert r["fp"] == 1
        assert r["tn"] == 0

    def test_determinable_negative_not_surfaced_is_tn(self):
        labelled = [_det_line(1, 0, False)]
        r = score([], labelled)
        assert r["tn"] == 1
        assert r["fp"] == 0

    def test_determinable_negative_fp_raises_fp_rate(self):
        labelled = [
            _det_line(1, 0, False),
            _det_line(2, 0, False),
        ]
        predicted = [_candidate(1, 0)]   # 1 of 2 negatives flagged
        r = score(predicted, labelled)
        assert abs(r["fp_rate"] - 0.5) < 1e-5

    def test_determinable_negative_tn_brings_fp_rate_down(self):
        labelled = [
            _det_line(1, 0, True, "other_disallowed"),
            _det_line(2, 0, False),
        ]
        predicted = [_candidate(1, 0, "other_disallowed")]   # only positive surfaced
        r = score(predicted, labelled)
        assert r["fp_rate"] == 0.0
        assert r["tn"] == 1


class TestDeterminabilityC:
    """C — indeterminate lines excluded from tp/fp/fn/tn and recall/fp_rate."""

    def test_indeterminate_positive_surfaced_excluded_from_tp(self):
        labelled = [_det_line(1, 0, True, "medical_expenses", determinability="indeterminate")]
        predicted = [_candidate(1, 0)]
        r = score(predicted, labelled)
        assert r["tp"] == 0
        assert r["fp"] == 0
        assert r["fn"] == 0
        assert r["tn"] == 0

    def test_indeterminate_negative_surfaced_excluded_from_fp(self):
        labelled = [_det_line(1, 0, False, determinability="indeterminate")]
        predicted = [_candidate(1, 0)]
        r = score(predicted, labelled)
        assert r["fp"] == 0
        assert r["tn"] == 0

    def test_indeterminate_lines_counted_in_surface_rate(self):
        labelled = [
            _det_line(1, 0, True, "medical_expenses", determinability="indeterminate"),
            _det_line(2, 0, True, "medical_expenses", determinability="indeterminate"),
            _det_line(3, 0, False, determinability="indeterminate"),
        ]
        predicted = [_candidate(1, 0)]   # 1 of 3 indeterminate surfaced
        r = score(predicted, labelled)
        assert r["indeterminate"]["support"] == 3
        assert abs(r["indeterminate"]["surface_rate"] - 1 / 3) < 1e-5

    def test_indeterminate_only_does_not_contribute_to_recall(self):
        labelled = [_det_line(1, 0, True, "medical_expenses", determinability="indeterminate")]
        r = score([], labelled)
        assert r["recall"] is None

    def test_indeterminate_only_does_not_contribute_to_fp_rate(self):
        labelled = [_det_line(1, 0, False, determinability="indeterminate")]
        r = score([_candidate(1, 0)], labelled)
        assert r["fp_rate"] is None

    def test_indeterminate_disposition_is_indet(self):
        labelled = [_det_line(1, 0, True, "medical_expenses", determinability="indeterminate")]
        r = score([], labelled)
        assert r["per_line"][0]["disposition"] == "INDET"


class TestDeterminabilityD:
    """D — zero-denominator cases return None without raising."""

    def test_no_positives_recall_is_none(self):
        labelled = [_det_line(1, 0, False), _det_line(2, 0, False)]
        r = score([], labelled)
        assert r["recall"] is None

    def test_no_negatives_fp_rate_is_none(self):
        labelled = [_det_line(1, 0, True, "medical_expenses")]
        r = score([_candidate(1, 0)], labelled)
        # tp=1, tn=0, fp=0, fp+tn=0 → fp_rate=None
        assert r["fp_rate"] is None

    def test_no_lines_at_all_no_raise(self):
        r = score([], [])
        assert r["recall"] is None
        assert r["fp_rate"] is None
        assert r["indeterminate"]["surface_rate"] is None

    def test_zero_indeterminate_surface_rate_is_none(self):
        labelled = [_det_line(1, 0, True, "club_subscriptions")]
        r = score([], labelled)
        assert r["indeterminate"]["surface_rate"] is None
        assert r["indeterminate"]["support"] == 0

    def test_per_category_zero_positive_recall_is_none(self):
        labelled = [_det_line(1, 0, False, determinability="determinable")]
        r = score([], labelled)
        assert r["per_category"]["n/a"]["recall"] is None

    def test_per_category_zero_negative_fp_rate_is_none(self):
        labelled = [_det_line(1, 0, True, "club_subscriptions")]
        r = score([], labelled)
        assert r["per_category"]["club_subscriptions"]["fp_rate"] is None

    def test_zero_denominator_never_raises(self):
        # Both denominators simultaneously zero
        labelled = [_det_line(1, 0, True, "medical_expenses")]
        score([], labelled)   # fn=1 but fp+tn=0; must not raise


class TestDeterminabilityE:
    """E — mixed determinable + indeterminate produces correct per_category splits."""

    @pytest.fixture
    def setup(self):
        # Determinable: (1,0) club pos TP, (2,0) medical pos FN, (3,0) neg n/a TN
        # Indeterminate: (4,0) medical pos, (5,0) neg n/a
        labelled = [
            _det_line(1, 0, True, "club_subscriptions"),
            _det_line(2, 0, True, "medical_expenses"),
            _det_line(3, 0, False),
            _det_line(4, 0, True, "medical_expenses", determinability="indeterminate"),
            _det_line(5, 0, False, determinability="indeterminate"),
        ]
        predicted = [
            _candidate(1, 0, "club_subscriptions"),  # TP
            _candidate(4, 0),                         # indeterminate surfaced
            _candidate(5, 0),                         # indeterminate surfaced
        ]
        return score(predicted, labelled)

    def test_overall_tp_fn_fp_tn(self, setup):
        r = setup
        assert r["tp"] == 1
        assert r["fn"] == 1
        assert r["fp"] == 0
        assert r["tn"] == 1

    def test_overall_determinable_support(self, setup):
        assert setup["determinable_support"] == 3

    def test_overall_indeterminate_support(self, setup):
        assert setup["indeterminate"]["support"] == 2

    def test_overall_indeterminate_surface_rate(self, setup):
        assert abs(setup["indeterminate"]["surface_rate"] - 1.0) < 1e-5

    def test_overall_recall_over_determinable_only(self, setup):
        # tp=1, fn=1, recall=0.5
        assert abs(setup["recall"] - 0.5) < 1e-5

    def test_overall_fp_rate_over_determinable_only(self, setup):
        # fp=0, tn=1, fp_rate=0.0
        assert setup["fp_rate"] == 0.0

    def test_club_per_category_determinable(self, setup):
        club = setup["per_category"]["club_subscriptions"]
        assert club["tp"] == 1
        assert club["fn"] == 0
        assert club["recall"] == 1.0
        assert club["fp_rate"] is None       # sn=0
        assert club["support_positive"] == 1
        assert club["support_negative"] == 0
        assert club["indeterminate_support"] == 0
        assert club["indeterminate_surface_rate"] is None

    def test_medical_per_category_determinable(self, setup):
        med = setup["per_category"]["medical_expenses"]
        assert med["tp"] == 0
        assert med["fn"] == 1
        assert med["recall"] == 0.0          # 0/(0+1)
        assert med["fp_rate"] is None        # sn=0
        assert med["support_positive"] == 1
        assert med["support_negative"] == 0

    def test_medical_per_category_indeterminate(self, setup):
        med = setup["per_category"]["medical_expenses"]
        assert med["indeterminate_support"] == 1
        assert abs(med["indeterminate_surface_rate"] - 1.0) < 1e-5

    def test_na_per_category_determinable(self, setup):
        na = setup["per_category"]["n/a"]
        assert na["recall"] is None          # sp=0
        assert na["fp_rate"] == 0.0          # fp=0, sn=1
        assert na["support_negative"] == 1

    def test_na_per_category_indeterminate(self, setup):
        na = setup["per_category"]["n/a"]
        assert na["indeterminate_support"] == 1
        assert abs(na["indeterminate_surface_rate"] - 1.0) < 1e-5

    def test_new_top_level_keys_present(self, setup):
        assert "determinable_support" in setup
        assert "indeterminate" in setup
        assert "surface_rate" in setup["indeterminate"]
        assert "support" in setup["indeterminate"]
