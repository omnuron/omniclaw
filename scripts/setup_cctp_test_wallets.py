#!/usr/bin/env python3
"""
Create test wallets for CCTP cross-chain transfer testing.

Creates:
1. Agent wallet on BASE-SEPOLIA (sender)
2. Seller wallet on ETH-SEPOLIA (receiver)
"""

import asyncio
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omniclaw import OmniClaw
from omniclaw.core.types import Network


async def main():
    # Initialize client
    client = OmniClaw.from_env()
    
    print("=" * 60)
    print("CCTP TEST WALLET SETUP")
    print("=" * 60)
    
    # 1. Create Agent wallet on BASE-SEPOLIA
    print("\n📱 Creating AGENT wallet on BASE-SEPOLIA...")
    agent_wallet = client.onboarding.create_wallet(
        blockchain=Network.BASE_SEPOLIA,
        name="CCTP-Test-Agent-Base",
    )
    print(f"   Wallet ID: {agent_wallet.wallet_id}")
    print(f"   Address:   {agent_wallet.address}")
    print(f"   Network:   {agent_wallet.blockchain}")
    
    # 2. Create Seller wallet on ETH-SEPOLIA
    print("\n🏪 Creating SELLER wallet on ETH-SEPOLIA...")
    seller_wallet = client.onboarding.create_wallet(
        blockchain=Network.ETH_SEPOLIA,
        name="CCTP-Test-Seller-ETH",
    )
    print(f"   Wallet ID: {seller_wallet.wallet_id}")
    print(f"   Address:   {seller_wallet.address}")
    print(f"   Network:   {seller_wallet.blockchain}")
    
    print("\n" + "=" * 60)
    print("NEXT STEPS:")
    print("=" * 60)
    print(f"""
1. Fund the AGENT wallet with USDC on Base Sepolia:
   - Go to Circle Faucet or Uniswap testnet
   - Address: {agent_wallet.address}
   - Network: Base Sepolia
   - Add at least 1 USDC

2. Once funded, run the transfer test:
   python scripts/test_cctp_transfer.py \\
       --agent-wallet {agent_wallet.wallet_id} \\
       --seller-address {seller_wallet.address} \\
       --amount 0.5

3. Check seller balance after transfer completes
""")
    
    # Save wallet IDs for later use
    print("WALLET DETAILS (save these):")
    print(f"AGENT_WALLET_ID={agent_wallet.wallet_id}")
    print(f"AGENT_ADDRESS={agent_wallet.address}")
    print(f"SELLER_WALLET_ID={seller_wallet.wallet_id}")
    print(f"SELLER_ADDRESS={seller_wallet.address}")


if __name__ == "__main__":
    asyncio.run(main())
