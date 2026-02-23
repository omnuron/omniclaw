"""
Guards module - Spending controls for AI agent payments.

Provides various guards to control and limit agent spending:
- BudgetGuard: Limits total spending over time periods
- SingleTxGuard: Limits individual transaction amounts
- RecipientGuard: Controls which recipients are allowed
- RateLimitGuard: Limits payment frequency
- ConfirmGuard: Requires explicit confirmation

Example:
    >>> from omniclaw.guards import BudgetGuard, SingleTxGuard, GuardChain
    >>> from decimal import Decimal
    >>>
    >>> # Create guards
    >>> budget = BudgetGuard(daily_limit=Decimal("100"))
    >>> max_tx = SingleTxGuard(max_amount=Decimal("25"))
    >>>
    >>> # Combine into chain
    >>> chain = GuardChain([max_tx, budget])
    >>>
    >>> # Check payments
    >>> result = await chain.check(payment_context)
    >>> if result.allowed:
    ...     # Proceed with payment
    ...     budget.record_spending(payment_context.amount)
"""

from omniclaw.guards.base import (
    Guard,
    GuardChain,
    GuardResult,
    PaymentContext,
)
from omniclaw.guards.budget import BudgetGuard
from omniclaw.guards.confirm import ConfirmGuard
from omniclaw.guards.manager import GuardConfig, GuardManager, GuardType
from omniclaw.guards.rate_limit import RateLimitGuard
from omniclaw.guards.recipient import RecipientGuard
from omniclaw.guards.single_tx import SingleTxGuard

__all__ = [
    # Base classes
    "Guard",
    "GuardChain",
    "GuardResult",
    "PaymentContext",
    # Manager and Config
    "GuardManager",
    "GuardConfig",
    "GuardType",
    # Concrete guards
    "BudgetGuard",
    "SingleTxGuard",
    "RecipientGuard",
    "RateLimitGuard",
    "ConfirmGuard",
]
