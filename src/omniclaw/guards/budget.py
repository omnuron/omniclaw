"""
BudgetGuard - Limits total spending over time periods.

Tracks cumulative spending and enforces daily/hourly/total budgets.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from time import monotonic
from typing import Any

from omniclaw.events import event_emitter
from omniclaw.guards.base import Guard, GuardResult, PaymentContext
from omniclaw.storage import StorageBackend

logger = logging.getLogger(__name__)


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
            daily_limit: Maximum spending per calendar day bucket
            hourly_limit: Maximum spending per calendar hour bucket
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
        """Get committed spending from the active budget counter."""
        if not self._storage:
            return Decimal("0")

        if window == timedelta(hours=1):
            return await self._get_period_used(wallet_id, "hourly", include_reserved=False)
        if window == timedelta(days=1):
            return await self._get_period_used(wallet_id, "daily", include_reserved=False)
        return await self._get_period_used(wallet_id, "total", include_reserved=False)

    async def get_hourly_spent(self, wallet_id: str) -> Decimal:
        """Get amount spent in the current calendar hour bucket."""
        return await self._get_spent(wallet_id, timedelta(hours=1))

    async def get_daily_spent(self, wallet_id: str) -> Decimal:
        """Get amount spent in the current calendar day bucket."""
        return await self._get_spent(wallet_id, timedelta(days=1))

    async def check(self, context: PaymentContext) -> GuardResult:
        """Check if payment fits within budget limits."""
        amount = context.amount
        wallet_id = context.wallet_id

        # Check hourly limit
        if self._hourly_limit is not None:
            hourly_spent = await self._get_period_used(wallet_id, "hourly")
            if hourly_spent + amount > self._hourly_limit:
                event_emitter.emit_background(
                    "guard.budget_exceeded", wallet_id, payload={"amount": str(amount)}
                )
                event_emitter.emit_background(
                    "payment.guard_evaluated", wallet_id, payload={"result": "FAIL"}
                )
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
            daily_spent = await self._get_period_used(wallet_id, "daily")
            if daily_spent + amount > self._daily_limit:
                event_emitter.emit_background(
                    "guard.budget_exceeded", wallet_id, payload={"amount": str(amount)}
                )
                event_emitter.emit_background(
                    "payment.guard_evaluated", wallet_id, payload={"result": "FAIL"}
                )
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
            total_spent = await self._get_period_used(wallet_id, "total")
            if total_spent + amount > self._total_limit:
                event_emitter.emit_background(
                    "guard.budget_exceeded", wallet_id, payload={"amount": str(amount)}
                )
                event_emitter.emit_background(
                    "payment.guard_evaluated", wallet_id, payload={"result": "FAIL"}
                )
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
        if self._hourly_limit is not None:
            hourly = await self._get_period_used(wallet_id, "hourly")
            remaining["hourly"] = self._hourly_limit - hourly
            if remaining["hourly"] < self._hourly_limit * Decimal("0.2"):
                event_emitter.emit_background(
                    "guard.budget_limit_approaching",
                    wallet_id,
                    payload={"remaining": str(remaining["hourly"])},
                )
        if self._daily_limit is not None:
            daily = await self._get_period_used(wallet_id, "daily")
            remaining["daily"] = self._daily_limit - daily
            if remaining["daily"] < self._daily_limit * Decimal("0.2"):
                event_emitter.emit_background(
                    "guard.budget_limit_approaching",
                    wallet_id,
                    payload={"remaining": str(remaining["daily"])},
                )

        event_emitter.emit_background(
            "payment.guard_evaluated", wallet_id, payload={"result": "PASS"}
        )
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

    def _parse_storage_decimal(self, data: Any) -> Decimal:
        if data is None:
            return Decimal("0")
        if isinstance(data, dict):
            return Decimal(str(data.get("value", "0")))
        return Decimal(str(data))

    async def _get_period_used(
        self,
        wallet_id: str,
        limit_type: str,
        *,
        include_reserved: bool = True,
    ) -> Decimal:
        """Read the current committed plus in-flight amount for a limit type."""
        if not self._storage:
            return Decimal("0")
        period_keys = self._get_period_keys(wallet_id, datetime.now())
        key_base = period_keys.get(limit_type)
        if not key_base:
            return Decimal("0")

        main_data = await self._storage.get("guard_state", key_base)
        total = self._parse_storage_decimal(main_data)
        if include_reserved:
            reserved_data = await self._storage.get("guard_state", f"{key_base}:reserved")
            total += self._parse_storage_decimal(reserved_data)
        return total

    def _reservation_key(self, reservation_id: str) -> str:
        return f"budget_reservation:{self.name}:{reservation_id}"

    def _limit_type_from_reservation_result(
        self,
        result: str,
        period_keys: dict[str, str],
    ) -> str:
        suffix = result.split(":", 1)[1] if ":" in result else ""
        period_values = list(period_keys.values())
        if suffix.isdigit():
            index = int(suffix) - 1
            if 0 <= index < len(period_values):
                suffix = period_values[index]

        for limit_type, key in period_keys.items():
            if key == suffix:
                return limit_type
        return "budget"

    async def _load_reservation(self, token: str) -> tuple[str, dict[str, Any]]:
        import json

        data = json.loads(token)
        if data.get("v") != 3:
            raise ValueError("Unsupported budget reservation token")

        reservation_id = str(data["id"])
        key = self._reservation_key(reservation_id)
        if not self._storage:
            raise ValueError("Budget guard storage is not configured")

        record = await self._storage.get("guard_state", key)
        if not record:
            raise ValueError("Budget reservation record is missing")
        return key, record

    async def _acquire_period_locks(
        self,
        period_keys: dict[str, str],
        *,
        ttl: int = 30,
        timeout: float = 30.0,
    ) -> list[tuple[str, str]]:
        if not self._storage:
            return []

        lock_keys = [f"guard:budget:{key}" for key in sorted(period_keys.values())]
        deadline = monotonic() + timeout

        while True:
            acquired: list[tuple[str, str]] = []
            try:
                for lock_key in lock_keys:
                    token = await self._storage.acquire_lock(lock_key, ttl=ttl)
                    if token is None:
                        await self._release_period_locks(acquired)
                        break
                    acquired.append((lock_key, token))
                else:
                    return acquired
            except BaseException:
                await self._release_period_locks(acquired)
                raise

            if monotonic() >= deadline:
                raise TimeoutError("Timed out acquiring budget reservation locks")
            await asyncio.sleep(0.005)

    async def _release_period_locks(self, locks: list[tuple[str, str]]) -> None:
        if not self._storage:
            return
        for lock_key, token in reversed(locks):
            try:
                released = await self._storage.release_lock(lock_key, token)
                if not released:
                    logger.warning(
                        "Budget lock %s was not released; ownership may be lost", lock_key
                    )
            except Exception:
                logger.warning("Failed to release budget lock %s", lock_key, exc_info=True)

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
        locks: list[tuple[str, str]] = []
        reservation_id = str(uuid.uuid4())
        reservation_key = self._reservation_key(reservation_id)
        reservation_record = {
            "id": reservation_id,
            "status": "reserved",
            "wallet_id": wallet_id,
            "amount": str(amount),
            "period_keys": list(period_keys.values()),
            "created_at": now.isoformat(),
        }
        storage_create = getattr(self._storage, "create_budget_reservation", None)

        if storage_create:
            period_limits = {
                key_base: str(getattr(self, f"_{limit_type}_limit"))
                for limit_type, key_base in period_keys.items()
            }
            result = await storage_create(
                "guard_state",
                reservation_key,
                period_limits,
                str(amount),
                reservation_record,
            )
            if result == "reserved":
                import json

                return json.dumps({"v": 3, "id": reservation_id})
            if result.startswith("limit_exceeded"):
                limit_type = self._limit_type_from_reservation_result(result, period_keys)
                limit = getattr(self, f"_{limit_type}_limit", "unknown")
                raise ValueError(f"{limit_type.capitalize()} budget limit exceeded. Limit: {limit}")
            raise RuntimeError(f"Budget reservation failed closed: {result}")

        try:
            locks = await self._acquire_period_locks(period_keys)

            # 2. Check every active limit before mutating reservation state.
            for limit_type, key_base in period_keys.items():
                key_reserved = f"{key_base}:reserved"
                key_main = key_base
                limit = getattr(self, f"_{limit_type}_limit")

                main_data = await self._storage.get("guard_state", key_main)
                res_data = await self._storage.get("guard_state", key_reserved)

                current_main = self._parse_storage_decimal(main_data)
                current_res = self._parse_storage_decimal(res_data)

                if limit is not None and current_main + current_res + amount > limit:
                    raise ValueError(
                        f"{limit_type.capitalize()} budget limit exceeded. Limit: {limit}"
                    )

            # 3. Reserve all active limits while holding storage-backed locks.
            for key_base in period_keys.values():
                key_reserved = f"{key_base}:reserved"
                await self._storage.atomic_add("guard_state", key_reserved, str(amount))
                reserved_keys.append(key_reserved)

            await self._storage.save("guard_state", reservation_key, reservation_record)

        except Exception:
            # Rollback ALL reserved keys
            for rk in reserved_keys:
                await self._storage.atomic_add("guard_state", rk, str(-amount))
            raise
        finally:
            await self._release_period_locks(locks)

        # Token = JSON string with context to reconstruct keys
        import json

        token_data = {"v": 3, "id": reservation_id}
        return json.dumps(token_data)

    async def commit(self, token: str | None) -> None:
        if not token or not self._storage:
            return

        wallet_id = "<unknown>"
        try:
            reservation_key, record = await self._load_reservation(token)
            status = record.get("status")
            if status != "reserved":
                return

            amount = Decimal(str(record["amount"]))
            wallet_id = str(record["wallet_id"])
            period_key_values = [str(key) for key in record.get("period_keys", [])]
            committed_at = datetime.now().isoformat()

            storage_commit = getattr(self._storage, "commit_budget_reservation", None)
            if storage_commit:
                result = await storage_commit(
                    "guard_state",
                    reservation_key,
                    period_key_values,
                    str(amount),
                    committed_at,
                )
                if result in {"committed", "released"}:
                    return
                if result == "missing":
                    raise ValueError("Budget reservation record is missing")

            period_keys = {str(index): key for index, key in enumerate(period_key_values)}
            locks = await self._acquire_period_locks(period_keys)

            try:
                current = await self._storage.get("guard_state", reservation_key)
                if not current:
                    raise ValueError("Budget reservation record is missing")
                if current.get("status") != "reserved":
                    return

                for key_base in period_key_values:
                    key_reserved = f"{key_base}:reserved"

                    # Move Reserved -> Main
                    await self._storage.atomic_add("guard_state", key_base, str(amount))
                    await self._storage.atomic_add("guard_state", key_reserved, str(-amount))

                await self._storage.update(
                    "guard_state",
                    reservation_key,
                    {"status": "committed", "committed_at": committed_at},
                )
            finally:
                await self._release_period_locks(locks)

        except Exception as exc:
            logger.error(
                f"BudgetGuard.commit() failed for wallet {wallet_id}: {exc}. "
                f"Budget tracking may be inaccurate — manual reconciliation recommended.",
                exc_info=True,
            )
            raise RuntimeError(
                f"BudgetGuard commit failed for wallet {wallet_id}; refusing to continue silently."
            ) from exc

    async def release(self, token: str | None) -> None:
        if not token or not self._storage:
            return

        wallet_id = "<unknown>"
        try:
            reservation_key, record = await self._load_reservation(token)
            status = record.get("status")
            if status != "reserved":
                return

            amount = Decimal(str(record["amount"]))
            wallet_id = str(record["wallet_id"])
            period_key_values = [str(key) for key in record.get("period_keys", [])]
            released_at = datetime.now().isoformat()

            storage_release = getattr(self._storage, "release_budget_reservation", None)
            if storage_release:
                result = await storage_release(
                    "guard_state",
                    reservation_key,
                    period_key_values,
                    str(amount),
                    released_at,
                )
                if result in {"released", "committed"}:
                    return
                if result == "missing":
                    raise ValueError("Budget reservation record is missing")

            period_keys = {str(index): key for index, key in enumerate(period_key_values)}
            locks = await self._acquire_period_locks(period_keys)

            try:
                current = await self._storage.get("guard_state", reservation_key)
                if not current:
                    raise ValueError("Budget reservation record is missing")
                if current.get("status") != "reserved":
                    return

                for key_base in period_key_values:
                    key_reserved = f"{key_base}:reserved"
                    await self._storage.atomic_add("guard_state", key_reserved, str(-amount))

                await self._storage.update(
                    "guard_state",
                    reservation_key,
                    {"status": "released", "released_at": released_at},
                )
            finally:
                await self._release_period_locks(locks)

        except Exception as exc:
            logger.error(
                f"BudgetGuard.release() failed for wallet {wallet_id}: {exc}. "
                f"Reserved budget may be permanently locked — manual reconciliation recommended.",
                exc_info=True,
            )
            raise RuntimeError(
                f"BudgetGuard release failed for wallet {wallet_id}; refusing to continue silently."
            ) from exc

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
