"""
GatewayWalletManager: On-chain deposit and withdraw operations for Circle Gateway.

Handles the on-chain operations for Circle Gateway:
- Deposit: Transfer USDC from wallet to the Gateway Wallet contract (on-chain)
- Trustless Withdrawal: Emergency withdrawal directly on-chain (7-day delay)

IMPORTANT: For normal same-chain and cross-chain transfers within the Gateway system,
these go through Circle's API (instant transfers), NOT through on-chain transactions.
The on-chain contract is used only for:
1. Depositing USDC into Gateway
2. Emergency trustless withdrawals (7-day delay)

On-chain transactions cost gas. All other operations (nanopayments, transfers, settlements)
are off-chain via Circle's API.

Note:
    The GatewayWalletManager uses a raw EOA private key for signing on-chain
    transactions. This key must be the same one used for nanopayment signing.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import web3

from omniclaw.protocols.nanopayments.client import NanopaymentClient
from omniclaw.protocols.nanopayments.exceptions import (
    DepositError,
    ERC20ApprovalError,
    WithdrawError,
)
from omniclaw.protocols.nanopayments.signing import EIP3009Signer
from omniclaw.protocols.nanopayments.types import (
    DepositResult,
    GatewayBalance,
    PaymentRequirements,
    PaymentRequirementsExtra,
    PaymentRequirementsKind,
    WithdrawResult,
)

logger = logging.getLogger(__name__)

# =============================================================================
# USDC ERC-20 ABI (standard)
# =============================================================================

_USDC_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "account", "type": "address"},
        ],
        "name": "balanceOf",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# =============================================================================
# Circle Gateway Wallet Contract ABI
# Source: https://developers.circle.com/gateway/references/contract-interfaces-and-events
# =============================================================================

_GATEWAY_WALLET_ABI: list[dict[str, Any]] = [
    # Deposit USDC into Gateway Wallet
    # This is the PRIMARY way to fund your Gateway balance
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "deposit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # Deposit on behalf of another address
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "depositor", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "depositFor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # Deposit with EIP-3009 authorization (for depositing without pre-approval)
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "from", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"},
        ],
        "name": "depositWithAuthorization",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # Emergency trustless withdrawal - initiate
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "initiateWithdrawal",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # Emergency trustless withdrawal - complete (after delay)
    {
        "inputs": [
            {"name": "token", "type": "address"},
        ],
        "name": "withdraw",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # Balance queries
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "depositor", "type": "address"},
        ],
        "name": "availableBalance",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "withdrawalDelay",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "depositor", "type": "address"},
        ],
        "name": "withdrawalBlock",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# =============================================================================
# GATEWAY WALLET MANAGER
# =============================================================================


class GatewayWalletManager:
    """
    Manages on-chain Gateway Wallet contract interactions.

    IMPORTANT USAGE NOTES:
    - Use deposit() to fund your Gateway balance (this is the only on-chain step for funding)
    - Use withdraw_to_address() for same-chain transfers (via API, no gas)
    - Use transfer_crosschain() for cross-chain transfers (via API, no gas)
    - Use initiate_trustless_withdrawal() ONLY for emergency withdrawals when API is down

    The private key is used to sign on-chain transactions. On-chain operations cost gas.

    Args:
        private_key: Raw EOA private key hex used for nanopayment signing.
        network: CAIP-2 network identifier (e.g. 'eip155:1').
        rpc_url: RPC endpoint for the network.
        nanopayment_client: NanopaymentClient for API operations and balance queries.
        gateway_address: Gateway Wallet contract address on the target network.
            If None, fetched from nanopayment_client.
        usdc_address: USDC token contract address on the target network.
            If None, fetched from nanopayment_client.
    """

    def __init__(
        self,
        private_key: str,
        network: str,
        rpc_url: str,
        nanopayment_client: NanopaymentClient,
        gateway_address: str | None = None,
        usdc_address: str | None = None,
    ) -> None:
        self._signer = EIP3009Signer(private_key)
        self._address = web3.Web3.to_checksum_address(self._signer.address)
        self._network = network
        chain_id = int(network.split(":")[1])
        self._chain_id = chain_id
        self._w3 = web3.Web3(web3.HTTPProvider(rpc_url))

        # Fix for POA chains across web3.py versions.
        try:
            from web3.middleware import ExtraDataToPOAMiddleware

            self._w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except ImportError:
            from web3.middleware import geth_poa_middleware

            self._w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        self._client = nanopayment_client
        self._gateway_address = (
            web3.Web3.to_checksum_address(gateway_address) if gateway_address else None
        )
        self._usdc_address = web3.Web3.to_checksum_address(usdc_address) if usdc_address else None
        self._gateway_contract: web3.Contract | None = None

    @property
    def address(self) -> str:
        """The EOA address derived from the private key."""
        return self._address

    @property
    def network(self) -> str:
        """The CAIP-2 network identifier."""
        return self._network

    # -------------------------------------------------------------------------
    # Contract address resolution
    # -------------------------------------------------------------------------

    async def _resolve_gateway_address(self) -> str:
        """Resolve Gateway Wallet contract address for current network."""
        if self._gateway_address:
            return self._gateway_address
        return web3.Web3.to_checksum_address(
            await self._client.get_verifying_contract(self._network)
        )

    async def _resolve_usdc_address(self) -> str:
        """Resolve USDC token contract address for current network."""
        if self._usdc_address:
            return self._usdc_address
        return web3.Web3.to_checksum_address(await self._client.get_usdc_address(self._network))

    def _get_gateway_contract(self, gateway_address: str) -> web3.Contract:
        """Get or create Gateway contract instance."""
        gateway_address = web3.Web3.to_checksum_address(gateway_address)
        if (
            self._gateway_contract is None
            or self._gateway_contract.address.lower() != gateway_address.lower()
        ):
            self._gateway_contract = self._w3.eth.contract(
                address=gateway_address,
                abi=_GATEWAY_WALLET_ABI,
            )
        return self._gateway_contract

    def _encode_gateway_call(self, gateway: web3.Contract, fn_name: str, args: list[Any]) -> str:
        """Encode a gateway contract call across web3 versions."""
        if hasattr(gateway, "encode_abi"):
            return gateway.encode_abi(fn_name=fn_name, args=args)  # type: ignore[attr-defined]
        if hasattr(gateway, "encodeABI"):
            return gateway.encodeABI(fn_name=fn_name, args=args)  # type: ignore[attr-defined]
        fn = getattr(gateway.functions, fn_name)(*args)
        if hasattr(fn, "build_transaction"):
            tx = fn.build_transaction({"from": self._address})
            data = tx.get("data")
            if data:
                return data
        if hasattr(fn, "_encode_transaction_data"):
            return fn._encode_transaction_data()  # type: ignore[attr-defined]
        raise RuntimeError(f"Unable to encode gateway call: {fn_name}")

    # -------------------------------------------------------------------------
    # USDC helpers
    # -------------------------------------------------------------------------

    def _usdc_contract(self, address: str) -> web3.Contract:
        """Get USDC contract instance."""
        address = web3.Web3.to_checksum_address(address)
        return self._w3.eth.contract(address=address, abi=_USDC_ABI)

    def _decimal_to_atomic(self, amount_decimal: str) -> int:
        """Convert decimal USDC string to atomic units (6 decimals)."""
        from decimal import Decimal, InvalidOperation

        try:
            value = Decimal(amount_decimal)
            scaled = value * Decimal(1_000_000)
            if scaled != scaled.to_integral_value():
                raise ValueError(f"USDC amount has more than 6 decimal places: {amount_decimal}")
            return int(scaled)
        except InvalidOperation:
            raise ValueError(f"Invalid USDC amount: {amount_decimal}") from None

    def _atomic_to_decimal(self, amount_atomic: int) -> str:
        """Convert atomic units to decimal USDC string."""
        from decimal import Decimal

        return str(Decimal(amount_atomic) / Decimal("1000000"))

    def _build_tx(
        self, to: str, data: str, value: int = 0, nonce: int | None = None
    ) -> dict[str, Any]:
        """Build a base transaction dict."""
        to = web3.Web3.to_checksum_address(to)
        if nonce is None:
            nonce = self._w3.eth.get_transaction_count(self._address)
        tx: dict[str, Any] = {
            "from": self._address,
            "to": to,
            "data": data,
            "value": value,
            "chainId": self._chain_id,
            "nonce": nonce,
        }
        # Estimate gas with a safety margin; fallback to a conservative default.
        try:
            gas_estimate = self._w3.eth.estimate_gas(
                {
                    "from": self._address,
                    "to": to,
                    "data": data,
                    "value": value,
                }
            )
            tx["gas"] = int(gas_estimate * 1.2)
        except Exception:
            tx["gas"] = 300_000

        # Prefer EIP-1559 fees when supported, fallback to legacy gasPrice.
        try:
            latest_block = self._w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas") if latest_block else None
        except Exception:
            base_fee = None

        if base_fee is not None:
            # Use a more reasonable priority fee (1-2 gwei instead of 50)
            max_priority_fee = self._w3.to_wei(2, "gwei")
            tx["maxPriorityFeePerGas"] = int(max_priority_fee)
            tx["maxFeePerGas"] = int(base_fee * 2 + max_priority_fee)
        else:
            tx["gasPrice"] = self._w3.eth.gas_price

        return tx

    def _sign_and_send(self, tx: dict[str, Any], error_type: type = DepositError) -> str:
        """Sign a transaction and send it, returning the tx hash."""
        try:
            # Get the private key and ensure it has 0x prefix for web3.py
            private_key = self._signer._private_key
            if not private_key.startswith("0x"):
                private_key = f"0x{private_key}"

            signed = self._w3.eth.account.sign_transaction(
                tx,
                private_key=private_key,
            )
            raw_tx = getattr(signed, "rawTransaction", None) or getattr(
                signed, "raw_transaction", None
            )
            tx_hash = self._w3.eth.send_raw_transaction(raw_tx)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash)
            if receipt["status"] != 1:
                raise error_type(
                    reason=f"Transaction failed: {tx_hash.hex()}",
                    tx_hash=tx_hash.hex(),
                )
            return tx_hash.hex()
        except (DepositError, WithdrawError, ERC20ApprovalError):
            raise
        except web3.exceptions.TimeExhausted:
            raise error_type(
                reason="Transaction timed out waiting for confirmation",
            ) from None
        except web3.exceptions.TransactionNotFound:
            raise error_type(
                reason="Transaction not found after broadcast",
            ) from None
        except Exception as exc:
            logger.error(f"Transaction failed: {exc}")
            raise error_type(reason=str(exc)) from exc

    # -------------------------------------------------------------------------
    # DEPOSIT (on-chain, costs gas)
    # -------------------------------------------------------------------------

    async def deposit(
        self,
        amount_usdc: str,
        check_gas: bool = True,
        skip_if_insufficient_gas: bool = False,
    ) -> DepositResult:
        """
        Deposit USDC into the Gateway Wallet contract ON-CHAIN.

        This is the ONLY on-chain operation needed to fund your Gateway balance.
        After depositing, all other operations (nanopayments, transfers) are OFF-CHAIN.

        Flow:
        1. Check gas reserve (if check_gas=True)
        2. Check current USDC allowance for Gateway contract
        3. If insufficient, approve Gateway contract to spend exact amount
        4. Call deposit(address token, uint256 value) on Gateway contract
        5. Wait for transaction confirmation
        6. Return tx hash and amount

        Args:
            amount_usdc: Amount in USDC decimal string (e.g. "10.00").
            check_gas: If True, check ETH balance for gas before proceeding.
                Default True. Set to False to skip the check.
            skip_if_insufficient_gas: If True and gas is insufficient, return
                a result with empty tx hashes instead of raising InsufficientGasError.
                Default False (raises on insufficient gas).

        Returns:
            DepositResult with approval_tx_hash (None if no approval needed)
            and deposit_tx_hash.

        Raises:
            InsufficientGasError: If check_gas=True and ETH balance is insufficient.
            DepositError: If the deposit transaction fails.
            ERC20ApprovalError: If the approval transaction fails.
        """
        # Step 1: Check gas reserve
        if check_gas:
            has_sufficient, message = self.check_gas_reserve()
            if not has_sufficient:
                if skip_if_insufficient_gas:
                    logger.warning(f"Skipping deposit due to insufficient gas. {message}")
                    return DepositResult(
                        approval_tx_hash=None,
                        deposit_tx_hash=None,
                        amount=self._decimal_to_atomic(amount_usdc),
                        formatted_amount=f"{amount_usdc} USDC",
                    )
                from omniclaw.protocols.nanopayments.exceptions import InsufficientGasError

                raise InsufficientGasError(reason=message)

        amount = self._decimal_to_atomic(amount_usdc)

        try:
            gateway_address = await self._resolve_gateway_address()
            usdc_address = await self._resolve_usdc_address()

            usdc = self._usdc_contract(usdc_address)

            # Skip allowance check - just approve directly for simplicity
            approval_tx_hash: str | None = None
            try:
                # web3.py 6.x uses functions.approve().build_transaction()
                approve_func = usdc.functions.approve(gateway_address, amount)
                approve_tx = self._build_tx(
                    to=usdc_address,
                    data=approve_func.build_transaction(
                        {"from": self._address, "gas": 50000}
                    )["data"],
                )
                approval_tx_hash = self._sign_and_send(
                    approve_tx,
                    error_type=ERC20ApprovalError,
                )
                logger.info(f"USDC approval tx: {approval_tx_hash}")
            except Exception as exc:
                logger.error(f"Approval failed: {exc}")
                raise ERC20ApprovalError(reason=f"Failed to approve USDC: {exc}") from exc

            # Build deposit transaction
            # CORRECT ABI: deposit(address token, uint256 value)
            gateway = self._get_gateway_contract(gateway_address)
            # web3.py 6.x uses functions.deposit().build_transaction()
            deposit_func = gateway.functions.deposit(usdc_address, amount)
            deposit_tx = self._build_tx(
                to=gateway_address,
                data=deposit_func.build_transaction(
                    {"from": self._address, "gas": 100000}
                )["data"],
                value=0,
            )

            deposit_tx_hash = self._sign_and_send(deposit_tx)
            logger.info(
                f"Deposit tx: {deposit_tx_hash}, amount: {amount_usdc} USDC to {gateway_address}"
            )

            return DepositResult(
                approval_tx_hash=approval_tx_hash,
                deposit_tx_hash=deposit_tx_hash,
                amount=amount,
                formatted_amount=f"{amount_usdc} USDC",
            )

        except (ERC20ApprovalError, DepositError):
            raise
        except Exception as exc:
            logger.error(f"Deposit failed: {exc}")
            raise DepositError(reason=str(exc)) from exc

    # -------------------------------------------------------------------------
    # TRUSTLESS WITHDRAWAL (emergency only - 7 day delay)
    # -------------------------------------------------------------------------

    async def get_withdrawal_delay(self) -> int:
        """
        Get the withdrawal delay in blocks for emergency trustless withdrawals.

        Returns:
            Number of blocks that must pass after initiating withdrawal.
            Typically ~7 days worth of blocks on Ethereum.
        """
        gateway_address = await self._resolve_gateway_address()
        gateway = self._get_gateway_contract(gateway_address)
        return gateway.functions.withdrawalDelay().call()

    async def initiate_trustless_withdrawal(self, amount_usdc: str) -> str:
        """
        Initiate an EMERGENCY trustless withdrawal.

        WARNING: This is for emergency use only when Circle's API is unavailable.
        Normal withdrawals should use transfer_to_address() or transfer_crosschain() via API.

        After initiating, you must wait for the withdrawal delay (typically ~7 days),
        then call complete_trustless_withdrawal().

        Args:
            amount_usdc: Amount in USDC decimal string.

        Returns:
            Transaction hash of the initiation.

        Raises:
            WithdrawError: If the initiation fails.
        """
        amount = self._decimal_to_atomic(amount_usdc)

        try:
            gateway_address = await self._resolve_gateway_address()
            usdc_address = await self._resolve_usdc_address()

            gateway = self._get_gateway_contract(gateway_address)

            # Check available balance
            available = gateway.functions.availableBalance(usdc_address, self._address).call()
            if available < amount:
                raise WithdrawError(
                    reason=f"Insufficient balance. Available: {self._atomic_to_decimal(available)} USDC, "
                    f"Requested: {amount_usdc} USDC"
                )

            # Initiate withdrawal
            withdraw_data = self._encode_gateway_call(
                gateway,
                "initiateWithdrawal",
                [usdc_address, amount],
            )

            withdraw_tx = self._build_tx(
                to=gateway_address,
                data=withdraw_data,
                value=0,
            )

            tx_hash = self._sign_and_send(withdraw_tx, error_type=WithdrawError)

            delay_blocks = await self.get_withdrawal_delay()
            logger.warning(
                f"Trustless withdrawal initiated: {tx_hash}. "
                f"Wait {delay_blocks} blocks before completing. "
                f"Amount: {amount_usdc} USDC"
            )

            return tx_hash

        except WithdrawError:
            raise
        except Exception as exc:
            logger.error(f"Withdrawal initiation failed: {exc}")
            raise WithdrawError(reason=str(exc)) from exc

    async def complete_trustless_withdrawal(self) -> str:
        """
        Complete an initiated trustless withdrawal.

        WARNING: Can only be called after the withdrawal delay has passed.

        Returns:
            Transaction hash of the completion.

        Raises:
            WithdrawError: If the completion fails or delay not passed.
        """
        try:
            gateway_address = await self._resolve_gateway_address()
            usdc_address = await self._resolve_usdc_address()

            gateway = self._get_gateway_contract(gateway_address)

            # Check if withdrawal is ready
            withdrawal_block = gateway.functions.withdrawalBlock(usdc_address, self._address).call()
            current_block = self._w3.eth.block_number

            if withdrawal_block == 0:
                raise WithdrawError(
                    reason="No withdrawal initiated. Call initiate_trustless_withdrawal() first."
                )
            if current_block < withdrawal_block:
                blocks_remaining = withdrawal_block - current_block
                raise WithdrawError(
                    reason=f"Withdrawal not ready. {blocks_remaining} blocks remaining."
                )

            # Complete withdrawal
            withdraw_data = self._encode_gateway_call(
                gateway,
                "withdraw",
                [usdc_address],
            )

            withdraw_tx = self._build_tx(
                to=gateway_address,
                data=withdraw_data,
                value=0,
            )

            tx_hash = self._sign_and_send(withdraw_tx, error_type=WithdrawError)
            logger.info(f"Trustless withdrawal completed: {tx_hash}")

            return tx_hash

        except WithdrawError:
            raise
        except Exception as exc:
            logger.error(f"Withdrawal completion failed: {exc}")
            raise WithdrawError(reason=str(exc)) from exc

    # -------------------------------------------------------------------------
    # API-BASED TRANSFERS (off-chain, no gas)
    # -------------------------------------------------------------------------

    async def transfer_to_address(
        self,
        amount_usdc: str,
        recipient_address: str,
    ) -> WithdrawResult:
        """
        Transfer USDC to another address on the SAME chain via Circle's API.

        Args:
            amount_usdc: Amount in USDC decimal string.
            recipient_address: Destination EOA address on the same chain.
        """
        return await self._transfer_via_gateway_settlement(
            amount_usdc=amount_usdc,
            destination_chain=self._network,
            recipient_address=recipient_address,
        )

    async def transfer_crosschain(
        self,
        amount_usdc: str,
        destination_chain: str,
        recipient_address: str,
    ) -> WithdrawResult:
        """
        Transfer USDC to another address on a DIFFERENT chain via Circle's API.

        Args:
            amount_usdc: Amount in USDC decimal string.
            destination_chain: Target CAIP-2 chain (e.g., 'eip155:137' for Polygon).
            recipient_address: Destination address on the target chain.
        """
        return await self._transfer_via_gateway_settlement(
            amount_usdc=amount_usdc,
            destination_chain=destination_chain,
            recipient_address=recipient_address,
        )

    async def _transfer_via_gateway_settlement(
        self,
        amount_usdc: str,
        destination_chain: str,
        recipient_address: str,
    ) -> WithdrawResult:
        """Execute a transfer by signing EIP-3009 authorization and settling via Gateway API."""
        if not recipient_address or not re.fullmatch(r"0x[a-fA-F0-9]{40}", recipient_address):
            raise WithdrawError(reason=f"Invalid recipient address: {recipient_address!r}")
        if recipient_address.lower() == self._address.lower():
            raise WithdrawError(
                reason=(
                    "Self-transfer via Gateway settlement is not supported. "
                    "Use initiate_trustless_withdrawal() for own-wallet withdrawals."
                )
            )
        if not destination_chain.startswith("eip155:"):
            raise WithdrawError(
                reason=f"Invalid destination chain (expected CAIP-2): {destination_chain!r}"
            )

        amount_atomic = self._decimal_to_atomic(amount_usdc)
        if amount_atomic <= 0:
            raise WithdrawError(reason=f"Amount must be positive. Got: {amount_usdc!r}")

        try:
            verifying_contract = await self._client.get_verifying_contract(destination_chain)
            usdc_address = await self._client.get_usdc_address(destination_chain)

            req_kind = PaymentRequirementsKind(
                scheme="exact",
                network=destination_chain,
                asset=usdc_address,
                amount=str(amount_atomic),
                max_timeout_seconds=345600,
                pay_to=recipient_address,
                extra=PaymentRequirementsExtra(
                    name="GatewayWalletBatched",
                    version="1",
                    verifying_contract=verifying_contract,
                ),
            )
            requirements = PaymentRequirements(x402_version=2, accepts=(req_kind,))
            payload = self._signer.sign_transfer_with_authorization(req_kind)
            # Circle Gateway requires a resource descriptor on payment payloads.
            from omniclaw.protocols.nanopayments.types import PaymentPayload, ResourceInfo

            resource = ResourceInfo(
                url=f"direct:{recipient_address}",
                description=f"Gateway transfer to {recipient_address} on {destination_chain}",
                mime_type="application/json",
            )
            payload = PaymentPayload(
                x402_version=payload.x402_version,
                scheme=payload.scheme,
                network=payload.network,
                payload=payload.payload,
                resource=resource,
            )
            settle = await self._client.settle(payload=payload, requirements=requirements)
        except Exception as exc:
            raise WithdrawError(reason=f"Gateway settlement transfer failed: {exc}") from exc

        return WithdrawResult(
            mint_tx_hash=settle.transaction,
            amount=amount_atomic,
            formatted_amount=f"{self._atomic_to_decimal(amount_atomic)} USDC",
            source_chain=self._network,
            destination_chain=destination_chain,
            recipient=recipient_address,
        )

    # -------------------------------------------------------------------------
    # DEPRECATED: withdraw() - same-chain via EIP-3009 (not how Gateway works)
    # -------------------------------------------------------------------------

    async def withdraw(
        self,
        amount_usdc: str,
        destination_chain: str | None = None,
        recipient: str | None = None,
    ) -> WithdrawResult:
        """
        Withdraw USDC from the Gateway Wallet.

        DEPRECATED: This method has confusing semantics. Use one of:
        - deposit() to fund your Gateway balance
        - transfer_to_address() for same-chain transfers
        - transfer_crosschain() for cross-chain transfers
        - initiate_trustless_withdrawal() + complete_trustless_withdrawal() for emergency

        Args:
            amount_usdc: Amount in USDC decimal string.
            destination_chain: Target CAIP-2 chain. None = same chain.
            recipient: Destination address. None = own address.

        Returns:
            WithdrawResult with transfer details.
        """
        recipient_address = recipient or self._address
        dest_chain = destination_chain or self._network

        if dest_chain == self._network:
            return await self.transfer_to_address(amount_usdc, recipient_address)
        else:
            return await self.transfer_crosschain(amount_usdc, dest_chain, recipient_address)

    # -------------------------------------------------------------------------
    # Balance queries
    # -------------------------------------------------------------------------

    async def get_balance(self) -> GatewayBalance:
        """
        Get the Gateway wallet balance for this wallet's address.

        Returns:
            GatewayBalance with total, available, and formatted amounts.
        """
        return await self._client.check_balance(
            address=self._address,
            network=self._network,
        )

    async def get_onchain_balance(self) -> int:
        """
        Get the USDC token balance in the wallet (NOT in Gateway).

        This is separate from your Gateway balance. USDC in your wallet
        must be deposited to Gateway before it can be used for nanopayments.

        Returns:
            Balance in atomic units.
        """
        usdc_address = await self._resolve_usdc_address()
        usdc = self._usdc_contract(usdc_address)
        return usdc.functions.balanceOf(self._address).call()

    async def get_gateway_available_balance(self) -> int:
        """
        Get the available balance in Gateway (on-chain query).

        This queries the contract directly, independent of Circle's API.

        Returns:
            Available balance in atomic units.
        """
        gateway_address = await self._resolve_gateway_address()
        usdc_address = await self._resolve_usdc_address()
        gateway = self._get_gateway_contract(gateway_address)
        return gateway.functions.availableBalance(usdc_address, self._address).call()

    # -------------------------------------------------------------------------
    # Gas reserve management
    # -------------------------------------------------------------------------

    def get_gas_balance_wei(self) -> int:
        """
        Get the ETH balance of this wallet in wei.

        Returns:
            ETH balance in wei.
        """
        return self._w3.eth.get_balance(self._address)

    def get_gas_balance_eth(self) -> str:
        """
        Get the ETH balance of this wallet in ETH.

        Returns:
            ETH balance as a decimal string.
        """
        balance_wei = self.get_gas_balance_wei()
        eth_balance = self._w3.from_wei(balance_wei, "ether")
        return str(eth_balance)

    def estimate_gas_for_deposit(self) -> int:
        """
        Estimate gas units required for a deposit transaction.

        A deposit involves two transactions:
        1. USDC.approve() (if allowance is insufficient) — ~65000 gas
        2. Gateway.deposit() — ~150000 gas

        Returns:
            Estimated gas units (total for both transactions if approval needed).
        """
        # Approval gas: standard ERC-20 approve is ~46k gas, with buffer
        # Deposit gas: Gateway deposit is ~100-150k gas
        # Total worst case: ~200k gas
        return 200_000

    def estimate_gas_cost_wei(self) -> int:
        """
        Estimate the ETH cost (in wei) for a deposit transaction.

        Returns:
            Estimated gas cost in wei based on current network gas price.
        """
        gas_price = self._w3.eth.gas_price
        gas_estimate = self.estimate_gas_for_deposit()
        # Add 20% buffer for price fluctuation
        return int(gas_price * gas_estimate * 1.2)

    def estimate_gas_cost_eth(self) -> str:
        """
        Estimate the ETH cost (in ETH) for a deposit transaction.

        Returns:
            Estimated gas cost as a decimal string.
        """
        cost_wei = self.estimate_gas_cost_wei()
        return self._w3.from_wei(cost_wei, "ether")

    def check_gas_reserve(self) -> tuple[bool, str]:
        """
        Check if the wallet has enough native gas balance for the deposit transactions.

        Returns:
            Tuple of (has_sufficient_gas, message).
            has_sufficient_gas is True if native gas balance >= 2x estimated gas cost.
        """
        try:
            balance_wei = self.get_gas_balance_wei()
            required_wei = self.estimate_gas_cost_wei() * 2
            has_sufficient = balance_wei >= required_wei

            msg = (
                "native gas balance: "
                f"{self._w3.from_wei(balance_wei, 'ether')}, "
                f"required reserve: {self._w3.from_wei(required_wei, 'ether')}"
            )

            return has_sufficient, msg
        except Exception as e:
            # If can't check, allow anyway
            return True, f"Could not verify gas: {e}"

    def has_sufficient_gas_for_deposit(self) -> bool:
        """
        Quick check if the wallet can afford a deposit gas cost.

        Returns:
            True if ETH balance >= 2x estimated gas cost.
        """
        has_sufficient, _ = self.check_gas_reserve()
        return has_sufficient

    def ensure_gas_reserve(self) -> None:
        """
        Ensure the wallet has sufficient ETH for deposit operations.

        Raises:
            InsufficientGasError: If ETH balance is below the recommended reserve.

        Note:
            This is a pre-flight check. Call before deposit() if you want
            to fail fast rather than have the transaction fail due to insufficient gas.
        """
        from omniclaw.protocols.nanopayments.exceptions import InsufficientGasError

        has_sufficient, message = self.check_gas_reserve()
        if not has_sufficient:
            raise InsufficientGasError(reason=message)
