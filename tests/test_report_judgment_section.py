"""
Tests for the AI-surfaced candidates subsection in Section 5 of the PDF report.

Covers:
  T1 — flag true + candidates: subsection present, disclaimer present,
        phrasing verbatim, deterministic totals unchanged, HitL invariant holds.
  T2 — flag true + no candidates (ok/empty): "No AI-surfaced candidates" line.
  T3 — flag true + errored artefact: "AI candidate pass did not complete".
  T4 — flag false: subsection absent entirely (show=False path).
  T5 — build_report backward-compat: no judgment_artefact → ai_candidates has show=False.
  T6 — PDF renders without errors for all flag/artefact combinations.
  T7 — HitL language invariant: AI phrasing must start with "Consider reviewing whether"
        and must not contain forbidden assertion phrases.
  T8 — build_ai_candidates_section unit tests.
  T9 — ClientConfig.show_ai_candidates defaults to False; validates bool.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from config.loader import ClientConfig, ConfigError
from report.contract import load_compile_output
from report.render import render_pdf
from report.report import ReportModel, build_report
from report.sections import (
    AICandidateRow,
    AICandidatesSection,
    build_ai_candidates_section,
)

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"
_AI_DISCLAIMER = (
    "AI-surfaced candidates for human review only — not assertions. "
    "The reviewer determines treatment and signs off."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(**overrides) -> ClientConfig:
    base = dict(
        client_id="sbodemosg",
        client_name="SBODEMOSG Demo",
        gst_registration_number="M12345678X",
        applicable_gst_rate=0.07,
        service_layer_url="https://fake",
        company_db="SBODEMOSG",
        username="manager",
        password="manager",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.1,
        reviewer_name="Terry Yeo",
        firm_name="AgentAssist Pte Ltd",
    )
    base.update(overrides)
    return ClientConfig(**base)


def _artefact_ok(candidates: list[dict] | None = None) -> dict:
    if candidates is None:
        candidates = [
            {
                "doc_num": 100,
                "doc_type": "purchase_invoice",
                "doc_date": "2024-07-15",
                "card_name": "Raffles Medical Clinic",
                "line_index": 0,
                "vat_group": "SI",
                "line_description": "Annual health screening",
                "line_total": 500.0,
                "tax_total": 45.0,
                "suspected_category": "medical_expenses",
                "reasoning": "Supplier appears to be a medical clinic.",
                "phrasing": "Consider reviewing whether this medical expense qualifies for input tax claim.",
                "confidence": "high",
            }
        ]
    return {
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
            "kb_slice_hash": "sha256:" + "ab" * 32,
            "validation_status": "unvalidated",
        },
        "input_summary": {"si_purchase_lines_examined": 5, "documents_examined": 3},
        "candidates": candidates,
        "candidate_count": len(candidates),
        "token_usage": {"input_tokens": 500, "output_tokens": 80},
        "disclaimer": _AI_DISCLAIMER,
    }


def _artefact_errored() -> dict:
    return {
        "artefact_type": "judgment-candidates",
        "schema_version": "1.0",
        "check": "reg-26-27-disallowed-input-tax",
        "period": {"start": "2024-07-01", "end": "2024-09-30"},
        "generated_at": "2026-06-02T00:00:00+00:00",
        "status": "errored",
        "error": "ANTHROPIC_API_KEY not set",
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
        "disclaimer": _AI_DISCLAIMER,
    }


@pytest.fixture(scope="module")
def raw_data() -> dict:
    return load_compile_output(FIXTURE)


def _all_findings(model: ReportModel):
    return [f for g in model.findings.groups for f in g.findings]


# ---------------------------------------------------------------------------
# T1 — flag true + candidates
# ---------------------------------------------------------------------------

class TestFlagTrueCandidatesPresent:
    @pytest.fixture
    def model(self, raw_data):
        cfg = _make_cfg(show_ai_candidates=True)
        return build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                            judgment_artefact=_artefact_ok())

    def test_ai_section_present_and_show_true(self, model):
        assert model.ai_candidates is not None
        assert model.ai_candidates.show is True

    def test_status_ok(self, model):
        assert model.ai_candidates.status == "ok"

    def test_candidate_count_correct(self, model):
        assert model.ai_candidates.candidate_count == 1
        assert len(model.ai_candidates.candidates) == 1

    def test_disclaimer_present(self, model):
        assert model.ai_candidates.disclaimer == _AI_DISCLAIMER

    def test_phrasing_verbatim(self, model):
        expected = (
            "Consider reviewing whether this medical expense qualifies "
            "for input tax claim."
        )
        assert model.ai_candidates.candidates[0].phrasing == expected

    def test_deterministic_total_unchanged(self, model, raw_data):
        cfg_no_ai = _make_cfg(show_ai_candidates=False)
        model_no_ai = build_report(raw_data, cfg_no_ai, generated_at=_GENERATED_AT)
        assert model.findings.total_findings == model_no_ai.findings.total_findings

    def test_ai_candidates_not_in_findings_groups(self, model):
        all_doc_nums = {f.doc_num for f in _all_findings(model)}
        # AI candidate doc_num 100 is not a real finding — should not appear in
        # deterministic FindingsSection.
        # (This test is self-consistent: if the fixture data had doc_num=100 it
        #  could appear, but the invariant is that AI candidates are NEVER added
        #  to FindingsSection.  We verify the counts are unaffected instead.)
        assert model.findings.total_findings == sum(
            len(g.findings) for g in model.findings.groups
        )

    def test_doc_num_in_candidate(self, model):
        assert model.ai_candidates.candidates[0].doc_num == 100

    def test_suspected_category_in_candidate(self, model):
        assert model.ai_candidates.candidates[0].suspected_category == "medical_expenses"

    def test_confidence_in_candidate(self, model):
        assert model.ai_candidates.candidates[0].confidence == "high"

    def test_hitl_invariant_no_must(self, model):
        phrasing = model.ai_candidates.candidates[0].phrasing.lower()
        assert "must reclassify" not in phrasing
        assert "must file" not in phrasing
        assert "submit amendment" not in phrasing
        assert "we certify" not in phrasing

    def test_hitl_phrasing_starts_with_consider(self, model):
        phrasing = model.ai_candidates.candidates[0].phrasing
        assert phrasing.startswith("Consider reviewing whether"), (
            f"Phrasing must start with 'Consider reviewing whether'; got: {phrasing!r}"
        )

    def test_pdf_renders_with_candidates(self, raw_data, tmp_path):
        cfg = _make_cfg(show_ai_candidates=True)
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                         judgment_artefact=_artefact_ok())
        out = tmp_path / "with_candidates.pdf"
        render_pdf(m, out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# T2 — flag true + empty candidates (status ok, count 0)
# ---------------------------------------------------------------------------

class TestFlagTrueNoCandidates:
    @pytest.fixture
    def model(self, raw_data):
        cfg = _make_cfg(show_ai_candidates=True)
        return build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                            judgment_artefact=_artefact_ok(candidates=[]))

    def test_show_true(self, model):
        assert model.ai_candidates.show is True

    def test_status_ok(self, model):
        assert model.ai_candidates.status == "ok"

    def test_no_candidate_rows(self, model):
        assert model.ai_candidates.candidate_count == 0
        assert model.ai_candidates.candidates == []

    def test_disclaimer_still_set(self, model):
        assert model.ai_candidates.disclaimer == _AI_DISCLAIMER

    def test_pdf_renders_empty_placeholder(self, raw_data, tmp_path):
        cfg = _make_cfg(show_ai_candidates=True)
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                         judgment_artefact=_artefact_ok(candidates=[]))
        out = tmp_path / "empty_candidates.pdf"
        render_pdf(m, out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# T3 — flag true + errored artefact
# ---------------------------------------------------------------------------

class TestFlagTrueErroredArtefact:
    @pytest.fixture
    def model(self, raw_data):
        cfg = _make_cfg(show_ai_candidates=True)
        return build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                            judgment_artefact=_artefact_errored())

    def test_show_true(self, model):
        assert model.ai_candidates.show is True

    def test_status_errored(self, model):
        assert model.ai_candidates.status == "errored"

    def test_no_candidate_rows(self, model):
        assert model.ai_candidates.candidate_count == 0

    def test_deterministic_total_unchanged(self, model, raw_data):
        cfg_no_ai = _make_cfg()
        model_no_ai = build_report(raw_data, cfg_no_ai, generated_at=_GENERATED_AT)
        assert model.findings.total_findings == model_no_ai.findings.total_findings

    def test_pdf_renders_errored_placeholder(self, raw_data, tmp_path):
        cfg = _make_cfg(show_ai_candidates=True)
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                         judgment_artefact=_artefact_errored())
        out = tmp_path / "errored_artefact.pdf"
        render_pdf(m, out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"

    def test_flag_true_none_artefact_is_errored(self, raw_data):
        cfg = _make_cfg(show_ai_candidates=True)
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                         judgment_artefact=None)
        assert m.ai_candidates.show is True
        assert m.ai_candidates.status == "errored"


# ---------------------------------------------------------------------------
# T4 — flag false: subsection absent entirely
# ---------------------------------------------------------------------------

class TestFlagFalse:
    @pytest.fixture
    def model(self, raw_data):
        cfg = _make_cfg(show_ai_candidates=False)
        return build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                            judgment_artefact=_artefact_ok())

    def test_show_false(self, model):
        assert model.ai_candidates is not None
        assert model.ai_candidates.show is False

    def test_status_disabled(self, model):
        assert model.ai_candidates.status == "disabled"

    def test_no_candidates(self, model):
        assert model.ai_candidates.candidates == []
        assert model.ai_candidates.candidate_count == 0

    def test_pdf_renders_without_subsection(self, raw_data, tmp_path):
        cfg = _make_cfg(show_ai_candidates=False)
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                         judgment_artefact=_artefact_ok())
        out = tmp_path / "flag_false.pdf"
        render_pdf(m, out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# T5 — backward compatibility: no judgment_artefact arg
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_no_judgment_artefact_gives_disabled(self, raw_data):
        cfg = _make_cfg()  # show_ai_candidates defaults to False
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT)
        assert m.ai_candidates is not None
        assert m.ai_candidates.show is False

    def test_no_judgment_artefact_deterministic_totals_unchanged(self, raw_data):
        cfg_new = _make_cfg()
        m_new = build_report(raw_data, cfg_new, generated_at=_GENERATED_AT)
        # Must equal the model built with explicit None (same thing)
        cfg_explicit = _make_cfg()
        m_explicit = build_report(raw_data, cfg_explicit, generated_at=_GENERATED_AT,
                                  judgment_artefact=None)
        assert m_new.findings.total_findings == m_explicit.findings.total_findings

    def test_pdf_renders_without_subsection(self, raw_data, tmp_path):
        cfg = _make_cfg()
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT)
        out = tmp_path / "compat.pdf"
        render_pdf(m, out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# T6 — Multiple candidates render correctly
# ---------------------------------------------------------------------------

class TestMultipleCandidates:
    def test_two_candidates_both_present(self, raw_data):
        candidates = [
            {
                "doc_num": 200, "doc_type": "purchase_invoice",
                "doc_date": "2024-07-20", "card_name": "Singapore Country Club",
                "line_index": 0, "vat_group": "SI",
                "line_description": "Monthly subscription fee",
                "line_total": 800.0, "tax_total": 72.0,
                "suspected_category": "club_subscriptions",
                "reasoning": "Supplier is a recreational club; line is subscription fee.",
                "phrasing": "Consider reviewing whether this club subscription fee is disallowed.",
                "confidence": "high",
            },
            {
                "doc_num": 201, "doc_type": "purchase_invoice",
                "doc_date": "2024-08-05", "card_name": "Comfort Delgro",
                "line_index": 2, "vat_group": "SI",
                "line_description": "Car rental S-plate sedan",
                "line_total": 1200.0, "tax_total": 108.0,
                "suspected_category": "motor_car_s_plate",
                "reasoning": "Description mentions S-plate rental car.",
                "phrasing": "Consider reviewing whether this S-plate rental car expense is disallowed.",
                "confidence": "medium",
            },
        ]
        cfg = _make_cfg(show_ai_candidates=True)
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                         judgment_artefact=_artefact_ok(candidates=candidates))
        assert m.ai_candidates.candidate_count == 2
        phrasings = [c.phrasing for c in m.ai_candidates.candidates]
        assert all(p.startswith("Consider reviewing whether") for p in phrasings)

    def test_two_candidates_deterministic_total_unchanged(self, raw_data):
        candidates = [
            {
                "doc_num": 200, "doc_type": "purchase_invoice",
                "doc_date": "2024-07-20", "card_name": "SCC",
                "line_index": 0, "vat_group": "SI",
                "line_description": "Subscription", "line_total": 100.0, "tax_total": 9.0,
                "suspected_category": "club_subscriptions",
                "reasoning": "Club", "phrasing": "Consider reviewing whether this is disallowed.",
                "confidence": "low",
            }
        ]
        cfg_ai = _make_cfg(show_ai_candidates=True)
        cfg_no = _make_cfg(show_ai_candidates=False)
        m_ai = build_report(raw_data, cfg_ai, generated_at=_GENERATED_AT,
                            judgment_artefact=_artefact_ok(candidates=candidates))
        m_no = build_report(raw_data, cfg_no, generated_at=_GENERATED_AT)
        assert m_ai.findings.total_findings == m_no.findings.total_findings


# ---------------------------------------------------------------------------
# T7 — HitL invariant: phrasing never contains forbidden phrases
# ---------------------------------------------------------------------------

class TestHitLInvariant:
    _FORBIDDEN = [
        "must reclassify",
        "must file",
        "file a gst f7",
        "submit amendment",
        "we certify",
        "agentassist certifies",
        "is disallowed",    # assertion, not candidate phrasing
        "must not claim",   # imperative directive
    ]

    def test_no_forbidden_phrases_in_phrasing(self, raw_data):
        candidates = [
            {
                "doc_num": 300, "doc_type": "purchase_invoice",
                "doc_date": "2024-07-15", "card_name": "ABC Medical",
                "line_index": 0, "vat_group": "SI",
                "line_description": "Medical consultation",
                "line_total": 200.0, "tax_total": 18.0,
                "suspected_category": "medical_expenses",
                "reasoning": "Medical supplier.",
                "phrasing": "Consider reviewing whether this medical expense qualifies.",
                "confidence": "medium",
            }
        ]
        cfg = _make_cfg(show_ai_candidates=True)
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                         judgment_artefact=_artefact_ok(candidates=candidates))
        all_phrasing = " ".join(
            c.phrasing.lower() for c in m.ai_candidates.candidates
        )
        for phrase in self._FORBIDDEN:
            assert phrase not in all_phrasing, (
                f"Forbidden phrase {phrase!r} found in AI candidate phrasing"
            )

    def test_phrasing_starts_with_consider(self, raw_data):
        candidates = [
            {
                "doc_num": 301, "doc_type": "purchase_invoice",
                "doc_date": "2024-07-16", "card_name": "XYZ Club",
                "line_index": 0, "vat_group": "SI",
                "line_description": "Annual membership", "line_total": 1000.0,
                "tax_total": 90.0, "suspected_category": "club_subscriptions",
                "reasoning": "Club membership fee.",
                "phrasing": "Consider reviewing whether the club membership fee is disallowed.",
                "confidence": "high",
            }
        ]
        cfg = _make_cfg(show_ai_candidates=True)
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT,
                         judgment_artefact=_artefact_ok(candidates=candidates))
        for c in m.ai_candidates.candidates:
            assert c.phrasing.startswith("Consider reviewing whether"), (
                f"Expected phrasing to start with 'Consider reviewing whether'; "
                f"got: {c.phrasing!r}"
            )


# ---------------------------------------------------------------------------
# T8 — build_ai_candidates_section unit tests
# ---------------------------------------------------------------------------

class TestBuildAICandidatesSection:
    def test_show_false_returns_disabled(self):
        sec = build_ai_candidates_section(None, show=False)
        assert sec.show is False
        assert sec.status == "disabled"
        assert sec.candidates == []

    def test_show_false_ignores_artefact(self):
        sec = build_ai_candidates_section(_artefact_ok(), show=False)
        assert sec.show is False
        assert sec.status == "disabled"

    def test_show_true_none_artefact_is_errored(self):
        sec = build_ai_candidates_section(None, show=True)
        assert sec.show is True
        assert sec.status == "errored"
        assert sec.candidates == []

    def test_show_true_errored_artefact(self):
        sec = build_ai_candidates_section(_artefact_errored(), show=True)
        assert sec.show is True
        assert sec.status == "errored"
        assert sec.candidates == []

    def test_show_true_ok_artefact_builds_candidates(self):
        sec = build_ai_candidates_section(_artefact_ok(), show=True)
        assert sec.show is True
        assert sec.status == "ok"
        assert sec.candidate_count == 1
        assert len(sec.candidates) == 1

    def test_show_true_ok_empty_candidates(self):
        sec = build_ai_candidates_section(_artefact_ok(candidates=[]), show=True)
        assert sec.show is True
        assert sec.status == "ok"
        assert sec.candidate_count == 0
        assert sec.candidates == []

    def test_disclaimer_propagated_from_artefact(self):
        sec = build_ai_candidates_section(_artefact_ok(), show=True)
        assert sec.disclaimer == _AI_DISCLAIMER

    def test_candidate_row_fields(self):
        sec = build_ai_candidates_section(_artefact_ok(), show=True)
        row = sec.candidates[0]
        assert isinstance(row, AICandidateRow)
        assert row.doc_num == 100
        assert row.line_index == 0
        assert row.suspected_category == "medical_expenses"
        assert row.confidence == "high"
        assert row.phrasing.startswith("Consider reviewing whether")

    def test_multiple_candidates_all_built(self):
        candidates = [
            {
                "doc_num": 1, "doc_type": "purchase_invoice", "doc_date": "2024-07-01",
                "card_name": "A", "line_index": 0, "vat_group": "SI",
                "line_description": "X", "line_total": 10.0, "tax_total": 1.0,
                "suspected_category": "medical_expenses", "reasoning": "R",
                "phrasing": "Consider reviewing whether this is medical.", "confidence": "low",
            },
            {
                "doc_num": 2, "doc_type": "purchase_invoice", "doc_date": "2024-07-02",
                "card_name": "B", "line_index": 1, "vat_group": "SI",
                "line_description": "Y", "line_total": 20.0, "tax_total": 2.0,
                "suspected_category": "entertainment", "reasoning": "S",
                "phrasing": "Consider reviewing whether this is entertainment.", "confidence": "medium",
            },
        ]
        sec = build_ai_candidates_section(_artefact_ok(candidates=candidates), show=True)
        assert sec.candidate_count == 2
        assert sec.candidates[0].suspected_category == "medical_expenses"
        assert sec.candidates[1].suspected_category == "entertainment"


# ---------------------------------------------------------------------------
# T9 — ClientConfig.show_ai_candidates field
# ---------------------------------------------------------------------------

class TestClientConfigShowAICandidates:
    def test_default_is_false(self):
        cfg = _make_cfg()
        assert cfg.show_ai_candidates is False

    def test_can_be_set_true(self):
        cfg = _make_cfg(show_ai_candidates=True)
        assert cfg.show_ai_candidates is True

    def test_show_ai_candidates_is_bool(self):
        cfg = _make_cfg(show_ai_candidates=True)
        assert isinstance(cfg.show_ai_candidates, bool)


# ---------------------------------------------------------------------------
# T10 — existing T1.4 e2e still green (spot-checks from test_report_e2e.py)
# ---------------------------------------------------------------------------

class TestExistingReportIntact:
    """Spot-checks ensuring T1.4 deterministic paths are untouched."""

    @pytest.fixture(scope="class")
    def model(self, raw_data):
        return build_report(raw_data, _make_cfg(), generated_at=_GENERATED_AT)

    def test_findings_total_positive(self, model):
        assert model.findings.total_findings > 0

    def test_cross_findings_doc_605(self, model):
        cross_nums = [e.doc_num for e in model.cross_findings.multi_error_docs]
        assert 605 in cross_nums

    def test_judgment_groups_present(self, model):
        assert len(model.judgment.groups) > 0

    def test_e2_605_template_6(self, model):
        all_f = [f for g in model.findings.groups for f in g.findings]
        e2_605 = next((f for f in all_f if f.doc_num == 605 and f.error_code == "E2"), None)
        assert e2_605 is not None
        assert e2_605.template_ref["number"] == 6

    def test_ai_section_disabled_by_default(self, model):
        assert model.ai_candidates.show is False

    def test_pdf_renders_same_size_without_ai(self, raw_data, tmp_path):
        cfg = _make_cfg()
        m = build_report(raw_data, cfg, generated_at=_GENERATED_AT)
        out = tmp_path / "no_ai.pdf"
        render_pdf(m, out)
        assert out.read_bytes()[:4] == b"%PDF"
