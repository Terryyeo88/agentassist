"""reasoning/reg2627.py — Reg 26/27 disallowed input tax candidate pass (T2.7).

Invariants (never break these):
- Outputs are candidates for human review only.  Every phrasing starts with
  "Consider reviewing whether".  The pass NEVER asserts a compliance conclusion.
- Runs beside the deterministic chain, never inside it.  This module has NO
  import of orchestrator/, audit_bundle/, or any SAP client.
- Emits the artefact dict unconditionally — status="errored" on any failure.
- The injectable line_source and llm_call parameters let tests use fakes so
  no test ever hits a live SAP instance or the live Anthropic API.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

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
_CONFIDENCE_VALUES = frozenset({"low", "medium", "high"})

# Batching: split SI lines into chunks so each LLM response stays within budget.
# Models differ greatly in output verbosity:
#   Haiku/Opus: ~75 tokens/candidate → 20 lines × 100% = 1,500 tok  (fine)
#   Sonnet:    ~300 tokens/candidate → 20 lines × 100% = 6,000 tok  (within 8,192)
# Batch of 30 with first-30-all-positive set caused Sonnet to hit 8,192 exactly.
_BATCH_SIZE  = 20    # max SI lines per LLM call
_MAX_TOKENS  = 8192  # output token budget per batch (safe for all three models)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _kb_hash() -> str:
    data = _KB_PATH.read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


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


def _validate_candidate(raw: dict) -> dict:
    """Validate and normalise one candidate.  Raises ValueError on bad data."""
    required = {
        "doc_num", "doc_type", "doc_date", "card_name", "line_index",
        "vat_group", "line_description", "line_total", "tax_total",
        "suspected_category", "reasoning", "phrasing", "confidence",
    }
    missing = required - set(raw.keys())
    if missing:
        raise ValueError(f"candidate missing fields: {sorted(missing)}")

    cat = raw.get("suspected_category")
    if cat not in _SUSPECTED_CATEGORIES:
        raise ValueError(
            f"invalid suspected_category {cat!r}; "
            f"must be one of {sorted(_SUSPECTED_CATEGORIES)}"
        )

    conf = raw.get("confidence")
    if conf not in _CONFIDENCE_VALUES:
        raise ValueError(
            f"invalid confidence {conf!r}; must be one of {sorted(_CONFIDENCE_VALUES)}"
        )

    phrasing = str(raw.get("phrasing", ""))
    if not phrasing.startswith("Consider reviewing whether"):
        phrasing = "Consider reviewing whether " + phrasing

    return {
        "doc_num": int(raw["doc_num"]),
        "doc_type": str(raw["doc_type"]),
        "doc_date": str(raw["doc_date"]),
        "card_name": str(raw["card_name"]),
        "line_index": int(raw["line_index"]),
        "vat_group": "SI",
        "line_description": str(raw["line_description"]),
        "line_total": float(raw["line_total"]),
        "tax_total": float(raw["tax_total"]),
        "suspected_category": str(cat),
        "reasoning": str(raw["reasoning"]),
        "phrasing": phrasing,
        "confidence": str(conf),
    }


# ---------------------------------------------------------------------------
# Default LLM callable (deferred import so tests can run without anthropic)
# ---------------------------------------------------------------------------

def _default_llm_call(
    model: str, system: str, messages: list[dict], max_tokens: int
) -> dict:
    """Call the Anthropic Messages API.

    Defers the anthropic import to call time; raises RuntimeError if the SDK
    is missing or ANTHROPIC_API_KEY is not set.  The caller (run_reg2627_pass)
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

    The returned callable satisfies the run_reg2627_pass llm_call contract:
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
# Public entry point
# ---------------------------------------------------------------------------

def run_reg2627_pass(
    period: dict,
    *,
    line_source: Callable[[], list[dict]],
    llm_call: Callable[[str, str, list[dict], int], dict] | None = None,
    model_id: str = _PINNED_MODEL,
) -> dict:
    """Run the Regulation 26/27 disallowed input tax reasoning pass.

    Args:
        period:      {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
        line_source: callable → list of purchase invoice line dicts.
                     Required keys per line: doc_num, doc_type, doc_date,
                     card_name, line_index, vat_group, line_description,
                     line_total, tax_total.  Only lines with vat_group=="SI"
                     are forwarded to the LLM.
        llm_call:    injectable; defaults to _default_llm_call (real Anthropic
                     Messages API).  Signature:
                       (model: str, system: str, messages: list[dict], max_tokens: int)
                       → {"content": str, "input_tokens": int, "output_tokens": int}
        model_id:    pinned Anthropic model string.

    Returns the complete judgment-candidates artefact dict — always, even on error.
    The caller (run_agent.py) must never discard this artefact on failure.
    """
    _llm = llm_call if llm_call is not None else _default_llm_call
    generated_at = datetime.now(timezone.utc).isoformat()

    def _errored(error_message: str, kb_hash: str = "sha256:" + "0" * 64) -> dict:
        return {
            "artefact_type": "judgment-candidates",
            "schema_version": "1.0",
            "check": "reg-26-27-disallowed-input-tax",
            "period": {
                "start": str(period.get("start", "")),
                "end": str(period.get("end", "")),
            },
            "generated_at": generated_at,
            "status": "errored",
            "error": error_message,
            "provenance": {
                "in_run_path": True,
                "model_id": model_id,
                "prompt_version": _PROMPT_VERSION,
                "kb_slice_hash": kb_hash,
                "validation_status": "unvalidated",
            },
            "input_summary": {"si_purchase_lines_examined": 0, "documents_examined": 0},
            "candidates": [],
            "candidate_count": 0,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "disclaimer": _DISCLAIMER,
        }

    # Load KB — if this fails we cannot run the pass meaningfully.
    try:
        kb_text = _KB_PATH.read_text(encoding="utf-8")
        kb_hash = _kb_hash()
    except Exception as exc:
        log.error("reg2627: KB load failed: %s", exc)
        return _errored(f"KB load failed: {exc}")

    # Fetch lines via the injectable source.
    try:
        all_lines = line_source()
    except Exception as exc:
        log.error("reg2627: line_source failed: %s", exc)
        return _errored(f"line_source failed: {exc}", kb_hash)

    si_lines = [
        ln for ln in all_lines
        if str(ln.get("vat_group") or "").strip() == "SI"
    ]
    doc_nums = {ln["doc_num"] for ln in si_lines}

    # No SI lines — emit a clean ok artefact without calling the LLM.
    if not si_lines:
        return {
            "artefact_type": "judgment-candidates",
            "schema_version": "1.0",
            "check": "reg-26-27-disallowed-input-tax",
            "period": {"start": period["start"], "end": period["end"]},
            "generated_at": generated_at,
            "status": "ok",
            "error": None,
            "provenance": {
                "in_run_path": True,
                "model_id": model_id,
                "prompt_version": _PROMPT_VERSION,
                "kb_slice_hash": kb_hash,
                "validation_status": "unvalidated",
            },
            "input_summary": {"si_purchase_lines_examined": 0, "documents_examined": 0},
            "candidates": [],
            "candidate_count": 0,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "disclaimer": _DISCLAIMER,
        }

    system_prompt = _build_system_prompt(kb_text)

    # Process SI lines in batches so no single response exceeds _MAX_TOKENS.
    all_candidates: list[dict] = []
    total_input_tokens  = 0
    total_output_tokens = 0
    n_batches = (len(si_lines) + _BATCH_SIZE - 1) // _BATCH_SIZE

    for batch_idx in range(n_batches):
        batch = si_lines[batch_idx * _BATCH_SIZE : (batch_idx + 1) * _BATCH_SIZE]
        user_message = _build_user_message(period, batch)

        try:
            llm_result = _llm(
                model_id,
                system_prompt,
                [{"role": "user", "content": user_message}],
                _MAX_TOKENS,
            )
        except Exception as exc:
            log.error("reg2627: LLM call failed (batch %d/%d): %s",
                      batch_idx + 1, n_batches, exc)
            return _errored(f"LLM call failed: {exc}", kb_hash)

        raw_content = llm_result.get("content", "")
        total_input_tokens  += int(llm_result.get("input_tokens",  0))
        total_output_tokens += int(llm_result.get("output_tokens", 0))

        try:
            # Strip optional markdown code fences that some models emit.
            stripped = raw_content.strip()
            if stripped.startswith("```"):
                stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
            if stripped.endswith("```"):
                stripped = stripped.rsplit("```", 1)[0]
            stripped = stripped.strip()

            parsed = json.loads(stripped)
            if not isinstance(parsed, list):
                raise ValueError(
                    f"expected JSON array from LLM, got {type(parsed).__name__}"
                )
            all_candidates.extend(_validate_candidate(c) for c in parsed)
        except Exception as exc:
            snippet = raw_content[:300] if raw_content else "<empty>"
            log.error("reg2627: response validation failed: %s | content: %s", exc, snippet)
            return _errored(
                f"LLM response invalid: {exc} | snippet: {snippet}",
                kb_hash,
            )

    return {
        "artefact_type": "judgment-candidates",
        "schema_version": "1.0",
        "check": "reg-26-27-disallowed-input-tax",
        "period": {"start": period["start"], "end": period["end"]},
        "generated_at": generated_at,
        "status": "ok",
        "error": None,
        "provenance": {
            "in_run_path": True,
            "model_id": model_id,
            "prompt_version": _PROMPT_VERSION,
            "kb_slice_hash": kb_hash,
            "validation_status": "unvalidated",
        },
        "input_summary": {
            "si_purchase_lines_examined": len(si_lines),
            "documents_examined": len(doc_nums),
        },
        "candidates": all_candidates,
        "candidate_count": len(all_candidates),
        "token_usage": {
            "input_tokens":  total_input_tokens,
            "output_tokens": total_output_tokens,
        },
        "disclaimer": _DISCLAIMER,
    }
