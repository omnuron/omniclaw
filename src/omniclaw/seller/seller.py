"""
OmniClaw Seller SDK - Complete Economic Infrastructure for Sellers.

This provides everything needed to accept payments:
- Multiple endpoint configuration
- Both payment methods (basic x402 + Circle)
- Webhook notifications
- Transaction history

Usage:
    from omniclaw.seller import Seller, create_seller

    seller = create_seller(
        seller_address="0x...",
        name="Weather API",
    )

    # Add protected endpoints
    seller.protect("/weather", "$0.001", "Current weather")
    seller.protect("/forecast", "$0.01", "7-day forecast")

    # Start server
    seller.serve(port=4023)
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

logger = logging.getLogger(__name__)

_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
USDC_DECIMAL_PLACES = 6


def _parse_price_to_decimal(price: str) -> Decimal:
    """Parse price string to Decimal USD amount."""
    cleaned = price.strip().lstrip("$").strip()
    if not cleaned:
        raise ValueError(f"Empty price: {price!r}")
    try:
        val = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"Invalid price: {price!r}") from None
    if val <= 0:
        raise ValueError(f"Price must be positive: {price!r}")
    return val


def _usd_to_atomic(price_usd: Decimal) -> int:
    """Convert USD Decimal to USDC atomic units (6 decimals)."""
    atomic = price_usd * Decimal(10**USDC_DECIMAL_PLACES)
    if atomic != int(atomic):
        raise ValueError(f"Price has too many decimals: {price_usd}")
    return int(atomic)


def _accepted_requirements_match(
    payment_payload: dict[str, Any],
    accepted: dict[str, Any],
) -> tuple[bool, str]:
    """Validate x402 v2 payload.accepted against the server-selected requirement."""
    payload_accepted = payment_payload.get("accepted")
    if int(payment_payload.get("x402Version", 2)) == 2 and not isinstance(
        payload_accepted, dict
    ):
        return False, "Missing accepted requirements in PAYMENT-SIGNATURE payload"
    if not isinstance(payload_accepted, dict):
        return True, ""

    checks = (
        ("scheme", False, False),
        ("network", False, False),
        ("asset", True, True),
        ("amount", False, False),
        ("payTo", True, True),
    )
    for requirement_field, casefold, optional in checks:
        expected = accepted.get(requirement_field)
        actual = payload_accepted.get(requirement_field)
        if optional and (expected is None or actual is None):
            continue
        expected_text = str(expected)
        actual_text = str(actual)
        if casefold:
            expected_text = expected_text.lower()
            actual_text = actual_text.lower()
        if actual_text != expected_text:
            return False, f"Accepted requirements mismatch: {requirement_field}"

    expected_extra = accepted.get("extra") or {}
    actual_extra = payload_accepted.get("extra") or {}
    expected_contract = expected_extra.get("verifyingContract")
    actual_contract = actual_extra.get("verifyingContract")
    if expected_contract and str(actual_contract).lower() != str(expected_contract).lower():
        return False, "Accepted requirements mismatch: verifyingContract"

    return True, ""


# =============================================================================
# TYPES
# =============================================================================


class PaymentScheme(str, Enum):
    """Payment schemes supported."""

    EXACT = "exact"  # Basic x402 (EIP-3009)
    GATEWAY_BATCHED = "GatewayWalletBatched"  # Circle Nanopayment


class PaymentStatus(str, Enum):
    """Payment status."""

    PENDING = "pending"
    VERIFIED = "verified"
    SETTLED = "settled"
    FAILED = "failed"


@dataclass
class PaymentRecord:
    """Record of a payment."""

    id: str
    scheme: str
    buyer_address: str
    seller_address: str
    amount: int
    amount_usd: float
    resource_url: str
    status: PaymentStatus
    created_at: datetime = field(default_factory=datetime.now)
    verified_at: datetime | None = None
    tx_hash: str | None = None


@dataclass
class Endpoint:
    """Protected endpoint configuration."""

    path: str
    price_usd: Decimal
    description: str
    schemes: list[PaymentScheme] = field(
        default_factory=lambda: [PaymentScheme.EXACT, PaymentScheme.GATEWAY_BATCHED]
    )
    requires_guild: str | None = None


@dataclass
class SellerConfig:
    """Seller configuration."""

    seller_address: str
    name: str
    description: str = ""
    network: str = "eip155:84532"  # Base Sepolia
    usdc_contract: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    gateway_contract: str = ""
    webhook_url: str = ""
    webhook_secret: str = ""


# =============================================================================
# CORE SELLER
# =============================================================================


class Seller:
    """
    Complete seller infrastructure for accepting payments.

    Features:
    - Multiple protected endpoints
    - Both payment methods (basic x402 + Circle)
    - Transaction history
    - Webhook notifications
    - Optional Circle Gateway facilitator integration

    Usage:
        seller = Seller(
            seller_address="0x742d...",
            name="My API",
        )

        seller.protect("/weather", "$0.001", "Weather data")
        seller.protect("/premium", "$0.01", "Premium content")

        seller.serve(port=4023)

    With Circle Gateway facilitator:
        from omniclaw.seller.facilitator import create_facilitator

        facilitator = create_facilitator(circle_api_key="...")
        seller = Seller(
            seller_address="0x742d...",
            name="My API",
            facilitator=facilitator,  # Uses Circle Gateway for verify/settle
        )
    """

    def __init__(
        self,
        seller_address: str,
        name: str,
        description: str = "",
        network: str = "eip155:84532",
        usdc_contract: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        webhook_url: str = "",
        webhook_secret: str = "",
        facilitator: Any = None,
    ):
        """
        Initialize seller.

        Args:
            seller_address: EVM address for receiving payments
            name: Seller name
            description: Seller description
            network: CAIP-2 network identifier
            usdc_contract: USDC contract address
            webhook_url: URL for payment notifications
            webhook_secret: Secret for webhook signing
            facilitator: Optional CircleGatewayFacilitator for verify/settle
        """
        self.config = SellerConfig(
            seller_address=seller_address,
            name=name,
            description=description,
            network=network,
            usdc_contract=usdc_contract,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
        )

        self._endpoints: dict[str, Endpoint] = {}
        self._payments: dict[str, PaymentRecord] = {}
        self._used_nonces: dict[tuple[str, str, str, str, str], int] = {}
        self._nonce_lock = asyncio.Lock()
        self._facilitator = facilitator

        self._gateway_contract = os.environ.get("CIRCLE_GATEWAY_CONTRACT", "")
        self._strict_gateway_contract = (
            os.environ.get("OMNICLAW_SELLER_STRICT_GATEWAY_CONTRACT", "false").lower() == "true"
        )
        if not self._gateway_contract:
            logger.warning(
                "CIRCLE_GATEWAY_CONTRACT env var not set. "
                "GatewayWalletBatched scheme will not work until this is configured. "
                "Fetch it from Circle Gateway /v1/x402/supported endpoint."
            )

        self._nonce_redis_client: Any | None = None
        self._nonce_redis_url = os.environ.get("OMNICLAW_SELLER_NONCE_REDIS_URL")
        runtime_env = os.environ.get("OMNICLAW_ENV", "").lower()
        self._is_production_env = runtime_env in {"prod", "production", "mainnet"}
        self._require_distributed_nonce = (
            os.environ.get("OMNICLAW_SELLER_REQUIRE_DISTRIBUTED_NONCE", "false").lower() == "true"
        )
        self._nonce_ttl_floor_seconds = int(
            os.environ.get("OMNICLAW_SELLER_NONCE_TTL_FLOOR_SECONDS", "300")
        )
        if self._nonce_redis_url:
            try:
                import redis.asyncio as redis_asyncio

                self._nonce_redis_client = redis_asyncio.from_url(
                    self._nonce_redis_url,
                    decode_responses=True,
                )
                logger.info("Seller nonce replay protection using Redis backend")
            except Exception as exc:
                if self._require_distributed_nonce:
                    raise RuntimeError(
                        "Distributed nonce protection required but Redis client init failed"
                    ) from exc
                logger.warning(
                    "Redis nonce backend unavailable, falling back to local memory: %s", exc
                )
        elif self._require_distributed_nonce:
            raise RuntimeError(
                "OMNICLAW_SELLER_REQUIRE_DISTRIBUTED_NONCE=true but "
                "OMNICLAW_SELLER_NONCE_REDIS_URL is not set"
            )
        elif self._is_production_env:
            raise RuntimeError(
                "Production seller requires distributed nonce protection. "
                "Set OMNICLAW_SELLER_NONCE_REDIS_URL (or explicitly run non-production env)."
            )

    def protect(
        self,
        path: str,
        price: str,
        description: str = "",
        schemes: list[PaymentScheme] | None = None,
    ) -> Callable:
        """
        Decorator to protect an endpoint.

        Args:
            path: Route path (e.g., "/weather")
            price: Price in USD (e.g., "$0.001")
            description: Endpoint description
            schemes: Payment schemes to accept (default: both)

        Usage:
            @seller.protect("/weather", "$0.001", "Weather data")
            def weather():
                return {"temp": 72}
        """
        price_usd = _parse_price_to_decimal(price)

        # Default to accepting both
        if schemes is None:
            schemes = [PaymentScheme.EXACT, PaymentScheme.GATEWAY_BATCHED]

        endpoint = Endpoint(
            path=path,
            price_usd=price_usd,
            description=description,
            schemes=schemes,
        )

        self._endpoints[path] = endpoint

        def decorator(func: Callable) -> Callable:
            return func

        return decorator

    def add_endpoint(
        self,
        path: str,
        price: str,
        description: str = "",
        schemes: list[PaymentScheme] | None = None,
    ) -> None:
        """
        Add a protected endpoint programmatically.

        Args:
            path: Route path
            price: Price in USD
            description: Description
            schemes: Payment schemes
        """
        price_usd = _parse_price_to_decimal(price)

        if schemes is None:
            schemes = [PaymentScheme.EXACT, PaymentScheme.GATEWAY_BATCHED]

        if (
            self._strict_gateway_contract
            and PaymentScheme.GATEWAY_BATCHED in schemes
            and not self._gateway_contract
        ):
            raise ValueError(
                "GatewayWalletBatched configured but CIRCLE_GATEWAY_CONTRACT is not set. "
                "Set CIRCLE_GATEWAY_CONTRACT or disable GatewayWalletBatched for this endpoint."
            )

        self._endpoints[path] = Endpoint(
            path=path,
            price_usd=price_usd,
            description=description,
            schemes=schemes,
        )

    def _create_accepts(self, endpoint: Endpoint) -> list[dict]:
        """Create accepts array for an endpoint."""
        amount_atomic = _usd_to_atomic(endpoint.price_usd)
        accepts = []

        for scheme in endpoint.schemes:
            if scheme == PaymentScheme.EXACT:
                accepts.append(
                    {
                        "scheme": "exact",
                        "network": self.config.network,
                        "asset": self.config.usdc_contract,
                        "amount": str(amount_atomic),
                        "payTo": self.config.seller_address,
                        "maxTimeoutSeconds": 345600,
                    }
                )
            elif scheme == PaymentScheme.GATEWAY_BATCHED:
                if not self._gateway_contract:
                    logger.warning(
                        f"Skipping GatewayWalletBatched for {endpoint.path}: "
                        f"CIRCLE_GATEWAY_CONTRACT not configured."
                    )
                    continue
                accepts.append(
                    {
                        "scheme": "exact",
                        "network": self.config.network,
                        "asset": self.config.usdc_contract,
                        "amount": str(amount_atomic),
                        "payTo": self.config.seller_address,
                        "maxTimeoutSeconds": 345600,
                        "extra": {
                            "name": "GatewayWalletBatched",
                            "version": "1",
                            "verifyingContract": self._gateway_contract,
                        },
                    }
                )

        return accepts

    async def _check_and_mark_nonce(
        self,
        *,
        network: str,
        payer: str,
        nonce: str,
        valid_before: int,
        verifying_contract: str = "",
        pay_to: str = "",
    ) -> bool:
        """Atomically mark nonce usage; returns False when nonce is already used."""
        now = int(time.time())
        ttl = max(
            (valid_before - now) + self._nonce_ttl_floor_seconds, self._nonce_ttl_floor_seconds
        )
        replay_scope = (
            str(network).lower(),
            str(verifying_contract).lower(),
            str(pay_to).lower(),
            str(payer).lower(),
            str(nonce),
        )

        if self._nonce_redis_client is not None:
            key = "omniclaw:seller:nonce:" + ":".join(replay_scope)
            result = await self._nonce_redis_client.set(key, "1", ex=ttl, nx=True)
            return bool(result)

        async with self._nonce_lock:
            self._prune_local_nonces(now)
            nonce_key = replay_scope
            expiry = self._used_nonces.get(nonce_key)
            if expiry is not None and expiry > now:
                return False
            self._used_nonces[nonce_key] = now + ttl
            return True

    def _prune_local_nonces(self, now: int | None = None) -> None:
        """Drop expired in-memory nonce markers."""
        current = now or int(time.time())
        expired = [key for key, expiry in self._used_nonces.items() if expiry <= current]
        for key in expired:
            del self._used_nonces[key]

    def _check_and_mark_nonce_sync(
        self,
        *,
        network: str,
        payer: str,
        nonce: str,
        valid_before: int,
        verifying_contract: str = "",
        pay_to: str = "",
    ) -> tuple[bool, str]:
        """Sync helper for nonce marking; rejects usage from running event loops."""
        try:
            asyncio.get_running_loop()
            return False, "Sync verify called from async loop; use verify_payment_async()"
        except RuntimeError:
            pass

        try:
            marked = asyncio.run(
                self._check_and_mark_nonce(
                    network=network,
                    payer=payer,
                    nonce=nonce,
                    valid_before=valid_before,
                    verifying_contract=verifying_contract,
                    pay_to=pay_to,
                )
            )
            if not marked:
                return False, "Nonce already used"
            return True, ""
        except Exception as exc:
            return False, f"Nonce replay protection error: {exc}"

    def create_402_response(self, path: str, url: str) -> tuple[dict, str]:
        """Create 402 response for a path."""
        endpoint = self._endpoints.get(path)

        if not endpoint:
            return {}, "Endpoint not found"

        payment_required = {
            "x402Version": 2,
            "error": "Payment required",
            "resource": {
                "url": url,
                "description": endpoint.description or f"Access to {path}",
                "mimeType": "application/json",
            },
            "accepts": self._create_accepts(endpoint),
        }

        header = base64.b64encode(json.dumps(payment_required).encode()).decode()

        return {"payment-required": header}, json.dumps({"error": "Payment required"})

    def verify_payment(
        self,
        payment_payload: dict,
        accepted: dict,
        verify_signature: bool = True,
        settle_payment: bool = False,
    ) -> tuple[bool, str, PaymentRecord | None]:
        """
        Verify a payment.

        Args:
            payment_payload: The payment payload from the request header
            accepted: The accepted payment requirements from 402 response
            verify_signature: Whether to verify EIP-3009 signature (default: True)
            settle_payment: Whether to settle via facilitator (default: False)

        Returns:
            (is_valid, error, payment_record)
        """
        try:
            if settle_payment and not self._facilitator:
                return (
                    False,
                    "Settlement requested but no facilitator is configured",
                    None,
                )

            scheme = payment_payload.get("scheme")
            payment_data = payment_payload.get("payload", {})
            authorization = payment_data.get("authorization", {})
            signature = payment_data.get("signature", "")

            accepted_ok, accepted_error = _accepted_requirements_match(payment_payload, accepted)
            if not accepted_ok:
                return False, accepted_error, None

            # Use Circle Gateway facilitator if available
            if self._facilitator:
                return self._verify_with_facilitator(
                    payment_payload=payment_payload,
                    accepted=accepted,
                    verify_signature=verify_signature,
                    settle_payment=settle_payment,
                )

            is_valid, error = self._validate_payment_fields(
                payment_payload=payment_payload,
                accepted=accepted,
                authorization=authorization,
                verify_signature=verify_signature,
                signature=signature,
            )
            if not is_valid:
                return False, error, None

            # Get buyer address
            buyer_address = authorization.get("from", "").lower()

            # Generate payment ID
            payment_id = hashlib.sha256(f"{buyer_address}{time.time()}".encode()).hexdigest()[:16]

            # Check timeout
            valid_after = int(authorization.get("validAfter", 0))
            valid_before = int(authorization.get("validBefore", 0))
            current = int(time.time())

            if current < valid_after:
                return False, "Payment not yet valid", None
            if current > valid_before:
                return False, "Payment expired", None

            # Check amount
            paid = int(authorization.get("value", "0"))
            required = int(accepted.get("amount", "0"))

            if paid < required:
                return False, f"Insufficient: {paid} < {required}", None

            # Check recipient
            to_address = authorization.get("to", "").lower()
            if to_address != self.config.seller_address.lower():
                return False, "Wrong recipient", None

            nonce = str(authorization.get("nonce", ""))
            network = str(accepted.get("network", self.config.network))
            pay_to = str(accepted.get("payTo", self.config.seller_address))
            verifying_contract = str((accepted.get("extra") or {}).get("verifyingContract", ""))
            if nonce:
                nonce_marked, nonce_error = self._check_and_mark_nonce_sync(
                    network=network,
                    payer=buyer_address,
                    nonce=nonce,
                    valid_before=valid_before,
                    verifying_contract=verifying_contract,
                    pay_to=pay_to,
                )
                if not nonce_marked:
                    return False, nonce_error, None

            # Create payment record
            record = PaymentRecord(
                id=payment_id,
                scheme=scheme,
                buyer_address=buyer_address,
                seller_address=self.config.seller_address,
                amount=paid,
                amount_usd=paid / 1_000_000,
                resource_url=accepted.get("resource", {}).get("url", ""),
                status=PaymentStatus.VERIFIED,
            )

            # Store payment
            self._payments[payment_id] = record

            # Send webhook
            if self.config.webhook_url:
                self._send_webhook(record)

            return True, "", record

        except Exception as e:
            return False, str(e), None

    async def verify_payment_async(
        self,
        payment_payload: dict,
        accepted: dict,
        verify_signature: bool = True,
        settle_payment: bool = False,
    ) -> tuple[bool, str, PaymentRecord | None]:
        """
        Verify a payment (async version for use with asyncio).

        Args:
            payment_payload: The payment payload from the request header
            accepted: The accepted payment requirements from 402 response
            verify_signature: Whether to verify EIP-3009 signature (default: True)
            settle_payment: Whether to settle via facilitator (default: False)

        Returns:
            (is_valid, error, payment_record)
        """
        import hashlib

        try:
            if settle_payment and not self._facilitator:
                return (
                    False,
                    "Settlement requested but no facilitator is configured",
                    None,
                )

            scheme = payment_payload.get("scheme")
            payment_data = payment_payload.get("payload", {})
            authorization = payment_data.get("authorization", {})
            signature = payment_data.get("signature", "")

            accepted_ok, accepted_error = _accepted_requirements_match(payment_payload, accepted)
            if not accepted_ok:
                return False, accepted_error, None

            # Use Circle Gateway facilitator if available
            if self._facilitator:
                payment_requirements = {
                    "scheme": accepted.get("scheme", "exact"),
                    "network": accepted.get("network", self.config.network),
                    "asset": accepted.get("asset", self.config.usdc_contract),
                    "amount": accepted.get("amount", "0"),
                    "payTo": accepted.get("payTo", self.config.seller_address),
                    "maxTimeoutSeconds": accepted.get("maxTimeoutSeconds", 345600),
                    "extra": accepted.get("extra", {}),
                }

                # Call facilitator directly (async)
                if settle_payment:
                    result = await self._facilitator.settle(payment_payload, payment_requirements)
                    status = PaymentStatus.SETTLED if result.success else PaymentStatus.FAILED

                    if not result.success:
                        return False, f"Settlement failed: {result.error_reason}", None

                    buyer_address = result.payer or ""

                else:
                    result = await self._facilitator.verify(payment_payload, payment_requirements)

                    if not result.is_valid:
                        return False, f"Verification failed: {result.invalid_reason}", None

                    buyer_address = result.payer or ""
                    status = PaymentStatus.VERIFIED

                nonce = str(authorization.get("nonce", ""))
                valid_before = int(authorization.get("validBefore", 0))
                network = str(accepted.get("network", self.config.network))
                pay_to = str(accepted.get("payTo", self.config.seller_address))
                verifying_contract = str((accepted.get("extra") or {}).get("verifyingContract", ""))
                if nonce:
                    nonce_marked = await self._check_and_mark_nonce(
                        network=network,
                        payer=buyer_address.lower(),
                        nonce=nonce,
                        valid_before=valid_before,
                        verifying_contract=verifying_contract,
                        pay_to=pay_to,
                    )
                    if not nonce_marked:
                        return False, "Nonce already used", None

                payment_id = hashlib.sha256(f"{buyer_address}{time.time()}".encode()).hexdigest()[
                    :16
                ]
                paid = int(payment_requirements["amount"])

                record = PaymentRecord(
                    id=payment_id,
                    scheme=scheme or "exact",
                    buyer_address=buyer_address.lower(),
                    seller_address=self.config.seller_address,
                    amount=paid,
                    amount_usd=paid / 1_000_000,
                    resource_url=accepted.get("resource", {}).get("url", ""),
                    status=status,
                )

                self._payments[payment_id] = record

                if self.config.webhook_url:
                    self._send_webhook(record)

                return True, "", record

            # Non-facilitator path (local verification)
            is_valid, error = self._validate_payment_fields(
                payment_payload=payment_payload,
                accepted=accepted,
                authorization=authorization,
                verify_signature=verify_signature,
                signature=signature,
            )
            if not is_valid:
                return False, error, None

            buyer_address = authorization.get("from", "").lower()
            payment_id = hashlib.sha256(f"{buyer_address}{time.time()}".encode()).hexdigest()[:16]

            valid_after = int(authorization.get("validAfter", 0))
            valid_before = int(authorization.get("validBefore", 0))
            current = int(time.time())

            if current < valid_after:
                return False, "Payment not yet valid", None
            if current > valid_before:
                return False, "Payment expired", None

            paid = int(authorization.get("value", "0"))
            required = int(accepted.get("amount", "0"))

            if paid < required:
                return False, f"Insufficient: {paid} < {required}", None

            to_address = authorization.get("to", "").lower()
            if to_address != self.config.seller_address.lower():
                return False, "Wrong recipient", None

            nonce = str(authorization.get("nonce", ""))
            valid_before = int(authorization.get("validBefore", 0))
            network = str(accepted.get("network", self.config.network))
            pay_to = str(accepted.get("payTo", self.config.seller_address))
            verifying_contract = str((accepted.get("extra") or {}).get("verifyingContract", ""))
            nonce_marked = await self._check_and_mark_nonce(
                network=network,
                payer=buyer_address,
                nonce=nonce,
                valid_before=valid_before,
                verifying_contract=verifying_contract,
                pay_to=pay_to,
            )
            if not nonce_marked:
                return False, "Nonce already used", None

            record = PaymentRecord(
                id=payment_id,
                scheme=scheme,
                buyer_address=buyer_address,
                seller_address=self.config.seller_address,
                amount=paid,
                amount_usd=paid / 1_000_000,
                resource_url=accepted.get("resource", {}).get("url", ""),
                status=PaymentStatus.VERIFIED,
            )

            self._payments[payment_id] = record
            if self.config.webhook_url:
                self._send_webhook(record)

            return True, "", record

        except Exception as e:
            return False, str(e), None

    def _verify_eip3009_signature(
        self,
        authorization: dict,
        signature: str,
        accepted: dict,
    ) -> tuple[bool, str]:
        """
        Verify EIP-3009 TransferWithAuthorization signature.

        Args:
            authorization: The authorization dict from payment payload
            signature: The hex-encoded signature
            network: CAIP-2 network identifier
            verifying_contract: The contract address for EIP-712 domain

        Returns:
            (is_valid, error_message)
        """
        try:
            # Parse network to get chain ID
            chain_id = 84532  # Default to Base Sepolia
            network = str(accepted.get("network", self.config.network))
            if ":" in network:
                chain_id = int(network.split(":")[-1])

            extra = accepted.get("extra", {}) or {}
            if extra:
                required_extra_fields = ("name", "version", "verifyingContract")
                missing = [field for field in required_extra_fields if not extra.get(field)]
                if missing:
                    return False, f"Missing required EIP-712 domain fields: {', '.join(missing)}"
                domain_name = str(extra.get("name"))
                domain_version = str(extra.get("version"))
                verifying_contract = str(extra.get("verifyingContract")).strip()
            else:
                domain_name = "USDC"
                domain_version = "2"
                verifying_contract = str(accepted.get("asset", self.config.usdc_contract)).strip()

            if not _EVM_ADDRESS_RE.match(verifying_contract):
                return False, f"Invalid verifyingContract: {verifying_contract}"

            # Build EIP-712 domain
            domain = {
                "name": domain_name,
                "version": domain_version,
                "chainId": chain_id,
                "verifyingContract": verifying_contract,
            }

            # Build EIP-712 message for TransferWithAuthorization
            message = {
                "types": {
                    "EIP712Domain": [
                        {"name": "name", "type": "string"},
                        {"name": "version", "type": "string"},
                        {"name": "chainId", "type": "uint256"},
                        {"name": "verifyingContract", "type": "address"},
                    ],
                    "TransferWithAuthorization": [
                        {"name": "from", "type": "address"},
                        {"name": "to", "type": "address"},
                        {"name": "value", "type": "uint256"},
                        {"name": "validAfter", "type": "uint256"},
                        {"name": "validBefore", "type": "uint256"},
                        {"name": "nonce", "type": "bytes32"},
                    ],
                },
                "primaryType": "TransferWithAuthorization",
                "domain": domain,
                "message": {
                    "from": authorization.get("from"),
                    "to": authorization.get("to"),
                    "value": int(authorization.get("value", 0)),
                    "validAfter": int(authorization.get("validAfter", 0)),
                    "validBefore": int(authorization.get("validBefore", 0)),
                    "nonce": authorization.get("nonce", "0x" + "00" * 32),
                },
            }

            # Recover signer from signature
            signable = encode_typed_data(full_message=message)
            signer = Account.recover_message(signable, signature=signature)
            expected_signer = authorization.get("from", "").lower()

            if signer.lower() != expected_signer:
                return False, f"Signature mismatch: {signer} != {expected_signer}"

            return True, ""

        except Exception as e:
            return False, f"Signature verification error: {str(e)}"

    def _validate_payment_fields(
        self,
        payment_payload: dict[str, Any],
        accepted: dict[str, Any],
        authorization: dict[str, Any],
        verify_signature: bool,
        signature: str,
    ) -> tuple[bool, str]:
        """Validate payload against server-selected accepted requirements."""
        payer = str(authorization.get("from", "")).lower()
        payee = str(authorization.get("to", "")).lower()
        nonce = str(authorization.get("nonce", ""))

        if not _EVM_ADDRESS_RE.match(payer):
            return False, "Invalid payer address"
        if not _EVM_ADDRESS_RE.match(payee):
            return False, "Invalid recipient address"
        if not nonce:
            return False, "Missing nonce"
        expected_scheme = str(accepted.get("scheme", "exact")).lower()
        payload_scheme = str(payment_payload.get("scheme", "exact")).lower()
        if payload_scheme and payload_scheme != expected_scheme:
            return False, f"Scheme mismatch: {payload_scheme} != {expected_scheme}"

        expected_network = str(accepted.get("network", self.config.network))
        payload_network = str(payment_payload.get("network", expected_network))
        if payload_network and payload_network != expected_network:
            return False, f"Network mismatch: {payload_network} != {expected_network}"

        required_payto = str(accepted.get("payTo", self.config.seller_address)).lower()
        if required_payto != self.config.seller_address.lower():
            return False, "Server payTo mismatch"
        if payee != required_payto:
            return False, "Wrong recipient"

        if verify_signature:
            if not signature:
                return False, "Missing signature"
            is_valid_sig, sig_error = self._verify_eip3009_signature(
                authorization=authorization,
                signature=signature,
                accepted=accepted,
            )
            if not is_valid_sig:
                return False, f"Invalid signature: {sig_error}"

        return True, ""

    def _select_accepted_for_payload(
        self, payload: dict[str, Any], path: str
    ) -> dict[str, Any] | None:
        """Pick server-defined accepted requirement matching incoming payload fields."""
        endpoint = self._endpoints.get(path)
        if not endpoint:
            return None
        accepts = self._create_accepts(endpoint)
        if not accepts:
            return None

        payload_accepted = payload.get("accepted")
        if int(payload.get("x402Version", 2)) == 2 and not isinstance(payload_accepted, dict):
            return None
        payload_accepted = payload_accepted or {}
        payload_network = str(payload_accepted.get("network", payload.get("network", "")))
        payload_scheme = str(payload_accepted.get("scheme", payload.get("scheme", "exact"))).lower()
        payload_data = payload.get("payload", {}) or {}
        auth = payload_data.get("authorization", {}) or {}
        payload_value = str(auth.get("value", ""))

        for accepted in accepts:
            if payload_scheme and payload_scheme != str(accepted.get("scheme", "")).lower():
                continue
            if payload_network and payload_network != str(accepted.get("network", "")):
                continue
            if str(payload_accepted.get("asset", accepted.get("asset", ""))).lower() != str(
                accepted.get("asset", "")
            ).lower():
                continue
            if str(payload_accepted.get("payTo", accepted.get("payTo", ""))).lower() != str(
                accepted.get("payTo", "")
            ).lower():
                continue
            accepted_amount = str(accepted.get("amount", "0"))
            if str(payload_accepted.get("amount", accepted_amount)) != accepted_amount:
                continue
            if payload_value and int(payload_value) < int(accepted_amount):
                continue
            return accepted
        return None

    def _verify_with_facilitator(
        self,
        payment_payload: dict,
        accepted: dict,
        verify_signature: bool,
        settle_payment: bool,
    ) -> tuple[bool, str, PaymentRecord | None]:
        """
        Verify and optionally settle payment using Circle Gateway facilitator.

        Args:
            payment_payload: The payment payload from the request header
            accepted: The accepted payment requirements from 402 response
            verify_signature: Whether to verify signature (passed to facilitator)
            settle_payment: Whether to settle via facilitator

        Returns:
            (is_valid, error, payment_record)
        """
        # Build the proper format for facilitator
        payment_requirements = {
            "scheme": accepted.get("scheme", "exact"),
            "network": accepted.get("network", self.config.network),
            "asset": accepted.get("asset", self.config.usdc_contract),
            "amount": accepted.get("amount", "0"),
            "payTo": accepted.get("payTo", self.config.seller_address),
            "maxTimeoutSeconds": accepted.get("maxTimeoutSeconds", 345600),
            "extra": accepted.get("extra", {}),
        }

        # Use asyncio.run() to properly handle async facilitator calls from sync context
        async def _do_verify():
            if settle_payment:
                return await self._facilitator.settle(payment_payload, payment_requirements)
            else:
                return await self._facilitator.verify(payment_payload, payment_requirements)

        try:
            asyncio.get_running_loop()
            return False, "Sync verify called from async loop; use verify_payment_async()", None
        except RuntimeError:
            pass

        try:
            result = asyncio.run(_do_verify())
        except Exception as e:
            return False, f"Facilitator error: {e}", None

        # Process result
        if settle_payment:
            status = PaymentStatus.SETTLED if result.success else PaymentStatus.FAILED

            if not result.success:
                return False, f"Settlement failed: {result.error_reason}", None

            buyer_address = result.payer or ""

        else:
            if not result.is_valid:
                return False, f"Verification failed: {result.invalid_reason}", None

            buyer_address = result.payer or ""

        authorization = (payment_payload.get("payload") or {}).get("authorization") or {}
        nonce = str(authorization.get("nonce", ""))
        valid_before = int(authorization.get("validBefore", 0))
        network = str(accepted.get("network", self.config.network))
        pay_to = str(accepted.get("payTo", self.config.seller_address))
        verifying_contract = str((accepted.get("extra") or {}).get("verifyingContract", ""))
        if nonce:
            nonce_marked, nonce_error = self._check_and_mark_nonce_sync(
                network=network,
                payer=buyer_address.lower(),
                nonce=nonce,
                valid_before=valid_before,
                verifying_contract=verifying_contract,
                pay_to=pay_to,
            )
            if not nonce_marked:
                return False, nonce_error, None

        payment_id = hashlib.sha256(f"{buyer_address}{time.time()}".encode()).hexdigest()[:16]
        paid = int(payment_requirements["amount"])
        status = PaymentStatus.SETTLED if settle_payment else PaymentStatus.VERIFIED

        # Create payment record
        record = PaymentRecord(
            id=payment_id,
            scheme=payment_payload.get("scheme", "exact"),
            buyer_address=buyer_address.lower(),
            seller_address=self.config.seller_address,
            amount=paid,
            amount_usd=paid / 1_000_000,
            resource_url=accepted.get("resource", {}).get("url", ""),
            status=status,
        )

        # Store payment
        self._payments[payment_id] = record

        # Send webhook
        if self.config.webhook_url:
            self._send_webhook(record)

        return True, "", record

    def _send_webhook(self, record: PaymentRecord) -> None:
        """Send webhook notification for payment."""
        if not self.config.webhook_url:
            return

        payload = {
            "event": "payment.received",
            "payment": {
                "id": record.id,
                "scheme": record.scheme,
                "buyer": record.buyer_address,
                "amount": str(record.amount),
                "amount_usd": str(record.amount_usd),
                "status": record.status.value,
                "timestamp": record.created_at.isoformat(),
            },
        }

        # Sign payload
        if self.config.webhook_secret:
            import hmac

            signature = hmac.new(
                self.config.webhook_secret.encode(), json.dumps(payload).encode(), "sha256"
            ).hexdigest()
            headers = {"X-Signature": signature}
        else:
            headers = {}

        try:
            httpx.post(
                self.config.webhook_url,
                json=payload,
                headers=headers,
                timeout=5.0,
            )
        except Exception as e:
            print(f"Webhook failed: {e}")

    def _build_payment_response_header(
        self,
        *,
        success: bool,
        payer: str,
        transaction: str = "",
        error_reason: str | None = None,
    ) -> str:
        """Build base64-encoded PAYMENT-RESPONSE header payload."""
        body: dict[str, Any] = {
            "success": success,
            "transaction": transaction,
            "network": self.config.network,
            "payer": payer,
        }
        if error_reason:
            body["errorReason"] = error_reason
        return base64.b64encode(json.dumps(body).encode()).decode()

    def get_payment(self, payment_id: str) -> PaymentRecord | None:
        """Get payment by ID."""
        return self._payments.get(payment_id)

    def list_payments(
        self,
        buyer_address: str | None = None,
        status: PaymentStatus | None = None,
        limit: int = 100,
    ) -> list[PaymentRecord]:
        """List payments with optional filters."""
        payments = list(self._payments.values())

        if buyer_address:
            payments = [p for p in payments if p.buyer_address == buyer_address.lower()]

        if status:
            payments = [p for p in payments if p.status == status]

        return payments[-limit:]

    def get_earnings(self) -> dict:
        """Get total earnings."""
        total = sum(
            p.amount_usd for p in self._payments.values() if p.status == PaymentStatus.VERIFIED
        )
        count = len([p for p in self._payments.values() if p.status == PaymentStatus.VERIFIED])

        return {
            "total_usd": total,
            "count": count,
            "by_scheme": {
                "exact": sum(
                    p.amount_usd
                    for p in self._payments.values()
                    if p.scheme == "exact" and p.status == PaymentStatus.VERIFIED
                ),
                "gateway_batched": sum(
                    p.amount_usd
                    for p in self._payments.values()
                    if p.scheme == "GatewayWalletBatched" and p.status == PaymentStatus.VERIFIED
                ),
            },
        }

    def get_endpoints(self) -> dict[str, Endpoint]:
        """Get all protected endpoints."""
        return self._endpoints

    def serve(self, port: int = 4023, host: str = "0.0.0.0") -> None:
        """
        Start the seller server.

        Args:
            port: Port to listen on
            host: Host to bind to
        """
        try:
            import uvicorn
            from fastapi import FastAPI, Request
            from fastapi.responses import JSONResponse
        except ImportError:
            print("FastAPI required: pip install fastapi uvicorn")
            return

        app = FastAPI(
            title=f"OmniClaw Seller: {self.config.name}",
            description=self.config.description,
        )

        # Add endpoints
        for path, _endpoint in self._endpoints.items():
            methods = ["GET"]

            # Create route handler
            async def handler(request: Request, path=path):
                payment = request.headers.get("payment-signature")

                if not payment:
                    # Return 402
                    headers, body = self.create_402_response(path, str(request.url))
                    return JSONResponse(
                        status_code=402,
                        content=json.loads(body),
                        headers=headers,
                    )

                # Verify payment
                try:
                    payload = json.loads(base64.b64decode(payment))
                    payer = str(
                        (((payload.get("payload") or {}).get("authorization") or {}).get("from"))
                        or ""
                    ).lower()
                    accepted = self._select_accepted_for_payload(payload, path)
                    if not accepted:
                        headers, body = self.create_402_response(path, str(request.url))
                        headers["PAYMENT-RESPONSE"] = self._build_payment_response_header(
                            success=False,
                            payer=payer,
                            error_reason="no_matching_payment_requirement",
                        )
                        body = json.dumps(
                            {"error": "No server-accepted payment kind matched payload"}
                        )
                        return JSONResponse(
                            status_code=402,
                            content=json.loads(body),
                            headers=headers,
                        )

                    is_valid, error, record = await self.verify_payment_async(
                        payload,
                        accepted,
                        settle_payment=True,
                    )

                    if not is_valid:
                        headers, body = self.create_402_response(path, str(request.url))
                        headers["PAYMENT-RESPONSE"] = self._build_payment_response_header(
                            success=False,
                            payer=payer,
                            error_reason=error or "verification_failed",
                        )
                        body = json.dumps({"error": error})
                        return JSONResponse(
                            status_code=402,
                            content=json.loads(body),
                            headers=headers,
                        )

                    # Payment valid - return data
                    success_headers = {
                        "PAYMENT-RESPONSE": self._build_payment_response_header(
                            success=True,
                            payer=payer,
                            transaction=record.id if record else "",
                        )
                    }
                    return JSONResponse(
                        status_code=200,
                        content={"status": "ok", "payment_id": record.id if record else None},
                        headers=success_headers,
                    )

                except Exception as e:
                    headers, body = self.create_402_response(path, str(request.url))
                    headers["PAYMENT-RESPONSE"] = self._build_payment_response_header(
                        success=False,
                        payer="",
                        error_reason="payload_parse_error",
                    )
                    return JSONResponse(
                        status_code=402,
                        content={"error": str(e)},
                        headers=headers,
                    )

            # Add route
            app.add_api_route(path, handler, methods=methods)

        # Management endpoints
        @app.get("/_/health")
        async def health():
            return {
                "status": "ok",
                "seller": self.config.name,
                "endpoints": len(self._endpoints),
                "payments": len(self._payments),
                "earnings": self.get_earnings(),
            }

        @app.get("/_/payments")
        async def list_payments(limit: int = 100):
            return {"payments": self.list_payments(limit=limit)}

        print(f"\n🏪 OmniClaw Seller: {self.config.name}")
        print(f"   Address: {self.config.seller_address}")
        print(f"   Endpoints: {len(self._endpoints)}")
        for path, ep in self._endpoints.items():
            schemes = [s.value for s in ep.schemes]
            print(f"   - {path}: ${ep.price_usd} ({', '.join(schemes)})")
        print(f"\n   Running on http://{host}:{port}")

        uvicorn.run(app, host=host, port=port)


# =============================================================================
# FACTORY FUNCTION
# =============================================================================


def create_seller(
    seller_address: str,
    name: str,
    description: str = "",
    network: str = "eip155:84532",
    webhook_url: str = "",
    webhook_secret: str = "",
    facilitator: Any = None,
    circle_api_key: str | None = None,
    facilitator_environment: str = "testnet",
) -> Seller:
    """
    Create a new seller.

    Args:
        seller_address: EVM address for payments
        name: Seller name
        description: Seller description
        network: CAIP-2 network
        webhook_url: Webhook URL for notifications
        webhook_secret: Webhook secret for signing
        facilitator: Optional CircleGatewayFacilitator instance
        circle_api_key: If provided (and no facilitator), creates facilitator automatically
        facilitator_environment: Environment for auto-created facilitator ('testnet' or 'mainnet')

    Returns:
        Seller instance
    """
    # Auto-create facilitator if API key provided but no facilitator
    if facilitator is None and circle_api_key:
        from omniclaw.seller.facilitator import create_facilitator

        facilitator = create_facilitator(
            circle_api_key=circle_api_key,
            environment=facilitator_environment,
        )

    return Seller(
        seller_address=seller_address,
        name=name,
        description=description,
        network=network,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        facilitator=facilitator,
    )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "Seller",
    "create_seller",
    "PaymentScheme",
    "PaymentStatus",
    "PaymentRecord",
    "Endpoint",
    "SellerConfig",
]
