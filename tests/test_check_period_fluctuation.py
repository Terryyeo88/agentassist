"""
Tests for orchestrator/check_period_fluctuation.py (T2.17).

All tests are hermetic — pure Python, no SAP calls, no anthropic import.
QuarterBoxes values are constructed as Decimal, matching the shared contract.

Coverage:
    [Q0] Empty list → empty result
    [Q1] Single quarter → empty result
    [Q2] Two identical quarters → no findings (zero movement)
    [Q3] Four identical quarters → no findings across 3 pairs

    [M1] Movement exactly at threshold → NOT flagged (strict >)
    [M2] Movement just over threshold → flagged
    [M3] Large positive movement flagged (+75%)
    [M4] Large negative movement flagged symmetrically (−75%)
    [M5] Multiple boxes in same pair both flag independently

    [Z1] from_value == 0, to_value == 0 → no finding (no movement)
    [Z2] from_value == 0, to_value != 0 → finding with pct_movement=None
    [Z3] from_value != 0, to_value == 0 → −100.0000% finding (exceeds ±50%)

    [B1] box_5 (taxable purchases) flagged symmetrically with sales boxes
    [B2] box_2 (zero-rated) and box_3 (exempt) flagged correctly

    [D1] description includes ASK §1.3a reference and "non-regulatory" marker
    [D2] undefined-movement description includes "prior-quarter value was zero"
    [D3] threshold value appears in description when non-default threshold used

    [I1] function is pure — input list not mutated
"""
from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from orchestrator.check_period_fluctuation import (
    FluctuationFinding,
    QuarterBoxes,
    detect_period_fluctuations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_THRESHOLD = Decimal("50")  # ±50% QoQ default


def _q(
    start: str,
    end: str,
    box_1: str = "10000",
    box_2: str = "0",
    box_3: str = "0",
    box_5: str = "5000",
) -> QuarterBoxes:
    return QuarterBoxes(
        period_start=start,
        period_end=end,
        box_1=Decimal(box_1),
        box_2=Decimal(box_2),
        box_3=Decimal(box_3),
        box_5=Decimal(box_5),
    )


_Q1 = _q("2024-01-01", "2024-03-31")
_Q2 = _q("2024-04-01", "2024-06-30")
_Q3 = _q("2024-07-01", "2024-09-30")
_Q4 = _q("2024-10-01", "2024-12-31")


# ---------------------------------------------------------------------------
# [Q] Quarter-count edge cases
# ---------------------------------------------------------------------------

def test_q0_empty_list():
    assert detect_period_fluctuations([], _THRESHOLD) == []


def test_q1_single_quarter():
    assert detect_period_fluctuations([_Q1], _THRESHOLD) == []


def test_q2_two_identical_quarters_no_movement():
    result = detect_period_fluctuations([_Q1, _Q2], _THRESHOLD)
    assert result == []


def test_q3_four_identical_quarters_no_movement():
    result = detect_period_fluctuations([_Q1, _Q2, _Q3, _Q4], _THRESHOLD)
    assert result == []


# ---------------------------------------------------------------------------
# [M] Movement threshold cases
# ---------------------------------------------------------------------------

def test_m1_exactly_at_threshold_no_flag():
    """from=10000, to=15000 → exactly +50.00% — NOT flagged (strict >)."""
    q_from = _q("2024-01-01", "2024-03-31", box_1="10000")
    q_to   = _q("2024-04-01", "2024-06-30", box_1="15000")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_1_findings = [f for f in result if f.box == "box_1"]
    assert box_1_findings == []


def test_m2_just_over_threshold_flags():
    """from=10000, to=15001 → +50.01% — flagged."""
    q_from = _q("2024-01-01", "2024-03-31", box_1="10000")
    q_to   = _q("2024-04-01", "2024-06-30", box_1="15001")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_1_findings = [f for f in result if f.box == "box_1"]
    assert len(box_1_findings) == 1
    f = box_1_findings[0]
    assert f.pct_movement is not None
    assert f.pct_movement > Decimal("50")


def test_m3_large_positive_movement():
    """from=10000, to=17500 → +75.0000%."""
    q_from = _q("2024-01-01", "2024-03-31", box_1="10000")
    q_to   = _q("2024-04-01", "2024-06-30", box_1="17500")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_1_findings = [f for f in result if f.box == "box_1"]
    assert len(box_1_findings) == 1
    f = box_1_findings[0]
    assert f.pct_movement == Decimal("75.0000")
    assert f.from_period_start == "2024-01-01"
    assert f.from_period_end == "2024-03-31"
    assert f.to_period_start == "2024-04-01"
    assert f.to_period_end == "2024-06-30"


def test_m4_negative_movement_flagged_symmetrically():
    """from=10000, to=2500 → −75.0000% (drop flagged same as rise)."""
    q_from = _q("2024-01-01", "2024-03-31", box_1="10000")
    q_to   = _q("2024-04-01", "2024-06-30", box_1="2500")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_1_findings = [f for f in result if f.box == "box_1"]
    assert len(box_1_findings) == 1
    assert box_1_findings[0].pct_movement == Decimal("-75.0000")


def test_m5_multiple_boxes_both_flag():
    """box_1 +100% and box_5 −90% in same pair both produce findings."""
    q_from = _q("2024-01-01", "2024-03-31", box_1="10000", box_5="5000")
    q_to   = _q("2024-04-01", "2024-06-30", box_1="20000", box_5="500")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    boxes_found = {f.box for f in result}
    assert "box_1" in boxes_found
    assert "box_5" in boxes_found


# ---------------------------------------------------------------------------
# [Z] Zero prior-value edge cases
# ---------------------------------------------------------------------------

def test_z1_both_zero_no_finding():
    """from=0, to=0 → no movement, no finding."""
    q_from = _q("2024-01-01", "2024-03-31", box_2="0")
    q_to   = _q("2024-04-01", "2024-06-30", box_2="0")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_2_findings = [f for f in result if f.box == "box_2"]
    assert box_2_findings == []


def test_z2_from_zero_to_nonzero_undefined_pct():
    """from=0, to=5000 → finding with pct_movement=None; no ZeroDivisionError."""
    q_from = _q("2024-01-01", "2024-03-31", box_2="0")
    q_to   = _q("2024-04-01", "2024-06-30", box_2="5000")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_2_findings = [f for f in result if f.box == "box_2"]
    assert len(box_2_findings) == 1
    f = box_2_findings[0]
    assert f.pct_movement is None
    assert "prior-quarter value was zero" in f.description


def test_z3_to_zero_gives_minus_100():
    """from=10000, to=0 → pct_movement == −100.0000%, exceeds ±50% threshold."""
    q_from = _q("2024-01-01", "2024-03-31", box_1="10000")
    q_to   = _q("2024-04-01", "2024-06-30", box_1="0")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_1_findings = [f for f in result if f.box == "box_1"]
    assert len(box_1_findings) == 1
    assert box_1_findings[0].pct_movement == Decimal("-100.0000")


# ---------------------------------------------------------------------------
# [B] Box-specific coverage
# ---------------------------------------------------------------------------

def test_b1_box5_purchases_flagged():
    """box_5 (taxable purchases) is checked and can flag (+80%)."""
    q_from = _q("2024-01-01", "2024-03-31", box_5="10000")
    q_to   = _q("2024-04-01", "2024-06-30", box_5="18000")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_5_findings = [f for f in result if f.box == "box_5"]
    assert len(box_5_findings) == 1
    assert box_5_findings[0].pct_movement == Decimal("80.0000")


def test_b2_box2_box3_flagged():
    """box_2 (+100%) and box_3 (+120%) are each detected independently."""
    q_from = _q("2024-01-01", "2024-03-31", box_2="1000", box_3="500")
    q_to   = _q("2024-04-01", "2024-06-30", box_2="2000", box_3="1100")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    boxes_found = {f.box for f in result}
    assert "box_2" in boxes_found
    assert "box_3" in boxes_found


# ---------------------------------------------------------------------------
# [D] Description content
# ---------------------------------------------------------------------------

def test_d1_description_contains_ask_reference():
    """Description includes 'ASK §1.3a' and marks threshold as 'non-regulatory'."""
    q_from = _q("2024-01-01", "2024-03-31", box_1="10000")
    q_to   = _q("2024-04-01", "2024-06-30", box_1="20000")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_1_findings = [f for f in result if f.box == "box_1"]
    assert len(box_1_findings) == 1
    desc = box_1_findings[0].description
    assert "ASK §1.3a" in desc
    assert "non-regulatory" in desc


def test_d2_undefined_description_content():
    """Undefined-movement description contains the right sentinel phrases."""
    q_from = _q("2024-01-01", "2024-03-31", box_3="0")
    q_to   = _q("2024-04-01", "2024-06-30", box_3="3000")
    result = detect_period_fluctuations([q_from, q_to], _THRESHOLD)
    box_3_findings = [f for f in result if f.box == "box_3"]
    assert len(box_3_findings) == 1
    desc = box_3_findings[0].description
    assert "prior-quarter value was zero" in desc
    assert "movement undefined" in desc
    assert "ASK §1.3a" in desc


def test_d3_custom_threshold_appears_in_description():
    """Non-default threshold value is reflected in the description string."""
    custom_threshold = Decimal("30")
    q_from = _q("2024-01-01", "2024-03-31", box_1="10000")
    q_to   = _q("2024-04-01", "2024-06-30", box_1="15000")  # +50%, exceeds 30%
    result = detect_period_fluctuations([q_from, q_to], custom_threshold)
    box_1_findings = [f for f in result if f.box == "box_1"]
    assert len(box_1_findings) == 1
    assert "30" in box_1_findings[0].description


# ---------------------------------------------------------------------------
# [I] Immutability guard
# ---------------------------------------------------------------------------

def test_i1_input_not_mutated():
    """The input list and its QuarterBoxes dicts are not modified."""
    q_from = _q("2024-01-01", "2024-03-31", box_1="10000")
    q_to   = _q("2024-04-01", "2024-06-30", box_1="20000")
    original = [copy.deepcopy(q_from), copy.deepcopy(q_to)]
    quarters = [q_from, q_to]
    detect_period_fluctuations(quarters, _THRESHOLD)
    assert quarters[0] == original[0]
    assert quarters[1] == original[1]
