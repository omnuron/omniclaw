"""
Tests for payment failure scenarios and resilience.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from omniclaw.client import OmniClaw
from omniclaw.core.exceptions import InsufficientBalanceError
from omniclaw.core.types import (
    Network,
    PaymentResult,
    PaymentStatus,
)
from omniclaw.payment.batch import BatchProcessor
from omniclaw.payment.router import PaymentRouter
from omniclaw.protocols.transfer import TransferAdapter
from omniclaw.wallet.service import TransferResult

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def client_mocked():
    """Client with heavily mocked internals for verifying failure paths."""
    client = OmniClaw(
        network=Network.ARC_TESTNET, circle_api_key="mock_key", entity_secret="mock_secret"
    )
    # Mock wallet service completely
    client._wallet_service = MagicMock()
    # Mock balance to prevent checks from failing before transfer
    balance = MagicMock()
    balance.amount = Decimal("1000000.00")
    client._wallet_service.get_usdc_balance.return_value = balance
    client._wallet_service.get_usdc_balance.return_value = balance
    client._wallet_service.get_usdc_balance_amount.return_value = Decimal("1000000.00")
    
    # Configure get_wallet mock to return an object with a valid blockchain string
    mock_wallet = MagicMock()
    mock_wallet.blockchain = "ARC-TESTNET"
    client._wallet_service.get_wallet.return_value = mock_wallet

    # CRITICAL: Re-initialize router to use the Mocked Wallet Service
    client._router = PaymentRouter(client._config, client._wallet_service)

    # CRITICAL: Register the Transfer Adapter so routing works!
    # Without this, "No adapter found" is returned for EVM addresses.
    transfer_adapter = TransferAdapter(client._config, client._wallet_service)
    client._router.register_adapter(transfer_adapter)

    # CRITICAL: Re-initialize BatchProcessor with the NEW router!
    # Without this, batch_pay uses the OLD router (with old wallet service/adapters).
    client._batch_processor = BatchProcessor(client._router)

    # Mock storage/ledger to verify side effects
    client.ledger.record = AsyncMock()
    client.ledger.update_status = AsyncMock()
    return client


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pay_insufficient_funds(client_mocked):
    """Test payment failing due to insufficient funds."""
    # Mock transfer to raise InsufficientBalanceError
    client_mocked._wallet_service.transfer.side_effect = InsufficientBalanceError(
        "Insufficient funds", current_balance=Decimal("0"), required_amount=Decimal("100.00")
    )

    result = await client_mocked.pay(
        wallet_id="wallet-123",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("100.00"),
    )

    assert result.success is False
    assert result.status == PaymentStatus.FAILED
    assert "Insufficient funds" in str(result.error)


@pytest.mark.asyncio
async def test_pay_network_error_during_transfer(client_mocked):
    """Test payment failing due to network error during transfer call."""
    # Transfer adapter DOES NOT catch generic Exception.
    client_mocked._wallet_service.transfer.side_effect = Exception("Circle API Timeout")

    with pytest.raises(Exception) as excinfo:
        await client_mocked.pay(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("100.00"),
        )

    assert "Circle API Timeout" in str(excinfo.value)


@pytest.mark.asyncio
async def test_pay_transfer_returns_failure_result(client_mocked):
    """Test payment where transfer() returns a failure result (not exception)."""
    # Note: Mocking transfer here works because adapter uses client._wallet_service
    client_mocked._wallet_service.transfer.return_value = TransferResult(
        success=False, error="Blockchain rejected transaction", transaction=None
    )

    result = await client_mocked.pay(
        wallet_id="wallet-123",
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("100.00"),
    )

    assert result.success is False
    assert result.status == PaymentStatus.FAILED
    assert "Blockchain rejected" in str(result.error)


@pytest.mark.asyncio
async def test_batch_pay_partial_failure(client_mocked):
    """Test batch payment where some succeed and some fail."""
    from omniclaw.core.types import PaymentRequest

    # Use _router because router property is private
    target = client_mocked._router

    # Mock router.pay via side_effect to simulate mixed results
    async def mock_router_pay(*args, **kwargs):
        amt = kwargs.get("amount")
        if amt == Decimal("10.00"):
            return PaymentResult(
                success=True,
                transaction_id="tx-1",
                blockchain_tx="0x1",
                amount=amt,
                recipient="0x...",
                method="transfer",
                status=PaymentStatus.COMPLETED,
            )
        else:
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amt,
                recipient="0x...",
                method="transfer",
                status=PaymentStatus.FAILED,
                error="Random failure",
            )

    target.pay = AsyncMock(side_effect=mock_router_pay)

    requests = [
        PaymentRequest(wallet_id="w1", recipient="r1", amount=Decimal("10.00")),
        PaymentRequest(wallet_id="w1", recipient="r1", amount=Decimal("20.00")),  # Fails
        PaymentRequest(wallet_id="w1", recipient="r1", amount=Decimal("10.00")),
    ]

    result = await client_mocked.batch_pay(requests)

    assert result.total_count == 3
    assert result.success_count == 2
    assert result.failed_count == 1
    assert len(result.results) == 3
