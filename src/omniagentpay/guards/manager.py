"""
GuardManager - Manages guard registrations using StorageBackend.

Clean architecture following the Ledger pattern:
- GuardConfig dataclass with to_dict() and from_dict()
- GuardManager service that uses storage directly
- Simple and testable
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
import uuid

from omniagentpay.guards.base import Guard, GuardChain, PaymentContext
from omniagentpay.core.logging import get_logger

if TYPE_CHECKING:
    from omniagentpay.storage.base import StorageBackend


class GuardType(str, Enum):
    """Types of guards available."""
    
    BUDGET = "budget"
    SINGLE_TX = "single_tx"
    RECIPIENT = "recipient"
    RATE_LIMIT = "rate_limit"
    CONFIRM = "confirm"


@dataclass
class GuardConfig:
    """Configuration for a guard instance, serializable to storage."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    guard_type: GuardType = GuardType.BUDGET
    name: str = "unnamed"
    
    # Budget guard params
    daily_limit: Decimal | None = None
    hourly_limit: Decimal | None = None
    total_limit: Decimal | None = None
    
    # Single tx guard params
    max_amount: Decimal | None = None
    min_amount: Decimal | None = None
    
    # Recipient guard params
    recipient_mode: str = "whitelist"  # "whitelist" or "blacklist"
    recipient_addresses: list[str] = field(default_factory=list)
    
    # Rate limit guard params
    max_per_minute: int | None = None
    max_per_hour: int | None = None
    max_per_day: int | None = None
    
    # Confirm guard params
    confirm_threshold: Decimal | None = None
    always_confirm: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "guard_type": self.guard_type.value,
            "name": self.name,
            # Budget
            "daily_limit": str(self.daily_limit) if self.daily_limit else None,
            "hourly_limit": str(self.hourly_limit) if self.hourly_limit else None,
            "total_limit": str(self.total_limit) if self.total_limit else None,
            # Single tx
            "max_amount": str(self.max_amount) if self.max_amount else None,
            "min_amount": str(self.min_amount) if self.min_amount else None,
            # Recipient
            "recipient_mode": self.recipient_mode,
            "recipient_addresses": self.recipient_addresses,
            # Rate limit
            "max_per_minute": self.max_per_minute,
            "max_per_hour": self.max_per_hour,
            "max_per_day": self.max_per_day,
            # Confirm
            "confirm_threshold": str(self.confirm_threshold) if self.confirm_threshold else None,
            "always_confirm": self.always_confirm,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GuardConfig":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            guard_type=GuardType(data.get("guard_type", GuardType.BUDGET.value)),
            name=data.get("name", "unnamed"),
            # Budget
            daily_limit=Decimal(data["daily_limit"]) if data.get("daily_limit") else None,
            hourly_limit=Decimal(data["hourly_limit"]) if data.get("hourly_limit") else None,
            total_limit=Decimal(data["total_limit"]) if data.get("total_limit") else None,
            # Single tx
            max_amount=Decimal(data["max_amount"]) if data.get("max_amount") else None,
            min_amount=Decimal(data["min_amount"]) if data.get("min_amount") else None,
            # Recipient
            recipient_mode=data.get("recipient_mode", "whitelist"),
            recipient_addresses=data.get("recipient_addresses", []),
            # Rate limit
            max_per_minute=data.get("max_per_minute"),
            max_per_hour=data.get("max_per_hour"),
            max_per_day=data.get("max_per_day"),
            # Confirm
            confirm_threshold=Decimal(data["confirm_threshold"]) if data.get("confirm_threshold") else None,
            always_confirm=data.get("always_confirm", False),
        )
    
    @classmethod
    def from_guard(cls, guard: Guard) -> "GuardConfig":
        guard_type = cls._detect_guard_type(guard)
        
        config = cls(
            guard_type=guard_type,
            name=guard.name,
        )
        
        # Budget guard
        if hasattr(guard, "_daily_limit"):
            config.daily_limit = guard._daily_limit
        if hasattr(guard, "_hourly_limit"):
            config.hourly_limit = guard._hourly_limit
        if hasattr(guard, "_total_limit"):
            config.total_limit = guard._total_limit
        
        # Single tx guard
        if hasattr(guard, "_max_amount"):
            config.max_amount = guard._max_amount
        if hasattr(guard, "_min_amount"):
            config.min_amount = guard._min_amount
        
        # Recipient guard
        if hasattr(guard, "_mode"):
            config.recipient_mode = guard._mode
        if hasattr(guard, "_addresses"):
            config.recipient_addresses = list(guard._addresses)
        
        # Rate limit guard
        if hasattr(guard, "_max_per_minute"):
            config.max_per_minute = guard._max_per_minute
        if hasattr(guard, "_max_per_hour"):
            config.max_per_hour = guard._max_per_hour
        if hasattr(guard, "_max_per_day"):
            config.max_per_day = guard._max_per_day
        
        # Confirm guard
        if hasattr(guard, "_threshold"):
            config.confirm_threshold = guard._threshold
        if hasattr(guard, "_always_confirm"):
            config.always_confirm = guard._always_confirm
        
        return config
    
    @staticmethod
    def _detect_guard_type(guard: Guard) -> GuardType:
        """Detect guard type from class name."""
        class_name = guard.__class__.__name__
        mapping = {
            "BudgetGuard": GuardType.BUDGET,
            "SingleTxGuard": GuardType.SINGLE_TX,
            "RecipientGuard": GuardType.RECIPIENT,
            "RateLimitGuard": GuardType.RATE_LIMIT,
            "ConfirmGuard": GuardType.CONFIRM,
        }
        return mapping.get(class_name, GuardType.BUDGET)
    
    def to_guard(self, storage: "StorageBackend") -> Guard:
        """Create a Guard instance from this config."""
        from omniagentpay.guards.budget import BudgetGuard
        from omniagentpay.guards.single_tx import SingleTxGuard
        from omniagentpay.guards.recipient import RecipientGuard
        from omniagentpay.guards.rate_limit import RateLimitGuard
        from omniagentpay.guards.confirm import ConfirmGuard
        
        if self.guard_type == GuardType.BUDGET:
            guard = BudgetGuard(
                name=self.name,
                daily_limit=self.daily_limit,
                hourly_limit=self.hourly_limit,
                total_limit=self.total_limit,
            )
        elif self.guard_type == GuardType.SINGLE_TX:
            guard = SingleTxGuard(
                name=self.name,
                max_amount=self.max_amount or Decimal("0"),
                min_amount=self.min_amount,
            )
        elif self.guard_type == GuardType.RECIPIENT:
            guard = RecipientGuard(
                name=self.name,
                mode=self.recipient_mode,
                addresses=self.recipient_addresses,
            )
        elif self.guard_type == GuardType.RATE_LIMIT:
            guard = RateLimitGuard(
                name=self.name,
                max_per_minute=self.max_per_minute,
                max_per_hour=self.max_per_hour,
                max_per_day=self.max_per_day,
            )
        elif self.guard_type == GuardType.CONFIRM:
            guard = ConfirmGuard(
                name=self.name,
                threshold=self.confirm_threshold,
                always_confirm=self.always_confirm,
            )
        else:
            raise ValueError(f"Unknown guard type: {self.guard_type}")
        
        guard.bind_storage(storage)
        return guard


class GuardManager:
    """Manages guard registrations using StorageBackend."""
    
    COLLECTION = "guard_registrations"
    
    def __init__(self, storage: "StorageBackend") -> None:
        """
        Initialize GuardManager with storage backend.
        
        Args:
            storage: StorageBackend for persistence
        """
        self._storage = storage
        self._logger = get_logger("guards")
    
    def _make_key(self, scope_type: str, scope_id: str) -> str:
        """Make storage key."""
        return f"{scope_type}:{scope_id}"
    
    # ==================== Add Guards ====================
    
    async def add_guard(self, wallet_id: str, guard: Guard) -> "GuardManager":
        """
        Add a guard for a wallet.
        
        Args:
            wallet_id: Wallet ID
            guard: Guard to add
            
        Returns:
            Self for chaining
        """
        key = self._make_key("wallet", wallet_id)
        
        # Get existing configs
        data = await self._storage.get(self.COLLECTION, key) or {"guards": []}
        
        # Create config from guard and add
        config = GuardConfig.from_guard(guard)
        data["guards"].append(config.to_dict())
        
        await self._storage.save(self.COLLECTION, key, data)
        return self
    
    async def add_guard_for_set(self, wallet_set_id: str, guard: Guard) -> "GuardManager":
        """Add a guard for a wallet set."""
        key = self._make_key("wallet_set", wallet_set_id)
        
        data = await self._storage.get(self.COLLECTION, key) or {"guards": []}
        config = GuardConfig.from_guard(guard)
        data["guards"].append(config.to_dict())
        
        await self._storage.save(self.COLLECTION, key, data)
        return self
    
    # ==================== Remove Guards ====================
    
    async def remove_guard(self, wallet_id: str, guard_name: str) -> bool:
        """Remove a guard from a wallet."""
        key = self._make_key("wallet", wallet_id)
        data = await self._storage.get(self.COLLECTION, key)
        
        if not data:
            return False
        
        original_count = len(data.get("guards", []))
        data["guards"] = [g for g in data.get("guards", []) if g.get("name") != guard_name]
        
        if len(data["guards"]) < original_count:
            await self._storage.save(self.COLLECTION, key, data)
            return True
        return False
    
    async def remove_guard_from_set(self, wallet_set_id: str, guard_name: str) -> bool:
        """Remove a guard from a wallet set."""
        key = self._make_key("wallet_set", wallet_set_id)
        data = await self._storage.get(self.COLLECTION, key)
        
        if not data:
            return False
        
        original_count = len(data.get("guards", []))
        data["guards"] = [g for g in data.get("guards", []) if g.get("name") != guard_name]
        
        if len(data["guards"]) < original_count:
            await self._storage.save(self.COLLECTION, key, data)
            return True
        return False
    
    # ==================== Get Guards ====================
    
    async def get_wallet_guards(self, wallet_id: str) -> GuardChain:
        """Get guards for a wallet."""
        key = self._make_key("wallet", wallet_id)
        data = await self._storage.get(self.COLLECTION, key)
        
        chain = GuardChain()
        if data:
            for guard_data in data.get("guards", []):
                config = GuardConfig.from_dict(guard_data)
                guard = config.to_guard(self._storage)
                chain.add(guard)
        
        return chain
    
    async def get_wallet_set_guards(self, wallet_set_id: str) -> GuardChain:
        """Get guards for a wallet set."""
        key = self._make_key("wallet_set", wallet_set_id)
        data = await self._storage.get(self.COLLECTION, key)
        
        chain = GuardChain()
        if data:
            for guard_data in data.get("guards", []):
                config = GuardConfig.from_dict(guard_data)
                guard = config.to_guard(self._storage)
                chain.add(guard)
        
        return chain
    
    async def list_wallet_guard_names(self, wallet_id: str) -> list[str]:
        """List guard names for a wallet."""
        key = self._make_key("wallet", wallet_id)
        data = await self._storage.get(self.COLLECTION, key)
        
        if not data:
            return []
        return [g.get("name", "unnamed") for g in data.get("guards", [])]
    
    async def list_wallet_set_guard_names(self, wallet_set_id: str) -> list[str]:
        """List guard names for a wallet set."""
        key = self._make_key("wallet_set", wallet_set_id)
        data = await self._storage.get(self.COLLECTION, key)
        
        if not data:
            return []
        return [g.get("name", "unnamed") for g in data.get("guards", [])]
    
    # ==================== Combined Operations ====================
    
    async def get_guard_chain(
        self,
        wallet_id: str,
        wallet_set_id: str | None = None,
    ) -> GuardChain:
        """
        Get combined guard chain for a wallet.
        
        Merges guards from wallet set (if provided) and wallet.
        """
        combined = GuardChain()
        
        # Add wallet set guards first
        if wallet_set_id:
            set_chain = await self.get_wallet_set_guards(wallet_set_id)
            for guard in set_chain:
                combined.add(guard)
        
        # Add wallet-specific guards
        wallet_chain = await self.get_wallet_guards(wallet_id)
        for guard in wallet_chain:
            combined.add(guard)
        
        return combined
    
    async def check(self, context: PaymentContext) -> tuple[bool, str | None, list[str]]:
        """
        Check guards for a payment context.
        
        Returns:
            Tuple of (allowed, reason, passed_guards)
        """
        chain = await self.get_guard_chain(
            context.wallet_id,
            context.wallet_set_id,
        )
        
        if len(chain) == 0:
            return True, None, []
        
        self._logger.debug(f"Checking {len(chain)} guards for wallet={context.wallet_id}")
        
        result = await chain.check(context)
        passed = result.metadata.get("passed_guards", []) if result.metadata else []
        
        if not result.allowed:
            self._logger.warning(f"Payment BLOCKED by guard: {result.reason} (Wallet: {context.wallet_id})")
        else:
            self._logger.debug(f"Guards passed: {passed}")
            
        return result.allowed, result.reason, passed
    
    async def record_spending(
        self,
        wallet_id: str,
        wallet_set_id: str | None,
        amount: Decimal,
        recipient: str,
        purpose: str | None,
    ) -> None:
        """Record spending in all relevant guards."""
        chain = await self.get_guard_chain(wallet_id, wallet_set_id)
        
        for guard in chain:
            # BudgetGuard uses record_spending
            if hasattr(guard, "record_spending"):
                await guard.record_spending(
                    amount=amount,
                    wallet_id=wallet_id,
                    recipient=recipient,
                    purpose=purpose,
                )
            # RateLimitGuard uses record_payment (now async with wallet_id)
            if hasattr(guard, "record_payment"):
                await guard.record_payment(wallet_id)
    
    async def clear_wallet_guards(self, wallet_id: str) -> None:
        """Clear all guards for a wallet."""
        key = self._make_key("wallet", wallet_id)
        await self._storage.delete(self.COLLECTION, key)
    
    async def clear_wallet_set_guards(self, wallet_set_id: str) -> None:
        """Clear all guards for a wallet set."""
        key = self._make_key("wallet_set", wallet_set_id)
        await self._storage.delete(self.COLLECTION, key)
