"""Tests for Simulation features (Dry Run and Reservations)."""

import os
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from omniclaw.client import OmniClaw
from omniclaw.core.types import Network, PaymentMethod


@pytest.fixture
def mock_env():
    """Set up mock environment variables."""
    with patch.dict(
        os.environ,
        {
            "CIRCLE_API_KEY": "test_api_key",
            "ENTITY_SECRET": "test_secret",
        },
    ):
        yield


@pytest.fixture
def client(mock_env) -> OmniClaw:
    """Create client with mocked environment."""
    return OmniClaw(network=Network.ARC_TESTNET)


@pytest.mark.asyncio
async def test_simulation_result_fields(client):
    """Test that SimulationResult has necessary fields populated."""
    # Mock router and balance
    client._router.simulate = AsyncMock()
    sim_res_mock = AsyncMock()
    # Return a simulated result
    from omniclaw.core.types import SimulationResult
    client._router.simulate.return_value = SimulationResult(
        would_succeed=True,
        route=PaymentMethod.TRANSFER,
        estimated_fee=Decimal("0.05")
    )

    client._wallet_service.get_usdc_balance_amount = lambda wid: Decimal("100.0")

    res = await client.simulate(
        wallet_id="wallet-1",
        recipient="0xabc",
        amount=Decimal("10.0")
    )

    assert res.would_succeed is True
    assert res.recipient_type == PaymentMethod.TRANSFER.value
    assert res.estimated_fee == Decimal("0.05")
    assert res.estimated_gas == Decimal("0.05")  # Alias check
    assert res.guards_that_would_pass == []


@pytest.mark.asyncio
async def test_simulation_respects_reservations(client):
    """Test that simulation checks available balance (balance - reserved)."""
    # Setup: Balance 100, Reserved 80
    client._wallet_service.get_usdc_balance_amount = lambda wid: Decimal("100.0")
    
    # Reserve 80 immediately
    await client._reservation.reserve("wallet-1", Decimal("80.0"), "intent-1")

    # Trying to simulate 30 should fail because available is 20
    res = await client.simulate(
        wallet_id="wallet-1",
        recipient="0xabc",
        amount=Decimal("30.0")
    )

    assert res.would_succeed is False
    assert "Insufficient available balance" in res.reason


@pytest.mark.asyncio
async def test_simulation_guards_passed(client):
    """Test that simulation populates guards_that_would_pass."""
    from omniclaw.guards.single_tx import SingleTxGuard

    client._wallet_service.get_usdc_balance_amount = lambda wid: Decimal("100.0")
    client._router.simulate = AsyncMock()
    from omniclaw.core.types import SimulationResult
    client._router.simulate.return_value = SimulationResult(
        would_succeed=True,
        route=PaymentMethod.TRANSFER,
    )

    # Add a guard that will pass
    guard = SingleTxGuard(max_amount=Decimal("50.0"), name="test_guard")
    await client.guards.add_guard("wallet-1", guard)

    # Simulate 10.0 (passes guard)
    res = await client.simulate(
        wallet_id="wallet-1",
        recipient="0xabc",
        amount=Decimal("10.0")
    )

    assert res.would_succeed is True
    assert "test_guard" in res.guards_that_would_pass

    # Simulate 60.0 (fails guard)
    res_fail = await client.simulate(
        wallet_id="wallet-1",
        recipient="0xabc",
        amount=Decimal("60.0")
    )

    assert res_fail.would_succeed is False
    assert "Would be blocked by guard" in res_fail.reason
