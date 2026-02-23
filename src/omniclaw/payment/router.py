"""PaymentRouter - Routes payments to appropriate protocol adapters."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from omniclaw.core.logging import get_logger
from omniclaw.core.types import (
    FeeLevel,
    Network,
    PaymentMethod,
    PaymentResult,
    PaymentStatus,
    SimulationResult,
)
from omniclaw.protocols.base import ProtocolAdapter

if TYPE_CHECKING:
    from omniclaw.core.config import Config
    from omniclaw.wallet.service import WalletService


class PaymentRouter:
    """Routes payments to the appropriate protocol adapter based on recipient type."""

    def __init__(
        self,
        config: Config,
        wallet_service: WalletService,
    ) -> None:
        self._config = config
        self._wallet_service = wallet_service
        self._adapters: list[ProtocolAdapter] = []
        self._logger = get_logger("router")

    def register_adapter(self, adapter: ProtocolAdapter) -> None:
        self._adapters.append(adapter)
        self._adapters.sort(key=lambda a: a.get_priority())

    def unregister_adapter(self, method: PaymentMethod) -> None:
        self._adapters = [a for a in self._adapters if a.method != method]

    def get_adapters(self) -> list[ProtocolAdapter]:
        return list(self._adapters)

    def detect_method(self, recipient: str, source_network: Network | str | None = None, destination_chain: Network | str | None = None, **kwargs: Any) -> PaymentMethod | None:
        for adapter in self._adapters:
            if adapter.supports(recipient, source_network=source_network, destination_chain=destination_chain, **kwargs):
                return adapter.method
        return None

    def _find_adapter(self, recipient: str, source_network: Network | str | None = None, destination_chain: Network | str | None = None, **kwargs: Any) -> ProtocolAdapter | None:
        for adapter in self._adapters:
            if adapter.supports(recipient, source_network=source_network, destination_chain=destination_chain, **kwargs):
                return adapter
        return None

    async def pay(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal | str,
        fee_level: FeeLevel = FeeLevel.MEDIUM,
        purpose: str | None = None,
        guards_passed: list[str] | None = None,
        idempotency_key: str | None = None,
        wait_for_completion: bool = False,
        timeout_seconds: float | None = None,
        destination_chain: Network | str | None = None,
        **kwargs: Any,
    ) -> PaymentResult:
        """Execute a payment via the appropriate method."""
        amount_decimal = Decimal(str(amount))

        # Resolve source network
        wallet = self._wallet_service.get_wallet(wallet_id)
        source_network = Network.from_string(wallet.blockchain)

        adapter = self._find_adapter(recipient, destination_chain=destination_chain, source_network=source_network, **kwargs)
        if not adapter:
            self._logger.error(f"No adapter found for recipient: {recipient}")
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount_decimal,
                recipient=recipient,
                method=PaymentMethod.TRANSFER,
                status=PaymentStatus.FAILED,
                error=f"No adapter found for recipient: {recipient}",
                guards_passed=guards_passed or [],
            )

        result = await adapter.execute(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=amount_decimal,
            source_network=source_network,
            purpose=purpose,
            fee_level=fee_level,
            idempotency_key=idempotency_key,
            destination_chain=destination_chain,
            wait_for_completion=wait_for_completion,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

        if guards_passed:
            result.guards_passed = guards_passed

        return result

    async def simulate(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal | str,
        **kwargs: Any,
    ) -> SimulationResult:
        """
        Simulate a payment without executing.

        Args:
            wallet_id: Source wallet ID
            recipient: Payment recipient
            amount: Amount to simulate

        Returns:
            Simulation result
        """
        amount_decimal = Decimal(str(amount))

        # Resolve source network from wallet - MUST succeed
        wallet = self._wallet_service.get_wallet(wallet_id)
        source_network = Network.from_string(wallet.blockchain)
        destination_chain = kwargs.get("destination_chain")

        # Find adapter
        adapter = self._find_adapter(recipient, source_network=source_network, destination_chain=destination_chain, **kwargs)

        if not adapter:
            return SimulationResult(
                would_succeed=False,
                route=PaymentMethod.TRANSFER,
                reason=f"No adapter found for recipient: {recipient}",
            )

        # Simulate via adapter
        sim_result = await adapter.simulate(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=amount_decimal,
            **kwargs,
        )

        return SimulationResult(
            would_succeed=sim_result.get("would_succeed", False),
            route=adapter.method,
            estimated_fee=Decimal(sim_result["estimated_fee"])
            if sim_result.get("estimated_fee")
            else None,
            reason=sim_result.get("reason"),
        )

    def can_handle(self, recipient: str) -> bool:
        """
        Check if any adapter can handle the recipient.

        Args:
            recipient: Payment recipient

        Returns:
            True if an adapter exists for this recipient
        """
        return self._find_adapter(recipient) is not None

    def get_supported_formats(self) -> dict[PaymentMethod, str]:
        """
        Get descriptions of supported recipient formats.

        Returns:
            Dict mapping methods to format descriptions
        """
        return {
            PaymentMethod.TRANSFER: "Blockchain address (0x... for EVM, Base58 for Solana)",
            PaymentMethod.X402: "HTTPS URL (https://api.example.com)",
            PaymentMethod.CROSSCHAIN: "chain:address format (base:0x...)",
        }
