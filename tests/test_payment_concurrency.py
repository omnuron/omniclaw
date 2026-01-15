
import pytest
import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock

from omniagentpay.client import OmniAgentPay
from omniagentpay.core.types import Network, PaymentResult, PaymentStatus
from omniagentpay.guards.budget import BudgetGuard
from omniagentpay.storage.memory import InMemoryStorage

@pytest.fixture
def client_with_storage():
    """Create a client with real in-memory storage for concurrency testing."""
    # We use real storage to test the locking/atomic mechanisms
    storage = InMemoryStorage()
    client = OmniAgentPay(
        network=Network.ARC_TESTNET,
        circle_api_key="mock_key",
        entity_secret="mock_secret"
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
            status=PaymentStatus.COMPLETED
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
            amount=Decimal("6.00")
        )
        
    tasks = [make_payment() for _ in range(20)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success_count = sum(1 for r in results if isinstance(r, PaymentResult) and r.success)
    failed_count = sum(1 for r in results if isinstance(r, PaymentResult) and not r.success)
    
    # Check that we didn't overspend
    # $6 * 16 = $96. $6 * 17 = $102 (Over budget)
    # So max success count should be 16.
    
    print(f"Success: {success_count}, Failed: {failed_count}")
    
    assert success_count <= 16, f"Budget exceeded! {success_count} payments succeeded."
    assert success_count + failed_count == 20
