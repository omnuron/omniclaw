"""
Create 3 wallets for x402 demo testing:
- 2 on ARC-TESTNET (agent + seller)
- 1 on BASE-SEPOLIA (for cross-chain testing)
"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

# Add src to path
sys.path.insert(0, str(project_root / "src"))

from omniclaw import OmniClaw
from omniclaw.core.types import Network


async def main():
    api_key = os.getenv("CIRCLE_API_KEY")
    entity_secret = os.getenv("ENTITY_SECRET")  # Changed from CIRCLE_ENTITY_SECRET
    
    if not api_key or not entity_secret:
        print(f"❌ Error: CIRCLE_API_KEY and ENTITY_SECRET must be set")
        print(f"   CIRCLE_API_KEY: {'SET' if api_key else 'NOT SET'}")
        print(f"   ENTITY_SECRET: {'SET' if entity_secret else 'NOT SET'}")
        return
    
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
    wallet1 = await client.create_wallet(
        blockchain=Network.ARC_TESTNET,
        name="x402-demo-agent-arc"
    )
    wallets.append(("Agent (ARC-TESTNET)", wallet1))
    
    # Wallet 2: ARC-TESTNET (Seller)
    print("2️⃣  Creating ARC-TESTNET wallet (Seller)...")
    wallet2 = await client.create_wallet(
        blockchain=Network.ARC_TESTNET,
        name="x402-demo-seller-arc"
    )
    wallets.append(("Seller (ARC-TESTNET)", wallet2))
    
    # Wallet 3: BASE-SEPOLIA (Cross-chain)
    print("3️⃣  Creating BASE-SEPOLIA wallet (Cross-chain)...")
    wallet3 = await client.create_wallet(
        blockchain=Network.BASE_SEPOLIA,
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
    print("2. Run the same-chain test (ARC → ARC)")
    print("3. Run the cross-chain test (ARC → BASE or BASE → ARC)")
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
    asyncio.run(main())
