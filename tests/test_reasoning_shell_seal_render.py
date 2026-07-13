"""
T2.27 — second reasoning stream: bundle key + report gate.

Proves the attach seam generalizes to a SECOND reasoning skill without
touching reg2627's stream:

  * seal_bundle accepts extra_reasoning_artefacts keyed by skill_id and seals
    each to steps/<skill_id>-candidates.json.  reg2627 keeps its exact key
    steps/judgment-candidates.json (byte-identical; the 8-core-artefact count
    test in test_reasoning_reg2627.py still holds because the new parameter
    defaults to None).
  * build_report accepts extra_judgment_artefacts and routes each through the
    SAME gated builder (build_ai_candidates_section, show=show_ai_candidates),
    exposing them on ReportModel.extra_candidates.
  * The renderer draws the extra stream ONLY when show=True — the freeze gate
    (show_ai_candidates=False) covers the second stream, and no ungated
    deterministic path renders it.

TEST-ONLY stub artefact; no tax semantics.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from audit_bundle.canonical import canonical_json
from config.loader import ClientConfig
from report.contract import load_compile_output
from report.report import build_report
from report.render import _extra_candidates_subsections
from report.sections import build_ai_candidates_section

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-02T00:00:00+00:00"


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


def _stub_artefact(candidates: list[dict] | None = None) -> dict:
    if candidates is None:
        candidates = [
            {
                "doc_num": 9001, "doc_type": "Invoice", "doc_date": "2024-01-05",
                "card_name": "ALPHA", "line_index": 0, "vat_group": "ZZ",
                "line_description": "STUB LINE ALPHA", "line_total": 100.0,
                "tax_total": 9.0, "suspected_category": "stub_flagged",
                "reasoning": "stub reason",
                "phrasing": "Consider reviewing whether the stub applies",
                "confidence": "low",
            }
        ]
    return {
        "artefact_type": "reasoning-candidates",
        "schema_version": "1.0",
        "check": "stub-check-not-a-rule",
        "period": {"start": "2024-07-01", "end": "2024-09-30"},
        "generated_at": _GENERATED_AT,
        "status": "ok",
        "error": None,
        "provenance": {
            "in_run_path": True,
            "model_id": "stub-model",
            "prompt_version": "t2.27-stub-v1",
            "kb_slice_hash": "sha256:" + "cd" * 32,
            "validation_status": "unvalidated",
        },
        "input_summary": {"stub_lines_examined": 2, "documents_examined": 2},
        "candidates": candidates,
        "candidate_count": len(candidates),
        "token_usage": {"input_tokens": 5, "output_tokens": 12},
        "disclaimer": "STUB — candidates for human review only.",
    }


def _reg_artefact() -> dict:
    return {
        "artefact_type": "judgment-candidates",
        "schema_version": "1.0",
        "check": "reg-26-27-disallowed-input-tax",
        "period": {"start": "2024-07-01", "end": "2024-09-30"},
        "generated_at": _GENERATED_AT,
        "status": "ok",
        "error": None,
        "provenance": {
            "in_run_path": True, "model_id": "claude-sonnet-4-6",
            "prompt_version": "t2.7-reg2627-v1",
            "kb_slice_hash": "sha256:" + "a" * 64,
            "validation_status": "unvalidated",
        },
        "input_summary": {"si_purchase_lines_examined": 2, "documents_examined": 1},
        "candidates": [], "candidate_count": 0,
        "token_usage": {"input_tokens": 0, "output_tokens": 0},
        "disclaimer": "d",
    }


def _gate_results():
    return {
        "all_passed": True,
        "gates": [
            {"gate": 1, "name": "record-count", "after_step": "fetch",
             "status": "PASS", "passed": True, "checked": {}},
        ],
    }


# ---------------------------------------------------------------------------
# seal_bundle: second bundle key
# ---------------------------------------------------------------------------

class TestSealSecondBundleKey:
    def _seal(self, tmp_path, monkeypatch, **kw):
        import audit_bundle.seal as _seal_mod
        from audit_bundle.seal import seal_bundle
        monkeypatch.setattr(_seal_mod, "_AUDIT_ROOT", tmp_path / "audit")
        compile_output = json.loads(FIXTURE.read_text(encoding="utf-8"))
        dummy_pdf = tmp_path / "dummy.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")
        return seal_bundle(
            client_config=_make_cfg(),
            period={"start": "2024-07-01", "end": "2024-09-30"},
            compile_output=compile_output,
            gate_results=_gate_results(),
            report_pdf_path=dummy_pdf,
            run_started_at="2026-06-02T00:00:00+00:00",
            run_completed_at="2026-06-02T00:00:10+00:00",
            **kw,
        )

    def test_extra_stream_seals_to_own_key(self, tmp_path, monkeypatch):
        art = _stub_artefact()
        bundle_dir = self._seal(
            tmp_path, monkeypatch,
            extra_reasoning_artefacts={"stubskill": art},
        )
        p = bundle_dir / "steps" / "stubskill-candidates.json"
        assert p.exists(), "steps/stubskill-candidates.json not written"
        # canonical bytes exactly match the artefact
        assert p.read_bytes() == canonical_json(art)

    def test_extra_stream_does_not_create_reg2627_key(self, tmp_path, monkeypatch):
        bundle_dir = self._seal(
            tmp_path, monkeypatch,
            extra_reasoning_artefacts={"stubskill": _stub_artefact()},
        )
        # No reg2627 reasoning_artefact was supplied → its key must be absent.
        assert not (bundle_dir / "steps" / "judgment-candidates.json").exists()

    def test_both_streams_coexist_distinctly(self, tmp_path, monkeypatch):
        bundle_dir = self._seal(
            tmp_path, monkeypatch,
            reasoning_artefact=_reg_artefact(),
            extra_reasoning_artefacts={"stubskill": _stub_artefact()},
        )
        jc = bundle_dir / "steps" / "judgment-candidates.json"
        sc = bundle_dir / "steps" / "stubskill-candidates.json"
        assert jc.exists() and sc.exists()
        # distinct content
        assert jc.read_bytes() != sc.read_bytes()
        # both hashed in the manifest
        manifest = json.loads((bundle_dir / "manifest.json").read_bytes())
        listed = {a["path"] for a in manifest["artefacts"]}
        assert "steps/judgment-candidates.json" in listed
        assert "steps/stubskill-candidates.json" in listed

    def test_extra_stream_verifies(self, tmp_path, monkeypatch):
        from audit_bundle.verify import verify_bundle
        bundle_dir = self._seal(
            tmp_path, monkeypatch,
            extra_reasoning_artefacts={"stubskill": _stub_artefact()},
        )
        ok, problems = verify_bundle(bundle_dir)
        assert ok is True, f"verify_bundle failed: {problems}"

    def test_skill_id_colliding_with_reg2627_key_is_rejected(self, tmp_path, monkeypatch):
        # "judgment" would map to judgment-candidates.json and overwrite reg2627.
        with pytest.raises(ValueError):
            self._seal(
                tmp_path, monkeypatch,
                extra_reasoning_artefacts={"judgment": _stub_artefact()},
            )

    def test_unsafe_skill_id_is_rejected(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError):
            self._seal(
                tmp_path, monkeypatch,
                extra_reasoning_artefacts={"../evil": _stub_artefact()},
            )


# ---------------------------------------------------------------------------
# build_report: second stream through the gated builder
# ---------------------------------------------------------------------------

class TestBuildReportExtraStream:
    def _raw(self):
        return load_compile_output(FIXTURE)

    def test_default_extra_candidates_is_none(self):
        # Existing callers pass no extra artefacts → field stays None so reg2627
        # runs (and their rendered PDFs) are byte-identical.
        m = build_report(self._raw(), _make_cfg(), generated_at=_GENERATED_AT)
        assert getattr(m, "extra_candidates", "MISSING") is None

    def test_extra_stream_gated_off_when_flag_false(self):
        m = build_report(
            self._raw(), _make_cfg(show_ai_candidates=False),
            generated_at=_GENERATED_AT,
            extra_judgment_artefacts={"stubskill": _stub_artefact()},
        )
        assert m.extra_candidates is not None
        assert m.extra_candidates["stubskill"].show is False

    def test_extra_stream_shown_when_flag_true(self):
        m = build_report(
            self._raw(), _make_cfg(show_ai_candidates=True),
            generated_at=_GENERATED_AT,
            extra_judgment_artefacts={"stubskill": _stub_artefact()},
        )
        sec = m.extra_candidates["stubskill"]
        assert sec.show is True
        assert sec.candidate_count == 1


# ---------------------------------------------------------------------------
# renderer: freeze gate covers the second stream
# ---------------------------------------------------------------------------

class TestRenderGate:
    def test_render_noop_when_no_extra(self):
        m = types.SimpleNamespace(extra_candidates=None)
        story: list = []
        _extra_candidates_subsections(m, story)
        assert story == []

    def test_render_noop_when_gate_off(self):
        sec = build_ai_candidates_section(_stub_artefact(), show=False)
        m = types.SimpleNamespace(extra_candidates={"stubskill": sec})
        story: list = []
        _extra_candidates_subsections(m, story)
        assert story == [], "second stream rendered despite show_ai_candidates=False"

    def test_render_draws_when_gate_on(self):
        sec = build_ai_candidates_section(_stub_artefact(), show=True)
        m = types.SimpleNamespace(extra_candidates={"stubskill": sec})
        story: list = []
        _extra_candidates_subsections(m, story)
        assert len(story) > 0
