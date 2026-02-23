"""
MANUAL Wallet Creation Script

Run this with your API credentials to create the 3 demo wallets.

Usage:
    python scripts/create_demo_wallets_manual.py <CIRCLE_API_KEY> <ENTITY_SECRET>
"""
import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omniclaw import OmniClaw
from omniclaw.core.types import Network


async def main(api_key: str, entity_secret: str):
    print("🏗️  Creating OmniClaw client...")
    client = OmniClaw(
        circle_api_key=api_key,
        entity_secret=entity_secret,
    )
    
    print("\n" + "="*60)
    print("Creating 3 Test Wallets for x402 Demo")
    print("="*60 + "\n")
    
    # Create wallets
    wallets = []
    
    # Wallet 1: ARC-TESTNET (Agent)
    print("1️⃣  Creating ARC-TESTNET wallet (Agent)...")
    wallet1 = client.create_wallet(
        network=Network.ARC_TESTNET,
        name="x402-demo-agent-arc"
    )
    wallets.append(("Agent (ARC-TESTNET)", wallet1))
    
    # Wallet 2: ARC-TESTNET (Seller)
    print("2️⃣  Creating ARC-TESTNET wallet (Seller)...")
    wallet2 = client.create_wallet(
        network=Network.ARC_TESTNET,
        name="x402-demo-seller-arc"
    )
    wallets.append(("Seller (ARC-TESTNET)", wallet2))
    
    # Wallet 3: BASE-SEPOLIA (Cross-chain)
    print("3️⃣  Creating BASE-SEPOLIA wallet (Cross-chain)...")
    wallet3 = client.create_wallet(
        network=Network.BASE_SEPOLIA,
        name="x402-demo-crosschain-base"
    )
    wallets.append(("Cross-chain (BASE-SEPOLIA)", wallet3))
    
    # Display results
    print("\n" + "="*60)
    print("✅ Wallets Created Successfully!")
    print("="*60 + "\n")
    
    for name, wallet in wallets:
        print(f"📍 {name}")
        print(f"   Wallet ID: {wallet.id}")
        print(f"   Address:   {wallet.address}")
        print(f"   Network:   {wallet.blockchain}")
        print()
    
    print("="*60)
    print("💡 Next Steps:")
    print("="*60)
    print("1. Fund the Agent (ARC-TESTNET) wallet with USDC")
    print("2. Update demo_x402_test.py with the wallet IDs")
    print("3. Run the demo tests")
    print("\n")
    
    # Save wallet info to a file for easy reference
    output_file = os.path.join(os.path.dirname(__file__), "demo_wallets.txt")
    with open(output_file, "w") as f:
        f.write("X402 Demo Test Wallets\n")
        f.write("=" * 60 + "\n\n")
        for name, wallet in wallets:
            f.write(f"{name}\n")
            f.write(f"Wallet ID: {wallet.id}\n")
            f.write(f"Address:   {wallet.address}\n")
            f.write(f"Network:   {wallet.blockchain}\n")
            f.write("\n")
    
    print(f"💾 Wallet info saved to: {output_file}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python create_demo_wallets_manual.py <CIRCLE_API_KEY> <ENTITY_SECRET>")
        sys.exit(1)
    
    api_key = sys.argv[1]
    entity_secret = sys.argv[2]
    
    asyncio.run(main(api_key, entity_secret))
