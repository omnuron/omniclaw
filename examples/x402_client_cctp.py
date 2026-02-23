"""
x402 Client - CCTP Cross-Chain Test (ETH-SEPOLIA → BASE-SEPOLIA)

Tests x402 payment with CCTP routing for cross-chain transfers.
"""
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path
from dotenv import load_dotenv

# Load environment
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")
sys.path.insert(0, str(project_root / "src"))

from omniclaw import OmniClaw
from omniclaw.core.types import Network


# Configuration for CCTP test
AGENT_WALLET_ID = "7612e1ec-88aa-5adc-a437-a2d75a1b6184"  # ETH-SEPOLIA (funded with 20 USDC)
SERVER_URL = "http://localhost:8402/premium"


async def main():
    api_key = os.getenv("CIRCLE_API_KEY")
    entity_secret = os.getenv("ENTITY_SECRET")
    
    if not api_key or not entity_secret:
        print("❌ Error: CIRCLE_API_KEY and ENTITY_SECRET must be set")
        return
    
    print("=" * 60)
    print("🚀 x402 CCTP Cross-Chain Test")
    print("   ETH-SEPOLIA → BASE-SEPOLIA")
    print("=" * 60)
    
    client = OmniClaw(
        circle_api_key=api_key,
        entity_secret=entity_secret,
        network=Network.ETH_SEPOLIA,  # ← Changed to ETH-SEPOLIA
    )
    
    # Check balance
    print(f"\n💰 Checking wallet balance...")
    try:
        balance = await client.get_balance(AGENT_WALLET_ID)
        print(f"   Agent Wallet (ETH-SEPOLIA): {balance} USDC")
        
        if balance < Decimal("0.1"):
            print("   ⚠️  Insufficient balance for test!")
            return
    except Exception as e:
        print(f"   ⚠️  Could not check balance: {e}")
    
    # Make x402 payment request (cross-chain)
    print(f"\n📡 Requesting: {SERVER_URL}")
    print(f"   Expected flow:")
    print(f"   1. GET {SERVER_URL}")
    print(f"   2. Receive 402 (requires BASE-SEPOLIA payment)")
    print(f"   3. Detect cross-chain (ETH-SEPOLIA → BASE-SEPOLIA)")
    print(f"   4. Route through CCTP V2")
    print(f"   5. Burn USDC on ETH-SEPOLIA")
    print(f"   6. Mint USDC on BASE-SEPOLIA (~2-5 sec)")
    print(f"   7. Submit payment proof")
    print(f"   8. Receive premium content\n")
    
    try:
        result = await client.pay(
            wallet_id=AGENT_WALLET_ID,
            recipient=SERVER_URL,
            amount=Decimal("1.0"),  # Max willing to pay
        )
        
        print("\n" + "=" * 60)
        if result.success:
            print("✅ CCTP Cross-Chain Payment Successful!")
            print("=" * 60)
            print(f"Transaction ID: {result.transaction_id}")
            print(f"Blockchain Tx: {result.blockchain_tx}")
            print(f"Amount Paid: {result.amount} USDC")
            print(f"Method: {result.method.value}")
            print(f"Status: {result.status.value}")
            
            if result.metadata:
                print(f"\n📋 CCTP Metadata:")
                for key, value in result.metadata.items():
                    if key == 'cctp_version':
                        print(f"  CCTP Version: {value}")
                    elif key == 'transfer_mode':
                        print(f"  Transfer Mode: {value}")
                    elif key == 'source_network':
                        print(f"  Source Network: {value}")
                    elif key == 'destination_network':
                        print(f"  Destination Network: {value}")
                    elif key == 'attestation_url':
                        print(f"  Attestation URL: {value}")
                    else:
                        print(f"  {key}: {value}")
                    
            # Show resource data
            if result.resource_data:
                print(f"\n🎁 Resource Data Received from Server:")
                print(f"=" * 60)
                import json
                if isinstance(result.resource_data, dict):
                    print(json.dumps(result.resource_data, indent=2))
                else:
                    print(result.resource_data)
                print("=" * 60)
        else:
            print("❌ CCTP Cross-Chain Payment Failed!")
            print("=" * 60)
            print(f"Error: {result.error}")
            if result.metadata:
                print(f"\nMetadata:")
                for key, value in result.metadata.items():
                    print(f"  {key}: {value}")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"\n💥 Exception: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
