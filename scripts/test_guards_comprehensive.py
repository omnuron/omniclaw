import asyncio
import sys
from unittest.mock import MagicMock
sys.modules["circle"] = MagicMock()
sys.modules["circle.web3"] = MagicMock()

from decimal import Decimal
from omniagentpay.guards.budget import BudgetGuard
from omniagentpay.guards.rate_limit import RateLimitGuard
from omniagentpay.storage.memory import InMemoryStorage
from omniagentpay.guards.base import PaymentContext

async def test_budget_atomic():
    print("--- Testing BudgetGuard Atomic Multi-Limit ---")
    storage = InMemoryStorage()
    guard = BudgetGuard(
        daily_limit=Decimal("100"),
        hourly_limit=Decimal("10"),
        total_limit=Decimal("1000"),
        name="bg"
    )
    guard.bind_storage(storage)
    
    ctx = PaymentContext("w1", "r1", Decimal("5"), "test")
    
    # 1. Reserve 5 (Passes all)
    token = await guard.reserve(ctx)
    print("Reserve 5:", token)
    assert token is not None
    await guard.commit(token)
    
    # 2. Reserve 6 (Total=11, Daily=11, Hourly=11 > 10 Limit)
    # Should FAIL on Hourly limit
    try:
        await guard.reserve(PaymentContext("w1", "r1", Decimal("6"), "test"))
        print("FAIL: Should have blocked 6")
        exit(1)
    except ValueError as e:
        print("Blocked correctly:", e)
        assert "Hourly" in str(e)

async def test_rate_limit_atomic():
    print("\n--- Testing RateLimitGuard Atomic ---")
    storage = InMemoryStorage()
    guard = RateLimitGuard(max_per_minute=2, name="rl")
    guard.bind_storage(storage)
    
    ctx = PaymentContext("w1", "r1", Decimal("1"), "test")
    
    # 1. Reserve 1
    t1 = await guard.reserve(ctx)
    print("Reserve 1:", t1)
    
    # 2. Reserve 2
    t2 = await guard.reserve(ctx)
    print("Reserve 2:", t2)
    
    # 3. Reserve 3 (Should Block)
    try:
        await guard.reserve(ctx)
        print("FAIL: Should have blocked 3")
        exit(1)
    except ValueError as e:
        print("Blocked correctly:", e)
        assert "minute" in str(e)
        
    print("✅ All Rate Limit tests passed")

if __name__ == "__main__":
    asyncio.run(test_budget_atomic())
    asyncio.run(test_rate_limit_atomic())
