"""orchestrator/check_partial_exemption.py — deterministic partial-exemption surfacing (Prompt I).

ASK Step 6 as a DETERMINISTIC check (D+), mirroring check_analytical_review.py's shape.
Two parts:
  (a) PREDICATE — actively_makes_exempt_supplies AND Box 3 > 0 AND the De Minimis
      computation FAILS -> one "apportionment may be required" candidate finding.
      TX-RE presence is INFORMATIONAL, never a gate: TX-RE lines present -> note that
      residual-input bucketing has begun; TX-RE ABSENT -> note that residual input tax
      may not have been identified (the STRONGER candidate). The check fires with zero
      TX-RE lines.
  (b) DE MINIMIS — exempt supplies (Box 3, as CODED) against the two thresholds
      (monthly-average and share-of-total-supplies), computed per ACCOUNTING PERIOD
      from the chain's boxes; the $40k/month average scales by months-in-period.

Invariants (mirror check_analytical_review.py):
- No ``anthropic`` import. Pure Python; safe from orchestrator/.
- check_partial_exemption() and run_partial_exemption_check() are READ-ONLY over
  boxes/compile_output — no box is recomputed, no gate is touched, nothing halts.
- All box values reaching the arithmetic are Decimal(str(float)) — never Decimal(float).
- Findings are candidates for review; never verdicts. The wording states the computed
  position GIVEN THE CODED FIGURES (Box 3 is what the client coded as exempt; a
  miscoded ES33 inflates the numerator) — consistency engine, not truth engine.

OUT OF SCOPE (v1 must NOT compute): the reg 33/34/35 apportionment formula, the
three-bucket attribution, and the Longer-Period-Adjustment mechanism. This module
only evaluates the predicate + the De Minimis arithmetic above. It DISCLOSES the
provisional nature of the position (see _NOTE) without computing the adjustment.

TX-RE note (rule-author ruling, 2026-07-15): the informational split keys on the
literal code "TX-RE". Annex-E bucket 3 lists TX-RE as a NAME COLLISION with
conflicting box-treatment semantics (T2.20); bucket 3 is blocked on T2.18 with no
scheduled follow-on. Revisit this note if/when bucket 3 lands.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------------------
# TERRY-AUTHORED CONSTANTS + WORDING (tax semantics — rule-author owns this block).
#
# VERIFIED 2026-07-15 (rule-author, against named sources):
#   (1) INCIDENTAL exempt supplies (reg 29(3) — e.g. bank interest, realised FX
#       gain/loss, share issuance; cf. General Guide §6.3.2) are EXCLUDED from
#       BOTH the numerator and the denominator of the De Minimis test.
#       Source: IRAS e-Tax Guide "GST: Partial Exemption and Input Tax Recovery"
#       (6th edition).
#       CONSEQUENCE: this system cannot identify an incidental exempt supply —
#       no tax code, GL account, item code or card code distinguishes one from a
#       trade exempt supply (ES33/ESN33 encode reg-33 vs non-reg-33 only). Box 3
#       is therefore used AS CODED; see _INCIDENTAL_CAVEAT for the exposure this
#       leaves and how it differs by data path.
#   (2) The "average of $40,000 per month" may be assessed over the prescribed
#       accounting period OR over a longer period (reg 28 requires the test in
#       any prescribed accounting period or any longer period). This module
#       assesses it over the PRESCRIBED ACCOUNTING PERIOD; the position is
#       therefore PROVISIONAL pending the Longer Period Adjustment (§6.3.8).
#       Sources: SSO GSTA1993-RG1 reg 28; IRAS e-Tax Guide "GST: Partial
#       Exemption and Input Tax Recovery" (6th edition).
# ---------------------------------------------------------------------------

# De Minimis thresholds. Exempt supplies are within De Minimis when the value is
# "less than or equals to" BOTH (1) an average of $40,000 per month and (2) 5% of
# the total value of all taxable and exempt supplies made in that accounting
# period. Breaching EITHER limb fails the rule.
# Sources: SSO GSTA1993-RG1 reg 28; IRAS GST: General Guide for Businesses §6.3.4.
_DE_MINIMIS_MONTHLY_AVG = Decimal("40000")   # S$40,000 per month, averaged over the period
_DE_MINIMIS_RATIO = Decimal("0.05")          # 5% of total taxable + exempt supplies

_BASIS = (
    "GST (General) Regulations reg 28 (De Minimis Rule); "
    "IRAS GST: General Guide for Businesses §6.3.4"
)

# Mirrors check_analytical_review._RC_OVR_CAVEAT: a SEPARATE field, never baked
# into the description. States what THIS SYSTEM does — it does not assert a
# definition of the denominator (§6.3.4 states a concept, "all taxable and exempt
# supplies made in that accounting period", not a box reference).
_RC_OVR_CAVEAT = (
    "Denominator scope: this system computes total taxable + exempt supplies as "
    "Box 1 + Box 2 + Box 3 from the coded figures. Reverse-charge / OVR / LVG "
    "supplies (Boxes 14-16) are not computed by this system and are therefore "
    "absent from the denominator; whether they form part of 'all taxable and "
    "exempt supplies' for this test is not determined here. For a business with "
    "material reverse-charge or OVR activity the denominator may be incomplete. "
    "This finding is a candidate for reviewer confirmation, not a determination "
    "of non-compliance."
)

_INCIDENTAL_CAVEAT = (
    "Incidental exempt supplies: supplies qualifying as incidental exempt "
    "supplies under reg 29(3) (for example bank interest, realised "
    "foreign-exchange gain/loss, share issuance) are excluded from both the "
    "numerator and the denominator of the De Minimis test. This system cannot "
    "identify them — no tax code, account code or item code distinguishes an "
    "incidental exempt supply from a trade exempt supply — so Box 3 is used as "
    "coded. Where Box 3 is re-derived from sales invoice lines, journal-booked "
    "incidental supplies are structurally absent (journal entries are not read by "
    "this system). Where Box 3 derives from a declared or filed figure, or where "
    "an incidental supply has been coded ES33/ESN33 on an invoice line, the "
    "numerator may be overstated and this finding may be raised where the De "
    "Minimis Rule is in fact satisfied. The reviewer confirms the composition of "
    "Box 3 before drawing any apportionment conclusion."
)

_NOTE = (
    "candidate for review — requires practitioner assessment of the apportionment "
    "position. Assessed over this prescribed accounting period; provisional "
    "pending the Longer Period Adjustment."
)

_TXRE_PRESENT_NOTE = (
    "TX-RE-coded purchase lines are present in this period — residual-input "
    "bucketing appears to have begun; the reviewer confirms its completeness."
)
_TXRE_ABSENT_NOTE = (
    "No TX-RE-coded purchase lines were found in this period — residual/overhead "
    "input tax may not have been identified or bucketed yet, which strengthens "
    "the case for reviewing whether apportionment is required."
)


# ---------------------------------------------------------------------------
# Mechanics
# ---------------------------------------------------------------------------

_RATIO_PRECISION = Decimal("0.0001")
_CENT = Decimal("0.01")


def months_in_period(period_start: str, period_end: str) -> int:
    """Calendar months spanned by [period_start, period_end], inclusive.

    A quarter (2024-07-01..2024-09-30) -> 3; a single month -> 1; a year -> 12.
    Day-of-month is ignored: the accounting periods this system reviews are
    whole calendar months/quarters/years (the chain's period contract).
    """
    start = date.fromisoformat(period_start)
    end = date.fromisoformat(period_end)
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def check_partial_exemption(
    *,
    actively_makes_exempt: bool,
    box_1: Decimal,
    box_2: Decimal,
    box_3: Decimal,
    months: int,
    txre_lines_present: bool,
) -> list[dict]:
    """Evaluate the partial-exemption predicate + De Minimis arithmetic. Pure/read-only.

    Fires (returns one finding) iff actively_makes_exempt AND box_3 > 0 AND the
    De Minimis computation FAILS on the coded figures — i.e. the period's exempt
    supplies breach EITHER the monthly-average threshold OR the ratio threshold.
    TX-RE presence only selects the informational note; it never gates.

    THRESHOLD ARITHMETIC: the comparison is made on the RAW quotients, never on
    rounded values. The test is "less than or equals to" — exact. Rounding before
    comparing would quantize a breach into compliance (a true ratio of 0.05004 ->
    0.0500 -> "not breached"), i.e. would fail silently in the taxpayer's favour.
    Rounded values are carried for DISPLAY only.

    Returns [] when: the flag is off; Box 3 (as coded) is zero or negative; the
    denominator (Box 1+2+3) is zero or negative (guard — no divide-by-zero); or
    the computed position meets both thresholds.
    """
    if not actively_makes_exempt:
        return []
    if box_3 <= Decimal("0"):
        return []
    box_4 = box_1 + box_2 + box_3
    if box_4 <= Decimal("0"):
        return []  # degenerate denominator (credit-note-heavy period) — no arithmetic possible

    # Compare RAW; quantize only for display (see docstring).
    monthly_avg_raw = box_3 / Decimal(months)
    ratio_raw = box_3 / box_4

    monthly_breached = monthly_avg_raw > _DE_MINIMIS_MONTHLY_AVG
    ratio_breached = ratio_raw > _DE_MINIMIS_RATIO
    if not (monthly_breached or ratio_breached):
        return []  # computed position meets both thresholds on the coded figures

    # Display-only rounding. NOTE: at a hairline breach the displayed figure can
    # read as equal to the threshold while the raw comparison (correctly) fired;
    # the per-limb *_breached flags are authoritative, not the rendered numbers.
    monthly_avg = monthly_avg_raw.quantize(_CENT, rounding=ROUND_HALF_UP)
    ratio = ratio_raw.quantize(_RATIO_PRECISION, rounding=ROUND_HALF_UP)

    description = (
        f"On the figures as coded, exempt supplies (Box 3) are "
        f"{box_3} over {months} month(s) — an average of {monthly_avg}/month "
        f"against the {_DE_MINIMIS_MONTHLY_AVG}/month threshold — and "
        f"{ratio:%} of total coded taxable + exempt supplies (Box 1+2+3 = {box_4}) "
        f"against the {_DE_MINIMIS_RATIO:%} threshold. The computed position does "
        f"not meet the De Minimis thresholds on these coded figures. "
        f"Consider reviewing whether input-tax apportionment is required for this "
        f"period (a miscoded exempt line would inflate Box 3; the reviewer "
        f"confirms the coding before any apportionment conclusion)."
    )

    return [{
        "check": "PARTIAL_EXEMPTION_DE_MINIMIS",
        "finding_type": "partial_exemption",
        "box_3": box_3,
        "box_4": box_4,
        "months_in_period": months,
        "monthly_average_exempt": monthly_avg,
        "exempt_ratio": ratio,
        "threshold_monthly_avg": _DE_MINIMIS_MONTHLY_AVG,
        "threshold_ratio": _DE_MINIMIS_RATIO,
        "monthly_average_breached": monthly_breached,
        "ratio_breached": ratio_breached,
        "txre_lines_present": txre_lines_present,
        "txre_note": _TXRE_PRESENT_NOTE if txre_lines_present else _TXRE_ABSENT_NOTE,
        "basis": _BASIS,
        "description": description,
        "caveat": _RC_OVR_CAVEAT,
        "caveat_incidental": _INCIDENTAL_CAVEAT,
        "note": _NOTE,
    }]


def run_partial_exemption_check(client_config, compile_output: dict) -> list[dict]:
    """Run the check over a completed chain's compile_output. READ-ONLY.

    Reads (never recomputes): compile_output["calculate"]["boxes"] (Decimal(str(...))
    at the float boundary), compile_output["period"] for months-in-period, and
    compile_output["classify"]["vatgroup_inventory"] for the INFORMATIONAL TX-RE
    presence (TX-RE routes to no F5 box, so its presence is only visible in the
    classify inventory, never in box totals).

    NOTE ON BOX 3 PROVENANCE: this function is reader-agnostic — it reads whatever
    box_3_exempt_sales the chain produced. On the SAP/extract path that figure is
    re-derived from ES33/ESN33 sales invoice and credit-note LINES. On the Xero F5
    path it is reconstructed from the client's FILED return, so it may include
    journal-booked incidental exempt supplies. See _INCIDENTAL_CAVEAT.

    The config flag is read with the same getattr forward-compat pattern the
    report layer uses for actively_makes_exempt_supplies.
    """
    actively = bool(getattr(client_config, "actively_makes_exempt_supplies", False))
    if not actively:
        return []  # cheap out — no box reads needed

    boxes = compile_output["calculate"]["boxes"]
    period = compile_output["period"]
    inventory = (compile_output.get("classify") or {}).get("vatgroup_inventory") or {}
    txre = inventory.get("TX-RE") or {}
    txre_present = bool(txre.get("doc_count", 0))

    return check_partial_exemption(
        actively_makes_exempt=actively,
        # Decimal(str(v)) — never Decimal(v) — stops IEEE-754 leakage.
        box_1=Decimal(str(boxes["box_1_standard_rated_sales"])),
        box_2=Decimal(str(boxes["box_2_zero_rated_sales"])),
        box_3=Decimal(str(boxes["box_3_exempt_sales"])),
        months=months_in_period(period["start"], period["end"]),
        txre_lines_present=txre_present,
    )
