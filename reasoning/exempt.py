"""reasoning/exempt.py — exempt-supply misclassification candidate pass (T2.30).

The SECOND production skill on the generalized reasoning shell (T2.27):
EXEMPT_SPEC binds run_reasoning_pass to sales lines coded ES33/ESN33 (frozenset
filter, T2.29) and the knowledge-base/slices/exempt-supply.md slice.  All tax
semantics live in that (cross-verified, corrected) slice — this module authors
the skill WIRING only, mirroring reasoning/reg2627.py exactly.

Invariants (never break these):
- Outputs are candidates for human review only.  Every phrasing starts with
  "Consider reviewing whether".  The pass NEVER asserts a classification.
- Runs beside the deterministic chain, never inside it.  This module has NO
  import of orchestrator/, audit_bundle/, or any SAP client.  F5 Box 3 is never
  touched, recomputed, or corrected.
- Emits the artefact dict unconditionally — status="errored" on any failure.
- The injectable line_source and llm_call parameters let tests use fakes so
  no test ever hits a live SAP instance or the live Anthropic API.
- The anthropic import is lazy, confined to _default_llm_call (mirrors reg2627).
- Honest status: mechanism/demo-validated only; NOT accuracy-validated; no
  ground-truth labels exist or are claimed; validation_status="unvalidated";
  show_ai_candidates=False keeps the stream hidden in the live report.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from reasoning.reasoning_pass import SkillSpec, run_reasoning_pass

_KB_PATH = Path(__file__).resolve().parent.parent / "knowledge-base" / "slices" / "exempt-supply.md"
_PROMPT_VERSION = "t2.30-exempt-supply-v1"
_PINNED_MODEL = "claude-sonnet-4-6"
_DISCLAIMER = (
    "AI-surfaced candidates for human review only — not assertions. "
    "The reviewer determines treatment and signs off."
)

# The slice-confirmed category enum (slice §4 traps + §5 bases, ruled by the
# rule author): seven §4 traps, the §5 "does not read as Fourth Schedule" basis,
# and the §5 indeterminate (silent/generic description) basis.  NO tax wording
# here — each slug's meaning is defined in the slice.
_SUSPECTED_CATEGORIES = frozenset({
    "intermediary_fee",
    "commercial_property",
    "real_estate_agent",
    "movable_furniture",
    "mixed_use_property",
    "overseas_financial_service",
    "dpt_intermediary",
    "not_fourth_schedule",
    "indeterminate",
})

# The exempt sales codes (both land in F5 Box 3).  The ES33-vs-ESN33 sub-split
# is out of v1 scope (slice §2) — the skill selects BOTH and each candidate
# keeps its own per-line code (T2.29 frozenset stamp).
_VAT_GROUPS = frozenset({"ES33", "ESN33"})

# Batching mirrors reg2627 (same output-verbosity envelope).
_BATCH_SIZE = 20    # max exempt sales lines per LLM call
_MAX_TOKENS = 8192  # output token budget per batch


# ---------------------------------------------------------------------------
# Prompt assembly (exempt-specific; bound onto EXEMPT_SPEC)
# ---------------------------------------------------------------------------

def _build_system_prompt(kb_text: str) -> str:
    return (
        "You are a Singapore GST compliance assistant. "
        "Review SALES invoice line items coded as exempt supplies and identify "
        "those whose description suggests the exempt classification may warrant "
        "review, per the knowledge base below.\n\n"
        "CRITICAL RULES:\n"
        "1. Return a JSON array ONLY — no markdown fences, no explanation, no other text.\n"
        "2. Return [] if no candidates are found.\n"
        "3. Your role is ONLY to surface candidates for human review. "
        "Never assert that a supply IS taxable or IS misclassified. "
        "Every 'phrasing' field MUST start with exactly: 'Consider reviewing whether'\n\n"
        "<knowledge_base>\n" + kb_text + "\n</knowledge_base>"
    )


def _build_user_message(period: dict, lines: list[dict]) -> str:
    lines_json = json.dumps(lines, ensure_ascii=False)
    return (
        f"Review these Singapore GST SALES invoice lines for period "
        f"{period['start']} to {period['end']}. "
        f"All lines carry an exempt VatGroup (ES33 or ESN33 — exempt supply, "
        f"F5 Box 3).\n\n"
        f"Lines:\n{lines_json}\n\n"
        f"Return a JSON array where each element has these exact keys:\n"
        f"doc_num (int or str: carry the line's doc_num through UNCHANGED — SAP "
        f"references are integers, Xero invoice numbers are strings like \"INV-2001\"), "
        f"doc_type (str), doc_date (YYYY-MM-DD str), card_name (str), "
        f"line_index (int), vat_group (the line's own code: \"ES33\" or \"ESN33\"), "
        f"line_description (str), line_total (float), tax_total (float), "
        f"suspected_category (one of: intermediary_fee | commercial_property | "
        f"real_estate_agent | movable_furniture | mixed_use_property | "
        f"overseas_financial_service | dpt_intermediary | not_fourth_schedule | "
        f"indeterminate), "
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
# The exempt-supply skill specification
# ---------------------------------------------------------------------------

EXEMPT_SPEC = SkillSpec(
    skill_id="exempt-supply",
    artefact_type="exempt-supply-candidates",
    check="exempt-supply-misclassification",
    prompt_version=_PROMPT_VERSION,
    kb_slice_name="exempt-supply",
    suspected_categories=_SUSPECTED_CATEGORIES,
    vat_group=_VAT_GROUPS,
    batch_size=_BATCH_SIZE,
    max_tokens=_MAX_TOKENS,
    disclaimer=_DISCLAIMER,
    lines_examined_label="exempt_sales_lines_examined",
    build_system_prompt=_build_system_prompt,
    build_user_message=_build_user_message,
    kb_dir=_KB_PATH.parent,
    default_llm_call=_default_llm_call,
)


# ---------------------------------------------------------------------------
# Public entry point (thin wrapper over the generic pass)
# ---------------------------------------------------------------------------

def run_exempt_pass(
    period: dict,
    *,
    line_source: Callable[[], list[dict]],
    llm_call: Callable[[str, str, list[dict], int], dict] | None = None,
    model_id: str = _PINNED_MODEL,
) -> dict:
    """Run the exempt-supply misclassification reasoning pass (sales side).

    Delegates to run_reasoning_pass(EXEMPT_SPEC, …).

    Args:
        period:      {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
        line_source: callable → list of SALES line dicts (fetch_sales_lines).
                     Required keys per line: doc_num, doc_type, doc_date,
                     card_name, line_index, vat_group, line_description,
                     line_total, tax_total.  Only lines whose vat_group is in
                     {"ES33", "ESN33"} are forwarded to the LLM.
        llm_call:    injectable; defaults to _default_llm_call (real Anthropic
                     Messages API) via EXEMPT_SPEC.default_llm_call.
        model_id:    pinned Anthropic model string.

    Returns the complete exempt-supply-candidates artefact dict — always, even
    on error.  The caller (engine/review.py) must never discard it on failure.
    """
    return run_reasoning_pass(
        EXEMPT_SPEC,
        period,
        line_source=line_source,
        llm_call=llm_call,
        model_id=model_id,
    )
