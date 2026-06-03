"""Tests for reasoning/label_fixture.py — fully deterministic; no network calls."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from reasoning.label_fixture import (
    _LLM_INPUT_FIELDS,
    _LABEL_CATEGORIES,
    _reconcile,
    _strip_to_observable,
    _to_fixture_fields,
    _validate_label,
    run_labelling_pass,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _annotated_line(
    doc_num: int = 1,
    line_index: int = 0,
    line_description: str = "STAFF MEDICAL",
    **extra,
) -> dict:
    """Build a full DRAFT-fixture annotated line (as line_source would supply)."""
    line = {
        # Observable fields
        "doc_num": doc_num,
        "doc_type": "purchase_invoice",
        "doc_date": "2024-07-01",
        "card_name": "Test Supplier",
        "line_index": line_index,
        "vat_group": "SI",
        "line_description": line_description,
        "line_total": 500.0,
        "tax_total": 45.0,
        # Annotation / ground-truth fields — must NOT reach the model
        "expected_candidate": True,
        "expected_category": "medical_expenses",
        "determinability": "determinable",
        "needs_human_review": True,
        "proposed": True,
        "iras_basis": "§6.1.6 item 2, General Guide — medical expense",
        "_label_note": "PROPOSED positive — medical",
        "contested": False,
    }
    line.update(extra)
    return line


def _label_response(
    disposition: str = "disallowed",
    determinability: str = "determinable",
    category: str = "medical_expenses",
    iras_basis: str = "§6.1.6 item 2, General Guide",
    rationale: str = "Staff medical expense.",
    confidence: str = "high",
) -> dict:
    return {
        "disposition": disposition,
        "determinability": determinability,
        "category": category,
        "iras_basis": iras_basis,
        "rationale": rationale,
        "confidence": confidence,
    }


def _canned(response: dict | list[dict]):
    """llm_call that cycles through the provided response(s)."""
    if isinstance(response, dict):
        responses = [response]
    else:
        responses: list[dict] = response
    calls: list[int] = []

    def _call(model, system, messages, max_tokens):
        idx = len(calls) % len(responses)
        calls.append(1)
        return {"content": json.dumps(responses[idx]), "input_tokens": 5, "output_tokens": 5}

    return _call


def _alternating(r1: dict, r2: dict):
    """llm_call that alternates: odd→r1, even→r2."""
    calls: list[int] = []

    def _call(model, system, messages, max_tokens):
        idx = len(calls)
        calls.append(1)
        resp = r1 if idx % 2 == 0 else r2
        return {"content": json.dumps(resp), "input_tokens": 5, "output_tokens": 5}

    return _call


# ---------------------------------------------------------------------------
# T1 — Prompt leakage: annotation fields must not reach the model
# ---------------------------------------------------------------------------

class TestPromptLeakage:
    """The labeller must be blind to any existing fixture annotation field."""

    def test_strip_excludes_expected_candidate(self):
        obs = _strip_to_observable(_annotated_line())
        assert "expected_candidate" not in obs

    def test_strip_excludes_expected_category(self):
        assert "expected_category" not in _strip_to_observable(_annotated_line())

    def test_strip_excludes_needs_human_review(self):
        assert "needs_human_review" not in _strip_to_observable(_annotated_line())

    def test_strip_excludes_proposed(self):
        assert "proposed" not in _strip_to_observable(_annotated_line())

    def test_strip_excludes_iras_basis(self):
        assert "iras_basis" not in _strip_to_observable(_annotated_line())

    def test_strip_excludes_determinability(self):
        assert "determinability" not in _strip_to_observable(_annotated_line())

    def test_strip_excludes_label_note(self):
        assert "_label_note" not in _strip_to_observable(_annotated_line())

    def test_strip_excludes_contested(self):
        assert "contested" not in _strip_to_observable(_annotated_line())

    def test_strip_contains_only_allowed_fields(self):
        obs = _strip_to_observable(_annotated_line())
        assert set(obs.keys()) <= _LLM_INPUT_FIELDS

    def test_strip_preserves_all_observable_fields_present_in_line(self):
        obs = _strip_to_observable(_annotated_line())
        for field in _LLM_INPUT_FIELDS:
            assert field in obs, f"Observable field {field!r} lost after strip"

    def test_model_user_message_contains_no_annotation_fields(self):
        """Integration: capture every user message sent to llm_call; assert no leakage."""
        captured_messages: list[str] = []

        def _capture(model, system, messages, max_tokens):
            for m in messages:
                if m.get("role") == "user":
                    captured_messages.append(m["content"])
            return {"content": json.dumps(_label_response()), "input_tokens": 1, "output_tokens": 1}

        run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_capture,
        )

        assert captured_messages, "llm_call was never called with user messages"
        forbidden = [
            "expected_candidate", "expected_category", "needs_human_review",
            "proposed", "iras_basis", "determinability", "_label_note",
        ]
        for msg in captured_messages:
            for field in forbidden:
                assert f'"{field}"' not in msg, (
                    f"Annotation field {field!r} leaked into model user message"
                )


# ---------------------------------------------------------------------------
# T2 — Both passes agree → determinable with that disposition
# ---------------------------------------------------------------------------

class TestBothPassesAgree:

    def test_both_agree_disallowed_determinable(self):
        r = _label_response(disposition="disallowed", determinability="determinable", confidence="high")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        fl = art["lines"][0]["final_label"]
        assert fl["disposition"] == "disallowed"
        assert fl["determinability"] == "determinable"
        assert fl["contested"] is False

    def test_both_agree_claimable_determinable(self):
        r = _label_response(disposition="claimable", determinability="determinable",
                            category="n/a", confidence="high")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        fl = art["lines"][0]["final_label"]
        assert fl["disposition"] == "claimable"
        assert fl["determinability"] == "determinable"
        assert fl["contested"] is False

    def test_both_agree_indeterminate(self):
        r = _label_response(disposition="disallowed", determinability="indeterminate", confidence="medium")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        fl = art["lines"][0]["final_label"]
        assert fl["determinability"] == "indeterminate"
        assert fl["contested"] is False

    def test_contested_false_when_both_pass1_agrees(self):
        r = _label_response(confidence="medium", determinability="determinable")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert art["lines"][0]["final_label"]["contested"] is False


# ---------------------------------------------------------------------------
# T3 — Passes disagree → indeterminate + contested=True
# ---------------------------------------------------------------------------

class TestDisagreement:

    def test_disposition_disagreement_gives_contested(self):
        r1 = _label_response(disposition="disallowed", determinability="determinable", confidence="high")
        r2 = _label_response(disposition="claimable",  determinability="determinable",
                             category="n/a", confidence="high")
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_alternating(r1, r2),
        )
        fl = art["lines"][0]["final_label"]
        assert fl["contested"] is True

    def test_disposition_disagreement_forces_indeterminate(self):
        r1 = _label_response(disposition="disallowed", determinability="determinable", confidence="high")
        r2 = _label_response(disposition="claimable",  determinability="determinable",
                             category="n/a", confidence="high")
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_alternating(r1, r2),
        )
        assert art["lines"][0]["final_label"]["determinability"] == "indeterminate"

    def test_determinability_disagreement_gives_contested(self):
        r1 = _label_response(disposition="disallowed", determinability="determinable",  confidence="high")
        r2 = _label_response(disposition="disallowed", determinability="indeterminate", confidence="medium")
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_alternating(r1, r2),
        )
        fl = art["lines"][0]["final_label"]
        assert fl["contested"] is True
        assert fl["determinability"] == "indeterminate"

    def test_fixture_mapping_needs_human_review_on_disagreement(self):
        r1 = _label_response(disposition="disallowed", determinability="determinable", confidence="high")
        r2 = _label_response(disposition="claimable",  determinability="determinable",
                             category="n/a", confidence="high")
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_alternating(r1, r2),
        )
        fm = art["lines"][0]["fixture_mapping"]
        assert fm["needs_human_review"] is True
        assert fm["determinability"] == "indeterminate"

    def test_per_line_artefact_records_both_pass_outputs(self):
        r1 = _label_response(disposition="disallowed", confidence="high")
        r2 = _label_response(disposition="claimable",  category="n/a", confidence="high")
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_alternating(r1, r2),
        )
        ln = art["lines"][0]
        assert ln["pass_1"]["parsed"] is not None
        assert ln["pass_2"]["parsed"] is not None


# ---------------------------------------------------------------------------
# T4 — confidence=low → indeterminate (regardless of passes agreeing)
# ---------------------------------------------------------------------------

class TestLowConfidence:

    def test_low_confidence_forces_indeterminate(self):
        r = _label_response(confidence="low", determinability="determinable")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        fl = art["lines"][0]["final_label"]
        assert fl["determinability"] == "indeterminate"

    def test_low_confidence_on_pass2_forces_indeterminate(self):
        r1 = _label_response(confidence="high",  determinability="determinable")
        r2 = _label_response(confidence="low",   determinability="determinable")
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_alternating(r1, r2),
        )
        assert art["lines"][0]["final_label"]["determinability"] == "indeterminate"

    def test_low_confidence_validate_sets_indeterminate(self):
        raw = json.dumps(_label_response(confidence="low", determinability="determinable"))
        label = _validate_label(raw)
        assert label["determinability"] == "indeterminate"

    def test_medium_confidence_does_not_force_indeterminate(self):
        r = _label_response(confidence="medium", determinability="determinable")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert art["lines"][0]["final_label"]["determinability"] == "determinable"


# ---------------------------------------------------------------------------
# T5 — Fixture field mapping
# ---------------------------------------------------------------------------

class TestFixtureMapping:

    def test_disallowed_sets_expected_candidate_true(self):
        r = _label_response(disposition="disallowed")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert art["lines"][0]["fixture_mapping"]["expected_candidate"] is True

    def test_claimable_sets_expected_candidate_false(self):
        r = _label_response(disposition="claimable", category="n/a")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert art["lines"][0]["fixture_mapping"]["expected_candidate"] is False

    def test_entertainment_claimable_gets_expected_category_entertainment(self):
        """A claimable entertainment line must carry expected_category='entertainment'."""
        r = _label_response(
            disposition="claimable",
            category="entertainment",
            determinability="determinable",
            confidence="high",
            iras_basis="§6.1.3(b)(ii), General Guide — F&B claimable",
        )
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line(line_description="CLIENT DINNER")],
            llm_call=_canned(r),
        )
        fm = art["lines"][0]["fixture_mapping"]
        assert fm["expected_candidate"] is False
        assert fm["expected_category"] == "entertainment"

    def test_na_claimable_has_no_expected_category(self):
        r = _label_response(disposition="claimable", category="n/a")
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line(line_description="OFFICE SUPPLIES")],
            llm_call=_canned(r),
        )
        fm = art["lines"][0]["fixture_mapping"]
        assert fm["expected_candidate"] is False
        assert fm.get("expected_category") is None

    def test_needs_human_review_true_when_candidate(self):
        r = _label_response(disposition="disallowed", determinability="determinable", confidence="high")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        fm = art["lines"][0]["fixture_mapping"]
        assert fm["needs_human_review"] is True

    def test_needs_human_review_true_when_indeterminate_and_claimable(self):
        r = _label_response(disposition="claimable", category="n/a",
                            determinability="indeterminate", confidence="medium")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert art["lines"][0]["fixture_mapping"]["needs_human_review"] is True

    def test_needs_human_review_false_when_claimable_determinable(self):
        r = _label_response(disposition="claimable", category="n/a",
                            determinability="determinable", confidence="high")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert art["lines"][0]["fixture_mapping"]["needs_human_review"] is False

    def test_disallowed_category_set_in_mapping(self):
        r = _label_response(disposition="disallowed", category="club_subscriptions")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert art["lines"][0]["fixture_mapping"]["expected_category"] == "club_subscriptions"

    def test_medical_insurance_category_propagated(self):
        r = _label_response(disposition="disallowed", category="medical_insurance",
                            iras_basis="§6.1.6 item 3, General Guide")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        fm = art["lines"][0]["fixture_mapping"]
        assert fm["expected_category"] == "medical_insurance"
        assert fm["expected_candidate"] is True

    def test_to_fixture_fields_produces_no_annotation_bleed(self):
        """_to_fixture_fields must not copy annotation fields from the original line."""
        original = _annotated_line()
        final = {
            "disposition": "disallowed", "determinability": "determinable",
            "contested": False, "category": "club_subscriptions",
            "iras_basis": "§6.1.6 item 1", "rationale": "Club.", "confidence": "high",
        }
        out = _to_fixture_fields(original, final)
        # Annotation fields that must not appear in the fixture line
        for forbidden in ("_label_note",):
            assert forbidden not in out, f"Annotation field {forbidden!r} bled into fixture line"


# ---------------------------------------------------------------------------
# T6 — _validate_label
# ---------------------------------------------------------------------------

class TestValidateLabel:

    def test_valid_label_accepted(self):
        label = _validate_label(json.dumps(_label_response()))
        assert label["disposition"] == "disallowed"
        assert label["category"] == "medical_expenses"

    def test_invalid_disposition_raises(self):
        with pytest.raises(ValueError, match="disposition"):
            _validate_label(json.dumps(_label_response(disposition="unclear")))

    def test_invalid_category_raises(self):
        with pytest.raises(ValueError, match="category"):
            _validate_label(json.dumps(_label_response(category="taxi_expense")))

    def test_invalid_confidence_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            _validate_label(json.dumps(_label_response(confidence="very_high")))

    def test_missing_field_raises(self):
        d = _label_response()
        del d["iras_basis"]
        with pytest.raises(ValueError, match="missing"):
            _validate_label(json.dumps(d))

    def test_low_confidence_forces_indeterminate_in_validate(self):
        raw = json.dumps(_label_response(confidence="low", determinability="determinable"))
        label = _validate_label(raw)
        assert label["determinability"] == "indeterminate"

    def test_markdown_fences_stripped(self):
        raw = "```json\n" + json.dumps(_label_response()) + "\n```"
        label = _validate_label(raw)
        assert label["disposition"] == "disallowed"

    def test_markdown_fences_no_closing_stripped(self):
        raw = "```\n" + json.dumps(_label_response())
        label = _validate_label(raw)
        assert label["disposition"] == "disallowed"

    def test_all_label_categories_accepted(self):
        for cat in _LABEL_CATEGORIES:
            disp = "claimable" if cat in ("n/a", "entertainment") else "disallowed"
            raw = json.dumps(_label_response(category=cat, disposition=disp))
            label = _validate_label(raw)
            assert label["category"] == cat

    def test_medical_insurance_accepted_as_category(self):
        raw = json.dumps(_label_response(category="medical_insurance",
                                         iras_basis="§6.1.6 item 3, General Guide"))
        label = _validate_label(raw)
        assert label["category"] == "medical_insurance"

    def test_not_json_raises(self):
        with pytest.raises(ValueError, match="JSON"):
            _validate_label("not json at all")

    def test_json_array_raises(self):
        with pytest.raises(ValueError):
            _validate_label("[]")


# ---------------------------------------------------------------------------
# T7 — _reconcile
# ---------------------------------------------------------------------------

class TestReconcile:

    def test_both_agree_no_contested(self):
        p = _label_response(disposition="disallowed", determinability="determinable", confidence="high")
        result = _reconcile(p, p)
        assert result["contested"] is False
        assert result["determinability"] == "determinable"

    def test_disposition_disagreement(self):
        p1 = _label_response(disposition="disallowed", determinability="determinable", confidence="high")
        p2 = _label_response(disposition="claimable",  determinability="determinable",
                             category="n/a", confidence="high")
        result = _reconcile(p1, p2)
        assert result["contested"] is True
        assert result["determinability"] == "indeterminate"

    def test_determinability_disagreement(self):
        p1 = _label_response(disposition="disallowed", determinability="determinable",  confidence="high")
        p2 = _label_response(disposition="disallowed", determinability="indeterminate", confidence="medium")
        result = _reconcile(p1, p2)
        assert result["contested"] is True
        assert result["determinability"] == "indeterminate"

    def test_lower_confidence_wins(self):
        p1 = _label_response(confidence="high")
        p2 = _label_response(confidence="medium")
        result = _reconcile(p1, p2)
        assert result["confidence"] == "medium"

    def test_low_confidence_forces_indeterminate_even_when_agreeing(self):
        p = _label_response(confidence="low", determinability="determinable")
        result = _reconcile(p, p)
        assert result["determinability"] == "indeterminate"

    def test_primary_disposition_from_pass1(self):
        p1 = _label_response(disposition="disallowed")
        p2 = _label_response(disposition="claimable", category="n/a")
        result = _reconcile(p1, p2)
        assert result["disposition"] == "disallowed"   # pass1 is primary

    def test_medical_insurance_category_valid(self):
        p = _label_response(category="medical_insurance", disposition="disallowed", confidence="high")
        result = _reconcile(p, p)
        assert result["category"] == "medical_insurance"
        assert result["contested"] is False


# ---------------------------------------------------------------------------
# T8 — Artefact structure
# ---------------------------------------------------------------------------

class TestArtefactStructure:

    def test_artefact_has_provisional_header(self):
        r = _label_response()
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert "_provisional_header" in art
        assert "unvalidated" in art["_provisional_header"]

    def test_artefact_has_run_metadata(self):
        r = _label_response()
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        meta = art["run_metadata"]
        for key in ("model", "run_at", "line_count", "contested_count",
                    "indeterminate_count", "error_count"):
            assert key in meta, f"run_metadata missing key: {key!r}"

    def test_artefact_line_count_matches_input(self):
        lines = [_annotated_line(doc_num=i) for i in range(1, 4)]
        r = _label_response()
        art = run_labelling_pass(line_source=lambda: lines, llm_call=_canned(r))
        assert len(art["lines"]) == 3
        assert art["run_metadata"]["line_count"] == 3

    def test_artefact_per_line_has_both_passes(self):
        r = _label_response()
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        ln = art["lines"][0]
        assert "pass_1" in ln
        assert "pass_2" in ln
        assert "final_label" in ln
        assert "fixture_mapping" in ln

    def test_artefact_per_line_has_doc_num_and_description(self):
        r = _label_response()
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line(doc_num=42, line_description="TEST LINE")],
            llm_call=_canned(r),
        )
        ln = art["lines"][0]
        assert ln["doc_num"] == 42
        assert ln["line_description"] == "TEST LINE"

    def test_contested_count_increments(self):
        r1 = _label_response(disposition="disallowed", confidence="high")
        r2 = _label_response(disposition="claimable",  category="n/a", confidence="high")
        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_alternating(r1, r2),
        )
        assert art["run_metadata"]["contested_count"] == 1

    def test_indeterminate_count_increments(self):
        r = _label_response(determinability="indeterminate", confidence="medium")
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert art["run_metadata"]["indeterminate_count"] == 1

    def test_provisional_header_mentions_opus(self):
        r = _label_response()
        art = run_labelling_pass(line_source=lambda: [_annotated_line()], llm_call=_canned(r))
        assert "opus-4-8" in art["_provisional_header"].lower()


# ---------------------------------------------------------------------------
# T9 — LLM error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:

    def test_llm_exception_marks_line_contested_indeterminate(self):
        call_count: list[int] = []

        def _bad(model, system, messages, max_tokens):
            call_count.append(1)
            raise RuntimeError("network error")

        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_bad,
        )
        fl = art["lines"][0]["final_label"]
        assert fl["contested"] is True
        assert fl["determinability"] == "indeterminate"
        assert art["run_metadata"]["error_count"] == 1

    def test_invalid_json_from_llm_marks_error(self):
        def _bad_json(model, system, messages, max_tokens):
            return {"content": "NOT JSON", "input_tokens": 1, "output_tokens": 1}

        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_bad_json,
        )
        assert art["run_metadata"]["error_count"] == 1

    def test_one_good_one_bad_pass_marks_error(self):
        calls: list[int] = []

        def _mixed(model, system, messages, max_tokens):
            idx = len(calls)
            calls.append(1)
            if idx % 2 == 0:
                return {"content": json.dumps(_label_response()), "input_tokens": 1, "output_tokens": 1}
            raise RuntimeError("pass 2 failed")

        art = run_labelling_pass(
            line_source=lambda: [_annotated_line()],
            llm_call=_mixed,
        )
        assert art["run_metadata"]["error_count"] == 1
        fl = art["lines"][0]["final_label"]
        assert fl["determinability"] == "indeterminate"

    def test_line_source_exception_returns_error_artefact(self):
        def _bad_source():
            raise ValueError("fixture missing")

        art = run_labelling_pass(line_source=_bad_source, llm_call=_canned(_label_response()))
        assert art["lines"] == []
        assert "error" in art["run_metadata"]


# ---------------------------------------------------------------------------
# T10 — Dependency invariants
# ---------------------------------------------------------------------------

class TestDependencyInvariants:

    def _source(self) -> str:
        import reasoning.label_fixture as mod
        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_no_top_level_anthropic_import(self):
        source = self._source()
        for line in source.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("import anthropic") or stripped.startswith("from anthropic"):
                if not line[0].isspace():
                    pytest.fail(f"Top-level anthropic import found: {line!r}")

    def test_does_not_import_orchestrator(self):
        source = self._source()
        assert "from orchestrator" not in source
        assert "import orchestrator" not in source

    def test_does_not_import_audit_bundle(self):
        source = self._source()
        assert "from audit_bundle" not in source
        assert "import audit_bundle" not in source

    def test_module_importable_without_anthropic(self):
        # The module must import successfully without triggering anthropic at import time.
        import importlib
        import reasoning.label_fixture  # noqa: F401 — import should not raise
        importlib.reload(reasoning.label_fixture)

    def test_run_labelling_pass_works_without_anthropic(self):
        """Tests that use an injected llm_call must not require anthropic to be importable."""
        # This would raise if anthropic were called at module or function entry
        r = _label_response()
        art = run_labelling_pass(line_source=lambda: [], llm_call=_canned(r))
        assert art["lines"] == []
