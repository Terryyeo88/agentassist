"""
orchestrator/check_declared_f5.py — Declared-vs-computed F5 divergence checks (T2.9).

Two deterministic checks run against the client's manually-filed F5 figures:

    Check A — Declared internal consistency
        Verifies the client's own filed numbers are self-consistent:
            Box 4 == Box 1 + Box 2 + Box 3
            Box 8 == Box 6 − Box 7
        A breach surfaces as a finding (not a load error) — the audit run always
        completes and seals normally; the inconsistency is an observation for
        reviewer attention.  The rule violated is stated in the finding.

    Check B — Declared-vs-computed divergence
        Compares declared to computed on the six independent F5 boxes:
            box_1, box_2, box_3, box_5, box_6, box_7.
        Box 4 (= Box 1+2+3) and Box 8 (= Box 6−7) are derived; they are reported
        as informational consequence notes rather than primary flagged boxes to
        avoid double-counting accumulated rounding across summed boxes.

Tolerance / materiality band
    Default tolerance: 1.00 dollar per independent box, configurable via the
    declared-f5.json input file (global default + optional per-box override map).
    The band is a materiality floor, not a claimed IRAS F5-box filing rounding
    convention — the IRAS guides are silent on F5-box rounding (the GST General
    Guide §7.5.1 covers invoice-level cents only).  The 1.00 default absorbs
    whole-dollar truncation that can occur when a client reads box values off
    their filed return, consistent with the analytical-review principle in the
    IRAS ASK Annual Review Guide, s10.1(d)(iii), footnote 33, which explicitly
    excludes "rounding differences" from the declared-vs-computed divergence
    indicator.

    Citation embedded in every Check B finding:
        "IRAS ASK Annual Review Guide s10.1(d)(iii) fn33"

Findings are statements of fact (deterministic).  Cause is expressed as a
non-asserted hypothesis line ("possible … — for reviewer confirmation") and is
never a verdict.

Invariant: run_declared_f5_checks() is read-only over computed_boxes.
    The dict passed in is never mutated; canonical JSON of computed_boxes
    before and after the call is byte-identical.

No SAP calls; no anthropic import.  Pure Python, import-safe from orchestrator/.

Public API:
    load_declared_f5(path, run_period)             -> dict
    run_declared_f5_checks(declared_f5, computed)  -> list[dict]
"""
from __future__ import annotations

import json
from pathlib import Path

# Default per-box tolerance (dollars).  Configurable in the input file.
# Rationale: absorbs whole-dollar truncation on the filed return.
# IRAS ASK Annual Review Guide s10.1(d)(iii) fn33 excludes rounding differences
# from the declared-vs-computed analytical-review indicator.
_DEFAULT_TOLERANCE: float = 1.00

# Independent boxes: each compared individually against the tolerance band.
# Box 4 (= Box1+2+3) and Box 8 (= Box6-Box7) are derived; they are reported
# as consequence notes, not primary flagged items, so summed-box rounding does
# not accumulate into false positives.
_INDEPENDENT_BOXES: tuple[str, ...] = (
    "box_1", "box_2", "box_3", "box_5", "box_6", "box_7",
)

# Human-readable label for each box (matches IRAS F5 return field names).
_BOX_LABELS: dict[str, str] = {
    "box_1": "Total value of standard-rated supplies",
    "box_2": "Total value of zero-rated supplies",
    "box_3": "Total value of exempt supplies",
    "box_4": "Total value of all supplies (Box 1+2+3, derived)",
    "box_5": "Total value of taxable purchases",
    "box_6": "Output tax due",
    "box_7": "Input tax and refunds claimed",
    "box_8": "Net GST payable (Box 6−7, derived)",
}

# Non-asserted hypothesis lines — informational for reviewer; never a verdict.
_HYPOTHESES: dict[str, str] = {
    "box_1": (
        "possible over/under-declaration of standard-rated supplies "
        "— for reviewer confirmation"
    ),
    "box_2": (
        "possible over/under-declaration of zero-rated supplies "
        "— for reviewer confirmation"
    ),
    "box_3": (
        "possible over/under-declaration of exempt supplies "
        "— for reviewer confirmation"
    ),
    "box_5": (
        "possible over/under-declaration of taxable purchases "
        "— for reviewer confirmation"
    ),
    "box_6": (
        "possible over-claim of output tax OR unrecorded credit note "
        "— for reviewer confirmation"
    ),
    "box_7": (
        "possible over-claim of input tax OR unrecorded credit note "
        "— for reviewer confirmation"
    ),
}

# Map short box key ("box_1") to the full key used in F5ReturnOutput.boxes.
_COMPUTED_KEY: dict[str, str] = {
    "box_1": "box_1_standard_rated_sales",
    "box_2": "box_2_zero_rated_sales",
    "box_3": "box_3_exempt_sales",
    "box_4": "box_4_total_sales",
    "box_5": "box_5_taxable_purchases",
    "box_6": "box_6_output_tax",
    "box_7": "box_7_input_tax",
    "box_8": "box_8_net_gst",
}

_ALL_BOX_KEYS: frozenset[str] = frozenset(_COMPUTED_KEY)


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def load_declared_f5(path: Path, run_period: dict) -> dict:
    """Load and validate the declared F5 input file.

    The file must contain all eight box values and a period that matches the
    run period.  Period mismatch is a hard error (wrong file loaded).
    Internal inconsistencies (Box4 != Box1+2+3, Box8 != Box6-Box7) are NOT
    load errors — they surface as Check A findings so the run can proceed.

    Args:
        path:       Path to the declared-f5.json input file.
        run_period: The run's audit period {"start": ..., "end": ...} —
                    validated against the file's period field.

    Returns:
        Validated dict with keys:
            period           — {"start": ..., "end": ...} from the file
            source           — provenance label (default "manual_client_input")
            declared         — {"box_1": float, ..., "box_8": float}
            tolerance        — float, global per-box default (default 1.00)
            per_box_tolerance — {box_key: float} overrides (may be empty)

    Raises:
        FileNotFoundError: path does not exist.
        ValueError:        Malformed file, missing boxes, non-numeric values,
                           negative tolerance, or period mismatch.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))

    # Period mismatch = wrong file; halt immediately.
    file_period = raw.get("period", {})
    if (
        file_period.get("start") != run_period["start"]
        or file_period.get("end") != run_period["end"]
    ):
        raise ValueError(
            f"declared-f5.json period {file_period!r} does not match "
            f"run period {run_period!r} — wrong input file loaded"
        )

    declared_raw = raw.get("declared")
    if not isinstance(declared_raw, dict):
        raise ValueError("declared-f5.json: 'declared' must be a JSON object")

    required = {"box_1", "box_2", "box_3", "box_4", "box_5", "box_6", "box_7", "box_8"}
    missing = required - set(declared_raw.keys())
    if missing:
        raise ValueError(
            f"declared-f5.json: missing required keys: {sorted(missing)}"
        )

    declared: dict[str, float] = {}
    for k in required:
        v = declared_raw[k]
        if not isinstance(v, (int, float)):
            raise ValueError(
                f"declared-f5.json: '{k}' must be numeric, got {type(v).__name__!r}"
            )
        declared[k] = float(v)

    tolerance = float(raw.get("tolerance", _DEFAULT_TOLERANCE))
    if tolerance < 0:
        raise ValueError(
            f"declared-f5.json: tolerance must be non-negative, got {tolerance}"
        )

    per_box_tolerance: dict[str, float] = {}
    raw_pbt = raw.get("per_box_tolerance", {})
    if isinstance(raw_pbt, dict):
        for box_key, val in raw_pbt.items():
            if box_key not in _ALL_BOX_KEYS:
                raise ValueError(
                    f"declared-f5.json: unknown per_box_tolerance key '{box_key}'"
                )
            per_box_tolerance[box_key] = float(val)

    return {
        "period": file_period,
        "source": raw.get("source", "manual_client_input"),
        "declared": declared,
        "tolerance": tolerance,
        "per_box_tolerance": per_box_tolerance,
    }


# ---------------------------------------------------------------------------
# Check A — declared internal consistency
# ---------------------------------------------------------------------------

def _check_a(declared: dict[str, float]) -> list[dict]:
    """Check declared figures for internal self-consistency.

    Rule 1: Box 4 == Box 1 + Box 2 + Box 3
    Rule 2: Box 8 == Box 6 − Box 7

    Both rules are checked independently; each violation becomes a separate
    finding.  The run always continues regardless.
    """
    findings: list[dict] = []

    expected_4 = declared["box_1"] + declared["box_2"] + declared["box_3"]
    if declared["box_4"] != expected_4:
        delta = declared["box_4"] - expected_4
        findings.append({
            "check": "A",
            "finding_type": "declared_internal_inconsistency",
            "rule": "Box 4 must equal Box 1 + Box 2 + Box 3",
            "box": "box_4",
            "declared_box4": declared["box_4"],
            "expected_box4": expected_4,
            "delta": round(delta, 6),
            "description": (
                f"Declared Box 4 ({declared['box_4']}) does not equal "
                f"Box1+Box2+Box3 ({declared['box_1']}+{declared['box_2']}"
                f"+{declared['box_3']}={expected_4}); "
                f"delta={delta:+.2f}."
            ),
        })

    expected_8 = declared["box_6"] - declared["box_7"]
    if declared["box_8"] != expected_8:
        delta = declared["box_8"] - expected_8
        findings.append({
            "check": "A",
            "finding_type": "declared_internal_inconsistency",
            "rule": "Box 8 must equal Box 6 − Box 7",
            "box": "box_8",
            "declared_box8": declared["box_8"],
            "expected_box8": expected_8,
            "delta": round(delta, 6),
            "description": (
                f"Declared Box 8 ({declared['box_8']}) does not equal "
                f"Box6-Box7 ({declared['box_6']}-{declared['box_7']}"
                f"={expected_8}); "
                f"delta={delta:+.2f}."
            ),
        })

    return findings


# ---------------------------------------------------------------------------
# Check B — declared-vs-computed divergence
# ---------------------------------------------------------------------------

def _check_b(
    declared: dict[str, float],
    computed_boxes: dict[str, float],
    tolerance: float,
    per_box_tolerance: dict[str, float],
) -> list[dict]:
    """Compare declared to computed on the six independent F5 boxes.

    Box 4 and Box 8 are NOT flagged via the per-box tolerance band (their
    deltas accumulate from the independent boxes and would produce false
    positives).  Instead they are reported as informational consequence notes
    whenever one or more of their constituent boxes diverges.

    computed_boxes is never mutated — this function is read-only.
    """
    findings: list[dict] = []
    diverged: dict[str, float] = {}  # short_key -> declared-computed delta

    for short_key in _INDEPENDENT_BOXES:
        tol = per_box_tolerance.get(short_key, tolerance)
        comp_val = computed_boxes[_COMPUTED_KEY[short_key]]
        decl_val = declared[short_key]
        delta = decl_val - comp_val  # positive = over-declared
        if abs(delta) > tol:
            direction = "over_declared" if delta > 0 else "under_declared"
            findings.append({
                "check": "B",
                "finding_type": "declared_vs_computed_divergence",
                "box": short_key,
                "box_label": _BOX_LABELS[short_key],
                "declared": decl_val,
                "computed": comp_val,
                "delta": round(delta, 6),
                "direction": direction,
                "tolerance_applied": tol,
                # IRAS ASK Annual Review Guide s10.1(d)(iii) fn33 excludes
                # rounding differences from the declared-vs-computed indicator;
                # the 1.00 default absorbs whole-dollar truncation on the filed
                # return.  This citation is the basis for the tolerance floor.
                "basis": "IRAS ASK Annual Review Guide s10.1(d)(iii) fn33",
                "hypothesis": _HYPOTHESES.get(short_key, "for reviewer confirmation"),
            })
            diverged[short_key] = round(delta, 6)

    # --- Box 8 consequence note (net-GST headline) ---
    box6_d = diverged.get("box_6", 0.0)
    box7_d = diverged.get("box_7", 0.0)
    if box6_d != 0.0 or box7_d != 0.0:
        decl_8 = declared["box_8"]
        comp_8 = computed_boxes[_COMPUTED_KEY["box_8"]]
        delta_8 = decl_8 - comp_8
        findings.append({
            "check": "B",
            "finding_type": "declared_vs_computed_divergence_derived",
            "box": "box_8",
            "box_label": _BOX_LABELS["box_8"],
            "declared": decl_8,
            "computed": comp_8,
            "delta": round(delta_8, 6),
            "direction": "over_declared" if delta_8 > 0 else "under_declared",
            "note": (
                "Derived box — not subject to per-box tolerance band. "
                "Reported as net-GST consequence of base-box divergence(s)."
            ),
            "root_cause_attribution": {
                k: diverged[k] for k in ("box_6", "box_7") if k in diverged
            },
            "basis": "IRAS ASK Annual Review Guide s10.1(d)(iii) fn33",
        })

    # --- Box 4 consequence note (informational) ---
    box1_d = diverged.get("box_1", 0.0)
    box2_d = diverged.get("box_2", 0.0)
    box3_d = diverged.get("box_3", 0.0)
    if box1_d != 0.0 or box2_d != 0.0 or box3_d != 0.0:
        decl_4 = declared["box_4"]
        comp_4 = computed_boxes[_COMPUTED_KEY["box_4"]]
        delta_4 = decl_4 - comp_4
        findings.append({
            "check": "B",
            "finding_type": "declared_vs_computed_divergence_derived",
            "box": "box_4",
            "box_label": _BOX_LABELS["box_4"],
            "declared": decl_4,
            "computed": comp_4,
            "delta": round(delta_4, 6),
            "direction": "over_declared" if delta_4 > 0 else "under_declared",
            "note": (
                "Derived box — not subject to per-box tolerance band. "
                "Reported as informational consequence of base-box divergence(s)."
            ),
            "root_cause_attribution": {
                k: diverged[k] for k in ("box_1", "box_2", "box_3") if k in diverged
            },
            "basis": "IRAS ASK Annual Review Guide s10.1(d)(iii) fn33",
        })

    return findings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_declared_f5_checks(
    declared_f5: dict,
    computed_boxes: dict[str, float],
) -> list[dict]:
    """Run Check A (internal consistency) and Check B (declared-vs-computed).

    Args:
        declared_f5:    Validated dict from load_declared_f5().  Must contain
                        'declared' (8 box floats), 'tolerance' (float), and
                        'per_box_tolerance' (dict, may be empty).
        computed_boxes: The 'boxes' sub-dict from F5ReturnOutput (calculate
                        step output), keyed by full names such as
                        'box_1_standard_rated_sales'.
                        This dict is NEVER modified — T2.9 is read-only.

    Returns:
        list[dict]: All findings from Check A + Check B.  Empty list when no
                    inconsistencies or divergences are detected.  A non-empty
                    list is a finding set, not a gate — the run always completes
                    and seals normally.
    """
    declared = declared_f5["declared"]
    tolerance = declared_f5.get("tolerance", _DEFAULT_TOLERANCE)
    per_box_tolerance = declared_f5.get("per_box_tolerance", {})

    findings: list[dict] = []
    findings.extend(_check_a(declared))
    findings.extend(_check_b(declared, computed_boxes, tolerance, per_box_tolerance))
    return findings
