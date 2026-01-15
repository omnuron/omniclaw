"""
Protocol adapters for different payment methods.

Adapters handle the specifics of each payment protocol:
- TransferAdapter: Direct USDC wallet-to-wallet transfers
- X402Adapter: HTTP 402 Payment Required protocol
- GatewayAdapter: Cross-chain transfers via Circle Gateway
"""

from omniagentpay.protocols.base import ProtocolAdapter
from omniagentpay.protocols.transfer import TransferAdapter
from omniagentpay.protocols.x402 import X402Adapter, PaymentRequirements, PaymentPayload
from omniagentpay.protocols.gateway import GatewayAdapter, CrosschainDestination

__all__ = [
    # Base
    "ProtocolAdapter",
    # Adapters
    "TransferAdapter",
    "X402Adapter",
    "GatewayAdapter",
    # Types
    "PaymentRequirements",
    "PaymentPayload",
    "CrosschainDestination",
]
