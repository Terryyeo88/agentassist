"""gate_record.py — shape raw gate-tracking records into the gates.json schema.

Provides the single transformation step between the flat list of gate outcome
dicts accumulated in orchestrator/chain.py and the structured gates.json
payload written into the sealed audit bundle.

The gates.json schema is:

    {
        "all_passed": bool,
        "gates": [
            {
                "gate":       int,          # gate number (1–5)
                "name":       str,          # e.g. "record-count"
                "after_step": str,          # e.g. "fetch"
                "status":     str,          # "PASS" | "WARN_PASS" | "FAIL"
                "passed":     bool,
                "checked":    dict,         # values the gate inspected
                "message":    str           # optional; present on WARN_PASS/FAIL
            },
            ...
        ]
    }

WARN_PASS is treated as passed (the chain continued); FAIL is not.

Public API:
    build_gate_results(records) -> dict
"""
from __future__ import annotations


def build_gate_results(records: list[dict]) -> dict:
    """Convert a list of per-gate tracking dicts into the gates.json structure.

    Each record must have: gate, name, after_step, status, passed, checked.
    An optional message key is preserved when present.

    all_passed is True iff every gate has passed=True.  WARN_PASS still counts
    as passed; FAIL does not.

    Args:
        records: Ordered list of gate outcome dicts accumulated by the _rec()
                 helper in orchestrator/chain.py.  Each dict must contain the
                 six required keys; "message" is optional and included in the
                 output only when present in the input.  Records are expected
                 in execution order (gate 1 first, gate 5 last), though the
                 function does not enforce ordering.

    Returns:
        dict: gates.json payload with two keys:
            - "all_passed" (bool): True only when every record has passed=True.
              A chain that halted on a GateFailure will have at least one
              record with passed=False, making this False.
            - "gates" (list[dict]): One entry per input record, in the same
              order, with the optional "message" key included only when the
              source record carried one.

    Example:
        gate_results = build_gate_results(records)
        (bundle_dir / "gates.json").write_text(
            json.dumps(gate_results, indent=2)
        )
    """
    # all() over an empty list returns True; an empty records list means no
    # gates ran, which is an unusual but technically valid "all passed" state.
    all_passed = all(r["passed"] for r in records)
    gates = []
    for r in records:
        entry: dict = {
            "gate": r["gate"],
            "name": r["name"],
            "after_step": r["after_step"],
            "status": r["status"],
            "passed": r["passed"],
            "checked": r["checked"],
        }
        # Only copy "message" when it exists — PASS entries are intentionally
        # kept compact without a message key rather than carrying an empty string.
        if "message" in r:
            entry["message"] = r["message"]
        gates.append(entry)
    return {"all_passed": all_passed, "gates": gates}
