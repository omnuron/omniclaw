"""
Example: Using Guards for Spending Controls

Demonstrates how to configure spending guards to protect agent payments.
"""

import asyncio
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

from omniclaw import (  # noqa: E402
    Network,
    OmniClaw,
    PaymentStatus,
)


async def main():
    """
    Guards example showing:
    1. SingleTxGuard - Limit individual transaction amounts
    2. BudgetGuard - Daily/hourly spending limits
    3. RecipientGuard - Whitelist/blacklist recipients
    4. RateLimitGuard - Limit payment frequency
    5. ConfirmGuard - Require confirmation for large payments
    """
    print("=== OmniClaw Guards Example ===\n")

    # Initialize client
    client = OmniClaw(network=Network.ARC_TESTNET)

    # Create a demo wallet (or use existing)
    # In production, you'd reuse an existing wallet
    try:
        wallet_set, wallet = client.wallet.create_agent_wallet(agent_name="guard-demo-agent")
        wallet_id = wallet.id
        print(f"✅ Using wallet: {wallet_id}")
    except Exception as e:
        print(f"⚠️  Wallet creation failed: {e}")
        print("   Using mock wallet ID for demonstration")
        wallet_id = "demo-wallet-id"

    # ========================================
    # Example 1: SingleTxGuard
    # ========================================
    print("\n--- Example 1: SingleTxGuard ---")
    print("Limits individual transaction amounts (max $25, min $0.10)")

    await client.add_single_tx_guard(
        wallet_id,
        max_amount=Decimal("25.00"),
        min_amount=Decimal("0.10"),
        name="max_25_min_0.10",
    )

    # This should fail (exceeds max)
    result = await client.pay(
        wallet_id=wallet_id,
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("50.00"),
    )
    print(f"  $50 payment: {result.status.value} - {result.error or 'OK'}")

    # Remove guard for next example
    await client.guards.remove_guard(wallet_id, "max_25_min_0.10")

    # ========================================
    # Example 2: BudgetGuard
    # ========================================
    print("\n--- Example 2: BudgetGuard ---")
    print("Enforces daily/hourly spending limits (max $100/day, $30/hour)")

    await client.add_budget_guard(
        wallet_id,
        daily_limit=Decimal("100.00"),
        hourly_limit=Decimal("30.00"),
        name="daily_100_hourly_30",
    )

    # This should succeed (within limits)
    result = await client.pay(
        wallet_id=wallet_id,
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("10.00"),
    )
    print(f"  $10 payment: {result.status.value} - {result.error or 'OK'}")

    await client.guards.remove_guard(wallet_id, "daily_100_hourly_30")

    # ========================================
    # Example 3: RecipientGuard (Whitelist)
    # ========================================
    print("\n--- Example 3: RecipientGuard (Whitelist) ---")
    print("Restricts payments to approved recipients only")

    await client.add_recipient_guard(
        wallet_id,
        mode="whitelist",
        addresses=[
            "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",  # Approved
        ],
        name="trusted_recipients",
    )

    # This should fail (not in whitelist)
    result = await client.pay(
        wallet_id=wallet_id,
        recipient="0xUNTRUSTED1234567890123456789012345678901",
        amount=Decimal("5.00"),
    )
    print(f"  Untrusted recipient: {result.status.value} - {result.error or 'OK'}")

    await client.guards.remove_guard(wallet_id, "trusted_recipients")

    # ========================================
    # Example 4: RateLimitGuard
    # ========================================
    print("\n--- Example 4: RateLimitGuard ---")
    print("Prevents runaway loops (max 3 txs/minute)")

    await client.add_rate_limit_guard(
        wallet_id,
        max_per_minute=3,
        max_per_hour=10,
        name="rate_3pm_10ph",
    )

    # Make 3 payments (should succeed)
    for _ in range(3):
        result = await client.pay(
            wallet_id=wallet_id,
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("1.00"),
        )

    # 4th payment should fail
    result = await client.pay(
        wallet_id=wallet_id,
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("1.00"),
    )
    print(f"  4th payment in minute: {result.status.value} - {result.error or 'OK'}")

    await client.guards.remove_guard(wallet_id, "rate_3pm_10ph")

    # ========================================
    # Example 5: ConfirmGuard
    # ========================================
    print("\n--- Example 5: ConfirmGuard ---")
    print("Requires confirmation for payments over $50 (Human-in-the-Loop)")

    await client.add_confirm_guard(
        wallet_id,
        threshold=Decimal("50.00"),  # Payments > $50 require confirmation
        name="confirm_over_50",
    )

    # This triggers confirmation requirement
    result = await client.pay(
        wallet_id=wallet_id,
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("100.00"),
    )
    print(f"  $100 (over threshold): {result.status.value}")
    if result.status == PaymentStatus.BLOCKED:
        print(f"    → Blocked for confirmation: {result.error}")

    print("\n=== Guards Example Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
