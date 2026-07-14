"""
T2.30 — exempt stream wiring through engine/review.py (hermetic).

The exempt pass runs beside the chain (Phase 2b) ONLY when
ReviewInputs.sales_line_source is provided, and its artefact routes through the
T2.27 extra_* seams: seal_bundle(extra_reasoning_artefacts={"exempt-supply": …})
→ steps/exempt-supply-candidates.json, and build_report(extra_judgment_artefacts=…)
→ gated ReportModel.extra_candidates.

Hard safety claims asserted here:
  * default (no sales_line_source) → run_exempt_pass NOT called; reg2627-only
    behaviour byte-identical (compile_output / gates / reasoning artefact equal).
  * reg2627's own path untouched: judgment-candidates.json key intact.
  * the exempt stream renders ONLY under show_ai_candidates=True (default False
    → hidden); F5 boxes + gates byte-identical with/without the exempt pass.

No live SAP, no live Anthropic.  Patch targets are names in engine.review.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.loader import ClientConfig

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}
_MOD = "engine.review"


def _make_cfg(**over) -> ClientConfig:
    base = dict(
        client_id="testclient",
        client_name="Test Client Pte Ltd",
        gst_registration_number="M90000001A",
        applicable_gst_rate=0.09,
        service_layer_url="https://fake",
        company_db="TESTDB",
        username="u",
        password="HUNTER2_TEST",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.10,
        reviewer_name="Jane Tan",
        firm_name="Tan & Associates",
    )
    base.update(over)
    return ClientConfig(**base)


def _gate_results() -> dict:
    return {
        "all_passed": True,
        "gates": [
            {"gate": i, "name": f"gate-{i}", "after_step": "step",
             "status": "PASS", "passed": True, "checked": {}}
            for i in range(1, 6)
        ],
    }


def _reg_artefact() -> dict:
    return {
        "artefact_type": "judgment-candidates", "schema_version": "1.0",
        "check": "reg-26-27-disallowed-input-tax", "period": _PERIOD,
        "generated_at": "2024-10-01T00:00:00+00:00", "status": "ok", "error": None,
        "provenance": {"in_run_path": True, "model_id": "claude-sonnet-4-6",
                       "prompt_version": "t2.7-reg2627-v1",
                       "kb_slice_hash": "sha256:" + "a" * 64,
                       "validation_status": "unvalidated"},
        "input_summary": {"si_purchase_lines_examined": 0, "documents_examined": 0},
        "candidates": [], "candidate_count": 0,
        "token_usage": {"input_tokens": 0, "output_tokens": 0},
        "disclaimer": "AI-surfaced candidates for human review only.",
    }


def _exempt_artefact(status: str = "ok") -> dict:
    return {
        "artefact_type": "exempt-supply-candidates", "schema_version": "1.0",
        "check": "exempt-supply-misclassification", "period": _PERIOD,
        "generated_at": "2024-10-01T00:00:00+00:00", "status": status,
        "error": None if status == "ok" else "boom",
        "provenance": {"in_run_path": True, "model_id": "claude-sonnet-4-6",
                       "prompt_version": "t2.30-exempt-supply-v1",
                       "kb_slice_hash": "sha256:" + "b" * 64,
                       "validation_status": "unvalidated"},
        "input_summary": {"exempt_sales_lines_examined": 2, "documents_examined": 2},
        "candidates": [], "candidate_count": 0,
        "token_usage": {"input_tokens": 0, "output_tokens": 0},
        "disclaimer": "AI-surfaced candidates for human review only.",
    }


def _sales_lines():
    return [{"doc_num": 1, "doc_type": "sales_invoice", "doc_date": "2024-08-01",
             "card_name": "C", "line_index": 0, "vat_group": "ES33",
             "line_description": "BROKERAGE", "line_total": 100.0, "tax_total": 0.0}]


def _mock_render(model, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF dummy")


def _run_review(tmp_path, *, sales=None, capture: dict | None = None,
                exempt_impl=None):
    """Run review() with chain/reg2627/exempt/report/render/seal patched."""
    compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cap = capture if capture is not None else {}

    def _chain(*a, **kw):
        return compile_output, _gate_results()

    def _reg(period, *, line_source, **kw):
        return _reg_artefact()

    def _exempt(period, *, line_source, **kw):
        cap["exempt_called_with_line_source"] = line_source
        return _exempt_artefact()

    def _build(*a, **kw):
        cap["build_report_kwargs"] = kw
        return MagicMock()

    def _seal(**kw):
        cap["seal_kwargs"] = kw
        return tmp_path / "bundle"

    from engine.review import ReviewInputs, review
    inputs = (ReviewInputs(line_source=lambda: [], sales_line_source=sales)
              if sales is not None else ReviewInputs(line_source=lambda: []))
    with patch(f"{_MOD}.run_chain", _chain), \
         patch(f"{_MOD}.run_reg2627_pass", _reg), \
         patch(f"{_MOD}.run_exempt_pass", exempt_impl or _exempt), \
         patch(f"{_MOD}.build_report", _build), \
         patch(f"{_MOD}.render_pdf", _mock_render), \
         patch(f"{_MOD}.seal_bundle", _seal), \
         patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
        result = review(_make_cfg(), _PERIOD, inputs)
    return result, cap


# ---------------------------------------------------------------------------
# 1. Default path — exempt pass NOT run; reg2627-only byte-identical
# ---------------------------------------------------------------------------

class TestDefaultPathByteIdentical:
    def test_sales_line_source_defaults_none(self):
        from engine.review import ReviewInputs
        inputs = ReviewInputs(line_source=lambda: [])
        assert inputs.sales_line_source is None

    def test_exempt_not_called_and_no_extra_kwargs_when_default(self, tmp_path):
        result, cap = self._run_default(tmp_path)
        assert "exempt_called_with_line_source" not in cap
        # reg2627-only call shape: no extra_* forwarded (or None), so report/seal
        # behave byte-identically to pre-T2.30.
        assert not cap["build_report_kwargs"].get("extra_judgment_artefacts")
        assert not cap["seal_kwargs"].get("extra_reasoning_artefacts")
        assert result.exempt_artefact is None

    def _run_default(self, tmp_path):
        cap: dict = {}

        def _exempt(period, *, line_source, **kw):
            cap["exempt_called_with_line_source"] = line_source
            return _exempt_artefact()

        return (*_run_review(tmp_path, sales=None, capture=cap, exempt_impl=_exempt),)

    def test_boxes_and_gates_byte_identical_with_and_without(self, tmp_path):
        r_without, _ = _run_review(tmp_path, sales=None)
        r_with, _ = _run_review(tmp_path, sales=_sales_lines)
        assert json.dumps(r_without.compile_output, sort_keys=True) == \
               json.dumps(r_with.compile_output, sort_keys=True)
        assert json.dumps(r_without.gate_results, sort_keys=True) == \
               json.dumps(r_with.gate_results, sort_keys=True)
        assert r_without.reasoning_artefact == r_with.reasoning_artefact


# ---------------------------------------------------------------------------
# 2. Wired path — exempt runs; artefact routed through the T2.27 seams
# ---------------------------------------------------------------------------

class TestWiredPath:
    def test_exempt_called_with_sales_line_source(self, tmp_path):
        result, cap = _run_review(tmp_path, sales=_sales_lines)
        assert cap["exempt_called_with_line_source"] is _sales_lines

    def test_artefact_routed_to_seal_under_skill_id(self, tmp_path):
        result, cap = _run_review(tmp_path, sales=_sales_lines)
        extra = cap["seal_kwargs"]["extra_reasoning_artefacts"]
        assert set(extra.keys()) == {"exempt-supply"}
        assert extra["exempt-supply"]["check"] == "exempt-supply-misclassification"

    def test_artefact_routed_to_report_under_skill_id(self, tmp_path):
        result, cap = _run_review(tmp_path, sales=_sales_lines)
        extra = cap["build_report_kwargs"]["extra_judgment_artefacts"]
        assert set(extra.keys()) == {"exempt-supply"}

    def test_result_carries_exempt_artefact(self, tmp_path):
        result, cap = _run_review(tmp_path, sales=_sales_lines)
        assert result.exempt_artefact is not None
        assert result.exempt_artefact["artefact_type"] == "exempt-supply-candidates"

    def test_reg2627_stream_untouched(self, tmp_path):
        result, cap = _run_review(tmp_path, sales=_sales_lines)
        # reg2627 still rides its own dedicated parameters, not the extra_* seams.
        assert cap["build_report_kwargs"]["judgment_artefact"]["check"] == \
               "reg-26-27-disallowed-input-tax"
        assert cap["seal_kwargs"]["reasoning_artefact"]["check"] == \
               "reg-26-27-disallowed-input-tax"

    def test_errored_exempt_pass_is_non_blocking(self, tmp_path):
        def _errored(period, *, line_source, **kw):
            return _exempt_artefact(status="errored")
        result, cap = _run_review(tmp_path, sales=_sales_lines, exempt_impl=_errored)
        assert result.status == "completed"
        extra = cap["seal_kwargs"]["extra_reasoning_artefacts"]
        assert extra["exempt-supply"]["status"] == "errored"


# ---------------------------------------------------------------------------
# 3. Real seal — bundle key on disk, reg2627 key intact
# ---------------------------------------------------------------------------

class TestRealSealBundleKey:
    def test_exempt_seals_to_own_key_reg2627_intact(self, tmp_path, monkeypatch):
        import audit_bundle.seal as _seal_mod
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))

        def _chain(*a, **kw):
            return compile_output, _gate_results()

        def _reg(period, *, line_source, **kw):
            return _reg_artefact()

        def _exempt(period, *, line_source, **kw):
            return _exempt_artefact()

        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain", _chain), \
             patch(f"{_MOD}.run_reg2627_pass", _reg), \
             patch(f"{_MOD}.run_exempt_pass", _exempt), \
             patch(f"{_MOD}.build_report", lambda *a, **kw: MagicMock()), \
             patch(f"{_MOD}.render_pdf", _mock_render), \
             patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
            result = review(_make_cfg(), _PERIOD,
                            ReviewInputs(line_source=lambda: [],
                                         sales_line_source=_sales_lines))

        bundle = result.bundle_dir
        assert (bundle / "steps" / "exempt-supply-candidates.json").exists()
        assert (bundle / "steps" / "judgment-candidates.json").exists()
        manifest = json.loads((bundle / "manifest.json").read_bytes())
        listed = {a["path"] for a in manifest["artefacts"]}
        assert "steps/exempt-supply-candidates.json" in listed
        assert "steps/judgment-candidates.json" in listed


# ---------------------------------------------------------------------------
# 4. Freeze gate — exempt stream hidden unless show_ai_candidates=True
# ---------------------------------------------------------------------------

class TestFreezeGate:
    def _model(self, show: bool):
        from report.contract import load_compile_output
        from report.report import build_report
        cfg = _make_cfg(show_ai_candidates=show) if show else _make_cfg()
        return build_report(
            load_compile_output(FIXTURE), cfg,
            generated_at="2024-10-01T00:00:00+00:00",
            extra_judgment_artefacts={"exempt-supply": _exempt_artefact()},
        )

    def test_hidden_by_default(self):
        m = self._model(show=False)
        assert m.extra_candidates["exempt-supply"].show is False

    def test_rendered_nothing_when_gate_off(self):
        import types
        from report.render import _extra_candidates_subsections
        m = self._model(show=False)
        story: list = []
        _extra_candidates_subsections(
            types.SimpleNamespace(extra_candidates=m.extra_candidates), story)
        assert story == []

    def test_visible_only_when_flag_true(self):
        m = self._model(show=True)
        assert m.extra_candidates["exempt-supply"].show is True


# ---------------------------------------------------------------------------
# 5. run_agent binding — sales partial wired (source-level)
# ---------------------------------------------------------------------------

class TestRunAgentBinding:
    def test_run_agent_binds_fetch_sales_lines(self):
        src = (Path(__file__).parent.parent / "run_agent.py").read_text(encoding="utf-8")
        assert "fetch_sales_lines" in src
        assert "sales_line_source" in src
