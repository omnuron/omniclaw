"""
x402 Demo Test Script

Tests both same-chain and cross-chain x402 payments:
1. Same-chain: ARC-TESTNET → ARC-TESTNET (direct transfer)
2. Cross-chain: ARC-TESTNET → BASE-SEPOLIA (CCTP routing)
"""
import asyncio
import os
import sys
from decimal import Decimal

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omniclaw import OmniClaw
from omniclaw.core.types import Network


# Configuration - UPDATE THESE WITH YOUR WALLET IDs FROM demo_wallets.txt
AGENT_WALLET_ID = "your-agent-wallet-id-here"  # ARC-TESTNET
SELLER_ARC_ADDRESS = "your-seller-arc-address-here"  # ARC-TESTNET
SELLER_BASE_ADDRESS = "your-seller-base-address-here"  # BASE-SEPOLIA


async def test_same_chain(client: OmniClaw):
    """Test same-chain x402 payment (ARC → ARC)"""
    print("\n" + "="*60)
    print("TEST 1: Same-Chain Payment (ARC-TESTNET → ARC-TESTNET)")
    print("="*60 + "\n")
    
    # For this test, we'll simulate an x402 server response
    # In a real scenario, you'd run the x402_server.py and point to it
    
    print(f"Agent Wallet: {AGENT_WALLET_ID}")
    print(f"Seller Address: {SELLER_ARC_ADDRESS}")
    print(f"Network: ARC-TESTNET (same chain)")
    
    # Direct transfer test
    print("\n📤 Executing direct transfer (same network)...")
    try:
        result = await client.pay(
            wallet_id=AGENT_WALLET_ID,
            recipient=SELLER_ARC_ADDRESS,
            amount=Decimal("0.5"),  # 0.5 USDC
            source_network=Network.ARC_TESTNET,
            destination_chain=Network.ARC_TESTNET,  # Same network
        )
        
        if result.success:
            print("\n✅ Same-chain payment successful!")
            print(f"   Transaction ID: {result.transaction_id}")
            print(f"   Blockchain Tx: {result.blockchain_tx}")
            print(f"   Method: {result.method.value}")
            print(f"   Status: {result.status.value}")
            if result.metadata:
                print(f"   Note: {result.metadata.get('note', 'N/A')}")
        else:
            print("\n❌ Same-chain payment failed!")
            print(f"   Error: {result.error}")
    
    except Exception as e:
        print(f"\n💥 Exception: {e}")


async def test_cross_chain(client: OmniClaw):
    """Test cross-chain x402 payment (ARC → BASE via CCTP)"""
    print("\n" + "="*60)
    print("TEST 2: Cross-Chain Payment (ARC-TESTNET → BASE-SEPOLIA)")
    print("="*60 + "\n")
    
    print(f"Agent Wallet: {AGENT_WALLET_ID}")
    print(f"Seller Address: {SELLER_BASE_ADDRESS}")
    print(f"Route: ARC-TESTNET → BASE-SEPOLIA (via CCTP)")
    
    print("\n📤 Executing cross-chain transfer...")
    try:
        result = await client.pay(
            wallet_id=AGENT_WALLET_ID,
            recipient=SELLER_BASE_ADDRESS,
            amount=Decimal("0.5"),  # 0.5 USDC
            source_network=Network.ARC_TESTNET,
            destination_chain=Network.BASE_SEPOLIA,  # Different network
        )
        
        if result.success:
            print("\n✅ Cross-chain payment initiated!")
            print(f"   Transaction ID: {result.transaction_id}")
            print(f"   Blockchain Tx: {result.blockchain_tx}")
            print(f"   Method: {result.method.value}")
            print(f"   Status: {result.status.value}")
            
            # CCTP metadata
            if result.metadata:
                print(f"\n   CCTP Details:")
                print(f"   - Version: {result.metadata.get('cctp_version', 'N/A')}")
                print(f"   - Transfer Mode: {result.metadata.get('transfer_mode', 'N/A')}")
                print(f"   - Source Network: {result.metadata.get('source_network', 'N/A')}")
                print(f"   - Dest Network: {result.metadata.get('destination_network', 'N/A')}")
                print(f"   - Attestation URL: {result.metadata.get('attestation_url', 'N/A')}")
        else:
            print("\n❌ Cross-chain payment failed!")
            print(f"   Error: {result.error}")
            
            # Check if it's because ARC doesn't support CCTP yet
            if "not supported by CCTP" in str(result.error):
                print("\n   ℹ️  This is expected - Circle doesn't support CCTP on ARC yet")
                print("   We'll add support once Circle enables it")
    
    except Exception as e:
        print(f"\n💥 Exception: {e}")


async def main():
    api_key = os.getenv("CIRCLE_API_KEY")
    entity_secret = os.getenv("CIRCLE_ENTITY_SECRET")
    
    if not api_key or not entity_secret:
        print("❌ Error: CIRCLE_API_KEY and CIRCLE_ENTITY_SECRET must be set")
        return
    
    # Check if wallet IDs are configured
    if "your-" in AGENT_WALLET_ID or "your-" in SELLER_ARC_ADDRESS:
        print("❌ Error: Please update the wallet IDs and addresses in this script")
        print("   Check demo_wallets.txt for the values")
        return
    
    print("🚀 Starting x402 Demo Tests")
    
    client = OmniClaw(
        circle_api_key=api_key,
        entity_secret=entity_secret,
    )
    
    # Check balance
    print("\n💰 Checking agent wallet balance...")
    try:
        balance = client.get_usdc_balance(AGENT_WALLET_ID)
        print(f"   Balance: {balance} USDC")
        
        if balance < Decimal("1.0"):
            print("\n⚠️  Warning: Low balance! Please fund the agent wallet first.")
            print("   You need at least 1 USDC for both tests")
            return
    except Exception as e:
        print(f"   ⚠️  Could not check balance: {e}")
    
    # Run tests
    await test_same_chain(client)
    await test_cross_chain(client)
    
    print("\n" + "="*60)
    print("✅ Demo Tests Complete!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
