"""
Test suite for gas estimation utilities.
"""

import pytest
from decimal import Decimal
from omniclaw.core.types import Network
from omniclaw.utils.gas import (
    get_network_gas_token,
    check_gas_requirements,
    estimate_cctp_gas_cost,
    GAS_REQUIREMENTS,
)


class TestNetworkGasToken:
    """Test gas token identification."""
    
    def test_ethereum_networks(self):
        """Test Ethereum-based networks use ETH."""
        assert get_network_gas_token(Network.ETH) == "ETH"
        assert get_network_gas_token(Network.ETH_SEPOLIA) == "ETH"
        assert get_network_gas_token(Network.OP) == "ETH"
        assert get_network_gas_token(Network.ARB) == "ETH"
        assert get_network_gas_token(Network.BASE) == "ETH"
    
    def test_other_networks(self):
        """Test other networks use their native tokens."""
        assert get_network_gas_token(Network.AVAX) == "AVAX"
        assert get_network_gas_token(Network.MATIC) == "MATIC"
    
    def test_arc_uses_usdc(self):
        """Test ARC network uses USDC for gas."""
        assert get_network_gas_token(Network.ARC_TESTNET) == "USDC"


class TestGasRequirements:
    """Test gas requirement checks."""
    
    def test_sufficient_gas_ethereum(self):
        """Test check passes with sufficient ETH."""
        has_gas, error = check_gas_requirements(
            Network.ETH_SEPOLIA,
            Decimal("0.02"),  # More than required 0.01
            "test operation"
        )
        
        assert has_gas is True
        assert error == ""
    
    def test_insufficient_gas_ethereum(self):
        """Test check fails with insufficient ETH."""
        has_gas, error = check_gas_requirements(
            Network.ETH_SEPOLIA,
            Decimal("0.005"),  # Less than required 0.01
            "test operation"
        )
        
        assert has_gas is False
        assert "Insufficient ETH" in error
        assert "0.01 ETH" in error
    
    def test_l2_has_lower_requirements(self):
        """Test L2 networks have lower gas requirements."""
        eth_req = GAS_REQUIREMENTS[Network.ETH]
        base_req = GAS_REQUIREMENTS[Network.BASE]
        
        assert base_req < eth_req
    
    def test_arc_always_sufficient(self):
        """Test ARC doesn't need gas checks (uses USDC)."""
        # Even with 0 balance, should pass (USDC checked separately)
        has_gas, error = check_gas_requirements(
            Network.ARC_TESTNET,
            Decimal("0"),
            "CCTP transfer"
        )
        
        assert has_gas is True
        assert error == ""
    
    def test_exact_requirement(self):
        """Test check passes with exact required amount."""
        required = GAS_REQUIREMENTS[Network.BASE_SEPOLIA]
        has_gas, error = check_gas_requirements(
            Network.BASE_SEPOLIA,
            required,
            "test"
        )
        
        assert has_gas is True
    
    def test_error_message_details(self):
        """Test error message contains helpful details."""
        has_gas, error = check_gas_requirements(
            Network.AVAX_FUJI,
            Decimal("0.05"),  # Less than required 0.1
            "CCTP transfer"
        )
        
        assert has_gas is False
        assert "AVAX" in error
        assert "AVAX-FUJI" in error
        assert "0.1" in error  # Required amount
        assert "0.05" in error  # Available amount


class TestGasCostEstimation:
    """Test CCTP gas cost estimation."""
    
    def test_arc_estimate_uses_usdc(self):
        """Test ARC estimates are in USDC."""
        estimate = estimate_cctp_gas_cost(Network.ARC_TESTNET)
        
        assert estimate["token"] == "USDC"
        assert estimate["total"] > 0
        assert estimate["approval"] > 0
        assert estimate["burn"] > 0
    
    def test_l2_cheaper_than_l1(self):
        """Test L2 gas estimates are lower than L1."""
        eth_estimate = estimate_cctp_gas_cost(Network.ETH)
        base_estimate = estimate_cctp_gas_cost(Network.BASE)
        
        assert base_estimate["total"] < eth_estimate["total"]
    
    def test_estimate_has_all_fields(self):
        """Test estimate contains all expected fields."""
        estimate = estimate_cctp_gas_cost(Network.ETH_SEPOLIA)
        
        assert "approval" in estimate
        assert "burn" in estimate
        assert "total" in estimate
        assert "token" in estimate
        
        # Total should equal sum of components
        assert estimate["total"] == estimate["approval"] + estimate["burn"]
    
    def test_reasonable_arc_costs(self):
        """Test ARC gas costs are reasonable."""
        estimate = estimate_cctp_gas_cost(Network.ARC_TESTNET)
        
        # Should be small fraction of USDC
        assert estimate["total"] < Decimal("0.01")  # Less than 1 cent
        assert estimate["total"] > Decimal("0.001")  # More than 0.1 cent


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
