"""
Tests for orchestrator/check_declared_f5.py (T2.9).

All tests are hermetic — no SAP calls, no live calculate_f5_return.
Computed box values are constructed inline as plain dicts.

Required coverage:
    [A1] Check A: internal-consistency breach (Box4) emits a finding
    [A2] Check A: internal-consistency breach (Box8) emits a finding
    [A3] Check A: consistent declared figures produce no findings
    [B1] Check B: divergence beyond tolerance flagged on an independent box
    [B2] within-tolerance (0.99 delta at default 1.00) does NOT flag
    [B3] truncation case: declared = floor(computed) does NOT false-flag
    [B4] summed-box safety: box_1/2/3 each rounded, no individual breach
         → Box 4 does NOT appear as a finding
    [B5] Box 8 derived consequence note appears when box_6 or box_7 diverges
    [B6] Box 4 derived consequence note appears when box_1/2/3 diverges
    [B7] per_box_tolerance override respected
    [L1] load_declared_f5: period mismatch raises ValueError (hard error)
    [L2] load_declared_f5: missing box key raises ValueError
    [L3] load_declared_f5: non-numeric box value raises ValueError
    [L4] load_declared_f5: negative tolerance raises ValueError
    [L5] load_declared_f5: happy path loads correctly with default tolerance
    [L6] load_declared_f5: custom tolerance and per_box_tolerance loaded
    [I1] isolation byte-identity: computed boxes dict is NOT mutated by checks
    [I2] declared_f5_findings absent when declared_f5=None (run_chain path)
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

from orchestrator.check_declared_f5 import (
    _DEFAULT_TOLERANCE,
    load_declared_f5,
    run_declared_f5_checks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERIOD = {"start": "2024-07-01", "end": "2024-09-30"}


def _computed(
    box_1=10000.0, box_2=0.0, box_3=0.0,
    box_5=5000.0, box_6=900.0, box_7=450.0,
) -> dict[str, float]:
    """Return a computed-boxes dict with all 8 keys derived correctly."""
    box_4 = box_1 + box_2 + box_3
    box_8 = box_6 - box_7
    return {
        "box_1_standard_rated_sales": box_1,
        "box_2_zero_rated_sales": box_2,
        "box_3_exempt_sales": box_3,
        "box_4_total_sales": box_4,
        "box_5_taxable_purchases": box_5,
        "box_6_output_tax": box_6,
        "box_7_input_tax": box_7,
        "box_8_net_gst": box_8,
    }


def _declared_f5(
    box_1=10000, box_2=0, box_3=0, box_4=None,
    box_5=5000, box_6=900, box_7=450, box_8=None,
    tolerance=None, per_box_tolerance=None,
) -> dict:
    """Build a validated declared_f5 dict directly (bypasses file I/O).

    box_4 defaults to box_1+box_2+box_3; box_8 defaults to box_6-box_7.
    """
    b4 = box_4 if box_4 is not None else (box_1 + box_2 + box_3)
    b8 = box_8 if box_8 is not None else (box_6 - box_7)
    result = {
        "period": _PERIOD,
        "source": "manual_client_input",
        "declared": {
            "box_1": float(box_1),
            "box_2": float(box_2),
            "box_3": float(box_3),
            "box_4": float(b4),
            "box_5": float(box_5),
            "box_6": float(box_6),
            "box_7": float(box_7),
            "box_8": float(b8),
        },
        "tolerance": float(tolerance) if tolerance is not None else _DEFAULT_TOLERANCE,
        "per_box_tolerance": per_box_tolerance or {},
    }
    return result


def _write_f5_file(tmp_path: Path, payload: dict) -> Path:
    """Write a declared-f5.json fixture to a temp file and return its path."""
    p = tmp_path / "declared-f5.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# [A] Check A — declared internal consistency
# ---------------------------------------------------------------------------

def test_check_a_box4_inconsistency_emits_finding():
    """[A1] Box4 != Box1+Box2+Box3 must produce a finding with rule stated."""
    df5 = _declared_f5(box_1=10000, box_2=500, box_3=0, box_4=10600)  # wrong: should be 10500
    findings = run_declared_f5_checks(df5, _computed())
    check_a = [f for f in findings if f["check"] == "A" and f["box"] == "box_4"]
    assert len(check_a) == 1
    f = check_a[0]
    assert f["finding_type"] == "declared_internal_inconsistency"
    assert "Box 4 must equal Box 1 + Box 2 + Box 3" in f["rule"]
    assert f["declared_box4"] == 10600.0
    assert f["expected_box4"] == 10500.0
    assert abs(f["delta"] - 100.0) < 1e-9


def test_check_a_box8_inconsistency_emits_finding():
    """[A2] Box8 != Box6-Box7 must produce a finding with rule stated."""
    df5 = _declared_f5(box_6=900, box_7=450, box_8=500)  # wrong: should be 450
    findings = run_declared_f5_checks(df5, _computed())
    check_a = [f for f in findings if f["check"] == "A" and f["box"] == "box_8"]
    assert len(check_a) == 1
    f = check_a[0]
    assert f["finding_type"] == "declared_internal_inconsistency"
    assert "Box 8 must equal Box 6" in f["rule"]
    assert f["declared_box8"] == 500.0
    assert f["expected_box8"] == 450.0


def test_check_a_consistent_no_findings():
    """[A3] Internally consistent declared figures produce zero Check A findings."""
    df5 = _declared_f5()
    findings = run_declared_f5_checks(df5, _computed())
    assert all(f["check"] != "A" for f in findings)


# ---------------------------------------------------------------------------
# [B] Check B — declared-vs-computed divergence
# ---------------------------------------------------------------------------

def test_check_b_divergence_beyond_tolerance_flagged():
    """[B1] Delta > 1.00 on an independent box flags a finding."""
    # computed box_1 = 10000; declared = 11100 → delta = 1100 → way above 1.00
    df5 = _declared_f5(box_1=11100)
    comp = _computed(box_1=10000.0)
    findings = run_declared_f5_checks(df5, comp)
    b_box1 = [f for f in findings if f["check"] == "B" and f.get("box") == "box_1"
              and f["finding_type"] == "declared_vs_computed_divergence"]
    assert len(b_box1) == 1
    f = b_box1[0]
    assert f["direction"] == "over_declared"
    assert abs(f["delta"] - 1100.0) < 1e-9
    assert f["tolerance_applied"] == pytest.approx(_DEFAULT_TOLERANCE)
    assert "IRAS ASK Annual Review Guide" in f["basis"]
    assert "hypothesis" in f


def test_check_b_within_tolerance_no_flag():
    """[B2] Delta of 0.99 at default tolerance 1.00 does NOT flag."""
    # computed box_5 = 5000.00; declared = 5000.99 → delta = 0.99 < 1.00
    df5 = _declared_f5(box_5=5000.99)
    comp = _computed(box_5=5000.00)
    findings = run_declared_f5_checks(df5, comp)
    b_box5 = [f for f in findings if f["check"] == "B" and f.get("box") == "box_5"
              and f["finding_type"] == "declared_vs_computed_divergence"]
    assert b_box5 == []


def test_check_b_truncation_no_false_flag():
    """[B3] declared = floor(computed-to-dollar) does not false-flag.

    If computed box_1 = 12345.78 and the client truncated to 12345,
    delta = -0.78 which is within the 1.00 band — no finding.
    """
    df5 = _declared_f5(box_1=12345)
    comp = _computed(box_1=12345.78)
    findings = run_declared_f5_checks(df5, comp)
    b_box1 = [f for f in findings if f["check"] == "B" and f.get("box") == "box_1"
              and f["finding_type"] == "declared_vs_computed_divergence"]
    assert b_box1 == []


def test_check_b_summed_box_safety_no_box4_flag():
    """[B4] When box_1/2/3 each diverge < 1.00, Box 4 must NOT appear as a finding.

    Three independent boxes each with sub-tolerance deltas; the accumulated
    Box 4 delta can exceed 1.00, but since no base box triggered, the derived
    Box 4 consequence note must NOT be emitted.
    """
    # computed: box_1=1000.33, box_2=2000.34, box_3=3000.33 → box_4=6001.00
    comp = _computed(box_1=1000.33, box_2=2000.34, box_3=3000.33)
    # declared: box_1=1000, box_2=2000, box_3=3000 → box_4=6000
    # deltas: -0.33, -0.34, -0.33 → all < 1.00 → no independent findings
    # box_4 declared delta = 6000 - 6001.00 = -1.00; NOT flagged (base boxes didn't trip)
    df5 = _declared_f5(box_1=1000, box_2=2000, box_3=3000)
    findings = run_declared_f5_checks(df5, comp)
    b_findings = [f for f in findings if f["check"] == "B"]
    # No independent findings and no derived Box 4 consequence note
    assert b_findings == []


def test_check_b_box8_consequence_note_when_box6_diverges():
    """[B5] Box 8 derived consequence note emitted when box_6 diverges."""
    # computed box_6 = 900; declared = 2000 → delta = 1100 > 1.00
    comp = _computed(box_6=900.0, box_7=450.0)
    df5 = _declared_f5(box_6=2000, box_7=450)
    findings = run_declared_f5_checks(df5, comp)
    # Primary box_6 finding
    primary = [f for f in findings if f["check"] == "B" and f.get("box") == "box_6"
               and f["finding_type"] == "declared_vs_computed_divergence"]
    assert len(primary) == 1
    # Derived Box 8 consequence
    derived_8 = [f for f in findings if f["check"] == "B" and f.get("box") == "box_8"
                 and f["finding_type"] == "declared_vs_computed_divergence_derived"]
    assert len(derived_8) == 1
    f8 = derived_8[0]
    assert "box_6" in f8["root_cause_attribution"]
    assert "note" in f8
    assert "net-GST consequence" in f8["note"]


def test_check_b_box4_consequence_note_when_box1_diverges():
    """[B6] Box 4 derived consequence note emitted when box_1 diverges."""
    comp = _computed(box_1=10000.0)
    df5 = _declared_f5(box_1=15000)  # delta = 5000 >> 1.00
    findings = run_declared_f5_checks(df5, comp)
    derived_4 = [f for f in findings if f["check"] == "B" and f.get("box") == "box_4"
                 and f["finding_type"] == "declared_vs_computed_divergence_derived"]
    assert len(derived_4) == 1
    f4 = derived_4[0]
    assert "box_1" in f4["root_cause_attribution"]
    assert "informational consequence" in f4["note"]


def test_check_b_per_box_tolerance_override():
    """[B7] per_box_tolerance override respected for specific box."""
    # Default tolerance = 1.00, but override box_6 to 2000.00
    comp = _computed(box_6=900.0, box_7=450.0)
    # declared box_6 = 901.50 → delta = 1.50 → would trip at default 1.00
    # but with override of 2000.00 it should NOT flag
    df5 = _declared_f5(box_6=901.50, box_7=450, per_box_tolerance={"box_6": 2000.00})
    findings = run_declared_f5_checks(df5, comp)
    b_box6 = [f for f in findings if f["check"] == "B" and f.get("box") == "box_6"
              and f["finding_type"] == "declared_vs_computed_divergence"]
    assert b_box6 == []


# ---------------------------------------------------------------------------
# [L] load_declared_f5 — input loading and validation
# ---------------------------------------------------------------------------

def test_load_period_mismatch_raises(tmp_path):
    """[L1] Period mismatch is a hard load error."""
    payload = {
        "period": {"start": "2023-01-01", "end": "2023-03-31"},  # wrong period
        "declared": {k: 0 for k in ("box_1", "box_2", "box_3", "box_4",
                                     "box_5", "box_6", "box_7", "box_8")},
    }
    path = _write_f5_file(tmp_path, payload)
    with pytest.raises(ValueError, match="period.*does not match"):
        load_declared_f5(path, _PERIOD)


def test_load_missing_box_raises(tmp_path):
    """[L2] Missing a required box key raises ValueError."""
    payload = {
        "period": _PERIOD,
        "declared": {
            "box_1": 1000, "box_2": 0, "box_3": 0, "box_4": 1000,
            "box_5": 500, "box_6": 90, "box_7": 45,
            # box_8 missing
        },
    }
    path = _write_f5_file(tmp_path, payload)
    with pytest.raises(ValueError, match="missing required keys"):
        load_declared_f5(path, _PERIOD)


def test_load_non_numeric_box_raises(tmp_path):
    """[L3] Non-numeric box value raises ValueError."""
    payload = {
        "period": _PERIOD,
        "declared": {
            "box_1": "not_a_number", "box_2": 0, "box_3": 0, "box_4": 0,
            "box_5": 0, "box_6": 0, "box_7": 0, "box_8": 0,
        },
    }
    path = _write_f5_file(tmp_path, payload)
    with pytest.raises(ValueError, match="must be numeric"):
        load_declared_f5(path, _PERIOD)


def test_load_negative_tolerance_raises(tmp_path):
    """[L4] Negative tolerance raises ValueError."""
    payload = {
        "period": _PERIOD,
        "declared": {k: 0 for k in ("box_1", "box_2", "box_3", "box_4",
                                     "box_5", "box_6", "box_7", "box_8")},
        "tolerance": -1.0,
    }
    path = _write_f5_file(tmp_path, payload)
    with pytest.raises(ValueError, match="tolerance must be non-negative"):
        load_declared_f5(path, _PERIOD)


def test_load_happy_path_default_tolerance(tmp_path):
    """[L5] Happy-path load: default tolerance=1.00, per_box_tolerance empty."""
    payload = {
        "period": _PERIOD,
        "declared": {
            "box_1": 12345, "box_2": 0, "box_3": 0, "box_4": 12345,
            "box_5": 5000, "box_6": 1111, "box_7": 512, "box_8": 599,
        },
    }
    path = _write_f5_file(tmp_path, payload)
    result = load_declared_f5(path, _PERIOD)
    assert result["tolerance"] == pytest.approx(_DEFAULT_TOLERANCE)
    assert result["per_box_tolerance"] == {}
    assert result["declared"]["box_1"] == pytest.approx(12345.0)
    assert result["declared"]["box_8"] == pytest.approx(599.0)
    assert result["period"] == _PERIOD


def test_load_custom_tolerance_and_per_box(tmp_path):
    """[L6] Custom tolerance and per_box_tolerance loaded correctly."""
    payload = {
        "period": _PERIOD,
        "declared": {k: 0 for k in ("box_1", "box_2", "box_3", "box_4",
                                     "box_5", "box_6", "box_7", "box_8")},
        "tolerance": 2.50,
        "per_box_tolerance": {"box_6": 5.00, "box_7": 3.00},
    }
    path = _write_f5_file(tmp_path, payload)
    result = load_declared_f5(path, _PERIOD)
    assert result["tolerance"] == pytest.approx(2.50)
    assert result["per_box_tolerance"]["box_6"] == pytest.approx(5.00)
    assert result["per_box_tolerance"]["box_7"] == pytest.approx(3.00)


# ---------------------------------------------------------------------------
# [I] Isolation invariant
# ---------------------------------------------------------------------------

def test_isolation_computed_boxes_not_mutated():
    """[I1] run_declared_f5_checks never mutates the computed_boxes dict.

    Serialize computed_boxes to canonical JSON before and after the call —
    the bytes must be identical.  This proves the isolation invariant: T2.9
    is read-only over the calculate step's output.
    """
    comp = _computed(box_1=10000.0, box_6=900.0, box_7=450.0)
    before = copy.deepcopy(comp)

    # Trigger divergence on multiple boxes so all code paths in _check_b run.
    df5 = _declared_f5(box_1=15000, box_6=2000, box_7=100)
    _ = run_declared_f5_checks(df5, comp)

    after = copy.deepcopy(comp)

    # Byte-identical serialisation (sort_keys for determinism).
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)


def test_isolation_no_declared_f5_empty_findings():
    """[I2] When declared_f5=None is passed to run_chain, declared_f5_findings is [].

    This is tested at the steps.py level: compile() always returns the key
    with an empty list when T2.9 checks are not run.
    """
    from orchestrator.steps import compile as compile_step

    manifest = {
        "period": _PERIOD,
        "fetched_at": "2024-10-01T00:00:00+00:00",
        "records": [],
        "doc_nums": set(),
        "sap_inline_count": None,
    }
    calc = {
        "period": _PERIOD,
        "currency": "SGD",
        "boxes": _computed(),
        "fx_invoices_requiring_conversion": [],
        "e1_candidates": [],
        "record_counts": {"sales_invoices_sgd": 0, "sales_invoices_fx": 0,
                          "purchase_invoices_sgd": 0, "purchase_invoices_fx": 0},
        "credit_note_counts": {"sgd_sales": 0, "fx_sales": 0,
                               "sgd_purchases": 0, "fx_purchases": 0},
        "credit_notes_applied": [],
        "anomalies": [],
    }
    cls = {
        "period": _PERIOD,
        "expected_rate": 0.09,
        "vatgroup_inventory": {},
        "issues": [],
        "summary": {"E1": 0, "E2": 0, "E3": 0, "E4": 0, "total": 0},
    }
    det = {
        "period": _PERIOD,
        "severity_counts": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
        "issues": [],
    }
    result = compile_step(manifest, calc, cls, det)
    assert "declared_f5_findings" in result
    assert result["declared_f5_findings"] == []


# ---------------------------------------------------------------------------
# [A-FP] Check A — float-artifact robustness (Step 2 reproduction + Step 4 cases)
# ---------------------------------------------------------------------------

def test_check_a_float_artifact_box4_false_positive():
    """[A-FP1] Cent-consistent box_4 must NOT flag due to IEEE-754 float sum artifact.

    0.10 + 0.20 + 0.00 = 0.30000000000000004 in IEEE 754 (differs from 0.30 by ~5e-17).
    With exact equality the current code emits a spurious Check A finding.
    ACCEPTANCE: this test FAILS on unpatched code, passes after the cent-rounding fix.
    """
    # Values are to-the-cent consistent: 0.30 == 0.10 + 0.20 + 0.00 (in cents)
    df5 = _declared_f5(box_1=0.10, box_2=0.20, box_3=0.00, box_4=0.30)
    findings = run_declared_f5_checks(df5, _computed())
    check_a = [f for f in findings if f["check"] == "A" and f["box"] == "box_4"]
    assert check_a == [], (
        "Check A incorrectly flagged cent-consistent box_4=0.30 "
        f"(float sum=0.1+0.2+0.0={0.10 + 0.20 + 0.00!r})"
    )


def test_check_a_float_artifact_box8_false_positive():
    """[A-FP2] Cent-consistent box_8 must NOT flag due to IEEE-754 float subtraction artifact.

    0.30 - 0.10 = 0.19999999999999998 in IEEE 754 (differs from 0.20 by ~1e-17).
    With exact equality the current code emits a spurious Check A finding.
    ACCEPTANCE: this test FAILS on unpatched code, passes after the cent-rounding fix.
    """
    # box_8 = 0.20 is to-the-cent consistent with box_6=0.30 − box_7=0.10
    df5 = _declared_f5(box_6=0.30, box_7=0.10, box_8=0.20)
    findings = run_declared_f5_checks(df5, _computed())
    check_a = [f for f in findings if f["check"] == "A" and f["box"] == "box_8"]
    assert check_a == [], (
        "Check A incorrectly flagged cent-consistent box_8=0.20 "
        f"(float diff=0.30-0.10={0.30 - 0.10!r})"
    )


def test_check_a_exact_cent_match_no_finding():
    """[A-FP3] Values with no float artifact (exact integer cents) produce no Check A finding."""
    df5 = _declared_f5(box_1=1000.00, box_2=2000.00, box_3=3000.00, box_4=6000.00)
    findings = run_declared_f5_checks(df5, _computed())
    check_a_box4 = [f for f in findings if f["check"] == "A" and f["box"] == "box_4"]
    assert check_a_box4 == []


def test_check_a_off_by_one_cent_still_flags():
    """[A-FP4] An off-by-one-cent discrepancy must still be flagged after the fix.

    box_4 = 600.61 but box_1+box_2+box_3 = 600.60 → genuine inconsistency, must flag.
    """
    df5 = _declared_f5(box_1=200.20, box_2=200.20, box_3=200.20, box_4=600.61)
    findings = run_declared_f5_checks(df5, _computed())
    check_a = [f for f in findings if f["check"] == "A" and f["box"] == "box_4"]
    assert len(check_a) == 1, "Off-by-one-cent inconsistency must still flag"


def test_check_a_large_magnitude_float_artifact_no_false_positive():
    """[A-FP5] Large-magnitude values that are cent-consistent must not trip Check A.

    At large magnitudes floating-point addition artifacts can be larger (e.g. ~1e-10).
    Example: 100000.10 + 200000.20 + 300000.30 vs declared box_4=600000.60.
    """
    # Verify that this is actually a float-artifact case at this magnitude
    raw_sum = 100000.10 + 200000.20 + 300000.30
    # If the sum rounds to 600000.60 at the cent, it's cent-consistent
    df5 = _declared_f5(
        box_1=100000.10, box_2=200000.20, box_3=300000.30, box_4=600000.60
    )
    findings = run_declared_f5_checks(df5, _computed())
    check_a = [f for f in findings if f["check"] == "A" and f["box"] == "box_4"]
    assert check_a == [], (
        f"Large-magnitude float artifact triggered false positive; "
        f"raw_sum={raw_sum!r}, declared_box4=600000.60"
    )
