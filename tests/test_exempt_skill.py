"""
T2.30 — exempt-supply reasoning skill #2 (reasoning/exempt.py), hermetic layer.

EXEMPT_SPEC is the second production SkillSpec on the T2.27 generalized shell:
sales lines coded ES33/ESN33 (frozenset filter, T2.29), KB slice
knowledge-base/slices/exempt-supply.md (cross-verified corrected version),
run_exempt_pass a thin wrapper over run_reasoning_pass — mirroring reg2627.

NO tax wording is asserted here beyond structural anchors; the semantics live in
the slice.  All tests hermetic: llm_call always injected; no live SAP/Anthropic.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from reasoning.exempt import (
    EXEMPT_SPEC,
    _DISCLAIMER,
    _PINNED_MODEL,
    _PROMPT_VERSION,
    run_exempt_pass,
)
from reasoning.reasoning_pass import kb_path, run_reasoning_pass

PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}

_SLICE = Path(__file__).parent.parent / "knowledge-base" / "slices" / "exempt-supply.md"

_ENUM = frozenset({
    "intermediary_fee", "commercial_property", "real_estate_agent",
    "movable_furniture", "mixed_use_property", "overseas_financial_service",
    "dpt_intermediary", "not_fourth_schedule", "indeterminate",
})


def _sales_line(vg: str, doc_num: int, desc: str, doc_type: str = "sales_invoice") -> dict:
    return {
        "doc_num": doc_num, "doc_type": doc_type, "doc_date": "2024-08-01",
        "card_name": "CUSTOMER PTE LTD", "line_index": 0, "vat_group": vg,
        "line_description": desc, "line_total": 1000.0, "tax_total": 0.0,
    }


def _candidate(vg: str, doc_num: int, cat: str, phrasing: str) -> dict:
    return {
        "doc_num": doc_num, "doc_type": "sales_invoice", "doc_date": "2024-08-01",
        "card_name": "CUSTOMER PTE LTD", "line_index": 0, "vat_group": vg,
        "line_description": "X", "line_total": 1000.0, "tax_total": 0.0,
        "suspected_category": cat, "reasoning": "desc-vs-code mismatch",
        "phrasing": phrasing, "confidence": "low",
    }


# ---------------------------------------------------------------------------
# EXEMPT_SPEC anchors
# ---------------------------------------------------------------------------

class TestExemptSpec:
    def test_identity_fields(self):
        assert EXEMPT_SPEC.skill_id == "exempt-supply"
        assert EXEMPT_SPEC.artefact_type == "exempt-supply-candidates"
        assert EXEMPT_SPEC.check == "exempt-supply-misclassification"
        assert EXEMPT_SPEC.prompt_version == "t2.30-exempt-supply-v1"
        assert EXEMPT_SPEC.kb_slice_name == "exempt-supply"
        assert EXEMPT_SPEC.lines_examined_label == "exempt_sales_lines_examined"

    def test_vat_group_is_the_exempt_frozenset(self):
        assert EXEMPT_SPEC.vat_group == frozenset({"ES33", "ESN33"})

    def test_suspected_categories_slice_confirmed_enum(self):
        assert EXEMPT_SPEC.suspected_categories == _ENUM

    def test_batching_mirrors_reg2627(self):
        assert EXEMPT_SPEC.batch_size == 20
        assert EXEMPT_SPEC.max_tokens == 8192

    def test_kb_path_resolves_to_committed_slice(self):
        assert kb_path(EXEMPT_SPEC) == _SLICE.resolve()
        assert _SLICE.exists(), "cross-verified slice must be committed with this build"

    def test_slice_is_the_cross_verified_corrected_version(self):
        text = _SLICE.read_text(encoding="utf-8")
        # Correction markers (gate #1) — DPT false-positive guard + furniture fix.
        assert "still EXEMPT" in text
        assert "stablecoin" in text
        assert "movable furniture" in text
        # No unresolved flags.
        for flag in ("VERIFY", "TODO", "XXX"):
            assert flag not in text

    def test_default_llm_call_bound_and_lazy(self):
        assert EXEMPT_SPEC.default_llm_call is not None
        # anthropic must NOT be imported at module import time — only lazily
        # inside _default_llm_call (mirrors reg2627).
        import reasoning.exempt as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        head = src.split("def _default_llm_call")[0]
        assert "import anthropic" not in head

    def test_pinned_model_mirrors_reg2627(self):
        assert _PINNED_MODEL == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Hermetic pass over synthetic ES33 + ESN33 + SO lines
# ---------------------------------------------------------------------------

class TestExemptPassHermetic:
    def _lines(self):
        return [
            _sales_line("ES33", 9001, "INSURANCE BROKERAGE COMMISSION"),
            _sales_line("ESN33", 9002, "OFFICE UNIT LEASE Q3"),
            _sales_line("SO", 9003, "WIDGET SALE"),          # non-member: excluded
            _sales_line("ZR", 9004, "EXPORT CONSIGNMENT"),   # non-member: excluded
        ]

    def _fake_llm(self, model, system, messages, max_tokens):
        arr = [
            _candidate("ES33", 9001, "intermediary_fee",
                       "Consider reviewing whether this brokerage commission is a taxable intermediary fee"),
            # Deliberately un-prefixed: generic normalisation must fix it.
            _candidate("ESN33", 9002, "commercial_property",
                       "an office lease coded exempt may be commercial property"),
        ]
        return {"content": json.dumps(arr), "input_tokens": 10, "output_tokens": 20}

    def _run(self):
        return run_exempt_pass(PERIOD, line_source=self._lines, llm_call=self._fake_llm)

    def test_ok_and_anchors(self):
        art = self._run()
        assert art["status"] == "ok"
        assert art["artefact_type"] == "exempt-supply-candidates"
        assert art["check"] == "exempt-supply-misclassification"
        assert art["provenance"]["prompt_version"] == "t2.30-exempt-supply-v1"
        assert art["provenance"]["validation_status"] == "unvalidated"
        assert art["disclaimer"] == _DISCLAIMER

    def test_frozenset_filter_selects_es33_and_esn33_only(self):
        art = self._run()
        # 2 of the 4 lines match {ES33, ESN33}; SO and ZR are excluded.
        assert art["input_summary"]["exempt_sales_lines_examined"] == 2

    def test_candidates_carry_their_own_per_line_codes(self):
        art = self._run()
        assert {c["vat_group"] for c in art["candidates"]} == {"ES33", "ESN33"}

    def test_thirteen_field_shape(self):
        art = self._run()
        expected = {
            "doc_num", "doc_type", "doc_date", "card_name", "line_index",
            "vat_group", "line_description", "line_total", "tax_total",
            "suspected_category", "reasoning", "phrasing", "confidence",
        }
        for c in art["candidates"]:
            assert set(c.keys()) == expected

    def test_phrasing_invariant_enforced(self):
        art = self._run()
        assert art["candidate_count"] == 2
        for c in art["candidates"]:
            assert c["phrasing"].startswith("Consider reviewing whether")

    def test_kb_slice_hash_is_sha256_of_committed_slice(self):
        art = self._run()
        expected = "sha256:" + hashlib.sha256(_SLICE.read_bytes()).hexdigest()
        assert art["provenance"]["kb_slice_hash"] == expected

    def test_wrapper_equals_generic_pass_modulo_timestamp(self):
        wrapped = self._run()
        generic = run_reasoning_pass(
            EXEMPT_SPEC, PERIOD, line_source=self._lines,
            llm_call=self._fake_llm, model_id=_PINNED_MODEL,
        )
        wrapped.pop("generated_at"); generic.pop("generated_at")
        assert wrapped == generic

    def test_category_outside_slice_enum_rejected(self):
        def _bad_llm(model, system, messages, max_tokens):
            arr = [_candidate("ES33", 9001, "medical_expenses",
                              "Consider reviewing whether x")]
            return {"content": json.dumps(arr), "input_tokens": 1, "output_tokens": 1}
        art = run_exempt_pass(PERIOD, line_source=self._lines, llm_call=_bad_llm)
        # invalid category -> artefact errors rather than surfacing a bad candidate
        assert art["status"] == "errored"

    def test_no_exempt_lines_is_clean_ok_without_llm(self):
        art = run_exempt_pass(
            PERIOD,
            line_source=lambda: [_sales_line("SO", 1, "WIDGET")],
            llm_call=lambda *a: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
        )
        assert art["status"] == "ok"
        assert art["candidate_count"] == 0
        assert art["input_summary"]["exempt_sales_lines_examined"] == 0


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------

class TestImportIsolation:
    def test_exempt_module_has_no_orchestrator_or_audit_bundle_import(self):
        import reasoning.exempt as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import orchestrator" not in src
        assert "import audit_bundle" not in src
        assert "sap_b1_server" not in src

    def test_anthropic_import_is_lazy_only(self):
        import reasoning.exempt as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        # Exactly one anthropic import, inside _default_llm_call (deferred).
        assert src.count("import anthropic") == 1
        body = src.split("def _default_llm_call", 1)[1]
        assert "import anthropic" in body
