"""
RateLimitGuard - Limits payment frequency.

Controls how many transactions can occur within time windows.
Uses StorageBackend for persistence.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from omniclaw.guards.base import Guard, GuardResult, PaymentContext

if TYPE_CHECKING:
    from omniclaw.storage.base import StorageBackend


class RateLimitGuard(Guard):
    """
    Guard that limits payment frequency.

    Tracks payment timestamps in storage and blocks when rate limits are exceeded.
    Uses a sliding window approach.
    """

    def __init__(
        self,
        max_per_minute: int | None = None,
        max_per_hour: int | None = None,
        max_per_day: int | None = None,
        name: str = "rate_limit",
    ) -> None:
        """
        Initialize RateLimitGuard.

        At least one limit must be specified.

        Args:
            max_per_minute: Maximum payments per minute
            max_per_hour: Maximum payments per hour
            max_per_day: Maximum payments per day
            name: Guard name for identification
        """
        if all(limit is None for limit in [max_per_minute, max_per_hour, max_per_day]):
            raise ValueError("At least one rate limit must be specified")

        self._name = name
        self._max_per_minute = max_per_minute
        self._max_per_hour = max_per_hour
        self._max_per_day = max_per_day
        self._storage: StorageBackend | None = None

    def bind_storage(self, storage: StorageBackend) -> None:
        """Bind storage backend to guard."""
        self._storage = storage

    @property
    def name(self) -> str:
        return self._name

    def _get_window_keys(self, wallet_id: str, ts: datetime) -> dict[str, str]:
        """Get keys for fixed time windows."""
        keys = {}
        if self._max_per_minute is not None:
            keys["minute"] = f"ratelimit:{wallet_id}:{self.name}:minute:{ts.strftime('%Y%m%d%H%M')}"

        if self._max_per_hour is not None:
            keys["hour"] = f"ratelimit:{wallet_id}:{self.name}:hour:{ts.strftime('%Y%m%d%H')}"

        if self._max_per_day is not None:
            keys["day"] = f"ratelimit:{wallet_id}:{self.name}:day:{ts.strftime('%Y%m%d')}"

        return keys

    async def reserve(self, context: PaymentContext) -> str | None:
        """Atomic reservation."""
        if not self._storage:
            return None

        wallet_id = context.wallet_id
        now = datetime.now()

        window_keys = self._get_window_keys(wallet_id, now)
        if not window_keys:
            return None

        reserved_keys: list[str] = []

        try:
            for limit_type, key in window_keys.items():
                limit = getattr(self, f"_max_per_{limit_type}")

                # Atomic Incr
                # atomic_add returns new value as str
                new_val_str = await self._storage.atomic_add("guard_state", key, "1")
                reserved_keys.append(key)

                new_val = int(float(new_val_str))  # Handle "1.0" if Redis returns float

                if new_val > limit:
                    raise ValueError(f"Rate limit exceeded ({limit_type}). Limit: {limit}")

        except Exception:
            # Rollback
            for k in reserved_keys:
                await self._storage.atomic_add("guard_state", k, "-1")
            raise

        import json

        token = {"v": 2, "w": wallet_id, "ts": now.isoformat()}
        return json.dumps(token)

    async def commit(self, token: str | None) -> None:
        """Commit is a no-op — rate limit cost is counted on reserve, released on rollback."""
        pass

    async def release(self, token: str | None) -> None:
        if not token or not self._storage:
            return
        import json

        try:
            data = json.loads(token)
            if data.get("v") != 2:
                return
            ts = datetime.fromisoformat(data["ts"])
            wallet_id = data["w"]

            window_keys = self._get_window_keys(wallet_id, ts)
            for key in window_keys.values():
                await self._storage.atomic_add("guard_state", key, "-1")
        except Exception:
            pass

    # Legacy / Read Helpers
    async def get_minute_count(self, wallet_id: str) -> int:
        keys = self._get_window_keys(wallet_id, datetime.now())
        if "minute" not in keys:
            return 0
        return await self._get_count(keys["minute"])

    async def _get_count(self, key: str) -> int:
        if not self._storage:
            return 0
        val = await self._storage.get("guard_state", key)
        if hasattr(val, "get"):
            val = val.get("value")  # Handle dict wrapper
        return int(float(str(val))) if val else 0

    async def check(self, context: PaymentContext) -> GuardResult:
        """Check if payment would be within rate limits (non-atomic read)."""
        if not self._storage:
            return GuardResult(allowed=True, guard_name=self.name)

        wallet_id = context.wallet_id
        now = datetime.now()
        window_keys = self._get_window_keys(wallet_id, now)

        for limit_type, key in window_keys.items():
            limit = getattr(self, f"_max_per_{limit_type}")
            current = await self._get_count(key)
            if current >= limit:
                return GuardResult(
                    allowed=False,
                    reason=f"Rate limit exceeded ({limit_type}): {current}/{limit}",
                    guard_name=self.name,
                    metadata={"limit_type": limit_type, "current": current, "limit": limit},
                )

        return GuardResult(allowed=True, guard_name=self.name)

    async def record_payment(self, wallet_id: str) -> None:
        # Deprecated
        pass

    def reset(self) -> None:
        """Reset is handled via storage - use clear_wallet instead."""
        pass

    async def clear_wallet(self, wallet_id: str) -> None:
        """Clear rate limit history for a wallet."""
        if self._storage:
            await self._storage.delete("guard_state", self._make_key(wallet_id))
