"""reasoning/reasoning_pass.py — skill-parameterized reasoning-candidate shell (T2.27).

Generalizes the Reg 26/27 pass (reasoning/reg2627.py) into a reusable shell so a
second Group-A skill is cheap to add.  reg2627 is now one SkillSpec bound over
this generic engine; run_reg2627_pass is a thin wrapper over run_reasoning_pass
and its artefact is byte-identical.

Invariants (identical to the reg2627 pass, now enforced generically):
- Outputs are candidates for human review only.  Every candidate's `phrasing`
  starts with "Consider reviewing whether" — enforced here for EVERY spec, not
  just reg2627.  The pass NEVER asserts a compliance conclusion.
- Runs beside the deterministic chain, never inside it.  This module imports NO
  orchestrator/, audit_bundle/, SAP client, or anthropic.  (The default Anthropic
  llm_call lives in reasoning/reg2627.py and is passed in via SkillSpec, keeping
  the sole lazy anthropic SDK import confined there.)
- Emits the artefact dict unconditionally — status="errored" on any failure.
- line_source and llm_call are injectable so tests use fakes: no test ever hits
  a live SAP instance or the live Anthropic API.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# Default knowledge-base slice directory (repo-root/knowledge-base/slices).
# A SkillSpec may override kb_dir (e.g. a TEST-ONLY stub pointing at a fixtures
# path) so a stub spec never implies a real rule under knowledge-base/slices/.
_DEFAULT_KB_DIR = Path(__file__).resolve().parent.parent / "knowledge-base" / "slices"

# Confidence vocabulary is skill-agnostic — shared by every spec.
_CONFIDENCE_VALUES = frozenset({"low", "medium", "high"})

# Callable signature for an injectable LLM call:
#   (model: str, system: str, messages: list[dict], max_tokens: int)
#     -> {"content": str, "input_tokens": int, "output_tokens": int}
LlmCall = Callable[[str, str, list, int], dict]


# ---------------------------------------------------------------------------
# Skill specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillSpec:
    """Everything skill-specific about one reasoning-candidate pass.

    The generic engine (run_reasoning_pass) reads all per-skill behaviour from a
    SkillSpec so adding a second Group-A skill means writing a new spec, not
    forking the pass.  reg2627 is REG2627_SPEC (see reasoning/reg2627.py).

    Attributes:
        skill_id:            Stable short id (e.g. "reg2627").  Also the bundle
                             routing key for the second reasoning stream
                             (steps/<skill_id>-candidates.json).
        artefact_type:       "artefact_type" field stamped into the output dict.
        check:               "check" identifier stamped into the output dict.
        prompt_version:      provenance.prompt_version stamp.
        kb_slice_name:       Basename (no extension) of the KB slice markdown
                             file under kb_dir.
        suspected_categories: Allowed values for a candidate's suspected_category.
        vat_group:           The tax code(s) this skill selects — either a single
                             canonical code (str, e.g. "SI") or a frozenset of
                             codes (e.g. frozenset({"ES33","ESN33"})).  Only lines
                             whose vat_group matches are forwarded to the LLM.
                             For a str spec the single code is also stamped onto
                             every emitted candidate (unchanged pre-T2.29
                             behaviour); for a frozenset spec each candidate keeps
                             its OWN per-line code so a multi-code skill does not
                             flatten every candidate to one value.
        batch_size:          Max lines per LLM call.
        max_tokens:          Output token budget per batch.
        disclaimer:          Human-review disclaimer stamped into the artefact.
        lines_examined_label: input_summary key for the filtered-line count
                             (reg2627 uses "si_purchase_lines_examined").
        build_system_prompt: (kb_text) -> system prompt string.
        build_user_message:  (period, lines) -> user message string.
        kb_dir:              Directory holding <kb_slice_name>.md.  Defaults to
                             knowledge-base/slices/.
        default_llm_call:    Fallback llm_call used when the caller passes
                             llm_call=None.  reg2627 binds the lazy Anthropic
                             caller here; None means "must inject an llm_call".
    """
    skill_id: str
    artefact_type: str
    check: str
    prompt_version: str
    kb_slice_name: str
    suspected_categories: frozenset
    vat_group: "str | frozenset[str]"
    batch_size: int
    max_tokens: int
    disclaimer: str
    lines_examined_label: str
    build_system_prompt: Callable[[str], str]
    build_user_message: Callable[[dict, list], str]
    kb_dir: Path = _DEFAULT_KB_DIR
    default_llm_call: "LlmCall | None" = None

    def __post_init__(self):
        # Validation only — no attribute assignment, so this is safe on a frozen
        # dataclass.  vat_group must be a single str or a frozenset of str; other
        # types (int, mutable set, frozenset with non-str members) are rejected.
        vg = self.vat_group
        if isinstance(vg, str):
            return
        if isinstance(vg, frozenset) and all(isinstance(x, str) for x in vg):
            return
        raise TypeError(
            "SkillSpec.vat_group must be a str or a frozenset[str]; "
            f"got {type(vg).__name__}"
        )

    def allowed_vat_groups(self) -> "frozenset[str]":
        """Return the set of codes this spec selects (str → single-element set)."""
        vg = self.vat_group
        return vg if isinstance(vg, frozenset) else frozenset({vg})


# ---------------------------------------------------------------------------
# KB slice loading + hashing (parameterized on the spec)
# ---------------------------------------------------------------------------

def kb_path(spec: SkillSpec) -> Path:
    """Resolve the KB slice file for a spec: <kb_dir>/<kb_slice_name>.md."""
    return spec.kb_dir / f"{spec.kb_slice_name}.md"


def kb_hash(spec: SkillSpec) -> str:
    """Return the sha256 provenance hash of the spec's KB slice bytes."""
    data = kb_path(spec).read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Candidate validation (parameterized on the spec)
# ---------------------------------------------------------------------------

def validate_candidate(spec: SkillSpec, raw: dict) -> dict:
    """Validate and normalise one candidate against a spec.  Raises ValueError.

    The candidate SHAPE is skill-agnostic (13 fields); the suspected_category
    enum and the stamped vat_group come from the spec.  The "Consider reviewing
    whether" phrasing invariant is enforced here for every skill.
    """
    required = {
        "doc_num", "doc_type", "doc_date", "card_name", "line_index",
        "vat_group", "line_description", "line_total", "tax_total",
        "suspected_category", "reasoning", "phrasing", "confidence",
    }
    missing = required - set(raw.keys())
    if missing:
        raise ValueError(f"candidate missing fields: {sorted(missing)}")

    cat = raw.get("suspected_category")
    if cat not in spec.suspected_categories:
        raise ValueError(
            f"invalid suspected_category {cat!r}; "
            f"must be one of {sorted(spec.suspected_categories)}"
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
        # str spec: force the single spec code (unchanged pre-T2.29 behaviour —
        # byte-identical for reg2627, whose filter guarantees line vat_group=="SI").
        # frozenset spec: keep the candidate's OWN per-line code so a multi-code
        # skill does not flatten every candidate to a single value.
        "vat_group": (
            str(raw["vat_group"])
            if isinstance(spec.vat_group, frozenset)
            else spec.vat_group
        ),
        "line_description": str(raw["line_description"]),
        "line_total": float(raw["line_total"]),
        "tax_total": float(raw["tax_total"]),
        "suspected_category": str(cat),
        "reasoning": str(raw["reasoning"]),
        "phrasing": phrasing,
        "confidence": str(conf),
    }


# ---------------------------------------------------------------------------
# Public generic entry point
# ---------------------------------------------------------------------------

def run_reasoning_pass(
    spec: SkillSpec,
    period: dict,
    *,
    line_source: Callable[[], list],
    llm_call: "LlmCall | None" = None,
    model_id: str,
) -> dict:
    """Run a skill-parameterized reasoning-candidate pass and return its artefact.

    Args:
        spec:        The SkillSpec describing this skill's behaviour.
        period:      {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}.
        line_source: callable -> list of line dicts.  Only lines with
                     vat_group == spec.vat_group are forwarded to the LLM.
        llm_call:    injectable; defaults to spec.default_llm_call when None.
        model_id:    model string forwarded to llm_call and stamped into provenance.

    Returns the complete reasoning-candidates artefact dict — always, even on
    error (status="errored").  The caller must never discard it on failure.
    """
    _llm = llm_call if llm_call is not None else spec.default_llm_call
    generated_at = datetime.now(timezone.utc).isoformat()

    def _errored(error_message: str, slice_hash: str = "sha256:" + "0" * 64) -> dict:
        return {
            "artefact_type": spec.artefact_type,
            "schema_version": "1.0",
            "check": spec.check,
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
                "prompt_version": spec.prompt_version,
                "kb_slice_hash": slice_hash,
                "validation_status": "unvalidated",
            },
            "input_summary": {spec.lines_examined_label: 0, "documents_examined": 0},
            "candidates": [],
            "candidate_count": 0,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "disclaimer": spec.disclaimer,
        }

    if _llm is None:
        return _errored("no llm_call available (inject one or set spec.default_llm_call)")

    # Load KB — if this fails we cannot run the pass meaningfully.
    try:
        kb_text = kb_path(spec).read_text(encoding="utf-8")
        slice_hash = kb_hash(spec)
    except Exception as exc:
        log.error("%s: KB load failed: %s", spec.skill_id, exc)
        return _errored(f"KB load failed: {exc}")

    # Fetch lines via the injectable source.
    try:
        all_lines = line_source()
    except Exception as exc:
        log.error("%s: line_source failed: %s", spec.skill_id, exc)
        return _errored(f"line_source failed: {exc}", slice_hash)

    # Normalize the spec's code(s) to a set once; a str spec becomes a single-
    # element set so membership is exactly the pre-T2.29 equality behaviour.
    allowed_vgs = spec.allowed_vat_groups()
    kept_lines = [
        ln for ln in all_lines
        if str(ln.get("vat_group") or "").strip() in allowed_vgs
    ]
    doc_nums = {ln["doc_num"] for ln in kept_lines}

    # No matching lines — emit a clean ok artefact without calling the LLM.
    if not kept_lines:
        return {
            "artefact_type": spec.artefact_type,
            "schema_version": "1.0",
            "check": spec.check,
            "period": {"start": period["start"], "end": period["end"]},
            "generated_at": generated_at,
            "status": "ok",
            "error": None,
            "provenance": {
                "in_run_path": True,
                "model_id": model_id,
                "prompt_version": spec.prompt_version,
                "kb_slice_hash": slice_hash,
                "validation_status": "unvalidated",
            },
            "input_summary": {spec.lines_examined_label: 0, "documents_examined": 0},
            "candidates": [],
            "candidate_count": 0,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "disclaimer": spec.disclaimer,
        }

    system_prompt = spec.build_system_prompt(kb_text)

    # Process matching lines in batches so no single response exceeds max_tokens.
    all_candidates: list = []
    total_input_tokens = 0
    total_output_tokens = 0
    n_batches = (len(kept_lines) + spec.batch_size - 1) // spec.batch_size

    for batch_idx in range(n_batches):
        batch = kept_lines[batch_idx * spec.batch_size : (batch_idx + 1) * spec.batch_size]
        user_message = spec.build_user_message(period, batch)

        try:
            llm_result = _llm(
                model_id,
                system_prompt,
                [{"role": "user", "content": user_message}],
                spec.max_tokens,
            )
        except Exception as exc:
            log.error("%s: LLM call failed (batch %d/%d): %s",
                      spec.skill_id, batch_idx + 1, n_batches, exc)
            return _errored(f"LLM call failed: {exc}", slice_hash)

        raw_content = llm_result.get("content", "")
        total_input_tokens += int(llm_result.get("input_tokens", 0))
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
            all_candidates.extend(validate_candidate(spec, c) for c in parsed)
        except Exception as exc:
            snippet = raw_content[:300] if raw_content else "<empty>"
            log.error("%s: response validation failed: %s | content: %s",
                      spec.skill_id, exc, snippet)
            return _errored(
                f"LLM response invalid: {exc} | snippet: {snippet}",
                slice_hash,
            )

    return {
        "artefact_type": spec.artefact_type,
        "schema_version": "1.0",
        "check": spec.check,
        "period": {"start": period["start"], "end": period["end"]},
        "generated_at": generated_at,
        "status": "ok",
        "error": None,
        "provenance": {
            "in_run_path": True,
            "model_id": model_id,
            "prompt_version": spec.prompt_version,
            "kb_slice_hash": slice_hash,
            "validation_status": "unvalidated",
        },
        "input_summary": {
            spec.lines_examined_label: len(kept_lines),
            "documents_examined": len(doc_nums),
        },
        "candidates": all_candidates,
        "candidate_count": len(all_candidates),
        "token_usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        },
        "disclaimer": spec.disclaimer,
    }
