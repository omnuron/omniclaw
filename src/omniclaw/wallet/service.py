"""
WalletService - High-level wallet management for AI agents.

This service provides a simplified interface for wallet operations,
abstracting away Circle API complexity for easy agent integration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

from omniclaw.core.circle_client import CircleClient
from omniclaw.core.config import Config
from omniclaw.core.exceptions import (
    InsufficientBalanceError,
    WalletError,
)
from omniclaw.core.types import (
    AccountType,
    Balance,
    FeeLevel,
    Network,
    TransactionInfo,
    TransactionState,
    WalletInfo,
    WalletSetInfo,
)


@dataclass
class TransferResult:
    """Result of a wallet transfer operation."""

    success: bool
    transaction: TransactionInfo | None = None
    tx_hash: str | None = None
    error: str | None = None

    @property
    def is_pending(self) -> bool:
        """Check if transfer is still pending."""
        if not self.transaction:
            return False
        return not self.transaction.is_terminal()


class WalletService:
    """
    High-level service for wallet management.

    Provides a simple interface for AI agents to:
    - Create and manage wallet sets
    - Create and list wallets
    - Check balances
    - Transfer USDC between wallets
    """

    def __init__(
        self,
        config: Config,
        circle_client: CircleClient | None = None,
    ) -> None:
        """
        Initialize WalletService.

        Args:
            config: SDK configuration
            circle_client: Optional pre-configured Circle client
        """
        self._config = config
        self._circle = circle_client or CircleClient(config)

        # Cache for wallet lookups
        self._wallet_cache: dict[str, WalletInfo] = {}

    # ==================== Wallet Set Operations ====================

    def create_wallet_set(self, name: str) -> WalletSetInfo:
        """
        Create a new wallet set to contain wallets.

        Args:
            name: Human-readable name for the wallet set

        Returns:
            Created wallet set info
        """
        return self._circle.create_wallet_set(name)

    def list_wallet_sets(self) -> list[WalletSetInfo]:
        """
        List all wallet sets.

        Returns:
            List of wallet sets
        """
        return self._circle.list_wallet_sets()

    def get_wallet_set(self, wallet_set_id: str) -> WalletSetInfo:
        """
        Get a wallet set by ID.

        Args:
            wallet_set_id: Wallet set ID

        Returns:
            Wallet set info
        """
        return self._circle.get_wallet_set(wallet_set_id)

    # ==================== Wallet Operations ====================

    def create_wallet(
        self,
        wallet_set_id: str,
        blockchain: Network | str | None = None,
        account_type: AccountType = AccountType.EOA,
    ) -> WalletInfo:
        """
        Create a new wallet in a wallet set.

        Args:
            wallet_set_id: Wallet set to create wallet in
            blockchain: Blockchain network (defaults to config network)
            account_type: Account type (SCA for smart contract, EOA for native)

        Returns:
            Created wallet info
        """
        network = blockchain or self._config.network

        wallets = self._circle.create_wallets(
            wallet_set_id=wallet_set_id,
            blockchain=network,
            count=1,
            account_type=account_type,
        )

        if not wallets:
            raise WalletError("No wallets created")

        wallet = wallets[0]
        self._wallet_cache[wallet.id] = wallet

        return wallet

    def create_wallets(
        self,
        wallet_set_id: str,
        count: int,
        blockchain: Network | str | None = None,
        account_type: AccountType = AccountType.EOA,
    ) -> list[WalletInfo]:
        """
        Create multiple wallets in a wallet set.

        Args:
            wallet_set_id: Wallet set to create wallets in
            count: Number of wallets to create (1-20)
            blockchain: Blockchain network (defaults to config network)
            account_type: Account type

        Returns:
            List of created wallets
        """
        network = blockchain or self._config.network

        wallets = self._circle.create_wallets(
            wallet_set_id=wallet_set_id,
            blockchain=network,
            count=count,
            account_type=account_type,
        )

        for wallet in wallets:
            self._wallet_cache[wallet.id] = wallet

        return wallets

    def create_agent_wallet(
        self,
        agent_name: str,
        blockchain: Network | str | None = None,
        count: int = 1,
    ) -> tuple[WalletSetInfo, WalletInfo | list[WalletInfo]]:
        """
        Create wallet(s) for an AI agent.

        Uses "agent-{name}" as wallet set name.
        If wallet set already exists, reuses it.

        Args:
            agent_name: Unique agent name (used as wallet set name)
            blockchain: Blockchain network (defaults to config network)
            count: Number of wallets to create (default: 1)

        Returns:
            Tuple of (wallet_set, wallet_or_list_of_wallets)

        Example:
            >>> # Create single wallet
            >>> set, wallet = service.create_agent_wallet("bot-1")
            >>>
            >>> # Create 5 wallets for swarm
            >>> set, wallets = service.create_agent_wallet("swarm-1", count=5)
        """
        target_name = f"agent-{agent_name}"

        # Check if wallet set exists
        # Note: Optimization would be to cache this or use a find method
        # But list_wallet_sets is typically fast enough for setup
        existing_sets = self.list_wallet_sets()
        wallet_set = next((s for s in existing_sets if s.name == target_name), None)

        if not wallet_set:
            wallet_set = self.create_wallet_set(name=target_name)

        # Create wallet(s)
        if count == 1:
            wallet = self.create_wallet(wallet_set_id=wallet_set.id, blockchain=blockchain)
            return wallet_set, wallet
        else:
            wallets = self.create_wallets(
                wallet_set_id=wallet_set.id, count=count, blockchain=blockchain
            )
            return wallet_set, wallets

    def create_user_wallet(
        self,
        user_id: str,
        blockchain: Network | str | None = None,
        count: int = 1,
    ) -> tuple[WalletSetInfo, WalletInfo | list[WalletInfo]]:
        """
        Create wallet(s) for an end user.

        Uses "user-{id}" as wallet set name.
        If wallet set already exists, reuses it.

        Args:
            user_id: Unique user identifier
            blockchain: Blockchain network
            count: Number of wallets to create

        Returns:
            Tuple of (wallet_set, wallet_or_list_of_wallets)
        """
        target_name = f"user-{user_id}"

        existing_sets = self.list_wallet_sets()
        wallet_set = next((s for s in existing_sets if s.name == target_name), None)

        if not wallet_set:
            wallet_set = self.create_wallet_set(name=target_name)

        if count == 1:
            wallet = self.create_wallet(wallet_set_id=wallet_set.id, blockchain=blockchain)
            return wallet_set, wallet
        else:
            wallets = self.create_wallets(
                wallet_set_id=wallet_set.id, count=count, blockchain=blockchain
            )
            return wallet_set, wallets

    def get_wallet(self, wallet_id: str) -> WalletInfo:
        """
        Get a wallet by ID.

        Args:
            wallet_id: Wallet ID

        Returns:
            Wallet info
        """
        if wallet_id in self._wallet_cache:
            return self._wallet_cache[wallet_id]

        wallet = self._circle.get_wallet(wallet_id)
        self._wallet_cache[wallet_id] = wallet

        return wallet

    def list_transactions(
        self,
        wallet_id: str | None = None,
        blockchain: Network | str | None = None,
    ) -> list[TransactionInfo]:
        """
        List transactions with optional filtering.

        Args:
            wallet_id: Filter by wallet ID
            blockchain: Filter by blockchain

        Returns:
            List of transactions
        """
        return self._circle.list_transactions(wallet_id, blockchain)

    def list_wallets(
        self,
        wallet_set_id: str | None = None,
        blockchain: Network | str | None = None,
    ) -> list[WalletInfo]:
        """
        List wallets with optional filtering.

        Args:
            wallet_set_id: Filter by wallet set
            blockchain: Filter by blockchain

        Returns:
            List of wallets
        """
        return self._circle.list_wallets(wallet_set_id, blockchain)

    def get_default_wallet(self) -> WalletInfo:
        """
        Get the default wallet from config.

        Returns:
            Default wallet info

        Raises:
            WalletError: If no default wallet configured
        """
        if not self._config.default_wallet_id:
            raise WalletError(
                "No default wallet configured. "
                "Set OMNICLAW_DEFAULT_WALLET or pass wallet_id explicitly."
            )

        return self.get_wallet(self._config.default_wallet_id)

    # ==================== Balance Operations ====================

    def get_balances(self, wallet_id: str) -> list[Balance]:
        """
        Get all token balances for a wallet.

        Args:
            wallet_id: Wallet ID

        Returns:
            List of token balances
        """
        return self._circle.get_wallet_balances(wallet_id)

    def get_usdc_balance(self, wallet_id: str) -> Balance:
        """
        Get USDC balance for a wallet.

        Args:
            wallet_id: Wallet ID

        Returns:
            USDC balance

        Raises:
            WalletError: If wallet has no USDC token
        """
        balance = self._circle.get_usdc_balance(wallet_id)

        if balance is None:
            raise WalletError(
                "Wallet has no USDC balance. The wallet may not have received any USDC yet.",
                wallet_id=wallet_id,
            )

        return balance

    def get_usdc_balance_amount(self, wallet_id: str) -> Decimal:
        """
        Get USDC balance amount as Decimal.

        Convenience method that returns just the amount.
        Returns 0 if wallet has no USDC.

        Args:
            wallet_id: Wallet ID

        Returns:
            USDC balance amount
        """
        try:
            balance = self.get_usdc_balance(wallet_id)
            return balance.amount
        except WalletError:
            return Decimal("0")

    def has_sufficient_balance(
        self,
        wallet_id: str,
        required_amount: Decimal,
    ) -> bool:
        """
        Check if wallet has sufficient USDC balance.

        Args:
            wallet_id: Wallet ID
            required_amount: Amount needed

        Returns:
            True if balance is sufficient
        """
        balance = self.get_usdc_balance_amount(wallet_id)
        return balance >= required_amount

    def ensure_sufficient_balance(
        self,
        wallet_id: str,
        required_amount: Decimal,
    ) -> Balance:
        """
        Ensure wallet has sufficient balance, raise if not.

        Args:
            wallet_id: Wallet ID
            required_amount: Amount needed

        Returns:
            Current balance

        Raises:
            InsufficientBalanceError: If balance is insufficient
        """
        try:
            balance = self.get_usdc_balance(wallet_id)
        except WalletError:
            raise InsufficientBalanceError(
                "Wallet has no USDC balance",
                current_balance=Decimal("0"),
                required_amount=required_amount,
                wallet_id=wallet_id,
            ) from None

        if balance.amount < required_amount:
            raise InsufficientBalanceError(
                "Insufficient USDC balance",
                current_balance=balance.amount,
                required_amount=required_amount,
                wallet_id=wallet_id,
            )

        return balance

    # ==================== Transfer Operations ====================

    def transfer(
        self,
        wallet_id: str,
        destination_address: str,
        amount: Decimal | str,
        fee_level: FeeLevel = FeeLevel.MEDIUM,
        check_balance: bool = True,
        wait_for_completion: bool = False,
        timeout_seconds: float | None = None,
        idempotency_key: str | None = None,
    ) -> TransferResult:
        """
        Transfer USDC from wallet to another address.

        Args:
            wallet_id: Source wallet ID
            destination_address: Destination wallet address
            amount: Amount to transfer
            fee_level: Gas fee level
            check_balance: Whether to verify balance before transfer
            wait_for_completion: Whether to wait for tx confirmation
            timeout_seconds: Max time to wait (uses config default if None)
            idempotency_key: Unique key to prevent duplicate transfers

        Returns:
            Transfer result
        """
        amount_decimal = Decimal(str(amount))
        amount_str = str(amount_decimal)

        # Check balance if requested
        if check_balance:
            self.ensure_sufficient_balance(wallet_id, amount_decimal)

        # Get USDC token ID
        usdc_token_id = self._circle.find_usdc_token_id(wallet_id)

        if not usdc_token_id:
            return TransferResult(
                success=False,
                error="Cannot find USDC token ID. Wallet may not have USDC.",
            )

        # Create transfer
        try:
            tx = self._circle.create_transfer(
                wallet_id=wallet_id,
                token_id=usdc_token_id,
                destination_address=destination_address,
                amount=amount_str,
                fee_level=fee_level,
                idempotency_key=idempotency_key,
            )
        except Exception as e:
            return TransferResult(
                success=False,
                error=str(e),
            )

        # Optionally wait for completion
        if wait_for_completion:
            timeout = timeout_seconds or self._config.transaction_poll_timeout
            tx = self._wait_for_transaction(tx.id, timeout)

        return TransferResult(
            success=tx.is_successful() if tx.is_terminal() else True,
            transaction=tx,
            tx_hash=tx.tx_hash,
            error=tx.error_reason if tx.state == TransactionState.FAILED else None,
        )

    def _wait_for_transaction(
        self,
        transaction_id: str,
        timeout_seconds: float,
    ) -> TransactionInfo:
        """
        Poll for transaction completion.

        Args:
            transaction_id: Transaction ID to poll
            timeout_seconds: Maximum wait time

        Returns:
            Final transaction info
        """
        start_time = time.time()
        poll_interval = self._config.transaction_poll_interval

        while True:
            tx = self._circle.get_transaction(transaction_id)

            if tx.is_terminal():
                return tx

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                return tx

            time.sleep(poll_interval)

    # ==================== Utility Methods ====================

    def get_or_create_default_wallet_set(
        self,
        name: str = "OmniClaw Default",
    ) -> WalletSetInfo:
        """
        Get existing wallet set by name or create new one.

        Args:
            name: Wallet set name

        Returns:
            Wallet set info
        """
        # Try to find existing
        wallet_sets = self.list_wallet_sets()
        for ws in wallet_sets:
            if ws.name == name:
                return ws

        # Create new
        return self.create_wallet_set(name)

    def setup_agent_wallet(
        self,
        agent_name: str = "AI Agent",
        blockchain: Network | str | None = None,
    ) -> tuple[WalletSetInfo, WalletInfo]:
        """
        Convenience method to set up a wallet for an AI agent.

        Creates a wallet set and wallet in one call.

        Args:
            agent_name: Name for the wallet set
            blockchain: Blockchain network

        Returns:
            Tuple of (wallet_set, wallet)
        """
        wallet_set = self.create_wallet_set(agent_name)
        wallet = self.create_wallet(
            wallet_set_id=wallet_set.id,
            blockchain=blockchain,
        )

        return wallet_set, wallet

    def setup_user_wallet(
        self,
        user_id: str | int,
        wallet_set_name: str = "User Wallets",
        blockchain: Network | str | None = None,
    ) -> tuple[WalletSetInfo, WalletInfo]:
        """
        Set up a wallet for an end-user.

        Creates a shared wallet set for users (if not exists) and creates
        a wallet for the specific user. The user_id is used to identify
        the wallet internally.

        Args:
            user_id: User identifier (will be converted to string)
            wallet_set_name: Name for the shared user wallet set
            blockchain: Blockchain network

        Returns:
            Tuple of (wallet_set, wallet)

        Example:
            >>> # For a database user with ID 12345
            >>> wallet_set, wallet = service.setup_user_wallet(user_id=12345)
            >>>
            >>> # For a UUID user
            >>> wallet_set, wallet = service.setup_user_wallet(user_id="550e8400-e29b-41d4-a716-446655440000")
        """
        # Convert user_id to string
        user_id_str = str(user_id)

        # Get or create shared wallet set for users
        wallet_set = self.get_or_create_default_wallet_set(wallet_set_name)

        # Create wallet for this user
        wallet = self.create_wallet(
            wallet_set_id=wallet_set.id,
            blockchain=blockchain,
        )

        # Cache with user_id as key for easy lookup
        self._wallet_cache[f"user:{user_id_str}"] = wallet

        return wallet_set, wallet

    def get_user_wallet(self, user_id: str | int) -> WalletInfo | None:
        """
        Get a cached user wallet by user_id.

        Args:
            user_id: User identifier

        Returns:
            Wallet info if cached, None otherwise
        """
        return self._wallet_cache.get(f"user:{str(user_id)}")

    def clear_cache(self) -> None:
        """Clear the wallet cache."""
        self._wallet_cache.clear()
