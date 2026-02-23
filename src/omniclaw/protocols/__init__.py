"""
Protocol adapters for different payment methods.

Adapters handle the specifics of each payment protocol:
- TransferAdapter: Direct USDC wallet-to-wallet transfers
- X402Adapter: HTTP 402 Payment Required protocol
- GatewayAdapter: Cross-chain transfers via Circle Gateway
"""

from omniclaw.protocols.base import ProtocolAdapter
from omniclaw.protocols.gateway import GatewayAdapter
from omniclaw.protocols.transfer import TransferAdapter
from omniclaw.protocols.x402 import PaymentPayload, PaymentRequirements, X402Adapter

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
]
