"""gst_ledger_input.py — shared assembly of the T2.24 gst_ledger side-input.

Extracted from run_agent.py so BOTH the CLI (run_agent) and the web layer (api/app.py)
build the gst_ledger dict the same way — the web layer must never import the CLI
entrypoint. Calls only feeder leaves (load_gst_ledger / parse_declared_return /
parse_not_included / parse_review_period), so importing this module drags in no
anthropic/agent/engine/orchestrator/reasoning.
"""
from __future__ import annotations


def build_gst_ledger_input(gst_ledger_path, xero_f5_path, period) -> dict:
    """Assemble the T2.24 gst_ledger side-input from a Xero ledger + F5 workbook.

    The F5 workbook (``xero_f5_path``) supplies the DECLARED boxes (Return sheet) AND the
    Signal-B "Transactions not included" rows; the Account-Transactions export
    (``gst_ledger_path``) supplies the 820 control-account lines. Returns the
    ``{"lines", "declared_boxes", "not_included"}`` dict the ``gst_ledger`` seam consumes
    (``declared_boxes`` = ``{"output_tax", "input_tax"}``).

    ``period`` is authoritative: this validates the F5 workbook's OWN period line against
    ``period`` and raises ValueError on mismatch — the file's self-reported period is never
    trusted to silently redefine the run window. (On the web F5 path ``period`` is derived
    from this same workbook, so the check is a no-op there.)
    """
    from feeders.xero_f5_reader import (  # noqa: PLC0415 — lazy; keeps import light
        parse_declared_return,
        parse_not_included,
        parse_review_period,
    )
    from feeders.xero_ledger_reader import load_gst_ledger  # noqa: PLC0415

    file_period = parse_review_period(xero_f5_path)
    if (file_period.get("start") != period["start"]
            or file_period.get("end") != period["end"]):
        raise ValueError(
            f"Xero F5 workbook period {file_period!r} does not match --period {period!r} "
            "(--period is authoritative; the workbook's own period is not trusted)"
        )
    return {
        "lines": load_gst_ledger(gst_ledger_path),
        "declared_boxes": parse_declared_return(xero_f5_path),
        "not_included": parse_not_included(xero_f5_path),
    }
