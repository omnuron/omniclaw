"""
Example: Using Guards for Spending Controls

Demonstrates how to configure spending guards to protect agent payments.
"""

import asyncio
import os
from decimal import Decimal

from dotenv import load_dotenv
load_dotenv()

from omniagentpay import (
    OmniAgentPay,
    Network,
    BudgetGuard,
    SingleTxGuard,
    RecipientGuard,
    RateLimitGuard,
    ConfirmGuard,
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
    print("=== OmniAgentPay Guards Example ===\n")
    
    # Initialize client
    client = OmniAgentPay(network=Network.ARC_TESTNET)
    client.set_default_wallet("demo-wallet-id")
    
    # ========================================
    # Example 1: SingleTxGuard
    # ========================================
    print("--- Example 1: SingleTxGuard ---")
    
    client.add_guard(SingleTxGuard(
        max_amount=Decimal("25.00"),
        min_amount=Decimal("0.10"),
        name="max_25_min_0.10",
    ))
    
    # This should fail (exceeds max)
    result = await client.pay(
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("50.00"),
    )
    print(f"  $50 payment: {result.status} - {result.error or 'OK'}")
    
    # Reset for next example
    client.remove_guard("max_25_min_0.10")
    
    # ========================================
    # Example 2: BudgetGuard
    # ========================================
    print("\n--- Example 2: BudgetGuard ---")
    
    budget_guard = BudgetGuard(
        daily_limit=Decimal("100.00"),
        hourly_limit=Decimal("30.00"),
        name="daily_100_hourly_30",
    )
    client.add_guard(budget_guard)
    
    # Simulate previous spending
    budget_guard.record_spending(Decimal("95.00"))
    
    # This should fail (would exceed daily limit)
    result = await client.pay(
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("10.00"),
    )
    print(f"  $10 after $95 spent: {result.status} - {result.error or 'OK'}")
    
    client.remove_guard("daily_100_hourly_30")
    
    # ========================================
    # Example 3: RecipientGuard (Whitelist)
    # ========================================
    print("\n--- Example 3: RecipientGuard (Whitelist) ---")
    
    client.add_guard(RecipientGuard(
        mode="whitelist",
        addresses=[
            "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",  # Approved
        ],
        name="trusted_recipients",
    ))
    
    # This should fail (not in whitelist)
    result = await client.pay(
        recipient="0xUNTRUSTED1234567890123456789012345678901",
        amount=Decimal("5.00"),
    )
    print(f"  Untrusted recipient: {result.status} - {result.error or 'OK'}")
    
    client.remove_guard("trusted_recipients")
    
    # ========================================
    # Example 4: RateLimitGuard
    # ========================================
    print("\n--- Example 4: RateLimitGuard ---")
    
    rate_guard = RateLimitGuard(
        max_per_minute=3,
        max_per_hour=10,
        name="rate_3pm_10ph",
    )
    client.add_guard(rate_guard)
    
    # Simulate hitting rate limit
    rate_guard.record_payment()
    rate_guard.record_payment()
    rate_guard.record_payment()
    
    result = await client.pay(
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("1.00"),
    )
    print(f"  4th payment in minute: {result.status} - {result.error or 'OK'}")
    
    client.remove_guard("rate_3pm_10ph")
    
    # ========================================
    # Example 5: ConfirmGuard with Callback
    # ========================================
    print("\n--- Example 5: ConfirmGuard ---")
    
    async def auto_approve_callback(context):
        """Simulate auto-approval for demo."""
        print(f"    [Callback] Approving ${context.amount} to {context.recipient[:10]}...")
        return True
    
    client.add_guard(ConfirmGuard(
        threshold=Decimal("50.00"),
        callback=auto_approve_callback,
        name="confirm_over_50",
    ))
    
    # This triggers confirmation callback
    result = await client.pay(
        recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
        amount=Decimal("100.00"),
    )
    # Note: Will still fail due to no actual wallet, but callback is invoked
    print(f"  $100 (over threshold): Callback invoked")
    
    print("\n=== Guards Example Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
