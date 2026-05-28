from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from omniclaw.guards.base import PaymentContext
from omniclaw.guards.budget import BudgetGuard
from omniclaw.storage.redis import RedisStorage


async def _redis_or_skip() -> RedisStorage:
    storage = RedisStorage(prefix=f"omniclaw-test-{uuid.uuid4()}")
    if not await storage.health_check():
        pytest.skip("Redis server is not available")
    return storage


@pytest.mark.asyncio
async def test_redis_numeric_counters_are_queryable():
    storage = await _redis_or_skip()
    try:
        await storage.atomic_add("guard_state", "budget:w1:budget:total", "10")

        value = await storage.get("guard_state", "budget:w1:budget:total")
        rows = await storage.query("guard_state")

        assert value == {"value": 10}
        assert any(row["_key"] == "budget:w1:budget:total" for row in rows)
    finally:
        await storage.clear("guard_state")
        await storage.close()


@pytest.mark.asyncio
async def test_redis_budget_reservation_lifecycle_is_single_use():
    storage = await _redis_or_skip()
    try:
        guard = BudgetGuard(total_limit=Decimal("100.00"), storage=storage)
        context = PaymentContext(wallet_id="wallet-redis", recipient="0x123", amount=Decimal("10.00"))

        token = await guard.reserve(context)
        await guard.commit(token)
        await guard.commit(token)

        total = await storage.get("guard_state", "budget:wallet-redis:budget:total")
        reserved = await storage.get("guard_state", "budget:wallet-redis:budget:total:reserved")
        assert total == {"value": 10}
        assert reserved == {"value": 0}
    finally:
        await storage.clear("guard_state")
        await storage.close()


@pytest.mark.asyncio
async def test_redis_budget_reservation_allows_exact_decimal_boundary():
    storage = await _redis_or_skip()
    try:
        guard = BudgetGuard(total_limit=Decimal("0.30"), storage=storage)
        first = PaymentContext(wallet_id="wallet-redis", recipient="0x123", amount=Decimal("0.10"))
        second = PaymentContext(wallet_id="wallet-redis", recipient="0x123", amount=Decimal("0.20"))

        token = await guard.reserve(first)
        await guard.commit(token)
        token = await guard.reserve(second)
        await guard.commit(token)

        total = await storage.get("guard_state", "budget:wallet-redis:budget:total")
        assert total == {"value": 0.3}
    finally:
        await storage.clear("guard_state")
        await storage.close()
