"""
Circle SDK client wrapper for developer-controlled wallets.

This module provides a clean interface to Circle's Python SDK for
wallet and transaction operations.
"""

from __future__ import annotations

import uuid
from typing import Any

from circle.web3 import developer_controlled_wallets, utils

from omniclaw.core.config import Config
from omniclaw.core.exceptions import (
    ConfigurationError,
    NetworkError,
    WalletError,
)
from omniclaw.core.types import (
    AccountType,
    Balance,
    FeeLevel,
    Network,
    TransactionInfo,
    WalletInfo,
    WalletSetInfo,
)


class CircleClient:
    """Wrapper around Circle's Python SDK for wallet and transaction operations."""

    def __init__(self, config: Config) -> None:
        self._config = config

        try:
            # Initialize the Circle SDK client
            self._client = utils.init_developer_controlled_wallets_client(
                api_key=config.circle_api_key,
                entity_secret=config.entity_secret,
            )
        except Exception as e:
            raise ConfigurationError(
                f"Failed to initialize Circle SDK client: {e}",
                details={"error": str(e)},
            ) from e

        # Initialize API instances
        self._wallet_sets_api = developer_controlled_wallets.WalletSetsApi(self._client)
        self._wallets_api = developer_controlled_wallets.WalletsApi(self._client)
        self._transactions_api = developer_controlled_wallets.TransactionsApi(self._client)

    # ==================== Wallet Set Operations ====================

    def list_wallet_sets(self) -> list[WalletSetInfo]:
        """List all wallet sets."""
        try:
            response = self._wallet_sets_api.get_wallet_sets()
            wallet_sets = []

            for ws in response.data.wallet_sets:
                ws_data = ws.to_dict()
                wallet_sets.append(WalletSetInfo.from_api_response(ws_data))

            return wallet_sets

        except developer_controlled_wallets.ApiException as e:
            raise WalletError(
                f"Failed to list wallet sets: {e}",
                details={"api_error": str(e)},
            ) from e

    def _get_ciphertext(self) -> str:
        return utils.generate_entity_secret_ciphertext(
            api_key=self._config.circle_api_key,
            entity_secret_hex=self._config.entity_secret,
        )

    def get_wallet_set(self, wallet_set_id: str) -> WalletSetInfo:
        """Get a specific wallet set by ID."""
        try:
            response = self._wallet_sets_api.get_wallet_set(wallet_set_id)
            ws_data = response.data.wallet_set.actual_instance.to_dict()
            return WalletSetInfo.from_api_response(ws_data)

        except developer_controlled_wallets.ApiException as e:
            raise WalletError(
                f"Failed to get wallet set {wallet_set_id}: {e}",
                details={"api_error": str(e), "wallet_set_id": wallet_set_id},
            ) from e

    # ==================== Wallet Operations ====================

    def create_wallet_set(
        self,
        name: str = "OmniClaw Wallet Set",
    ) -> WalletSetInfo:
        """Create a new wallet set."""
        try:
            ciphertext = self._get_ciphertext()
            idempotency_key = str(uuid.uuid4())

            request = developer_controlled_wallets.CreateWalletSetRequest.from_dict(
                {
                    "name": name,
                    "idempotencyKey": idempotency_key,
                    "entitySecretCiphertext": ciphertext,
                }
            )
            response = self._wallet_sets_api.create_wallet_set(request)

            # Extract wallet set data from response
            wallet_set_data = response.data.wallet_set
            return WalletSetInfo.from_api_response(wallet_set_data.to_dict())

        except developer_controlled_wallets.ApiException as e:
            raise WalletError(
                f"Failed to create wallet set: {e}",
                details={"api_error": str(e), "name": name},
            ) from e
        except Exception as e:
            raise WalletError(
                f"Unexpected error creating wallet set: {e}",
                details={"error": str(e), "name": name},
            ) from e

    def create_wallets(
        self,
        wallet_set_id: str,
        blockchain: Network | str,
        count: int = 1,
        account_type: AccountType = AccountType.EOA,
    ) -> list[WalletInfo]:
        """Create new wallets within a wallet set."""
        if count < 1 or count > 20:
            raise WalletError(
                "Wallet count must be between 1 and 20",
                details={"count": count},
            )

        # Convert Network enum to string if needed
        blockchain_str = blockchain.value if isinstance(blockchain, Network) else blockchain

        try:
            ciphertext = self._get_ciphertext()
            idempotency_key = str(uuid.uuid4())

            request = developer_controlled_wallets.CreateWalletRequest.from_dict(
                {
                    "walletSetId": wallet_set_id,
                    "blockchains": [blockchain_str],
                    "count": count,
                    "accountType": account_type.value if hasattr(account_type, "value") else str(account_type),
                    "idempotencyKey": idempotency_key,
                    "entitySecretCiphertext": ciphertext,
                }
            )
            response = self._wallets_api.create_wallet(request)

            wallets = []
            for wallet in response.data.wallets:
                wallet_data = wallet.actual_instance.to_dict()
                wallets.append(WalletInfo.from_api_response(wallet_data))

            return wallets

        except developer_controlled_wallets.ApiException as e:
            raise WalletError(
                f"Failed to create wallets: {e}",
                details={
                    "api_error": str(e),
                    "wallet_set_id": wallet_set_id,
                    "blockchain": blockchain_str,
                    "count": count,
                },
            ) from e

    def get_wallet(self, wallet_id: str) -> WalletInfo:
        """Get a specific wallet by ID."""
        try:
            response = self._wallets_api.get_wallet(wallet_id)
            wallet_data = response.data.wallet.actual_instance.to_dict()
            return WalletInfo.from_api_response(wallet_data)

        except developer_controlled_wallets.ApiException as e:
            raise WalletError(
                f"Failed to get wallet {wallet_id}: {e}",
                wallet_id=wallet_id,
                details={"api_error": str(e)},
            ) from e

    def list_wallets(
        self,
        wallet_set_id: str | None = None,
        blockchain: Network | str | None = None,
    ) -> list[WalletInfo]:
        """List wallets, optionally filtered by wallet set or blockchain."""
        try:
            # Build query parameters
            kwargs: dict[str, Any] = {}
            if wallet_set_id:
                kwargs["wallet_set_id"] = wallet_set_id
            if blockchain:
                blockchain_str = blockchain.value if isinstance(blockchain, Network) else blockchain
                kwargs["blockchain"] = blockchain_str

            response = self._wallets_api.get_wallets(**kwargs)

            wallets = []
            for wallet in response.data.wallets:
                wallet_data = wallet.actual_instance.to_dict()
                wallets.append(WalletInfo.from_api_response(wallet_data))

            return wallets

        except developer_controlled_wallets.ApiException as e:
            raise WalletError(
                f"Failed to list wallets: {e}",
                details={"api_error": str(e), "wallet_set_id": wallet_set_id},
            ) from e

    # ==================== Balance Operations ====================

    def get_wallet_balances(self, wallet_id: str) -> list[Balance]:
        """Get token balances for a wallet."""
        try:
            response = self._wallets_api.list_wallet_balance(wallet_id)

            balances = []
            for tb in response.data.token_balances:
                # Balance is a direct Pydantic model, not wrapped in actual_instance
                balance_data = tb.to_dict()
                balances.append(Balance.from_api_response(balance_data))

            return balances

        except developer_controlled_wallets.ApiException as e:
            raise WalletError(
                f"Failed to get wallet balances: {e}",
                wallet_id=wallet_id,
                details={"api_error": str(e)},
            ) from e

    def get_usdc_balance(self, wallet_id: str) -> Balance | None:
        """Get USDC balance for a wallet."""
        balances = self.get_wallet_balances(wallet_id)

        for balance in balances:
            # Check for USDC on mainnet or USDC-TESTNET on testnets
            symbol = balance.token.symbol.upper()
            if symbol == "USDC" or symbol == "USDC-TESTNET":
                return balance

        return None

    # ==================== Transaction Operations ====================

    def create_transfer(
        self,
        wallet_id: str,
        token_id: str,
        destination_address: str,
        amount: str,
        fee_level: FeeLevel = FeeLevel.MEDIUM,
        idempotency_key: str | None = None,
    ) -> TransactionInfo:
        """Create a token transfer transaction."""
        try:
            # Generate idempotency key if not provided
            if not idempotency_key:
                idempotency_key = str(uuid.uuid4())

            ciphertext = self._get_ciphertext()

            # Use correct SDK request class for developer wallets
            request = (
                developer_controlled_wallets.CreateTransferTransactionForDeveloperRequest.from_dict(
                    {
                        "idempotencyKey": idempotency_key,
                        "entitySecretCiphertext": ciphertext,
                        "walletId": wallet_id,
                        "tokenId": token_id,
                        "destinationAddress": destination_address,
                        "amounts": [amount],
                        "feeLevel": fee_level.value,  # Fee level at top level, not nested
                    }
                )
            )
            # Use correct API method for developer wallets
            response = self._transactions_api.create_developer_transaction_transfer(request)

            tx_data = response.data.to_dict()
            return TransactionInfo.from_api_response(tx_data)

        except developer_controlled_wallets.ApiException as e:
            raise WalletError(
                f"Failed to create transfer: {e}",
                wallet_id=wallet_id,
                details={
                    "api_error": str(e),
                    "destination": destination_address,
                    "amount": amount,
                },
            ) from e

    def get_transaction(self, transaction_id: str) -> TransactionInfo:
        """Get transaction status by ID."""
        try:
            response = self._transactions_api.get_transaction(transaction_id)
            tx_data = response.data.transaction.to_dict()
            return TransactionInfo.from_api_response(tx_data)

        except developer_controlled_wallets.ApiException as e:
            raise NetworkError(
                f"Failed to get transaction {transaction_id}: {e}",
                details={"api_error": str(e), "transaction_id": transaction_id},
            ) from e

    def list_transactions(
        self,
        wallet_id: str | None = None,
        blockchain: Network | str | None = None,
    ) -> list[TransactionInfo]:
        """List transactions, optionally filtered."""
        try:
            kwargs: dict[str, Any] = {}
            if wallet_id:
                kwargs["wallet_ids"] = wallet_id
            if blockchain:
                blockchain_str = blockchain.value if isinstance(blockchain, Network) else blockchain
                kwargs["blockchain"] = blockchain_str

            response = self._transactions_api.list_transactions(**kwargs)

            transactions = []
            for tx in response.data.transactions:
                tx_data = tx.to_dict()
                transactions.append(TransactionInfo.from_api_response(tx_data))

            return transactions

        except developer_controlled_wallets.ApiException as e:
            raise NetworkError(
                f"Failed to list transactions: {e}",
                details={"api_error": str(e)},
            ) from e

    # ==================== Utility Methods ====================

    def find_usdc_token_id(self, wallet_id: str) -> str | None:
        """Find the USDC token ID for a wallet's blockchain."""
        balance = self.get_usdc_balance(wallet_id)
        return balance.token.id if balance else None

    def create_contract_execution(
        self,
        wallet_id: str,
        contract_address: str,
        abi_function_signature: str,
        abi_parameters: list[str],
        fee_level: FeeLevel = FeeLevel.MEDIUM,
        idempotency_key: str | None = None,
    ) -> TransactionInfo:
        """
        Execute a smart contract function.

        This enables CCTP by calling TokenMessenger.depositForBurn().

        Args:
            wallet_id: Source wallet ID
            contract_address: Contract to call (e.g., TokenMessenger)
            abi_function_signature: Function signature (e.g., "depositForBurn(uint256,uint32,bytes32,address)")
            abi_parameters: Function parameters as strings
            fee_level: Gas fee level
            idempotency_key: Optional idempotency key

        Returns:
            TransactionInfo for the contract call
        """
        try:
            if not idempotency_key:
                idempotency_key = str(uuid.uuid4())

            ciphertext = self._get_ciphertext()

            request = (
                developer_controlled_wallets.CreateContractExecutionTransactionForDeveloperRequest.from_dict(
                    {
                        "idempotencyKey": idempotency_key,
                        "entitySecretCiphertext": ciphertext,
                        "walletId": wallet_id,
                        "contractAddress": contract_address,
                        "abiFunctionSignature": abi_function_signature,
                        "abiParameters": abi_parameters,
                        "feeLevel": fee_level.value,
                    }
                )
            )
            response = self._transactions_api.create_developer_transaction_contract_execution(
                request
            )

            tx_data = response.data.to_dict()
            return TransactionInfo.from_api_response(tx_data)

        except developer_controlled_wallets.ApiException as e:
            raise WalletError(
                f"Failed to execute contract: {e}",
                wallet_id=wallet_id,
                details={
                    "api_error": str(e),
                    "contract": contract_address,
                    "function": abi_function_signature,
                },
            ) from e

