"""
orchestrator/check_period_fluctuation.py — Period-over-period fluctuation detection (T2.17).

Implements IRAS ASK §Step 1.3a: surfaces material quarter-over-quarter movements
in F5 Boxes 1/2/3/5 as candidates for reviewer explanation (business cycle vs error).

IRAS §1.3a defines no numeric threshold — it is a human reasonableness assessment.
The threshold_pct parameter is a non-regulatory surfacing tuning parameter.
Default: ±50% QoQ (clearly material; absorbs normal seasonal variation).

Public API:
    detect_period_fluctuations(quarters, threshold_pct) -> list[FluctuationFinding]

Input contract (shared with T2.16 FY-box pass):
    QuarterBoxes = {period_start, period_end, box_1, box_2, box_3, box_5} (Decimal)

No SAP calls; no anthropic import.  Pure Python, import-safe from orchestrator/.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TypedDict

_FOUR_DP = Decimal("0.0001")

_BOX_LABELS: dict[str, str] = {
    "box_1": "standard-rated supplies (Box 1)",
    "box_2": "zero-rated supplies (Box 2)",
    "box_3": "exempt supplies (Box 3)",
    "box_5": "taxable purchases (Box 5)",
}

_BOXES: tuple[str, ...] = ("box_1", "box_2", "box_3", "box_5")

_ASK_SUFFIX = (
    "Candidate for reviewer explanation (business cycle vs error) per ASK §" "1.3a. "
    "Surfacing threshold: ±{threshold}% (non-regulatory tuning parameter, not an IRAS rule)."
)


class QuarterBoxes(TypedDict):
    """Box values for a single GST quarter, consumed by detect_period_fluctuations.

    All monetary values are Decimal (SGD).  The caller (T2.16 FY-box pass) is
    responsible for converting float outputs from calculate_f5_return to Decimal.
    Only Boxes 1/2/3/5 are carried here — ASK §1.3a covers supplies and taxable
    purchases, not the derived or tax boxes.
    """
    period_start: str   # YYYY-MM-DD inclusive
    period_end: str     # YYYY-MM-DD inclusive
    box_1: Decimal      # standard-rated supplies
    box_2: Decimal      # zero-rated supplies
    box_3: Decimal      # exempt supplies
    box_5: Decimal      # taxable purchases


@dataclass(frozen=True)
class FluctuationFinding:
    """A surfaced QoQ movement candidate for reviewer attention per ASK §1.3a.

    pct_movement is None when the from-quarter value was zero (% change undefined).
    The finding is still surfaced — any non-zero value following a zero quarter
    warrants reviewer awareness regardless of magnitude.

    All findings are candidates, never assertions.  Cause attribution (business
    cycle, seasonal pattern, data error, etc.) is the reviewer's responsibility.
    """
    box: str                      # "box_1" | "box_2" | "box_3" | "box_5"
    from_period_start: str        # YYYY-MM-DD
    from_period_end: str          # YYYY-MM-DD
    to_period_start: str          # YYYY-MM-DD
    to_period_end: str            # YYYY-MM-DD
    pct_movement: Decimal | None  # signed 4dp; None when from_value was zero
    description: str              # human-readable framing for the reviewer


def detect_period_fluctuations(
    quarters: list[QuarterBoxes],
    threshold_pct: Decimal = Decimal("50"),
) -> list[FluctuationFinding]:
    """Detect material QoQ movements in F5 Boxes 1/2/3/5 per ASK §1.3a.

    Examines each consecutive quarter pair and surfaces a FluctuationFinding
    whenever abs(movement) > threshold_pct.  threshold_pct is a surfacing
    parameter, not an IRAS rule.

    Edge-case handling:
        - Fewer than 2 quarters       → returns [] immediately.
        - from==0 and to==0           → no movement, no finding.
        - from==0 and to!=0           → finding with pct_movement=None.
        - from!=0 and to==0           → pct = −100.0000% (flagged by threshold).
        - |movement| == threshold_pct → NOT flagged (comparison is strict >).

    Args:
        quarters:      Chronological list of QuarterBoxes.  The expected input
                       is 4 entries (one per GST filing period in the FY), but
                       any length >= 2 is accepted.  Not mutated.
        threshold_pct: Absolute movement magnitude triggering surfacing.
                       Default Decimal("50") = ±50% QoQ.  Non-regulatory.

    Returns:
        list[FluctuationFinding] ordered by (quarter-pair index, box order in
        _BOXES).  Empty list when no movements exceed the threshold.
    """
    if len(quarters) < 2:
        return []

    findings: list[FluctuationFinding] = []
    threshold_str = str(threshold_pct.normalize())

    for i in range(len(quarters) - 1):
        from_q = quarters[i]
        to_q = quarters[i + 1]

        for box in _BOXES:
            from_val: Decimal = from_q[box]  # type: ignore[literal-required]
            to_val: Decimal = to_q[box]      # type: ignore[literal-required]
            label = _BOX_LABELS[box]
            period_span = (
                f"{from_q['period_start']}–{from_q['period_end']}"
                f" → {to_q['period_start']}–{to_q['period_end']}"
            )

            if from_val == 0:
                if to_val == 0:
                    continue
                # Prior quarter was zero — movement undefined; surface regardless
                desc = (
                    f"{label}: {period_span}: prior-quarter value was zero; "
                    f"movement undefined (cannot compute % change). "
                    f"To-quarter value: {to_val}. "
                    + _ASK_SUFFIX.format(threshold=threshold_str)
                )
                findings.append(FluctuationFinding(
                    box=box,
                    from_period_start=from_q["period_start"],
                    from_period_end=from_q["period_end"],
                    to_period_start=to_q["period_start"],
                    to_period_end=to_q["period_end"],
                    pct_movement=None,
                    description=desc,
                ))
                continue

            raw_pct = (to_val - from_val) / abs(from_val) * Decimal("100")
            if abs(raw_pct) <= threshold_pct:
                continue

            pct = raw_pct.quantize(_FOUR_DP, rounding=ROUND_HALF_UP)
            sign = "+" if pct >= 0 else ""
            desc = (
                f"{label}: {period_span}: movement {sign}{pct}% "
                f"(from {from_val} to {to_val}). "
                + _ASK_SUFFIX.format(threshold=threshold_str)
            )
            findings.append(FluctuationFinding(
                box=box,
                from_period_start=from_q["period_start"],
                from_period_end=from_q["period_end"],
                to_period_start=to_q["period_start"],
                to_period_end=to_q["period_end"],
                pct_movement=pct,
                description=desc,
            ))

    return findings
