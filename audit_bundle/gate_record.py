"""gate_record.py — shape raw gate-tracking records into the gates.json schema."""

from __future__ import annotations


def build_gate_results(records: list[dict]) -> dict:
    """Convert a list of per-gate tracking dicts into the gates.json structure.

    Each record must have: gate, name, after_step, status, passed, checked.
    An optional message key is preserved when present.

    all_passed is True iff every gate has passed=True.  WARN_PASS still counts
    as passed; FAIL does not.
    """
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
        if "message" in r:
            entry["message"] = r["message"]
        gates.append(entry)
    return {"all_passed": all_passed, "gates": gates}
