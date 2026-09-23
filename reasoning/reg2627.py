"""reasoning/reg2627.py — Reg 26/27 disallowed input tax candidate pass (T2.7).

As of T2.27 this module is a thin binding of the generic reasoning shell
(reasoning/reasoning_pass.py): reg2627 is one SkillSpec (REG2627_SPEC) and
run_reg2627_pass delegates to run_reasoning_pass.  The observable artefact is
byte-identical to the pre-T2.27 pass (a characterization test proves it).

Invariants (never break these):
- Outputs are candidates for human review only.  Every phrasing starts with
  "Consider reviewing whether".  The pass NEVER asserts a compliance conclusion.
- Runs beside the deterministic chain, never inside it.  This module has NO
  import of orchestrator/, audit_bundle/, or any SAP client.
- Emits the artefact dict unconditionally — status="errored" on any failure.
- The injectable line_source and llm_call parameters let tests use fakes so
  no test ever hits a live SAP instance or the live Anthropic API.
- This module is the ONLY place in reasoning/ that imports anthropic (lazily,
  inside _default_llm_call), bound onto REG2627_SPEC.default_llm_call.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from reasoning.reasoning_pass import (
    SkillSpec,
    run_reasoning_pass,
    validate_candidate as _validate_candidate_generic,
)

_KB_PATH = Path(__file__).resolve().parent.parent / "knowledge-base" / "slices" / "reg2627.md"
_PROMPT_VERSION = "t2.7-reg2627-v1"
_PINNED_MODEL = "claude-sonnet-4-6"
_DISCLAIMER = (
    "AI-surfaced candidates for human review only — not assertions. "
    "The reviewer determines treatment and signs off."
)
_SUSPECTED_CATEGORIES = frozenset({
    "medical_expenses",
    "motor_car_s_plate",
    "club_subscriptions",
    "family_benefits",
    "entertainment",
    "other_disallowed",
})

# Batching: split SI lines into chunks so each LLM response stays within budget.
# Models differ greatly in output verbosity:
#   Haiku/Opus: ~75 tokens/candidate → 20 lines × 100% = 1,500 tok  (fine)
#   Sonnet:    ~300 tokens/candidate → 20 lines × 100% = 6,000 tok  (within 8,192)
# Batch of 30 with first-30-all-positive set caused Sonnet to hit 8,192 exactly.
_BATCH_SIZE  = 20    # max SI lines per LLM call
_MAX_TOKENS  = 8192  # output token budget per batch (safe for all three models)


# ---------------------------------------------------------------------------
# Prompt assembly (reg2627-specific; bound onto REG2627_SPEC)
# ---------------------------------------------------------------------------

def _build_system_prompt(kb_text: str) -> str:
    return (
        "You are a Singapore GST compliance assistant. "
        "Review purchase invoice line items and identify those that may fall under "
        "Regulation 26 or 27 disallowed input tax categories.\n\n"
        "CRITICAL RULES:\n"
        "1. Return a JSON array ONLY — no markdown fences, no explanation, no other text.\n"
        "2. Return [] if no candidates are found.\n"
        "3. Your role is ONLY to surface candidates for human review. "
        "Never assert that input tax IS disallowed. "
        "Every 'phrasing' field MUST start with exactly: 'Consider reviewing whether'\n\n"
        "<knowledge_base>\n" + kb_text + "\n</knowledge_base>"
    )


def _build_user_message(period: dict, lines: list[dict]) -> str:
    lines_json = json.dumps(lines, ensure_ascii=False)
    return (
        f"Review these Singapore GST purchase invoice lines for period "
        f"{period['start']} to {period['end']}. "
        f"All lines carry VatGroup=SI (standard-rated purchase, input tax claimed).\n\n"
        f"Lines:\n{lines_json}\n\n"
        f"Return a JSON array where each element has these exact keys:\n"
        f"doc_num (int), doc_type (str), doc_date (YYYY-MM-DD str), card_name (str), "
        f"line_index (int), vat_group (always \"SI\"), line_description (str), "
        f"line_total (float), tax_total (float), "
        f"suspected_category (one of: medical_expenses | motor_car_s_plate | "
        f"club_subscriptions | family_benefits | entertainment | other_disallowed), "
        f"reasoning (str: brief reason why this line warrants review), "
        f"phrasing (str: MUST start with \"Consider reviewing whether\"), "
        f"confidence (one of: low | medium | high).\n\n"
        f"Return [] if no candidates. Return only the JSON array."
    )


# ---------------------------------------------------------------------------
# Default LLM callable (deferred import so tests can run without anthropic)
# ---------------------------------------------------------------------------

def _default_llm_call(
    model: str, system: str, messages: list[dict], max_tokens: int
) -> dict:
    """Call the Anthropic Messages API.

    Defers the anthropic import to call time; raises RuntimeError if the SDK
    is missing or ANTHROPIC_API_KEY is not set.  The caller (run_reasoning_pass)
    wraps this in a broad try/except so any failure becomes status="errored".
    """
    try:
        import anthropic  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(f"anthropic SDK not installed: {exc}") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    content = response.content[0].text if response.content else ""
    return {
        "content": content,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


# ---------------------------------------------------------------------------
# Public factory — bind a model to the default Anthropic call
# ---------------------------------------------------------------------------

def build_anthropic_llm_call(
    model_id: str,
) -> "Callable[[str, str, list[dict], int], dict]":
    """Return an llm_call callable with model_id baked in.

    The returned callable satisfies the run_reasoning_pass llm_call contract:
        (model, system, messages, max_tokens) → {"content", "input_tokens", "output_tokens"}
    but ignores the positional 'model' argument and always uses the bound model_id.

    Used by the measurement harness so each model can be swapped in without
    changing the model_id parameter of run_reg2627_pass.
    """
    def _bound_call(
        _model: str, system: str, messages: list[dict], max_tokens: int
    ) -> dict:
        return _default_llm_call(model_id, system, messages, max_tokens)

    _bound_call.__name__ = f"anthropic_llm_call[{model_id}]"
    return _bound_call


# ---------------------------------------------------------------------------
# The Reg 26/27 skill specification
# ---------------------------------------------------------------------------

REG2627_SPEC = SkillSpec(
    skill_id="reg2627",
    artefact_type="judgment-candidates",
    check="reg-26-27-disallowed-input-tax",
    prompt_version=_PROMPT_VERSION,
    kb_slice_name="reg2627",
    suspected_categories=_SUSPECTED_CATEGORIES,
    # D-2026-09-23-xero-purchase-lines (ruling B1). The check's subject is STANDARD-RATED
    # PURCHASE LINES: "SI" is the raw SAP Service-Layer code, "TX" the canonical AgentAssist
    # code the Xero F5 reader emits. Selecting both is what makes this skill runnable on the
    # Xero path at all — with "SI" alone every Xero line was filtered out and the pass
    # returned a clean ok/0, i.e. the failure looked exactly like success.
    #
    # This is a BRIDGE, not the final design. The SAP reasoning feeder still emits RAW codes
    # while the chain emits canonical ones — a tolerated asymmetry in the frozen fixtures.
    # Once those fixtures are re-captured canonically this should reduce to "TX" alone
    # (filed open item). Under a frozenset spec the validator keeps each candidate's OWN
    # per-line code instead of stamping the spec's, which is more honest: a TX line must not
    # be reported as SI.
    vat_group=frozenset({"SI", "TX"}),
    batch_size=_BATCH_SIZE,
    max_tokens=_MAX_TOKENS,
    disclaimer=_DISCLAIMER,
    lines_examined_label="si_purchase_lines_examined",
    build_system_prompt=_build_system_prompt,
    build_user_message=_build_user_message,
    kb_dir=_KB_PATH.parent,
    default_llm_call=_default_llm_call,
)


def _validate_candidate(raw: dict) -> dict:
    """Validate and normalise one Reg 26/27 candidate.  Raises ValueError.

    Thin wrapper over the generic validator bound to REG2627_SPEC, preserving
    the single-argument contract used by the reg2627 unit tests.
    """
    return _validate_candidate_generic(REG2627_SPEC, raw)


# ---------------------------------------------------------------------------
# Public entry point (thin wrapper over the generic pass)
# ---------------------------------------------------------------------------

def run_reg2627_pass(
    period: dict,
    *,
    line_source: Callable[[], list[dict]],
    llm_call: Callable[[str, str, list[dict], int], dict] | None = None,
    model_id: str = _PINNED_MODEL,
) -> dict:
    """Run the Regulation 26/27 disallowed input tax reasoning pass.

    Delegates to run_reasoning_pass(REG2627_SPEC, …); the artefact is
    byte-identical to the pre-T2.27 pass.

    Args:
        period:      {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
        line_source: callable → list of purchase invoice line dicts.
                     Required keys per line: doc_num, doc_type, doc_date,
                     card_name, line_index, vat_group, line_description,
                     line_total, tax_total.  Only lines with vat_group=="SI"
                     are forwarded to the LLM.
        llm_call:    injectable; defaults to _default_llm_call (real Anthropic
                     Messages API) via REG2627_SPEC.default_llm_call.  Signature:
                       (model: str, system: str, messages: list[dict], max_tokens: int)
                       → {"content": str, "input_tokens": int, "output_tokens": int}
        model_id:    pinned Anthropic model string.

    Returns the complete judgment-candidates artefact dict — always, even on error.
    The caller (run_agent.py) must never discard this artefact on failure.
    """
    return run_reasoning_pass(
        REG2627_SPEC,
        period,
        line_source=line_source,
        llm_call=llm_call,
        model_id=model_id,
    )
