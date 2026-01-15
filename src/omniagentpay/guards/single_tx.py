"""
SingleTxGuard - Limits individual transaction amounts.

Simple guard that blocks transactions above a maximum amount.
"""

from __future__ import annotations

from decimal import Decimal

from omniagentpay.guards.base import Guard, GuardResult, PaymentContext


class SingleTxGuard(Guard):
    """
    Guard that limits individual transaction amounts.
    
    Blocks any single payment that exceeds the configured maximum.
    """
    
    def __init__(
        self,
        max_amount: Decimal,
        min_amount: Decimal | None = None,
        name: str = "single_tx",
    ) -> None:
        """
        Initialize SingleTxGuard.
        
        Args:
            max_amount: Maximum allowed transaction amount
            min_amount: Optional minimum transaction amount
            name: Guard name for identification
        """
        self._name = name
        self._max_amount = max_amount
        self._min_amount = min_amount or Decimal("0")
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def max_amount(self) -> Decimal:
        return self._max_amount
    
    @property
    def min_amount(self) -> Decimal:
        return self._min_amount
    
    async def check(self, context: PaymentContext) -> GuardResult:
        """Check if transaction amount is within allowed range."""
        amount = context.amount
        
        if amount > self._max_amount:
            return GuardResult(
                allowed=False,
                reason=(
                    f"Transaction amount {amount} exceeds maximum {self._max_amount}"
                ),
                guard_name=self.name,
                metadata={
                    "requested": str(amount),
                    "max_allowed": str(self._max_amount),
                },
            )
        
        if amount < self._min_amount:
            return GuardResult(
                allowed=False,
                reason=(
                    f"Transaction amount {amount} below minimum {self._min_amount}"
                ),
                guard_name=self.name,
                metadata={
                    "requested": str(amount),
                    "min_required": str(self._min_amount),
                },
            )
        
        return GuardResult(
            allowed=True,
            guard_name=self.name,
        )
