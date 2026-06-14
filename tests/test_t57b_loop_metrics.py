"""
tests/test_t57b_loop_metrics.py — T5.7b: the two LOOP-QUALITY metrics.

These metrics are measured by DRIVING the real Slice-2 case-file loop
(agent.loop.run_casefile_loop) over a scripted, hermetic transport and then scoring
the dossiers/framing it produced:

  * dossier_completeness_rate — fraction of findings whose dossier reached the
    CODE-DEFINED completeness (satisfied=True). Golden path → 1.0; a deliberately
    incomplete path is meaningfully < 1.0.
  * language_lint_pass_rate   — fraction of produced candidate_framing_text that
    passes agent.lint.lint_framing. Clean framing → 1.0; an assertive-framing path
    the lint catches is < 1.0.

Hermetic: ScriptedLoopTransport (no SDK, no binary), in-memory fakes, no tokens.
"""
from __future__ import annotations

import subprocess

from agent.eval.loop_runner import run_loop_scenario
from agent.eval.loop_scenarios import (
    assertive_framing_loop_scenario,
    build_loop_basket,
    golden_loop_scenario,
    incomplete_loop_scenario,
)
from agent.eval.metrics import (
    MetricResult,
    compute_loop_metrics,
    dossier_completeness_rate,
    language_lint_pass_rate,
)


def _outcomes(scenario):
    return run_loop_scenario(scenario).outcomes


# ---------------------------------------------------------------------------
# Loop runner drives the real loop hermetically
# ---------------------------------------------------------------------------

def test_golden_loop_stages_every_finding():
    rec = run_loop_scenario(golden_loop_scenario())
    assert rec.result.review_status == "completed"
    assert len(rec.outcomes) >= 2
    assert {o.status for o in rec.outcomes} == {"staged"}


def test_loop_runner_spawns_no_subprocess(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - fires only on a containment breach
        raise AssertionError("loop eval attempted to spawn a subprocess")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    rec = run_loop_scenario(golden_loop_scenario())
    assert rec.result.agent_layer_complete is True


# ---------------------------------------------------------------------------
# dossier_completeness_rate
# ---------------------------------------------------------------------------

def test_completeness_rate_golden_is_one():
    m = dossier_completeness_rate(_outcomes(golden_loop_scenario()))
    assert isinstance(m, MetricResult)
    assert m.name == "dossier_completeness_rate"
    assert m.value == 1.0
    assert m.passed is True


def test_completeness_rate_incomplete_below_one():
    m = dossier_completeness_rate(_outcomes(incomplete_loop_scenario()))
    assert 0.0 <= m.value < 1.0
    assert m.passed is False
    # the incomplete finding's dossier is present but not satisfied
    assert "incomplete" in m.detail.lower() or "/" in m.detail


# ---------------------------------------------------------------------------
# language_lint_pass_rate
# ---------------------------------------------------------------------------

def test_lint_rate_golden_is_one():
    m = language_lint_pass_rate(_outcomes(golden_loop_scenario()))
    assert m.name == "language_lint_pass_rate"
    assert m.value == 1.0
    assert m.passed is True


def test_lint_rate_assertive_below_one():
    m = language_lint_pass_rate(_outcomes(assertive_framing_loop_scenario()))
    assert 0.0 <= m.value < 1.0
    assert m.passed is False


def test_assertive_path_completeness_isolated_to_lint():
    # The assertive path GATHERS evidence (so completeness is satisfied) but voices
    # an assertive verdict — only the lint metric should drop, not completeness.
    outcomes = _outcomes(assertive_framing_loop_scenario())
    comp = dossier_completeness_rate(outcomes)
    lint = language_lint_pass_rate(outcomes)
    assert comp.value == 1.0
    assert lint.value < 1.0


# ---------------------------------------------------------------------------
# compute_loop_metrics + basket
# ---------------------------------------------------------------------------

def test_compute_loop_metrics_returns_the_two_named_metrics():
    metrics = compute_loop_metrics(_outcomes(golden_loop_scenario()))
    names = {m.name for m in metrics}
    assert names == {"dossier_completeness_rate", "language_lint_pass_rate"}


def test_build_loop_basket_is_golden_and_passes():
    basket = build_loop_basket()
    assert len(basket) >= 1
    outcomes = [o for s in basket for o in run_loop_scenario(s).outcomes]
    metrics = compute_loop_metrics(outcomes)
    assert all(m.passed for m in metrics)
