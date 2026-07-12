"""
Internal-consistency reconciliation between two derivation paths over the SAME source:
GST posted to the Xero 820 control account (Account Transactions export) versus GST
declared in the F5 return. A divergence is a CANDIDATE FOR REVIEW — never a verdict,
never a gate, and no assertion that either side is correct.

This surfaces two failure modes:
  (a) a GST posting that lands in the 820 ledger but drops from the F5 report
      (e.g. a raw-GL manual journal with no tax code); and
  (b) a tax code whose control-account posting DISAGREES with its box routing
      (GST posted to 820 but the invoice routed to a non-GST-output box).

It does NOT detect a tax code that is WRONG but INTERNALLY CONSISTENT across ledger and
box — where both derive from the same (wrong) assignment they agree, and this check is
blind to it. This is an internal-consistency check, not a truth check.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# NON-REGULATORY TUNING PARAMETER — no IRAS source in knowledge-base/ prescribes a
# ledger-vs-return tolerance. The fixtures are cent-precision machine exports, so a
# one-cent band absorbs float/rounding noise without masking a real divergence.
_TOLERANCE: float = 0.01

# Ledger-side GST recompute is by SOURCE (the transaction TYPE), not by column: the 820
# control account credits output-tax liability and debits input-tax claims, so the sign a
# debit/credit contributes depends on which kind of transaction posted it.
_SOURCE_OUTPUT_ADD_CREDIT = "Receivable Invoice"      # output GST += credit
_SOURCE_OUTPUT_SUB_DEBIT = "Receivable Credit Note"   # output GST -= debit  (reversal)
_SOURCE_INPUT_ADD_DEBIT = "Payable Invoice"           # input  GST += debit
_SOURCE_INPUT_SUB_CREDIT = "Payable Credit Note"      # input  GST -= credit (reversal)
_SOURCE_MANUAL = "Manual Journal"                     # by sign vs 820: debit->input, credit->output


def _make_finding(side: str, ledger_gst: float, declared_gst: float,
                  divergence: float) -> dict:
    """Build one per-side divergence finding — a CANDIDATE, framed conditionally."""
    box_num = "6" if side == "output" else "7"
    description = (
        f"Ledger-derived {side} GST ({ledger_gst}) exceeds declared Box {box_num} "
        f"({declared_gst}) by {divergence}. If a reviewer adjudicates this divergence "
        f"as an error in the return, net GST payable would change by {divergence}. This "
        f"is an internal-consistency observation between two derivations of the same "
        f"source, not a verdict that either side is correct."
    )
    return {
        "check_id": "GST_LEDGER_RECON",
        "finding_type": "ledger_recon_divergence",
        "side": side,
        "ledger_gst": ledger_gst,
        "declared_gst": declared_gst,
        "divergence": divergence,
        "description": description,
        "recommendation": (
            "Candidate for reviewer adjudication. Reconcile the 820 control-"
            "account postings for this side against the declared return box."
        ),
    }


def run_ledger_recon_checks(ledger_lines, declared_boxes, tolerance: float = _TOLERANCE) -> list:
    """Reconcile ledger-derived GST against the return's DECLARED boxes; return findings.

    Args:
        ledger_lines:  list of dicts from feeders.xero_ledger_reader.load_gst_ledger —
                       each carries {source, debit, credit, ...}.
        declared_boxes: {"output_tax": <F5 Box 6>, "input_tax": <F5 Box 7>} — the RETURN's
                       DECLARED figures (caller-supplied). NEVER the engine's computed boxes
                       (comparing computed boxes to the return is a tautology: both derive
                       from the same tax-code assignments).
        tolerance:     per-side abs materiality band (default _TOLERANCE, a NON-REGULATORY
                       tuning parameter).

    Returns:
        list[dict]: zero, one, or two per-side finding dicts (output before input). A per-side
        abs divergence within ``tolerance`` emits nothing. Findings are CANDIDATES — this
        function asserts no verdict, mutates nothing, and never raises on a clean run.

    A line whose ``source`` matches none of the five known transaction types is NOT
    categorised (it cannot be signed against the 820 account without knowing its type);
    such lines are logged (surfaced, never silently dropped) and excluded from both totals.
    """
    output_gst = 0.0
    input_gst = 0.0
    unclassified: list[str] = []

    for line in ledger_lines:
        source = (line.get("source") or "").strip()
        debit = float(line.get("debit") or 0.0)
        credit = float(line.get("credit") or 0.0)
        if source == _SOURCE_OUTPUT_ADD_CREDIT:
            output_gst += credit
        elif source == _SOURCE_OUTPUT_SUB_DEBIT:
            output_gst -= debit
        elif source == _SOURCE_INPUT_ADD_DEBIT:
            input_gst += debit
        elif source == _SOURCE_INPUT_SUB_CREDIT:
            input_gst -= credit
        elif source == _SOURCE_MANUAL:
            input_gst += debit
            output_gst += credit
        else:
            unclassified.append(source)

    if unclassified:
        # Surfaced, never silently dropped (there is no such line in the demo fixtures;
        # the guard is real-world robustness). A structured metadata channel is a PR-2
        # concern — PR-1 keeps the return type list[dict] per the build contract.
        log.warning(
            "ledger recon: %d line(s) with unclassified source excluded from totals "
            "(surfaced, not dropped): %r",
            len(unclassified), sorted(set(unclassified)),
        )

    output_gst = round(output_gst, 2)
    input_gst = round(input_gst, 2)
    declared_output = round(float(declared_boxes["output_tax"]), 2)
    declared_input = round(float(declared_boxes["input_tax"]), 2)

    findings: list = []
    out_div = round(output_gst - declared_output, 2)
    if abs(out_div) > tolerance:
        findings.append(_make_finding("output", output_gst, declared_output, out_div))
    in_div = round(input_gst - declared_input, 2)
    if abs(in_div) > tolerance:
        findings.append(_make_finding("input", input_gst, declared_input, in_div))
    return findings
