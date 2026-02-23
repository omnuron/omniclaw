"""Gas estimation utilities for OmniClaw."""

from decimal import Decimal
from typing import Dict

from omniclaw.core.logging import get_logger
from omniclaw.core.types import Network

logger = get_logger("utils.gas")


# Minimum gas requirements by network (in native tokens)
GAS_REQUIREMENTS: Dict[Network, Decimal] = {
    # Ethereum
    Network.ETH: Decimal("0.01"),
    Network.ETH_SEPOLIA: Decimal("0.01"),
    # Avalanche
    Network.AVAX: Decimal("0.1"),
    Network.AVAX_FUJI: Decimal("0.1"),
    # Optimism
    Network.OP: Decimal("0.001"),
    Network.OP_SEPOLIA: Decimal("0.001"),
    # Arbitrum
    Network.ARB: Decimal("0.001"),
    Network.ARB_SEPOLIA: Decimal("0.001"),
    # Base
    Network.BASE: Decimal("0.001"),
    Network.BASE_SEPOLIA: Decimal("0.001"),
    # Polygon
    Network.MATIC: Decimal("0.1"),
    Network.MATIC_AMOY: Decimal("0.1"),
    # Arc (uses USDC for gas)
    Network.ARC_TESTNET: Decimal("0"),
}


def get_network_gas_token(network: Network) -> str:
    """Get the native gas token name for a network."""
    if network in [Network.ETH, Network.ETH_SEPOLIA]:
        return "ETH"
    elif network in [Network.OP, Network.OP_SEPOLIA]:
        return "ETH"
    elif network in [Network.ARB, Network.ARB_SEPOLIA]:
        return "ETH"
    elif network in [Network.BASE, Network.BASE_SEPOLIA]:
        return "ETH"
    elif network in [Network.AVAX, Network.AVAX_FUJI]:
        return "AVAX"
    elif network in [Network.MATIC, Network.MATIC_AMOY]:
        return "MATIC"
    elif network == Network.ARC_TESTNET:
        return "USDC"
    else:
        return "Unknown"


def check_gas_requirements(
    network: Network,
    native_balance: Decimal,
    operation: str = "CCTP transfer"
) -> tuple[bool, str]:
    """
    Check if a wallet has sufficient gas for an operation.
    
    Args:
        network: The blockchain network
        native_balance: Current native token balance
        operation: Description of the operation (for error message)
        
    Returns:
        Tuple of (has_sufficient_gas, error_message)
        error_message is empty string if sufficient
    """
    required = GAS_REQUIREMENTS.get(network, Decimal("0"))
    gas_token = get_network_gas_token(network)
    
    # Arc doesn't need separate gas checks (uses USDC)
    if network == Network.ARC_TESTNET:
        return True, ""
    
    if native_balance < required:
        error_msg = (
            f"Insufficient {gas_token} for {operation} on {network.value}. "
            f"Required: {required} {gas_token}, Available: {native_balance} {gas_token}. "
            f"Please fund your wallet with {gas_token}."
        )
        logger.warning(error_msg)
        return False, error_msg
    
    logger.debug(
        f"Gas check passed: {native_balance} {gas_token} >= {required} {gas_token} "
        f"on {network.value}"
    )
    return True, ""


def estimate_cctp_gas_cost(network: Network) -> Dict[str, Decimal]:
    """
    Estimate gas costs for a CCTP transfer.
    
    Returns:
        Dictionary with estimated costs in native tokens
    """
    gas_token = get_network_gas_token(network)
    
    # Arc uses USDC for gas
    if network == Network.ARC_TESTNET:
        return {
            "approval": Decimal("0.001"),
            "burn": Decimal("0.002"),
            "total": Decimal("0.003"),
            "token": "USDC"
        }
    
    # L2 networks (cheaper)
    if network in [Network.OP, Network.OP_SEPOLIA, Network.ARB, Network.ARB_SEPOLIA,
                   Network.BASE, Network.BASE_SEPOLIA]:
        return {
            "approval": Decimal("0.0001"),
            "burn": Decimal("0.0002"),
            "total": Decimal("0.0003"),
            "token": gas_token
        }
    
    # L1 networks (more expensive)
    return {
        "approval": Decimal("0.002"),
        "burn": Decimal("0.003"),
        "total": Decimal("0.005"),
        "token": gas_token
    }
