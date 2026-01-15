
import asyncio
import sys
from unittest.mock import MagicMock, AsyncMock
from decimal import Decimal

# Mock dependencies
sys.modules["circle"] = MagicMock()
sys.modules["circle.web3"] = MagicMock()

from omniagentpay import OmniAgentPay, Network
from omniagentpay.core.types import (
    PaymentMethod, PaymentResult, PaymentStatus,
    WalletInfo, WalletState, CustodyType, AccountType
)
from omniagentpay.wallet.service import WalletService

# Mock Config Env
import os
os.environ["CIRCLE_API_KEY"] = "sk_test_mock"
os.environ["ENTITY_SECRET"] = "mock_secret_hex_32_bytes"

async def test_routing():
    print("=== Testing Destination Chain Routing ===")
    
    # 1. Setup Client with Mocks
    client = OmniAgentPay(network=Network.ETH_SEPOLIA)
    
    # Mock WalletService to return a known wallet on ETH_SEPOLIA
    mock_wallet = WalletInfo(
        id="w-123",
        address="0x123", # valid EVM
        blockchain="ETH-SEPOLIA",
        state=WalletState.LIVE,
        wallet_set_id="ws-1",
        custody_type=CustodyType.DEVELOPER,
        account_type=AccountType.EOA,
    )
    client._wallet_service.get_wallet = MagicMock(return_value=mock_wallet)
    
    # Mock Guards to always pass
    client._guard_manager.check = AsyncMock(return_value=(True, None, []))
    client._guard_manager.record_spending = AsyncMock()
    
    # Mock Ledger record
    client._ledger.record = AsyncMock()
    client._ledger.update_status = AsyncMock()
    
    # Mock Adapters Execute to avoid real calls
    # We inspect which adapter was selected by checking client._router._find_adapter
    # Or just mock execute and return which method handled it.
    
    # Better: Inspect Router.detect_method results? 
    # But pay logic does _find_adapter.
    
    # Let's mock Router's pay method? No, we want to test Router logic.
    # We can inspect the RESULT. `PaymentResult` has `.method`.
    
    # But for this test, we must mock the ADAPTERS' execute methods.
    # The real adapters are instantiated in Router.
    # Let's access them.
    adapters = client._router.get_adapters()
    transfer_adapter = next(a for a in adapters if a.method == PaymentMethod.TRANSFER)
    gateway_adapter = next(a for a in adapters if a.method == PaymentMethod.CROSSCHAIN)
    
    transfer_adapter.execute = AsyncMock(return_value=PaymentResult(
        success=True, transaction_id="t-1", blockchain_tx="0xT", amount=Decimal(10), 
        recipient="0xR", method=PaymentMethod.TRANSFER, status=PaymentStatus.COMPLETED
    ))
    
    gateway_adapter.execute = AsyncMock(return_value=PaymentResult(
        success=True, transaction_id="g-1", blockchain_tx="0xG", amount=Decimal(10), 
        recipient="0xR", method=PaymentMethod.CROSSCHAIN, status=PaymentStatus.COMPLETED
    ))
    
    # --- Test Case 1: Same Chain (Implicit) ---
    print("\n1. Testing Implicit Same Chain (ETH-SEPOLIA -> ETH-SEPOLIA)")
    res = await client.pay(
        wallet_id="w-123", recipient="0xRecipient", amount=10, 
        skip_guards=True # simplify
    )
    print(f"   Method Used: {res.method}")
    assert res.method == PaymentMethod.TRANSFER
    
    # --- Test Case 2: Explicit Same Chain ---
    print("\n2. Testing Explicit Same Chain (dest=ETH-SEPOLIA)")
    res = await client.pay(
        wallet_id="w-123", recipient="0xRecipient", amount=10, 
        destination_chain=Network.ETH_SEPOLIA,
        skip_guards=True
    )
    print(f"   Method Used: {res.method}")
    assert res.method == PaymentMethod.TRANSFER

    # --- Test Case 3: Explicit Cross Chain (dest=BASE) ---
    print("\n3. Testing Explicit Cross Chain (dest=BASE)")
    # Note: Gateway supports BASE (mapped to Network.BASE)
    # Gateway should claim this.
    res = await client.pay(
        wallet_id="w-123", recipient="0xRecipient", amount=10, 
        destination_chain=Network.BASE,
        skip_guards=True
    )
    print(f"   Method Used: {res.method}")
    assert res.method == PaymentMethod.CROSSCHAIN

    # --- Test Case 4: Explicit Cross Chain (dest='base') String Alias ---
    print("\n4. Testing String Alias (dest='base')")
    res = await client.pay(
        wallet_id="w-123", recipient="0xRecipient", amount=10, 
        destination_chain="base",
        skip_guards=True
    )
    print(f"   Method Used: {res.method}")
    assert res.method == PaymentMethod.CROSSCHAIN
    
    print("\n✅ All Routing Tests Passed!")

if __name__ == "__main__":
    asyncio.run(test_routing())
