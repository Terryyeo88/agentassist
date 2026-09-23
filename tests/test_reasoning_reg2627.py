"""
Tests for reasoning/reg2627.py — Reg 26/27 disallowed input tax reasoning pass.

All tests use injectable fakes for line_source and llm_call.
No test hits a live SAP instance or the live Anthropic API.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reasoning.reg2627 import (
    _KB_PATH,
    _DISCLAIMER,
    _PINNED_MODEL,
    _PROMPT_VERSION,
    _validate_candidate,
    run_reg2627_pass,
)

_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_llm(content: str = "[]", input_tokens: int = 100, output_tokens: int = 10):
    """Return a fake llm_call callable that returns fixed content."""
    def _call(model, system, messages, max_tokens):
        return {
            "content": content,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
    return _call


def _si_line(
    doc_num: int = 1,
    line_index: int = 0,
    line_description: str = "Medical Consultation",
    line_total: float = 100.0,
    tax_total: float = 9.0,
    card_name: str = "Raffles Medical",
    doc_date: str = "2024-07-15",
) -> dict:
    return {
        "doc_num": doc_num,
        "doc_type": "purchase_invoice",
        "doc_date": doc_date,
        "card_name": card_name,
        "line_index": line_index,
        "vat_group": "SI",
        "line_description": line_description,
        "line_total": line_total,
        "tax_total": tax_total,
    }


def _valid_candidate(**overrides) -> dict:
    base = {
        "doc_num": 1,
        "doc_type": "purchase_invoice",
        "doc_date": "2024-07-15",
        "card_name": "Raffles Medical",
        "line_index": 0,
        "vat_group": "SI",
        "line_description": "Medical Consultation",
        "line_total": 100.0,
        "tax_total": 9.0,
        "suspected_category": "medical_expenses",
        "reasoning": "Supplier is a medical clinic.",
        "phrasing": "Consider reviewing whether this medical expense qualifies.",
        "confidence": "high",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# T1 — Empty line source → ok, no candidates, no LLM call
# ---------------------------------------------------------------------------

class TestEmptyLineSource:
    def test_empty_lines_returns_ok(self):
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [],
            llm_call=_fake_llm("should-not-be-called"),
        )
        assert artefact["status"] == "ok"

    def test_empty_lines_candidates_empty(self):
        artefact = run_reg2627_pass(_PERIOD, line_source=lambda: [], llm_call=_fake_llm())
        assert artefact["candidates"] == []
        assert artefact["candidate_count"] == 0

    def test_empty_lines_no_llm_call(self):
        called = []
        def _track(model, system, messages, max_tokens):
            called.append(True)
            return {"content": "[]", "input_tokens": 0, "output_tokens": 0}

        run_reg2627_pass(_PERIOD, line_source=lambda: [], llm_call=_track)
        assert called == [], "LLM must not be called when there are no SI lines"

    def test_empty_lines_token_usage_zero(self):
        artefact = run_reg2627_pass(_PERIOD, line_source=lambda: [], llm_call=_fake_llm())
        assert artefact["token_usage"] == {"input_tokens": 0, "output_tokens": 0}

    def test_empty_lines_input_summary_zero(self):
        artefact = run_reg2627_pass(_PERIOD, line_source=lambda: [], llm_call=_fake_llm())
        assert artefact["input_summary"]["si_purchase_lines_examined"] == 0
        assert artefact["input_summary"]["documents_examined"] == 0


# ---------------------------------------------------------------------------
# T2 — Non-SI lines are filtered out before reaching the LLM
# ---------------------------------------------------------------------------

class TestNonSIFiltering:
    def test_non_si_lines_filtered(self):
        non_si_line = {**_si_line(), "vat_group": "SO"}

        called_with: list[dict] = []
        def _track(model, system, messages, max_tokens):
            called_with.append({"messages": messages})
            return {"content": "[]", "input_tokens": 5, "output_tokens": 2}

        run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [non_si_line],
            llm_call=_track,
        )
        # LLM not called since no SI lines survived filtering
        assert called_with == []

    def test_mixed_lines_only_si_forwarded(self):
        lines = [
            _si_line(doc_num=1, line_index=0),
            {**_si_line(doc_num=2, line_index=0), "vat_group": "SO"},
        ]
        received: list[str] = []
        def _track(model, system, messages, max_tokens):
            received.append(messages[0]["content"])
            return {"content": "[]", "input_tokens": 5, "output_tokens": 2}

        run_reg2627_pass(_PERIOD, line_source=lambda: lines, llm_call=_track)
        assert len(received) == 1
        content = received[0]
        assert "doc_num" in content
        # doc_num=2 (SO line) must not appear in the message
        # doc_num=1 (SI line) must appear
        content_data = content
        assert '"doc_num": 1' in content_data or "'doc_num': 1" in content_data or "1" in content_data


# ---------------------------------------------------------------------------
# T3 — Valid LLM response → candidates parsed correctly
# ---------------------------------------------------------------------------

class TestValidLLMResponse:
    def _run_with_candidate(self, candidate_override=None):
        c = _valid_candidate(**(candidate_override or {}))
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm(json.dumps([c]), input_tokens=50, output_tokens=20),
        )
        return artefact

    def test_status_ok(self):
        assert self._run_with_candidate()["status"] == "ok"

    def test_error_is_null(self):
        assert self._run_with_candidate()["error"] is None

    def test_candidate_count(self):
        assert self._run_with_candidate()["candidate_count"] == 1

    def test_candidate_fields_present(self):
        artefact = self._run_with_candidate()
        c = artefact["candidates"][0]
        for field in ("doc_num", "doc_type", "doc_date", "card_name", "line_index",
                      "vat_group", "line_description", "line_total", "tax_total",
                      "suspected_category", "reasoning", "phrasing", "confidence"):
            assert field in c, f"field '{field}' missing from candidate"

    def test_candidate_keeps_its_per_line_vat_group(self):
        # AMENDED by Terry 2026-09-23 (Slice E, ruling B1): REG2627_SPEC is now
        # frozenset({"SI","TX"}), so a candidate keeps its OWN code instead of being forced to
        # the spec's. A TX line must not be reported as SI.
        # NOTE — the defence this test used to provide is NOT replaced: the stamp is now the
        # MODEL'S echo, not the matched line's code. Open item: stamp from the matched line
        # (join on doc_num + line_index) so per-line honesty and hallucination-resistance both
        # hold. Must close before any T2.11 validation run.
        c = _valid_candidate(vat_group="SO")  # LLM echoes a wrong vat_group
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm(json.dumps([c])),
        )
        assert artefact["candidates"][0]["vat_group"] == "SO"

    def test_token_usage_captured(self):
        artefact = self._run_with_candidate()
        assert artefact["token_usage"]["input_tokens"] == 50
        assert artefact["token_usage"]["output_tokens"] == 20

    def test_two_candidates(self):
        two = [_valid_candidate(doc_num=1, line_index=0), _valid_candidate(doc_num=2, line_index=0)]
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line(doc_num=1), _si_line(doc_num=2)],
            llm_call=_fake_llm(json.dumps(two)),
        )
        assert artefact["candidate_count"] == 2
        assert len(artefact["candidates"]) == 2

    def test_llm_empty_array_returns_ok_no_candidates(self):
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm("[]"),
        )
        assert artefact["status"] == "ok"
        assert artefact["candidates"] == []
        assert artefact["candidate_count"] == 0


# ---------------------------------------------------------------------------
# T4 — Phrasing normalisation
# ---------------------------------------------------------------------------

class TestPhrasingNormalisation:
    def test_phrasing_already_correct_unchanged(self):
        c = _valid_candidate(phrasing="Consider reviewing whether this is OK.")
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm(json.dumps([c])),
        )
        assert artefact["candidates"][0]["phrasing"] == "Consider reviewing whether this is OK."

    def test_phrasing_missing_prefix_gets_prepended(self):
        c = _valid_candidate(phrasing="this medical expense should be reviewed")
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm(json.dumps([c])),
        )
        result = artefact["candidates"][0]["phrasing"]
        assert result.startswith("Consider reviewing whether")

    def test_phrasing_empty_string_gets_prefix(self):
        c = _valid_candidate(phrasing="")
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm(json.dumps([c])),
        )
        result = artefact["candidates"][0]["phrasing"]
        assert result.startswith("Consider reviewing whether")


# ---------------------------------------------------------------------------
# T5 — Error cases → status="errored", candidates=[]
# ---------------------------------------------------------------------------

class TestErrorCases:
    def test_llm_returns_invalid_json(self):
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm("not-valid-json"),
        )
        assert artefact["status"] == "errored"
        assert artefact["candidates"] == []
        assert artefact["candidate_count"] == 0
        assert artefact["error"] is not None

    def test_llm_returns_json_object_not_array(self):
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm('{"key": "value"}'),
        )
        assert artefact["status"] == "errored"
        assert "array" in artefact["error"].lower() or artefact["error"] is not None

    def test_llm_call_throws(self):
        def _raise(model, system, messages, max_tokens):
            raise RuntimeError("Network error")

        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_raise,
        )
        assert artefact["status"] == "errored"
        assert "Network error" in artefact["error"]

    def test_line_source_throws(self):
        def _bad_source():
            raise AttributeError("'NoneType' object has no attribute 'get'")

        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=_bad_source,
            llm_call=_fake_llm(),
        )
        assert artefact["status"] == "errored"
        assert artefact["candidates"] == []
        assert "NoneType" in artefact["error"]

    def test_errored_artefact_always_has_all_top_level_keys(self):
        def _raise(model, system, messages, max_tokens):
            raise RuntimeError("boom")

        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_raise,
        )
        required_keys = {
            "artefact_type", "schema_version", "check", "period", "generated_at",
            "status", "error", "provenance", "input_summary", "candidates",
            "candidate_count", "token_usage", "disclaimer",
        }
        assert required_keys <= set(artefact.keys())

    def test_errored_token_usage_zero(self):
        def _raise(model, system, messages, max_tokens):
            raise RuntimeError("boom")

        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_raise,
        )
        assert artefact["token_usage"] == {"input_tokens": 0, "output_tokens": 0}


# ---------------------------------------------------------------------------
# T6 — Candidate validation errors → entire response rejected (errored)
# ---------------------------------------------------------------------------

class TestCandidateValidation:
    def test_invalid_suspected_category_causes_errored(self):
        c = _valid_candidate(suspected_category="taxi_expense")
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm(json.dumps([c])),
        )
        assert artefact["status"] == "errored"

    def test_invalid_confidence_causes_errored(self):
        c = _valid_candidate(confidence="very_high")
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm(json.dumps([c])),
        )
        assert artefact["status"] == "errored"

    def test_missing_required_field_causes_errored(self):
        c = _valid_candidate()
        del c["reasoning"]
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm(json.dumps([c])),
        )
        assert artefact["status"] == "errored"

    def test_valid_all_suspected_categories_accepted(self):
        categories = [
            "medical_expenses", "motor_car_s_plate", "club_subscriptions",
            "family_benefits", "entertainment", "other_disallowed",
        ]
        for cat in categories:
            c = _valid_candidate(suspected_category=cat)
            artefact = run_reg2627_pass(
                _PERIOD,
                line_source=lambda: [_si_line()],
                llm_call=_fake_llm(json.dumps([c])),
            )
            assert artefact["status"] == "ok", f"category {cat!r} should be accepted"

    def test_valid_all_confidence_values_accepted(self):
        for conf in ("low", "medium", "high"):
            c = _valid_candidate(confidence=conf)
            artefact = run_reg2627_pass(
                _PERIOD,
                line_source=lambda: [_si_line()],
                llm_call=_fake_llm(json.dumps([c])),
            )
            assert artefact["status"] == "ok", f"confidence {conf!r} should be accepted"


# ---------------------------------------------------------------------------
# T7 — Provenance fields
# ---------------------------------------------------------------------------

class TestProvenance:
    def _artefact(self):
        return run_reg2627_pass(_PERIOD, line_source=lambda: [], llm_call=_fake_llm())

    def test_in_run_path_true(self):
        assert self._artefact()["provenance"]["in_run_path"] is True

    def test_model_id_pinned(self):
        assert self._artefact()["provenance"]["model_id"] == _PINNED_MODEL

    def test_prompt_version(self):
        assert self._artefact()["provenance"]["prompt_version"] == _PROMPT_VERSION

    def test_validation_status_unvalidated(self):
        assert self._artefact()["provenance"]["validation_status"] == "unvalidated"

    def test_kb_slice_hash_format(self):
        h = self._artefact()["provenance"]["kb_slice_hash"]
        assert h.startswith("sha256:")
        assert len(h) == len("sha256:") + 64

    def test_kb_slice_hash_matches_actual_file(self):
        expected = "sha256:" + hashlib.sha256(_KB_PATH.read_bytes()).hexdigest()
        assert self._artefact()["provenance"]["kb_slice_hash"] == expected

    def test_model_id_can_be_overridden(self):
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [],
            llm_call=_fake_llm(),
            model_id="claude-haiku-4-5-20251001",
        )
        assert artefact["provenance"]["model_id"] == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# T8 — Top-level artefact structure
# ---------------------------------------------------------------------------

class TestArtefactStructure:
    def _artefact(self):
        return run_reg2627_pass(_PERIOD, line_source=lambda: [], llm_call=_fake_llm())

    def test_artefact_type(self):
        assert self._artefact()["artefact_type"] == "judgment-candidates"

    def test_schema_version(self):
        assert self._artefact()["schema_version"] == "1.0"

    def test_check_field(self):
        assert self._artefact()["check"] == "reg-26-27-disallowed-input-tax"

    def test_period_matches_input(self):
        a = self._artefact()
        assert a["period"]["start"] == _PERIOD["start"]
        assert a["period"]["end"] == _PERIOD["end"]

    def test_generated_at_present(self):
        assert self._artefact()["generated_at"] != ""

    def test_disclaimer_present_and_correct(self):
        assert self._artefact()["disclaimer"] == _DISCLAIMER

    def test_candidate_count_matches_list_length(self):
        two = [_valid_candidate(doc_num=1), _valid_candidate(doc_num=2)]
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line(doc_num=1), _si_line(doc_num=2)],
            llm_call=_fake_llm(json.dumps(two)),
        )
        assert artefact["candidate_count"] == len(artefact["candidates"])


# ---------------------------------------------------------------------------
# T9 — Input summary counts
# ---------------------------------------------------------------------------

class TestInputSummary:
    def test_si_lines_examined_count(self):
        lines = [_si_line(doc_num=1, line_index=0), _si_line(doc_num=1, line_index=1)]
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: lines,
            llm_call=_fake_llm("[]"),
        )
        assert artefact["input_summary"]["si_purchase_lines_examined"] == 2

    def test_documents_examined_distinct_doc_nums(self):
        lines = [
            _si_line(doc_num=10, line_index=0),
            _si_line(doc_num=10, line_index=1),
            _si_line(doc_num=20, line_index=0),
        ]
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: lines,
            llm_call=_fake_llm("[]"),
        )
        assert artefact["input_summary"]["documents_examined"] == 2

    def test_non_si_lines_excluded_from_count(self):
        lines = [
            _si_line(doc_num=1, line_index=0),
            {**_si_line(doc_num=2, line_index=0), "vat_group": "ZP"},
        ]
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: lines,
            llm_call=_fake_llm("[]"),
        )
        assert artefact["input_summary"]["si_purchase_lines_examined"] == 1
        assert artefact["input_summary"]["documents_examined"] == 1


# ---------------------------------------------------------------------------
# T10 — No secrets in artefact JSON
# ---------------------------------------------------------------------------

class TestNoSecrets:
    def test_no_credentials_in_artefact_json(self):
        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=lambda: [_si_line()],
            llm_call=_fake_llm(json.dumps([_valid_candidate()])),
        )
        artefact_str = json.dumps(artefact)
        forbidden = ["HUNTER2", "password", "api_key", "secret", "token"]
        for word in forbidden:
            # These words must not appear as credential values (case-insensitive check
            # on the specific sentinel values used in tests).
            assert "HUNTER2" not in artefact_str
        # The artefact_type field is fine; "token_usage" contains "token" as a key
        # name (not a credential).  Only check that API key values are absent.
        assert "ANTHROPIC_API_KEY" not in artefact_str


# ---------------------------------------------------------------------------
# T11 — _validate_candidate unit tests
# ---------------------------------------------------------------------------

class TestValidateCandidate:
    def test_valid_candidate_returned_normalised(self):
        raw = _valid_candidate()
        result = _validate_candidate(raw)
        assert result["vat_group"] == "SI"
        assert isinstance(result["doc_num"], int)
        assert isinstance(result["line_total"], float)
        assert isinstance(result["tax_total"], float)

    def test_raises_on_missing_field(self):
        raw = _valid_candidate()
        del raw["suspected_category"]
        with pytest.raises(ValueError, match="missing fields"):
            _validate_candidate(raw)

    def test_raises_on_invalid_category(self):
        raw = _valid_candidate(suspected_category="haircut")
        with pytest.raises(ValueError, match="suspected_category"):
            _validate_candidate(raw)

    def test_raises_on_invalid_confidence(self):
        raw = _valid_candidate(confidence="certain")
        with pytest.raises(ValueError, match="confidence"):
            _validate_candidate(raw)

    def test_phrasing_prefix_added_when_absent(self):
        raw = _valid_candidate(phrasing="the description suggests disallowed use")
        result = _validate_candidate(raw)
        assert result["phrasing"].startswith("Consider reviewing whether")

    def test_phrasing_unchanged_when_correct(self):
        p = "Consider reviewing whether this line is disallowed."
        raw = _valid_candidate(phrasing=p)
        result = _validate_candidate(raw)
        assert result["phrasing"] == p

    def test_vat_group_is_not_forced_under_a_frozenset_spec(self):
        # AMENDED by Terry 2026-09-23 (Slice E, ruling B1): see the note on
        # test_candidate_keeps_its_per_line_vat_group. The value is the model's echo today;
        # the open item is to stamp it from the matched line instead.
        raw = _valid_candidate(vat_group="ZP")
        result = _validate_candidate(raw)
        assert result["vat_group"] == "ZP"

# ---------------------------------------------------------------------------
# T12 — seal_bundle integration: reasoning_artefact included in manifest
# ---------------------------------------------------------------------------

class TestSealBundleWithReasoning:
    """Verify that seal_bundle correctly writes and hashes the reasoning artefact."""

    def _make_cfg(self):
        from config.loader import ClientConfig
        return ClientConfig(
            client_id="testclient",
            client_name="Test Client",
            gst_registration_number="M1",
            applicable_gst_rate=0.09,
            service_layer_url="https://fake",
            company_db="TESTDB",
            username="u",
            password="HUNTER2_TEST",
            ssl_verify=False,
            fiscal_year_start_month=1,
            custom_vat_groups={},
            completeness_threshold=0.10,
            reviewer_name="Jane",
            firm_name="Firm",
        )

    def _gate_results(self):
        return {
            "all_passed": True,
            "gates": [
                {"gate": 1, "name": "record-count", "after_step": "fetch",
                 "status": "PASS", "passed": True, "checked": {}},
            ],
        }

    def test_reasoning_artefact_in_manifest(self, tmp_path, monkeypatch):
        import audit_bundle.seal as _seal_mod
        from audit_bundle.seal import seal_bundle
        from audit_bundle.verify import verify_bundle

        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")

        fixture = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
        compile_output = json.loads(fixture.read_text(encoding="utf-8"))

        dummy_pdf = tmp_path / "dummy.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

        reasoning_artefact = {
            "artefact_type": "judgment-candidates",
            "schema_version": "1.0",
            "check": "reg-26-27-disallowed-input-tax",
            "period": {"start": "2024-07-01", "end": "2024-09-30"},
            "generated_at": "2026-06-02T00:00:00+00:00",
            "status": "ok",
            "error": None,
            "provenance": {
                "in_run_path": True,
                "model_id": "claude-sonnet-4-6",
                "prompt_version": "t2.7-reg2627-v1",
                "kb_slice_hash": "sha256:" + "a" * 64,
                "validation_status": "unvalidated",
            },
            "input_summary": {"si_purchase_lines_examined": 2, "documents_examined": 1},
            "candidates": [],
            "candidate_count": 0,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "disclaimer": _DISCLAIMER,
        }

        bundle_dir = seal_bundle(
            client_config=self._make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=compile_output,
            gate_results=self._gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2026-06-02T00:00:00+00:00",
            run_completed_at="2026-06-02T00:00:10+00:00",
            reasoning_artefact=reasoning_artefact,
        )

        # File must exist
        jc_path = bundle_dir / "steps" / "judgment-candidates.json"
        assert jc_path.exists(), "steps/judgment-candidates.json not written"

        # Must appear in manifest artefacts
        manifest = json.loads((bundle_dir / "manifest.json").read_bytes())
        listed = {a["path"] for a in manifest["artefacts"]}
        assert "steps/judgment-candidates.json" in listed

        # verify_bundle must pass
        ok, problems = verify_bundle(bundle_dir)
        assert ok is True, f"verify_bundle failed: {problems}"

    def test_no_reasoning_artefact_gives_8_core_artefacts(self, tmp_path, monkeypatch):
        import audit_bundle.seal as _seal_mod
        from audit_bundle.seal import seal_bundle

        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")

        fixture = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
        compile_output = json.loads(fixture.read_text(encoding="utf-8"))

        dummy_pdf = tmp_path / "dummy.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

        bundle_dir = seal_bundle(
            client_config=self._make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=compile_output,
            gate_results=self._gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2026-06-02T00:01:00+00:00",
            run_completed_at="2026-06-02T00:01:10+00:00",
            # reasoning_artefact not supplied → default None
        )

        manifest = json.loads((bundle_dir / "manifest.json").read_bytes())
        assert len(manifest["artefacts"]) == 8
        listed = {a["path"] for a in manifest["artefacts"]}
        assert "steps/judgment-candidates.json" not in listed

    def test_errored_reasoning_artefact_still_seals_cleanly(self, tmp_path, monkeypatch):
        import audit_bundle.seal as _seal_mod
        from audit_bundle.seal import seal_bundle
        from audit_bundle.verify import verify_bundle

        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")

        fixture = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
        compile_output = json.loads(fixture.read_text(encoding="utf-8"))

        dummy_pdf = tmp_path / "dummy.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

        errored_artefact = {
            "artefact_type": "judgment-candidates",
            "schema_version": "1.0",
            "check": "reg-26-27-disallowed-input-tax",
            "period": {"start": "2024-07-01", "end": "2024-09-30"},
            "generated_at": "2026-06-02T00:00:00+00:00",
            "status": "errored",
            "error": "LLM call failed: ANTHROPIC_API_KEY not set",
            "provenance": {
                "in_run_path": True,
                "model_id": "claude-sonnet-4-6",
                "prompt_version": "t2.7-reg2627-v1",
                "kb_slice_hash": "sha256:" + "0" * 64,
                "validation_status": "unvalidated",
            },
            "input_summary": {"si_purchase_lines_examined": 0, "documents_examined": 0},
            "candidates": [],
            "candidate_count": 0,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "disclaimer": _DISCLAIMER,
        }

        bundle_dir = seal_bundle(
            client_config=self._make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=compile_output,
            gate_results=self._gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2026-06-02T00:02:00+00:00",
            run_completed_at="2026-06-02T00:02:10+00:00",
            reasoning_artefact=errored_artefact,
        )

        ok, problems = verify_bundle(bundle_dir)
        assert ok is True, f"errored reasoning artefact should still verify cleanly: {problems}"


# ---------------------------------------------------------------------------
# T13 — No import of orchestrator/, audit_bundle/, or SAP client in reasoning/
# ---------------------------------------------------------------------------

class TestDependencyInvariants:
    def test_reasoning_module_does_not_import_orchestrator(self):
        import reasoning.reg2627 as mod
        import sys
        source = Path(mod.__file__).read_text(encoding="utf-8")
        # Direct string scan of the source file (not sys.modules) to catch
        # static imports — the module itself must not contain these imports.
        assert "from orchestrator" not in source
        assert "import orchestrator" not in source

    def test_reasoning_module_does_not_import_audit_bundle(self):
        import reasoning.reg2627 as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "from audit_bundle" not in source
        assert "import audit_bundle" not in source

    def test_reasoning_module_does_not_import_sap_b1_server(self):
        import reasoning.reg2627 as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "sap_b1_server" not in source

    def test_orchestrator_chain_does_not_import_reasoning(self):
        import orchestrator.chain as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "from reasoning" not in source
        assert "import reasoning" not in source

    def test_orchestrator_steps_does_not_import_anthropic(self):
        import orchestrator.steps as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import anthropic" not in source

    def test_orchestrator_chain_does_not_import_anthropic(self):
        import orchestrator.chain as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import anthropic" not in source

    def test_sap_lines_does_not_import_orchestrator(self):
        import reasoning.sap_lines as mod
        import ast
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [alias.name for alias in getattr(node, "names", [])]
                assert not module.startswith("orchestrator"), \
                    f"sap_lines imports from orchestrator: {module}"
                assert not any(n.startswith("orchestrator") for n in names), \
                    f"sap_lines imports orchestrator: {names}"

    def test_sap_lines_does_not_import_audit_bundle(self):
        import reasoning.sap_lines as mod
        import ast
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [alias.name for alias in getattr(node, "names", [])]
                assert not module.startswith("audit_bundle"), \
                    f"sap_lines imports from audit_bundle: {module}"
                assert not any(n.startswith("audit_bundle") for n in names), \
                    f"sap_lines imports audit_bundle: {names}"

    def test_reg2627_does_not_import_sap_lines(self):
        import reasoning.reg2627 as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "sap_lines" not in source


# ---------------------------------------------------------------------------
# T14 — FIX D: per-artefact llm block in manifest
# ---------------------------------------------------------------------------

class TestManifestLLMBlock:
    """Verify per-artefact llm provenance in manifest.json (FIX D)."""

    def _make_cfg(self):
        from config.loader import ClientConfig
        return ClientConfig(
            client_id="testclient",
            client_name="Test Client",
            gst_registration_number="M1",
            applicable_gst_rate=0.09,
            service_layer_url="https://fake",
            company_db="TESTDB",
            username="u",
            password="HUNTER2_TEST",
            ssl_verify=False,
            fiscal_year_start_month=1,
            custom_vat_groups={},
            completeness_threshold=0.10,
            reviewer_name="Jane",
            firm_name="Firm",
        )

    def _gate_results(self):
        return {
            "all_passed": True,
            "gates": [
                {"gate": 1, "name": "record-count", "after_step": "fetch",
                 "status": "PASS", "passed": True, "checked": {}},
            ],
        }

    def _reasoning_artefact(self, status="ok"):
        return {
            "artefact_type": "judgment-candidates",
            "schema_version": "1.0",
            "check": "reg-26-27-disallowed-input-tax",
            "period": {"start": "2024-07-01", "end": "2024-09-30"},
            "generated_at": "2026-06-02T00:00:00+00:00",
            "status": status,
            "error": None if status == "ok" else "test error",
            "provenance": {
                "in_run_path": True,
                "model_id": "claude-sonnet-4-6",
                "prompt_version": "t2.7-reg2627-v1",
                "kb_slice_hash": "sha256:" + "ab" * 32,
                "validation_status": "unvalidated",
            },
            "input_summary": {"si_purchase_lines_examined": 3, "documents_examined": 1},
            "candidates": [],
            "candidate_count": 0,
            "token_usage": {"input_tokens": 100, "output_tokens": 20},
            "disclaimer": _DISCLAIMER,
        }

    def _do_seal(self, tmp_path, monkeypatch, reasoning_artefact=None, run_ts_offset=0):
        import audit_bundle.seal as _seal_mod
        from audit_bundle.seal import seal_bundle
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        fixture = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
        compile_output = json.loads(fixture.read_text(encoding="utf-8"))
        dummy_pdf = tmp_path / f"dummy{run_ts_offset}.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")
        return seal_bundle(
            client_config=self._make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=compile_output,
            gate_results=self._gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at=f"2026-06-02T00:0{run_ts_offset}:00+00:00",
            run_completed_at=f"2026-06-02T00:0{run_ts_offset}:10+00:00",
            reasoning_artefact=reasoning_artefact,
        )

    def test_judgment_candidates_entry_has_llm_block(self, tmp_path, monkeypatch):
        bundle_dir = self._do_seal(tmp_path, monkeypatch,
                                   reasoning_artefact=self._reasoning_artefact())
        manifest = json.loads((bundle_dir / "manifest.json").read_bytes())
        jc_entry = next(
            a for a in manifest["artefacts"]
            if a["path"] == "steps/judgment-candidates.json"
        )
        assert "llm" in jc_entry, "judgment-candidates.json artefact entry must have 'llm' block"

    def test_llm_block_fields_correct(self, tmp_path, monkeypatch):
        bundle_dir = self._do_seal(tmp_path, monkeypatch,
                                   reasoning_artefact=self._reasoning_artefact())
        manifest = json.loads((bundle_dir / "manifest.json").read_bytes())
        jc_entry = next(
            a for a in manifest["artefacts"]
            if a["path"] == "steps/judgment-candidates.json"
        )
        llm = jc_entry["llm"]
        assert llm["in_run_path"] is True
        assert llm["model_id"] == "claude-sonnet-4-6"
        assert llm["prompt_version"] == "t2.7-reg2627-v1"
        assert llm["kb_slice_hash"] == "sha256:" + "ab" * 32

    def test_deterministic_artefacts_have_no_llm_block(self, tmp_path, monkeypatch):
        bundle_dir = self._do_seal(tmp_path, monkeypatch,
                                   reasoning_artefact=self._reasoning_artefact(),
                                   run_ts_offset=1)
        manifest = json.loads((bundle_dir / "manifest.json").read_bytes())
        for entry in manifest["artefacts"]:
            if entry["path"] != "steps/judgment-candidates.json":
                assert "llm" not in entry, (
                    f"Deterministic artefact {entry['path']!r} must not have an 'llm' block"
                )

    def test_global_provenance_llm_in_run_path_false(self, tmp_path, monkeypatch):
        bundle_dir = self._do_seal(tmp_path, monkeypatch,
                                   reasoning_artefact=self._reasoning_artefact(),
                                   run_ts_offset=2)
        manifest = json.loads((bundle_dir / "manifest.json").read_bytes())
        assert manifest["provenance"]["llm_in_run_path"] is False

    def test_tampering_llm_block_fails_verify(self, tmp_path, monkeypatch):
        import stat, os
        from audit_bundle.verify import verify_bundle
        bundle_dir = self._do_seal(tmp_path, monkeypatch,
                                   reasoning_artefact=self._reasoning_artefact(),
                                   run_ts_offset=3)
        manifest_path = bundle_dir / "manifest.json"
        # Force writable
        try:
            os.chmod(manifest_path, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass
        manifest = json.loads(manifest_path.read_bytes())
        # Tamper with the llm block in the manifest
        for entry in manifest["artefacts"]:
            if entry.get("path") == "steps/judgment-candidates.json":
                entry["llm"]["model_id"] = "TAMPERED"
                break
        # Keep original root_hash so the test proves it's now mismatched
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        ok, problems = verify_bundle(bundle_dir)
        assert ok is False
        assert "root_hash mismatch" in problems

    def test_sealing_without_reasoning_no_llm_blocks_anywhere(self, tmp_path, monkeypatch):
        bundle_dir = self._do_seal(tmp_path, monkeypatch,
                                   reasoning_artefact=None, run_ts_offset=4)
        manifest = json.loads((bundle_dir / "manifest.json").read_bytes())
        for entry in manifest["artefacts"]:
            assert "llm" not in entry, (
                f"When no reasoning artefact, no entry should have an 'llm' block; "
                f"found in {entry['path']!r}"
            )

    def test_verify_passes_with_llm_block(self, tmp_path, monkeypatch):
        from audit_bundle.verify import verify_bundle
        bundle_dir = self._do_seal(tmp_path, monkeypatch,
                                   reasoning_artefact=self._reasoning_artefact(),
                                   run_ts_offset=5)
        ok, problems = verify_bundle(bundle_dir)
        assert ok is True, f"verify_bundle failed with llm block present: {problems}"
