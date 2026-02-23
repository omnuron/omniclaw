"""
Create ETH-SEPOLIA wallet for CCTP testing.
"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")
sys.path.insert(0, str(project_root / "src"))

from omniclaw import OmniClaw
from omniclaw.core.types import Network


async def main():
    api_key = os.getenv("CIRCLE_API_KEY")
    entity_secret = os.getenv("ENTITY_SECRET")
    
    if not api_key or not entity_secret:
        print("❌ Error: CIRCLE_API_KEY and ENTITY_SECRET must be set")
        return
    
    print("🏗️  Creating ETH-SEPOLIA wallet for CCTP testing...")
    
    client = OmniClaw(
        circle_api_key=api_key,
        entity_secret=entity_secret,
    )
    
    wallet = await client.create_wallet(
        blockchain=Network.ETH_SEPOLIA,
        name="cctp-demo-eth-buyer"
    )
    
    print("\n" + "=" * 60)
    print("✅ ETH-SEPOLIA Wallet Created!")
    print("=" * 60)
    print(f"Wallet ID: {wallet.id}")
    print(f"Address:   {wallet.address}")
    print(f"Network:   {wallet.blockchain}")
    print("=" * 60)
    print("\n💡 Next Steps:")
    print("1. Fund this wallet with USDC on ETH-SEPOLIA")
    print("2. Update x402_client_demo.py:")
    print(f"   AGENT_WALLET_ID = \"{wallet.id}\"")
    print(f"3. Update OmniClaw network to ETH_SEPOLIA")
    print("4. Run the cross-chain test (ETH → BASE)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
