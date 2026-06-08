"""reasoning/label_fixture.py — Two-pass Opus-4-8 labelling of the Reg 26/27 DRAFT fixture.

PROVISIONAL: All labels produced here are LLM-derived and UNVALIDATED.
validation_status stays "unvalidated". Do not cite these labels as a gate result
or accuracy claim without independent human GST-specialist review.

The labeller is BLIND to existing fixture labels: it strips each line to the same
observable allow-list used by the measurement-harness LLM input path before calling
the model. No expected_*, needs_human_review, proposed, iras_basis, or determinability
field reaches the model.

Two independent passes are run per line.  Disagreement on disposition or
determinability forces determinability="indeterminate" and contested=True.
confidence="low" on either pass also forces indeterminate.

Mirrors reg2627.py: injectable line_source + llm_call so tests run without network.
anthropic import is deferred inside _default_llm_call.
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_KB_REG2627_PATH  = _REPO_ROOT / "knowledge-base" / "slices" / "reg2627.md"
_KB_BUSINESS_PATH = _REPO_ROOT / "knowledge-base" / "slices" / "business-context.md"
_DRAFT_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "reg2627-labelled-lines.DRAFT.json"
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "exploration-notes" / "t2.7-measurement"

_LABELLER_MODEL = "claude-opus-4-8"
_MAX_TOKENS_PER_CALL = 512   # per-line; JSON label is small

_PROVISIONAL_HEADER = (
    "PROVISIONAL — opus-4-8 labelling pass; LLM-derived; "
    "validation_status: unvalidated; "
    "the opus-4-8 measurement row is the least independent because labels are opus-derived."
)

# Observable fields sent to the model — same allow-list as run_measurement._LLM_INPUT_FIELDS
_LLM_INPUT_FIELDS: frozenset[str] = frozenset({
    "doc_num", "doc_type", "doc_date", "card_name",
    "line_index", "vat_group", "line_description",
    "line_total", "tax_total",
})

# Valid category values (incl. §6.1.6 medical split, entertainment per §6.1.3, and n/a)
_LABEL_CATEGORIES: frozenset[str] = frozenset({
    "club_subscriptions",   # §6.1.6 item 1
    "medical_expenses",     # §6.1.6 item 2 — treatment / consultation costs
    "medical_insurance",    # §6.1.6 item 3 — medical & accident insurance premiums
    "family_benefits",      # §6.1.6 item 4
    "motor_car_s_plate",    # §6.1.6 item 5
    "other_disallowed",     # §6.1.6 item 6 — betting / sweepstakes / games of chance
    "entertainment",        # §6.1.3 claimable; retained as category for per_category bucketing
    "n/a",                  # no applicable Reg 26/27 category
})

_DISPOSITIONS       = frozenset({"disallowed", "claimable"})
_DETERMINABILITIES  = frozenset({"determinable", "indeterminate"})
_CONFIDENCES        = frozenset({"high", "medium", "low"})
_CONF_RANK          = {"high": 2, "medium": 1, "low": 0}


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _kb_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _build_system_prompt() -> str:
    """Build the full-context labeller system prompt from the two KB slices."""
    kb_reg2627  = _KB_REG2627_PATH.read_text(encoding="utf-8")
    kb_business = _KB_BUSINESS_PATH.read_text(encoding="utf-8")

    cats = (
        "club_subscriptions | medical_expenses | medical_insurance | "
        "family_benefits | motor_car_s_plate | other_disallowed | "
        "entertainment | n/a"
    )

    return f"""You are a Singapore GST specialist producing ground-truth labels for a measurement fixture.

THIS IS A LABELLING PASS — NOT A CANDIDATE-SURFACING PASS.
Determine the CORRECT Reg 26/27 GST treatment for each line from IRAS sources.

{_PROVISIONAL_HEADER}

=== BUSINESS CONTEXT ===
{kb_business}

=== REGULATORY KNOWLEDGE BASE ===
{kb_reg2627}

=== DETERMINABLE vs INDETERMINATE (KEY DISTINCTION) ===
"determinable": the correct Reg 26/27 treatment can be established from the line data alone,
combined with IRAS source documents and the generic-SME assumption above. No further records
(payroll, vehicle registration, underlying invoices) are needed.

"indeterminate": the correct treatment depends on context not present in the line data:
  - Business-type specifics (car dealer? clinic? insurance broker?)
  - WICA mandatory status (cannot confirm from description alone)
  - Vehicle type ambiguity (bare "VAN" — could be goods vehicle or MPV/private car)
  - Whether external parties were present (bare "DINNER" — internal staff or clients?)
  - Any other external context absent from the observable line fields
RULE: confidence="low" MUST produce determinability="indeterminate" regardless of other factors.

=== ENTERTAINMENT RULE (CRITICAL — READ CAREFULLY) ===
Entertainment is NOT a Reg 26/27 disallowed category. §6.1.6 does not list it.
Food and drink entertainment for internal staff OR external parties is CLAIMABLE per §6.1.3.
- Assign disposition="claimable" and category="entertainment" for clean F&B entertainment.
- Assign disposition="disallowed" ONLY if the line is also explicitly a disallowed §6.1.6 category
  (e.g. a club membership invoice that happens to involve entertainment).
- Do NOT assign disposition="disallowed" for restaurant meals, catering, or F&B invoices.

=== MEDICAL SPLIT (TWO DISTINCT §6.1.6 CATEGORIES) ===
"medical_expenses"  = §6.1.6 item 2: treatment, GP, dental, hospitalisation, health screening, TCM.
  Carve-outs: WICA/collective-agreement mandatory; post-Oct-2021 work-environment health; COVID-19.
"medical_insurance" = §6.1.6 item 3: insurance PREMIUMS (group medical, personal accident insurance).
  Carve-out: mandatory under WICA or collective agreement.
Use the correct sub-category. Do not mix treatment costs with insurance premiums.

=== §6.1.6 SIX-CATEGORY SUMMARY ===
1. club_subscriptions  — subscription, membership, joining, transfer fees at sporting/recreational clubs.
2. medical_expenses    — staff medical treatment costs (see carve-outs above).
3. medical_insurance   — staff medical & accident insurance premiums (see carve-outs above).
4. family_benefits     — any goods or services benefiting family members / relatives of staff.
5. motor_car_s_plate   — costs and running expenses on S-plate / privately-registered motor cars,
                         COE-renewed company cars (on/after 1 Apr 1998), rental cars (on/after 1 Jul 1999).
6. other_disallowed    — transactions involving betting, sweepstakes, lotteries, fruit machines, games of chance.

=== OUTPUT FORMAT ===
Return ONLY a JSON object with these EXACT keys (no markdown fences, no surrounding text):
{{
  "disposition":      "disallowed" | "claimable",
  "determinability":  "determinable" | "indeterminate",
  "category":         {cats},
  "iras_basis":       "<specific IRAS citation, e.g. §6.1.6 item 1, General Guide>",
  "rationale":        "<one concise sentence>",
  "confidence":       "high" | "medium" | "low"
}}

Rules:
- "disallowed": input tax disallowed under Reg 26/27 for a generic SME.
- "claimable": input tax is claimable (NOT a Reg 26/27 candidate).
- Set category to the most specific applicable value. Claimable non-entertainment lines → "n/a".
- confidence="low" MUST result in determinability="indeterminate".
- Return ONLY the JSON object. Nothing else."""


def _build_user_message(observable_line: dict) -> str:
    return (
        "Label this Singapore GST purchase invoice line:\n"
        f"{json.dumps(observable_line, ensure_ascii=False)}\n\n"
        "Return ONLY the JSON label object."
    )


# ---------------------------------------------------------------------------
# Allow-list strip (leakage prevention)
# ---------------------------------------------------------------------------

def _strip_to_observable(line: dict) -> dict:
    """Return only the observable fields; drop every annotation/ground-truth key."""
    return {k: line[k] for k in _LLM_INPUT_FIELDS if k in line}


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

def _validate_label(raw_text: str) -> dict:
    """Parse and validate one labeller JSON response.  Raises ValueError on bad data.

    Side-effects:
      - Strips accidental markdown fences from the model output.
      - Enforces: confidence="low" → determinability="indeterminate".
    """
    text = raw_text.strip()
    if text.startswith("```"):
        lines_text = text.splitlines()
        inner = lines_text[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"labeller response is not valid JSON: {exc}\nRaw (first 300): {raw_text[:300]}"
        ) from exc

    if not isinstance(obj, dict):
        raise ValueError(f"labeller response must be a JSON object, got {type(obj).__name__}")

    required = {"disposition", "determinability", "category", "iras_basis", "rationale", "confidence"}
    missing = required - set(obj.keys())
    if missing:
        raise ValueError(f"labeller response missing fields: {sorted(missing)}")

    if obj["disposition"] not in _DISPOSITIONS:
        raise ValueError(f"invalid disposition {obj['disposition']!r}; must be one of {sorted(_DISPOSITIONS)}")
    if obj["determinability"] not in _DETERMINABILITIES:
        raise ValueError(f"invalid determinability {obj['determinability']!r}")
    if obj["category"] not in _LABEL_CATEGORIES:
        raise ValueError(f"invalid category {obj['category']!r}; must be one of {sorted(_LABEL_CATEGORIES)}")
    if obj["confidence"] not in _CONFIDENCES:
        raise ValueError(f"invalid confidence {obj['confidence']!r}; must be one of {sorted(_CONFIDENCES)}")

    # Enforce invariant: low confidence → indeterminate
    if obj["confidence"] == "low":
        obj["determinability"] = "indeterminate"

    return {
        "disposition":    obj["disposition"],
        "determinability": obj["determinability"],
        "category":       obj["category"],
        "iras_basis":     str(obj["iras_basis"]),
        "rationale":      str(obj["rationale"]),
        "confidence":     obj["confidence"],
    }


# ---------------------------------------------------------------------------
# Two-pass reconciliation
# ---------------------------------------------------------------------------

def _reconcile(pass1: dict, pass2: dict) -> dict:
    """Reconcile two independent validated label dicts.

    Disagreement on disposition OR determinability → contested=True, determinability="indeterminate".
    Lower confidence of the two passes is used.  Low confidence on either also forces indeterminate.
    """
    contested = (
        pass1["disposition"] != pass2["disposition"]
        or pass1["determinability"] != pass2["determinability"]
    )
    lower_conf = (
        pass1["confidence"]
        if _CONF_RANK[pass1["confidence"]] <= _CONF_RANK[pass2["confidence"]]
        else pass2["confidence"]
    )
    determinability = (
        "indeterminate"
        if (contested or lower_conf == "low")
        else pass1["determinability"]
    )
    return {
        "disposition":    pass1["disposition"],
        "determinability": determinability,
        "contested":      contested,
        "category":       pass1["category"],
        "iras_basis":     pass1["iras_basis"],
        "rationale":      pass1["rationale"],
        "confidence":     lower_conf,
    }


# ---------------------------------------------------------------------------
# Fixture line construction
# ---------------------------------------------------------------------------

def _to_fixture_fields(original: dict, final: dict) -> dict:
    """Build the output fixture line from observable fields + reconciled label."""
    expected_candidate = final["disposition"] == "disallowed"
    cat = final["category"]

    out: dict = {k: original[k] for k in _LLM_INPUT_FIELDS if k in original}
    out["expected_candidate"] = expected_candidate
    if cat != "n/a":
        out["expected_category"] = cat
    out["determinability"]    = final["determinability"]
    out["needs_human_review"] = expected_candidate or final["determinability"] == "indeterminate"
    out["iras_basis"]  = final["iras_basis"]
    out["rationale"]   = final["rationale"]
    out["confidence"]  = final["confidence"]
    out["contested"]   = final["contested"]
    out["proposed"]    = True
    out["label_source"] = "opus-4-8"
    return out


# ---------------------------------------------------------------------------
# Default LLM callable (deferred anthropic import)
# ---------------------------------------------------------------------------

def _default_llm_call(
    model: str, system: str, messages: list[dict], max_tokens: int
) -> dict:
    try:
        import anthropic  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(f"anthropic SDK not installed: {exc}") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model, max_tokens=max_tokens, system=system, messages=messages,
    )
    content = response.content[0].text if response.content else ""
    return {
        "content":       content,
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


# ---------------------------------------------------------------------------
# Per-line call helper
# ---------------------------------------------------------------------------

def _call_once(
    observable: dict,
    system: str,
    llm_call: Callable,
    model_id: str,
) -> tuple[dict | None, str, str]:
    """One labelling call.  Returns (validated_label_or_None, raw_content, error_str)."""
    msg = _build_user_message(observable)
    try:
        resp = llm_call(model_id, system, [{"role": "user", "content": msg}], _MAX_TOKENS_PER_CALL)
        raw = resp.get("content", "")
        label = _validate_label(raw)
        return label, raw, ""
    except Exception as exc:  # noqa: BLE001
        return None, "", str(exc)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_labelling_pass(
    *,
    line_source: Callable[[], list[dict]],
    llm_call: Callable[[str, str, list[dict], int], dict] | None = None,
    model_id: str = _LABELLER_MODEL,
    fixture_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict:
    """Run two-pass Opus-4-8 labelling on DRAFT fixture lines.

    Args:
        line_source:  callable → list of ORIGINAL annotated lines from the DRAFT fixture.
                      The pass strips each line to observable-only fields internally.
        llm_call:     injectable; defaults to _default_llm_call (real Anthropic API).
                      Signature: (model, system, messages, max_tokens) → {content, input_tokens, output_tokens}
        model_id:     Anthropic model to use.
        fixture_path: if provided, the updated DRAFT fixture is written here.
        output_dir:   if provided, labelling artefact .json and .md are written here.

    Returns the labelling artefact dict (always, even on partial error).
    """
    _llm = llm_call if llm_call is not None else _default_llm_call
    run_at     = datetime.now(timezone.utc)
    run_at_str = run_at.isoformat()
    date_str   = run_at.strftime("%Y%m%d")

    try:
        system = _build_system_prompt()
    except Exception as exc:  # noqa: BLE001
        return _error_artefact(f"failed to build system prompt: {exc}", run_at_str, model_id)

    try:
        original_lines = line_source()
    except Exception as exc:  # noqa: BLE001
        return _error_artefact(f"line_source() failed: {exc}", run_at_str, model_id)

    artefact_lines:   list[dict] = []
    fixture_lines:    list[dict] = []
    total_in_tok  = 0
    total_out_tok = 0
    contested_n   = 0
    indeterminate_n = 0
    error_n       = 0

    for original in original_lines:
        observable = _strip_to_observable(original)
        key = (original.get("doc_num"), original.get("line_index"))

        p1, raw1, err1 = _call_once(observable, system, _llm, model_id)
        p2, raw2, err2 = _call_once(observable, system, _llm, model_id)

        if p1 is None or p2 is None:
            error_n += 1
            log.warning("Line %s labelling error: %s %s", key, err1, err2)
            final: dict = {
                "disposition":     "claimable",   # conservative default on failure
                "determinability": "indeterminate",
                "contested":       True,
                "category":        "n/a",
                "iras_basis":      "error",
                "rationale":       f"labelling error: {(err1 or err2)[:120]}",
                "confidence":      "low",
            }
        else:
            final = _reconcile(p1, p2)

        if final["contested"]:
            contested_n += 1
        if final["determinability"] == "indeterminate":
            indeterminate_n += 1

        fixture_lines.append(_to_fixture_fields(original, final))
        artefact_lines.append({
            "doc_num":          original.get("doc_num"),
            "line_index":       original.get("line_index"),
            "line_description": original.get("line_description"),
            "pass_1": {"raw": raw1, "parsed": p1, "error": err1 if p1 is None else None},
            "pass_2": {"raw": raw2, "parsed": p2, "error": err2 if p2 is None else None},
            "final_label":      final,
            "fixture_mapping": {
                "expected_candidate":  fixture_lines[-1]["expected_candidate"],
                "expected_category":   fixture_lines[-1].get("expected_category"),
                "determinability":     fixture_lines[-1]["determinability"],
                "needs_human_review":  fixture_lines[-1]["needs_human_review"],
            },
        })

    artefact = {
        "_provisional_header": _PROVISIONAL_HEADER,
        "run_metadata": {
            "model":                      model_id,
            "run_at":                     run_at_str,
            "kb_reg2627_hash":            _kb_hash(_KB_REG2627_PATH),
            "kb_business_context_hash":   _kb_hash(_KB_BUSINESS_PATH),
            "fixture_path":               str(fixture_path or _DRAFT_FIXTURE_PATH),
            "line_count":                 len(original_lines),
            "contested_count":            contested_n,
            "indeterminate_count":        indeterminate_n,
            "error_count":                error_n,
            "total_input_tokens":         total_in_tok,
            "total_output_tokens":        total_out_tok,
        },
        "lines": artefact_lines,
    }

    if fixture_path is not None:
        _write_fixture(fixture_path, fixture_lines, run_at_str, model_id)

    if output_dir is not None:
        _write_artefact(output_dir, artefact, date_str)

    return artefact


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _write_fixture(
    fixture_path: Path,
    fixture_lines: list[dict],
    run_at_str: str,
    model_id: str,
) -> None:
    try:
        existing: dict = json.loads(fixture_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        existing = {}

    meta = existing.get("_meta", {})
    meta["label_source"]        = f"{model_id} labelling pass {run_at_str[:10]}"
    meta["labels_provisional"]  = True
    meta["ground_truth_set_by"] = (
        f"DRAFT — {model_id} labelling pass {run_at_str[:10]}; "
        "LLM-derived; NOT reviewed by human GST specialist"
    )
    existing["_meta"]  = meta
    existing["lines"]  = fixture_lines

    out = {"_meta": existing["_meta"]}
    if "assumptions" in existing:
        out["assumptions"] = existing["assumptions"]
    out["lines"] = fixture_lines

    fixture_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log.info("Fixture written → %s (%d lines)", fixture_path, len(fixture_lines))


def _write_artefact(output_dir: Path, artefact: dict, date_str: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"labelling-pass-{date_str}.json"
    json_path.write_text(
        json.dumps(artefact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    meta = artefact["run_metadata"]
    md_rows = [
        f"# Labelling Pass — {date_str}",
        "",
        f"> {artefact['_provisional_header']}",
        "",
        "## Run metadata",
        "",
        "| Key | Value |",
        "|-----|-------|",
        f"| Model | `{meta.get('model','')}` |",
        f"| Run at | {meta.get('run_at','')} |",
        f"| Lines | {meta.get('line_count','')} |",
        f"| Contested | {meta.get('contested_count','')} |",
        f"| Indeterminate | {meta.get('indeterminate_count','')} |",
        f"| Errors | {meta.get('error_count','')} |",
        f"| reg2627.md hash | `{meta.get('kb_reg2627_hash','')}` |",
        f"| business-context.md hash | `{meta.get('kb_business_context_hash','')}` |",
        "",
        "## Per-line summary",
        "",
        "| doc_num | idx | description | disposition | category | determinability | contested | conf |",
        "|---------|-----|-------------|-------------|----------|-----------------|-----------|------|",
    ]
    for ln in artefact["lines"]:
        fl  = ln.get("final_label", {})
        desc = str(ln.get("line_description", ""))[:38]
        md_rows.append(
            f"| {ln.get('doc_num')} | {ln.get('line_index')} | {desc} | "
            f"{fl.get('disposition','')} | {fl.get('category','')} | "
            f"{fl.get('determinability','')} | {fl.get('contested','')} | "
            f"{fl.get('confidence','')} |"
        )

    md_path = output_dir / f"labelling-pass-{date_str}.md"
    md_path.write_text("\n".join(md_rows) + "\n", encoding="utf-8")
    log.info("Artefact written → %s", json_path)


def _error_artefact(msg: str, run_at_str: str, model_id: str) -> dict:
    return {
        "_provisional_header": _PROVISIONAL_HEADER,
        "run_metadata": {"error": msg, "run_at": run_at_str, "model": model_id},
        "lines": [],
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m reasoning.label_fixture",
        description=(
            "Two-pass Opus-4-8 labelling of the Reg 26/27 DRAFT fixture.\n\n"
            f"PROVISIONAL — {_PROVISIONAL_HEADER}\n\n"
            "Reads ANTHROPIC_API_KEY from the environment (or .env). "
            "Fails fast if the key is absent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fixture", type=Path,
        default=_DRAFT_FIXTURE_PATH,
        metavar="PATH",
        help=(
            f"Fixture JSON to label "
            f"(default: {_DRAFT_FIXTURE_PATH.relative_to(_REPO_ROOT)})"
        ),
    )
    parser.add_argument(
        "--out", type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=(
            f"Directory for the dated artefact .json/.md output "
            f"(default: {_DEFAULT_OUTPUT_DIR.relative_to(_REPO_ROOT)})"
        ),
    )
    parser.add_argument(
        "--write-fixture", action="store_true",
        help=(
            "Write labelled results back to --fixture (mutates the file in place). "
            "Without this flag only the dated artefact is written; the fixture is NOT changed."
        ),
    )
    args = parser.parse_args()

    # Load .env
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
        load_dotenv()
    except ImportError:
        pass

    # Fail fast before any expensive API calls
    _api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not _api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "Export it or add it to .env, then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load source lines
    _fixture_path: Path = args.fixture
    try:
        _fixture_data = json.loads(_fixture_path.read_text(encoding="utf-8"))
        _original_lines: list[dict] = _fixture_data["lines"]
    except Exception as _exc:  # noqa: BLE001
        print(f"ERROR: could not load fixture {_fixture_path}: {_exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\nLabelling pass — {_LABELLER_MODEL}")
    print(f"  Fixture:       {_fixture_path}  ({len(_original_lines)} lines)")
    print(f"  Output dir:    {args.out}")
    print(f"  Write fixture: {args.write_fixture}")
    print(f"  {_PROVISIONAL_HEADER}")
    print()

    _artefact = run_labelling_pass(
        line_source=lambda: _original_lines,
        llm_call=None,                              # uses _default_llm_call → real Anthropic API
        fixture_path=_fixture_path if args.write_fixture else None,
        output_dir=args.out,
    )

    # --- Summary ---
    _meta = _artefact.get("run_metadata", {})
    _n_total = _meta.get("line_count", 0)
    _n_indet = _meta.get("indeterminate_count", 0)
    _n_det   = _n_total - _n_indet
    _n_cont  = _meta.get("contested_count", 0)
    _n_err   = _meta.get("error_count", 0)
    _n_low   = sum(
        1 for ln in _artefact.get("lines", [])
        if ln.get("final_label", {}).get("confidence") == "low"
    )
    _date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    _artefact_path = args.out / f"labelling-pass-{_date_str}.json"

    print("\nSummary")
    print(f"  Lines labelled:   {_n_total}")
    print(f"  Determinable:     {_n_det}")
    print(f"  Indeterminate:    {_n_indet}")
    print(f"  Contested:        {_n_cont}")
    print(f"  Low-confidence:   {_n_low}")
    if _n_err:
        print(f"  Errors:           {_n_err}")
    if args.write_fixture:
        print(f"  Fixture written:  {_fixture_path}")
    print(f"  Artefact:         {_artefact_path}")
    print()
    print(
        "REMINDER: validation_status stays 'unvalidated'. Labels are LLM-derived (opus-4-8).\n"
        "Do not promote to reg2627-labelled-lines.json without independent GST-specialist review."
    )
