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
    >>> from omniclaw.storage.memory import InMemoryStorage
    >>> from decimal import Decimal
    >>>
    >>> # Create guards
    >>> storage = InMemoryStorage()
    >>> budget = BudgetGuard(daily_limit=Decimal("100"), storage=storage)
    >>> max_tx = SingleTxGuard(max_amount=Decimal("25"))
    >>>
    >>> # Combine into chain
    >>> chain = GuardChain([max_tx, budget])
    >>>
    >>> # Reserve before execution, then commit or release after outcome
    >>> tokens = await chain.reserve(payment_context)
    >>> try:
    ...     # Proceed with payment execution
    ...     await chain.commit(tokens)
    ... except Exception:
    ...     await chain.release(tokens)
    ...     raise
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
