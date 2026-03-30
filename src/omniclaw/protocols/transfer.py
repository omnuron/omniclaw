"""
TransferAdapter - Direct USDC wallet-to-wallet transfers.

Handles payments to blockchain addresses using Circle's transfer API.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from omniclaw.core.exceptions import InsufficientBalanceError, WalletError
from omniclaw.core.idempotency import derive_idempotency_key
from omniclaw.core.logging import get_logger
from omniclaw.core.state_machine import is_irreversible_success_status
from omniclaw.core.types import (
    FeeLevel,
    Network,
    PaymentMethod,
    PaymentResult,
    PaymentStatus,
    TransactionState,
)
from omniclaw.protocols.base import ProtocolAdapter

if TYPE_CHECKING:
    from omniclaw.core.config import Config
    from omniclaw.wallet.service import WalletService


# Regex patterns for blockchain addresses
EVM_ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
SOLANA_ADDRESS_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class TransferAdapter(ProtocolAdapter):
    """Adapter for direct USDC transfers between wallets (EVM & Solana)."""

    def __init__(
        self,
        config: Config,
        wallet_service: WalletService,
    ) -> None:
        self._config = config
        self._wallet_service = wallet_service
        self._logger = get_logger("transfer")

    @property
    def method(self) -> PaymentMethod:
        return PaymentMethod.TRANSFER

    def supports(
        self,
        recipient: str,
        source_network: Network | str | None = None,
        destination_chain: Network | str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Check if recipient is a valid blockchain address for current network."""
        # Determine network context (Source Wallet wins over Global Config)
        network = source_network or self._config.network
        try:
            network = network if isinstance(network, Network) else Network.from_string(str(network))
        except Exception:
            return False

        dest_chain = destination_chain
        if dest_chain:
            try:
                dest_chain = (
                    dest_chain
                    if isinstance(dest_chain, Network)
                    else Network.from_string(str(dest_chain))
                )
            except Exception:
                return False
            if dest_chain != network:
                return False

        if network.is_solana():
            return self._is_solana_address(recipient)

        if network.is_evm():
            return self._is_evm_address(recipient)

        return False

    def _is_evm_address(self, address: str) -> bool:
        return bool(EVM_ADDRESS_PATTERN.match(address))

    def _is_solana_address(self, address: str) -> bool:
        if not SOLANA_ADDRESS_PATTERN.match(address):
            return False
        return not address.startswith("0x")

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
        """Execute a direct USDC transfer."""
        canonical_idempotency_key = idempotency_key or derive_idempotency_key(
            "transfer",
            wallet_id,
            recipient,
            str(amount),
            purpose,
            destination_chain.value if hasattr(destination_chain, "value") else destination_chain,
            source_network.value if hasattr(source_network, "value") else source_network,
        )
        try:
            transfer_result = await self._wallet_service.transfer(
                wallet_id=wallet_id,
                destination_address=recipient,
                amount=amount,
                fee_level=fee_level,
                check_balance=True,
                wait_for_completion=wait_for_completion,
                timeout_seconds=timeout_seconds,
                idempotency_key=canonical_idempotency_key,
            )
        except (WalletError, InsufficientBalanceError) as e:
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=recipient,
                method=self.method,
                status=PaymentStatus.FAILED,
                error=str(e),
            )

        if not transfer_result.success:
            return PaymentResult(
                success=False,
                transaction_id=transfer_result.transaction.id
                if transfer_result.transaction
                else None,
                blockchain_tx=transfer_result.tx_hash,
                amount=amount,
                recipient=recipient,
                method=self.method,
                status=PaymentStatus.FAILED,
                error=transfer_result.error,
            )

        strict_settlement = bool(getattr(self._config, "payment_strict_settlement", True))
        tx = transfer_result.transaction
        status = PaymentStatus.PENDING_SETTLEMENT if strict_settlement else PaymentStatus.PROCESSING
        if tx:
            if tx.state == TransactionState.COMPLETE:
                status = PaymentStatus.SETTLED if strict_settlement else PaymentStatus.COMPLETED
            elif tx.state == TransactionState.FAILED or tx.is_terminal():
                status = PaymentStatus.FAILED_FINAL if strict_settlement else PaymentStatus.FAILED

        return PaymentResult(
            success=is_irreversible_success_status(status)
            if strict_settlement
            else status != PaymentStatus.FAILED,
            transaction_id=tx.id if tx else None,
            blockchain_tx=transfer_result.tx_hash,
            amount=amount,
            recipient=recipient,
            method=self.method,
            status=status,
            metadata={
                "purpose": purpose,
                "fee_level": fee_level.value,
                "tx_state": tx.state.value if tx else None,
                "idempotency_key": canonical_idempotency_key,
                "destination_chain": destination_chain,
                "source_network": source_network,
            },
        )

    async def simulate(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Simulate a transfer without executing."""
        result: dict[str, Any] = {
            "method": self.method.value,
            "recipient": recipient,
            "amount": str(amount),
        }

        wallet = self._wallet_service.get_wallet(wallet_id)
        source_network = Network.from_string(wallet.blockchain)

        if not self.supports(
            recipient,
            source_network=source_network,
            destination_chain=kwargs.get("destination_chain"),
        ):
            result["would_succeed"] = False
            result["reason"] = f"Invalid address format: {recipient}"
            return result

        try:
            balance = self._wallet_service.get_usdc_balance(wallet_id)
            result["current_balance"] = str(balance.amount)

            if balance.amount >= amount:
                result["would_succeed"] = True
                result["remaining_balance"] = str(balance.amount - amount)
            else:
                result["would_succeed"] = False
                result["reason"] = f"Insufficient balance: {balance.amount} < {amount}"
                result["shortfall"] = str(amount - balance.amount)

        except WalletError as e:
            result["would_succeed"] = False
            result["reason"] = f"Balance check failed: {e}"

        return result

    def get_priority(self) -> int:
        return 50
