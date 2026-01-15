"""
Verification script for OmniAgentPay Core SDK.
Tests Client, Guards, Ledger, and Adapters integration.
"""
import asyncio
import os
import sys
from decimal import Decimal
# Force current directory into python path to ensure we use local package
sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv
load_dotenv()

from omniagentpay import (
    OmniAgentPay, Network, BudgetGuard, SingleTxGuard, 
    RecipientGuard, RateLimitGuard, GuardChain, PaymentStatus
)

async def main():
    print("🚀 Starting Core SDK Verification...")
    
    # 1. Initialize Client
    print("\n📦 Initializing OmniAgentPay Client...")
    api_key = os.environ.get("CIRCLE_API_KEY")
    entity_secret = os.environ.get("ENTITY_SECRET")
    
    if not api_key: # Entity secret might be optional if passed via env var implicitly loaded by Config? No, Config constructor takes it or reads env.
        # But let's check explicit env vars for script clarity
        pass # Client will handle it
        
    try:
        client = OmniAgentPay(
            network=Network.ARC_TESTNET
        )
        print("✅ Client initialized")
    except Exception as e:
        print(f"❌ Client initialization failed: {e}")
        sys.exit(1)

    # 2. Setup/Fetch Wallet
    print("\n💼 Setting up Wallet...")
    try:
        # We'll try to get the first available wallet or create one
        wallets = client.wallet.list_wallets()
        if wallets:
            wallet = wallets[0]
            print(f"✅ Found existing wallet: {wallet.id} ({wallet.address})")
            client.set_default_wallet(wallet.id)
        else:
            print("⚠️ No wallets found. Attempting to create one...")
            # We assume user has wallet set capability or we fail
            sys.exit("No wallets found. Please run e2e tests to setup wallet first.")
            
    except Exception as e:
        print(f"❌ Wallet setup failed: {e}")
        sys.exit(1)

    # 3. Configure Guards
    print("\n🛡️  Configuring Guards...")
    # Add a SingleTxGuard for 50 USDC
    # Add a BudgetGuard for 100 USDC daily
    client.add_guard(SingleTxGuard(max_amount=Decimal("50.00"), name="max_tx_50"))
    client.add_guard(BudgetGuard(daily_limit=Decimal("100.00"), name="daily_budget_100"))
    print("✅ Guards configured: SingleTx(50), Budget(100)")

    # 4. Test Guard Blocking (Simulation)
    print("\n🛑 Testing Guard Blocking (Simulation)...")
    
    # CASE A: Amount too high for SingleTxGuard
    # Valid 40-char EVM address (random)
    recipient = "0x742d35Cc6634C0532925a3b844Bc9e75952e342a" 
    amount_too_high = Decimal("60.00")
    
    print(f"   Attempting simulation of ${amount_too_high} (should fail due to MaxTx)...")
    sim_result = await client.simulate(recipient, amount_too_high)
    
    if not sim_result.would_succeed and "max_tx_50" in str(sim_result.reason):
        print(f"   ✅ Correctly blocked by SingleTxGuard: {sim_result.reason}")
    else:
        print(f"   ❌ Failed to block or wrong reason: {sim_result}")

    # 5. Test Ledger Recording with Blocking
    print("\n📒 Testing Ledger Recording (Blocked Payment)...")
    
    result = await client.pay(
        recipient=recipient, 
        amount=amount_too_high, 
        purpose="Testing Guard Blocking"
    )
    
    if result.status == PaymentStatus.BLOCKED:
         print(f"   ✅ Payment correctly blocked: {result.error}")
    else:
         print(f"   ❌ Payment went through or wrong status: {result.status}, {result.error}")

    # Check ledger
    entries = await client.ledger.query(limit=5)
    # Find our entry
    found_entry = None
    for e in entries:
        if str(e.amount) == str(amount_too_high) and e.purpose == "Testing Guard Blocking":
            found_entry = e
            break
            
    if found_entry:
        print(f"   ✅ Transaction recorded in ledger: {found_entry.status}")
    else:
        print(f"   ❌ Transaction not found in ledger")

    # 6. Test Valid Payment (Simulation)
    print("\n✅ Testing Valid Payment (Simulation)...")
    valid_amount = Decimal("1.00")
    sim_result_valid = await client.simulate(recipient, valid_amount)
    
    if sim_result_valid.would_succeed:
        print("   ✅ Simulation says payment would succeed")
    else:
        print(f"   ⚠️ Simulation failed: {sim_result_valid.reason}")
        # Not a failure of logic if it's balance related.
        if "Balance" in str(sim_result_valid.reason):
             print("      (Pass: Ledger/Guards passed, Balance check failed correctly)")

    print("\n🎉 Verification Complete!")

if __name__ == "__main__":
    asyncio.run(main())
