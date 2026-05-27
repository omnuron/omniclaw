"""PaymentRouter - Routes payments to appropriate protocol adapters."""

from __future__ import annotations

import contextlib
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from omniclaw.core.logging import get_logger
from omniclaw.core.state_machine import is_effective_success_status
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

    @staticmethod
    def _route_value(route: Any) -> str:
        return str(route.value if hasattr(route, "value") else route or "").strip()

    @classmethod
    def _matches_preferred_route(cls, adapter: ProtocolAdapter, preferred_route: Any) -> bool:
        if not preferred_route:
            return True
        adapter_method = getattr(adapter, "method", None)
        return cls._route_value(adapter_method) == cls._route_value(preferred_route)

    def detect_method(
        self,
        recipient: str,
        source_network: Network | str | None = None,
        destination_chain: Network | str | None = None,
        **kwargs: Any,
    ) -> PaymentMethod | None:
        for adapter in self._adapters:
            if not self._matches_preferred_route(adapter, kwargs.get("preferred_url_route")):
                continue
            if adapter.supports(
                recipient,
                source_network=source_network,
                destination_chain=destination_chain,
                **kwargs,
            ):
                return adapter.method
        return None

    def _find_adapter(
        self,
        recipient: str,
        source_network: Network | str | None = None,
        destination_chain: Network | str | None = None,
        **kwargs: Any,
    ) -> ProtocolAdapter | None:
        for adapter in self._adapters:
            if not self._matches_preferred_route(adapter, kwargs.get("preferred_url_route")):
                continue
            if adapter.supports(
                recipient,
                source_network=source_network,
                destination_chain=destination_chain,
                **kwargs,
            ):
                return adapter
        return None

    def _find_adapters(
        self,
        recipient: str,
        source_network: Network | str | None = None,
        destination_chain: Network | str | None = None,
        **kwargs: Any,
    ) -> list[ProtocolAdapter]:
        return [
            adapter
            for adapter in self._adapters
            if self._matches_preferred_route(adapter, kwargs.get("preferred_url_route"))
            and adapter.supports(
                recipient,
                source_network=source_network,
                destination_chain=destination_chain,
                **kwargs,
            )
        ]

    @staticmethod
    def _can_fallback(result: PaymentResult) -> bool:
        metadata = result.metadata or {}
        return metadata.get("fallback_eligible") is True

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
        # Try to get from Circle wallet first, then from config default
        source_network = None
        try:
            wallet = self._wallet_service.get_wallet(wallet_id)
            source_network = Network.from_string(wallet.blockchain)
        except Exception:
            # Wallet not in Circle system - try to get network from config default
            if source_network is None and hasattr(self, "_config"):
                with contextlib.suppress(Exception):
                    source_network = self._config.network

            if source_network is None:
                # Fallback to ETH Sepolia if we can't determine the network
                source_network = Network.ETH_SEPOLIA

        adapters = self._find_adapters(
            recipient,
            destination_chain=destination_chain,
            source_network=source_network,
            amount=amount_decimal,
            **kwargs,
        )
        if not adapters:
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

        last_result: PaymentResult | None = None
        for index, adapter in enumerate(adapters):
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
            last_result = result

            if result.success or is_effective_success_status(result.status):
                if guards_passed:
                    result.guards_passed = guards_passed
                return result

            has_next = index < (len(adapters) - 1)
            if not has_next or not self._can_fallback(result):
                if guards_passed:
                    result.guards_passed = guards_passed
                return result

            self._logger.warning(
                "Adapter %s failed with fallback-eligible error; trying next route.",
                getattr(adapter.method, "value", str(adapter.method)),
            )

        if last_result is not None:
            if guards_passed:
                last_result.guards_passed = guards_passed
            return last_result
        return PaymentResult(
            success=False,
            transaction_id=None,
            blockchain_tx=None,
            amount=amount_decimal,
            recipient=recipient,
            method=PaymentMethod.TRANSFER,
            status=PaymentStatus.FAILED,
            error="Payment routing failed unexpectedly",
            guards_passed=guards_passed or [],
        )

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

        # Resolve source network from wallet when available. x402-only buyer
        # profiles may use a synthetic wallet id backed by an EOA signer.
        try:
            wallet = self._wallet_service.get_wallet(wallet_id)
            source_network = Network.from_string(wallet.blockchain)
        except Exception:
            source_network = self._config.network
        destination_chain = kwargs.pop("destination_chain", None)

        # Find adapter
        adapter = self._find_adapter(
            recipient,
            source_network=source_network,
            destination_chain=destination_chain,
            amount=amount_decimal,
            **kwargs,
        )

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
