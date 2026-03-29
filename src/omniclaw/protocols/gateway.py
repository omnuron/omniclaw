"""GatewayAdapter - Cross-chain USDC transfers via Circle CCTP."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from omniclaw.core.gateway_client import usdc_to_units
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


class GatewayAdapter(ProtocolAdapter):
    """Adapter for cross-chain transfers via CCTP."""

    def __init__(
        self,
        config: Config,
        wallet_service: WalletService,
        gateway_client: Any | None = None,
    ) -> None:
        """Initialize GatewayAdapter."""
        self._config = config
        self._wallet_service = wallet_service
        # gateway_client reserved for future API integration
        self._gateway_client = gateway_client
        self._logger = get_logger("gateway")

    @property
    def method(self) -> PaymentMethod:
        """Return payment method type."""
        return PaymentMethod.CROSSCHAIN

    def supports(
        self,
        recipient: str,
        source_network: Network | str | None = None,
        destination_chain: Network | str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Check if this is a valid cross-chain transfer request."""
        if destination_chain is None:
            return False
        return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", recipient))

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
        """Execute a cross-chain transfer."""

        source_network = source_network or self._config.network
        strict_settlement = bool(getattr(self._config, "payment_strict_settlement", True))
        canonical_idempotency_key = idempotency_key or derive_idempotency_key(
            "gateway",
            wallet_id,
            recipient,
            str(amount),
            purpose,
            source_network.value if hasattr(source_network, "value") else source_network,
            destination_chain.value if hasattr(destination_chain, "value") else destination_chain,
            kwargs.get("use_fast_transfer", True),
        )

        use_fast_transfer = kwargs.get("use_fast_transfer", True)

        if not destination_chain:
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=recipient,
                method=self.method,
                status=PaymentStatus.FAILED,
                error="destination_chain parameter is required",
            )

        destination_address = recipient
        strict_destination_validation = bool(kwargs.get("strict_destination_validation", False))
        if strict_destination_validation and not re.fullmatch(
            r"0x[a-fA-F0-9]{40}",
            destination_address,
        ):
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=recipient,
                method=self.method,
                status=PaymentStatus.FAILED,
                error=f"Invalid destination EVM address: {destination_address!r}",
            )

        # Normalize network types to Network enums
        source_network = self._normalize_network(source_network)
        destination_chain = self._normalize_network(destination_chain)

        if source_network == destination_chain:
            try:
                transfer_result = await self._wallet_service.transfer(
                    wallet_id=wallet_id,
                    destination_address=destination_address,
                    amount=amount,
                    fee_level=fee_level,
                    wait_for_completion=wait_for_completion,
                    idempotency_key=canonical_idempotency_key,
                    timeout_seconds=timeout_seconds,
                )

                # Backward compatibility for tests/mocks that return a raw tx object
                if not hasattr(transfer_result, "success"):
                    raw_tx = transfer_result
                    transfer_result = type(
                        "GatewayTransferResult",
                        (),
                        {
                            "success": True,
                            "transaction": raw_tx,
                            "tx_hash": getattr(raw_tx, "tx_hash", None),
                            "error": None,
                        },
                    )()

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
                        error=transfer_result.error or "Same-chain transfer failed",
                    )

                tx_status = (
                    PaymentStatus.PENDING_SETTLEMENT if strict_settlement else PaymentStatus.PENDING
                )
                if transfer_result.transaction:
                    if transfer_result.transaction.state == TransactionState.COMPLETE:
                        tx_status = (
                            PaymentStatus.SETTLED if strict_settlement else PaymentStatus.COMPLETED
                        )
                    elif transfer_result.transaction.state in (
                        TransactionState.FAILED,
                        TransactionState.CANCELLED,
                    ):
                        tx_status = (
                            PaymentStatus.FAILED_FINAL
                            if strict_settlement
                            else PaymentStatus.FAILED
                        )
                    elif wait_for_completion:
                        tx_status = (
                            PaymentStatus.PENDING_SETTLEMENT
                            if strict_settlement
                            else PaymentStatus.PROCESSING
                        )

                tx_id = transfer_result.transaction.id if transfer_result.transaction else None
                return PaymentResult(
                    success=(
                        is_irreversible_success_status(tx_status)
                        if strict_settlement
                        else tx_status != PaymentStatus.FAILED
                    ),
                    transaction_id=tx_id,
                    blockchain_tx=transfer_result.tx_hash,
                    amount=amount,
                    recipient=recipient,
                    method=self.method,
                    status=tx_status,
                    metadata={
                        "source_network": source_network.value
                        if hasattr(source_network, "value")
                        else str(source_network),
                        "destination_network": destination_chain.value
                        if hasattr(destination_chain, "value")
                        else str(destination_chain),
                        "destination_address": destination_address,
                        "purpose": purpose,
                        "same_chain": True,
                        "idempotency_key": canonical_idempotency_key,
                    },
                )
            except Exception as e:
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=amount,
                    recipient=recipient,
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error=f"Same-chain transfer failed: {e}",
                    metadata={
                        "source_network": source_network.value
                        if hasattr(source_network, "value")
                        else str(source_network),
                        "destination_network": destination_chain.value
                        if hasattr(destination_chain, "value")
                        else str(destination_chain),
                        "destination_address": destination_address,
                        "purpose": purpose,
                    },
                )
        else:
            try:
                result = await self._execute_cctp_transfer(
                    wallet_id=wallet_id,
                    source_network=source_network,
                    dest_network=destination_chain,
                    destination_address=destination_address,
                    amount=amount,
                    fee_level=fee_level,
                    wait_for_completion=wait_for_completion,
                    use_fast_transfer=use_fast_transfer,
                    idempotency_key=canonical_idempotency_key,
                    strict_settlement=strict_settlement,
                )
                return result
            except Exception as e:
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=amount,
                    recipient=recipient,
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error=f"Cross-chain transfer failed: {e}",
                    metadata={
                        "source_network": source_network.value,
                        "destination_network": destination_chain.value,
                        "destination_address": destination_address,
                        "purpose": purpose,
                    },
                )

    async def _execute_cctp_transfer(
        self,
        wallet_id: str,
        source_network: Network,
        dest_network: Network,
        destination_address: str,
        amount: Decimal,
        fee_level: FeeLevel = FeeLevel.MEDIUM,
        wait_for_completion: bool = True,
        use_fast_transfer: bool = True,
        idempotency_key: str | None = None,
        strict_settlement: bool = True,
    ) -> PaymentResult:
        """
        Execute a CCTP V2 cross-chain transfer.

        Args:
            wallet_id: Source wallet ID
            source_network: Source chain
            dest_network: Destination chain
            destination_address: Recipient address
            amount: Amount in USDC
            fee_level: Gas fee level
            wait_for_completion: Wait for burn tx completion
            use_fast_transfer: Use Fast Transfer (2-5 secs) vs Standard (13-19 mins)
        """
        from omniclaw.core.cctp_constants import (
            CCTP_DOMAIN_IDS,
            DEFAULT_MAX_FEE,
            EMPTY_DESTINATION_CALLER,
            FAST_TRANSFER_THRESHOLD,
            STANDARD_TRANSFER_THRESHOLD,
            USDC_CONTRACTS,
            get_iris_v2_attestation_url,
            get_token_messenger_v2,
            is_cctp_supported,
        )

        # Validate network support
        if not is_cctp_supported(source_network):
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=f"{dest_network.value}:{destination_address}",
                method=self.method,
                status=PaymentStatus.FAILED,
                error=f"Source network {source_network.value} not supported by CCTP",
            )

        if not is_cctp_supported(dest_network):
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=f"{dest_network.value}:{destination_address}",
                method=self.method,
                status=PaymentStatus.FAILED,
                error=f"Destination network {dest_network.value} not supported by CCTP",
            )

        # Get V2 contract addresses
        source_network_str = source_network.value
        token_messenger = get_token_messenger_v2(source_network)
        usdc_address = USDC_CONTRACTS.get(source_network_str)

        if not token_messenger or not usdc_address:
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=f"{dest_network.value}:{destination_address}",
                method=self.method,
                status=PaymentStatus.FAILED,
                error=f"CCTP V2 contracts not configured for {source_network_str}",
            )

        # Prepare transaction parameters
        amount_units = usdc_to_units(amount)
        dest_address_bytes32 = "0x" + destination_address.lower().replace("0x", "").zfill(64)
        source_domain = CCTP_DOMAIN_IDS[source_network]
        dest_domain = CCTP_DOMAIN_IDS[dest_network]
        # V2 Transfer parameters
        # Arc Testnet: Explicitly disable Fast Transfer (Source not supported per docs)
        # Also disable Forwarding Service (max_fee=0) as fallback to prevent reverts
        if source_network == Network.ARC_TESTNET:
            use_fast_transfer = False
            finality_threshold = STANDARD_TRANSFER_THRESHOLD
            max_fee = 0  # Force manual mint to avoid revert risks
            transfer_mode = "Standard Transfer (~13-19m)"
        else:
            finality_threshold = (
                FAST_TRANSFER_THRESHOLD if use_fast_transfer else STANDARD_TRANSFER_THRESHOLD
            )
            fallback_max_fee = DEFAULT_MAX_FEE if use_fast_transfer else 0
            max_fee = await self._resolve_cctp_max_fee(
                source_network=source_network,
                source_domain=source_domain,
                dest_domain=dest_domain,
                finality_threshold=finality_threshold,
                amount_units=amount_units,
                fallback_fee=fallback_max_fee,
            )
            transfer_mode = (
                "Fast Transfer (~2-5s)" if use_fast_transfer else "Standard Transfer (~13-19m)"
            )

        # Gas check (except Arc)
        if source_network != Network.ARC_TESTNET:
            try:
                from omniclaw.utils.gas import check_gas_requirements

                try:
                    native_balance = self._wallet_service.get_native_balance(wallet_id)
                    has_gas, gas_error = check_gas_requirements(
                        source_network, native_balance, "CCTP transfer"
                    )
                    if not has_gas:
                        return PaymentResult(
                            success=False,
                            transaction_id=None,
                            blockchain_tx=None,
                            amount=amount,
                            recipient=f"{dest_network.value}:{destination_address}",
                            method=self.method,
                            status=PaymentStatus.FAILED,
                            error=gas_error,
                        )
                except AttributeError:
                    self._logger.debug("Gas pre-flight check skipped (method not available)")
            except ImportError:
                self._logger.debug("Gas utilities not available")

        # Approve TokenMessengerV2
        self._logger.info(f"CCTP V2: Approving {amount} USDC for TokenMessengerV2")

        try:
            approve_tx = self._wallet_service._circle.create_contract_execution(
                wallet_id=wallet_id,
                contract_address=usdc_address,
                abi_function_signature="approve(address,uint256)",
                abi_parameters=[token_messenger, str(amount_units)],
                fee_level=fee_level,
            )

            # Wait for approval confirmation to prevent race condition with burn
            self._logger.info("CCTP V2: Waiting for approval transaction confirmation...")
            approval_confirmed = False
            for wait_attempt in range(60):  # 2 minutes max
                await asyncio.sleep(2)
                updated_approve_tx = self._wallet_service._circle.get_transaction(approve_tx.id)

                if updated_approve_tx.state in (
                    TransactionState.CONFIRMED,
                    TransactionState.COMPLETE,
                    TransactionState.CLEARED,
                    TransactionState.FAILED,
                    TransactionState.CANCELLED,
                ):
                    if updated_approve_tx.state in (
                        TransactionState.FAILED,
                        TransactionState.CANCELLED,
                    ):
                        self._logger.error("CCTP V2: Approval transaction FAILED on blockchain")
                        return PaymentResult(
                            success=False,
                            transaction_id=approve_tx.id,
                            blockchain_tx=updated_approve_tx.tx_hash,
                            amount=amount,
                            recipient=f"{dest_network.value}:{destination_address}",
                            method=self.method,
                            status=PaymentStatus.FAILED,
                            error="USDC Approval failed on blockchain",
                        )
                    approval_confirmed = True
                    self._logger.info(f"CCTP V2: Approval confirmed: {updated_approve_tx.tx_hash}")
                    break

                if wait_attempt % 5 == 0:
                    self._logger.debug(f"Waiting for approval... state={updated_approve_tx.state}")

            if not approval_confirmed:
                return PaymentResult(
                    success=False,
                    transaction_id=approve_tx.id,
                    blockchain_tx=updated_approve_tx.tx_hash,
                    amount=amount,
                    recipient=f"{dest_network.value}:{destination_address}",
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error="USDC approval did not confirm within 2 minutes",
                )

        except Exception as e:
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=f"{dest_network.value}:{destination_address}",
                method=self.method,
                status=PaymentStatus.FAILED,
                error=f"CCTP V2 approval failed: {e}",
            )

        # Burn USDC via depositForBurn
        self._logger.info(f"CCTP V2: Burning USDC on {source_network.value} ({transfer_mode})")

        try:
            # depositForBurn(amount, destDomain, mintRecipient, burnToken, destCaller, maxFee, minFinalityThreshold)
            burn_tx = self._wallet_service._circle.create_contract_execution(
                wallet_id=wallet_id,
                contract_address=token_messenger,
                abi_function_signature="depositForBurn(uint256,uint32,bytes32,address,bytes32,uint256,uint32)",
                abi_parameters=[
                    str(amount_units),  # amount
                    str(dest_domain),  # destinationDomain
                    dest_address_bytes32,  # mintRecipient
                    usdc_address,  # burnToken
                    EMPTY_DESTINATION_CALLER,  # destinationCaller (0x00 = any)
                    str(max_fee),  # maxFee
                    str(finality_threshold),  # minFinalityThreshold
                ],
                fee_level=fee_level,
            )

            # Wait for burn transaction to be confirmed and get tx_hash
            self._logger.info("CCTP V2: Waiting for burn transaction confirmation...")
            burn_tx_hash = None
            for wait_attempt in range(150):  # 150 attempts * 2 seconds = 5 minutes max
                await asyncio.sleep(2)
                updated_tx = self._wallet_service._circle.get_transaction(burn_tx.id)

                if updated_tx.tx_hash:
                    burn_tx_hash = updated_tx.tx_hash
                    self._logger.info(f"CCTP V2: Burn tx confirmed: {burn_tx_hash}")
                    break

                if updated_tx.state in (
                    TransactionState.CONFIRMED,
                    TransactionState.COMPLETE,
                    TransactionState.CLEARED,
                    TransactionState.FAILED,
                    TransactionState.CANCELLED,
                ):
                    burn_tx_hash = updated_tx.tx_hash
                    if updated_tx.state in (TransactionState.FAILED, TransactionState.CANCELLED):
                        self._logger.error("CCTP V2: Burn transaction FAILED on blockchain")
                        return PaymentResult(
                            success=False,
                            transaction_id=burn_tx.id,
                            blockchain_tx=burn_tx_hash,
                            amount=amount,
                            recipient=f"{dest_network.value}:{destination_address}",
                            method=self.method,
                            status=PaymentStatus.FAILED,
                            error="Burn transaction reverted on blockchain (Check gas/parameters)",
                            metadata={"burn_tx_id": burn_tx.id, "burn_tx_state": updated_tx.state},
                        )
                    break

                if wait_attempt % 5 == 0:  # Log every 10 seconds
                    self._logger.debug(f"Waiting for burn tx... state={updated_tx.state}")

            if not burn_tx_hash:
                return PaymentResult(
                    success=False,
                    transaction_id=burn_tx.id,
                    blockchain_tx=None,
                    amount=amount,
                    recipient=f"{dest_network.value}:{destination_address}",
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error="Burn transaction did not confirm within 5 minutes",
                )

            # Step 3: Poll for attestation from Circle Iris API
            self._logger.info(
                f"CCTP V2: Polling for attestation (Fast Transfer: {use_fast_transfer})"
            )
            attestation_url = get_iris_v2_attestation_url(
                source_network, source_domain, burn_tx_hash
            )

            attestation_message = None
            attestation_signature = None
            max_attempts = 240  # 240 attempts × 5 seconds = 20 minutes for Standard Transfer
            attempt = 0

            self._logger.info(f"Attestation URL: {attestation_url}")

            while attempt < max_attempts:
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(attestation_url, timeout=10.0)

                        if response.status_code == 200:
                            data = response.json()
                            messages = data.get("messages", [])

                            if messages and len(messages) > 0:
                                message_data = messages[0]
                                status = message_data.get("status")

                                self._logger.debug(f"Attempt {attempt + 1}: status={status}")

                                if status == "complete":
                                    attestation_signature = message_data.get("attestation")
                                    attestation_message = message_data.get("message")
                                    self._logger.info(
                                        f"CCTP V2: Attestation received after {attempt * 5}s"
                                    )
                                    break
                            else:
                                self._logger.debug(f"No messages yet (attempt {attempt + 1})")
                        elif response.status_code == 404:
                            self._logger.debug(
                                f"Transaction not yet indexed (attempt {attempt + 1})"
                            )
                        else:
                            self._logger.debug(f"HTTP {response.status_code}")

                except Exception as e:
                    self._logger.debug(f"Poll attempt {attempt + 1} failed: {e}")

                attempt += 1
                if attempt < max_attempts:
                    await asyncio.sleep(5)

            if not attestation_signature or not attestation_message:
                self._logger.warning("CCTP V2: Attestation polling timed out")
                return PaymentResult(
                    success=False,
                    transaction_id=burn_tx.id,
                    blockchain_tx=burn_tx.tx_hash,
                    amount=amount,
                    recipient=f"{dest_network.value}:{destination_address}",
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error="Attestation polling timed out after 20 minutes",
                    metadata={
                        "cctp_version": "v2",
                        "burn_tx_id": burn_tx.id,
                        "attestation_url": attestation_url,
                    },
                )

            # Step 4: Cross-Chain Transfer Handoff or Agent-Side Mint
            # If max_fee > 0, we generally assume Forwarding Service (Relayer) will pick it up.
            # However, for some networks (like Arc Testnet) or if max_fee == 0, we perform Agent-Side Minting.

            is_relayed = max_fee > 0
            should_mint = not is_relayed or dest_network == Network.ARC_TESTNET
            attestation_message_hash = (
                hashlib.sha256(attestation_message.encode("utf-8")).hexdigest()
                if attestation_message
                else None
            )
            attestation_signature_hash = (
                hashlib.sha256(attestation_signature.encode("utf-8")).hexdigest()
                if attestation_signature
                else None
            )

            mint_result = None
            status = (
                PaymentStatus.PENDING_SETTLEMENT if strict_settlement else PaymentStatus.PROCESSING
            )

            if should_mint:
                self._logger.info(
                    f"CCTP V2: Attempting Agent-Side Mint (relayed={is_relayed}, dest={dest_network.value})"
                )
                mint_result = await self._mint_usdc(
                    attestation_message, attestation_signature, dest_network
                )

                if mint_result["success"]:
                    note = (
                        f"Transfer completed via Agent-Side Mint. Tx: {mint_result.get('tx_hash')}"
                    )
                    blockchain_final_tx = mint_result.get("tx_hash")
                    status = (
                        PaymentStatus.PENDING_SETTLEMENT
                        if mint_result.get("status") == "pending_confirmation"
                        else (
                            PaymentStatus.SETTLED if strict_settlement else PaymentStatus.COMPLETED
                        )
                    )
                else:
                    note = f"Agent-Side Mint failed: {mint_result.get('error')}. Check destination wallet gas."
                    blockchain_final_tx = None
                    return PaymentResult(
                        success=False,
                        transaction_id=burn_tx.id,
                        blockchain_tx=burn_tx_hash,
                        amount=amount,
                        recipient=f"{dest_network.value}:{destination_address}",
                        method=self.method,
                        status=PaymentStatus.FAILED,
                        error=note,
                        metadata={
                            "cctp_version": "v2",
                            "cctp_flow": "burn_attestation_mint",
                            "transfer_mode": transfer_mode,
                            "source_domain": source_domain,
                            "destination_domain": dest_domain,
                            "burn_tx_id": burn_tx.id,
                            "burn_tx_hash": burn_tx_hash,
                            "mint_result": mint_result,
                            "attestation_url": attestation_url,
                            "source_network": source_network.value,
                            "destination_network": dest_network.value,
                            "destination_address": destination_address,
                            "max_fee_usdc": str(Decimal(max_fee) / Decimal("1000000")),
                            "min_finality_threshold": finality_threshold,
                        },
                    )
            else:
                note = "Transfer handed off to CCTP Relayer/Forwarding Service for final minting"
                blockchain_final_tx = None
                status = (
                    PaymentStatus.PENDING_SETTLEMENT
                    if strict_settlement
                    else PaymentStatus.PROCESSING
                )
                self._logger.info(f"CCTP V2: Attestation secured. {note} (max_fee={max_fee})")

            return PaymentResult(
                success=(
                    is_irreversible_success_status(status)
                    if strict_settlement
                    else status != PaymentStatus.FAILED
                ),
                transaction_id=burn_tx.id,
                blockchain_tx=burn_tx.tx_hash,  # Primary tx is the burn
                amount=amount,
                recipient=f"{dest_network.value}:{destination_address}",
                method=self.method,
                status=status,
                metadata={
                    "cctp_version": "v2",
                    "cctp_flow": "burn_attestation_mint"
                    if should_mint
                    else "burn_attestation_relay",
                    "transfer_mode": transfer_mode,
                    "source_domain": source_domain,
                    "destination_domain": dest_domain,
                    "burn_tx_id": burn_tx.id,
                    "burn_tx_hash": burn_tx_hash,
                    "mint_tx_hash": blockchain_final_tx,
                    "mint_result": mint_result,
                    "attestation_signature_hash": attestation_signature_hash,
                    "attestation_message_hash": attestation_message_hash,
                    "attestation_url": attestation_url,
                    "source_network": source_network.value,
                    "destination_network": dest_network.value,
                    "destination_address": destination_address,
                    "max_fee_usdc": str(Decimal(max_fee) / Decimal("1000000")),
                    "min_finality_threshold": finality_threshold,
                    "note": note,
                    "settlement_final": bool(
                        should_mint and mint_result and mint_result.get("success")
                    ),
                    "manual_mint_required": not is_relayed
                    and (not mint_result or not mint_result.get("success")),
                    "idempotency_key": idempotency_key,
                },
            )

        except Exception as e:
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=f"{dest_network.value}:{destination_address}",
                method=self.method,
                status=PaymentStatus.FAILED,
                error=f"CCTP V2 burn failed: {e}",
            )

    async def simulate(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Simulate a cross-chain transfer."""
        from omniclaw.core.cctp_constants import is_cctp_supported

        result: dict[str, Any] = {
            "method": self.method.value,
            "recipient": recipient,
            "amount": str(amount),
        }

        source_network = kwargs.get("source_network") or self._config.network
        dest_network = kwargs.get("destination_chain")

        if not dest_network:
            result["would_succeed"] = False
            result["reason"] = "destination_chain parameter required"
            return result

        # Handle string or Network enum
        source_net_str = (
            source_network.value if isinstance(source_network, Network) else str(source_network)
        )
        dest_net_str = (
            dest_network.value if isinstance(dest_network, Network) else str(dest_network)
        )

        result["source_network"] = source_net_str
        result["destination_network"] = dest_net_str
        result["destination_address"] = recipient

        if source_network == dest_network:
            result["is_same_chain"] = True
            result["note"] = "Same-chain transfer, no CCTP needed"
            try:
                balance = self._wallet_service.get_usdc_balance_amount(wallet_id)
                result["would_succeed"] = balance >= amount
                result["current_balance"] = str(balance)
                if not result["would_succeed"] and balance is not None:
                    result["reason"] = f"Insufficient balance: {balance} < {amount}"
                elif balance is None:
                    result["reason"] = "Could not retrieve balance"
            except Exception as e:
                result["would_succeed"] = False
                result["reason"] = f"Balance check failed: {e}"
        else:
            result["is_same_chain"] = False
            if is_cctp_supported(source_network) and is_cctp_supported(dest_network):
                result["would_succeed"] = True
                result["estimated_time"] = "~2-5 seconds (Fast Transfer)"
            else:
                result["would_succeed"] = False
                result["reason"] = f"CCTP not supported for {source_net_str} -> {dest_net_str}"

        return result

    async def _resolve_cctp_max_fee(
        self,
        source_network: Network,
        source_domain: int,
        dest_domain: int,
        finality_threshold: int,
        amount_units: int,
        fallback_fee: int,
    ) -> int:
        """
        Fetch route-specific minimum fee from Iris and use it as maxFee.

        Falls back to fallback_fee if lookup fails.
        """
        from omniclaw.core.cctp_constants import get_iris_url

        fees_url = f"{get_iris_url(source_network)}/v2/burn/USDC/fees/{source_domain}/{dest_domain}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(fees_url, headers={"Accept": "application/json"})
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, list):
                return fallback_fee

            exact_match_bps: int | None = None
            fallback_match_bps: int | None = None
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                ft = int(entry.get("finalityThreshold", -1))
                fee_bps = max(int(entry.get("minimumFee", 0)), 0)
                if ft == finality_threshold:
                    exact_match_bps = fee_bps
                    break
                if finality_threshold <= 1000 and ft <= 1000:
                    fallback_match_bps = fee_bps
                if finality_threshold >= 2000 and ft >= 2000:
                    fallback_match_bps = fee_bps

            selected_bps = exact_match_bps if exact_match_bps is not None else fallback_match_bps
            if selected_bps is None:
                return fallback_fee

            # Circle Iris /v2/burn/USDC/fees returns minimumFee as basis points (bps).
            # maxFee in depositForBurn is token units, so convert: amount * bps / 10_000.
            computed_fee = math.ceil((amount_units * selected_bps) / 10_000)
            if selected_bps > 0 and computed_fee == 0:
                computed_fee = 1
            return max(computed_fee, fallback_fee)
        except Exception as exc:
            self._logger.warning(
                "CCTP fee lookup failed (%s). Using fallback max fee=%s",
                exc,
                fallback_fee,
            )
            return fallback_fee

    async def _mint_usdc(
        self,
        attestation_message: str,
        attestation_signature: str,
        dest_network: Network,
    ) -> dict[str, Any]:
        """
        Mint USDC on the destination chain via the Agent SDK (Agent-Side Minting).

        Args:
            attestation_message: The message bytes (hex)
            attestation_signature: The signature bytes (hex)
            dest_network: Destination network

        Returns:
            Dict with mint transaction details
        """
        from omniclaw.core.cctp_constants import get_message_transmitter_v2

        message_transmitter = get_message_transmitter_v2(dest_network)
        if not message_transmitter:
            return {
                "success": False,
                "error": f"No MessageTransmitter configured for {dest_network.value}",
            }

        # Find a wallet on the destination chain to execute the transaction
        # Any wallet with gas can do this
        executor_wallet = await self._get_executor_wallet(dest_network)
        if not executor_wallet:
            return {
                "success": False,
                "error": f"No wallet found on {dest_network.value} to execute minting. Please create a wallet on this network with native gas tokens.",
            }

        self._logger.info(
            f"CCTP V2: Minting via wallet {executor_wallet.id} on {dest_network.value}"
        )

        try:
            # receiveMessage(message, attestation)
            mint_tx = self._wallet_service._circle.create_contract_execution(
                wallet_id=executor_wallet.id,
                contract_address=message_transmitter,
                abi_function_signature="receiveMessage(bytes,bytes)",
                abi_parameters=[attestation_message, attestation_signature],
                fee_level=FeeLevel.MEDIUM,
            )

            # Wait for mint confirmation
            self._logger.info("CCTP V2: Waiting for mint transaction confirmation...")
            mint_tx_hash = None
            for _wait_attempt in range(60):
                await asyncio.sleep(2)
                updated_tx = self._wallet_service._circle.get_transaction(mint_tx.id)

                if updated_tx.tx_hash:
                    mint_tx_hash = updated_tx.tx_hash

                if updated_tx.state in (
                    TransactionState.CONFIRMED,
                    TransactionState.COMPLETE,
                    TransactionState.FAILED,
                ):
                    if updated_tx.state == TransactionState.FAILED:
                        return {
                            "success": False,
                            "error": "Mint transaction FAILED on blockchain",
                            "tx_id": mint_tx.id,
                            "tx_hash": updated_tx.tx_hash,
                        }

                    self._logger.info(f"CCTP V2: Mint confirmed: {updated_tx.tx_hash}")
                    return {
                        "success": True,
                        "tx_id": mint_tx.id,
                        "tx_hash": updated_tx.tx_hash,
                        "executor_wallet": executor_wallet.id,
                    }

            if mint_tx_hash:
                return {
                    "success": True,
                    "tx_id": mint_tx.id,
                    "tx_hash": mint_tx_hash,
                    "executor_wallet": executor_wallet.id,
                    "status": "pending_confirmation",
                }

            return {
                "success": False,
                "error": "Mint transaction timed out (no hash generated)",
                "tx_id": mint_tx.id,
            }

        except Exception as e:
            self._logger.error(f"CCTP V2: Mint exception: {e}")
            return {"success": False, "error": str(e)}

    async def _get_executor_wallet(self, network: Network) -> Any | None:
        """Find a suitable wallet on the given network to execute transactions."""
        try:
            # List all wallets for this network
            wallets = self._wallet_service.list_wallets(blockchain=network)

            # Filter for active wallets
            active_wallets = [w for w in wallets if w.state == "LIVE"]

            if not active_wallets:
                return None

            # Ideally checks for gas, but for now return the first one
            # The user should ensure their wallets are funded
            return active_wallets[0]

        except Exception as e:
            self._logger.error(f"Failed to find executor wallet: {e}")
            return None

    @staticmethod
    def _normalize_network(network: Network | str | None) -> Network | str | None:
        """Normalize a network parameter to a Network enum if possible."""
        if network is None or isinstance(network, Network):
            return network
        try:
            return Network(network)
        except (ValueError, KeyError):
            # Try uppercase variant
            try:
                return Network(str(network).upper().replace("-", "_"))
            except (ValueError, KeyError):
                return network  # Return as-is if not a known enum value

    def get_priority(self) -> int:
        """Gateway adapter has medium priority."""
        return 30


__all__ = ["GatewayAdapter"]
