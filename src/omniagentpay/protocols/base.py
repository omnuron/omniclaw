"""
Base protocol adapter interface.

All payment protocol adapters (Transfer, X402, Crosschain) implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from omniagentpay.core.types import PaymentMethod, PaymentResult

if TYPE_CHECKING:
    from omniagentpay.core.config import Config
    from omniagentpay.wallet.service import WalletService


class ProtocolAdapter(ABC):
    """
    Abstract base class for payment protocol adapters.
    
    Each adapter handles a specific payment method:
    - TransferAdapter: Direct USDC transfers between wallets
    - X402Adapter: HTTP 402 Payment Required protocol
    - CrosschainAdapter: Gateway/CCTP/Bridge Kit transfers
    
    The PaymentRouter uses adapters to execute payments based on recipient type.
    """
    
    @property
    @abstractmethod
    def method(self) -> PaymentMethod:
        """Return the payment method this adapter handles."""
        ...
    
    @abstractmethod
    def supports(self, recipient: str, **kwargs: Any) -> bool:
        """
        Check if this adapter can handle the given recipient.
        
        Args:
            recipient: Payment recipient (URL, address, etc.)
            **kwargs: Additional context (e.g. destination_chain)
            
        Returns:
            True if this adapter can handle the recipient
        """
        ...
    
    @abstractmethod
    async def execute(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal,
        purpose: str | None = None,
        **kwargs: Any,
    ) -> PaymentResult:
        """
        Execute a payment.
        
        Args:
            wallet_id: Source wallet ID
            recipient: Payment recipient
            amount: Amount to pay
            purpose: Human-readable purpose
            **kwargs: Additional adapter-specific parameters
            
        Returns:
            Payment result
        """
        ...
    
    async def simulate(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Simulate a payment without executing.
        
        Default implementation returns basic info. Adapters can override
        for more detailed simulation.
        
        Args:
            wallet_id: Source wallet ID
            recipient: Payment recipient
            amount: Amount to simulate
            
        Returns:
            Simulation result dict
        """
        return {
            "would_succeed": True,
            "method": self.method.value,
            "recipient": recipient,
            "amount": str(amount),
        }
    
    def get_priority(self) -> int:
        """
        Get adapter priority for routing.
        
        Lower number = higher priority. Used when multiple adapters
        could handle the same recipient.
        
        Returns:
            Priority value (default 100)
        """
        return 100
