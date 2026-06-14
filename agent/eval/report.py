"""
agent/eval/report.py — Scorecard report for the cage-invariant eval basket.

report_eval(records)   — compute the basket metrics over RunRecords → EvalReport.
run_basket()           — run the adversarial library end-to-end → EvalReport.
format_scorecard(rep)  — render a human-readable scorecard (pass/fail per metric
                         + per-scenario detail), with DEFERRED rows reserved for
                         T5.7b (dossier completeness, language-lint) so the table
                         structure is ready once the Slice-2 loop lands.

Zero SDK import (the runner uses the SDK lazily). Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from agent.eval.metrics import MetricResult, compute_basket_metrics
from agent.eval.runner import RunRecord, run_scenario
from agent.eval.scenarios import build_adversarial_basket

#: Loop-quality metrics deferred to T5.7b — they need the Slice-2 gather→act→verify
#: loop. Listed here so the scorecard reserves their rows.
_DEFERRED_T57B = (
    ("dossier_completeness", "fraction of findings with a complete evidence dossier"),
    ("language_lint", "fraction of report language passing the assertive-language lint"),
)


@dataclass
class EvalReport:
    """A computed eval report: the metric basket + the runs it was scored over."""
    metrics: list[MetricResult] = field(default_factory=list)
    records: list[RunRecord] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        """True iff every cage-invariant metric meets its target."""
        return all(m.passed for m in self.metrics)


def report_eval(records: Sequence[RunRecord]) -> EvalReport:
    """Compute the cage-invariant basket over *records* and return an EvalReport."""
    return EvalReport(metrics=compute_basket_metrics(records), records=list(records))


def run_basket() -> EvalReport:
    """Run the adversarial scenario library through the real cage and score it."""
    records = [run_scenario(s) for s in build_adversarial_basket()]
    return report_eval(records)


def _status(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def format_scorecard(report: EvalReport) -> str:
    """Render *report* as a plain-text scorecard.

    Sections:
        1. Cage-invariant metric basket — one row per metric (PASS/FAIL + value).
        2. Deferred (T5.7b) — placeholder rows for the loop-quality metrics.
        3. Per-scenario detail — attempts (tier/decision) + executions per run.
    """
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("T5.7a — Agent cage-invariant eval scorecard")
    lines.append("=" * 72)

    overall = "PASS" if report.all_passed else "FAIL"
    lines.append(f"OVERALL: {overall}   "
                 f"({sum(m.passed for m in report.metrics)}/{len(report.metrics)} metrics passed, "
                 f"{len(report.records)} scenarios)")
    lines.append("")

    # 1. Cage-invariant metrics
    lines.append("Cage-invariant metric basket")
    lines.append("-" * 72)
    for m in report.metrics:
        lines.append(f"  [{_status(m.passed)}] {m.name}")
        lines.append(f"         value={m.value}   target: {m.target}")
        lines.append(f"         {m.detail}")
    lines.append("")

    # 2. Deferred rows (T5.7b)
    lines.append("Deferred — T5.7b (needs the Slice-2 gather->act->verify loop)")
    lines.append("-" * 72)
    for name, desc in _DEFERRED_T57B:
        lines.append(f"  [DEFERRED:T5.7b] {name}")
        lines.append(f"         {desc}")
    lines.append("")

    # 3. Per-scenario detail
    lines.append("Per-scenario detail")
    lines.append("-" * 72)
    for rec in report.records:
        lines.append(f"  scenario: {rec.scenario_name}   "
                     f"(spawned_binary={rec.transport_spawned_binary})")
        for ar in rec.attempts:
            decision = ar.decision.upper()
            reason = f" — {ar.reason}" if ar.reason else ""
            lines.append(f"      attempt tier{ar.tier} {ar.tool_name!r}: "
                         f"{decision}{reason}")
        for ex in rec.executions:
            lines.append(f"      execution {ex.action!r}: "
                         f"{'OK' if ex.success else 'FAIL'}"
                         f"{(' — ' + ex.error) if ex.error else ''}")
    lines.append("=" * 72)
    return "\n".join(lines)
