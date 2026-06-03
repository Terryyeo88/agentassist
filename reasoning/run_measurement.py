"""
reasoning/run_measurement.py — Reg 26/27 multi-model recall / FP measurement CLI.

THIS IS NOT A PYTEST TEST.  Running it calls the Anthropic API and costs tokens.
Terry runs this manually after code changes to the reasoning pass.

Usage::
    python -m reasoning.run_measurement
    python -m reasoning.run_measurement --models claude-sonnet-4-6
    python -m reasoning.run_measurement --models claude-haiku-4-5-20251001 claude-sonnet-4-6

Gate (must be met before enabling show_ai_candidates or changing validation_status):
    recall   > 95 %
    fp_rate  <  5 %
    (weight recall — partial FP acceptance is preferable to missing disallowed expenses)

Output::
    Prints a per-model table to stdout.
    Writes a JSON record to exploration-notes/t2.7-measurement/<timestamp>.json
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Pricing table (input $/M tokens, output $/M tokens).
# UPDATE from https://console.anthropic.com/settings/usage when rates change.
# ---------------------------------------------------------------------------

RATE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (0.80,  4.00),
    "claude-sonnet-4-6":         (3.00,  15.00),
    "claude-opus-4-8":           (15.00, 75.00),
}

DEFAULT_MODELS: list[str] = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-8",
]

# Measurement gate thresholds
GATE_RECALL:  float = 0.95
GATE_FP_RATE: float = 0.05

_REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "reg2627-labelled-lines.json"
OUTPUT_DIR   = _REPO_ROOT / "exploration-notes" / "t2.7-measurement"

_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fields the model legitimately sees: observable SI-line data only.
# Annotation and ground-truth fields (expected_*, determinability,
# needs_human_review, proposed, iras_basis, _label_note, …) must never
# reach the LLM input — they encode the answer and would leak ground truth.
_LLM_INPUT_FIELDS: frozenset[str] = frozenset({
    "doc_num",
    "doc_type",
    "doc_date",
    "card_name",
    "line_index",
    "vat_group",
    "line_description",
    "line_total",
    "tax_total",
})


_DRAFT_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "reg2627-labelled-lines.DRAFT.json"


def _load_fixture(fixture_path: Path | None = None) -> tuple[list[dict], list[dict]]:
    """Return (labelled_lines, si_lines_for_llm).

    labelled_lines: full records including expected_* and annotation fields
                    (used by scorer only — never sent to the LLM).
    si_lines_for_llm: each line reduced to _LLM_INPUT_FIELDS only.
                      No annotation or ground-truth fields are included.

    Args:
        fixture_path: path to the fixture JSON; defaults to FIXTURE_PATH when None.

    Raises ValueError if any line is missing or has an invalid 'determinability' field.
    """
    from reasoning.measurement import validate_fixture_lines

    path = fixture_path if fixture_path is not None else FIXTURE_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    labelled: list[dict] = data["lines"]
    validate_fixture_lines(labelled)
    si_lines = [
        {k: line[k] for k in _LLM_INPUT_FIELDS if k in line}
        for line in labelled
    ]
    return labelled, si_lines


def _estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Rough cost in USD using RATE_PER_MTOK.  Returns 0.0 if model not in table."""
    if model_id not in RATE_PER_MTOK:
        return 0.0
    in_rate, out_rate = RATE_PER_MTOK[model_id]
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


def _fmt_metric(v: float | None, precision: int = 3) -> str:
    """Format a float metric for display; return 'N/A' when None."""
    return f"{v:.{precision}f}" if v is not None else "N/A"


def _print_table(results: list[dict]) -> None:
    """Print a fixed-width comparison table to stdout."""
    col_w = [32, 8, 8, 8, 8, 9, 9, 11, 11, 11, 8]
    header = [
        "model", "tp", "fp", "fn", "tn",
        "recall", "fp_rate", "cat_acc",
        "in_tok", "out_tok", "cost_$",
    ]
    sep = "  ".join("-" * w for w in col_w)

    def _row(vals: list) -> str:
        return "  ".join(str(v)[:w].ljust(w) for v, w in zip(vals, col_w))

    print()
    print(_row(header))
    print(sep)
    for r in results:
        model_short = r["model_id"].replace("claude-", "").replace("-20251001", "")
        gate = "PASS" if r["gate_passed"] else "FAIL"
        vals = [
            f"{model_short} [{gate}]",
            r["tp"], r["fp"], r["fn"], r["tn"],
            _fmt_metric(r["recall"]),
            _fmt_metric(r["fp_rate"]),
            _fmt_metric(r.get("category_accuracy")),
            r["input_tokens"], r["output_tokens"],
            f"${r['estimated_cost_usd']:.4f}",
        ]
        print(_row(vals))
    print()


def _print_per_line(result: dict) -> None:
    """Print per-line disposition for one model result."""
    print(f"\n  Per-line detail — {result['model_id']}")
    print(f"  {'doc':>6}  {'idx':>4}  {'disp':>5}  {'cat_ok':>6}  description")
    print(f"  {'---':>6}  {'---':>4}  {'-----':>5}  {'------':>6}  -----------")
    for ln in result["per_line"]:
        cat_ok = (
            "yes" if ln["category_correct"] is True
            else "no " if ln["category_correct"] is False
            else "n/a"
        )
        desc = ln["line_description"][:55]
        print(
            f"  {ln['doc_num']:>6}  {ln['line_index']:>4}  "
            f"{ln['disposition']:>5}  {cat_ok:>6}  {desc}"
        )


def _print_per_category_table(result: dict) -> None:
    """Print per-category breakdown for one model result.

    Determinable categories are shown with recall/fp_rate (N/A when denominator=0).
    Negatives-only categories show recall as N/A.
    A separate indeterminate surface-rate block is appended when indeterminate
    lines are present in any category.
    """
    pc = result.get("per_category")
    if not pc:
        return
    model_short = result["model_id"].replace("claude-", "").replace("-20251001", "")
    gate = "PASS" if result.get("gate_passed") else "FAIL"

    # ── Determinable table ──────────────────────────────────────────────────
    col_w = [22, 5, 5, 5, 9, 9, 5, 5]
    hdr = ["category", "tp", "fn", "fp", "recall", "fp_rate", "(+)", "(-)"]
    sep = "  ".join("-" * w for w in col_w)

    def _row(vals: list) -> str:
        return "  ".join(str(v)[:w].ljust(w) for v, w in zip(vals, col_w))

    print(f"  Per-category — {model_short} [{gate}]")
    print(f"  {_row(hdr)}")
    print(f"  {sep}")
    for cat, s in sorted(pc.items()):
        rec = _fmt_metric(s["recall"])
        fpr = _fmt_metric(s["fp_rate"])
        print(f"  {_row([cat, s['tp'], s['fn'], s['fp'], rec, fpr, s['support_positive'], s['support_negative']])}")
    print()

    # ── Indeterminate surface-rate block ────────────────────────────────────
    indet_cats = {
        cat: s for cat, s in sorted(pc.items())
        if s.get("indeterminate_support", 0) > 0
    }
    if indet_cats:
        col_w2 = [22, 14, 9]
        hdr2 = ["category", "surface_rate", "indet(n)"]
        sep2 = "  ".join("-" * w for w in col_w2)

        def _row2(vals: list) -> str:
            return "  ".join(str(v)[:w].ljust(w) for v, w in zip(vals, col_w2))

        print(f"  Indeterminate surface-rate — {model_short}")
        print(f"  {_row2(hdr2)}")
        print(f"  {sep2}")
        for cat, s in indet_cats.items():
            sr = _fmt_metric(s.get("indeterminate_surface_rate"))
            n = s.get("indeterminate_support", 0)
            print(f"  {_row2([cat, sr, n])}")
        print()


def _print_gate_reminder() -> None:
    print(textwrap.dedent("""
    ╔══════════════════════════════════════════════════════════════╗
    ║  HUMAN CHECKPOINT — Terry reviews this table                ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  Gate requirements (BOTH must be met):                      ║
    ║    recall  > 95 %   (weight recall — missing expenses > FP) ║
    ║    fp_rate <  5 %                                           ║
    ║                                                             ║
    ║  If a model clears the gate:                                ║
    ║    1. Set _PINNED_MODEL in reasoning/reg2627.py             ║
    ║    2. In the client YAML: show_ai_candidates: true          ║
    ║    3. Change validation_status to "validated" in the seal   ║
    ║                                                             ║
    ║  Do NOT call T2.7 "validated" before a model clears gate.   ║
    ╚══════════════════════════════════════════════════════════════╝
    """))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    models: list[str],
    *,
    verbose: bool = False,
    fixture_path: Path | None = None,
) -> list[dict]:
    """Execute the measurement run; return list of result dicts.

    Args:
        models:       list of Anthropic model IDs to test.
        verbose:      print per-line disposition detail for each model.
        fixture_path: path to the fixture JSON; defaults to FIXTURE_PATH when None.
    """
    from reasoning.reg2627 import build_anthropic_llm_call, run_reg2627_pass
    from reasoning.measurement import score

    active_path = fixture_path if fixture_path is not None else FIXTURE_PATH
    labelled_lines, si_lines = _load_fixture(active_path)
    n_pos = sum(1 for l in labelled_lines if l["expected_candidate"])
    n_neg = len(labelled_lines) - n_pos
    n_det = sum(1 for l in labelled_lines if l.get("determinability", "determinable") == "determinable")
    n_indet = len(labelled_lines) - n_det

    print(f"\nFixture: {active_path}")
    if active_path.resolve() != _DRAFT_FIXTURE_PATH.resolve():
        print(f"  NOTE: not the DRAFT fixture — for DRAFT measurement use "
              f"--fixture {_DRAFT_FIXTURE_PATH.relative_to(_REPO_ROOT)}")
    print(f"  Lines: {len(labelled_lines)} total  ({n_pos} positive, {n_neg} negative)")
    print(f"  Determinable: {n_det}  Indeterminate: {n_indet}")
    print(f"  Period: {_PERIOD['start']} → {_PERIOD['end']}")
    print(f"  Models: {', '.join(models)}")
    print()

    results: list[dict] = []

    for model_id in models:
        print(f"Running model: {model_id} ...", flush=True)

        llm_call = build_anthropic_llm_call(model_id)
        line_source = lambda: list(si_lines)

        artefact = run_reg2627_pass(
            _PERIOD,
            line_source=line_source,
            llm_call=llm_call,
            model_id=model_id,
        )

        if artefact["status"] != "ok":
            print(f"  ERROR: artefact status={artefact['status']!r}  "
                  f"error={artefact.get('error', '')[:120]}")
            results.append({
                "model_id": model_id,
                "status": artefact["status"],
                "error": artefact.get("error"),
                "tp": 0, "fp": 0, "fn": n_pos, "tn": n_neg,
                "recall": None, "fp_rate": None, "category_accuracy": 0.0,
                "determinable_support": n_det,
                "indeterminate": {"surface_rate": None, "support": n_indet},
                "input_tokens": artefact["token_usage"]["input_tokens"],
                "output_tokens": artefact["token_usage"]["output_tokens"],
                "estimated_cost_usd": 0.0,
                "gate_passed": False,
                "per_line": [],
                "out_of_fixture_predictions": 0,
                "per_category": {},
            })
            continue

        scored = score(artefact["candidates"], labelled_lines)
        in_tok  = artefact["token_usage"]["input_tokens"]
        out_tok = artefact["token_usage"]["output_tokens"]
        cost    = _estimate_cost(model_id, in_tok, out_tok)
        gate    = (
            scored["recall"] is not None
            and scored["fp_rate"] is not None
            and scored["recall"] > GATE_RECALL
            and scored["fp_rate"] < GATE_FP_RATE
        )

        recall_str  = _fmt_metric(scored["recall"])
        fp_rate_str = _fmt_metric(scored["fp_rate"])
        print(
            f"  recall={recall_str}  fp_rate={fp_rate_str}  "
            f"cat_acc={scored['category_accuracy']:.3f}  "
            f"det_support={scored['determinable_support']}  "
            f"indet_support={scored['indeterminate']['support']}  "
            f"tokens={in_tok}+{out_tok}  cost=${cost:.4f}  "
            f"gate={'PASS' if gate else 'FAIL'}"
        )
        if scored["out_of_fixture_predictions"]:
            print(f"  WARNING: {scored['out_of_fixture_predictions']} out-of-fixture "
                  "prediction(s) — model hallucinated doc_num/line_index")

        result = {
            "model_id": model_id,
            "status": "ok",
            "error": None,
            **{k: scored[k] for k in (
                "tp", "fp", "fn", "tn",
                "recall", "fp_rate", "category_accuracy",
                "out_of_fixture_predictions",
                "determinable_support",
                "indeterminate",
            )},
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost_usd": cost,
            "gate_passed": gate,
            "per_line": scored["per_line"],
            "per_category": scored["per_category"],
            "artefact_candidates": artefact["candidates"],
        }

        if verbose:
            _print_per_line(result)

        results.append(result)

    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m reasoning.run_measurement",
        description=(
            "Reg 26/27 multi-model recall/FP measurement harness. "
            "Calls the Anthropic API — costs tokens."
        ),
    )
    parser.add_argument(
        "--models", nargs="+", default=DEFAULT_MODELS,
        help="Model IDs to test (default: all three)",
    )
    parser.add_argument(
        "--fixture", type=Path, default=None, metavar="PATH",
        help=(
            f"Fixture JSON to score against "
            f"(default: {FIXTURE_PATH.relative_to(_REPO_ROOT)})"
        ),
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print per-line disposition detail for each model",
    )
    args = parser.parse_args(argv)

    # Load .env so ANTHROPIC_API_KEY is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    active_fixture = args.fixture if args.fixture is not None else FIXTURE_PATH

    run_at = datetime.now(timezone.utc)
    results = run(args.models, verbose=args.verbose, fixture_path=args.fixture)

    _print_table(results)
    for r in results:
        _print_per_category_table(r)
    _print_gate_reminder()

    # Write JSON record
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = run_at.strftime("%Y%m%d-%H%M%S")
    out_path = OUTPUT_DIR / f"measurement-{ts}.json"
    try:
        fixture_rel = str(active_fixture.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        fixture_rel = str(active_fixture)
    fixture_line_count = sum(
        1 for r in results if r.get("tp", 0) + r.get("fp", 0) + r.get("fn", 0) + r.get("tn", 0) > 0
    )
    record = {
        "run_at": run_at.isoformat(),
        "fixture_path": fixture_rel,
        "fixture_line_count": results[0].get("determinable_support", 0) if results else 0,
        "gate": {
            "recall_threshold": GATE_RECALL,
            "fp_rate_threshold": GATE_FP_RATE,
        },
        "results": [
            {k: v for k, v in r.items() if k != "artefact_candidates"}
            for r in results
        ],
    }
    out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Results written → {out_path}")


if __name__ == "__main__":
    main()
