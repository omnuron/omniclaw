
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from decimal import Decimal
import pytest

from omniclaw.core.config import Config
from omniclaw.core.types import (
    Network, 
    TransactionInfo, 
    TransactionState, 
    WalletInfo,
    WalletState,
    CustodyType,
    AccountType
)
from omniclaw.protocols.gateway import GatewayAdapter
from omniclaw.wallet.service import WalletService

@pytest.fixture
def mock_config():
    return Config(
        circle_api_key="test_key",
        entity_secret="test_secret",
        network=Network.ETH_SEPOLIA,
        default_wallet_id="wallet-123",
    )

@pytest.fixture
def mock_wallet_service(mock_config):
    service = AsyncMock(spec=WalletService)
    service._config = mock_config
    service._circle = MagicMock()
    # Ensure nested _circle is usable
    
    # helper for creating transaction response
    def create_tx(id, state, tx_hash=None):
        return TransactionInfo(
            id=id, 
            state=state, 
            tx_hash=tx_hash,
            blockchain="ARC-TESTNET",
            amounts=["100"],
            fee_level=None
        )

    service._circle.get_transaction.side_effect = lambda tx_id: create_tx(tx_id, TransactionState.COMPLETE, "0xhash")
    service._circle.create_contract_execution.return_value = create_tx("tx-mint", TransactionState.PENDING)
    
    # Mock list_wallets to return a destination wallet
    dest_wallet = WalletInfo(
        id="dest-wallet-123",
        address="0xdestwallet",
        blockchain="ARC-TESTNET",
        state=WalletState.LIVE,
        wallet_set_id="ws-123",
        custody_type=CustodyType.DEVELOPER,
        account_type=AccountType.EOA
    )
    service.list_wallets.return_value = [dest_wallet]
    
    return service

@pytest.mark.asyncio
async def test_mint_usdc_success(mock_config, mock_wallet_service):
    """Test _mint_usdc successfully finds wallet and calls contract."""
    adapter = GatewayAdapter(mock_config, mock_wallet_service)
    
    result = await adapter._mint_usdc(
        attestation_message="0xmsg",
        attestation_signature="0xsig",
        dest_network=Network.ARC_TESTNET
    )
    
    assert result["success"] is True
    assert result["tx_hash"] == "0xhash"
    
    # Verify list_wallets called for destination network
    mock_wallet_service.list_wallets.assert_called_with(blockchain=Network.ARC_TESTNET)
    
    # Verify create_contract_execution called with correct params
    mock_wallet_service._circle.create_contract_execution.assert_called_once()
    args = mock_wallet_service._circle.create_contract_execution.call_args[1]
    assert args["wallet_id"] == "dest-wallet-123"
    assert "receiveMessage" in args["abi_function_signature"]
    assert args["abi_parameters"] == ["0xmsg", "0xsig"]

@pytest.mark.asyncio
async def test_mint_usdc_no_wallet(mock_config, mock_wallet_service):
    """Test _mint_usdc fails if no wallet found."""
    mock_wallet_service.list_wallets.return_value = []
    
    adapter = GatewayAdapter(mock_config, mock_wallet_service)
    
    result = await adapter._mint_usdc(
        attestation_message="0xmsg",
        attestation_signature="0xsig",
        dest_network=Network.ARC_TESTNET
    )
    
    assert result["success"] is False
    assert "No wallet found" in result["error"]
    mock_wallet_service._circle.create_contract_execution.assert_not_called()

@pytest.mark.asyncio
async def test_execute_cctp_forces_mint_on_arc(mock_config, mock_wallet_service):
    """Test that _execute_cctp_transfer forces mint calls for ARC_TESTNET destination."""
    adapter = GatewayAdapter(mock_config, mock_wallet_service)
    
    # Mock internal methods to skip network calls
    adapter._mint_usdc = AsyncMock(return_value={"success": True, "tx_hash": "0xmint"})
    
    # Mock httpx response for attestation polling
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messages": [
                {"status": "complete", "message": "0xmsg", "attestation": "0xsig"}
            ]
        }
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response
        
        # Mock gas check import or method
        with patch("omniclaw.protocols.gateway.check_gas_requirements", create=True) as mock_gas:
             mock_gas.return_value = (True, None) # has gas
             
             # Call execute
             # We need to ensure is_cctp_supported returns True and addresses are found
             # Since we are using real constants, ensure ARC_TESTNET is in types.py (it is)
             
             source_network = Network.ETH_SEPOLIA
             dest_network = Network.ARC_TESTNET
             
             # Mock initial txs
             mock_wallet_service._circle.create_contract_execution.return_value = TransactionInfo(
                 id="tx-1", state=TransactionState.COMPLETE, tx_hash="0xburn"
             )
             mock_wallet_service._circle.get_transaction.return_value = TransactionInfo(
                 id="tx-1", state=TransactionState.COMPLETE, tx_hash="0xburn"
             )

             # We need to mock GatewayAdapter._execute_cctp_transfer or call execute and let it flow?
             # Calling execute is complex due to dependencies.
             # Call _execute_cctp_transfer directly.
             
             result = await adapter._execute_cctp_transfer(
                 wallet_id="source-123",
                 source_network=source_network,
                 dest_network=dest_network,
                 destination_address="0xdest",
                 amount=Decimal("10"),
                 fee_level=None
             )
             
             assert result.success is True
             assert result.status.value == "completed"
             # Check metadata contains mint info
             assert result.metadata["cctp_flow"] == "burn_attestation_mint"
             assert result.metadata["mint_tx_hash"] == "0xmint"
             
             # Verify _mint_usdc was called
             adapter._mint_usdc.assert_called_once()
