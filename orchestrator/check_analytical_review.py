"""
orchestrator/check_analytical_review.py — Annual Analytical Review pass (T2.16).

Implements IRAS ASK Annual Review Guide Step 1.3d: TP/TS ratio check.
Computes the financial-year Box 5 / Box 4 ratio and surfaces a candidate
when the ratio exceeds 1.2 (IRAS-defined threshold).

Shared contract (consumed by T2.17 — period-over-period fluctuation check):
    QuarterBoxes keys: period_start, period_end, box_1, box_2, box_3, box_5
    All numeric values are Decimal (constructed via Decimal(str(float)) to
    avoid IEEE-754 representation leakage from the SAP float API).

IRAS basis:
    TP/TS ratio check — ASK Annual Review Guide §Step 1.3d
    "Taxable Purchases / Total Supplies ratio. If the TP/TS ratio exceeds
    1.2, request explanation from the client."

Approximation caveat (encoded in every finding):
    IRAS defines Total Supplies to EXCLUDE Boxes 14–16 (reverse charge /
    OVR / LVG output tax). Those boxes are not computed by this system,
    so the denominator used here is Box 4 only. For businesses with
    material RC/OVR transactions the ratio is approximate; the finding
    text discloses this explicitly.

    Box 4 == 0 → no finding (prevents ZeroDivisionError; an empty supply
    period is a separate analytical observation outside the scope of this check).

Invariants:
    - No `anthropic` import. Pure Python; safe from orchestrator/.
    - check_tpts_ratio() and aggregate_to_fy() are read-only.
    - All box values reaching T2.17 are Decimal(str(float)).
    - Findings are candidates for review; never verdicts.

Public API:
    QuarterBoxes                                         TypedDict
    derive_fy_period(period_start, fiscal_year_start_month) -> (str, str)
    generate_fy_quarters(fy_start, fy_end)               -> list[tuple[str,str]]
    filter_populated_quarters(quarters)                  -> list[QuarterBoxes]
    aggregate_to_fy(quarter_boxes_list)                  -> (Decimal, Decimal)
    check_tpts_ratio(fy_box_4, fy_box_5)                 -> list[dict]
    run_analytical_review_pass(client_config, period)    -> dict
"""
from __future__ import annotations

import calendar
import json
import logging
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import TypedDict

from orchestrator.check_period_fluctuation import detect_period_fluctuations

# Ensure repo root and mcp-servers/custom are on sys.path so sap_b1_server
# and config.loader are importable when called from run_agent.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MCP_CUSTOM = _REPO_ROOT / "mcp-servers" / "custom"
for _p in (str(_REPO_ROOT), str(_MCP_CUSTOM)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

log = logging.getLogger(__name__)

_CENT = Decimal("0.01")
_TPTS_THRESHOLD = Decimal("1.2")
_BASIS = "IRAS ASK Annual Review Guide §Step 1.3d"
_RC_OVR_CAVEAT = (
    "RC/OVR approximation: IRAS defines Total Supplies to exclude Boxes 14–16 "
    "(reverse charge / OVR / LVG output tax). Those boxes are not computed by "
    "this system. For businesses with material RC/OVR transactions the ratio is "
    "approximate — this finding is a candidate for reviewer confirmation, not a "
    "determination of non-compliance."
)


# ---------------------------------------------------------------------------
# Shared contract — T2.17 consumes this TypedDict
# ---------------------------------------------------------------------------

class QuarterBoxes(TypedDict):
    """One quarter's F5 box snapshot.

    Numeric values are Decimal, constructed via Decimal(str(float)) to
    avoid IEEE-754 representation leakage from the SAP float JSON API.
    """
    period_start: str
    period_end: str
    box_1: Decimal
    box_2: Decimal
    box_3: Decimal
    box_5: Decimal


# ---------------------------------------------------------------------------
# Empty-quarter filter (T2.17 integration)
# ---------------------------------------------------------------------------

_FLUCT_BOXES: tuple[str, ...] = ("box_1", "box_2", "box_3", "box_5")


def filter_populated_quarters(quarters: list[QuarterBoxes]) -> list[QuarterBoxes]:
    """Return only quarters that have at least one non-zero box value.

    A quarter is "empty" when box_1 == box_2 == box_3 == box_5 == 0.  This
    covers partial-year runs where the company has not filed the trailing
    quarter yet — excluding them prevents -100% artefact fluctuation findings
    from appearing in the report.

    Args:
        quarters: List of QuarterBoxes (Decimal values).  Not mutated.

    Returns:
        New list containing only the populated entries, in original order.
    """
    return [q for q in quarters if any(q[b] != 0 for b in _FLUCT_BOXES)]  # type: ignore[literal-required]


# ---------------------------------------------------------------------------
# FY period derivation
# ---------------------------------------------------------------------------

def _last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def derive_fy_period(
    period_start: str,
    fiscal_year_start_month: int,
) -> tuple[str, str]:
    """Derive the financial year containing period_start.

    Args:
        period_start:            ISO date 'YYYY-MM-DD' — the reviewed period start.
        fiscal_year_start_month: Integer 1–12; month when the client's FY begins.

    Returns:
        (fy_start, fy_end) as ISO date strings 'YYYY-MM-DD'.

    Examples:
        derive_fy_period("2024-07-01", 1)  → ("2024-01-01", "2024-12-31")
        derive_fy_period("2024-01-15", 4)  → ("2023-04-01", "2024-03-31")
        derive_fy_period("2024-07-01", 4)  → ("2024-04-01", "2025-03-31")
    """
    pd = date.fromisoformat(period_start)
    if pd.month >= fiscal_year_start_month:
        fy_start_year = pd.year
    else:
        fy_start_year = pd.year - 1

    fy_start = date(fy_start_year, fiscal_year_start_month, 1)
    # Next FY starts exactly 12 months later; FY ends one day before.
    next_fy_start_year = fy_start_year + 1
    next_fy_start = date(next_fy_start_year, fiscal_year_start_month, 1)
    fy_end = next_fy_start - timedelta(days=1)
    return fy_start.isoformat(), fy_end.isoformat()


# ---------------------------------------------------------------------------
# Quarter period generation
# ---------------------------------------------------------------------------

def _add_months(d: date, months: int) -> date:
    """Add an integer number of months to a date, clamping to month-end."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, _last_day_of_month(year, month))
    return date(year, month, day)


def generate_fy_quarters(fy_start: str, fy_end: str) -> list[tuple[str, str]]:
    """Divide the financial year into 4 successive 3-month quarter periods.

    Args:
        fy_start: ISO date 'YYYY-MM-DD' — first day of the FY.
        fy_end:   ISO date 'YYYY-MM-DD' — last day of the FY.

    Returns:
        List of 4 (period_start, period_end) ISO date string tuples,
        chronological from Q1 to Q4.  The last quarter's end date is
        always fy_end to handle months with varying day counts.
    """
    start = date.fromisoformat(fy_start)
    end = date.fromisoformat(fy_end)
    quarters: list[tuple[str, str]] = []
    for i in range(4):
        q_start = _add_months(start, 3 * i)
        if i < 3:
            q_end = _add_months(start, 3 * (i + 1)) - timedelta(days=1)
        else:
            q_end = end   # final quarter always ends at fy_end
        quarters.append((q_start.isoformat(), q_end.isoformat()))
    return quarters


# ---------------------------------------------------------------------------
# FY aggregation
# ---------------------------------------------------------------------------

def aggregate_to_fy(
    quarter_boxes_list: list[QuarterBoxes],
) -> tuple[Decimal, Decimal]:
    """Sum quarterly box values to produce FY-level Box 4 and Box 5.

    Box 4 is derived as sum(box_1 + box_2 + box_3) across all quarters.
    Box 5 is sum(box_5) across all quarters.

    Args:
        quarter_boxes_list: 4-element list of QuarterBoxes (Decimal values).

    Returns:
        (fy_box_4, fy_box_5) as Decimal.  Both are zero when all quarters
        are empty — the caller must guard against fy_box_4 == 0.
    """
    fy_box_4 = Decimal("0")
    fy_box_5 = Decimal("0")
    for q in quarter_boxes_list:
        fy_box_4 += q["box_1"] + q["box_2"] + q["box_3"]
        fy_box_5 += q["box_5"]
    return fy_box_4, fy_box_5


# ---------------------------------------------------------------------------
# TP/TS ratio check
# ---------------------------------------------------------------------------

def check_tpts_ratio(
    fy_box_4: Decimal,
    fy_box_5: Decimal,
) -> list[dict]:
    """Check the financial-year TP/TS ratio against the IRAS 1.2 threshold.

    Args:
        fy_box_4: Financial-year Box 4 (Total Supplies) as Decimal.
        fy_box_5: Financial-year Box 5 (Taxable Purchases) as Decimal.

    Returns:
        List of finding dicts.  Contains one TP_TS_RATIO finding when
        ratio > 1.2.  Empty list when ratio <= 1.2 or fy_box_4 == 0.
        The ratio is never asserted as a definitive error; the finding
        uses "candidate for review" language throughout.
    """
    if fy_box_4 == Decimal("0"):
        return []

    ratio = fy_box_4 and (fy_box_5 / fy_box_4)
    if ratio <= _TPTS_THRESHOLD:
        return []

    ratio_rounded = ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    return [{
        "check": "TP_TS_RATIO",
        "finding_type": "annual_analytical_review",
        "ratio": str(ratio_rounded),
        "fy_box_4": str(fy_box_4),
        "fy_box_5": str(fy_box_5),
        "threshold": str(_TPTS_THRESHOLD),
        "basis": _BASIS,
        "description": (
            f"Financial-year TP/TS ratio ({ratio_rounded}) exceeds the IRAS "
            f"threshold of {_TPTS_THRESHOLD}. IRAS ASK Annual Review Guide "
            f"§Step 1.3d requires the reviewer to obtain an explanation when "
            f"Taxable Purchases (Box 5 = {fy_box_5}) exceed Total Supplies "
            f"(Box 4 = {fy_box_4}) by more than 20%. Consider reviewing whether "
            "the purchases reflect a genuinely high-purchase-intensity period "
            "or indicate a recording or classification issue."
        ),
        "caveat": _RC_OVR_CAVEAT,
        "note": "candidate for review — requires practitioner explanation",
    }]


# ---------------------------------------------------------------------------
# Full pass — SAP integration
# ---------------------------------------------------------------------------

def run_analytical_review_pass(
    client_config,
    period: dict,
) -> dict:
    """Run the annual analytical review pass for the FY containing the reviewed period.

    Derives the financial year from client_config.fiscal_year_start_month,
    generates 4 quarter periods, calls calculate_f5_return once per quarter,
    constructs list[QuarterBoxes] with Decimal values, aggregates to FY totals,
    and runs the TP/TS ratio check.

    The SAP session must already be configured (run_chain has been called).
    This function is read-only — it never mutates compile_output or the boxes
    computed by the main chain run.

    Args:
        client_config: ClientConfig; reads fiscal_year_start_month.
        period:        {"start": ..., "end": ...} — the reviewed period.

    Returns:
        dict with keys:
            fy_start:              ISO date str
            fy_end:                ISO date str
            quarter_boxes:         list[QuarterBoxes] (4 entries, chronological)
            fy_box_4:              str (Decimal value)
            fy_box_5:              str (Decimal value)
            ratio:                 str or None (Decimal, None when fy_box_4 == 0)
            findings:              list[dict] — TP/TS ratio findings
            fluctuation_findings:  list[FluctuationFinding] — QoQ movement candidates
    """
    import sap_b1_server  # noqa: PLC0415 — deferred; module must be path-importable

    fiscal_year_start_month: int = getattr(
        client_config, "fiscal_year_start_month", 1
    )
    fy_start, fy_end = derive_fy_period(period["start"], fiscal_year_start_month)
    log.info(
        f"analytical-review: FY {fy_start}..{fy_end} "
        f"(fiscal_year_start_month={fiscal_year_start_month})"
    )

    quarter_periods = generate_fy_quarters(fy_start, fy_end)
    quarter_boxes: list[QuarterBoxes] = []

    for q_start, q_end in quarter_periods:
        raw = json.loads(sap_b1_server.calculate_f5_return(q_start, q_end))
        b = raw["boxes"]
        quarter_boxes.append(QuarterBoxes(
            period_start=q_start,
            period_end=q_end,
            # Decimal(str(v)) — never Decimal(v) — stops IEEE-754 leakage
            box_1=Decimal(str(b["box_1_standard_rated_sales"])),
            box_2=Decimal(str(b["box_2_zero_rated_sales"])),
            box_3=Decimal(str(b["box_3_exempt_sales"])),
            box_5=Decimal(str(b["box_5_taxable_purchases"])),
        ))
        log.info(
            f"  {q_start}..{q_end}: "
            f"box1={b['box_1_standard_rated_sales']:.2f} "
            f"box5={b['box_5_taxable_purchases']:.2f}"
        )

    fy_box_4, fy_box_5 = aggregate_to_fy(quarter_boxes)
    findings = check_tpts_ratio(fy_box_4, fy_box_5)

    ratio: str | None = None
    if fy_box_4 != Decimal("0"):
        r = fy_box_5 / fy_box_4
        ratio = str(r.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

    populated = filter_populated_quarters(quarter_boxes)
    fluctuation_findings = detect_period_fluctuations(populated)
    log.info(
        f"analytical-review: fy_box_4={fy_box_4} fy_box_5={fy_box_5} "
        f"ratio={ratio} findings={len(findings)} "
        f"fluctuation_findings={len(fluctuation_findings)} "
        f"(from {len(populated)}/{len(quarter_boxes)} populated quarters)"
    )

    return {
        "fy_start": fy_start,
        "fy_end": fy_end,
        "quarter_boxes": quarter_boxes,
        "fy_box_4": str(fy_box_4),
        "fy_box_5": str(fy_box_5),
        "ratio": ratio,
        "findings": findings,
        "fluctuation_findings": fluctuation_findings,
    }
