"""
agent/eval/ — T5.7a agent-behaviour eval harness (TEST/MEASUREMENT infrastructure).

This subpackage is the agent layer's analogue of the reasoning layer's
measurement.py: it MEASURES the cage, it is NOT a production agent workflow. It is
fully hermetic — a FakeTransport replays a scripted agent stream and the runner
drives the REAL PreToolUse/PostToolUse hooks + registry + justification gate +
executor. No live model, no SAP, no tokens, no binary spawn.

Public API:
    FakeTransport, scenario_to_stream              (transport)
    Attempt, Tier2Execution, Scenario,
        load_scenario, load_scenarios_from_json     (scenario)
    run_scenario, RunRecord, AttemptResult,
        ExecutionRecord                             (runner)
    MetricResult, compute_basket_metrics, ...       (metrics)
    build_adversarial_basket                        (scenarios)
    run_basket, report_eval, format_scorecard,
        EvalReport                                  (report)

SCOPE (T5.7a): the cage-invariant metric basket only — justification-gate hold
rate, zero Tier-2 self-execution, Tier-3 denial, sealed-chain routing integrity.
Loop-quality metrics (dossier completeness, language-lint) are DEFERRED to T5.7b
(they need the Slice-2 gather→act→verify loop).
"""
from __future__ import annotations

from agent.eval.scenario import (
    Attempt,
    Scenario,
    Tier2Execution,
    load_scenario,
    load_scenarios_from_json,
)
from agent.eval.transport import FakeTransport, scenario_to_stream
from agent.eval.runner import (
    AttemptResult,
    ExecutionRecord,
    RunRecord,
    run_scenario,
)
from agent.eval.metrics import (
    MetricResult,
    compute_basket_metrics,
    justification_gate_hold_rate,
    sealed_chain_routing_integrity,
    tier2_self_execution_count,
    tier3_denial_correct,
)
from agent.eval.scenarios import build_adversarial_basket
from agent.eval.report import EvalReport, format_scorecard, report_eval, run_basket

__all__ = [
    "Attempt",
    "Scenario",
    "Tier2Execution",
    "load_scenario",
    "load_scenarios_from_json",
    "FakeTransport",
    "scenario_to_stream",
    "AttemptResult",
    "ExecutionRecord",
    "RunRecord",
    "run_scenario",
    "MetricResult",
    "compute_basket_metrics",
    "justification_gate_hold_rate",
    "sealed_chain_routing_integrity",
    "tier2_self_execution_count",
    "tier3_denial_correct",
    "build_adversarial_basket",
    "EvalReport",
    "format_scorecard",
    "report_eval",
    "run_basket",
]
