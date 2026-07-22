"""tests/test_review_persist_flag.py — BUILD ID t-xero-signoff, FAILING-FIRST (Contract A).

Written BEFORE the implementation exists; MUST fail today for the RIGHT reason — the feature
is absent, not a typo: ``review()`` accepts no ``persist_artifacts`` keyword and ALWAYS runs
Phase-5 (build_report / render_pdf / seal_bundle) today — the conditional skip does not exist.

DESIGN NOTE (T5.8 tripwire): ``persist_artifacts`` is a KEYWORD-ONLY parameter on
``review()`` — deliberately NOT a ``ReviewInputs`` field, because the T5.8 artifact
contract (tests/test_t58_artifact_contract.py) freezes that dataclass's field set and
persistence is execution POLICY, not review input data. The frozen contract stays intact.

HARD INVARIANT PINNED HERE (three-times rule — prompt + code + THIS test):
  * M2 SKIP — ``review(..., persist_artifacts=False)`` skips build_report / render_pdf /
    seal_bundle ENTIRELY: ``report_pdf_path is None`` and ``bundle_dir is None`` while the
    review still ``status="completed"`` and carries its compile_output / gate_results /
    reasoning_artefact unchanged, with ``run_completed_at`` still a timestamp. The default
    (keyword omitted, ``persist_artifacts=True``) is byte-identical to today: seal_bundle IS
    called, ``report_pdf_path`` is a Path, ``bundle_dir`` is the sealed dir.

Mirrors tests/test_engine_review.py's mock/monkeypatch style (patch engine.review.* with
recording fakes; drive review() with a minimal fake line_source). Minimal fakes are
RE-CREATED here — the existing test file is off-limits and exposes no importable helpers.
Hermetic: SAP off, no anthropic, no tokens.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.loader import ClientConfig

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"

_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}
_MOD = "engine.review"


# ── Minimal fakes (re-created; not imported from test_engine_review.py) ───────────────

def _make_cfg() -> ClientConfig:
    return ClientConfig(
        client_id="persistclient",
        client_name="Persist Client Pte Ltd",
        gst_registration_number="M90000009A",
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
            {"gate": i, "name": f"gate-{i}", "after_step": "step",
             "status": "PASS", "passed": True, "checked": {}}
            for i in range(1, 6)
        ],
    }


def _ok_reasoning() -> dict:
    return {
        "artefact_type": "judgment-candidates",
        "schema_version": "1.0",
        "check": "reg-26-27-disallowed-input-tax",
        "period": _PERIOD,
        "generated_at": "2024-10-01T00:00:00+00:00",
        "status": "ok",
        "error": None,
        "provenance": {
            "in_run_path": True, "model_id": "claude-sonnet-4-6",
            "prompt_version": "t2.7-reg2627-v1",
            "kb_slice_hash": "sha256:" + "0" * 64,
            "validation_status": "unvalidated",
        },
        "input_summary": {"si_purchase_lines_examined": 0, "documents_examined": 0},
        "candidates": [], "candidate_count": 0,
        "token_usage": {"input_tokens": 0, "output_tokens": 0},
        "disclaimer": "AI-surfaced candidates for human review only.",
    }


def _fake_line_source():
    return []


def _mock_render_pdf(model, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF dummy")


# ── A1. persist_artifacts is a keyword-only review() param; ReviewInputs stays frozen ──

def test_persist_artifacts_is_review_kwarg_not_inputs_field():
    import inspect

    from engine.review import ReviewInputs, review

    # The keyword exists on review(), defaults True, and is keyword-only.
    param = inspect.signature(review).parameters["persist_artifacts"]
    assert param.default is True
    assert param.kind is inspect.Parameter.KEYWORD_ONLY

    # The T5.8-frozen ReviewInputs field set is NOT extended (tripwire respected).
    assert "persist_artifacts" not in {f for f in ReviewInputs.__dataclass_fields__}


# ── A2. persist_artifacts=False SKIPS build_report / render_pdf / seal_bundle ─────────

def test_persist_false_skips_seal_render_build(tmp_path):
    compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
    gate_results = _make_gate_results()
    called: list[str] = []

    def rec_build(*a, **kw):
        called.append("build_report")
        return MagicMock()

    def rec_render(model, path):
        called.append("render_pdf")
        _mock_render_pdf(model, path)

    def rec_seal(**kw):
        called.append("seal_bundle")
        return tmp_path / "bundle"

    from engine.review import ReviewInputs, review
    with patch(f"{_MOD}.run_chain", return_value=(compile_output, gate_results)), \
         patch(f"{_MOD}.run_reg2627_pass", return_value=_ok_reasoning()), \
         patch(f"{_MOD}.build_report", rec_build), \
         patch(f"{_MOD}.render_pdf", rec_render), \
         patch(f"{_MOD}.seal_bundle", rec_seal), \
         patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
        result = review(
            _make_cfg(), _PERIOD,
            ReviewInputs(line_source=_fake_line_source),
            persist_artifacts=False,
        )

    # The three persistence stages are skipped ENTIRELY.
    assert "build_report" not in called
    assert "render_pdf" not in called
    assert "seal_bundle" not in called

    # The review still completed and carries its deterministic + reasoning payload unchanged.
    assert result.status == "completed"
    assert result.report_pdf_path is None
    assert result.bundle_dir is None
    assert result.compile_output is compile_output
    assert result.gate_results is gate_results
    assert result.reasoning_artefact["status"] == "ok"
    assert result.run_started_at is not None
    # run_completed_at is still stamped even though nothing was sealed.
    assert result.run_completed_at is not None


# ── A3. default (flag omitted) is byte-identical to today: seal IS called ──────────────

def test_default_persist_still_seals(tmp_path):
    compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
    dummy_bundle = tmp_path / "bundle"
    called: list[str] = []

    def rec_seal(**kw):
        called.append("seal_bundle")
        return dummy_bundle

    from engine.review import ReviewInputs, review
    with patch(f"{_MOD}.run_chain", return_value=(compile_output, _make_gate_results())), \
         patch(f"{_MOD}.run_reg2627_pass", return_value=_ok_reasoning()), \
         patch(f"{_MOD}.build_report", return_value=MagicMock()), \
         patch(f"{_MOD}.render_pdf", _mock_render_pdf), \
         patch(f"{_MOD}.seal_bundle", side_effect=rec_seal), \
         patch(f"{_MOD}._REPORTS_DIR", tmp_path / "reports"):
        result = review(_make_cfg(), _PERIOD, ReviewInputs(line_source=_fake_line_source))

    assert "seal_bundle" in called
    assert result.status == "completed"
    assert isinstance(result.report_pdf_path, Path)
    assert result.bundle_dir == dummy_bundle
