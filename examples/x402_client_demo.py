"""
x402 Client - Real Demo Test

Tests x402 payment flow with real wallets and USDC.

Usage:
    python x402_client_demo.py
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


# Configuration
AGENT_WALLET_ID = "1c111395-984e-530d-a936-342053146971"  # ARC-TESTNET (funded with 20 USDC)
SERVER_URL = "http://localhost:8402/premium"


async def main():
    api_key = os.getenv("CIRCLE_API_KEY")
    entity_secret = os.getenv("ENTITY_SECRET")
    
    if not api_key or not entity_secret:
        print("❌ Error: CIRCLE_API_KEY and ENTITY_SECRET must be set")
        return
    
    print("=" * 60)
    print("🚀 x402 Client Demo Test")
    print("=" * 60)
    
    client = OmniClaw(
        circle_api_key=api_key,
        entity_secret=entity_secret,
        network=Network.ARC_TESTNET,
    )
    
    # Check balance
    print(f"\n💰 Checking wallet balance...")
    try:
        balance = await client.get_balance(AGENT_WALLET_ID)
        print(f"   Agent Wallet: {balance} USDC")
        
        if balance < Decimal("0.1"):
            print("   ⚠️  Insufficient balance for test!")
            return
    except Exception as e:
        print(f"   ⚠️  Could not check balance: {e}")
    
    # Make x402 payment request
    print(f"\n📡 Requesting: {SERVER_URL}")
    print(f"   This will:")
    print(f"   1. GET {SERVER_URL}")
    print(f"   2. Receive 402 Payment Required")
    print(f"   3. Parse payment requirements")
    print(f"   4. Transfer USDC to seller")
    print(f"   5. Submit payment proof")
    print(f"   6. Receive premium content\n")
    
    try:
        result = await client.pay(
            wallet_id=AGENT_WALLET_ID,
            recipient=SERVER_URL,
            amount=Decimal("1.0"),  # Max willing to pay
        )
        
        print("\n" + "=" * 60)
        if result.success:
            print("✅ Payment Successful!")
            print("=" * 60)
            print(f"Transaction ID: {result.transaction_id}")
            print(f"Blockchain Tx: {result.blockchain_tx}")
            print(f"Amount Paid: {result.amount} USDC")
            print(f"Method: {result.method.value}")
            print(f"Status: {result.status.value}")
            
            if result.metadata:
                print(f"\n📋 Payment Metadata:")
                for key, value in result.metadata.items():
                    if key == 'http_status':
                        print(f"  HTTP Status: {value}")
                    elif key == 'payment_response':
                        print(f"  Payment Response: {value}")
                    elif key == 'cross_chain':
                        print(f"  Cross-chain: {value}")
                    else:
                        print(f"  {key}: {value}")
                    
            # Show resource data if present (the actual API response from server)
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
            print("❌ Payment Failed!")
            print("=" * 60)
            print(f"Error: {result.error}")
            if result.metadata:
                print(f"Metadata: {result.metadata}")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"\n💥 Exception: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
