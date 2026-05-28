import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from omniclaw.client import OmniClaw
from omniclaw.core.types import Network, PaymentResult, PaymentStatus
from omniclaw.guards.base import PaymentContext
from omniclaw.guards.budget import BudgetGuard
from omniclaw.storage.memory import InMemoryStorage


class YieldingInMemoryStorage(InMemoryStorage):
    """In-memory storage that yields around operations to expose async races."""

    async def atomic_add(self, collection: str, key: str, amount: str) -> str:
        await asyncio.sleep(0)
        return await super().atomic_add(collection, key, amount)

    async def get(self, collection: str, key: str) -> dict[str, Any] | None:
        await asyncio.sleep(0)
        return await super().get(collection, key)


@pytest.fixture
def client_with_storage():
    """Create a client with real in-memory storage for concurrency testing."""
    # We use real storage to test the locking/atomic mechanisms
    storage = InMemoryStorage()
    client = OmniClaw(
        network=Network.ARC_TESTNET, circle_api_key="mock_key", entity_secret="mock_secret"
    )
    # Inject the storage into the guard manager
    client.guards._storage = storage
    # We also need to mock the internal wallet service to not fail on "network" calls
    # but still allow the high-level flow to proceed
    client._wallet_service = MagicMock()
    # Mock balance check to always succeed
    balance_mock = MagicMock()
    balance_mock.amount = Decimal("1000000.00")
    client._wallet_service.get_usdc_balance.return_value = balance_mock

    # Mock transfer to be slow to simulate race window?
    # Actually, the guard check happens BEFORE transfer.
    # The atomic reservation is what we care about.

    async def mock_transfer(*args, **kwargs):
        return MagicMock(success=True, transaction=MagicMock(id="tx-1", state="COMPLETE"))

    client._wallet_service.transfer = AsyncMock(side_effect=mock_transfer)

    # Mock Router to just return success
    async def mock_pay(*args, **kwargs):
        # Simulate some latency
        await asyncio.sleep(0.01)
        return PaymentResult(
            success=True,
            transaction_id="tx-1",
            blockchain_tx="0x...",
            amount=kwargs.get("amount", Decimal("0")),
            recipient=kwargs.get("recipient", "0x..."),
            method="transfer",
            status=PaymentStatus.COMPLETED,
        )

    # We patch the router's pay method bound to this client
    # Using _router as the public property is not available
    client._router.pay = mock_pay

    return client


@pytest.mark.asyncio
async def test_concurrent_budget_updates(client_with_storage):
    """Test that concurrent payments correctly enforce budget limits."""
    # Set a budget of $100
    budget_guard = BudgetGuard(daily_limit=Decimal("100.00"), name="concurrent_budget")
    await client_with_storage.guards.add_guard("wallet-123", budget_guard)

    # Launch 20 concurrent payments of $6 each.
    # Total attempted = $120.
    # Expected: 16 succeed ($96), 4 fail (Total > $100).
    # OR 17 succeed ($102) if race condition exists (FAILURE).

    async def make_payment():
        return await client_with_storage.pay(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("6.00"),
        )

    tasks = [make_payment() for _ in range(20)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success_count = sum(1 for r in results if isinstance(r, PaymentResult) and r.success)
    failed_count = sum(1 for r in results if isinstance(r, PaymentResult) and not r.success)
    exception_count = sum(1 for r in results if isinstance(r, Exception))

    # Check that we didn't overspend
    # $6 * 16 = $96. $6 * 17 = $102 (Over budget)
    # So max success count should be 16.

    print(f"Success: {success_count}, Failed: {failed_count}, Exceptions: {exception_count}")

    assert success_count <= 16, f"Budget exceeded! {success_count} payments succeeded."
    assert success_count + failed_count + exception_count == 20


@pytest.mark.asyncio
async def test_budget_guard_concurrent_reservations_do_not_under_authorize_with_async_storage():
    """Concurrent reservations should admit capacity instead of all rolling back."""
    storage = YieldingInMemoryStorage()
    guard = BudgetGuard(total_limit=Decimal("100.00"), name="concurrent_budget", storage=storage)

    async def reserve_and_commit(index: int) -> str:
        context = PaymentContext(
            wallet_id="wallet-concurrent",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("6.00"),
            purpose=f"concurrent-{index}",
        )
        try:
            token = await guard.reserve(context)
        except ValueError:
            return "rejected"

        await asyncio.sleep(0.01)
        await guard.commit(token)
        return "success"

    results = await asyncio.gather(*(reserve_and_commit(i) for i in range(20)))

    assert results.count("success") == 16
    assert results.count("rejected") == 4

    total = await storage.get("guard_state", "budget:wallet-concurrent:concurrent_budget:total")
    reserved = await storage.get(
        "guard_state", "budget:wallet-concurrent:concurrent_budget:total:reserved"
    )
    assert total == "96.00"
    assert reserved == "0.00"
