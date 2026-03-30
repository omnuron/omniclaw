"""OmniClawClient - Main SDK entry point."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from omniclaw.protocols.nanopayments.client import NanopaymentClient

from omniclaw.core.config import Config
from omniclaw.core.exceptions import (
    ConfigurationError,
    InsufficientBalanceError,
    PaymentError,
    ValidationError,
)
from omniclaw.core.idempotency import derive_idempotency_key
from omniclaw.core.state_machine import is_irreversible_success_status
from omniclaw.core.types import (
    AccountType,
    AmountType,
    BatchPaymentResult,
    FeeLevel,
    Network,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentMethod,
    PaymentRequest,
    PaymentResult,
    PaymentStatus,
    PaymentStrategy,
    SimulationResult,
    TransactionInfo,
    WalletInfo,
    WalletSetInfo,
)
from omniclaw.guards.base import PaymentContext
from omniclaw.guards.manager import GuardManager
from omniclaw.identity.types import TrustCheckResult, TrustPolicy, TrustVerdict
from omniclaw.intents.intent_facade import PaymentIntentFacade
from omniclaw.intents.reservation import ReservationService
from omniclaw.intents.service import PaymentIntentService
from omniclaw.ledger import Ledger, LedgerEntry, LedgerEntryStatus
from omniclaw.ledger.lock import FundLockService
from omniclaw.payment.batch import BatchProcessor
from omniclaw.payment.router import PaymentRouter
from omniclaw.protocols.gateway import GatewayAdapter
from omniclaw.protocols.nanopayments import (
    DepositResult,
    GatewayBalance,
    GatewayMiddleware,
    NanoKeyVault,
    NanopaymentAdapter,
    NanopaymentClient,
    NanopaymentNotInitializedError,
    NanopaymentProtocolAdapter,
    PaymentInfo,
    WithdrawResult,
)
from omniclaw.protocols.transfer import TransferAdapter
from omniclaw.protocols.x402 import X402Adapter
from omniclaw.resilience.circuit import CircuitBreaker, CircuitOpenError
from omniclaw.resilience.retry import execute_with_retry
from omniclaw.storage import get_storage
from omniclaw.trust.gate import TrustGate
from omniclaw.wallet.service import WalletService
from omniclaw.webhooks import WebhookParser

_current_payment_info: contextvars.ContextVar[PaymentInfo | None] = contextvars.ContextVar(
    "_current_payment_info", default=None
)


class OmniClaw:
    """
    Main client for OmniClaw SDK.

    Multi-tenant design: serves multiple agents/wallets with per-wallet guards.

    Initialization requires:
    - circle_api_key
    - entity_secret
    - network
    """

    def __init__(
        self,
        circle_api_key: str | None = None,
        entity_secret: str | None = None,
        network: Network = Network.ARC_TESTNET,
        log_level: int | str | None = None,
        trust_policy: TrustPolicy | str | None = None,
        rpc_url: str | None = None,
    ) -> None:
        """
        Initialize OmniClaw client.

        Args:
            circle_api_key: Circle API key (or from CIRCLE_API_KEY env)
            entity_secret: Entity secret for signing (or from ENTITY_SECRET env)
            network: Target blockchain network
            log_level: Logging level (default INFO). Set to logging.DEBUG for full traceability.
            trust_policy: Trust policy preset ("permissive"/"standard"/"strict") or TrustPolicy
            rpc_url: RPC endpoint for ERC-8004 on-chain reads (or set OMNICLAW_RPC_URL env var).
                     Supports comma-separated for fallback: "https://alchemy.com/KEY,https://infura.io/KEY"
        """
        # Determine log level
        if log_level is None:
            log_level = os.environ.get("OMNICLAW_LOG_LEVEL", "INFO")

        # Configure logging immediately
        from omniclaw.core.logging import configure_logging, get_logger

        configure_logging(level=log_level)
        self._logger = get_logger("client")
        network_value = network.value if hasattr(network, "value") else str(network)
        self._logger.info(f"Initializing OmniClaw SDK (Network: {network_value})")

        if not circle_api_key:
            circle_api_key = os.environ.get("CIRCLE_API_KEY")

        if not entity_secret:
            entity_secret = os.environ.get("ENTITY_SECRET")

        if circle_api_key and not entity_secret:
            from omniclaw.onboarding import load_managed_entity_secret

            managed_secret = load_managed_entity_secret(circle_api_key)
            if managed_secret:
                entity_secret = managed_secret
                os.environ.setdefault("ENTITY_SECRET", managed_secret)
                self._logger.info("Loaded entity secret from managed OmniClaw config.")

        # Auto-setup entity secret if missing but API key is present
        if circle_api_key and not entity_secret:
            self._logger.info("Entity secret not found. Running auto-setup...")
            try:
                from omniclaw.onboarding import auto_setup_entity_secret

                entity_secret = auto_setup_entity_secret(circle_api_key, logger=self._logger)
                self._logger.info("Entity secret auto-generated and registered.")
            except Exception as e:
                self._logger.error(f"Auto-setup failed: {e}")
                raise

        if not circle_api_key:
            self._logger.warning("CIRCLE_API_KEY not set. SDK will fail.")

        self._config = Config.from_env(
            circle_api_key=circle_api_key,
            entity_secret=entity_secret,
            network=network,
        )
        self._enforce_production_startup_requirements()

        if circle_api_key and entity_secret:
            try:
                from omniclaw.onboarding import store_managed_credentials

                store_managed_credentials(
                    circle_api_key,
                    entity_secret,
                    source="runtime_sync",
                )
            except OSError as exc:
                self._logger.warning(f"Failed to sync managed credentials store: {exc}")

        self._storage = get_storage()
        self._require_trust_gate = (
            os.environ.get("OMNICLAW_REQUIRE_TRUST_GATE", "false").lower() == "true"
        )
        self._ledger = Ledger(self._storage)
        self._fund_lock = FundLockService(self._storage)
        self._guard_manager = GuardManager(self._storage)
        self._wallet_service = WalletService(
            self._config,
        )

        # Initialize Nanopayments fields FIRST (before router registration uses them)
        self._nano_vault: NanoKeyVault | None = None
        self._nano_client: NanopaymentClient | None = None
        self._nano_adapter: NanopaymentAdapter | None = None
        self._nano_http: httpx.AsyncClient | None = None
        self._gateway_middleware: GatewayMiddleware | None = None
        self._gateway_default_address: str | None = None
        if self._config.nanopayments_enabled:
            self._init_nanopayments()

        self._router = PaymentRouter(self._config, self._wallet_service)
        self._router.register_adapter(TransferAdapter(self._config, self._wallet_service))
        self._router.register_adapter(X402Adapter(self._config, self._wallet_service))
        self._router.register_adapter(GatewayAdapter(self._config, self._wallet_service))

        # Register NanopaymentProtocolAdapter if nanopayments initialized successfully
        if self._nano_adapter is not None:
            nano_router_adapter = NanopaymentProtocolAdapter(
                nanopayment_adapter=self._nano_adapter,
                micro_threshold_usdc=self._config.nanopayments_micro_threshold,
            )
            self._router.register_adapter(nano_router_adapter)

        self._intent_service = PaymentIntentService(self._storage)
        self._reservation = ReservationService(self._storage)
        self._intent_facade = PaymentIntentFacade(self)
        self._batch_processor = BatchProcessor(self._router)
        self._webhook_parser = WebhookParser(
            verification_key=os.environ.get("OMNICLAW_WEBHOOK_VERIFICATION_KEY"),
        )

        # Initialize Trust Gate (ERC-8004)
        if isinstance(trust_policy, str):
            presets = {
                "permissive": TrustPolicy.permissive,
                "standard": TrustPolicy.standard,
                "strict": TrustPolicy.strict,
            }
            trust_policy = presets.get(trust_policy, TrustPolicy.permissive)()
        self._trust_gate = TrustGate(
            storage=self._storage,
            wallet_service=self._wallet_service,
            network=network,
            default_policy=trust_policy,
            rpc_url=rpc_url or self._config.rpc_url,
        )

        # Initialize Resilience
        self._circuit_breakers = {
            "default": CircuitBreaker("default", self._storage),
            "circle_api": CircuitBreaker("circle_api", self._storage),
        }

    def _enforce_production_startup_requirements(self) -> None:
        """Fail fast when production hardening requirements are missing."""
        env = str(self._config.env or "").lower()
        if env not in {"prod", "production", "mainnet"}:
            return

        required_env = [
            "OMNICLAW_SELLER_NONCE_REDIS_URL",
            "OMNICLAW_WEBHOOK_VERIFICATION_KEY",
            "OMNICLAW_WEBHOOK_DEDUP_DB_PATH",
        ]
        missing = [name for name in required_env if not os.environ.get(name)]
        if missing:
            raise ConfigurationError(
                "Missing required production environment variables: " + ", ".join(missing),
                details={"missing": missing, "env": env},
            )

        if not self._config.payment_strict_settlement:
            raise ConfigurationError(
                "OMNICLAW_STRICT_SETTLEMENT must be true in production environments",
                details={
                    "env": env,
                    "payment_strict_settlement": self._config.payment_strict_settlement,
                },
            )

    def _init_nanopayments(self) -> None:
        """Initialize nanopayments components (NanoKeyVault, NanopaymentClient, NanopaymentAdapter)."""
        if not self._config.nanopayments_enabled:
            return

        try:
            # Pre-import and warmup Circle SDK to resolve all lazy modules before
            # any parallel threads (asyncio.to_thread) try to import concurrently.
            # The Circle Python SDK uses a lazy module loader that breaks when
            # multiple threads trigger concurrent resolution of the same lazy module.
            try:
                from circle.web3 import developer_controlled_wallets, utils

                warmup_client = utils.init_developer_controlled_wallets_client(
                    api_key=self._config.circle_api_key,
                    entity_secret=self._config.entity_secret,
                )
                # Force resolution of all lazy submodules by instantiating API classes
                developer_controlled_wallets.WalletSetsApi(warmup_client)
                developer_controlled_wallets.WalletsApi(warmup_client)
                developer_controlled_wallets.TransactionsApi(warmup_client)
            except Exception as warmup_exc:
                self._logger.debug(f"Circle SDK warmup: {warmup_exc}")

            import httpx

            from omniclaw.protocols.nanopayments import (
                NanoKeyVault,
                NanopaymentAdapter,
                NanopaymentClient,
            )

            self._nano_http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._config.request_timeout, connect=10.0),
            )
            self._nano_client = NanopaymentClient(
                environment=self._config.nanopayments_environment,
                api_key=self._config.circle_api_key,
            )
            self._nano_vault = NanoKeyVault(
                entity_secret=self._config.entity_secret,
                storage_backend=self._storage,
                circle_api_key=self._config.circle_api_key,
                nanopayments_environment=self._config.nanopayments_environment,
                default_network=self._config.nanopayments_default_network,
            )
            self._nano_adapter = NanopaymentAdapter(
                vault=self._nano_vault,
                nanopayment_client=self._nano_client,
                http_client=self._nano_http,
                auto_topup_enabled=self._config.nanopayments_auto_topup,
                auto_topup_threshold=self._config.nanopayments_topup_threshold,
                auto_topup_amount=self._config.nanopayments_topup_amount,
                strict_settlement=self._config.payment_strict_settlement,
            )
            self._logger.info("Nanopayments initialized (EIP-3009 Circle Gateway)")
        except Exception as e:
            self._logger.warning(
                f"Nanopayments initialization failed: {e}. Disabling nanopayments."
            )
            self._nano_vault = None
            self._nano_client = None
            self._nano_adapter = None

    @property
    def config(self) -> Config:
        """Get SDK configuration."""
        return self._config

    @property
    def wallet(self) -> WalletService:
        """Get wallet service for wallet management."""
        return self._wallet_service

    @property
    def guards(self) -> GuardManager:
        """Get the guard manager for per-wallet/wallet-set guards."""
        return self._guard_manager

    @property
    def trust(self) -> TrustGate:
        """Get Trust Gate for ERC-8004 identity/reputation lookups."""
        return self._trust_gate

    @property
    def intent(self) -> PaymentIntentFacade:
        """Get intent facade for 2-phase commit."""
        return self._intent_facade

    @property
    def ledger(self) -> Ledger:
        """Get the transaction ledger."""
        return self._ledger

    @property
    def webhooks(self) -> WebhookParser:
        """Get webhook parser for verifying and parsing events."""
        return self._webhook_parser

    # -------------------------------------------------------------------------
    # Nanopayments (EIP-3009 Circle Gateway)
    # -------------------------------------------------------------------------

    @property
    def vault(self) -> NanoKeyVault | None:
        """
        Get the NanoKeyVault for managing EOA keys used in nanopayments.

        Returns None if nanopayments are not initialized.
        """
        return self._nano_vault

    @property
    def nanopayment_adapter(self) -> NanopaymentAdapter | None:
        """
        Get the NanopaymentAdapter for executing Circle Gateway nanopayments.

        Returns None if nanopayments are not initialized.
        """
        return self._nano_adapter

    async def gateway(
        self,
        seller_address: str | None = None,
        facilitator: str | None = None,
    ) -> GatewayMiddleware:
        """
        Get the GatewayMiddleware for protecting seller endpoints with x402 payments.

        Usage (FastAPI):
            from fastapi import Depends

            app = FastAPI()

            @app.get("/premium")
            async def premium(payment=Depends(omniclaw.gateway().require("$0.001"))):
                return {"data": "paid content", "paid_by": payment.payer}

        Args:
            seller_address: The address that receives payments.
                - For Circle Gateway: uses your wallet's nano address
                - For other facilitators: any EVM address you control
            facilitator: Choose which facilitator to use:
                - "circle" (default): Circle Gateway (needs wallet)
                - "coinbase": Coinbase CDP
                - "ordern": OrderN
                - "rbx": RBX
                - "thirdweb": Thirdweb

        Raises:
            NanopaymentNotInitializedError: If nanopayments are disabled and facilitator is Circle.
        """
        # Return cached middleware if available and no overrides specified
        if self._gateway_middleware is not None and seller_address is None and facilitator is None:
            return self._gateway_middleware

        # For Circle, we need nanopayments initialized
        if (facilitator is None or facilitator == "circle") and (
            not self._nano_client or not self._nano_vault
        ):
            raise NanopaymentNotInitializedError()

        # If no seller_address provided, try to get from wallet
        if not seller_address:
            if self._nano_vault:
                # Try to get from existing wallet
                with contextlib.suppress(Exception):
                    seller_address = await self._nano_vault.get_address(alias=None)
            if not seller_address:
                raise ValueError(
                    "seller_address is required. "
                    "Provide your payment address, or create a wallet first."
                )

        # Create facilitator if not Circle
        facilitator_client = None
        if facilitator and facilitator != "circle":
            from omniclaw.seller.facilitator_generic import create_facilitator

            facilitator_client = create_facilitator(
                provider=facilitator,
                environment=self._config.nanopayments_environment,
            )

        from omniclaw.protocols.nanopayments.middleware import GatewayMiddleware

        # For Circle, we need the nanopayment client
        if facilitator_client is None and self._nano_client:
            client_to_use = self._nano_client
        else:
            client_to_use = None

        self._gateway_middleware = GatewayMiddleware(
            seller_address=seller_address,
            nanopayment_client=client_to_use,
            facilitator=facilitator_client,
        )

        return self._gateway_middleware

    def sell(
        self,
        price: str,
        seller_address: str | None = None,
        facilitator: str | None = None,
    ) -> Any:
        """
        Decorator factory for marking a FastAPI route as a paid endpoint.

        Returns a FastAPI Depends() that gates the route with x402 payment.

        Usage:
            from fastapi import Depends

            @app.get("/premium")
            async def premium(payment=Depends(omniclaw.sell("$0.001"))):
                payment_info = omniclaw.current_payment()
                return {"data": "paid content", "paid_by": payment_info.payer}

        Args:
            price: Price in USD string (e.g. "$0.001", "1.00").
            seller_address: Your payment address.
                - For Circle Gateway: your wallet's nano address
                - For other facilitators: any EVM address you control
            facilitator: Choose which facilitator:
                - "circle" (default): Circle Gateway (needs wallet)
                - "coinbase": Coinbase CDP
                - "ordern": OrderN
                - "rbx": RBX
                - "thirdweb": Thirdweb

        Returns:
            A FastAPI Depends() callable.

        Examples:
            # Circle Gateway (needs wallet)
            client.sell("$0.01")
            client.sell("$0.01", seller_address="0xYourNanoAddress")

            # Other facilitators (just provide your address)
            client.sell("$0.01", facilitator="coinbase")
            client.sell("$0.01", seller_address="0xYourAddress", facilitator="coinbase")
        """
        from fastapi import Depends

        def base_dependency_factory():
            return self.gateway(
                seller_address=seller_address,
                facilitator=facilitator,
            )

        price_str = price

        async def wrapper() -> PaymentInfo:
            gateway_mw = await base_dependency_factory()
            base_dep = gateway_mw.require(price_str)
            payment_info: PaymentInfo = await base_dep()
            _current_payment_info.set(payment_info)
            return payment_info

        return Depends(wrapper)

    def current_payment(self) -> PaymentInfo:
        """
        Get the current payment within a @sell() decorated function.

        Returns the PaymentInfo for the in-progress payment, including
        the payer's address, amount, network, and settlement transaction.

        Usage:
            @agent.sell(price="$0.001")
            async def get_data():
                payment = agent.current_payment()
                return {"data": "...", "paid_by": payment.payer}

        Returns:
            PaymentInfo for the current request.

        Raises:
            ValueError: If called outside of a @sell() decorated function.
        """
        info: PaymentInfo | None = _current_payment_info.get()
        if info is None:
            raise ValueError("current_payment() called outside of a @sell() decorated function")
        return info

    # -------------------------------------------------------------------------
    # Key management (delegates to NanoKeyVault)
    # -------------------------------------------------------------------------

    async def add_key(self, alias: str, private_key: str) -> str:
        """
        Import an existing EOA private key into the NanoKeyVault.

        The key is encrypted and stored securely. Raw private keys are never
        exposed to agents — they receive only the alias string.

        Args:
            alias: Unique identifier for this key (e.g. "alice-nano").
            private_key: EOA private key hex (with or without 0x prefix).

        Returns:
            The EOA address derived from the key.

        Raises:
            DuplicateKeyAliasError: If a key with this alias already exists.
            InvalidPrivateKeyError: If the private key is invalid.
        """
        if not self._nano_vault:
            raise NanopaymentNotInitializedError()
        return await self._nano_vault.add_key(alias, private_key)

    async def generate_key(self, alias: str, network: str | None = None) -> str:
        """
        Generate a new EOA keypair and store it encrypted in the vault.

        The operator must fund the generated address with USDC before
        it can be used for nanopayments.

        Args:
            alias: Unique identifier for this key.
            network: CAIP-2 network for this key (e.g. 'eip155:5042002').
                     If None, uses the default network for the environment.

        Returns:
            The new EOA address.

        Raises:
            DuplicateKeyAliasError: If a key with this alias already exists.
        """
        if not self._nano_vault:
            raise NanopaymentNotInitializedError()
        return await self._nano_vault.generate_key(alias, network=network)

    async def set_default_key(self, alias: str) -> None:
        """
        Set the default nanopayment key for agents that don't specify one.

        Args:
            alias: The key alias to set as default.

        Raises:
            KeyNotFoundError: If no key with this alias exists.
        """
        if not self._nano_vault:
            raise NanopaymentNotInitializedError()
        await self._nano_vault.set_default_key(alias)

    async def list_keys(self) -> list[str]:
        """
        List all key aliases in the vault (safe for operator use).

        Returns:
            List of key aliases. Does NOT return the actual keys.
        """
        if not self._nano_vault:
            return []
        return await self._nano_vault.list_keys()

    # -------------------------------------------------------------------------
    # Gateway Wallet management (on-chain deposit/withdraw)
    # -------------------------------------------------------------------------

    async def deposit_to_gateway(
        self,
        wallet_id: str,
        amount_usdc: str,
        network: str | None = None,
    ) -> DepositResult:
        """
        Deposit USDC into the Circle Gateway Wallet for nanopayment use.

        This is the ONLY nanopayment operation that costs gas (on-chain).
        Once deposited, payments are gasless via EIP-3009 batched settlement.

        Args:
            wallet_id: The wallet ID to deposit from.
            amount_usdc: Amount in USDC decimal (e.g. "10.00").
            network: CAIP-2 network (e.g. 'eip155:5042002').
                     Defaults to config nanopayments_environment.

        Returns:
            DepositResult with approval_tx_hash and deposit_tx_hash.

        Raises:
            NanopaymentNotInitializedError: If nanopayments are disabled.
            KeyNotFoundError: If the key alias doesn't exist.
        """
        if not self._nano_vault or not self._nano_client:
            raise NanopaymentNotInitializedError()

        from omniclaw.protocols.nanopayments.wallet import GatewayWalletManager

        key_alias = f"wallet-{wallet_id}"
        raw_key = await self._nano_vault.get_raw_key(alias=key_alias)
        net = network or await self._nano_vault.get_network(alias=key_alias)
        manager = GatewayWalletManager(
            private_key=raw_key,
            network=net,
            rpc_url=self._config.rpc_url or "",
            nanopayment_client=self._nano_client,
        )
        return await manager.deposit(amount_usdc)

    async def withdraw_from_gateway(
        self,
        wallet_id: str,
        amount_usdc: str,
        destination_chain: str | None = None,
        recipient: str | None = None,
        network: str | None = None,
    ) -> WithdrawResult:
        """
        Withdraw USDC from the Circle Gateway Wallet.

        Same-chain: Instant via internal contract transfer.
        Cross-chain: Burns USDC on source chain, mints on destination via CCTP.

        Args:
            wallet_id: The wallet ID to withdraw from.
            amount_usdc: Amount in USDC decimal.
            destination_chain: Target CAIP-2 chain. None = same chain.
            recipient: Destination address. None = own address.
            network: CAIP-2 network. Defaults to testnet.

        Returns:
            WithdrawResult with mint_tx_hash and details.

        Raises:
            NanopaymentNotInitializedError: If nanopayments are disabled.
        """
        if not self._nano_vault or not self._nano_client:
            raise NanopaymentNotInitializedError()

        from omniclaw.protocols.nanopayments.wallet import GatewayWalletManager

        key_alias = f"wallet-{wallet_id}"
        raw_key = await self._nano_vault.get_raw_key(alias=key_alias)
        net = network or await self._nano_vault.get_network(alias=key_alias)
        manager = GatewayWalletManager(
            private_key=raw_key,
            network=net,
            rpc_url=self._config.rpc_url or "",
            nanopayment_client=self._nano_client,
        )
        return await manager.withdraw(
            amount_usdc=amount_usdc,
            destination_chain=destination_chain,
            recipient=recipient,
        )

    async def get_gateway_balance(
        self,
        wallet_id: str,
    ) -> GatewayBalance:
        """
        Get the Gateway wallet balance for a wallet.

        Args:
            wallet_id: The wallet ID to check gateway balance for.

        Returns:
            GatewayBalance with total, available, and formatted amounts.

        Raises:
            NanopaymentNotInitializedError: If nanopayments are disabled.
        """
        if not self._nano_vault:
            raise NanopaymentNotInitializedError()

        key_alias = f"wallet-{wallet_id}"
        return await self._nano_vault.get_balance(alias=key_alias)

    def configure_nanopayments(
        self,
        auto_topup_enabled: bool | None = None,
        auto_topup_threshold: str | None = None,
        auto_topup_amount: str | None = None,
        wallet_manager: Any = None,
    ) -> None:
        """
        Configure auto-topup for nanopayment gateway balance.

        Args:
            auto_topup_enabled: Enable/disable auto-topup.
            auto_topup_threshold: Balance threshold in USDC (e.g. "1.00").
            auto_topup_amount: Amount to deposit when auto-topup triggers.
            wallet_manager: GatewayWalletManager instance for auto-topup deposits.
                If provided, auto-topup will actually work.
        """
        if self._nano_adapter:
            self._nano_adapter.configure_auto_topup(
                enabled=auto_topup_enabled,
                threshold=auto_topup_threshold,
                amount=auto_topup_amount,
            )
            if wallet_manager is not None:
                self._nano_adapter.set_wallet_manager(wallet_manager)

    # -------------------------------------------------------------------------
    # Agent creation with nanopayment support
    # -------------------------------------------------------------------------

    async def create_agent(
        self,
        agent_name: str,
        blockchain: Network | str | None = None,
        apply_default_guards: bool = True,
        nanopayment_key_alias: str | bool | None = None,
    ) -> tuple[WalletSetInfo, WalletInfo]:
        """
        Create a wallet for an AI agent with optional nanopayment key.

        This is a convenience wrapper around create_agent_wallet that also
        optionally generates or assigns a NanoKeyVault key for the agent.

        Agents receive only the `nano_key_alias` string — raw private keys
        stay in the operator's vault and are never exposed to agents.

        Args:
            agent_name: Unique agent name (used as wallet set name).
            blockchain: Blockchain network (defaults to config network).
            apply_default_guards: Apply configured default guards to wallet.
            nanopayment_key_alias: NanoKeyVault alias for the agent.
                                   If None, no nanopayment key is created.
                                   If True, auto-generates "agent-{name}-nano".

        Returns:
            Tuple of (wallet_set, wallet_info).

        Raises:
            NanopaymentNotInitializedError: If nanopayment_key_alias is set
                but nanopayments are disabled.
            DuplicateKeyAliasError: If the generated key alias already exists.
        """
        # Create the wallet
        wallet_set, wallet = await self.create_agent_wallet(
            agent_name=agent_name,
            blockchain=blockchain,
            apply_default_guards=apply_default_guards,
        )

        # Optionally create a nanopayment key for this agent
        if nanopayment_key_alias is not None:
            if not self._nano_vault:
                raise NanopaymentNotInitializedError()

            # True → auto-generate alias
            if nanopayment_key_alias is True:
                key_alias = f"agent-{agent_name}-nano"
            else:
                key_alias = nanopayment_key_alias

            # Generate the key (operator funds the resulting address)
            address = await self._nano_vault.generate_key(key_alias)
            self._logger.info(
                f"Generated nanopayment key for agent '{agent_name}': "
                f"alias={key_alias}, address={address}"
            )

        return wallet_set, wallet

    async def __aenter__(self) -> OmniClaw:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit — clean up resources."""
        # Close Trust Gate (HTTP clients for metadata fetching)
        await self._trust_gate.close()
        # Close nanopayment HTTP client if it was created
        if self._nano_http:
            await self._nano_http.aclose()
        # Close any HTTP clients held by protocol adapters
        for adapter in self._router.get_adapters():
            client = getattr(adapter, "_http_client", None)
            if client and hasattr(client, "aclose"):
                await client.aclose()

    async def get_balance(self, wallet_id: str) -> Decimal:
        """
        Get USDC balance for a wallet.

        For more detailed balance info (available + reserved), use get_detailed_balance().

        Args:
            wallet_id: The wallet ID to check balance for.

        Returns:
            Available USDC balance as Decimal.
        """
        return self._wallet_service.get_usdc_balance_amount(wallet_id)

    async def get_detailed_balance(self, wallet_id: str) -> dict:
        """
        Get detailed USDC balance for a wallet including reserved amounts.

        Args:
            wallet_id: The wallet ID to check balance for.

        Returns:
            Dict with:
                - available: Decimal - spendable USDC
                - reserved: Decimal - reserved for payment intents
                - total: Decimal - total USDC (available + reserved)
        """
        available = self._wallet_service.get_usdc_balance_amount(wallet_id)

        reserved = Decimal("0")
        if self._reservation:
            reserved = await self._reservation.get_reserved_total(wallet_id)

        return {
            "available": available,
            "reserved": reserved,
            "total": available + reserved,
        }

    async def create_wallet(
        self,
        blockchain: Network | str | None = None,
        wallet_set_id: str | None = None,
        account_type: AccountType = AccountType.EOA,
        name: str | None = None,
    ) -> WalletInfo:
        """
        Create a new wallet.

        Args:
            blockchain: Blockchain network (default: config.network)
            wallet_set_id: ID of existing wallet set. If None, creates a new set using `name` or default.
            account_type: Wallet type (EOA or SCA)
            name: Name for new wallet set if creating one (default: "default-set")

        Returns:
            Created WalletInfo
        """
        if not wallet_set_id:
            # Create a new set automatically
            set_name = name or f"set-{uuid.uuid4().hex[:8]}"
            wallet_set = self._wallet_service.create_wallet_set(name=set_name)
            wallet_set_id = wallet_set.id

        return self._wallet_service.create_wallet(
            wallet_set_id=wallet_set_id,
            blockchain=blockchain,
            account_type=account_type,
        )

    async def create_agent_wallet(
        self,
        agent_name: str,
        blockchain: Network | str | None = None,
        apply_default_guards: bool = True,
    ) -> tuple[WalletSetInfo, WalletInfo]:
        """
        Create a wallet for an AI agent, optionally applying default SDK guards.

        Also creates a nanopayment key so the agent can use gateway operations.

        Args:
            agent_name: Unique agent name (used as wallet set name)
            blockchain: Blockchain network (defaults to config network)
            apply_default_guards: Apply configured default guards to wallet

        Returns:
            Tuple of (wallet_set, wallet_info)
        """
        # 10/10 RESILIENCE: setup_agent_wallet is SYNC and blocks.
        # Offload to a thread so asyncio.gather can work in parallel.
        # Use positional arguments for maximum compatibility across Python versions.
        wallet_set, wallet = await asyncio.to_thread(
            self._wallet_service.setup_agent_wallet,
            agent_name,
            blockchain,
        )

        if apply_default_guards:
            await self.apply_default_guards(wallet.id)

        # 10/10 RESILIENCE: Key generation can fail on slow RPCs (free Base nodes).
        # We retry with exponential backoff to ensure the agent is ready.
        if self._nano_vault:
            key_alias = f"wallet-{wallet.id}"
            max_retries = 5
            base_delay = 3

            for attempt in range(max_retries):
                try:
                    address = await self._nano_vault.generate_key(key_alias)
                    self._logger.info(
                        f"Generated nanopayment key for wallet '{wallet.id}': "
                        f"alias={key_alias}, address={address} (Attempt {attempt + 1})"
                    )
                    break
                except Exception as e:
                    error_msg = str(e).lower()
                    if "already exists" in error_msg:
                        self._logger.info(
                            f"Nanopayment key already exists for wallet '{wallet.id}': "
                            f"alias={key_alias}. Recovery successful."
                        )
                        break
                        
                    if attempt == max_retries - 1:
                        self._logger.warning(
                            f"Final attempt failed to create nanopayment key: {e}. Wallet will start in Degraded mode."
                        )
                    else:
                        delay = base_delay * (2**attempt)
                        self._logger.warning(
                            f"Nanopayment key generation failed (Attempt {attempt + 1}): {e}. Retrying in {delay}s..."
                        )
                        await asyncio.sleep(delay)

        return wallet_set, wallet

    async def apply_default_guards(self, wallet_id: str) -> None:
        """Apply default guards configured in SDK Config to a wallet."""
        c = self._config

        if c.daily_budget or c.hourly_budget:
            await self.add_budget_guard(
                wallet_id=wallet_id,
                daily_limit=c.daily_budget,
                hourly_limit=c.hourly_budget,
                name="default_budget",
            )

        if c.rate_limit_per_min:
            await self.add_rate_limit_guard(
                wallet_id=wallet_id, max_per_minute=c.rate_limit_per_min, name="default_rate_limit"
            )

        if c.tx_limit:
            await self.add_single_tx_guard(
                wallet_id=wallet_id, max_amount=c.tx_limit, name="default_single_tx"
            )

        if c.whitelisted_recipients:
            await self.add_recipient_guard(
                wallet_id=wallet_id,
                mode="whitelist",
                addresses=c.whitelisted_recipients,
                name="default_recipient_whitelist",
            )

        if c.confirm_always or c.confirm_threshold is not None:
            await self.add_confirm_guard(
                wallet_id=wallet_id,
                always_confirm=c.confirm_always,
                threshold=c.confirm_threshold,
                name="default_confirm",
            )

    async def create_wallet_set(self, name: str | None = None) -> WalletSetInfo:
        """Create a new wallet set."""
        return self._wallet_service.create_wallet_set(name)

    async def list_wallets(self, wallet_set_id: str | None = None) -> list[WalletInfo]:
        """List wallets (optional filter by set)."""
        return self._wallet_service.list_wallets(wallet_set_id)

    async def list_wallet_sets(self) -> list[WalletSetInfo]:
        """List available wallet sets."""
        return self._wallet_service.list_wallet_sets()

    async def get_wallet(self, wallet_id: str) -> WalletInfo:
        """Get details of a specific wallet."""
        return self._wallet_service.get_wallet(wallet_id)

    async def get_payment_address(self, wallet_id: str) -> str:
        """
        Get the payment address for a wallet.

        This is the address that should be funded with USDC to enable payments.

        Args:
            wallet_id: The wallet ID to get the payment address for.

        Returns:
            The Ethereum address (0x...) that can receive USDC.
        """
        wallet = await self.get_wallet(wallet_id)
        return wallet.address

    async def get_wallet_set(self, wallet_set_id: str) -> WalletSetInfo:
        """Get details of a specific wallet set."""
        return self._wallet_service.get_wallet_set(wallet_set_id)

    async def list_transactions(
        self, wallet_id: str | None = None, blockchain: Network | str | None = None
    ) -> list[TransactionInfo]:
        """List transactions for a wallet or globally."""
        return self._wallet_service.list_transactions(wallet_id, blockchain)

    async def pay(
        self,
        wallet_id: str,
        recipient: str,
        amount: AmountType,
        destination_chain: Network | str | None = None,
        wallet_set_id: str | None = None,
        purpose: str | None = None,
        idempotency_key: str | None = None,
        fee_level: FeeLevel = FeeLevel.MEDIUM,
        strategy: PaymentStrategy = PaymentStrategy.RETRY_THEN_FAIL,
        skip_guards: bool = False,
        check_trust: bool = False,
        consume_intent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        wait_for_completion: bool = False,
        timeout_seconds: float | None = None,
        validate_recipient: bool = True,
        **kwargs: Any,
    ) -> PaymentResult:
        """
        Execute a payment with automatic routing, guards, and resilience.

        Args:
            wallet_id: Source wallet ID (REQUIRED)
            recipient: Payment recipient (address or URL)
            amount: Amount to pay (USDC)
            destination_chain: Target blockchain for cross-chain (optional)
            wallet_set_id: Wallet set ID for hierarchical guards
            purpose: Human-readable purpose
            idempotency_key: Unique key for deduplication
            fee_level: Transaction fee level
            strategy: Reliability strategy (FAIL_FAST, RETRY_THEN_FAIL, QUEUE_BACKGROUND)
            skip_guards: Skip guard checks (dangerous!)
            check_trust: Enable/disable ERC-8004 Trust Gate check for this payment.
                         None (default) = auto (enabled if trust_gate is configured).
                         True = force enable. False = skip trust check.
            metadata: Additional metadata
            wait_for_completion: Wait for transaction confirmation
            timeout_seconds: Maximum wait time
            validate_recipient: Validate recipient address/URL format (default: True)
            **kwargs: Additional options

        Returns:
            PaymentResult with transaction details
        """
        if not wallet_id:
            raise ValidationError("wallet_id is required")

        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            raise ValidationError(f"Payment amount must be positive. Got: {amount_decimal}")

        if self._config.auto_reconcile_pending_settlements:
            try:
                await self.reconcile_pending_settlements(wallet_id=wallet_id, limit=20)
            except Exception as reconcile_exc:
                self._logger.warning(
                    "Auto reconcile pending settlements failed (wallet=%s): %s",
                    wallet_id,
                    reconcile_exc,
                )

        # Validate recipient format
        if validate_recipient:
            if not recipient:
                raise ValidationError("recipient is required")
            # EVM address validation (0x + 40 hex chars)
            if recipient.startswith("0x"):
                if not re.match(r"^0x[0-9a-fA-F]{40}$", recipient):
                    raise ValidationError(
                        f"Invalid EVM address: {recipient!r}. "
                        f"Must be '0x' followed by exactly 40 hex characters."
                    )
            # URL recipients (x402) must be valid HTTPS
            elif recipient.startswith("http") and not recipient.startswith("https://"):
                raise ValidationError(f"x402 recipient URL must use HTTPS. Got: {recipient!r}")

        if not idempotency_key:
            idempotency_key = derive_idempotency_key(
                "payment",
                wallet_id,
                recipient,
                str(amount_decimal),
                purpose,
                destination_chain.value
                if hasattr(destination_chain, "value")
                else destination_chain,
                kwargs.get("http_method", kwargs.get("method", "GET")),
                kwargs.get("request_json"),
                kwargs.get("request_body", kwargs.get("body")),
            )

        meta = metadata or {}
        meta["idempotency_key"] = idempotency_key
        meta["strategy"] = strategy.value

        if self._require_trust_gate and self._trust_gate and not self._trust_gate.is_configured:
            raise ConfigurationError(
                "OMNICLAW_REQUIRE_TRUST_GATE=true but Trust Gate is not configured. "
                "Set OMNICLAW_RPC_URL to a real RPC endpoint."
            )

        # ── Trust Gate Check (ERC-8004) ──────────────────────────────
        # check_trust=False (default) → skip trust check
        # check_trust=True → run trust check (requires OMNICLAW_RPC_URL)
        run_trust = check_trust and not skip_guards
        trust_result: TrustCheckResult | None = None
        if self._trust_gate and run_trust and not self._trust_gate.is_configured:
            raise ConfigurationError(
                "Trust Gate requires a real OMNICLAW_RPC_URL. "
                "Set OMNICLAW_RPC_URL before using trust verification."
            )
        if self._trust_gate and run_trust:
            trust_result = await self._trust_gate.evaluate(
                recipient_address=recipient,
                amount=amount_decimal,
                wallet_id=wallet_id,
            )
            meta["trust"] = trust_result.to_dict()

            if trust_result.verdict == TrustVerdict.BLOCKED:
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=amount_decimal,
                    recipient=recipient,
                    method=PaymentMethod.TRANSFER,
                    status=PaymentStatus.BLOCKED,
                    error=f"Trust Gate blocked: {trust_result.block_reason}",
                    metadata={"trust": trust_result.to_dict()},
                )
            elif trust_result.verdict == TrustVerdict.HELD:
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=amount_decimal,
                    recipient=recipient,
                    method=PaymentMethod.TRANSFER,
                    status=PaymentStatus.PENDING,
                    error=f"Trust Gate held for review: {trust_result.block_reason}",
                    metadata={"trust": trust_result.to_dict()},
                )

        context = PaymentContext(
            wallet_id=wallet_id,
            wallet_set_id=wallet_set_id,
            recipient=recipient,
            amount=amount_decimal,
            purpose=purpose,
            metadata=meta,
        )

        ledger_entry = LedgerEntry(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=amount_decimal,
            purpose=purpose,
            metadata=meta,
        )
        await self._ledger.record(ledger_entry)

        guards_chain = None
        reservation_tokens = []
        guards_passed: list[str] = []

        # Detect payment route early to know which balance to check
        try:
            detected_route = (
                self._router.detect_method(
                    recipient,
                    source_network=Network.from_string(
                        self._wallet_service.get_wallet(wallet_id).blockchain
                    ),
                    destination_chain=kwargs.get("destination_chain"),
                    amount=amount_decimal,
                )
                or PaymentMethod.TRANSFER
            )
        except Exception:
            detected_route = PaymentMethod.TRANSFER

        if not skip_guards:
            guards_chain = await self._guard_manager.get_guard_chain(
                wallet_id=wallet_id, wallet_set_id=wallet_set_id
            )
            try:
                # Reserve budget/limits first (atomic counters)
                reservation_tokens = await guards_chain.reserve(context)
                guards_passed = [g.name for g in guards_chain]
            except ValueError as e:
                await self._ledger.update_status(
                    ledger_entry.id,
                    LedgerEntryStatus.BLOCKED,
                    tx_hash=None,
                )
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=amount_decimal,
                    recipient=recipient,
                    method=PaymentMethod.TRANSFER,
                    status=PaymentStatus.BLOCKED,
                    error=f"Blocked by guard: {e}",
                    guards_passed=guards_passed,
                    metadata={"guard_reason": str(e)},
                )

        # Acquire Fund Lock (Mutex) to prevent double-spend race conditions
        lock_ttl_seconds = max(60, int(self._config.transaction_poll_timeout) + 30)
        lock_token = await self._fund_lock.acquire(
            wallet_id,
            amount_decimal,
            ttl=lock_ttl_seconds,
        )
        if not lock_token:
            # Could not acquire lock (busy)
            error_msg = "Wallet is busy (locked by another transaction). Please retry."
            if guards_chain and reservation_tokens:
                await guards_chain.release(reservation_tokens)

            await self._ledger.update_status(
                ledger_entry.id, LedgerEntryStatus.FAILED, metadata_updates={"error": error_msg}
            )
            raise PaymentError(error_msg)

        lock_heartbeat_stop = asyncio.Event()
        lock_lost_event = asyncio.Event()
        lock_heartbeat_task = asyncio.create_task(
            self._maintain_wallet_lock(
                wallet_id=wallet_id,
                lock_token=lock_token,
                ttl_seconds=lock_ttl_seconds,
                stop_event=lock_heartbeat_stop,
                lock_lost_event=lock_lost_event,
            )
        )
        execution_result: PaymentResult | None = None

        try:
            # If we are confirming an intent, release its reservation now that we hold the mutex
            if consume_intent_id:
                await self._reservation.release(consume_intent_id)

            # Get appropriate balance based on payment route
            # For X402/nanopayment routes → check Gateway balance
            # For Transfer/crosschain routes → check Circle wallet balance
            circle_balance = self._wallet_service.get_usdc_balance_amount(wallet_id)
            reserved_total = await self._reservation.get_reserved_total(wallet_id)

            # Check if this is a Gateway-based route
            route_uses_gateway = detected_route in (PaymentMethod.X402, PaymentMethod.NANOPAYMENT)

            if route_uses_gateway and self._nano_vault:
                try:
                    gateway_balance = await self._nano_vault.get_balance(
                        alias=f"wallet-{wallet_id}"
                    )
                    # Gateway balance is available for spending (no reservations concept)
                    available = gateway_balance.available
                    balance_source = f"Gateway: {available}"
                except Exception:
                    # Fall back to circle balance if gateway lookup fails
                    available = circle_balance - reserved_total
                    balance_source = f"Circle: {available}"
            else:
                available = circle_balance - reserved_total
                balance_source = f"Circle: {available}"
            if lock_lost_event.is_set():
                raise PaymentError("Wallet lock lease was lost before execution could start.")
            if amount_decimal > available:
                error_msg = f"Insufficient available balance ({balance_source}, Reserved: {reserved_total}, Required: {amount_decimal})"
                if guards_chain and reservation_tokens:
                    await guards_chain.release(reservation_tokens)
                await self._ledger.update_status(
                    ledger_entry.id, LedgerEntryStatus.FAILED, metadata_updates={"error": error_msg}
                )
                raise InsufficientBalanceError(
                    error_msg, current_balance=available, required_amount=amount_decimal
                )

            # Resilience Shell
            circuit = self._circuit_breakers.get("circle_api")  # Default to Circle API for now
            if not circuit:
                circuit = self._circuit_breakers["default"]

            # 1. Check Circuit
            if not await circuit.is_available():
                if strategy == PaymentStrategy.QUEUE_BACKGROUND:
                    # Queue it
                    return await self._queue_payment(
                        context, ledger_entry.id, guards_chain, reservation_tokens
                    )

                # Fail Fast / Retry logic implies fail if circuit open
                recovery_ts = (
                    await circuit.get_recovery_ts() if hasattr(circuit, "get_recovery_ts") else 0
                )
                raise CircuitOpenError(circuit.service, recovery_ts)

            # 2. Execute with Strategy
            async with circuit:
                if lock_lost_event.is_set():
                    raise PaymentError("Wallet lock lease was lost before payment execution.")
                if strategy == PaymentStrategy.RETRY_THEN_FAIL:
                    result = await execute_with_retry(
                        self._router.pay,
                        wallet_id=wallet_id,
                        recipient=recipient,
                        amount=amount_decimal,
                        purpose=purpose,
                        guards_passed=guards_passed,
                        fee_level=fee_level,
                        idempotency_key=idempotency_key,
                        destination_chain=destination_chain,
                        wait_for_completion=wait_for_completion,
                        timeout_seconds=timeout_seconds,
                        **kwargs,
                    )
                else:
                    # FAIL_FAST or QUEUE_BACKGROUND (attempt once)
                    result = await self._router.pay(
                        wallet_id=wallet_id,
                        recipient=recipient,
                        amount=amount_decimal,
                        purpose=purpose,
                        guards_passed=guards_passed,
                        fee_level=fee_level,
                        idempotency_key=idempotency_key,
                        destination_chain=destination_chain,
                        wait_for_completion=wait_for_completion,
                        timeout_seconds=timeout_seconds,
                        **kwargs,
                    )
                execution_result = result
                if lock_lost_event.is_set():
                    raise PaymentError("Wallet lock lease was lost during payment execution.")

            # 3. Success Handling
            if result.success or (
                result.status
                in (
                    PaymentStatus.AUTHORIZED,
                    PaymentStatus.PENDING,
                    PaymentStatus.PROCESSING,
                    PaymentStatus.PENDING_SETTLEMENT,
                    PaymentStatus.COMPLETED,
                    PaymentStatus.SETTLED,
                )
            ):
                await self._ledger.update_status(
                    ledger_entry.id,
                    LedgerEntryStatus.COMPLETED
                    if is_irreversible_success_status(result.status)
                    else LedgerEntryStatus.PENDING,
                    result.blockchain_tx,
                    metadata_updates={"transaction_id": result.transaction_id},
                )
                if guards_chain:
                    try:
                        await guards_chain.commit(reservation_tokens)
                    except Exception as commit_error:
                        await self._ledger.update_status(
                            ledger_entry.id,
                            LedgerEntryStatus.PENDING,
                            result.blockchain_tx,
                            metadata_updates={
                                "transaction_id": result.transaction_id,
                                "post_commit_error": str(commit_error),
                                "tx_already_submitted": True,
                            },
                        )
                        if result.metadata is None:
                            result.metadata = {}
                        result.metadata["post_commit_error"] = str(commit_error)
                        self._logger.error(
                            "Guard commit failed after payment execution (wallet=%s, ledger=%s): %s",
                            wallet_id,
                            ledger_entry.id,
                            commit_error,
                        )
                        return result
            else:
                await self._ledger.update_status(ledger_entry.id, LedgerEntryStatus.FAILED)
                if guards_chain:
                    await guards_chain.release(reservation_tokens)

            return result

        except Exception as e:
            # 4. Failure Handling & Queueing
            if strategy == PaymentStrategy.QUEUE_BACKGROUND:
                if execution_result and (
                    execution_result.transaction_id or execution_result.blockchain_tx
                ):
                    await self._ledger.update_status(
                        ledger_entry.id,
                        LedgerEntryStatus.PENDING,
                        execution_result.blockchain_tx,
                        metadata_updates={
                            "error": str(e),
                            "tx_already_submitted": True,
                            "transaction_id": execution_result.transaction_id,
                        },
                    )
                    raise e
                self._logger.warning(f"Payment failed ({e}), queueing background retry.")
                return await self._queue_payment(
                    context, ledger_entry.id, guards_chain, reservation_tokens
                )

            # Release guards on final failure
            if guards_chain:
                await guards_chain.release(reservation_tokens)

            await self._ledger.update_status(
                ledger_entry.id, LedgerEntryStatus.FAILED, metadata_updates={"error": str(e)}
            )
            raise e
        finally:
            # Release lock in all cases
            if lock_token:
                lock_heartbeat_stop.set()
                await lock_heartbeat_task
                await self._fund_lock.release_with_key(wallet_id, lock_token)

    async def _queue_payment(
        self,
        context: PaymentContext,
        ledger_entry_id: str,
        guards_chain: Any,
        reservation_tokens: list[str],
    ) -> PaymentResult:
        """Queue a payment for later execution with fund reservation."""
        # Create intent
        intent = await self._intent_service.create(
            wallet_id=context.wallet_id,
            recipient=context.recipient,
            amount=context.amount,
            purpose="Queued background payment",
            metadata=context.metadata,
        )

        # Reserve funds so they aren't double-spent while queued
        await self._reservation.reserve(context.wallet_id, context.amount, intent.id)
        intent.reserved_amount = context.amount

        # Update ledger to PENDING/QUEUED
        await self._ledger.update_status(
            ledger_entry_id,
            LedgerEntryStatus.PENDING,
            metadata_updates={"intent_id": intent.id, "queued": True},
        )

        # Release guard reservations — the fund reservation protects the balance
        if guards_chain:
            await guards_chain.release(reservation_tokens)

        return PaymentResult(
            success=False,  # Not yet executed — queued for later
            transaction_id=None,
            blockchain_tx=None,
            amount=context.amount,
            recipient=context.recipient,
            method=PaymentMethod.TRANSFER,
            status=PaymentStatus.PENDING,
            metadata={"queued": True, "intent_id": intent.id},
        )

    async def simulate(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal | str,
        wallet_set_id: str | None = None,
        check_trust: bool = False,
        skip_guards: bool = False,
        **kwargs: Any,
    ) -> SimulationResult:
        """
        Simulate a payment without executing.

        Checks:
        - Guards would pass
        - Balance is sufficient
        - Recipient is valid
        - Trust Gate (ERC-8004) would approve

        Args:
            wallet_id: Source wallet ID (REQUIRED)
            recipient: Payment recipient
            amount: Amount to simulate
            wallet_set_id: Optional wallet set ID (for set-level guards)
            check_trust: Enable/disable ERC-8004 Trust Gate check.
                         None (default) = auto (enabled if trust_gate configured).
                         True = force enable. False = skip trust check.
            skip_guards: Skip guard checks (dangerous!)
            **kwargs: Additional parameters

        Returns:
            SimulationResult with would_succeed and details
        """
        if not wallet_id:
            return SimulationResult(
                would_succeed=False,
                route=PaymentMethod.TRANSFER,
                reason="wallet_id is required",
            )

        amount_decimal = Decimal(str(amount))

        # Detect the actual route early so early-return reasons include it
        try:
            detected_route = (
                self._router.detect_method(
                    recipient,
                    source_network=Network.from_string(
                        self._wallet_service.get_wallet(wallet_id).blockchain
                    ),
                    destination_chain=kwargs.get("destination_chain"),
                    amount=amount_decimal,
                )
                or PaymentMethod.TRANSFER
            )
        except Exception:
            detected_route = PaymentMethod.TRANSFER

        if self._require_trust_gate and self._trust_gate and not self._trust_gate.is_configured:
            return SimulationResult(
                would_succeed=False,
                route=detected_route,
                reason=(
                    "OMNICLAW_REQUIRE_TRUST_GATE=true but Trust Gate is not configured. "
                    "Set OMNICLAW_RPC_URL."
                ),
            )

        # Get appropriate balance based on payment route
        # For X402/nanopayment routes → check Gateway balance
        # For Transfer/crosschain routes → check Circle wallet balance
        circle_balance = self._wallet_service.get_usdc_balance_amount(wallet_id)
        reserved_total = await self._reservation.get_reserved_total(wallet_id)

        route_uses_gateway = detected_route in (PaymentMethod.X402, PaymentMethod.NANOPAYMENT)

        if route_uses_gateway and self._nano_vault:
            try:
                gateway_balance = await self._nano_vault.get_balance(alias=f"wallet-{wallet_id}")
                available = gateway_balance.available
                balance_source = f"Gateway: {available}"
            except Exception:
                available = circle_balance - reserved_total
                balance_source = f"Circle: {available}"
        else:
            available = circle_balance - reserved_total
            balance_source = f"Circle: {available}"

        if amount_decimal > available:
            return SimulationResult(
                would_succeed=False,
                route=detected_route,
                reason=f"Insufficient available balance ({balance_source}, Reserved: {reserved_total}, Required: {amount_decimal})",
            )

        # Check guards first
        context = PaymentContext(
            wallet_id=wallet_id,
            wallet_set_id=wallet_set_id,
            recipient=recipient,
            amount=amount_decimal,
            purpose="Simulation",
        )

        passed_guards = []
        if not skip_guards:
            allowed, reason, passed_guards = await self._guard_manager.check(context)
            if not allowed:
                return SimulationResult(
                    would_succeed=False,
                    route=detected_route,
                    reason=f"Would be blocked by guard: {reason}",
                )

        # Trust Gate check (ERC-8004)
        run_trust = check_trust and not skip_guards
        trust_result: TrustCheckResult | None = None
        if self._trust_gate and run_trust and not self._trust_gate.is_configured:
            return SimulationResult(
                would_succeed=False,
                route=detected_route,
                reason="Trust Gate requires OMNICLAW_RPC_URL to be configured",
            )
        if self._trust_gate and run_trust:
            trust_result = await self._trust_gate.evaluate(
                recipient_address=recipient,
                amount=amount_decimal,
                wallet_id=wallet_id,
            )
            if trust_result.verdict != TrustVerdict.APPROVED:
                return SimulationResult(
                    would_succeed=False,
                    route=detected_route,
                    reason=f"Trust Gate: {trust_result.verdict.value} — {trust_result.block_reason}",
                )

        # Check via router
        sim_result = await self._router.simulate(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=amount_decimal,
            **kwargs,
        )
        sim_result.guards_that_would_pass = passed_guards
        # Recipient type logic based on route
        sim_result.recipient_type = getattr(sim_result.route, "value", str(sim_result.route))
        return sim_result

    def can_pay(self, recipient: str) -> bool:
        """
        Check if a recipient can be paid.

        Args:
            recipient: Payment recipient

        Returns:
            True if an adapter can handle this recipient
        """
        return self._router.can_handle(recipient)

    def detect_method(self, recipient: str) -> PaymentMethod | None:
        """Detect which payment method would be used for a recipient."""
        return self._router.detect_method(recipient)

    async def _maintain_wallet_lock(
        self,
        wallet_id: str,
        lock_token: str,
        ttl_seconds: int,
        stop_event: asyncio.Event,
        lock_lost_event: asyncio.Event | None = None,
    ) -> None:
        """Refresh a wallet lock lease in the background until stop_event is set."""
        refresh_interval = max(5, ttl_seconds // 3)
        while True:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=refresh_interval)
                return
            except asyncio.TimeoutError:
                refreshed = await self._fund_lock.refresh_with_key(
                    wallet_id=wallet_id,
                    lock_token=lock_token,
                    ttl=ttl_seconds,
                )
                if not refreshed:
                    self._logger.error(
                        "Wallet lock lease refresh failed (wallet=%s). "
                        "The lock may have been lost before payment flow completed.",
                        wallet_id,
                    )
                    if lock_lost_event is not None:
                        lock_lost_event.set()
                    return

    @property
    def intents(self) -> PaymentIntentService:
        """Get intent management service."""
        return self._intent_service

    async def create_payment_intent(
        self,
        wallet_id: str,
        recipient: str,
        amount: AmountType,
        purpose: str | None = None,
        expires_in: int | None = None,
        idempotency_key: str | None = None,
        skip_guards: bool = False,
        check_trust: bool | None = None,
        validate_recipient: bool = True,
        **kwargs: Any,
    ) -> PaymentIntent:
        """Create a Payment Intent (Authorize)."""
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            raise ValidationError(f"Payment amount must be positive. Got: {amount_decimal}")

        if self._require_trust_gate and self._trust_gate and not self._trust_gate.is_configured:
            raise ConfigurationError(
                "OMNICLAW_REQUIRE_TRUST_GATE=true but Trust Gate is not configured. "
                "Set OMNICLAW_RPC_URL before creating payment intents."
            )

        # Validate recipient format if enabled
        if validate_recipient:
            if not recipient:
                raise ValidationError("recipient is required")
            if recipient.startswith("0x"):
                if not re.match(r"^0x[0-9a-fA-F]{40}$", recipient):
                    raise ValidationError(
                        f"Invalid EVM address: {recipient!r}. "
                        f"Must be '0x' followed by exactly 40 hex characters."
                    )
            elif recipient.startswith("http") and not recipient.startswith("https://"):
                raise ValidationError(f"x402 recipient URL must use HTTPS. Got: {recipient!r}")

        # Acquire lock to ensure balance isn't changing while we simulate and reserve
        lock_ttl_seconds = max(60, int(self._config.transaction_poll_timeout) + 30)
        lock_token = await self._fund_lock.acquire(wallet_id, amount_decimal, ttl=lock_ttl_seconds)
        if not lock_token:
            raise PaymentError("Wallet is busy (locked by another transaction). Please retry.")

        lock_heartbeat_stop = asyncio.Event()
        lock_lost_event = asyncio.Event()
        lock_heartbeat_task = asyncio.create_task(
            self._maintain_wallet_lock(
                wallet_id=wallet_id,
                lock_token=lock_token,
                ttl_seconds=lock_ttl_seconds,
                stop_event=lock_heartbeat_stop,
                lock_lost_event=lock_lost_event,
            )
        )

        try:
            # Simulate check (Routing + Guards) strictly
            if lock_lost_event.is_set():
                raise PaymentError("Wallet lock lease was lost before intent simulation.")
            sim_result = await self.simulate(
                wallet_id=wallet_id,
                recipient=recipient,
                amount=amount_decimal,
                skip_guards=skip_guards,
                check_trust=check_trust,
                **kwargs,
            )

            if not sim_result.would_succeed:
                # Allow intent creation if Trust Gate simply HELD the transaction for review
                is_trust_held = sim_result.reason and "Trust Gate: HELD" in sim_result.reason
                if not is_trust_held:
                    raise PaymentError(f"Authorization failed: {sim_result.reason}")

            # Create Intent
            if idempotency_key:
                idempotency_index_key = f"wallet:{wallet_id}:intent_idempotency:{idempotency_key}"
                existing_map = await self._storage.get(
                    "payment_intent_idempotency", idempotency_index_key
                )
                if existing_map:
                    existing_intent_id = existing_map.get("intent_id")
                    if existing_intent_id:
                        existing_intent = await self._intent_service.get(existing_intent_id)
                        if existing_intent is not None:
                            return existing_intent

            metadata = kwargs.copy()
            metadata.update(
                {
                    "idempotency_key": idempotency_key,
                    "simulated_route": getattr(sim_result.route, "value", str(sim_result.route)),
                }
            )

            is_trust_held = (
                not sim_result.would_succeed
                and sim_result.reason
                and "Trust Gate: HELD" in sim_result.reason
            )
            if is_trust_held:
                metadata["trust_status"] = "HELD"
                metadata["trust_reason"] = sim_result.reason

            intent = await self._intent_service.create(
                wallet_id=wallet_id,
                recipient=recipient,
                amount=amount_decimal,
                purpose=purpose,
                expires_in=expires_in,
                metadata=metadata,
            )

            # If the transaction requires manual review, map it to the correct Intent State
            if is_trust_held:
                from omniclaw.core.types import PaymentIntentStatus

                await self._intent_service.update_status(
                    intent.id, PaymentIntentStatus.REQUIRES_REVIEW
                )
                intent.status = PaymentIntentStatus.REQUIRES_REVIEW

            # Layer 2: Reserve the funds in the ledger
            await self._reservation.reserve(
                wallet_id, amount_decimal, intent.id, expires_at=intent.expires_at
            )
            if idempotency_key:
                idempotency_index_key = f"wallet:{wallet_id}:intent_idempotency:{idempotency_key}"
                await self._storage.save(
                    "payment_intent_idempotency",
                    idempotency_index_key,
                    {"intent_id": intent.id},
                )
            if lock_lost_event.is_set():
                raise PaymentError(
                    "Wallet lock lease was lost before intent reservation completed."
                )
            intent.reserved_amount = amount_decimal

            return intent
        finally:
            if lock_token:
                lock_heartbeat_stop.set()
                await lock_heartbeat_task
                await self._fund_lock.release_with_key(wallet_id, lock_token)

    async def confirm_payment_intent(self, intent_id: str) -> PaymentResult:
        """Confirm and execute a Payment Intent (Capture)."""
        intent = await self._intent_service.get(intent_id)
        if not intent:
            raise ValidationError(f"Intent not found: {intent_id}")

        if intent.status not in (
            PaymentIntentStatus.REQUIRES_CONFIRMATION,
            PaymentIntentStatus.REQUIRES_REVIEW,
        ):
            raise ValidationError(f"Intent cannot be confirmed. Status: {intent.status}")
        if intent.status == PaymentIntentStatus.REQUIRES_REVIEW:
            approved = bool((intent.metadata or {}).get("trust_review_approved"))
            if not approved:
                raise ValidationError("Intent requires manual trust approval before confirmation.")

        # Check expiry
        if intent.expires_at:
            from datetime import datetime, timezone

            now_utc = datetime.now(timezone.utc)
            cmp_time = now_utc if intent.expires_at.tzinfo else now_utc.replace(tzinfo=None)

            if cmp_time > intent.expires_at:
                # Auto-cancel expired intent and release reservation
                await self._reservation.release(intent.id)
                await self._intent_service.cancel(intent.id, reason="Expired")
                raise ValidationError(f"Intent expired at {intent.expires_at}")

        try:
            # Update to Processing
            await self._intent_service.update_status(intent.id, PaymentIntentStatus.PROCESSING)

            # Prepare exec args from intent + metadata
            exec_kwargs = intent.metadata.copy()

            # Remove internal metadata keys that aren't for routing
            purpose = exec_kwargs.pop("purpose", None)
            idempotency_key = exec_kwargs.pop("idempotency_key", None)
            exec_kwargs.pop("simulated_route", None)
            exec_kwargs.pop("trust_status", None)
            exec_kwargs.pop("trust_reason", None)

            # Execute Pay
            result = await self.pay(
                wallet_id=intent.wallet_id,
                recipient=intent.recipient,
                amount=intent.amount,
                purpose=purpose,
                idempotency_key=idempotency_key,
                check_trust=False,
                consume_intent_id=intent.id,  # Key part: releases reservation inside the lock
                validate_recipient=False,  # Intent already validated recipient at creation
                **exec_kwargs,
            )

            if result.success:
                await self._intent_service.update_status(intent.id, PaymentIntentStatus.SUCCEEDED)
            else:
                await self._reservation.release(intent.id)
                await self._intent_service.update_status(intent.id, PaymentIntentStatus.FAILED)

            return result

        except Exception as e:
            # Mark failed on exception
            await self._reservation.release(intent.id)
            await self._intent_service.update_status(intent.id, PaymentIntentStatus.FAILED)
            raise e

    async def get_payment_intent(self, intent_id: str) -> PaymentIntent | None:
        """Get Payment Intent by ID."""
        return await self._intent_service.get(intent_id)

    async def cancel_payment_intent(
        self, intent_id: str, reason: str | None = None
    ) -> PaymentIntent:
        """Cancel a Payment Intent."""
        intent = await self._intent_service.get(intent_id)
        if not intent:
            raise ValidationError(f"Intent not found: {intent_id}")

        if intent.status not in (
            PaymentIntentStatus.REQUIRES_CONFIRMATION,
            PaymentIntentStatus.REQUIRES_REVIEW,
        ):
            raise ValidationError(f"Cannot cancel intent in status: {intent.status}")

        # Layer 2: Release reserved funds
        await self._reservation.release(intent.id)

        return await self._intent_service.cancel(intent.id, reason=reason)

    async def approve_payment_intent_review(
        self,
        intent_id: str,
        *,
        approved_by: str,
        reason: str | None = None,
    ) -> PaymentIntent:
        """Approve a REQUIRES_REVIEW intent for confirmation."""
        intent = await self._intent_service.get(intent_id)
        if not intent:
            raise ValidationError(f"Intent not found: {intent_id}")
        if intent.status != PaymentIntentStatus.REQUIRES_REVIEW:
            raise ValidationError(f"Intent is not in REQUIRES_REVIEW status: {intent.status}")
        metadata = intent.metadata or {}
        metadata["trust_review_approved"] = True
        metadata["trust_review_approved_by"] = approved_by
        metadata["trust_review_reason"] = reason or ""
        metadata["trust_review_approved_at"] = datetime.now(timezone.utc).isoformat()
        intent.metadata = metadata
        await self._intent_service._save(intent)
        return intent

    async def batch_pay(
        self, requests: list[PaymentRequest], concurrency: int = 5
    ) -> BatchPaymentResult:
        """
        Execute multiple payments in batch.

        Args:
            requests: List of payment requests to execute
            concurrency: Maximum number of concurrent executions (default 5)

        Returns:
            BatchPaymentResult containing status of all payments
        """
        return await self._batch_processor.process(requests, concurrency)

    async def sync_transaction(self, entry_id: str) -> LedgerEntry:
        """Synchronize a ledger entry with the provider status."""
        entry = await self._ledger.get(entry_id)
        if not entry:
            raise ValidationError(f"Ledger entry not found: {entry_id}")

        tx_id = entry.metadata.get("transaction_id")
        if not tx_id:
            raise ValidationError("Ledger entry has no transaction ID to sync")

        # Call Provider
        try:
            tx_info = self._wallet_service._circle.get_transaction(tx_id)
        except Exception as e:
            raise PaymentError(f"Failed to fetch transaction from provider: {e}") from e

        # Map status
        new_status = entry.status
        if tx_info.state == "COMPLETE":
            new_status = LedgerEntryStatus.COMPLETED
        elif tx_info.state == "FAILED":
            new_status = LedgerEntryStatus.FAILED
        elif tx_info.state == "CANCELLED":
            new_status = LedgerEntryStatus.CANCELLED

        # Update Ledger
        await self._ledger.update_status(
            entry.id,
            new_status,
            tx_hash=tx_info.tx_hash,
            metadata_updates={
                "last_synced": datetime.now(timezone.utc).isoformat(),
                "provider_state": tx_info.state.value
                if hasattr(tx_info.state, "value")
                else str(tx_info.state),
                "fee_level": tx_info.fee_level.value if tx_info.fee_level else None,
            },
        )

        updated = await self._ledger.get(entry.id)
        return updated  # type: ignore

    async def list_pending_settlements(
        self,
        *,
        wallet_id: str | None = None,
        limit: int = 100,
    ) -> list[LedgerEntry]:
        """List ledger entries awaiting settlement finalization."""
        return await self._ledger.query(
            wallet_id=wallet_id,
            status=LedgerEntryStatus.PENDING,
            limit=limit,
        )

    async def finalize_pending_settlement(
        self,
        entry_id: str,
        *,
        settled: bool,
        settlement_tx_hash: str | None = None,
        reason: str | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        """
        Finalize an in-flight settlement (manual/operator reconciliation hook).

        This is intended for relayed cross-chain flows where final mint confirmation
        arrives out-of-band from the original burn transaction.
        """
        entry = await self._ledger.get(entry_id)
        if not entry:
            raise ValidationError(f"Ledger entry not found: {entry_id}")
        if entry.status != LedgerEntryStatus.PENDING:
            raise ValidationError(f"Ledger entry is not pending settlement: {entry.status.value}")

        final_status = LedgerEntryStatus.COMPLETED if settled else LedgerEntryStatus.FAILED
        merged_updates = {
            "settlement_final": bool(settled),
            "settlement_reconciled_at": datetime.now(timezone.utc).isoformat(),
        }
        if reason:
            merged_updates["settlement_reconcile_reason"] = reason
        if metadata_updates:
            merged_updates.update(metadata_updates)

        await self._ledger.update_status(
            entry_id,
            final_status,
            tx_hash=settlement_tx_hash or entry.tx_hash,
            metadata_updates=merged_updates,
        )

        updated = await self._ledger.get(entry_id)
        if not updated:
            raise PaymentError(f"Failed to reload updated ledger entry: {entry_id}")
        return updated

    async def reconcile_pending_settlements(
        self,
        *,
        wallet_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, int]:
        """
        Reconcile pending settlements by syncing provider transaction states.

        Returns counters for operational monitoring.
        """
        pending_entries = await self.list_pending_settlements(wallet_id=wallet_id, limit=limit)
        stats = {
            "processed": 0,
            "finalized": 0,
            "still_pending": 0,
            "errors": 0,
        }

        for entry in pending_entries:
            stats["processed"] += 1
            tx_id = (entry.metadata or {}).get("transaction_id")
            if not tx_id:
                stats["still_pending"] += 1
                continue

            try:
                updated = await self.sync_transaction(entry.id)
                if updated.status in (
                    LedgerEntryStatus.COMPLETED,
                    LedgerEntryStatus.FAILED,
                    LedgerEntryStatus.CANCELLED,
                ):
                    await self._ledger.update_status(
                        updated.id,
                        updated.status,
                        tx_hash=updated.tx_hash,
                        metadata_updates={
                            "settlement_final": updated.status == LedgerEntryStatus.COMPLETED,
                            "settlement_reconciled_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    stats["finalized"] += 1
                else:
                    stats["still_pending"] += 1
            except Exception as exc:
                stats["errors"] += 1
                self._logger.warning(
                    "Pending settlement reconcile failed (entry=%s): %s",
                    entry.id,
                    exc,
                )

        return stats

    async def add_budget_guard(
        self,
        wallet_id: str,
        daily_limit: str | Decimal | None = None,
        hourly_limit: str | Decimal | None = None,
        total_limit: str | Decimal | None = None,
        name: str = "budget",
    ) -> None:
        """
        Add a budget guard to a wallet.

        Enforce spending limits over time periods (Atomic & Reliable).

        Args:
            wallet_id: Target wallet ID
            daily_limit: Max spend per 24h
            hourly_limit: Max spend per 1h
            total_limit: Max total spend (lifetime)
            name: Custom name for the guard
        """
        from omniclaw.guards.budget import BudgetGuard

        d_limit = Decimal(str(daily_limit)) if daily_limit else None
        h_limit = Decimal(str(hourly_limit)) if hourly_limit else None
        t_limit = Decimal(str(total_limit)) if total_limit else None

        guard = BudgetGuard(
            daily_limit=d_limit, hourly_limit=h_limit, total_limit=t_limit, name=name
        )
        await self._guard_manager.add_guard(wallet_id, guard)

    async def add_budget_guard_for_set(
        self,
        wallet_set_id: str,
        daily_limit: str | Decimal | None = None,
        hourly_limit: str | Decimal | None = None,
        total_limit: str | Decimal | None = None,
        name: str = "budget",
    ) -> None:
        """
        Add a budget guard to a wallet set (applies to ALL wallets in the set).

        Args:
            wallet_set_id: Target wallet set ID
            daily_limit: Max spend per 24h
            hourly_limit: Max spend per 1h
            total_limit: Max total spend (lifetime)
            name: Custom name for the guard
        """
        from omniclaw.guards.budget import BudgetGuard

        d_limit = Decimal(str(daily_limit)) if daily_limit else None
        h_limit = Decimal(str(hourly_limit)) if hourly_limit else None
        t_limit = Decimal(str(total_limit)) if total_limit else None

        guard = BudgetGuard(
            daily_limit=d_limit, hourly_limit=h_limit, total_limit=t_limit, name=name
        )
        await self._guard_manager.add_guard_for_set(wallet_set_id, guard)

    async def add_single_tx_guard(
        self,
        wallet_id: str,
        max_amount: str | Decimal,
        min_amount: str | Decimal | None = None,
        name: str = "single_tx",
    ) -> None:
        """
        Add a Single Transaction Limit guard.

        Args:
            wallet_id: Target wallet ID
            max_amount: Max amount per transaction
            min_amount: Min amount per transaction
            name: Guard name
        """
        from omniclaw.guards.single_tx import SingleTxGuard

        guard = SingleTxGuard(
            max_amount=Decimal(str(max_amount)),
            min_amount=Decimal(str(min_amount)) if min_amount else None,
            name=name,
        )
        await self._guard_manager.add_guard(wallet_id, guard)

    async def add_recipient_guard(
        self,
        wallet_id: str,
        mode: str = "whitelist",
        addresses: list[str] | None = None,
        patterns: list[str] | None = None,
        domains: list[str] | None = None,
        name: str = "recipient",
    ) -> None:
        """
        Add a Recipient Access Control guard.

        Args:
            wallet_id: Target wallet ID
            mode: 'whitelist' (allow specific) or 'blacklist' (block specific)
            addresses: List of allowed/blocked addresses
            patterns: List of regex patterns
            domains: List of allowed/blocked domains (for x402/URLs)
            name: Guard name
        """
        from omniclaw.guards.recipient import RecipientGuard

        guard = RecipientGuard(
            mode=mode, addresses=addresses, patterns=patterns, domains=domains, name=name
        )
        await self._guard_manager.add_guard(wallet_id, guard)

    async def add_rate_limit_guard(
        self,
        wallet_id: str,
        max_per_minute: int | None = None,
        max_per_hour: int | None = None,
        max_per_day: int | None = None,
        name: str = "rate_limit",
    ) -> None:
        """
        Add a rate limit guard to a wallet.

        Limit number of transactions per time window.

        Args:
            wallet_id: Target wallet ID
            max_per_minute: Max txs per minute
            max_per_hour: Max txs per hour
            max_per_day: Max txs per day
            name: Custom name for the guard
        """
        from omniclaw.guards.rate_limit import RateLimitGuard

        guard = RateLimitGuard(
            max_per_minute=max_per_minute,
            max_per_hour=max_per_hour,
            max_per_day=max_per_day,
            name=name,
        )
        await self._guard_manager.add_guard(wallet_id, guard)

    async def add_confirm_guard(
        self,
        wallet_id: str,
        threshold: str | Decimal | None = None,
        always_confirm: bool = False,
        name: str = "confirm",
    ) -> None:
        """
        Add a confirmation guard to a wallet (Human-in-the-Loop).

        Payments above the threshold require explicit confirmation via callback
        or external handling (e.g., webhook approval).

        Args:
            wallet_id: Target wallet ID
            threshold: Amount above which confirmation is required
            always_confirm: If True, require confirmation for ALL payments
            name: Custom name for the guard
        """
        from omniclaw.guards.confirm import ConfirmGuard

        t_threshold = Decimal(str(threshold)) if threshold else None

        guard = ConfirmGuard(threshold=t_threshold, always_confirm=always_confirm, name=name)
        await self._guard_manager.add_guard(wallet_id, guard)

    async def add_confirm_guard_for_set(
        self,
        wallet_set_id: str,
        threshold: str | Decimal | None = None,
        always_confirm: bool = False,
        name: str = "confirm",
    ) -> None:
        """
        Add a confirmation guard to a wallet set (applies to ALL wallets in the set).

        Args:
            wallet_set_id: Target wallet set ID
            threshold: Amount above which confirmation is required
            always_confirm: If True, require confirmation for ALL payments
            name: Custom name for the guard
        """
        from omniclaw.guards.confirm import ConfirmGuard

        t_threshold = Decimal(str(threshold)) if threshold else None

        guard = ConfirmGuard(threshold=t_threshold, always_confirm=always_confirm, name=name)
        await self._guard_manager.add_guard_for_set(wallet_set_id, guard)

    async def add_rate_limit_guard_for_set(
        self,
        wallet_set_id: str,
        max_per_minute: int | None = None,
        max_per_hour: int | None = None,
        max_per_day: int | None = None,
        name: str = "rate_limit",
    ) -> None:
        """
        Add a rate limit guard to a wallet set (applies to ALL wallets in the set).

        Args:
            wallet_set_id: Target wallet set ID
            max_per_minute: Max txs per minute
            max_per_hour: Max txs per hour
            max_per_day: Max txs per day
            name: Custom name for the guard
        """
        from omniclaw.guards.rate_limit import RateLimitGuard

        guard = RateLimitGuard(
            max_per_minute=max_per_minute,
            max_per_hour=max_per_hour,
            max_per_day=max_per_day,
            name=name,
        )
        await self._guard_manager.add_guard_for_set(wallet_set_id, guard)

    async def add_recipient_guard_for_set(
        self,
        wallet_set_id: str,
        mode: str = "whitelist",
        addresses: list[str] | None = None,
        patterns: list[str] | None = None,
        domains: list[str] | None = None,
        name: str = "recipient",
    ) -> None:
        """
        Add a Recipient Access Control guard to a wallet set.

        Args:
            wallet_set_id: Target wallet set ID
            mode: 'whitelist' (allow specific) or 'blacklist' (block specific)
            addresses: List of allowed/blocked addresses
            patterns: List of regex patterns
            domains: List of allowed/blocked domains (for x402/URLs)
            name: Guard name
        """
        from omniclaw.guards.recipient import RecipientGuard

        guard = RecipientGuard(
            mode=mode, addresses=addresses, patterns=patterns, domains=domains, name=name
        )
        await self._guard_manager.add_guard_for_set(wallet_set_id, guard)

    async def list_guards(self, wallet_id: str) -> list[str]:
        """
        List all guard names registered for a wallet.

        Args:
            wallet_id: Target wallet ID

        Returns:
            List of guard names
        """
        return await self._guard_manager.list_wallet_guard_names(wallet_id)

    async def list_guards_for_set(self, wallet_set_id: str) -> list[str]:
        """
        List all guard names registered for a wallet set.

        Args:
            wallet_set_id: Target wallet set ID

        Returns:
            List of guard names
        """
        return await self._guard_manager.list_wallet_set_guard_names(wallet_set_id)
