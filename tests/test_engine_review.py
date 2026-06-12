"""
Hermetic seam tests for engine/review.py.  No live SAP, no live Anthropic API.

Covers:
    T1 — composition order: chain → reasoning → report → seal (ordered)
    T2 — ReviewResult shape on completed run
    T3 — halted path (GateFailure → status="halted", no bundle, gate_failure set)
    T4 — reasoning failure is non-blocking (errored artefact → completed, bundle sealed)
    T5 — behavior equivalence: seal_bundle receives the correct arguments from review()
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.loader import ClientConfig
from orchestrator.exceptions import GateFailure

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"

_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}
_CLIENT = "testclient"

# String patch targets — always patch names in the module that uses them.
_MOD = "engine.review"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_cfg() -> ClientConfig:
    return ClientConfig(
        client_id=_CLIENT,
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


def _make_gate_results() -> dict:
    return {
        "all_passed": True,
        "gates": [
            {
                "gate": i,
                "name": f"gate-{i}",
                "after_step": "step",
                "status": "PASS",
                "passed": True,
                "checked": {},
            }
            for i in range(1, 6)
        ],
    }


def _errored_reasoning() -> dict:
    return {
        "artefact_type": "judgment-candidates",
        "schema_version": "1.0",
        "check": "reg-26-27-disallowed-input-tax",
        "period": _PERIOD,
        "generated_at": "2024-10-01T00:00:00+00:00",
        "status": "errored",
        "error": "ANTHROPIC_API_KEY environment variable is not set",
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
        "disclaimer": "AI-surfaced candidates for human review only.",
    }


def _ok_reasoning() -> dict:
    d = _errored_reasoning()
    d["status"] = "ok"
    d["error"] = None
    return d


def _fake_line_source():
    return []


def _mock_render_pdf(model, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF dummy")


# ---------------------------------------------------------------------------
# T1 — Composition order
# ---------------------------------------------------------------------------

class TestCompositionOrder:
    """review() must call chain → reasoning → seal in that order."""

    def test_happy_path_order(self, tmp_path):
        compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
        call_order: list[str] = []

        def _chain(*a, **kw):
            call_order.append("run_chain")
            return compile_output, _make_gate_results()

        def _reasoning(period, *, line_source, **kw):
            call_order.append("run_reg2627_pass")
            return _ok_reasoning()

        def _build(*a, **kw):
            call_order.append("build_report")
            return MagicMock()

        def _render(model, path):
            call_order.append("render_pdf")
            _mock_render_pdf(model, path)

        def _seal(**kw):
            call_order.append("seal_bundle")
            return tmp_path / "bundle"

        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain", _chain), \
             patch(f"{_MOD}.run_reg2627_pass", _reasoning), \
             patch(f"{_MOD}.build_report", _build), \
             patch(f"{_MOD}.render_pdf", _render), \
             patch(f"{_MOD}.seal_bundle", _seal), \
             patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
            review(_make_cfg(), _PERIOD, ReviewInputs(line_source=_fake_line_source))

        assert call_order[0] == "run_chain", f"chain must be first; got {call_order}"
        assert call_order[-1] == "seal_bundle", f"seal must be last; got {call_order}"
        assert "run_reg2627_pass" in call_order
        chain_idx = call_order.index("run_chain")
        reasoning_idx = call_order.index("run_reg2627_pass")
        seal_idx = call_order.index("seal_bundle")
        assert chain_idx < reasoning_idx < seal_idx

    def test_gate_failure_stops_before_reasoning(self, tmp_path):
        """On GateFailure, reasoning and seal must never be called."""
        reasoning_called = []
        seal_called = []

        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain",
                   side_effect=GateFailure("Gate 2 failed", checked={"box_4": 999.0})), \
             patch(f"{_MOD}.run_reg2627_pass",
                   side_effect=lambda *a, **kw: reasoning_called.append(True) or _ok_reasoning()), \
             patch(f"{_MOD}.seal_bundle",
                   side_effect=lambda **kw: seal_called.append(True) or tmp_path / "bundle"):
            result = review(_make_cfg(), _PERIOD, ReviewInputs(line_source=_fake_line_source))

        assert result.status == "halted"
        assert reasoning_called == [], "reasoning must not be called on GateFailure"
        assert seal_called == [], "seal must not be called on GateFailure"


# ---------------------------------------------------------------------------
# T2 — ReviewResult shape on completed run
# ---------------------------------------------------------------------------

class TestReviewResultShapeCompleted:
    def test_all_fields_populated(self, tmp_path):
        compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
        gate_results = _make_gate_results()
        dummy_bundle = tmp_path / "bundle"

        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain", return_value=(compile_output, gate_results)), \
             patch(f"{_MOD}.run_reg2627_pass", return_value=_ok_reasoning()), \
             patch(f"{_MOD}.build_report", return_value=MagicMock()), \
             patch(f"{_MOD}.render_pdf", _mock_render_pdf), \
             patch(f"{_MOD}.seal_bundle", return_value=dummy_bundle), \
             patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
            result = review(_make_cfg(), _PERIOD, ReviewInputs(line_source=_fake_line_source))

        assert result.status == "completed"
        assert result.compile_output is compile_output
        assert result.gate_results is gate_results
        assert result.reasoning_artefact["status"] == "ok"
        assert result.document_candidates is None        # no provider
        assert result.analytical_review_data is None     # analytical_review=False
        assert isinstance(result.report_pdf_path, Path)
        assert result.bundle_dir == dummy_bundle
        assert result.run_started_at is not None
        assert result.run_completed_at is not None
        assert result.run_started_at <= result.run_completed_at
        assert result.gate_failure is None

    def test_analytical_review_data_forwarded(self, tmp_path):
        """When analytical_review=True, result.analytical_review_data is populated."""
        compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
        ar_data = {"ratio": 1.5, "findings": [{"finding_type": "TP_TS_HIGH"}]}

        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain",
                   return_value=(compile_output, _make_gate_results())), \
             patch(f"{_MOD}.run_reg2627_pass", return_value=_ok_reasoning()), \
             patch(f"{_MOD}.run_analytical_review_pass", return_value=ar_data), \
             patch(f"{_MOD}.build_report", return_value=MagicMock()), \
             patch(f"{_MOD}.render_pdf", _mock_render_pdf), \
             patch(f"{_MOD}.seal_bundle", return_value=tmp_path / "bundle"), \
             patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
            inputs = ReviewInputs(line_source=_fake_line_source, analytical_review=True)
            result = review(_make_cfg(), _PERIOD, inputs)

        assert result.analytical_review_data is ar_data


# ---------------------------------------------------------------------------
# T3 — Halted path: GateFailure → status="halted", no bundle, gate_failure set
# ---------------------------------------------------------------------------

class TestHaltedPath:
    def _run_halted(self, tmp_path, checked=None):
        checked = checked if checked is not None else {"box_4": 999.0, "box_1_2_3_sum": 100.0}
        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain",
                   side_effect=GateFailure("Gate 2 box-reconciliation", checked=checked)), \
             patch(f"{_MOD}.seal_bundle",
                   side_effect=AssertionError("must not seal on GateFailure")):
            return review(_make_cfg(), _PERIOD, ReviewInputs(line_source=_fake_line_source))

    def test_status_is_halted(self, tmp_path):
        assert self._run_halted(tmp_path).status == "halted"

    def test_bundle_dir_is_none(self, tmp_path):
        assert self._run_halted(tmp_path).bundle_dir is None

    def test_compile_output_is_none(self, tmp_path):
        assert self._run_halted(tmp_path).compile_output is None

    def test_gate_results_is_none(self, tmp_path):
        assert self._run_halted(tmp_path).gate_results is None

    def test_gate_failure_message_and_checked(self, tmp_path):
        checked = {"box_4": 999.0, "box_1_2_3_sum": 100.0}
        result = self._run_halted(tmp_path, checked=checked)
        assert result.gate_failure is not None
        assert "Gate 2" in result.gate_failure.message
        assert result.gate_failure.checked == checked

    def test_gate_failure_is_plain_record(self, tmp_path):
        """GateHalt must be a plain serialisable dataclass, not a live exception."""
        result = self._run_halted(tmp_path)
        from engine.review import GateHalt
        assert isinstance(result.gate_failure, GateHalt)
        d = asdict(result.gate_failure)
        assert "message" in d
        assert "checked" in d

    def test_run_started_at_set_run_completed_at_none(self, tmp_path):
        result = self._run_halted(tmp_path)
        assert result.run_started_at is not None
        assert result.run_completed_at is None


# ---------------------------------------------------------------------------
# T4 — Reasoning failure is non-blocking
# ---------------------------------------------------------------------------

class TestReasoningFailureNonBlocking:
    def test_errored_reasoning_still_completes(self, tmp_path):
        """A status='errored' reasoning artefact must not prevent sealing."""
        compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
        dummy_bundle = tmp_path / "bundle"

        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain",
                   return_value=(compile_output, _make_gate_results())), \
             patch(f"{_MOD}.run_reg2627_pass", return_value=_errored_reasoning()), \
             patch(f"{_MOD}.build_report", return_value=MagicMock()), \
             patch(f"{_MOD}.render_pdf", _mock_render_pdf), \
             patch(f"{_MOD}.seal_bundle", return_value=dummy_bundle), \
             patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
            result = review(_make_cfg(), _PERIOD, ReviewInputs(line_source=_fake_line_source))

        assert result.status == "completed"
        assert result.bundle_dir == dummy_bundle
        assert result.reasoning_artefact["status"] == "errored"

    def test_errored_reasoning_artefact_forwarded_to_seal(self, tmp_path):
        """The errored artefact must be forwarded to seal_bundle as reasoning_artefact."""
        compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
        errored = _errored_reasoning()
        seal_kwargs: dict = {}

        def _capture(**kw):
            seal_kwargs.update(kw)
            return tmp_path / "bundle"

        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain",
                   return_value=(compile_output, _make_gate_results())), \
             patch(f"{_MOD}.run_reg2627_pass", return_value=errored), \
             patch(f"{_MOD}.build_report", return_value=MagicMock()), \
             patch(f"{_MOD}.render_pdf", _mock_render_pdf), \
             patch(f"{_MOD}.seal_bundle", side_effect=_capture), \
             patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
            review(_make_cfg(), _PERIOD, ReviewInputs(line_source=_fake_line_source))

        assert seal_kwargs.get("reasoning_artefact") is errored


# ---------------------------------------------------------------------------
# T5 — Behavior equivalence: seal_bundle receives the correct arguments
# ---------------------------------------------------------------------------

class TestBehaviorEquivalence:
    def test_seal_receives_compile_output_and_gate_results(self, tmp_path):
        compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
        gate_results = _make_gate_results()
        seal_kwargs: dict = {}

        def _capture(**kw):
            seal_kwargs.update(kw)
            return tmp_path / "bundle"

        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain", return_value=(compile_output, gate_results)), \
             patch(f"{_MOD}.run_reg2627_pass", return_value=_ok_reasoning()), \
             patch(f"{_MOD}.build_report", return_value=MagicMock()), \
             patch(f"{_MOD}.render_pdf", _mock_render_pdf), \
             patch(f"{_MOD}.seal_bundle", side_effect=_capture), \
             patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
            result = review(_make_cfg(), _PERIOD, ReviewInputs(line_source=_fake_line_source))

        assert seal_kwargs["compile_output"] is compile_output
        assert seal_kwargs["gate_results"] is gate_results
        assert seal_kwargs["period"] == _PERIOD
        assert seal_kwargs["run_started_at"] == result.run_started_at
        assert seal_kwargs["run_completed_at"] == result.run_completed_at

    def test_seal_receives_declared_f5_when_provided(self, tmp_path):
        compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
        declared = {"period": _PERIOD, "boxes": {"box_1": 100.0}}
        seal_kwargs: dict = {}

        def _capture(**kw):
            seal_kwargs.update(kw)
            return tmp_path / "bundle"

        from engine.review import ReviewInputs, review
        with patch(f"{_MOD}.run_chain",
                   return_value=(compile_output, _make_gate_results())), \
             patch(f"{_MOD}.run_reg2627_pass", return_value=_ok_reasoning()), \
             patch(f"{_MOD}.build_report", return_value=MagicMock()), \
             patch(f"{_MOD}.render_pdf", _mock_render_pdf), \
             patch(f"{_MOD}.seal_bundle", side_effect=_capture), \
             patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
            inputs = ReviewInputs(line_source=_fake_line_source, declared_f5=declared)
            review(_make_cfg(), _PERIOD, inputs)

        assert seal_kwargs.get("declared_f5") is declared
