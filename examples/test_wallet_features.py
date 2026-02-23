"""
Test Example: Wallet Management Features

This script tests all wallet management features documented in the README.
Each function can be run individually to verify the SDK works correctly.

Usage:
    python test_wallet_features.py

Make sure you have CIRCLE_API_KEY set in your environment or .env file.
"""

import asyncio
import logging

from dotenv import load_dotenv

load_dotenv()

from omniclaw import Network, OmniClaw  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# Initialize client (reused across all tests)
try:
    client = OmniClaw(network=Network.ARC_TESTNET, log_level=logging.INFO)
except Exception as e:
    print(f"\n[FAILED] Initialization Error: {e}")
    exit(1)


# ============================================================
# WALLET SET OPERATIONS
# ============================================================


async def test_create_wallet_set():
    """Test creating a new wallet set."""
    print("\n" + "=" * 50)
    print("TEST: Create Wallet Set")
    print("=" * 50)

    wallet_set = await client.create_wallet_set(name="test-set-001")

    print("[OK] Created wallet set:")
    print(f"  ID: {wallet_set.id}")
    if wallet_set.name:
        print(f"  Name: {wallet_set.name}")

    return wallet_set


async def test_list_wallet_sets():
    """Test listing all wallet sets."""
    print("\n" + "=" * 50)
    print("TEST: List Wallet Sets")
    print("=" * 50)

    wallet_sets = await client.list_wallet_sets()

    print(f"[OK] Found {len(wallet_sets)} wallet set(s):")
    for ws in wallet_sets[:5]:  # Show first 5
        name_display = ws.name if ws.name else "(unnamed)"
        print(f"  - {ws.id}: {name_display}")

    if len(wallet_sets) > 5:
        print(f"  ... and {len(wallet_sets) - 5} more")

    return wallet_sets


# ============================================================
# WALLET OPERATIONS
# ============================================================


async def test_create_wallet(wallet_set_id: str = None):
    """Test creating a new wallet."""
    print("\n" + "=" * 50)
    print("TEST: Create Wallet")
    print("=" * 50)

    if not wallet_set_id:
        # Create a new set first
        wallet_set = await client.create_wallet_set(name="wallet-test-set")
        wallet_set_id = wallet_set.id
        print(f"  (Created new wallet set: {wallet_set_id})")

    wallet = await client.create_wallet(wallet_set_id=wallet_set_id, blockchain=Network.ARC_TESTNET)

    print("[OK] Created wallet:")
    print(f"  ID: {wallet.id}")
    print(f"  Address: {wallet.address}")
    print(f"  Blockchain: {wallet.blockchain}")

    return wallet


async def test_list_wallets(wallet_set_id: str = None):
    """Test listing wallets."""
    print("\n" + "=" * 50)
    print("TEST: List Wallets")
    print("=" * 50)

    wallets = await client.list_wallets(wallet_set_id=wallet_set_id)

    if wallet_set_id:
        print(f"[OK] Found {len(wallets)} wallet(s) in set {wallet_set_id[:8]}...:")
    else:
        print(f"[OK] Found {len(wallets)} wallet(s) total:")

    for w in wallets[:5]:  # Show first 5
        print(f"  - {w.id[:16]}... | {w.address[:10]}...{w.address[-6:]} | {w.blockchain}")

    if len(wallets) > 5:
        print(f"  ... and {len(wallets) - 5} more")

    return wallets


async def test_get_wallet(wallet_id: str):
    """Test getting a specific wallet."""
    print("\n" + "=" * 50)
    print("TEST: Get Wallet")
    print("=" * 50)

    wallet = await client.get_wallet(wallet_id)

    print("[OK] Retrieved wallet:")
    print(f"  ID: {wallet.id}")
    print(f"  Address: {wallet.address}")
    print(f"  Blockchain: {wallet.blockchain}")
    print(f"  Account Type: {wallet.account_type}")
    print(f"  State: {wallet.state}")

    return wallet


# ============================================================
# BALANCE OPERATIONS
# ============================================================


async def test_get_balance(wallet_id: str):
    """Test getting wallet balance."""
    print("\n" + "=" * 50)
    print("TEST: Get Balance")
    print("=" * 50)

    balance = await client.get_balance(wallet_id)

    print(f"[OK] Balance for {wallet_id[:16]}...:")
    print(f"  USDC: {balance}")

    return balance


# ============================================================
# AGENT/USER WALLET HELPERS
# ============================================================


async def test_create_agent_wallet():
    """Test creating an agent wallet (convenience method)."""
    print("\n" + "=" * 50)
    print("TEST: Create Agent Wallet")
    print("=" * 50)

    wallet_set, wallet = client.wallet.create_agent_wallet(agent_name="test-agent-001")

    print("[OK] Created agent wallet:")
    print(f"  Wallet Set ID: {wallet_set.id}")
    if wallet_set.name:
        print(f"  Wallet Set Name: {wallet_set.name}")
    print(f"  Wallet ID: {wallet.id}")
    print(f"  Wallet Address: {wallet.address}")

    return wallet_set, wallet


async def test_create_user_wallet():
    """Test creating a user wallet (convenience method)."""
    print("\n" + "=" * 50)
    print("TEST: Create User Wallet")
    print("=" * 50)

    wallet_set, wallet = client.wallet.create_user_wallet(user_id="user-12345")

    print("[OK] Created user wallet:")
    print(f"  Wallet Set ID: {wallet_set.id}")
    print(f"  Wallet Set Name: {wallet_set.name}")
    print(f"  Wallet ID: {wallet.id}")
    print(f"  Wallet Address: {wallet.address}")

    return wallet_set, wallet


# ============================================================
# FULL WALLET DETAILS
# ============================================================


async def test_get_all_balances(wallet_id: str):
    """Test getting all token balances for a wallet."""
    print("\n" + "=" * 50)
    print("TEST: Get All Balances")
    print("=" * 50)

    balances = client.wallet.get_balances(wallet_id)

    print(f"[OK] All balances for {wallet_id[:16]}...:")
    if not balances:
        print("  (No balances found)")
    for bal in balances:
        print(f"  - {bal.token.symbol}: {bal.amount}")

    return balances


# ============================================================
# TRANSFER OPERATIONS
# ============================================================


async def test_transfer_usdc(wallet_id: str, destination: str = None, amount: str = "0.01"):
    """Test transferring USDC."""
    print("\n" + "=" * 50)
    print("TEST: Transfer USDC")
    print("=" * 50)

    if not destination:
        print("Enter destination address:")
        destination = input("  > ").strip()

    if not amount:
        print("Enter amount (default: 0.01):")
        amount_in = input("  > ").strip()
        if amount_in:
            amount = amount_in

    try:
        print(f"\nSending {amount} USDC from {wallet_id[:8]}... to {destination[:8]}...")

        result = await client.pay(
            wallet_id=wallet_id, recipient=destination, amount=amount, wait_for_completion=True
        )

        if result.success:
            print("[OK] Transfer Successful!")
            print(f"  Transaction Hash: {result.blockchain_tx}")
        else:
            print(f"[FAILED] Transfer Failed: {result.error}")

        return result

    except Exception as e:
        print(f"[ERROR] Transfer Exception: {e}")
        return None


# ============================================================
# GUARD & LEDGER OPERATIONS
# ============================================================


async def test_list_transactions(wallet_id: str):
    """Test listing transactions."""
    print("\n" + "=" * 50)
    print("TEST: List Transactions")
    print("=" * 50)

    txs = await client.list_transactions(wallet_id=wallet_id)

    print(f"[OK] Found {len(txs)} transaction(s):")
    for tx in txs[:10]:
        print(f"  - {tx.state.value} | {tx.tx_hash[:10]}... | {tx.amounts}")

    return txs


async def test_list_ledger(wallet_id: str):
    """Test viewing ledger entries."""
    print("\n" + "=" * 50)
    print("TEST: List Ledger")
    print("=" * 50)

    entries = await client.ledger.query(wallet_id=wallet_id, limit=20)

    print(f"[OK] Found {len(entries)} ledger entry(s):")
    for entry in entries:
        print(
            f"  - {entry.timestamp} | {entry.entry_type.value} | {entry.status.value} | {entry.amount} -> {entry.recipient[:8]}..."
        )

    return entries


async def test_add_budget_guard(wallet_id: str):
    """Test adding a budget guard."""
    print("\n" + "=" * 50)
    print("TEST: Add Budget Guard")
    print("=" * 50)

    print("Enter Daily Limit (USDC) [start w/ 10]:")
    daily = input("  > ").strip() or "10"

    await client.add_budget_guard(wallet_id=wallet_id, daily_limit=daily, name="daily_budget")
    print(f"[OK] Added budget guard with daily limit: {daily} USDC")


async def test_list_guards(wallet_id: str):
    """Test listing guards."""
    print("\n" + "=" * 50)
    print("TEST: List Guards")
    print("=" * 50)

    guards = await client.list_guards(wallet_id)

    print(f"[OK] Active Guards for {wallet_id[:8]}...:")
    for g in guards:
        print(f"  - {g}")

    return guards


# ============================================================
# RUN ALL TESTS
# ============================================================


async def run_all_tests():
    """Run all wallet management tests in sequence."""
    print("\n" + "#" * 60)
    print("#  OMNICLAW WALLET MANAGEMENT TEST SUITE")
    print("#" * 60)

    try:
        # 1. Wallet Set Operations
        wallet_set = await test_create_wallet_set()
        await test_list_wallet_sets()

        # 2. Wallet Operations
        wallet = await test_create_wallet(wallet_set.id)
        await test_list_wallets(wallet_set.id)
        await test_get_wallet(wallet.id)

        # 3. Balance Operations
        await test_get_balance(wallet.id)
        await test_get_all_balances(wallet.id)

        # 4. Convenience Methods
        await test_create_agent_wallet()
        await test_create_user_wallet()

        print("\n" + "#" * 60)
        print("#  ALL TESTS PASSED")
        print("#" * 60)

    except Exception as e:
        print(f"\n[FAILED] TEST FAILED: {e}")
        raise


# ============================================================
# INTERACTIVE MENU
# ============================================================


def print_menu():
    """Print interactive menu."""
    print("\n" + "=" * 50)
    print("OMNICLAW WALLET MANAGEMENT TESTER")
    print("=" * 50)
    print("1. Create Wallet Set")
    print("2. List Wallet Sets")
    print("3. Create Wallet")
    print("4. List Wallets")
    print("5. Get Wallet (requires wallet_id)")
    print("6. Get Balance (requires wallet_id)")
    print("7. Create Agent Wallet")
    print("8. Create User Wallet")
    print("9. Run All Tests")
    print("9. Run All Tests")
    print("10. Transfer USDC (requires wallet_id)")
    print("11. Set Active Wallet Set (requires wallet_set_id)")
    print("12. List Transactions (requires wallet_id)")
    print("13. View Ledger (requires wallet_id)")
    print("14. Add Budget Guard (requires wallet_id)")
    print("15. List Guards (requires wallet_id)")
    print("0. Exit")
    print("-" * 50)


async def interactive_mode():
    """Run in interactive mode."""
    wallet_id = None
    wallet_set_id = None

    while True:
        print_menu()
        if wallet_id:
            print(f"Current wallet: {wallet_id[:16]}...")
        if wallet_set_id:
            print(f"Current wallet set: {wallet_set_id[:16]}...")

        choice = input("\nEnter choice (0-15): ").strip()

        try:
            if choice == "1":
                ws = await test_create_wallet_set()
                wallet_set_id = ws.id

            elif choice == "2":
                await test_list_wallet_sets()

            elif choice == "3":
                if not wallet_set_id:
                    print(
                        "Enter Wallet Set ID to create wallet in (or press Enter to create new set):"
                    )
                    inp_sid = input("  > ").strip()
                    if inp_sid:
                        wallet_set_id = inp_sid

                w = await test_create_wallet(wallet_set_id)
                wallet_id = w.id

            elif choice == "4":
                await test_list_wallets(wallet_set_id)

            elif choice == "5":
                if not wallet_id:
                    wallet_id = input("Enter wallet ID: ").strip()
                await test_get_wallet(wallet_id)

            elif choice == "6":
                if not wallet_id:
                    wallet_id = input("Enter wallet ID: ").strip()
                await test_get_balance(wallet_id)

            elif choice == "7":
                ws, w = await test_create_agent_wallet()
                wallet_set_id = ws.id
                wallet_id = w.id

            elif choice == "8":
                ws, w = await test_create_user_wallet()
                wallet_set_id = ws.id
                wallet_id = w.id

            elif choice == "9":
                await run_all_tests()

            elif choice == "10":
                if not wallet_id:
                    wallet_id = input("Enter source wallet ID: ").strip()
                await test_transfer_usdc(wallet_id)

            elif choice == "11":
                wallet_set_id = input("Enter Wallet Set ID: ").strip()

            elif choice == "12":
                if not wallet_id:
                    wallet_id = input("Enter wallet ID: ").strip()
                await test_list_transactions(wallet_id)

            elif choice == "13":
                if not wallet_id:
                    wallet_id = input("Enter wallet ID: ").strip()
                await test_list_ledger(wallet_id)

            elif choice == "14":
                if not wallet_id:
                    wallet_id = input("Enter wallet ID: ").strip()
                await test_add_budget_guard(wallet_id)

            elif choice == "15":
                if not wallet_id:
                    wallet_id = input("Enter wallet ID: ").strip()
                await test_list_guards(wallet_id)

            elif choice == "0":
                print("\nGoodbye!")
                break

            else:
                print("Invalid choice. Please enter 0-9.")

        except Exception as e:
            print(f"\n[ERROR] {e}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        # Run all tests automatically
        asyncio.run(run_all_tests())
    else:
        # Interactive mode
        asyncio.run(interactive_mode())
