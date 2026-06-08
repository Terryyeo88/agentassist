"""
orchestrator/exceptions.py — Custom exception hierarchy for the audit chain.

Defines the two exception types raised within the orchestrator package:

    ChainError   — base class for unexpected chain-level failures.
    GateFailure  — reconciliation gate halted the chain; carries the values
                   the gate inspected so callers can build diagnostic output
                   without re-parsing the exception message string.

These are the only exception types that orchestrator/chain.py propagates
intentionally.  All other exceptions are unhandled and indicate bugs.
"""


class ChainError(Exception):
    """Base class for unexpected failures within the audit chain.

    Raised for unrecoverable errors that are not reconciliation failures
    (e.g. a step returning a structurally invalid result).  Not currently
    raised directly — subclass or raise as-is when needed.
    """
    pass


class GateFailure(Exception):
    """Raised when a gate's reconciliation check fails.

    Carries a `checked` dict of the values the gate inspected when it
    decided to halt, so callers can build diagnostic output or partial
    gate records without re-parsing the exception message string.

    Attributes:
        checked: Dict of the numeric or structural values the gate evaluated.
                 Always a dict — never None — even if the caller omits it.

    Example:
        try:
            run_chain(cfg, period)
        except GateFailure as exc:
            print(exc)           # human-readable message
            print(exc.checked)   # {"local_count": 42, "sap_inline_count": 45}
    """

    def __init__(self, message: str = "", checked: dict | None = None) -> None:
        """Initialise GateFailure with an optional message and checked values.

        Args:
            message: Human-readable description of why the gate halted,
                     forwarded to Exception.__init__ for str(exc) output.
            checked: Dict of values the gate inspected.  Defaults to an
                     empty dict when omitted so callers can always iterate
                     exc.checked without a None guard.
        """
        super().__init__(message)
        # Normalise None → {} so downstream code can always do exc.checked.items()
        # without guarding against None.
        self.checked: dict = checked if checked is not None else {}
