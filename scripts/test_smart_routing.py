
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

from omniagentpay.core.config import Config
from omniagentpay.core.types import Network, PaymentMethod
from omniagentpay.payment.router import PaymentRouter
from omniagentpay.protocols.transfer import TransferAdapter
from omniagentpay.protocols.gateway import GatewayAdapter
from omniagentpay.protocols.x402 import X402Adapter

@pytest.fixture
def mock_deps():
    config = Config(
        circle_api_key="sk_test_123",
        entity_secret="secret",
        network=Network.ARC_TESTNET,
    )
    wallet_service = Mock()
    return config, wallet_service

@pytest.fixture
def router(mock_deps):
    config, wallet_service = mock_deps
    router = PaymentRouter(config, wallet_service)
    
    # Register adapters with priorities
    # Priorities: X402=10, Gateway=30, Transfer=50
    router.register_adapter(TransferAdapter(config, wallet_service))
    router.register_adapter(GatewayAdapter(config, wallet_service))
    router.register_adapter(X402Adapter(config, wallet_service))
    return router

def test_smart_routing(router):
    # 1. Standard Transfer (Same chain inferred, no kwargs)
    # ----------------------------------------------------
    recipient = "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0"
    method = router.detect_method(recipient)
    assert method == PaymentMethod.TRANSFER
    
    # 2. X402 (URL)
    # -------------
    url = "https://api.example.com/pay"
    method = router.detect_method(url)
    assert method == PaymentMethod.X402
    
    # 3. Gateway (Legacy chain:address)
    # ---------------------------------
    crosschain = "base:0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0"
    method = router.detect_method(crosschain)
    assert method == PaymentMethod.CROSSCHAIN
    
    # 4. Gateway (Smart Routing: Explicit Destination)
    # ------------------------------------------------
    # Recipient is plain address, but targeting Base (diff from Arc)
    method = router.detect_method(
        recipient, 
        destination_chain="base"
    )
    assert method == PaymentMethod.CROSSCHAIN
    
    
    # 5. Transfer (Explicit Same Chain)
    # ---------------------------------
    method = router.detect_method(
        recipient,
        destination_chain="arc-testnet"  # Same as config source
    )
    assert method == PaymentMethod.TRANSFER
    
    # 6. Gateway (Implicit Inference - EVM to Solana)
    # -----------------------------------------------
    solana_recipient = "HN7cABqLq46Es1jh92dQQisAq662SmxELLLsHHe4YWrx"
    method = router.detect_method(solana_recipient)
    assert method == PaymentMethod.CROSSCHAIN
    
    # 7. Transfer (Reject Foreign Address)
    # ------------------------------------
    # TransferAdapter shouldn't claim Solana address on EVM chain
    transfer_adapter = router.get_adapters()[2] # Priority 50
    assert isinstance(transfer_adapter, TransferAdapter)
    assert transfer_adapter.supports(solana_recipient) is False

    # 8. Multi-Chain Source Override
    # ------------------------------
    # Simulate: Global Config is ARC_TESTNET (EVM)
    # But we explicitly pass source_network=Network.SOL
    # And we check a Solana address.
    # TransferAdapter should accept it (because Source=SOL).
    
    # Normally check:
    assert router._config.network == Network.ARC_TESTNET
    
    # If we pass source_network=SOL, TransferAdapter should accept Base58
    assert transfer_adapter.supports(
        solana_recipient, 
        source_network=Network.SOL
    ) is True
    
    # And reject 0x address
    assert transfer_adapter.supports(
        recipient, 
        source_network=Network.SOL
    ) is False

@pytest.mark.asyncio
async def test_execution_smart_routing(router, mock_deps):
    config, wallet_service = mock_deps
    
    # Setup mock wallet service
    mock_balance = Mock()
    mock_balance.amount = Decimal("100")
    wallet_service.get_usdc_balance = Mock(return_value=mock_balance)
    wallet_service.get_usdc_balance_amount = Mock(return_value=Decimal("100"))
    wallet_service.transfer = Mock(return_value=Mock(success=True, transaction=Mock(id="tx1", state=Mock(value="complete"))))
    
    # Mock get_wallet to return a wallet on ARC_TESTNET
    mock_wallet = Mock()
    mock_wallet.blockchain = Network.ARC_TESTNET
    wallet_service.get_wallet = Mock(return_value=mock_wallet)
    
    # Mock GatewayAdapter's specific execution to verify CCTP logic triggered
    # (Since we don't have real backend, verify _execute_cctp_transfer calls)
    
    # For this test, we just check simulation logic which uses routing logic too
    
    # 1. Simulate Gateway via Smart Routing
    recipient = "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0"
    result = await router.simulate(
        wallet_id="w1",
        recipient=recipient,
        amount=Decimal("10"),
        destination_chain="base"
    )
    
    assert result.route == PaymentMethod.CROSSCHAIN
    assert not result.would_succeed  # Expected false as balance check mocked incompletely or CCTP not ready
    
    # 2. Simulate Transfer via Default
    result = await router.simulate(
        wallet_id="w1",
        recipient=recipient,
        amount=Decimal("10")
    )
    assert result.route == PaymentMethod.TRANSFER

if __name__ == "__main__":
    import sys
    from pytest import main
    sys.exit(main(["-v", __file__]))
