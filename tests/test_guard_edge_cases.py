"""
Tests for guard edge cases and boundary conditions.
"""

from decimal import Decimal

import pytest

from omniclaw.guards.base import PaymentContext
from omniclaw.guards.budget import BudgetGuard
from omniclaw.guards.single_tx import SingleTxGuard
from omniclaw.storage.memory import InMemoryStorage


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
    guard = BudgetGuard(daily_limit=Decimal("100.00"), name="budget", storage=InMemoryStorage())
    mock_context.amount = Decimal("100.00")

    # Reserve should succeed (100 <= 100)
    token = await guard.reserve(mock_context)
    assert token is not None


@pytest.mark.asyncio
async def test_budget_exceeds_by_smallest_unit(mock_context):
    """Test payment exceeding budget by 0.01."""
    storage = InMemoryStorage()
    guard = BudgetGuard(daily_limit=Decimal("100.00"), name="budget", storage=storage)
    mock_context.amount = Decimal("100.01")

    # Reserve should fail by raising ValueError
    with pytest.raises(ValueError, match="budget limit exceeded"):
        await guard.reserve(mock_context)

    guard_state = await storage.query("guard_state")
    assert not [entry for entry in guard_state if entry["_key"].endswith(":reserved")]


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
    guard = BudgetGuard(daily_limit=Decimal("100.00"), name="budget", storage=InMemoryStorage())

    mock_context.amount = Decimal("-10.00")

    token = await guard.reserve(mock_context)
    assert token is not None


@pytest.mark.asyncio
async def test_zero_amount_budget(mock_context):
    """Test zero amount payment impacting budget."""
    guard = BudgetGuard(daily_limit=Decimal("100.00"), name="budget", storage=InMemoryStorage())

    mock_context.amount = Decimal("0")

    token = await guard.reserve(mock_context)
    assert token is not None
