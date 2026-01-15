"""
TransferAdapter - Direct USDC wallet-to-wallet transfers.

Handles payments to blockchain addresses using Circle's transfer API.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from omniagentpay.core.exceptions import PaymentError, WalletError, InsufficientBalanceError
from omniagentpay.protocols.base import ProtocolAdapter
from omniagentpay.core.types import (
    FeeLevel,
    PaymentMethod,
    PaymentResult,
    PaymentStatus,
    TransactionState,
)

if TYPE_CHECKING:
    from omniagentpay.core.config import Config
    from omniagentpay.wallet.service import WalletService


# Regex patterns for blockchain addresses
EVM_ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
SOLANA_ADDRESS_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


from omniagentpay.core.logging import get_logger


class TransferAdapter(ProtocolAdapter):
    """Adapter for direct USDC transfers between wallets (EVM & Solana)."""
    
    def __init__(
        self,
        config: "Config",
        wallet_service: "WalletService",
    ) -> None:
        self._config = config
        self._wallet_service = wallet_service
        self._logger = get_logger("transfer")
    
    @property
    def method(self) -> PaymentMethod:
        return PaymentMethod.TRANSFER
    
    def supports(self, recipient: str, **kwargs: Any) -> bool:
        """Check if recipient is a valid blockchain address for current network."""
        # Determine network context (Source Wallet wins over Global Config)
        network = kwargs.get("source_network") or self._config.network
        
        dest_chain = kwargs.get("destination_chain")
        if dest_chain:
            d_str = str(dest_chain).upper()
            n_str = str(network).upper()
            if d_str != n_str:
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
        if address.startswith("0x"):
            return False
        return True
    
    async def execute(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal,
        purpose: str | None = None,
        fee_level: FeeLevel = FeeLevel.MEDIUM,
        wait_for_completion: bool = False,
        timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> PaymentResult:
        """Execute a direct USDC transfer."""
        try:
            transfer_result = self._wallet_service.transfer(
                wallet_id=wallet_id,
                destination_address=recipient,
                amount=amount,
                fee_level=fee_level,
                check_balance=True,
                wait_for_completion=wait_for_completion,
                timeout_seconds=timeout_seconds,
                idempotency_key=kwargs.get("idempotency_key"),
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
                transaction_id=transfer_result.transaction.id if transfer_result.transaction else None,
                blockchain_tx=transfer_result.tx_hash,
                amount=amount,
                recipient=recipient,
                method=self.method,
                status=PaymentStatus.FAILED,
                error=transfer_result.error,
            )
        
        tx = transfer_result.transaction
        status = PaymentStatus.PROCESSING
        if tx:
            if tx.state == TransactionState.COMPLETE:
                status = PaymentStatus.COMPLETED
            elif tx.state == TransactionState.FAILED:
                status = PaymentStatus.FAILED
            elif tx.is_terminal():
                status = PaymentStatus.FAILED
                
        return PaymentResult(
            success=True,
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
        
        if not self.supports(recipient):
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
