class ChainError(Exception):
    pass


class GateFailure(Exception):
    """Raised when a gate's reconciliation check fails.

    checked: dict of the values the gate inspected when it decided to halt.
    Callers can inspect exc.checked for diagnostic output without re-parsing
    the exception message string.
    """

    def __init__(self, message: str = "", checked: dict | None = None) -> None:
        super().__init__(message)
        self.checked: dict = checked if checked is not None else {}
