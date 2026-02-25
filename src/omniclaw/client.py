"""OmniClawClient - Main SDK entry point."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from omniclaw.core.circle_client import CircleClient
from omniclaw.core.config import Config
from omniclaw.core.exceptions import InsufficientBalanceError, PaymentError, ValidationError
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
from omniclaw.intents.intent_facade import PaymentIntentFacade
from omniclaw.intents.reservation import ReservationService
from omniclaw.intents.service import PaymentIntentService
from omniclaw.ledger import Ledger, LedgerEntry, LedgerEntryStatus
from omniclaw.ledger.lock import FundLockService
from omniclaw.payment.batch import BatchProcessor
from omniclaw.payment.router import PaymentRouter
from omniclaw.protocols.gateway import GatewayAdapter
from omniclaw.protocols.transfer import TransferAdapter
from omniclaw.protocols.x402 import X402Adapter
from omniclaw.resilience.circuit import CircuitBreaker, CircuitOpenError
from omniclaw.resilience.retry import execute_with_retry
from omniclaw.storage import get_storage
from omniclaw.risk.guard import RiskGuard, RiskFlaggedError, RiskBlockedError
from omniclaw.trust.gate import TrustGate
from omniclaw.identity.types import TrustCheckResult, TrustPolicy, TrustVerdict
from omniclaw.wallet.service import WalletService
from omniclaw.webhooks import WebhookParser


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
        self._logger.info(f"Initializing OmniClaw SDK (Network: {network.value})")

        if not circle_api_key:
            circle_api_key = os.environ.get("CIRCLE_API_KEY")

        if not entity_secret:
            entity_secret = os.environ.get("ENTITY_SECRET")

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

        self._storage = get_storage()
        self._ledger = Ledger(self._storage)
        self._fund_lock = FundLockService(self._storage)
        self._guard_manager = GuardManager(self._storage)
        self._circle_client = CircleClient(self._config)

        self._wallet_service = WalletService(
            self._config,
            self._circle_client,
        )

        self._router = PaymentRouter(self._config, self._wallet_service)
        self._router.register_adapter(TransferAdapter(self._config, self._wallet_service))
        self._router.register_adapter(X402Adapter(self._config, self._wallet_service))
        self._router.register_adapter(GatewayAdapter(self._config, self._wallet_service))

        self._intent_service = PaymentIntentService(self._storage)
        self._reservation = ReservationService(self._storage)
        self._intent_facade = PaymentIntentFacade(self)
        self._batch_processor = BatchProcessor(self._router)
        self._webhook_parser = WebhookParser()

        # Initialize Trust Gate (ERC-8004)
        if isinstance(trust_policy, str):
            presets = {"permissive": TrustPolicy.permissive, "standard": TrustPolicy.standard, "strict": TrustPolicy.strict}
            trust_policy = presets.get(trust_policy, TrustPolicy.permissive)()
        self._trust_gate = TrustGate(
            storage=self._storage,
            wallet_service=self._wallet_service,
            network=network,
            default_policy=trust_policy,
            rpc_url=rpc_url,
        )

        # Initialize Resilience
        self._circuit_breakers = {
            "default": CircuitBreaker("default", self._storage),
            "circle_api": CircuitBreaker("circle_api", self._storage),
        }

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

    async def __aenter__(self) -> OmniClaw:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit — clean up resources."""
        # Close Trust Gate (HTTP clients for metadata fetching)
        await self._trust_gate.close()
        # Close any HTTP clients held by protocol adapters
        for adapter in self._router.get_adapters():
            client = getattr(adapter, "_http_client", None)
            if client and hasattr(client, "aclose"):
                await client.aclose()

    async def get_balance(self, wallet_id: str) -> Decimal:
        """Get USDC balance for a wallet."""
        return self._wallet_service.get_usdc_balance_amount(wallet_id)

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
        check_trust: bool | None = None,
        consume_intent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        wait_for_completion: bool = False,
        timeout_seconds: float | None = None,
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
            **kwargs: Additional options

        Returns:
            PaymentResult with transaction details
        """
        if not wallet_id:
            raise ValidationError("wallet_id is required")

        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            raise ValidationError(f"Payment amount must be positive. Got: {amount_decimal}")

        idempotency_key = idempotency_key or str(uuid.uuid4())

        meta = metadata or {}
        meta["idempotency_key"] = idempotency_key
        meta["strategy"] = strategy.value

        # ── Trust Gate Check (ERC-8004) ──────────────────────────────
        # check_trust=None → auto (enabled if trust_gate configured and guards not skipped)
        # check_trust=True → force enable even with skip_guards
        # check_trust=False → skip trust check
        run_trust = check_trust if check_trust is not None else (not skip_guards)
        trust_result: TrustCheckResult | None = None
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
            except RiskFlaggedError as e:
                # RISK FLAG: Create intent for review
                intent = await self._intent_service.create(
                    wallet_id=wallet_id,
                    recipient=recipient,
                    amount=amount_decimal,
                    purpose=purpose,
                    metadata=meta,
                )
                
                # Reserve funds for the intent so they are locked while pending review
                # The guard reservation (if any) is released, replaced by this dedicated intent reservation
                if guards_chain and reservation_tokens:
                    await guards_chain.release(reservation_tokens)
                
                await self._reservation.reserve(wallet_id, amount_decimal, intent.id)
                intent.reserved_amount = amount_decimal
                
                await self._ledger.update_status(
                    ledger_entry.id,
                    LedgerEntryStatus.PENDING,
                    metadata_updates={
                        "risk_score": e.score,
                        "risk_reasons": e.reasons,
                        "intent_id": intent.id,
                        "status": "flagged_for_review"
                    }
                )
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=amount_decimal,
                    recipient=recipient,
                    method=PaymentMethod.TRANSFER,
                    status=PaymentStatus.PENDING,
                    error=f"Risk Flagged ({e.score:.1f}): Requires Review",
                    guards_passed=guards_passed,
                    metadata={
                        "risk_score": e.score,
                        "risk_flagged": True,
                        "intent_id": intent.id
                    }
                )
            except RiskBlockedError as e:
                if guards_chain and reservation_tokens:
                    await guards_chain.release(reservation_tokens)
                    
                await self._ledger.update_status(
                    ledger_entry.id,
                    LedgerEntryStatus.BLOCKED,
                    metadata_updates={"risk_blocked": True, "error": str(e)}
                )
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=amount_decimal,
                    recipient=recipient,
                    method=PaymentMethod.TRANSFER,
                    status=PaymentStatus.BLOCKED,
                    error=f"Risk Blocked: {e}",
                    guards_passed=guards_passed,
                    metadata={"risk_blocked": True}
                )

        # Acquire Fund Lock (Mutex) to prevent double-spend race conditions
        lock_token = await self._fund_lock.acquire(wallet_id, amount_decimal)
        if not lock_token:
             # Could not acquire lock (busy)
             error_msg = "Wallet is busy (locked by another transaction). Please retry."
             if guards_chain and reservation_tokens:
                 await guards_chain.release(reservation_tokens)
             
             await self._ledger.update_status(
                 ledger_entry.id, 
                 LedgerEntryStatus.FAILED, 
                 metadata_updates={"error": error_msg}
             )
             raise PaymentError(error_msg)

        try:
            # If we are confirming an intent, release its reservation now that we hold the mutex
            if consume_intent_id:
                await self._reservation.release(consume_intent_id)

            # Double check available balance inside lock
            balance = self._wallet_service.get_usdc_balance_amount(wallet_id)
            reserved_total = await self._reservation.get_reserved_total(wallet_id)
            available = balance - reserved_total
            if amount_decimal > available:
                error_msg = f"Insufficient available balance (Total: {balance}, Reserved: {reserved_total}, Available: {available})"
                if guards_chain and reservation_tokens:
                    await guards_chain.release(reservation_tokens)
                await self._ledger.update_status(
                    ledger_entry.id,
                    LedgerEntryStatus.FAILED,
                    metadata_updates={"error": error_msg}
                )
                raise InsufficientBalanceError(
                    error_msg,
                    current_balance=available,
                    required_amount=amount_decimal
                )

            # Resilience Shell
            circuit = self._circuit_breakers.get("circle_api")  # Default to Circle API for now
            if not circuit:
                 circuit = self._circuit_breakers["default"]

            # 1. Check Circuit
            if not await circuit.is_available():
                if strategy == PaymentStrategy.QUEUE_BACKGROUND:
                    # Queue it
                    return await self._queue_payment(context, ledger_entry.id, guards_chain, reservation_tokens)
                
                # Fail Fast / Retry logic implies fail if circuit open
                recovery_ts = await circuit.get_recovery_ts() if hasattr(circuit, "get_recovery_ts") else 0
                raise CircuitOpenError(circuit.service, recovery_ts)

            # 2. Execute with Strategy
            async with circuit:
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

            # 3. Success Handling
            if result.success:
                await self._ledger.update_status(
                    ledger_entry.id,
                    LedgerEntryStatus.COMPLETED
                    if result.status == PaymentStatus.COMPLETED
                    else LedgerEntryStatus.PENDING,
                    result.blockchain_tx,
                    metadata_updates={"transaction_id": result.transaction_id},
                )
                if guards_chain:
                    await guards_chain.commit(reservation_tokens)
            else:
                await self._ledger.update_status(ledger_entry.id, LedgerEntryStatus.FAILED)
                if guards_chain:
                    await guards_chain.release(reservation_tokens)

            return result

        except Exception as e:
            # 4. Failure Handling & Queueing
            if strategy == PaymentStrategy.QUEUE_BACKGROUND:
                self._logger.warning(f"Payment failed ({e}), queueing background retry.")
                return await self._queue_payment(context, ledger_entry.id, guards_chain, reservation_tokens)
            
            # Release guards on final failure
            if guards_chain:
                await guards_chain.release(reservation_tokens)

            await self._ledger.update_status(ledger_entry.id, LedgerEntryStatus.FAILED, metadata_updates={"error": str(e)})
            raise e
        finally:
            # Release lock in all cases
            if lock_token:
                await self._fund_lock.release_with_key(wallet_id, lock_token)

    async def _queue_payment(
        self,
        context: PaymentContext,
        ledger_entry_id: str,
        guards_chain: Any,
        reservation_tokens: list[str]
    ) -> PaymentResult:
        """Queue a payment for later execution with fund reservation."""
        # Create intent
        intent = await self._intent_service.create(
            wallet_id=context.wallet_id,
            recipient=context.recipient,
            amount=context.amount,
            purpose="Queued background payment",
            metadata=context.metadata
        )

        # Reserve funds so they aren't double-spent while queued
        await self._reservation.reserve(context.wallet_id, context.amount, intent.id)
        intent.reserved_amount = context.amount

        # Update ledger to PENDING/QUEUED
        await self._ledger.update_status(
            ledger_entry_id, 
            LedgerEntryStatus.PENDING, 
            metadata_updates={"intent_id": intent.id, "queued": True}
        )
        
        # Release guard reservations — the fund reservation protects the balance
        if guards_chain:
            await guards_chain.release(reservation_tokens)

        return PaymentResult(
            success=True,  # It was successfully queued
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
        check_trust: bool | None = None,
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

        # Check available balance considering reservations
        reserved_total = await self._reservation.get_reserved_total(wallet_id)
        balance = self._wallet_service.get_usdc_balance_amount(wallet_id)
        available = balance - reserved_total
        if amount_decimal > available:
            return SimulationResult(
                would_succeed=False,
                route=PaymentMethod.TRANSFER,
                reason=f"Insufficient available balance (Total: {balance}, Reserved for intents: {reserved_total}, Available: {available})",
            )

        # Check guards first
        context = PaymentContext(
            wallet_id=wallet_id,
            wallet_set_id=wallet_set_id,
            recipient=recipient,
            amount=amount_decimal,
            purpose="Simulation",
        )

        allowed, reason, passed_guards = await self._guard_manager.check(context)
        if not allowed:
            return SimulationResult(
                would_succeed=False,
                route=PaymentMethod.TRANSFER,
                reason=f"Would be blocked by guard: {reason}",
            )

        # Trust Gate check (ERC-8004)
        run_trust = check_trust if check_trust is not None else True
        trust_result: TrustCheckResult | None = None
        if self._trust_gate and run_trust:
            trust_result = await self._trust_gate.evaluate(
                recipient_address=recipient,
                amount=amount_decimal,
                wallet_id=wallet_id,
            )
            if trust_result.verdict != TrustVerdict.APPROVED:
                return SimulationResult(
                    would_succeed=False,
                    route=PaymentMethod.TRANSFER,
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
        sim_result.recipient_type = sim_result.route.value
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
        **kwargs: Any,
    ) -> PaymentIntent:
        """Create a Payment Intent (Authorize)."""
        amount_decimal = Decimal(str(amount))

        # Acquire lock to ensure balance isn't changing while we simulate and reserve
        lock_token = await self._fund_lock.acquire(wallet_id, amount_decimal)
        if not lock_token:
             raise PaymentError("Wallet is busy (locked by another transaction). Please retry.")
             
        try:
            # Simulate check (Routing + Guards) strictly
            sim_result = await self.simulate(
                wallet_id=wallet_id, recipient=recipient, amount=amount_decimal, **kwargs
            )

            if not sim_result.would_succeed:
                raise PaymentError(f"Authorization failed: {sim_result.reason}")

            # Create Intent
            metadata = kwargs.copy()
            metadata.update(
                {
                    "idempotency_key": idempotency_key,
                    "simulated_route": sim_result.route.value,
                }
            )

            intent = await self._intent_service.create(
                wallet_id=wallet_id, 
                recipient=recipient, 
                amount=amount_decimal, 
                purpose=purpose,
                expires_in=expires_in,
                metadata=metadata
            )
            
            # Layer 2: Reserve the funds in the ledger
            await self._reservation.reserve(wallet_id, amount_decimal, intent.id)
            intent.reserved_amount = amount_decimal
            
            return intent
        finally:
            if lock_token:
                await self._fund_lock.release_with_key(wallet_id, lock_token)

    async def confirm_payment_intent(self, intent_id: str) -> PaymentResult:
        """Confirm and execute a Payment Intent (Capture)."""
        intent = await self._intent_service.get(intent_id)
        if not intent:
            raise ValidationError(f"Intent not found: {intent_id}")

        if intent.status != PaymentIntentStatus.REQUIRES_CONFIRMATION:
            raise ValidationError(f"Intent cannot be confirmed. Status: {intent.status}")

        # Check expiry
        if intent.expires_at:
            from datetime import datetime
            if datetime.utcnow() > intent.expires_at:
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

            # Execute Pay
            result = await self.pay(
                wallet_id=intent.wallet_id,
                recipient=intent.recipient,
                amount=intent.amount,
                purpose=purpose,
                idempotency_key=idempotency_key,
                consume_intent_id=intent.id, # Key part: releases reservation inside the lock
                **exec_kwargs,
            )

            if result.success:
                await self._intent_service.update_status(intent.id, PaymentIntentStatus.SUCCEEDED)
            else:
                await self._intent_service.update_status(intent.id, PaymentIntentStatus.FAILED)

            return result

        except Exception as e:
            # Mark failed on exception
            await self._intent_service.update_status(intent.id, PaymentIntentStatus.FAILED)
            raise e

    async def get_payment_intent(self, intent_id: str) -> PaymentIntent | None:
        """Get Payment Intent by ID."""
        return await self._intent_service.get(intent_id)

    async def cancel_payment_intent(self, intent_id: str, reason: str | None = None) -> PaymentIntent:
        """Cancel a Payment Intent."""
        intent = await self._intent_service.get(intent_id)
        if not intent:
            raise ValidationError(f"Intent not found: {intent_id}")

        if intent.status not in (PaymentIntentStatus.REQUIRES_CONFIRMATION,):
            raise ValidationError(f"Cannot cancel intent in status: {intent.status}")

        # Layer 2: Release reserved funds
        await self._reservation.release(intent.id)

        return await self._intent_service.cancel(intent.id, reason=reason)

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
            tx_info = self._circle_client.get_transaction(tx_id)
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
                "last_synced": datetime.utcnow().isoformat(),
                "provider_state": tx_info.state.value
                if hasattr(tx_info.state, "value")
                else str(tx_info.state),
                "fee_level": tx_info.fee_level.value if tx_info.fee_level else None,
            },
        )

        updated = await self._ledger.get(entry.id)
        return updated  # type: ignore

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
