"""
Example: Ledger and Transaction Tracking

Demonstrates how to use the transaction ledger for audit trails.
"""

import asyncio
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

from omniclaw import (  # noqa: E402
    Network,
    OmniClaw,
    SingleTxGuard,
)
from omniclaw.ledger import LedgerEntryStatus  # noqa: E402


async def main():
    """
    Ledger example showing:
    1. Automatic transaction recording
    2. Querying transaction history
    3. Tracking blocked vs completed payments
    """
    print("=== OmniClaw Ledger Example ===\n")

    # Initialize client
    client = OmniClaw(network=Network.ARC_TESTNET)
    client.set_default_wallet("demo-wallet-id")

    # Add a guard to block some payments
    client.add_guard(SingleTxGuard(max_amount=Decimal("50.00")))

    recipient = "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0"

    # ========================================
    # Make some payments (will be recorded)
    # ========================================
    print("--- Making Payments ---")

    # Payment 1: Will be blocked by guard
    result1 = await client.pay(
        recipient=recipient,
        amount=Decimal("100.00"),
        purpose="Large API payment",
    )
    print(f"  $100 payment: {result1.status}")

    # Payment 2: Would pass guard but fail on execution (no real wallet)
    result2 = await client.pay(
        recipient=recipient,
        amount=Decimal("25.00"),
        purpose="Small API payment",
    )
    print(f"  $25 payment: {result2.status}")

    # Payment 3: Another blocked payment
    result3 = await client.pay(
        recipient=recipient,
        amount=Decimal("75.00"),
        purpose="Medium API payment",
    )
    print(f"  $75 payment: {result3.status}")

    # ========================================
    # Query the ledger
    # ========================================
    print("\n--- Ledger Contents ---")

    # Get all entries
    all_entries = await client.ledger.query(limit=10)
    print(f"  Total entries: {len(all_entries)}")

    for entry in all_entries:
        print(f"    [{entry.status.value}] ${entry.amount} - {entry.purpose}")

    # ========================================
    # Filter by status
    # ========================================
    print("\n--- Blocked Transactions ---")

    blocked = await client.ledger.query(status=LedgerEntryStatus.BLOCKED)
    print(f"  Blocked count: {len(blocked)}")

    for entry in blocked:
        print(f"    ${entry.amount} to {entry.recipient[:10]}... - {entry.purpose}")

    # ========================================
    # Get total spent (only COMPLETED transactions)
    # ========================================
    print("\n--- Spending Summary ---")

    total_spent = await client.ledger.get_total_spent("demo-wallet-id")
    print(f"  Total spent (completed): ${total_spent}")

    # Count by status
    pending = await client.ledger.query(status=LedgerEntryStatus.PENDING)
    completed = await client.ledger.query(status=LedgerEntryStatus.COMPLETED)
    failed = await client.ledger.query(status=LedgerEntryStatus.FAILED)

    print(f"  Pending: {len(pending)}")
    print(f"  Completed: {len(completed)}")
    print(f"  Blocked: {len(blocked)}")
    print(f"  Failed: {len(failed)}")

    print("\n=== Ledger Example Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
