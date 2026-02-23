"""
Verification script for Ledger Sync.
"""

import asyncio
import sys
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

# Mock Circle
sys.modules["circle"] = MagicMock()
sys.modules["circle.web3"] = MagicMock()

from omniclaw import OmniClaw  # noqa: E402
from omniclaw.core.types import (  # noqa: E402
    FeeLevel,
    TransactionInfo,
    TransactionState,
)
from omniclaw.ledger import LedgerEntry, LedgerEntryStatus  # noqa: E402


async def test_ledger_sync():
    print("\n=== Testing Ledger Sync ===")

    # Init client
    client = OmniClaw(circle_api_key="mock", entity_secret="mock")

    # 1. Create a dummy PENDING ledger entry manually
    # We cheat and use internal ledger to insert
    dummy_tx_id = "tx_circle_123"
    entry = LedgerEntry(
        id=str(uuid.uuid4()),
        wallet_id="w1",
        recipient="r1",
        amount=Decimal("10.00"),
        status=LedgerEntryStatus.PENDING,
        metadata={"transaction_id": dummy_tx_id},  # Vital!
    )
    await client._ledger.record(entry)
    print(f"1. Recorded PENDING entry: {entry.id}")

    # 2. Mock CircleClient.get_transaction to return COMPLETE
    mock_tx_info = TransactionInfo(
        id=dummy_tx_id,
        state=TransactionState.COMPLETE,
        blockchain="ETH",
        tx_hash="0xFinalHash",
        wallet_id="w1",
        source_address="0xSrc",
        destination_address="0xDst",
        amounts=["10.00"],
        fee_level=FeeLevel.MEDIUM,
        create_date=None,
        update_date=None,
    )
    # Mocking the method on the instance
    client._circle_client.get_transaction = MagicMock(return_value=mock_tx_info)

    # 3. Call sync_transaction
    print("2. Calling sync_transaction()...")
    updated_entry = await client.sync_transaction(entry.id)

    # 4. Verify
    print(f"3. Updated Status: {updated_entry.status}")
    print(f"   Provider State: {updated_entry.metadata.get('provider_state')}")
    print(f"   Tx Hash: {updated_entry.tx_hash}")

    assert updated_entry.status == LedgerEntryStatus.COMPLETED
    assert updated_entry.tx_hash == "0xFinalHash"
    assert updated_entry.metadata["last_synced"] is not None

    print("Ledger Sync Verification Successful")


if __name__ == "__main__":
    asyncio.run(test_ledger_sync())
