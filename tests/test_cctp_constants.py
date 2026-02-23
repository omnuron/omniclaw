"""
Test suite for CCTP constants and utilities.
"""

import pytest
from omniclaw.core.types import Network
from omniclaw.core.cctp_constants import (
    CCTP_DOMAIN_IDS,
    TOKEN_MESSENGER_V2_CONTRACTS,
    MESSAGE_TRANSMITTER_V2_CONTRACTS,
    USDC_CONTRACTS,
    is_cctp_supported,
    get_token_messenger_v2,
    get_message_transmitter_v2,
    get_iris_url,
    get_iris_v2_attestation_url,
)


class TestCCTPDomainIDs:
    """Test CCTP domain ID mappings."""
    
    def test_all_networks_have_domain_ids(self):
        """Verify all CCTP-supported networks have domain IDs."""
        expected_networks = [
            Network.ETH, Network.ETH_SEPOLIA,
            Network.AVAX, Network.AVAX_FUJI,
            Network.OP, Network.OP_SEPOLIA,
            Network.ARB, Network.ARB_SEPOLIA,
            Network.SOL, Network.SOL_DEVNET,
            Network.BASE, Network.BASE_SEPOLIA,
            Network.MATIC, Network.MATIC_AMOY,
            Network.ARC_TESTNET,
        ]
        
        for network in expected_networks:
            assert network in CCTP_DOMAIN_IDS, f"{network} missing domain ID"
    
    def test_arc_testnet_domain_id(self):
        """Verify ARC testnet has correct domain ID."""
        assert CCTP_DOMAIN_IDS[Network.ARC_TESTNET] == 26
    
    def test_ethereum_domain_id(self):
        """Verify Ethereum networks have correct domain ID."""
        assert CCTP_DOMAIN_IDS[Network.ETH] == 0
        assert CCTP_DOMAIN_IDS[Network.ETH_SEPOLIA] == 0


class TestCCTPContracts:
    """Test CCTP contract address mappings."""
    
    def test_token_messenger_contracts(self):
        """Verify TokenMessenger contracts are configured."""
        # Testnet networks
        testnets = ["ETH-SEPOLIA", "BASE-SEPOLIA", "ARC-TESTNET"]
        for network in testnets:
            assert network in TOKEN_MESSENGER_V2_CONTRACTS
            assert TOKEN_MESSENGER_V2_CONTRACTS[network].startswith("0x")
    
    def test_message_transmitter_contracts(self):
        """Verify MessageTransmitter contracts are configured."""
        testnets = ["ETH-SEPOLIA", "BASE-SEPOLIA", "ARC-TESTNET"]
        for network in testnets:
            assert network in MESSAGE_TRANSMITTER_V2_CONTRACTS
            assert MESSAGE_TRANSMITTER_V2_CONTRACTS[network].startswith("0x")
    
    def test_usdc_contracts(self):
        """Verify USDC contract addresses."""
        assert USDC_CONTRACTS["ETH-SEPOLIA"] == "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238"
        assert USDC_CONTRACTS["BASE-SEPOLIA"] == "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
        # ARC testnet USDC address
        assert USDC_CONTRACTS["ARC-TESTNET"] == "0x79A02482A880bCE3F13e09Da970dC34db4CD24d1"


class TestCCTPUtilities:
    """Test CCTP utility functions."""
    
    def test_is_cctp_supported(self):
        """Test CCTP network support detection."""
        # Supported networks
        assert is_cctp_supported(Network.ETH_SEPOLIA) is True
        assert is_cctp_supported(Network.BASE_SEPOLIA) is True
        assert is_cctp_supported(Network.ARC_TESTNET) is True
        
        # Unsupported networks
        assert is_cctp_supported(Network.NEAR) is False
        assert is_cctp_supported(Network.APTOS) is False
    
    def test_get_token_messenger_v2(self):
        """Test TokenMessenger contract retrieval."""
        contract = get_token_messenger_v2(Network.ETH_SEPOLIA)
        assert contract is not None
        assert contract.startswith("0x")
        
        contract = get_token_messenger_v2(Network.ARC_TESTNET)
        assert contract is not None
    
    def test_get_message_transmitter_v2(self):
        """Test MessageTransmitter contract retrieval."""
        contract = get_message_transmitter_v2(Network.BASE_SEPOLIA)
        assert contract is not None
        assert contract.startswith("0x")
    
    def test_get_iris_url(self):
        """Test Iris API URL selection."""
        # Testnet should use sandbox
        url = get_iris_url(Network.ETH_SEPOLIA)
        assert "sandbox" in url
        
        # Mainnet should use production
        url = get_iris_url(Network.ETH)
        assert "sandbox" not in url
    
    def test_get_iris_v2_attestation_url(self):
        """Test attestation URL generation."""
        url = get_iris_v2_attestation_url(
            Network.ETH_SEPOLIA,
            0,
            "0x1234567890abcdef"
        )
        assert "iris-api-sandbox.circle.com" in url
        assert "v2/messages" in url
        assert "0x1234567890abcdef" in url


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
