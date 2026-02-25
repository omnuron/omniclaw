"""
Tests for the full Payment Intent (2-Phase Commit) lifecycle.

Verifies create → confirm and create → cancel flows,
including fund reservation, expiry checks, and facade API.
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omniclaw.client import OmniClaw
from omniclaw.core.types import (
    Network,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentMethod,
    PaymentResult,
    PaymentStatus,
    SimulationResult,
)
from omniclaw.storage.memory import InMemoryStorage


@pytest.fixture
def client():
    """Create a client with mocked externals for intent testing."""
    c = OmniClaw(
        network=Network.ARC_TESTNET,
        circle_api_key="mock_key",
        entity_secret="mock_secret",
    )

    # Mock wallet service to return sufficient balance
    c._wallet_service = MagicMock()
    c._wallet_service.get_usdc_balance_amount.return_value = Decimal("500.00")
    c._wallet_service.get_wallet.return_value = MagicMock(blockchain="ETH-SEPOLIA")

    # Mock router simulate to succeed
    async def mock_simulate(*args, **kwargs):
        return SimulationResult(
            would_succeed=True,
            route=PaymentMethod.TRANSFER,
            estimated_fee=Decimal("0.01"),
        )

    c._router.simulate = mock_simulate

    # Mock router pay to succeed
    async def mock_pay(*args, **kwargs):
        return PaymentResult(
            success=True,
            transaction_id="tx-123",
            blockchain_tx="0xabc",
            amount=kwargs.get("amount", Decimal("0")),
            recipient=kwargs.get("recipient", ""),
            method=PaymentMethod.TRANSFER,
            status=PaymentStatus.COMPLETED,
        )

    c._router.pay = mock_pay

    return c


@pytest.mark.asyncio
async def test_create_intent_via_facade(client):
    """Test intent creation via the client.intent.create() facade API."""
    intent = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="50.00",
        purpose="Run LLM inference",
        expires_in=300,
    )

    assert intent.id is not None
    assert intent.status == PaymentIntentStatus.REQUIRES_CONFIRMATION
    assert intent.wallet_id == "wallet-1"
    assert intent.amount == Decimal("50.00")
    assert intent.purpose == "Run LLM inference"
    assert intent.expires_at is not None
    assert intent.reserved_amount == Decimal("50.00")


@pytest.mark.asyncio
async def test_confirm_intent_via_facade(client):
    """Test the full create → confirm flow."""
    intent = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="25.00",
        purpose="API call",
    )

    result = await client.intent.confirm(intent.id)

    assert result.success is True
    assert result.transaction_id == "tx-123"
    assert result.amount == Decimal("25.00")


@pytest.mark.asyncio
async def test_cancel_intent_via_facade(client):
    """Test the full create → cancel flow with reason."""
    intent = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="30.00",
    )

    cancelled = await client.intent.cancel(intent.id, reason="User declined")

    assert cancelled.status == PaymentIntentStatus.CANCELED
    assert cancelled.cancel_reason == "User declined"


@pytest.mark.asyncio
async def test_cancel_releases_reservation(client):
    """Cancelling an intent releases the reserved funds."""
    # Create intent → reserves funds
    intent = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="100.00",
    )

    # Verify reservation exists
    reserved = await client._reservation.get_reserved_total("wallet-1")
    assert reserved == Decimal("100.00")

    # Cancel → releases reservation
    await client.intent.cancel(intent.id, reason="Changed mind")

    reserved_after = await client._reservation.get_reserved_total("wallet-1")
    assert reserved_after == Decimal("0")


@pytest.mark.asyncio
async def test_get_intent_via_facade(client):
    """Test fetching an intent by ID."""
    intent = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="15.00",
    )

    fetched = await client.intent.get(intent.id)
    assert fetched is not None
    assert fetched.id == intent.id
    assert fetched.amount == Decimal("15.00")


@pytest.mark.asyncio
async def test_expired_intent_rejected(client):
    """Confirming an expired intent should fail and auto-cancel."""
    from omniclaw.core.exceptions import ValidationError

    # Create intent with very short expiry
    intent = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="20.00",
        expires_in=1,  # 1 second
    )

    # Wait for expiry
    await asyncio.sleep(1.1)

    # Confirm should fail
    with pytest.raises(ValidationError, match="expired"):
        await client.intent.confirm(intent.id)


@pytest.mark.asyncio
async def test_double_confirm_rejected(client):
    """Confirming an already-confirmed intent should fail."""
    from omniclaw.core.exceptions import ValidationError

    intent = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="10.00",
    )

    # Confirm once
    await client.intent.confirm(intent.id)

    # Second confirm should fail (status is no longer REQUIRES_CONFIRMATION)
    with pytest.raises(ValidationError, match="cannot be confirmed"):
        await client.intent.confirm(intent.id)


@pytest.mark.asyncio
async def test_cancel_already_cancelled_rejected(client):
    """Cancelling an already-cancelled intent should fail."""
    from omniclaw.core.exceptions import ValidationError

    intent = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="10.00",
    )

    await client.intent.cancel(intent.id)

    with pytest.raises(ValidationError, match="Cannot cancel"):
        await client.intent.cancel(intent.id)


@pytest.mark.asyncio
async def test_reservation_prevents_double_spend(client):
    """Creating two intents for more than the available balance should fail."""
    from omniclaw.core.exceptions import PaymentError

    # Balance is 500.00
    # Create first intent for 300
    intent1 = await client.intent.create(
        wallet_id="wallet-1",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount="300.00",
    )

    # Create second intent for 300 — only 200 available
    with pytest.raises(PaymentError, match="Authorization failed"):
        await client.intent.create(
            wallet_id="wallet-1",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount="300.00",
        )
