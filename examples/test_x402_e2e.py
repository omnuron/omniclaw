import asyncio
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock

# Mock external dependencies that might be missing in simulation env
mock_circle = MagicMock()
sys.modules["circle"] = mock_circle
sys.modules["circle.web3"] = mock_circle
sys.modules["circle.web3.developer_controlled_wallets"] = mock_circle
sys.modules["circle.web3.utils"] = mock_circle

# Add src to path if running from root
sys.path.append(os.path.abspath("omniagentpay/src"))

from omniagentpay import OmniAgentPay
from omniagentpay.wallet.service import TransferResult
from omniagentpay.core.types import TransactionInfo, TransactionState

async def main():
    print("🚀 Starting x402 E2E Client Test...")
    
    # 1. Initialize Client (with mocks where needed)
    # We mock the wallet service's transfer method to avoid needing real funds/keys
    client = OmniAgentPay(circle_api_key="sk_test_mock", entity_secret="mock_secret")
    
    # Mock the transfer method to return success immediately
    mock_tx = TransactionInfo(
        id="tx_mock_123",
        amounts=["0.1"],
        destination_address="0x8979313437651086C21235D62DD8685e13D30B9f",
        # token_id="USDC", # TransactionInfo expects explicit listing, simplified here
        state=TransactionState.COMPLETE,
        tx_hash="0xMockTransactionHashForE2E",
        blockchain="ETH-SEPOLIA"
    )
    
    mock_result = TransferResult(
        success=True,
        transaction=mock_tx,
        tx_hash="0xMockTransactionHashForE2E"
    )
    
    # Inject mock into the adapter's wallet service
    # The client initializes adapters internally, so we need to patch the wallet service used by the x402 adapter
    # A cleaner way for E2E is to patch the wallet service passed to the client or generic patching
    
    # We will patch the specific wallet service instance capable of transfer
    # Since we can't easily reach into the client's private adapter list from outside without knowing implementation details,
    # we'll use unittest.mock.patch on the class method for this run context.
    
    from omniagentpay.wallet.service import WalletService
    
    # We'll create a dummy wallet for the "get_wallet" call too
    mock_wallet = MagicMock()
    mock_wallet.address = "0xClientWallet"
    
    with (
        patch.object(WalletService, 'transfer', return_value=mock_result),
        patch.object(WalletService, 'get_wallet', return_value=mock_wallet),
        patch.object(WalletService, 'get_usdc_balance_amount', return_value=Decimal("100.0"))
    ):
        target_url = "http://localhost:8000/premium"
        print(f"📡 Requesting: {target_url}")
        
        # 2. Execute Payment Request
        # Any wallet ID works since we mocked the service
        try:
            result = await client.pay(
                wallet_id="wallet-123", # Mock ID
                recipient=target_url,
                amount=Decimal("1.0")
            )
            
            # 3. Verify Result
            if result.success:
                print("\n✅ Payment Successful!")
                print(f"   Resource Data: {result.metadata.get('response_body')}")
                print(f"   Payment Proof: {result.metadata.get('payment_response')}")
                print(f"   Tx Hash: {result.blockchain_tx}")
            else:
                print("\n❌ Payment Failed!")
                print(f"   Error: {result.error}")
                print(f"   Metadata: {result.metadata}")
                
        except Exception as e:
            print(f"\n💥 Exception: {e}")

if __name__ == "__main__":
    from unittest.mock import patch
    asyncio.run(main())
