"""
Tests for guard edge cases and boundary conditions.
"""
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock

from omniagentpay.guards.budget import BudgetGuard
from omniagentpay.guards.single_tx import SingleTxGuard
from omniagentpay.guards.base import PaymentContext, GuardResult
from omniagentpay.core.types import Network

@pytest.fixture
def mock_context():
    return PaymentContext(
        wallet_id="wallet-123",
        recipient="0x...",
        amount=Decimal("0"),
    )

@pytest.mark.asyncio
async def test_budget_exact_limit(mock_context):
    """Test payment exactly equal to the budget limit."""
    guard = BudgetGuard(daily_limit=Decimal("100.00"), name="budget")
    guard._storage = MagicMock()
    
    # Mock get to return 100.00 for reserved key check
    async def mock_get(collection, key):
        if key.endswith(":reserved"):
            return "100.00"
        return None
    
    guard._storage.get = AsyncMock(side_effect=mock_get)
    guard._storage.atomic_add = AsyncMock(return_value=Decimal("100.00")) 
    
    mock_context.amount = Decimal("100.00")
    
    # Reserve should succeed (100 <= 100)
    token = await guard.reserve(mock_context)
    assert token is not None


@pytest.mark.asyncio
async def test_budget_exceeds_by_smallest_unit(mock_context):
    """Test payment exceeding budget by 0.01."""
    guard = BudgetGuard(daily_limit=Decimal("100.00"), name="budget")
    guard._storage = MagicMock()
    
    async def mock_get(collection, key):
        if key.endswith(":reserved"):
            return "100.01" # Simulating the result of atomic_add
        return None
        
    guard._storage.get = AsyncMock(side_effect=mock_get)
    guard._storage.atomic_add = AsyncMock(return_value=Decimal("100.01"))
    
    mock_context.amount = Decimal("100.01")
    
    # Reserve should fail by raising ValueError
    with pytest.raises(ValueError, match="budget limit exceeded"):
        await guard.reserve(mock_context)
    
    # Should revert (atomic_add negative amount)
    assert guard._storage.atomic_add.call_count == 2
    args_2 = guard._storage.atomic_add.call_args_list[1]
    # Check that second call added negative amount
    assert args_2[0][2] == str(Decimal("-100.01")) 


@pytest.mark.asyncio
async def test_single_tx_exact_limit(mock_context):
    """Test single transaction exactly at limit."""
    guard = SingleTxGuard(max_amount=Decimal("50.00"), name="limit")
    
    mock_context.amount = Decimal("50.00")
    result = await guard.check(mock_context)
    assert result.allowed is True

    mock_context.amount = Decimal("50.01")
    result = await guard.check(mock_context)
    assert result.allowed is False


@pytest.mark.asyncio
async def test_negative_amount_handling(mock_context):
    """Test guards handling negative amounts."""
    guard = BudgetGuard(daily_limit=Decimal("100.00"), name="budget")
    guard._storage = MagicMock()
    
    async def mock_get(collection, key):
        if key.endswith(":reserved"):
            return "-10.00"
        return None

    guard._storage.get = AsyncMock(side_effect=mock_get)
    guard._storage.atomic_add = AsyncMock(return_value=Decimal("-10.00"))
    
    mock_context.amount = Decimal("-10.00")
    
    token = await guard.reserve(mock_context)
    assert token is not None


@pytest.mark.asyncio
async def test_zero_amount_budget(mock_context):
    """Test zero amount payment impacting budget."""
    guard = BudgetGuard(daily_limit=Decimal("100.00"), name="budget")
    guard._storage = MagicMock()
    
    async def mock_get(collection, key):
        if key.endswith(":reserved"):
            return "50.00" # Assuming some previous usage? or just 0 + 0
        return None
        
    guard._storage.get = AsyncMock(side_effect=mock_get)
    guard._storage.atomic_add = AsyncMock(return_value=Decimal("50.00"))
    
    mock_context.amount = Decimal("0")
    
    token = await guard.reserve(mock_context)
    assert token is not None
