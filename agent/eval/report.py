"""
agent/eval/report.py — Scorecard report for the agent-behaviour eval basket.

report_eval(records)   — compute the cage-invariant basket over RunRecords →
                         EvalReport (loop metrics empty; pure over records).
run_basket()           — run the adversarial library AND the golden loop basket
                         end-to-end → EvalReport carrying all SIX metrics.
format_scorecard(rep)  — render a human-readable scorecard: the 4 cage-invariant
                         metrics + the 2 loop-quality metrics (T5.7b) + per-scenario
                         detail. When the loop basket has not been run (report_eval),
                         the loop rows fall back to DEFERRED placeholders.

Zero SDK import (the runner uses the SDK lazily; the loop runner uses no SDK at all).
Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from agent.eval.loop_runner import LoopRunRecord, run_loop_scenario
from agent.eval.loop_scenarios import build_loop_basket
from agent.eval.metrics import MetricResult, compute_basket_metrics, compute_loop_metrics
from agent.eval.runner import RunRecord, run_scenario
from agent.eval.scenarios import build_adversarial_basket

#: Loop-quality metric names + descriptions, used to render DEFERRED placeholder
#: rows when a report has no loop metrics (e.g. report_eval over records only).
_LOOP_ROWS = (
    ("dossier_completeness_rate", "fraction of findings with a complete evidence dossier"),
    ("language_lint_pass_rate", "fraction of candidate framing passing the assertive-language lint"),
)


@dataclass
class EvalReport:
    """A computed eval report: the metric baskets + the runs they were scored over.

    Attributes:
        metrics:      The 4 cage-invariant metrics (over the adversarial RunRecords).
        records:      The cage-invariant RunRecords.
        loop_metrics: The 2 loop-quality metrics (T5.7b), empty when only the cage
                      basket was scored (report_eval).
        loop_records: The LoopRunRecords the loop metrics were scored over.
    """
    metrics: list[MetricResult] = field(default_factory=list)
    records: list[RunRecord] = field(default_factory=list)
    loop_metrics: list[MetricResult] = field(default_factory=list)
    loop_records: list[LoopRunRecord] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        """True iff every metric in BOTH baskets meets its target."""
        return all(m.passed for m in self.metrics) and all(m.passed for m in self.loop_metrics)


def report_eval(records: Sequence[RunRecord]) -> EvalReport:
    """Compute the cage-invariant basket over *records* and return an EvalReport.

    Pure over the records: only the 4 cage-invariant metrics are computed (the
    loop-quality metrics require driving the loop, so loop_metrics stays empty).
    """
    return EvalReport(metrics=compute_basket_metrics(records), records=list(records))


def run_basket() -> EvalReport:
    """Run the adversarial cage basket AND the golden loop basket, and score both.

    The cage-invariant metrics are scored over the adversarial RunRecords; the
    loop-quality metrics are scored over the FindingOutcomes the real Slice-2 loop
    produced on the golden loop scenarios. Returns an EvalReport carrying all six.
    """
    records = [run_scenario(s) for s in build_adversarial_basket()]
    loop_records = [run_loop_scenario(s) for s in build_loop_basket()]
    outcomes = [o for lr in loop_records for o in lr.outcomes]
    return EvalReport(
        metrics=compute_basket_metrics(records),
        records=list(records),
        loop_metrics=compute_loop_metrics(outcomes),
        loop_records=loop_records,
    )


def _status(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _render_metric(lines: list[str], m: MetricResult) -> None:
    lines.append(f"  [{_status(m.passed)}] {m.name}")
    lines.append(f"         value={m.value}   target: {m.target}")
    lines.append(f"         {m.detail}")


def format_scorecard(report: EvalReport) -> str:
    """Render *report* as a plain-text scorecard.

    Sections:
        1. Cage-invariant metric basket — one row per metric (PASS/FAIL + value).
        2. Loop-quality metric basket (T5.7b) — dossier completeness + language-lint
           (filled when the loop basket was run; DEFERRED placeholders otherwise).
        3. Per-scenario detail — cage attempts/executions + loop outcomes.
    """
    all_metrics = list(report.metrics) + list(report.loop_metrics)
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("T5.7 — Agent-behaviour eval scorecard")
    lines.append("=" * 72)

    overall = "PASS" if report.all_passed else "FAIL"
    lines.append(f"OVERALL: {overall}   "
                 f"({sum(m.passed for m in all_metrics)}/{len(all_metrics)} metrics passed, "
                 f"{len(report.records)} cage scenarios, {len(report.loop_records)} loop scenarios)")
    lines.append("")

    # 1. Cage-invariant metrics
    lines.append("Cage-invariant metric basket")
    lines.append("-" * 72)
    for m in report.metrics:
        _render_metric(lines, m)
    lines.append("")

    # 2. Loop-quality metrics (T5.7b)
    lines.append("Loop-quality metric basket (T5.7b — Slice-2 gather->act->verify loop)")
    lines.append("-" * 72)
    if report.loop_metrics:
        for m in report.loop_metrics:
            _render_metric(lines, m)
    else:
        for name, desc in _LOOP_ROWS:
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
    for lr in report.loop_records:
        lines.append(f"  loop scenario: {lr.scenario_name}   "
                     f"(review_status={lr.result.review_status})")
        for o in lr.outcomes:
            satisfied = o.dossier.completeness.get("satisfied") if o.dossier else None
            lines.append(f"      finding {o.finding_id!r} ({o.check_id}): "
                         f"{o.status} (completeness_satisfied={satisfied})")
    lines.append("=" * 72)
    return "\n".join(lines)
