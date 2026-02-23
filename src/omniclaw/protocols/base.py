"""
Base protocol adapter interface.

All payment protocol adapters (Transfer, X402, Crosschain) implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from omniclaw.core.types import FeeLevel, Network, PaymentMethod, PaymentResult

if TYPE_CHECKING:
    pass


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
    def supports(self, recipient: str, source_network: Network | str | None = None, destination_chain: Network | str | None = None, **kwargs: Any) -> bool:
        """
        Check if this adapter can handle the given recipient.

        Args:
            recipient: Payment recipient (URL, address, etc.)
            source_network: Source network (optional)
            destination_chain: Destination chain (optional)
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
        fee_level: FeeLevel = FeeLevel.MEDIUM,
        idempotency_key: str | None = None,
        purpose: str | None = None,
        destination_chain: Network | str | None = None,
        source_network: Network | str | None = None,
        wait_for_completion: bool = False,
        timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> PaymentResult:
        """
        Execute a payment.

        Args:
            wallet_id: Source wallet ID
            recipient: Payment recipient
            amount: Amount to pay
            fee_level: Fee level (optional)
            idempotency_key: Idempotency key (optional)
            purpose: Human-readable purpose
            destination_chain: Destination chain (optional)
            source_network: Source network (optional)
            wait_for_completion: Wait for completion (optional)
            timeout_seconds: Timeout in seconds (optional)
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
