"""
agent/budget.py — RunBudget accounting and over-budget routing primitive.

Per invariant 7: an agent that hits its cap fails into the non-blocking path,
never causes an unbounded run. BudgetExceededSignal is catchable; callers
route to the non-blocking path on catch (log + return deterministic chain
output without the agent's contribution).

Cost is accumulated so cost-per-run is auditable and priceable
(per-engagement pricing depends on it), consistent with T5.2 spec.

Public API:
    RunBudget               — turn/cost cap with over-budget flag
    BudgetExceededSignal    — raised when max_turns or max_cost_usd is exceeded

Zero anthropic import. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceededSignal(Exception):
    """Raised when a RunBudget cap is exceeded.

    Attributes:
        reason: Human-readable description of which cap was hit and the values.
    """
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class RunBudget:
    """Per-run turn/cost cap.

    Invariant 7 compliance: exceeding either cap raises BudgetExceededSignal,
    which the caller catches to route to the non-blocking path. The agent loop
    never runs unbounded.

    Cost is written into the justification ledger (by the caller, not here) so
    cost-per-review is auditable and priceable.

    Attributes:
        max_turns:      Maximum number of turns allowed.
        max_cost_usd:   Maximum USD cost allowed.
        turns_used:     Accumulated turns so far.
        cost_usd_used:  Accumulated cost in USD so far.
        over_budget:    Set to True when BudgetExceededSignal is raised.
    """
    max_turns: int
    max_cost_usd: float
    turns_used: int = field(default=0)
    cost_usd_used: float = field(default=0.0)
    over_budget: bool = field(default=False)

    def increment(self, *, turns: int = 1, cost_usd: float = 0.0) -> None:
        """Record consumption and raise BudgetExceededSignal if a cap is exceeded.

        Checks are performed AFTER accumulation so that reaching exactly the
        cap is allowed; exceeding it raises. This matches the spec: 'at exact
        cap does not raise'.

        Args:
            turns:    Number of turns to add (default 1).
            cost_usd: USD cost to add (default 0.0).

        Raises:
            BudgetExceededSignal: If turns_used > max_turns or
                                  cost_usd_used > max_cost_usd after accumulation.
        """
        self.turns_used += turns
        self.cost_usd_used += cost_usd

        if self.turns_used > self.max_turns:
            self.over_budget = True
            raise BudgetExceededSignal(
                f"max_turns exceeded: {self.turns_used} > {self.max_turns}"
            )
        if self.cost_usd_used > self.max_cost_usd:
            self.over_budget = True
            raise BudgetExceededSignal(
                f"max_cost_usd exceeded: {self.cost_usd_used:.6f} > {self.max_cost_usd:.6f}"
            )
