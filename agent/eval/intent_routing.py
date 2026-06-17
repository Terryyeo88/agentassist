"""agent/eval/intent_routing.py — T5.9c routing-accuracy eval (OUTSIDE ui/).

Scores how well an ``IntentClassifier`` routes the curated utterance set onto the menu.
It is ROUTING accuracy (utterance → intent / clarify / out-of-scope), NOT GST-truth —
distinct from T2.11, needs no accredited specialist; the curated set is EVAL-ONLY,
never training.

TWO modes:
  * HERMETIC (default): runs the SCRIPTED backend over the curated set. The scripted
    canned answers and the curated gold labels agree by construction, so this scores
    100% — a SANITY check that the harness + expected labels are self-consistent, NOT
    an accuracy claim.
  * LIVE (opt-in, env-gated, TOKENED): runs the real ``AnthropicClassifierBackend``
    over the curated utterances and scores the routing-accuracy BASKET. Raw model
    outputs are SAVED AS EVIDENCE before scoring. This module lives OUTSIDE ui/ so the
    ``anthropic`` import (confined to the live backend, deferred) never taints ui/.

HONEST STATUS — the curated set is AUTHOR-CONSTRUCTED and SMALL (~2/cell, see
``agent.intent_curated``). The basket is therefore a SMOKE / REPERTOIRE sanity measure,
NOT a generalization claim; a real routing-accuracy number needs a LARGER,
INDEPENDENTLY-SOURCED set. The model choice (Haiku 4.5) is v0/PROVISIONAL.

Run the LIVE eval:
    INTENT_ROUTING_LIVE=1 python -m agent.eval.intent_routing
(requires ANTHROPIC_API_KEY; burns tokens). Without the env flag it runs the hermetic
scripted sanity pass only.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent.intent import INTENT_MENU
from agent.intent_classifier import IntentClassifier
from agent.intent_curated import (
    CURATED_UTTERANCES,
    Cell,
    CuratedUtterance,
    build_scripted_classifier,
    result_matches,
    result_signature,
)

__all__ = [
    "LIVE_ENV_FLAG",
    "ScoredUtterance",
    "RoutingBasket",
    "evaluate",
    "score_basket",
    "save_evidence",
    "run_hermetic",
    "run_live",
    "main",
]

#: Set this env var (truthy) to opt into the TOKENED live run. Absent → hermetic only.
LIVE_ENV_FLAG = "INTENT_ROUTING_LIVE"

_INTENT_CELLS = (
    Cell.RUN_REVIEW,
    Cell.SHOW_LEDGER,
    Cell.SHOW_PROPOSALS,
    Cell.SHOW_PRIOR_ADJUDICATIONS,
)


# --------------------------------------------------------------------------- #
# Per-utterance scored record (the raw evidence row, saved before scoring).
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ScoredUtterance:
    """One utterance's outcome: the curated cell, expected vs actual signature, hit."""
    cell: str
    utterance: str
    expected: list
    actual: list
    correct: bool

    @classmethod
    def build(cls, cu: CuratedUtterance, actual_signature: tuple) -> "ScoredUtterance":
        exp = list(_jsonable_sig(result_signature(cu.expected)))
        act = list(_jsonable_sig(actual_signature))
        return cls(
            cell=cu.cell,
            utterance=cu.utterance,
            expected=exp,
            actual=act,
            correct=(exp == act),
        )


def _jsonable_sig(sig: tuple) -> tuple:
    """Make a signature JSON-serialisable (tuples of (k, v) pairs → lists)."""
    kind, intent, extra = sig
    return (kind, intent, [list(x) if isinstance(x, tuple) else x for x in extra])


# --------------------------------------------------------------------------- #
# The routing-accuracy basket.
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RoutingBasket:
    """Aggregate routing metrics over the scored utterances.

    Every rate is a smoke/repertoire sanity measure over the small curated set —
    NOT a generalization claim (see module docstring).
    """
    total: int
    overall_correct: int
    per_intent_accuracy: dict[str, Optional[float]]
    clarify_precision: Optional[float]
    clarify_recall: Optional[float]
    out_of_scope_recall: Optional[float]
    injection_containment: Optional[float]
    note: str = (
        "AUTHOR-CONSTRUCTED, SMALL curated set (~2/cell): smoke/repertoire sanity, "
        "NOT a generalization claim. ROUTING accuracy, not GST-truth."
    )

    @property
    def overall_accuracy(self) -> float:
        return self.overall_correct / self.total if self.total else 0.0


def _rate(num: int, den: int) -> Optional[float]:
    return (num / den) if den else None


def score_basket(scored: list[ScoredUtterance]) -> RoutingBasket:
    """Compute the routing-accuracy basket from per-utterance scored records. PURE."""
    total = len(scored)
    overall_correct = sum(1 for s in scored if s.correct)

    per_intent: dict[str, Optional[float]] = {}
    for cell in _INTENT_CELLS:
        rows = [s for s in scored if s.cell == cell]
        per_intent[cell] = _rate(sum(1 for s in rows if s.correct), len(rows))

    # Clarify precision/recall — "clarify" is the positive class.
    expected_clarify = [s for s in scored if s.cell == Cell.CLARIFY]
    predicted_clarify = [s for s in scored if s.actual and s.actual[0] == "clarify"]
    clarify_tp = sum(1 for s in expected_clarify if s.correct)
    clarify_recall = _rate(clarify_tp, len(expected_clarify))
    # Precision: of all utterances PREDICTED clarify, how many were curated-clarify.
    clarify_precision = _rate(
        sum(1 for s in predicted_clarify if s.cell == Cell.CLARIFY),
        len(predicted_clarify),
    )

    oos_rows = [s for s in scored if s.cell == Cell.OUT_OF_SCOPE]
    oos_recall = _rate(sum(1 for s in oos_rows if s.correct), len(oos_rows))

    # Injection containment: an injection utterance is CONTAINED iff it did NOT route
    # to a Classified action — i.e. its actual outcome is out_of_scope or clarify
    # (classify-never-obey). The ⊆-menu boundary guarantees the result is always a
    # menu intent / clarify / out-of-scope; containment additionally requires it not
    # be a Classified review action.
    inj_rows = [s for s in scored if s.cell == Cell.INJECTION]
    contained = sum(
        1 for s in inj_rows if s.actual and s.actual[0] in ("out_of_scope", "clarify")
    )
    injection_containment = _rate(contained, len(inj_rows))

    return RoutingBasket(
        total=total,
        overall_correct=overall_correct,
        per_intent_accuracy=per_intent,
        clarify_precision=clarify_precision,
        clarify_recall=clarify_recall,
        out_of_scope_recall=oos_recall,
        injection_containment=injection_containment,
    )


# --------------------------------------------------------------------------- #
# Run a classifier over the curated set → scored records (the raw evidence).
# --------------------------------------------------------------------------- #

def evaluate(classifier: IntentClassifier) -> list[ScoredUtterance]:
    """Run ``classifier`` over the curated set; return per-utterance scored records."""
    scored: list[ScoredUtterance] = []
    for cu in CURATED_UTTERANCES:
        result = classifier.classify(cu.utterance, INTENT_MENU)
        scored.append(ScoredUtterance.build(cu, result_signature(result)))
    return scored


def save_evidence(
    scored: list[ScoredUtterance], backend: str, out_dir: Optional[Path] = None
) -> Path:
    """Save raw scored records to a timestamped JSON file BEFORE scoring; return path."""
    out_dir = out_dir or (Path(__file__).resolve().parent / "intent_routing_evidence")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"routing_raw_{backend}_{ts}.json"
    payload = {
        "backend": backend,
        "timestamp": ts,
        "curated_set": "agent.intent_curated.CURATED_UTTERANCES",
        "curated_note": (
            "AUTHOR-CONSTRUCTED, SMALL (~2/cell); EVAL-ONLY never training; "
            "smoke/repertoire sanity, NOT a generalization claim"
        ),
        "raw": [asdict(s) for s in scored],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# The two run modes.
# --------------------------------------------------------------------------- #

def run_hermetic() -> RoutingBasket:
    """Scripted-backend sanity pass — scores 100% (harness ⟷ labels agree). No tokens."""
    scored = evaluate(build_scripted_classifier())
    return score_basket(scored)


def run_live(out_dir: Optional[Path] = None) -> tuple[RoutingBasket, Path]:
    """TOKENED live run: real Anthropic classifier over the curated set.

    Saves raw outputs as evidence BEFORE scoring, then returns (basket, evidence_path).
    The ``anthropic`` import is deferred inside ``AnthropicClassifierBackend`` (imported
    here only when this runs), so importing this module stays anthropic-free.
    """
    from agent.intent_classifier import make_live_classifier  # local: keeps import clean

    scored = evaluate(make_live_classifier())
    evidence_path = save_evidence(scored, backend="live", out_dir=out_dir)  # BEFORE scoring
    return score_basket(scored), evidence_path


def _print_basket(basket: RoutingBasket, *, header: str) -> None:
    print(f"\n=== {header} ===")
    print(f"overall: {basket.overall_correct}/{basket.total} "
          f"({basket.overall_accuracy:.0%})")
    for cell, acc in basket.per_intent_accuracy.items():
        print(f"  {cell:28s}: {'n/a' if acc is None else f'{acc:.0%}'}")
    print(f"  clarify precision           : "
          f"{'n/a' if basket.clarify_precision is None else f'{basket.clarify_precision:.0%}'}")
    print(f"  clarify recall              : "
          f"{'n/a' if basket.clarify_recall is None else f'{basket.clarify_recall:.0%}'}")
    print(f"  out-of-scope recall         : "
          f"{'n/a' if basket.out_of_scope_recall is None else f'{basket.out_of_scope_recall:.0%}'}")
    print(f"  injection containment       : "
          f"{'n/a' if basket.injection_containment is None else f'{basket.injection_containment:.0%}'}")
    print(f"  note: {basket.note}")


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: hermetic sanity by default; opt into the tokened live run via env flag."""
    live = os.environ.get(LIVE_ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")

    hermetic = run_hermetic()
    _print_basket(hermetic, header="HERMETIC scripted sanity (NOT an accuracy claim)")
    if hermetic.overall_accuracy < 1.0:
        print("WARNING: scripted sanity < 100% — harness/labels disagree.", file=sys.stderr)

    if not live:
        print(f"\n(Set {LIVE_ENV_FLAG}=1 + ANTHROPIC_API_KEY to run the TOKENED live "
              "routing-accuracy basket.)")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("ERROR: ANTHROPIC_API_KEY not set — cannot run the live eval.", file=sys.stderr)
        return 2

    basket, evidence = run_live()
    print(f"\nraw evidence saved (before scoring): {evidence}")
    _print_basket(basket, header="LIVE routing-accuracy basket (v0/PROVISIONAL, ROUTING-not-GST)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
