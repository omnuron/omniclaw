"""
Example: Basic Payment Flow

Demonstrates the simplest way to use OmniAgentPay SDK.
"""

import asyncio
import os
from decimal import Decimal

from dotenv import load_dotenv
load_dotenv()

from omniagentpay import OmniAgentPay, Network


async def main():
    """
    Basic example showing:
    1. Initialize client
    2. List wallets
    3. Make a payment (simulated)
    """
    print("=== OmniAgentPay Basic Example ===\n")
    
    # Step 1: Initialize client
    # Reads CIRCLE_API_KEY and ENTITY_SECRET from environment
    client = OmniAgentPay(network=Network.ARC_TESTNET)
    print("✅ Client initialized")
    
    # Step 2: List existing wallets
    wallets = client.wallet.list_wallets()
    if not wallets:
        print("⚠️  No wallets found. Create one first using the E2E test script.")
        return
    
    wallet = wallets[0]
    print(f"✅ Found wallet: {wallet.id}")
    print(f"   Address: {wallet.address}")
    
    wallet = wallets[0]
    print(f"✅ Found wallet: {wallet.id}")
    print(f"   Address: {wallet.address}")
    
    # Step 3: Check balance
    try:
        balance = await client.get_balance(wallet.id)
        print(f"✅ Balance: {balance} USDC")
    except Exception as e:
        print(f"⚠️  Balance check failed: {e}")
    
    # Step 4: Make a payment (simulated with skip_guards for demo if needed, or real)
    # Note: On testnet, ensure you have funds!
    recipient = "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0"
    amount = Decimal("1.00")
    
    print(f"\n📤 Sending payment of {amount} USDC to {recipient[:10]}...")
    
    try:
        # We use wait_for_completion=True to see the result immediately
        result = await client.pay(
            wallet_id=wallet.id,
            recipient=recipient,
            amount=amount,
            wait_for_completion=True
        )
        
        if result.success:
            print(f"✅ Payment Successful! Tx: {result.blockchain_tx}")
        else:
            print(f"⚠️  Payment Failed: {result.error}")
            
    except Exception as e:
        print(f"❌ Error during payment: {e}")
    
    print("\n=== Example Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
