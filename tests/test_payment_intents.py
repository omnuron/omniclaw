"""Tests for Payment Intents and 2-Phase Commit."""

import os
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from omniclaw.client import OmniClaw
from omniclaw.core.exceptions import InsufficientBalanceError, PaymentError, ValidationError
from omniclaw.core.types import Network, PaymentIntentStatus, PaymentMethod, PaymentResult


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
async def test_create_and_confirm_intent(client):
    """Test full 2-phase commit positive flow."""
    # Mock dependencies
    client._wallet_service.get_usdc_balance_amount = lambda wid: Decimal("200.0")
    client._router.simulate = AsyncMock()
    client._router.pay = AsyncMock()

    from omniclaw.core.types import PaymentStatus, SimulationResult
    client._router.simulate.return_value = SimulationResult(
        would_succeed=True, route=PaymentMethod.TRANSFER
    )
    client._router.pay.return_value = PaymentResult(
        success=True,
        transaction_id="tx-123",
        blockchain_tx="hash-456",
        amount=Decimal("50.0"),
        recipient="0xabc",
        method=PaymentMethod.TRANSFER,
        status=PaymentStatus.COMPLETED
    )

    # 1. Create intent
    intent = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0xabc",
        amount=Decimal("50.0"),
        purpose="Subscription",
        expires_in=3600
    )

    assert intent.status == PaymentIntentStatus.REQUIRES_CONFIRMATION
    assert intent.purpose == "Subscription"
    assert intent.reserved_amount == Decimal("50.0")

    # 2. Verify funds are reserved
    reserved = await client._reservation.get_reserved_total("wallet-1")
    assert reserved == Decimal("50.0")

    # 3. Confirm intent
    result = await client.intent.confirm(intent.id)
    assert result.success is True
    assert result.transaction_id == "tx-123"

    # 4. Verify intent status is updated and funds are released
    updated_intent = await client.intent.get(intent.id)
    assert updated_intent.status == PaymentIntentStatus.SUCCEEDED
    
    reserved_after = await client._reservation.get_reserved_total("wallet-1")
    assert reserved_after == Decimal("0.0")


@pytest.mark.asyncio
async def test_intent_prevents_double_spend(client):
    """Test that a pending intent prevents direct pay from using its reserved funds."""
    client._wallet_service.get_usdc_balance_amount = lambda wid: Decimal("100.0")
    client._router.simulate = AsyncMock()
    from omniclaw.core.types import SimulationResult
    client._router.simulate.return_value = SimulationResult(
        would_succeed=True, route=PaymentMethod.TRANSFER
    )

    # Create intent for 80 USDC
    intent = await client.intent.create(
        wallet_id="wallet-2",
        recipient="0xabc",
        amount=Decimal("80.0")
    )

    assert intent.status == PaymentIntentStatus.REQUIRES_CONFIRMATION

    # Attempt direct pay for 30 USDC (Total 100, Reserved 80, Available 20 -> should fail)
    with pytest.raises(InsufficientBalanceError) as exc:
        await client.pay(
            wallet_id="wallet-2",
            recipient="0xdef",
            amount=Decimal("30.0")
        )

    assert "Insufficient available balance" in str(exc.value)

    # Cancel the intent
    await client.intent.cancel(intent.id, reason="Changed mind")

    # Now direct pay should succeed (mocking the pay method)
    client._router.pay = AsyncMock()
    from omniclaw.core.types import PaymentResult, PaymentStatus
    client._router.pay.return_value = PaymentResult(
        success=True,
        transaction_id="tx-456",
        blockchain_tx="hash-789",
        amount=Decimal("30.0"),
        recipient="0xdef",
        method=PaymentMethod.TRANSFER,
        status=PaymentStatus.COMPLETED
    )

    res = await client.pay(
        wallet_id="wallet-2",
        recipient="0xdef",
        amount=Decimal("30.0")
    )
    assert res.success is True


@pytest.mark.asyncio
async def test_cancel_intent(client):
    """Test cancellation of intent releases funds."""
    client._wallet_service.get_usdc_balance_amount = lambda wid: Decimal("100.0")
    client._router.simulate = AsyncMock()
    from omniclaw.core.types import SimulationResult
    client._router.simulate.return_value = SimulationResult(
        would_succeed=True, route=PaymentMethod.TRANSFER
    )

    intent = await client.intent.create(
        wallet_id="wallet-3",
        recipient="0xabc",
        amount=Decimal("40.0")
    )

    # Verify reservation
    reserved = await client._reservation.get_reserved_total("wallet-3")
    assert reserved == Decimal("40.0")

    # Cancel
    canceled_intent = await client.intent.cancel(intent.id, reason="Not needed")
    assert canceled_intent.status == PaymentIntentStatus.CANCELED
    assert canceled_intent.cancel_reason == "Not needed"

    # Verify release
    reserved_after = await client._reservation.get_reserved_total("wallet-3")
    assert reserved_after == Decimal("0.0")

    # Attempting to confirm canceled intent should raise error
    with pytest.raises(ValidationError) as exc:
        await client.intent.confirm(intent.id)
    
    assert "Cannot be confirmed" in str(exc.value) or "cannot be confirmed" in str(exc.value)
