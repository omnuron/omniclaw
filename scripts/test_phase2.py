"""
Verification script for Phase 2: Payment Intents and Batch Payments.
"""
import asyncio
import uuid
from decimal import Decimal
import sys
from unittest.mock import MagicMock, AsyncMock

# Mock external Circle SDK dependency
sys.modules["circle"] = MagicMock()
sys.modules["circle.web3"] = MagicMock()
sys.modules["circle.web3.developer_controlled_wallets"] = MagicMock()
sys.modules["circle.web3.utils"] = MagicMock()

from omniagentpay import OmniAgentPay, Network

from omniagentpay.core.types import (
    PaymentIntentStatus,
    PaymentRequest,
    PaymentResult,
    PaymentStatus,
    PaymentMethod,
    SimulationResult
)

async def test_payment_intents():
    print("\n=== Testing Payment Intents ===")
    
    # Initialize Client (Memory Storage by default)
    client = OmniAgentPay(circle_api_key="mock_key", entity_secret="mock_secret")
    
    # Mock Router behaviors to avoid real API calls
    client._router.simulate = AsyncMock(return_value=SimulationResult(
        would_succeed=True,
        route=PaymentMethod.TRANSFER,
        reason="Mock Success"
    ))
    
    client._router.pay = AsyncMock(return_value=PaymentResult(
        success=True,
        transaction_id="tx_123",
        blockchain_tx="0xabc",
        amount=Decimal("10"),
        recipient="0x123",
        method=PaymentMethod.TRANSFER,
        status=PaymentStatus.COMPLETED
    ))

    # 1. Create Intent
    print("1. Creating Intent...")
    wallet_id = str(uuid.uuid4())
    intent = await client.create_payment_intent(
        wallet_id=wallet_id,
        recipient="0xRecipient",
        amount=Decimal("10.00"),
        purpose="Test Intent"
    )
    print(f"   Created Intent: {intent.id} Status: {intent.status}")
    assert intent.status == PaymentIntentStatus.REQUIRES_CONFIRMATION
    assert intent.metadata["purpose"] == "Test Intent"

    # 2. Get Intent
    print("2. Retrieving Intent...")
    fetched = await client.get_payment_intent(intent.id)
    assert fetched is not None
    assert fetched.id == intent.id
    print("   Retrieval Successful")

    # 3. Cancel Intent
    print("3. Cancelling Intent...")
    cancelled = await client.cancel_payment_intent(intent.id)
    assert cancelled.status == PaymentIntentStatus.CANCELED
    print("   Cancellation Successful")

    # 4. Confirm Intent (Create new one first)
    print("4. Confirming Intent...")
    intent2 = await client.create_payment_intent(
        wallet_id=wallet_id,
        recipient="0xRecipient",
        amount=Decimal("20.00")
    )
    result = await client.confirm_payment_intent(intent2.id)
    
    # Verify execution
    assert result.success
    assert result.transaction_id == "tx_123"
    
    # Verify status update
    updated = await client.get_payment_intent(intent2.id)
    assert updated.status == PaymentIntentStatus.SUCCEEDED
    print("   Confirmation Successful & Status Updated")


async def test_batch_payments():
    print("\n=== Testing Batch Payments ===")
    
    client = OmniAgentPay(circle_api_key="mock_key", entity_secret="mock_secret")
    
    # Mock Router Pay
    async def mock_pay(wallet_id, recipient, amount, **kwargs):
        # Fail specific amount for testing mixed results
        if amount == Decimal("5.00"):
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=recipient,
                method=PaymentMethod.TRANSFER,
                status=PaymentStatus.FAILED,
                error="Mock Failure"
            )
        return PaymentResult(
            success=True,
            transaction_id=f"tx_{amount}",
            blockchain_tx="0x...",
            amount=amount,
            recipient=recipient,
            method=PaymentMethod.TRANSFER,
            status=PaymentStatus.COMPLETED
        )
    
    client._router.pay = AsyncMock(side_effect=mock_pay)
    
    requests = [
        PaymentRequest(wallet_id="w1", recipient="r1", amount=Decimal("1.00")),
        PaymentRequest(wallet_id="w1", recipient="r2", amount=Decimal("2.00")),
        PaymentRequest(wallet_id="w1", recipient="r3", amount=Decimal("3.00")),
        PaymentRequest(wallet_id="w1", recipient="r4", amount=Decimal("5.00")), # Expect Fail
    ]
    
    print(f"Executing Batch checking {len(requests)} items...")
    result = await client.batch_pay(requests, concurrency=2)
    
    print(f"Batch Result: {result.success_count}/{result.total_count} succeeded")
    
    assert result.total_count == 4
    assert result.success_count == 3
    assert result.failed_count == 1
    assert len(result.results) == 4
    assert "tx_1.00" in result.transaction_ids
    assert "tx_5.00" not in result.transaction_ids
    
    print("Batch Payment Verification Successful")

if __name__ == "__main__":
    asyncio.run(test_payment_intents())
    asyncio.run(test_batch_payments())
