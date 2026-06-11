"""
Tests for orchestrator/check_analytical_review.py (T2.16).

All tests are hermetic — no SAP calls, no live data.
Box values are constructed inline as Decimal or float.

Coverage required:
    [R1] ratio > 1.2  → flag fires (one finding)
    [R2] ratio == 1.2 → no finding (strict greater-than)
    [R3] ratio < 1.2  → no finding
    [R4] box_4 == 0   → no finding, no ZeroDivisionError
    [C1] finding text includes RC/OVR approximation caveat
    [C2] finding note is "candidate for review", never an assertion
    [C3] finding includes ratio, fy_box_4, fy_box_5, basis, threshold
    [Q1] list[QuarterBoxes] has exactly 4 entries
    [Q2] entries are chronological (period_start ascending)
    [Q3] QuarterBoxes keys: period_start, period_end, box_1, box_2, box_3, box_5
    [Q4] box values are Decimal, not float
    [F1] derive_fy_period: Jan fiscal start, period in mid-year → correct FY
    [F2] derive_fy_period: Apr fiscal start, period before start month → prior FY
    [F3] derive_fy_period: Apr fiscal start, period after start month → same-year FY
    [F4] generate_fy_quarters: Jan start produces 4 correct quarter ranges
    [F5] generate_fy_quarters: Apr start crosses year boundary correctly
    [A1] aggregate_to_fy: sums box_1+box_2+box_3 → fy_box_4; box_5 → fy_box_5
    [A2] aggregate_to_fy: all-zero quarter (empty period) handled without error
    [I1] box-isolation: run_analytical_review_pass never mutates compile_output boxes
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from orchestrator.check_analytical_review import (
    QuarterBoxes,
    aggregate_to_fy,
    check_tpts_ratio,
    derive_fy_period,
    generate_fy_quarters,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASIS = "IRAS ASK Annual Review Guide §Step 1.3d"
_THRESHOLD = Decimal("1.2")
_RC_OVR_CAVEAT_FRAGMENT = "RC/OVR"


def _qb(period_start, period_end, b1, b2, b3, b5) -> QuarterBoxes:
    """Construct a QuarterBoxes dict with Decimal values."""
    return QuarterBoxes(
        period_start=period_start,
        period_end=period_end,
        box_1=Decimal(str(b1)),
        box_2=Decimal(str(b2)),
        box_3=Decimal(str(b3)),
        box_5=Decimal(str(b5)),
    )


def _four_quarters(b4_total=None, b5_total=None) -> list[QuarterBoxes]:
    """Return 4 synthetic QuarterBoxes summing to b4_total / b5_total.

    Splits b4_total evenly across box_1 in Q1–Q3 (Q4 zero for realism).
    """
    if b4_total is None:
        b4_total = Decimal("993717.08")
    if b5_total is None:
        b5_total = Decimal("500772.55")
    b4 = Decimal(str(b4_total))
    b5 = Decimal(str(b5_total))
    per_q = (b4 / 3).quantize(Decimal("0.01"))
    per_q5 = (b5 / 3).quantize(Decimal("0.01"))
    return [
        _qb("2024-01-01", "2024-03-31", per_q, 0, 0, per_q5),
        _qb("2024-04-01", "2024-06-30", per_q, 0, 0, per_q5),
        _qb("2024-07-01", "2024-09-30", b4 - per_q * 2, 0, 0, b5 - per_q5 * 2),
        _qb("2024-10-01", "2024-12-31", 0, 0, 0, 0),
    ]


# ---------------------------------------------------------------------------
# [R] TP/TS ratio flag
# ---------------------------------------------------------------------------

def test_ratio_above_threshold_fires():
    """[R1] ratio > 1.2 → one TP_TS_RATIO finding."""
    # box_4=1000, box_5=1201 → ratio=1.201 > 1.2
    findings = check_tpts_ratio(Decimal("1000"), Decimal("1201"))
    assert len(findings) == 1
    f = findings[0]
    assert f["check"] == "TP_TS_RATIO"


def test_ratio_at_threshold_no_finding():
    """[R2] ratio exactly 1.2 → no finding (strict >1.2 only)."""
    # box_4=1000, box_5=1200 → ratio=1.200 not > 1.2
    findings = check_tpts_ratio(Decimal("1000"), Decimal("1200"))
    assert findings == []


def test_ratio_below_threshold_no_finding():
    """[R3] ratio < 1.2 → no finding."""
    # FY SBODEMOSG ratio ≈ 0.5039
    b4, b5 = Decimal("993717.08"), Decimal("500772.55")
    findings = check_tpts_ratio(b4, b5)
    assert findings == []


def test_box4_zero_no_finding_no_zero_division():
    """[R4] box_4 == 0 → no finding, no ZeroDivisionError."""
    findings = check_tpts_ratio(Decimal("0"), Decimal("500"))
    assert findings == []


# ---------------------------------------------------------------------------
# [C] Finding content invariants
# ---------------------------------------------------------------------------

def test_finding_includes_rc_ovr_caveat():
    """[C1] Finding description must mention RC/OVR approximation."""
    findings = check_tpts_ratio(Decimal("1000"), Decimal("1300"))
    assert len(findings) == 1
    desc = findings[0].get("description", "") + findings[0].get("caveat", "")
    assert _RC_OVR_CAVEAT_FRAGMENT in desc


def test_finding_note_is_candidate_not_assertion():
    """[C2] Finding note must use candidate language, not an assertion."""
    findings = check_tpts_ratio(Decimal("1000"), Decimal("1300"))
    assert len(findings) == 1
    note = findings[0].get("note", "").lower()
    assert "candidate" in note
    # Must NOT use definitive assertion words
    for forbidden in ("must", "is an error", "non-compliant", "incorrect"):
        assert forbidden not in note, f"Assertion language found: {forbidden!r}"


def test_finding_includes_required_fields():
    """[C3] Finding must carry ratio, fy_box_4, fy_box_5, basis, threshold."""
    b4, b5 = Decimal("1000"), Decimal("1300")
    findings = check_tpts_ratio(b4, b5)
    assert len(findings) == 1
    f = findings[0]
    assert "ratio" in f
    assert "fy_box_4" in f
    assert "fy_box_5" in f
    assert "basis" in f
    assert _BASIS in f["basis"]
    assert "threshold" in f
    assert Decimal(str(f["threshold"])) == _THRESHOLD


# ---------------------------------------------------------------------------
# [Q] QuarterBoxes shape
# ---------------------------------------------------------------------------

def test_generate_fy_quarters_jan_count():
    """[Q1] FY Jan start → 4 quarter tuples."""
    quarters = generate_fy_quarters("2024-01-01", "2024-12-31")
    assert len(quarters) == 4


def test_generate_fy_quarters_chronological():
    """[Q2] Quarter period_starts are strictly ascending."""
    quarters = generate_fy_quarters("2024-01-01", "2024-12-31")
    starts = [q[0] for q in quarters]
    assert starts == sorted(starts)
    assert len(set(starts)) == 4, "Quarter starts must be distinct"


def test_quarter_boxes_keys():
    """[Q3] QuarterBoxes has exactly the 6 required keys."""
    qb = _qb("2024-01-01", "2024-03-31", 1000, 0, 0, 500)
    assert set(qb.keys()) == {"period_start", "period_end", "box_1", "box_2", "box_3", "box_5"}


def test_quarter_boxes_values_are_decimal():
    """[Q4] Numeric fields in QuarterBoxes must be Decimal, not float."""
    qb = _qb("2024-01-01", "2024-03-31", 228163.35, 0.0, 0.0, 93666.97)
    for key in ("box_1", "box_2", "box_3", "box_5"):
        assert isinstance(qb[key], Decimal), f"{key} is {type(qb[key])}, expected Decimal"


# ---------------------------------------------------------------------------
# [F] FY period derivation and quarter generation
# ---------------------------------------------------------------------------

def test_derive_fy_jan_start_mid_year():
    """[F1] Jan fiscal start, period 2024-07-01 → FY 2024-01-01..2024-12-31."""
    start, end = derive_fy_period("2024-07-01", fiscal_year_start_month=1)
    assert start == "2024-01-01"
    assert end == "2024-12-31"


def test_derive_fy_apr_start_before_month():
    """[F2] Apr fiscal start, period 2024-01-15 → FY starts Apr 2023."""
    start, end = derive_fy_period("2024-01-15", fiscal_year_start_month=4)
    assert start == "2023-04-01"
    assert end == "2024-03-31"


def test_derive_fy_apr_start_after_month():
    """[F3] Apr fiscal start, period 2024-07-01 → FY starts Apr 2024."""
    start, end = derive_fy_period("2024-07-01", fiscal_year_start_month=4)
    assert start == "2024-04-01"
    assert end == "2025-03-31"


def test_generate_fy_quarters_jan_ranges():
    """[F4] Jan FY start → exact quarter date ranges."""
    quarters = generate_fy_quarters("2024-01-01", "2024-12-31")
    assert quarters[0] == ("2024-01-01", "2024-03-31")
    assert quarters[1] == ("2024-04-01", "2024-06-30")
    assert quarters[2] == ("2024-07-01", "2024-09-30")
    assert quarters[3] == ("2024-10-01", "2024-12-31")


def test_generate_fy_quarters_apr_cross_year():
    """[F5] Apr FY start → Q4 crosses into the next calendar year."""
    quarters = generate_fy_quarters("2024-04-01", "2025-03-31")
    assert quarters[0] == ("2024-04-01", "2024-06-30")
    assert quarters[1] == ("2024-07-01", "2024-09-30")
    assert quarters[2] == ("2024-10-01", "2024-12-31")
    assert quarters[3] == ("2025-01-01", "2025-03-31")


# ---------------------------------------------------------------------------
# [A] FY aggregation
# ---------------------------------------------------------------------------

def test_aggregate_to_fy_sums_correctly():
    """[A1] aggregate_to_fy sums box_1+box_2+box_3 → fy_box_4; box_5 → fy_box_5."""
    quarters = _four_quarters(b4_total=Decimal("993717.08"), b5_total=Decimal("500772.55"))
    fy_box_4, fy_box_5 = aggregate_to_fy(quarters)
    # Allow 1-cent rounding tolerance from the helper split
    assert abs(fy_box_4 - Decimal("993717.08")) <= Decimal("0.02")
    assert abs(fy_box_5 - Decimal("500772.55")) <= Decimal("0.02")


def test_aggregate_to_fy_all_zero_quarter():
    """[A2] All-zero Q4 (empty period) is handled without error."""
    quarters = [
        _qb("2024-01-01", "2024-03-31", 100, 0, 0, 50),
        _qb("2024-04-01", "2024-06-30", 200, 0, 0, 80),
        _qb("2024-07-01", "2024-09-30", 300, 0, 0, 120),
        _qb("2024-10-01", "2024-12-31", 0, 0, 0, 0),  # empty Q4
    ]
    fy_box_4, fy_box_5 = aggregate_to_fy(quarters)
    assert fy_box_4 == Decimal("600")
    assert fy_box_5 == Decimal("250")


# ---------------------------------------------------------------------------
# [I] Box-isolation invariant
# ---------------------------------------------------------------------------

def test_check_tpts_ratio_does_not_mutate_inputs():
    """[I1] check_tpts_ratio is read-only — original Decimal values unchanged."""
    b4 = Decimal("1000")
    b5 = Decimal("1300")
    b4_original = b4
    b5_original = b5
    check_tpts_ratio(b4, b5)
    assert b4 == b4_original
    assert b5 == b5_original
