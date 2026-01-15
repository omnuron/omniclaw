"""
Guard base classes and chain.

Guards provide spending controls for AI agent payments.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omniagentpay.core.types import PaymentContext


@dataclass
class GuardResult:
    """
    Result of a guard check.
    
    Attributes:
        allowed: Whether the payment is allowed
        reason: Human-readable reason (especially when blocked)
        guard_name: Name of the guard that produced this result
        metadata: Additional context data
    """
    
    allowed: bool
    reason: str | None = None
    guard_name: str = ""
    metadata: dict[str, Any] | None = None
    
    def __bool__(self) -> bool:
        """Allow using result in boolean context."""
        return self.allowed


@dataclass
class PaymentContext:
    """
    Context for a payment being checked by guards.
    
    Contains all information guards need to make decisions.
    Guards can scope their limits by wallet_id or wallet_set_id.
    """
    
    wallet_id: str
    recipient: str
    amount: Decimal
    wallet_set_id: str | None = None
    purpose: str | None = None
    metadata: dict[str, Any] | None = None
    
    # Filled in by the system
    current_balance: Decimal | None = None
    total_spent_today: Decimal | None = None
    total_spent_hour: Decimal | None = None
    payment_count_today: int = 0


class Guard(ABC):
    """
    Abstract base class for payment guards.
    
    Guards inspect payment requests and decide whether to allow or block them.
    They provide spending controls for AI agents.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this guard."""
        ...
    
    @abstractmethod
    async def check(self, context: PaymentContext) -> GuardResult:
        """Check if payment should be allowed."""
        ...
    
    def bind_storage(self, storage: Any) -> None:
        """Bind storage backend to guard."""
        pass
    
    async def reserve(self, context: PaymentContext) -> str | None:
        """
        Reserve resources atomically.
        
        Returns:
            Reservation token (str) if successful, or None if stateless.
            Raises ValueError if check fails.
        """
        # Default implementation: just check
        result = await self.check(context)
        if not result.allowed:
            raise ValueError(result.reason)
        return None

    async def commit(self, token: str | None) -> None:
        """Commit reservation (finalize spend)."""
        pass

    async def release(self, token: str | None) -> None:
        """Release reservation (rollback)."""
        pass

    def reset(self) -> None:
        """Reset guard state."""
        pass


class GuardChain:
    """
    Chain of guards executed in sequence.
    
    Runs all guards and returns the first failure, or success if all pass.
    """
    
    def __init__(self, guards: list[Guard] | None = None) -> None:
        self._guards: list[Guard] = guards or []
    
    def add(self, guard: Guard) -> "GuardChain":
        """Add a guard to the chain."""
        self._guards.append(guard)
        return self
    
    def remove(self, name: str) -> bool:
        """Remove a guard by name."""
        for i, guard in enumerate(self._guards):
            if guard.name == name:
                del self._guards[i]
                return True
        return False
    
    def get(self, name: str) -> Guard | None:
        """Get a guard by name."""
        for guard in self._guards:
            if guard.name == name:
                return guard
        return None
    
    @property
    def guards(self) -> list[Guard]:
        """Get all guards in the chain."""
        return list(self._guards)
    
    async def check(self, context: PaymentContext) -> GuardResult:
        """
        Run all guards and return result.
        
        Stops at first failure.
        """
        passed_guards: list[str] = []
        
        for guard in self._guards:
            result = await guard.check(context)
            
            if not result.allowed:
                result.metadata = result.metadata or {}
                result.metadata["passed_guards"] = passed_guards
                return result
            
            passed_guards.append(guard.name)
        
        return GuardResult(
            allowed=True,
            reason="All guards passed",
            guard_name="chain",
            metadata={"passed_guards": passed_guards},
        )
    
    async def check_all(self, context: PaymentContext) -> list[GuardResult]:
        """
        Run all guards and return all results.
        
        Unlike check(), this doesn't stop at first failure.
        
        Args:
            context: Payment context
            
        Returns:
            List of all guard results
        """
        results = []
        for guard in self._guards:
            result = await guard.check(context)
            results.append(result)
        return results
    
    def reset_all(self) -> None:
        """Reset all guards in the chain."""
        for guard in self._guards:
            guard.reset()
    
    def __len__(self) -> int:
        """Return number of guards in chain."""
        return len(self._guards)
    
    def __iter__(self):
        """Iterate over guards."""
        return iter(self._guards)

    async def reserve(self, context: PaymentContext) -> list[tuple[str, str | None]]:
        """
        Reserve all guards in chain.
        Returns list of (guard_name, token).
        Rolls back on failure.
        """
        tokens: list[tuple[str, str | None]] = []
        try:
            for guard in self._guards:
                token = await guard.reserve(context)
                tokens.append((guard.name, token))
        except Exception:
            # Rollback performed reservations
            await self.release(tokens)
            raise
        return tokens

    async def commit(self, tokens: list[tuple[str, str | None]]) -> None:
        """Commit all reservations."""
        for name, token in tokens:
            guard = self.get(name)
            if guard:
                await guard.commit(token)

    async def release(self, tokens: list[tuple[str, str | None]]) -> None:
        """Release all reservations."""
        for name, token in tokens:
            guard = self.get(name)
            if guard:
                await guard.release(token)
