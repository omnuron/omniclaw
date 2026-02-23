"""
BudgetGuard - Limits total spending over time periods.

Tracks cumulative spending and enforces daily/hourly/total budgets.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from omniclaw.guards.base import Guard, GuardResult, PaymentContext
from omniclaw.storage import StorageBackend


class BudgetGuard(Guard):
    """
    Guard that enforces spending budgets over time periods.

    Tracks all payments and blocks when limits are exceeded.
    """

    def __init__(
        self,
        daily_limit: Decimal | None = None,
        hourly_limit: Decimal | None = None,
        total_limit: Decimal | None = None,
        name: str = "budget",
        storage: StorageBackend | None = None,
    ) -> None:
        """
        Initialize BudgetGuard.

        At least one limit must be specified.

        Args:
            daily_limit: Maximum spending per 24-hour rolling period
            hourly_limit: Maximum spending per 1-hour rolling period
            total_limit: Maximum cumulative spending (no reset)
            name: Guard name for identification
            storage: Optional storage backend (if not provided, must be bound later)
        """
        if all(limit is None for limit in [daily_limit, hourly_limit, total_limit]):
            raise ValueError("At least one limit must be specified")

        self._name = name
        self._daily_limit = daily_limit
        self._hourly_limit = hourly_limit
        self._total_limit = total_limit
        self._storage = storage

    def bind_storage(self, storage: StorageBackend) -> None:
        """Bind storage backend to guard."""
        self._storage = storage

    @property
    def name(self) -> str:
        return self._name

    async def _get_spent(self, wallet_id: str, window: timedelta | None = None) -> Decimal:
        """Get spending from storage."""
        if not self._storage:
            # Fallback for tests not using storage yet, or return 0
            return Decimal("0")

        # We query the ledger or a specific budget collection
        # For simplicity and robustness, we query the LEDGER (truth)
        # Assuming we can query the associated StorageLedger via shared storage



        # Get all successful payments
        # In a real optimized system, we'd use aggregation queries, but
        # StorageBackend is simple CRUD. So we fetch recent records.

        # If total limit, we need everything. If rolling window, only recent.
        # But since we can't query by date easily in simple KV/Doc stores without indexing,
        # we might rely on a dedicated "budget_tracking" collection updated on spend.

        # STRATEGY: Use a dedicated "spending_summary" record in storage
        # Key: `budget:{wallet_id}:{guard_name}`
        # Data: { "total": "100.00", "history": [ {ts, amount}... ] }
        # This keeps it self-contained in the guard logic.

        key = f"budget:{wallet_id}:{self.name}"
        data = await self._storage.get("guard_state", key)
        if not data:
            return Decimal("0")

        history = data.get("history", [])
        total_spent = Decimal(str(data.get("total", "0")))

        if window is None:
            return total_spent

        # Calculate window spending
        cutoff = datetime.now() - window
        window_spent = Decimal("0")

        for record in history:
            ts = datetime.fromisoformat(record["ts"])
            if ts > cutoff:
                window_spent += Decimal(str(record["amount"]))

        return window_spent

    async def get_hourly_spent(self, wallet_id: str) -> Decimal:
        """Get amount spent in last hour."""
        return await self._get_spent(wallet_id, timedelta(hours=1))

    async def get_daily_spent(self, wallet_id: str) -> Decimal:
        """Get amount spent in last 24 hours."""
        return await self._get_spent(wallet_id, timedelta(days=1))



    async def check(self, context: PaymentContext) -> GuardResult:
        """Check if payment fits within budget limits."""
        amount = context.amount
        wallet_id = context.wallet_id

        # Check hourly limit
        if self._hourly_limit is not None:
            hourly_spent = await self.get_hourly_spent(wallet_id)
            if hourly_spent + amount > self._hourly_limit:
                return GuardResult(
                    allowed=False,
                    reason=(
                        f"Hourly limit exceeded. "
                        f"Spent: {hourly_spent}, Limit: {self._hourly_limit}, "
                        f"Requested: {amount}"
                    ),
                    guard_name=self.name,
                    metadata={
                        "limit_type": "hourly",
                        "current_spent": str(hourly_spent),
                        "limit": str(self._hourly_limit),
                        "requested": str(amount),
                    },
                )

        # Check daily limit
        if self._daily_limit is not None:
            daily_spent = await self.get_daily_spent(wallet_id)
            if daily_spent + amount > self._daily_limit:
                return GuardResult(
                    allowed=False,
                    reason=(
                        f"Daily limit exceeded. "
                        f"Spent today: {daily_spent}, Limit: {self._daily_limit}, "
                        f"Requested: {amount}"
                    ),
                    guard_name=self.name,
                    metadata={
                        "limit_type": "daily",
                        "current_spent": str(daily_spent),
                        "limit": str(self._daily_limit),
                        "requested": str(amount),
                    },
                )

        # Check total limit
        if self._total_limit is not None:
            total_spent = await self.get_total_spent(wallet_id)
            if total_spent + amount > self._total_limit:
                return GuardResult(
                    allowed=False,
                    reason=(
                        f"Total limit exceeded. "
                        f"Total spent: {total_spent}, Limit: {self._total_limit}, "
                        f"Requested: {amount}"
                    ),
                    guard_name=self.name,
                    metadata={
                        "limit_type": "total",
                        "current_spent": str(total_spent),
                        "limit": str(self._total_limit),
                        "requested": str(amount),
                    },
                )

        remaining = {}
        if self._hourly_limit:
            remaining["hourly"] = self._hourly_limit - await self.get_hourly_spent(wallet_id)
        if self._daily_limit:
            remaining["daily"] = self._daily_limit - await self.get_daily_spent(wallet_id)

        return GuardResult(
            allowed=True,
            guard_name=self.name,
            metadata={"remaining": remaining},
        )

    def _get_period_keys(self, wallet_id: str, ts: datetime) -> dict[str, str]:
        """Get keys for time periods based on timestamp."""
        keys = {}
        if self._total_limit is not None:
            keys["total"] = f"budget:{wallet_id}:{self.name}:total"

        if self._daily_limit is not None:
            # YYYYMMDD
            day_str = ts.strftime("%Y%m%d")
            keys["daily"] = f"budget:{wallet_id}:{self.name}:daily:{day_str}"

        if self._hourly_limit is not None:
            # YYYYMMDDHH
            hour_str = ts.strftime("%Y%m%d%H")
            keys["hourly"] = f"budget:{wallet_id}:{self.name}:hourly:{hour_str}"

        return keys

    async def reserve(self, context: PaymentContext) -> str | None:
        """Atomic reservation for all configured limits."""
        if not self._storage:
            return None

        amount = context.amount
        wallet_id = context.wallet_id
        now = datetime.now()

        # 1. Identify all active keys
        period_keys = self._get_period_keys(wallet_id, now)
        if not period_keys:
            return None  # No limits configured

        reserved_keys: list[str] = []

        try:
            # 2. Iterate and Reserve each
            for limit_type, key_base in period_keys.items():
                key_reserved = f"{key_base}:reserved"
                key_main = key_base
                limit = getattr(self, f"_{limit_type}_limit")

                # Optimistic Increment Reserved
                await self._storage.atomic_add("guard_state", key_reserved, str(amount))
                reserved_keys.append(key_reserved)

                # Fetch Check
                main_data = await self._storage.get("guard_state", key_main)
                res_data = await self._storage.get("guard_state", key_reserved)

                def _parse_val(d: Any) -> Decimal:
                    if d is None:
                        return Decimal("0")
                    if isinstance(d, dict):
                        return Decimal(str(d.get("value", "0")))
                    return Decimal(str(d))

                current_main = _parse_val(main_data)
                current_res = _parse_val(res_data)

                if current_main + current_res > limit:
                    raise ValueError(
                        f"{limit_type.capitalize()} budget limit exceeded. Limit: {limit}"
                    )

        except Exception:
            # Rollback ALL reserved keys
            for rk in reserved_keys:
                await self._storage.atomic_add("guard_state", rk, str(-amount))
            raise

        # Token = JSON string with context to reconstruct keys
        import json

        token_data = {"v": 2, "w": wallet_id, "a": str(amount), "ts": now.isoformat()}
        return json.dumps(token_data)

    async def commit(self, token: str | None) -> None:
        if not token or not self._storage:
            return
        import json

        try:
            data = json.loads(token)
            if data.get("v") != 2:
                return

            amount = Decimal(data["a"])
            wallet_id = data["w"]
            ts = datetime.fromisoformat(data["ts"])

            # Reconstruct Keys using ORIGINAL timestamp
            # This ensures we commit to the bucket we reserved in
            period_keys = self._get_period_keys(wallet_id, ts)

            for key_base in period_keys.values():
                key_reserved = f"{key_base}:reserved"

                # Move Reserved -> Main
                await self._storage.atomic_add("guard_state", key_base, str(amount))
                await self._storage.atomic_add("guard_state", key_reserved, str(-amount))

        except Exception:
            pass  # Best effort commit? Or log failure.

    async def release(self, token: str | None) -> None:
        if not token or not self._storage:
            return
        import json

        try:
            data = json.loads(token)
            if data.get("v") != 2:
                return

            amount = Decimal(data["a"])
            wallet_id = data["w"]
            ts = datetime.fromisoformat(data["ts"])

            period_keys = self._get_period_keys(wallet_id, ts)

            for key_base in period_keys.values():
                key_reserved = f"{key_base}:reserved"
                await self._storage.atomic_add("guard_state", key_reserved, str(-amount))

        except Exception:
            pass

    # Legacy support / Read-only helpers
    async def get_total_spent(self, wallet_id: str) -> Decimal:
        """Get total amount spent."""
        if not self._storage:
            return Decimal("0")
        key = f"budget:{wallet_id}:{self.name}:total"
        data = await self._storage.get("guard_state", key)
        if isinstance(data, dict):
            return Decimal(str(data.get("value", "0")))
        return Decimal(str(data) if data else "0")

    def reset(self) -> None:
        pass
