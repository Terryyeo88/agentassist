"""
T2.29 — SkillSpec.vat_group generalized from str to str | frozenset[str].

One reasoning skill can now select a SET of canonical tax codes (e.g.
{"ES33","ESN33"}) instead of a single one.  This authors NO tax semantics, NO
skill, NO KB slice — it is a pure typing/branching generalization.

The hard safety claim: reg2627 (a str "SI" spec) is BYTE-IDENTICAL.  The str
path keeps forcing spec.vat_group onto every candidate (the pre-T2.29 behaviour,
locked by test_reasoning_shell_generalize.py); only the frozenset path stamps the
candidate's own per-line code so a {"ES33","ESN33"} spec does not flatten every
candidate to one code.

No Anthropic API calls (llm_call always injected).  No live SAP.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from reasoning.reasoning_pass import (
    SkillSpec,
    run_reasoning_pass,
    validate_candidate,
)
from reasoning.reg2627 import REG2627_SPEC, _PINNED_MODEL

PERIOD = {"start": "2024-01-01", "end": "2024-03-31"}
_STUB_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reasoning-shell"


# ---------------------------------------------------------------------------
# Spec builders / fakes
# ---------------------------------------------------------------------------

def _sys_prompt(kb_text: str) -> str:
    return "STUB SYSTEM\n" + kb_text


def _user_msg(period: dict, lines: list[dict]) -> str:
    return f"STUB {period['start']} {json.dumps(lines)}"


def _exempt_spec(vat_group) -> SkillSpec:
    """A TEST-ONLY exempt-style spec over the T2.27 stub KB slice."""
    return SkillSpec(
        skill_id="exemptstub",
        artefact_type="reasoning-candidates",
        check="exempt-stub-not-a-rule",
        prompt_version="t2.29-exemptstub-v1",
        kb_slice_name="stubskill",
        suspected_categories=frozenset({"exempt_supply", "other"}),
        vat_group=vat_group,
        batch_size=20,
        max_tokens=1024,
        disclaimer="STUB — human review only.",
        lines_examined_label="exempt_lines_examined",
        build_system_prompt=_sys_prompt,
        build_user_message=_user_msg,
        kb_dir=_STUB_FIXTURE_DIR,
    )


def _sales_line(vg: str, doc_num: int, desc: str) -> dict:
    return {
        "doc_num": doc_num, "doc_type": "sales_invoice", "doc_date": "2024-02-01",
        "card_name": "CUST", "line_index": 0, "vat_group": vg,
        "line_description": desc, "line_total": 100.0, "tax_total": 0.0,
    }


def _raw_candidate(vg: str, cat: str = "exempt_supply") -> dict:
    return {
        "doc_num": 1, "doc_type": "sales_invoice", "doc_date": "2024-02-01",
        "card_name": "CUST", "line_index": 0, "vat_group": vg,
        "line_description": "D", "line_total": 100.0, "tax_total": 0.0,
        "suspected_category": cat, "reasoning": "r",
        "phrasing": "this line may be exempt", "confidence": "low",
    }


# ---------------------------------------------------------------------------
# 1. Field type + validator
# ---------------------------------------------------------------------------

class TestVatGroupFieldType:
    def test_accepts_str(self):
        spec = _exempt_spec("ES33")
        assert spec.vat_group == "ES33"

    def test_accepts_frozenset(self):
        spec = _exempt_spec(frozenset({"ES33", "ESN33"}))
        assert spec.vat_group == frozenset({"ES33", "ESN33"})

    def test_rejects_int(self):
        with pytest.raises(TypeError):
            _exempt_spec(123)

    def test_rejects_mutable_set(self):
        # frozenset (not set) is required — SkillSpec is a frozen/hashable dataclass.
        with pytest.raises(TypeError):
            _exempt_spec({"ES33", "ESN33"})

    def test_rejects_frozenset_of_non_str(self):
        with pytest.raises(TypeError):
            _exempt_spec(frozenset({"ES33", 7}))


# ---------------------------------------------------------------------------
# 2. reg2627 str path — BYTE-IDENTICAL stamp (forces spec.vat_group)
# ---------------------------------------------------------------------------

class TestReg2627StrPathByteIdentical:
    def test_str_spec_forces_spec_vat_group_regardless_of_raw(self):
        # The pre-T2.29 behaviour, preserved: for a str spec the candidate's
        # vat_group is stamped from the spec even if the raw LLM echo differs.
        out = validate_candidate(REG2627_SPEC, _raw_candidate("ES33", cat="medical_expenses"))
        assert out["vat_group"] == "SI"

    def test_str_spec_run_provenance_unchanged(self):
        def _fake(model, system, messages, max_tokens):
            arr = [{
                "doc_num": 3001, "doc_type": "purchase_invoice", "doc_date": "2024-02-01",
                "card_name": "ACME", "line_index": 0, "vat_group": "SI",
                "line_description": "MED", "line_total": 100.0, "tax_total": 9.0,
                "suspected_category": "medical_expenses", "reasoning": "x",
                "phrasing": "Consider reviewing whether disallowed", "confidence": "low",
            }]
            return {"content": json.dumps(arr), "input_tokens": 1, "output_tokens": 1}

        def _lines():
            return [{"doc_num": 3001, "doc_type": "purchase_invoice",
                     "doc_date": "2024-02-01", "card_name": "ACME", "line_index": 0,
                     "vat_group": "SI", "line_description": "MED",
                     "line_total": 100.0, "tax_total": 9.0}]

        art = run_reasoning_pass(REG2627_SPEC, PERIOD, line_source=_lines,
                                 llm_call=_fake, model_id=_PINNED_MODEL)
        assert art["status"] == "ok"
        assert art["check"] == "reg-26-27-disallowed-input-tax"
        assert art["provenance"]["prompt_version"] == "t2.7-reg2627-v1"
        assert art["candidates"][0]["vat_group"] == "SI"
        assert "si_purchase_lines_examined" in art["input_summary"]


# ---------------------------------------------------------------------------
# 3. frozenset path — SET selection + per-line stamp
# ---------------------------------------------------------------------------

class TestFrozensetPath:
    def test_stamp_is_per_line_code_not_flattened(self):
        spec = _exempt_spec(frozenset({"ES33", "ESN33"}))
        es33 = validate_candidate(spec, _raw_candidate("ES33"))
        esn33 = validate_candidate(spec, _raw_candidate("ESN33"))
        assert es33["vat_group"] == "ES33"
        assert esn33["vat_group"] == "ESN33"

    def test_phrasing_invariant_still_enforced(self):
        spec = _exempt_spec(frozenset({"ES33", "ESN33"}))
        out = validate_candidate(spec, _raw_candidate("ES33"))
        assert out["phrasing"].startswith("Consider reviewing whether")

    def _run_over_lines(self, spec):
        lines = [
            _sales_line("ES33", 1, "Financial service"),
            _sales_line("ESN33", 2, "Sale of shares"),
            _sales_line("SO", 3, "Widget"),  # non-member — must be excluded
        ]

        def _fake(model, system, messages, max_tokens):
            arr = [
                {**_raw_candidate("ES33"), "doc_num": 1,
                 "phrasing": "Consider reviewing whether exempt"},
                {**_raw_candidate("ESN33"), "doc_num": 2,
                 "phrasing": "Consider reviewing whether exempt"},
            ]
            return {"content": json.dumps(arr), "input_tokens": 1, "output_tokens": 1}

        return run_reasoning_pass(spec, PERIOD, line_source=lambda: lines,
                                  llm_call=_fake, model_id="stub-model")

    def test_set_selects_both_members_excludes_non_member(self):
        art = self._run_over_lines(_exempt_spec(frozenset({"ES33", "ESN33"})))
        assert art["status"] == "ok"
        # Only the ES33 + ESN33 lines are forwarded to the LLM; SO is excluded.
        assert art["input_summary"]["exempt_lines_examined"] == 2

    def test_candidates_carry_their_own_codes(self):
        art = self._run_over_lines(_exempt_spec(frozenset({"ES33", "ESN33"})))
        assert {c["vat_group"] for c in art["candidates"]} == {"ES33", "ESN33"}
        for c in art["candidates"]:
            assert c["phrasing"].startswith("Consider reviewing whether")

    def test_single_element_frozenset_equivalent_to_str(self):
        # A one-code frozenset selects exactly like the str path did.
        lines = [_sales_line("ES33", 1, "svc"), _sales_line("SO", 2, "widget")]

        def _fake(model, system, messages, max_tokens):
            arr = [{**_raw_candidate("ES33"), "doc_num": 1,
                    "phrasing": "Consider reviewing whether exempt"}]
            return {"content": json.dumps(arr), "input_tokens": 1, "output_tokens": 1}

        art = run_reasoning_pass(_exempt_spec(frozenset({"ES33"})), PERIOD,
                                 line_source=lambda: lines, llm_call=_fake,
                                 model_id="stub-model")
        assert art["input_summary"]["exempt_lines_examined"] == 1
        assert art["candidates"][0]["vat_group"] == "ES33"
