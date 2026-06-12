"""
engine — GST review pipeline seam (T5.1).

Exposes the full AgentAssist GST review pipeline as one atomic callable.

Public API:
    from engine.review import review          # must come from engine.review directly
    from engine import ReviewResult, ReviewInputs, GateHalt  # dataclasses re-exported here

`review` is intentionally absent from this package's namespace: re-exporting
it would set `engine.review = <function>`, shadowing the submodule attribute
and breaking `patch("engine.review.run_chain", ...)` in tests.  The dataclasses
carry no submodule name collision, so they are convenient to import from `engine`.
"""

from engine.review import GateHalt, ReviewInputs, ReviewResult  # noqa: E402

__all__ = ["ReviewResult", "ReviewInputs", "GateHalt"]
