"""
Risk Engine Factors.

Defines the interface and implementations for risk factors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from omniclaw.guards.base import PaymentContext


class RiskFactor(ABC):
    """
    Abstract base class for risk factors.

    A risk factor evaluates a payment context and returns a risk score contribution.
    """

    def __init__(self, weight: float = 1.0) -> None:
        """
        Initialize risk factor.

        Args:
            weight: Importance of this factor (0.0 to 1.0)
        """
        self.weight = weight

    @abstractmethod
    async def evaluate(self, context: PaymentContext) -> float:
        """
        Evaluate risk for a payment context.

        Args:
            context: Payment context

        Returns:
            Risk score contribution (0.0 to 1.0)
            0.0 = No Risk
            1.0 = High Risk
        """
        pass

    async def initialize(self, storage: Any, ledger: Any) -> None:
        """
        Initialize with storage and ledger access.
        
        Args:
            storage: Storage backend
            ledger: Ledger service
        """
        self._storage = storage
        self._ledger = ledger


class AmountFactor(RiskFactor):
    """
    Risk factor based on transaction amount.

    Risk scales non-linearly with amount.
    """

    def __init__(
        self,
        weight: float = 1.0,
        low_threshold: Decimal = Decimal("100"),
        high_threshold: Decimal = Decimal("1000"),
    ) -> None:
        super().__init__(weight)
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold

    async def evaluate(self, context: PaymentContext) -> float:
        amount = context.amount
        
        if amount <= self.low_threshold:
            return 0.0
        
        if amount >= self.high_threshold:
            return 1.0
            
        # Linear interpolation between low and high
        # (amount - low) / (high - low)
        risk = (amount - self.low_threshold) / (self.high_threshold - self.low_threshold)
        return float(risk)


class NewRecipientFactor(RiskFactor):
    """
    Risk factor based on recipient history.

    High risk if recipient is new for this wallet.
    """

    def __init__(self, weight: float = 1.0) -> None:
        super().__init__(weight)

    async def evaluate(self, context: PaymentContext) -> float:
        if not hasattr(self, "_ledger"):
            # Default to medium risk if ledger not available
            return 0.5

        # Check if we have paid this recipient before
        # This requires a ledger query
        # Optimize: Could cache recipients in Redis set
        
        # Check specific wallet history
        entries = await self._ledger.query(
            wallet_id=context.wallet_id,
            recipient=context.recipient,
            status=None, # Any status (even failed implies we tried)
            limit=1
        )
        
        if entries:
            return 0.0 # Known recipient
            
        return 1.0 # New recipient


class VelocityFactor(RiskFactor):
    """
    Risk factor based on transaction velocity.

    Checks if transaction frequency is spiking.
    """

    def __init__(
        self, 
        weight: float = 1.0, 
        window_seconds: int = 3600, 
        max_count: int = 10
    ) -> None:
        super().__init__(weight)
        self.window_seconds = window_seconds
        self.max_count = max_count

    async def evaluate(self, context: PaymentContext) -> float:
        if not hasattr(self, "_ledger"):
            return 0.5
            
        # We need to count transactions in the last window
        from datetime import datetime, timedelta
        
        start_time = datetime.utcnow() - timedelta(seconds=self.window_seconds)
        
        # This query might be expensive on large ledgers without indexing
        # For MVP, we use the ledger query
        entries = await self._ledger.query(
            wallet_id=context.wallet_id,
            from_date=start_time,
            limit=self.max_count * 2 # Fetch enough to verify
        )
        
        count = len(entries)
        
        if count <= self.max_count:
            return 0.0
            
        # Scale risk if over limit
        # simple linear scale: (count - max) / max
        excess = count - self.max_count
        risk = min(1.0, excess / self.max_count)
        
        return float(risk)
