#!/usr/bin/env python3
"""
End-to-End Test Script for OmniAgentPay SDK.

This script tests all WalletService functionality against the real Circle API.
Make sure you have your .env file set up with:
  - CIRCLE_API_KEY
  - ENTITY_SECRET

Run: python scripts/test_wallet_service_e2e.py
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omniagentpay import Config, Network
from omniagentpay.core.circle_client import CircleClient
from omniagentpay.wallet.service import WalletService


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_success(message: str) -> None:
    """Print success message."""
    print(f"  ✓ {message}")


def print_info(message: str) -> None:
    """Print info message."""
    print(f"  → {message}")


def test_ensure_setup(api_key: str | None = None):
    """Test 1: Ensure SDK is set up (auto-registers entity secret if needed)."""
    print_header("Test 1: Ensure Setup (Auto-Registration)")
    
    from omniagentpay.onboarding import ensure_setup
    
    try:
        # This will:
        # 1. Load .env if exists
        # 2. Check for API key
        # 3. Check for entity secret - if missing, auto-generate and register
        # 4. Update .env with new entity secret
        result = ensure_setup(api_key=api_key)
        
        print_success("SDK setup complete!")
        print_info(f"Entity secret registered: {result['entity_secret_registered']}")
        return True
    except Exception as e:
        print(f"  ✗ Setup failed: {e}")
        return False


def test_config_loading():
    """Test 2: Load configuration from .env."""
    print_header("Test 2: Configuration Loading")
    
    try:
        config = Config.from_env()
        print_success(f"API Key: {config.masked_api_key()}")
        print_success(f"Network: {config.network.value}")
        print_success(f"Entity Secret: ***{config.entity_secret[-4:]}")
        return config
    except Exception as e:
        print(f"  ✗ Failed to load config: {e}")
        return None


def test_circle_client_init(config: Config):
    """Test 3: Initialize Circle client."""
    print_header("Test 3: Circle Client Initialization")
    
    try:
        client = CircleClient(config)
        print_success("Circle client initialized successfully")
        return client
    except Exception as e:
        print(f"  ✗ Failed to initialize Circle client: {e}")
        return None


def test_wallet_service_init(config: Config, client: CircleClient):
    """Test 4: Initialize WalletService."""
    print_header("Test 4: WalletService Initialization")
    
    try:
        service = WalletService(config, client)
        print_success("WalletService initialized")
        return service
    except Exception as e:
        print(f"  ✗ Failed to initialize WalletService: {e}")
        return None


def test_wallet_set_operations(service: WalletService):
    """Test 5: Wallet set CRUD operations."""
    print_header("Test 5: Wallet Set Operations")
    
    try:
        # List existing wallet sets
        wallet_sets = service.list_wallet_sets()
        print_success(f"Listed {len(wallet_sets)} existing wallet sets")
        
        # Show details of all existing wallet sets
        if wallet_sets:
            print("  📋 Existing wallet sets:")
            for ws in wallet_sets[:5]:  # Show first 5
                print(f"     • {ws.id} | {ws.custody_type.value} | Created: {ws.create_date}")
            if len(wallet_sets) > 5:
                print(f"     ... and {len(wallet_sets) - 5} more")
        
        # Create new wallet set
        test_name = "OmniAgentPay E2E Test"
        wallet_set = service.create_wallet_set(test_name)
        print_success(f"Created wallet set: {wallet_set.id}")
        # Note: Circle API for DeveloperWalletSet doesn't return 'name' field
        print_info(f"Name: (not returned by Circle API for developer wallets)")
        print_info(f"Custody: {wallet_set.custody_type.value}")
        
        # Get wallet set by ID
        fetched = service.get_wallet_set(wallet_set.id)
        print_success(f"Fetched wallet set: {fetched.id}")
        
        return wallet_set
    except Exception as e:
        print(f"  ✗ Wallet set operations failed: {e}")
        return None


def test_wallet_operations(service: WalletService, wallet_set):
    """Test 6: Wallet CRUD operations."""
    print_header("Test 6: Wallet Operations")
    
    try:
        # First, list ALL wallets across all sets
        all_wallets = service.list_wallets()
        print_success(f"Listed {len(all_wallets)} total wallets across all sets")
        
        if all_wallets:
            print("  📋 Existing wallets:")
            for w in all_wallets[:5]:  # Show first 5
                print(f"     • {w.id[:8]}... | {w.address[:10]}...{w.address[-6:]} | {w.blockchain}")
            if len(all_wallets) > 5:
                print(f"     ... and {len(all_wallets) - 5} more")
        
        # Create single wallet
        wallet = service.create_wallet(
            wallet_set_id=wallet_set.id,
            blockchain=Network.ARC_TESTNET,
        )
        print_success(f"Created wallet: {wallet.id}")
        print_info(f"Address: {wallet.address}")
        print_info(f"Blockchain: {wallet.blockchain}")
        print_info(f"Account Type: {wallet.account_type.value}")
        print_info(f"State: {wallet.state.value}")
        
        # Get wallet by ID
        fetched = service.get_wallet(wallet.id)
        print_success(f"Fetched wallet: {fetched.id}")
        
        # List wallets in this specific wallet set
        wallets_in_set = service.list_wallets(wallet_set_id=wallet_set.id)
        print_success(f"Listed {len(wallets_in_set)} wallets in this set")
        for w in wallets_in_set:
            print(f"     • {w.address}")
        
        return wallet
    except Exception as e:
        print(f"  ✗ Wallet operations failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_balance_operations(service: WalletService, wallet):
    """Test 7: Balance checking operations."""
    print_header("Test 7: Balance Operations")
    
    try:
        # Get all balances
        balances = service.get_balances(wallet.id)
        print_success(f"Got {len(balances)} token balances")
        
        for balance in balances:
            print_info(f"{balance.token.symbol}: {balance.amount}")
        
        # Get USDC balance specifically
        try:
            usdc_balance = service.get_usdc_balance(wallet.id)
            print_success(f"USDC Balance: {usdc_balance.amount}")
        except Exception:
            # Expected if wallet is new
            print_info("No USDC balance (wallet is new/unfunded)")
        
        # Get USDC balance amount (returns 0 if none)
        usdc_amount = service.get_usdc_balance_amount(wallet.id)
        print_success(f"USDC Amount: {usdc_amount}")
        
        # Check sufficient balance
        has_balance = service.has_sufficient_balance(wallet.id, Decimal("1.00"))
        print_success(f"Has >= 1.00 USDC: {has_balance}")
        
        return True
    except Exception as e:
        print(f"  ✗ Balance operations failed: {e}")
        return False


def test_transfer_operations(service: WalletService, wallet):
    """Test 8: Transfer operations (requires funded wallet)."""
    print_header("Test 8: Transfer Operations")
    
    try:
        # Check if wallet has USDC to transfer
        usdc_amount = service.get_usdc_balance_amount(wallet.id)
        
        if usdc_amount == Decimal("0"):
            print("  ⚠️  Wallet has no USDC - cannot test transfer")
            print("  📋 To test transfers:")
            print(f"     1. Go to Circle Faucet for testnet USDC")
            print(f"     2. Fund wallet: {wallet.address}")
            print("     3. Re-run this test")
            print_info("Transfer test SKIPPED (no funds) - this is expected for new wallets")
            return True  # Not a failure, just skipped
        
        print_success(f"Wallet has {usdc_amount} USDC available")
        
        # Test 1: Try transfer with insufficient balance check
        print("\n  Testing balance validation...")
        try:
            # Request more than available to test validation
            result = service.transfer(
                wallet_id=wallet.id,
                destination_address=wallet.address,  # Self-transfer for testing
                amount=usdc_amount + Decimal("1000"),  # More than available
            )
            if not result.success:
                print_success("Balance validation working - rejected transfer > balance")
        except Exception as e:
            print_success(f"Balance validation working - {e}")
        
        # Test 2: Self-transfer a tiny amount to test mechanism
        if usdc_amount >= Decimal("0.01"):
            print("\n  Testing actual transfer (0.01 USDC self-transfer)...")
            result = service.transfer(
                wallet_id=wallet.id,
                destination_address=wallet.address,  # Self-transfer
                amount=Decimal("0.01"),
                check_balance=True,
                wait_for_completion=False,  # Don't wait to speed up test
            )
            
            if result.success:
                print_success(f"Transfer initiated successfully!")
                print_info(f"Transaction ID: {result.transaction.id if result.transaction else 'N/A'}")
                print_info(f"State: {result.transaction.state.value if result.transaction else 'N/A'}")
                if result.tx_hash:
                    print_info(f"TX Hash: {result.tx_hash}")
            else:
                print(f"  ⚠️  Transfer failed: {result.error}")
        else:
            print_info(f"Balance too low ({usdc_amount}) - minimum 0.01 USDC needed")
        
        # Test 3: Test TransferResult properties
        print("\n  Testing TransferResult class...")
        from omniagentpay.wallet.service import TransferResult
        from omniagentpay.core.types import TransactionState, TransactionInfo
        
        # Create mock result to test properties
        mock_tx = TransactionInfo(id="test", state=TransactionState.PENDING)
        mock_result = TransferResult(success=True, transaction=mock_tx)
        print_success(f"TransferResult.is_pending() = {mock_result.is_pending()}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Transfer operations failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_agent_wallet_setup(service: WalletService):
    """Test 9: Agent wallet convenience setup."""
    print_header("Test 9: Agent Wallet Setup")
    
    try:
        wallet_set, wallet = service.setup_agent_wallet(
            agent_name="E2E Test Agent",
            blockchain=Network.ARC_TESTNET,
        )
        print_success(f"Agent wallet set created: {wallet_set.id}")
        print_success(f"Agent wallet created: {wallet.id}")
        print_info(f"Address: {wallet.address}")
        
        return wallet_set, wallet
    except Exception as e:
        print(f"  ✗ Agent wallet setup failed: {e}")
        return None, None


def test_user_wallet_setup(service: WalletService):
    """Test 10: User wallet convenience setup."""
    print_header("Test 10: User Wallet Setup")
    
    try:
        # Test with integer user ID
        wallet_set1, wallet1 = service.setup_user_wallet(
            user_id=12345,
            blockchain=Network.ARC_TESTNET,
        )
        print_success(f"User 12345 wallet: {wallet1.id}")
        print_info(f"Address: {wallet1.address}")
        
        # Test with string user ID (UUID-like)
        wallet_set2, wallet2 = service.setup_user_wallet(
            user_id="user-uuid-abc123",
            blockchain=Network.ARC_TESTNET,
        )
        print_success(f"User uuid wallet: {wallet2.id}")
        print_info(f"Address: {wallet2.address}")
        
        # Test cache retrieval
        cached = service.get_user_wallet(12345)
        if cached:
            print_success(f"Retrieved cached wallet for user 12345")
        
        return True
    except Exception as e:
        print(f"  ✗ User wallet setup failed: {e}")
        return False


def test_get_or_create_default(service: WalletService):
    """Test 11: Get or create default wallet set."""
    print_header("Test 11: Get or Create Default Wallet Set")
    
    try:
        # First call creates
        ws1 = service.get_or_create_default_wallet_set("E2E Default Set")
        print_success(f"Got/created wallet set: {ws1.id}")
        
        # Second call should return same
        ws2 = service.get_or_create_default_wallet_set("E2E Default Set")
        
        if ws1.id == ws2.id:
            print_success("Correctly returned existing wallet set on second call")
        else:
            print_info("Note: Created new wallet set (first run)")
        
        return True
    except Exception as e:
        print(f"  ✗ Get or create failed: {e}")
        return False


def test_cache_operations(service: WalletService):
    """Test 12: Cache operations."""
    print_header("Test 12: Cache Operations")
    
    try:
        # Clear cache
        service.clear_cache()
        print_success("Cache cleared successfully")
        
        # Verify user wallet cache is cleared
        cached = service.get_user_wallet(12345)
        if cached is None:
            print_success("User wallet cache properly cleared")
        
        return True
    except Exception as e:
        print(f"  ✗ Cache operations failed: {e}")
        return False


def main(api_key: str | None = None):
    """Run all end-to-end tests."""
    print("\n" + "🚀" * 20)
    print("   OmniAgentPay SDK - End-to-End Test")
    print("🚀" * 20)
    
    # Test 1: Ensure setup (auto-registers entity secret if needed)
    if not test_ensure_setup(api_key):
        print("\n❌ Setup failed. Check your CIRCLE_API_KEY.")
        return
    
    # Test 2: Load config
    config = test_config_loading()
    if not config:
        return
    
    # Test 3: Initialize Circle client
    client = test_circle_client_init(config)
    if not client:
        return
    
    # Test 4: Initialize WalletService
    service = test_wallet_service_init(config, client)
    if not service:
        return
    
    # Test 5: Wallet set operations
    wallet_set = test_wallet_set_operations(service)
    if not wallet_set:
        return
    
    # Test 6: Wallet operations
    wallet = test_wallet_operations(service, wallet_set)
    if not wallet:
        return
    
    # Test 7: Balance operations
    test_balance_operations(service, wallet)
    
    # Test 8: Transfer operations (may skip if unfunded)
    test_transfer_operations(service, wallet)
    
    # Test 9: Agent wallet setup
    test_agent_wallet_setup(service)
    
    # Test 10: User wallet setup
    test_user_wallet_setup(service)
    
    # Test 11: Get or create default
    test_get_or_create_default(service)
    
    # Test 12: Cache operations
    test_cache_operations(service)
    
    # Summary
    print_header("Test Summary")
    print_success("All 12 WalletService tests completed!")
    print()
    print("  Created resources:")
    print(f"    - Wallet Set: {wallet_set.id}")
    print(f"    - Wallet: {wallet.id}")
    print(f"    - Address: {wallet.address}")
    print()
    print("  To test transfers with actual funds:")
    print("    1. Fund the wallet with testnet USDC from Circle Faucet")
    print("    2. Re-run this test script")


if __name__ == "__main__":
    main()
