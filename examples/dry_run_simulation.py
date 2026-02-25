import asyncio
import os
from decimal import Decimal

from omniclaw.client import OmniClaw
from omniclaw.core.types import Network
from omniclaw.guards.budget import BudgetGuard
from omniclaw.guards.single_tx import SingleTxGuard


async def run_dry_run_simulation():
    print("🚀 Initializing OmniClaw for Dry Run Simulation...")
    # Initialize client (requires CIRCLE_API_KEY environment variable)
    client = OmniClaw(network=Network.ARC_TESTNET)

    # Note: Replace with an actual wallet ID from your Circle developer account
    wallet_id = os.environ.get("TEST_WALLET_ID", "dummy-wallet-id")
    recipient = "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0"

    print("\n🛡️ Configuring specific guards on the wallet...")
    await client.guards.add_guard(wallet_id, SingleTxGuard(max_amount=Decimal("50.00"), name="TxLimitGuard"))
    await client.guards.add_guard(wallet_id, BudgetGuard(daily_limit=Decimal("500.00"), name="DailyBudgetGuard"))

    print(f"\n🧪 Simulating payment of 10.00 USDC to {recipient}...")
    try:
        simulation = await client.simulate(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=Decimal("10.00"),
        )
        
        print("\n--- Simulation Results ---")
        print(f"Would Succeed:   {simulation.would_succeed}")
        print(f"Estimated Gas:   {simulation.estimated_gas}")
        print(f"Guards That Pass:{simulation.guards_that_pass}")
        print(f"Recipient Type:  {simulation.recipient_type}")
        print(f"Route:           {simulation.route.value}")
        
    except Exception as e:
        print(f"\n❌ Simulation failed unexpectedly: {e}")

    print(f"\n🧪 Simulating payment of 5000.00 USDC (Should be blocked by guards)...")
    try:
        simulation_blocked = await client.simulate(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=Decimal("5000.00"),
        )
        
        print("\n--- Simulation Results ---")
        print(f"Would Succeed:   {simulation_blocked.would_succeed}")
        print(f"Reason:          {simulation_blocked.reason}")
        print(f"Guards That Pass:{simulation_blocked.guards_that_pass}")
        
    except Exception as e:
        print(f"\n❌ Simulation failed unexpectedly: {e}")


if __name__ == "__main__":
    asyncio.run(run_dry_run_simulation())
