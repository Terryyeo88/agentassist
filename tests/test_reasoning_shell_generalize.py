"""
T2.27 — reasoning-shell generalization tests.

Proves that the Reg 26/27 reasoning pass has been generalized into a
skill-parameterized shell (reasoning/reasoning_pass.py) WITHOUT changing
reg2627's observable behaviour:

  * SkillSpec carries the per-skill parameters (skill_id, kb_slice_name,
    suspected-category enum, vat_group filter, batch_size, prompt hooks).
  * run_reasoning_pass(spec, ...) is the generic entry point.
  * run_reg2627_pass is now a thin wrapper over run_reasoning_pass(REG2627_SPEC,…)
    and its artefact is byte-identical (modulo the generated_at timestamp).
  * The "Consider reviewing whether…" phrasing invariant is enforced generically
    for ANY spec, proven with a TEST-ONLY stub skill.

TEST-ONLY: the stub spec authors no tax semantics; its KB slice lives under
tests/fixtures/reasoning-shell/, never knowledge-base/slices/.

No Anthropic API calls (llm_call is always injected).  No live SAP.
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
from reasoning.reg2627 import (
    REG2627_SPEC,
    run_reg2627_pass,
    _DISCLAIMER,
    _PINNED_MODEL,
    _KB_PATH,
)

PERIOD = {"start": "2024-01-01", "end": "2024-03-31"}

_STUB_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reasoning-shell"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _reg_line_source() -> list[dict]:
    return [
        {
            "doc_num": 3001, "doc_type": "PurchaseInvoice", "doc_date": "2024-02-01",
            "card_name": "ACME PTE LTD", "line_index": 0, "vat_group": "SI",
            "line_description": "MEDICAL CLAIM STAFF", "line_total": 100.0,
            "tax_total": 9.0,
        },
        # A non-SI line that must be filtered out before the LLM is called.
        {
            "doc_num": 3002, "doc_type": "PurchaseInvoice", "doc_date": "2024-02-02",
            "card_name": "ZERO CO", "line_index": 0, "vat_group": "ZR",
            "line_description": "EXPORT SALE", "line_total": 50.0, "tax_total": 0.0,
        },
    ]


def _reg_fake_llm(model, system, messages, max_tokens):
    arr = [{
        "doc_num": 3001, "doc_type": "PurchaseInvoice", "doc_date": "2024-02-01",
        "card_name": "ACME PTE LTD", "line_index": 0, "vat_group": "SI",
        "line_description": "MEDICAL CLAIM STAFF", "line_total": 100.0,
        "tax_total": 9.0, "suspected_category": "medical_expenses",
        "reasoning": "line description suggests staff medical expense",
        "phrasing": "Consider reviewing whether this input tax is disallowed",
        "confidence": "low",
    }]
    return {"content": json.dumps(arr), "input_tokens": 10, "output_tokens": 20}


# ── Stub skill (TEST-ONLY; no tax semantics) ───────────────────────────────

def _stub_system_prompt(kb_text: str) -> str:
    return "STUB SYSTEM PROMPT\n" + kb_text


def _stub_user_message(period: dict, lines: list[dict]) -> str:
    return f"STUB USER {period['start']} {json.dumps(lines)}"


STUB_SPEC = SkillSpec(
    skill_id="stubskill",
    artefact_type="reasoning-candidates",
    check="stub-check-not-a-rule",
    prompt_version="t2.27-stub-v1",
    kb_slice_name="stubskill",
    suspected_categories=frozenset({"stub_flagged", "stub_other"}),
    vat_group="ZZ",
    batch_size=20,
    max_tokens=1024,
    disclaimer="STUB — candidates for human review only, not a real skill.",
    lines_examined_label="stub_lines_examined",
    build_system_prompt=_stub_system_prompt,
    build_user_message=_stub_user_message,
    kb_dir=_STUB_FIXTURE_DIR,
)


def _stub_line_source() -> list[dict]:
    return [
        {"doc_num": 9001, "doc_type": "Invoice", "doc_date": "2024-01-05",
         "card_name": "ALPHA", "line_index": 0, "vat_group": "ZZ",
         "line_description": "STUB LINE ALPHA", "line_total": 100.0, "tax_total": 9.0},
        {"doc_num": 9002, "doc_type": "Invoice", "doc_date": "2024-01-06",
         "card_name": "BETA", "line_index": 0, "vat_group": "ZZ",
         "line_description": "STUB LINE BETA", "line_total": 200.0, "tax_total": 18.0},
        # filtered out (not the stub vat_group)
        {"doc_num": 9003, "doc_type": "Invoice", "doc_date": "2024-01-07",
         "card_name": "GAMMA", "line_index": 0, "vat_group": "SI",
         "line_description": "STUB LINE GAMMA", "line_total": 300.0, "tax_total": 27.0},
    ]


def _stub_fake_llm(model, system, messages, max_tokens):
    arr = [
        {"doc_num": 9001, "doc_type": "Invoice", "doc_date": "2024-01-05",
         "card_name": "ALPHA", "line_index": 0, "vat_group": "ZZ",
         "line_description": "STUB LINE ALPHA", "line_total": 100.0, "tax_total": 9.0,
         "suspected_category": "stub_flagged", "reasoning": "stub reason",
         # NO prefix — must be normalised to start with the invariant phrase.
         "phrasing": "this stub line looks worth a second look", "confidence": "low"},
        {"doc_num": 9002, "doc_type": "Invoice", "doc_date": "2024-01-06",
         "card_name": "BETA", "line_index": 0, "vat_group": "ZZ",
         "line_description": "STUB LINE BETA", "line_total": 200.0, "tax_total": 18.0,
         "suspected_category": "stub_other", "reasoning": "stub reason 2",
         "phrasing": "Consider reviewing whether the stub applies", "confidence": "high"},
    ]
    return {"content": json.dumps(arr), "input_tokens": 5, "output_tokens": 12}


def _strip_ts(artefact: dict) -> dict:
    out = dict(artefact)
    out.pop("generated_at", None)
    return out


# ---------------------------------------------------------------------------
# SkillSpec + REG2627_SPEC shape
# ---------------------------------------------------------------------------
        # AMENDED by Terry 2026-09-23 (Slice E): the spec now selects standard-rated purchase
        # lines in BOTH vocabularies — raw SAP "SI" and canonical "TX". A BRIDGE, not the final
        # design: the SAP reasoning feeder still emits raw codes while the chain emits canonical
        # ones. Once those fixtures are re-captured canonically, this reduces to TX alone.

class TestReg2627Spec:
    def test_reg2627_spec_fields(self):
        assert REG2627_SPEC.skill_id == "reg2627"
        assert REG2627_SPEC.kb_slice_name == "reg2627"
        # AMENDED by Terry 2026-09-23 (Slice E): the spec now selects standard-rated purchase
        # lines in BOTH vocabularies — raw SAP "SI" and canonical "TX". A BRIDGE, not the final
        # design: the SAP reasoning feeder still emits raw codes while the chain emits canonical
        # ones. Once those fixtures are re-captured canonically, this reduces to TX alone.
        assert REG2627_SPEC.vat_group == frozenset({"SI", "TX"})
        assert REG2627_SPEC.batch_size == 20
        assert REG2627_SPEC.check == "reg-26-27-disallowed-input-tax"
        assert REG2627_SPEC.artefact_type == "judgment-candidates"
        assert REG2627_SPEC.prompt_version == "t2.7-reg2627-v1"

    def test_reg2627_spec_kb_path_matches_legacy_constant(self):
        # The generic loader must resolve to the exact same file the locked
        # test reads via reasoning.reg2627._KB_PATH.
        assert (REG2627_SPEC.kb_dir / f"{REG2627_SPEC.kb_slice_name}.md") == _KB_PATH

    def test_reg2627_categories_are_the_six_reg_categories(self):
        assert REG2627_SPEC.suspected_categories == frozenset({
            "medical_expenses", "motor_car_s_plate", "club_subscriptions",
            "family_benefits", "entertainment", "other_disallowed",
        })


# ---------------------------------------------------------------------------
# Byte-identity: wrapper delegates faithfully to the generic pass
# ---------------------------------------------------------------------------

class TestWrapperByteIdentity:
    def test_wrapper_equals_generic_pass_modulo_timestamp(self):
        wrapped = run_reg2627_pass(
            PERIOD, line_source=_reg_line_source, llm_call=_reg_fake_llm,
            model_id=_PINNED_MODEL,
        )
        generic = run_reasoning_pass(
            REG2627_SPEC, PERIOD, line_source=_reg_line_source,
            llm_call=_reg_fake_llm, model_id=_PINNED_MODEL,
        )
        assert _strip_ts(wrapped) == _strip_ts(generic)

    def test_wrapper_artefact_reg2627_anchors(self):
        art = run_reg2627_pass(
            PERIOD, line_source=_reg_line_source, llm_call=_reg_fake_llm,
            model_id=_PINNED_MODEL,
        )
        assert art["artefact_type"] == "judgment-candidates"
        assert art["check"] == "reg-26-27-disallowed-input-tax"
        assert art["status"] == "ok"
        assert art["provenance"]["prompt_version"] == "t2.7-reg2627-v1"
        assert art["provenance"]["validation_status"] == "unvalidated"
        assert art["disclaimer"] == _DISCLAIMER
        # reg2627-specific input_summary key preserved.
        assert "si_purchase_lines_examined" in art["input_summary"]
        assert art["input_summary"]["si_purchase_lines_examined"] == 1
        # non-SI line filtered out before the LLM.
        assert art["candidates"][0]["vat_group"] == "SI"

    def test_reg2627_generated_at_present_and_iso(self):
        art = run_reg2627_pass(
            PERIOD, line_source=_reg_line_source, llm_call=_reg_fake_llm,
        )
        assert "T" in art["generated_at"]  # ISO-8601


# ---------------------------------------------------------------------------
# Generic pass runs an arbitrary (stub) skill
# ---------------------------------------------------------------------------

class TestStubSkillPass:
    def _run(self):
        return run_reasoning_pass(
            STUB_SPEC, PERIOD, line_source=_stub_line_source,
            llm_call=_stub_fake_llm, model_id="stub-model",
        )

    def test_stub_pass_ok(self):
        art = self._run()
        assert art["status"] == "ok"
        assert art["check"] == "stub-check-not-a-rule"
        assert art["artefact_type"] == "reasoning-candidates"
        assert art["provenance"]["prompt_version"] == "t2.27-stub-v1"
        assert art["provenance"]["validation_status"] == "unvalidated"

    def test_stub_vat_group_filter(self):
        art = self._run()
        # Only the two ZZ lines are examined; the SI line is filtered out.
        assert art["input_summary"]["stub_lines_examined"] == 2

    def test_stub_kb_hash_from_test_slice(self):
        art = self._run()
        assert art["provenance"]["kb_slice_hash"].startswith("sha256:")

    def test_stub_candidates_validated_against_stub_enum(self):
        art = self._run()
        cats = {c["suspected_category"] for c in art["candidates"]}
        assert cats <= {"stub_flagged", "stub_other"}
        # vat_group is stamped from the spec, not trusted from the model.
        assert all(c["vat_group"] == "ZZ" for c in art["candidates"])

    def test_phrasing_invariant_enforced_generically(self):
        art = self._run()
        assert art["candidate_count"] == 2
        for c in art["candidates"]:
            assert c["phrasing"].startswith("Consider reviewing whether"), (
                f"phrasing invariant not enforced for stub candidate: {c['phrasing']!r}"
            )


# ---------------------------------------------------------------------------
# validate_candidate is generic + reg2627 wrapper keeps single-arg contract
# ---------------------------------------------------------------------------

class TestValidateCandidateGeneric:
    def _raw(self, **over):
        base = {
            "doc_num": 1, "doc_type": "Invoice", "doc_date": "2024-01-01",
            "card_name": "X", "line_index": 0, "vat_group": "ignored",
            "line_description": "D", "line_total": 1.0, "tax_total": 0.0,
            "suspected_category": "stub_flagged", "reasoning": "r",
            "phrasing": "raw text", "confidence": "low",
        }
        base.update(over)
        return base

    def test_generic_normalises_phrasing_and_vat_group(self):
        out = validate_candidate(STUB_SPEC, self._raw())
        assert out["phrasing"].startswith("Consider reviewing whether")
        assert out["vat_group"] == "ZZ"

    def test_generic_rejects_category_outside_spec_enum(self):
        with pytest.raises(ValueError):
            validate_candidate(STUB_SPEC, self._raw(suspected_category="medical_expenses"))

    def test_reg2627_wrapper_still_single_arg(self):
        # AMENDED by Terry 2026-09-23 (Slice E): the single-arg wrapper contract is unchanged;
        # only the stamp is. Under the frozenset spec the candidate keeps its own per-line code,
        # so this pins the CONTRACT (one arg, category preserved), not the old forced "SI".
        from reasoning.reg2627 import _validate_candidate
        raw = self._raw(suspected_category="medical_expenses", vat_group="TX")
        out = _validate_candidate(raw)
        assert out["vat_group"] == "TX"
        assert out["suspected_category"] == "medical_expenses"


# ---------------------------------------------------------------------------
# Import isolation — the generic shell adds no forbidden imports
# ---------------------------------------------------------------------------

class TestImportIsolation:
    def test_reasoning_pass_has_no_anthropic_import(self):
        import reasoning.reasoning_pass as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import anthropic" not in src
        assert "from anthropic" not in src

    def test_reasoning_pass_has_no_orchestrator_or_audit_bundle_import(self):
        import reasoning.reasoning_pass as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import orchestrator" not in src
        assert "import audit_bundle" not in src
        assert "sap_b1_server" not in src
