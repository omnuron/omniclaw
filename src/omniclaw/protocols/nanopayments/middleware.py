"""
GatewayMiddleware: Seller-side x402 payment gate for FastAPI/Starlette.

The Python equivalent of Circle's createGatewayMiddleware().
Sellers use this to protect their endpoints with x402 payments.

Usage:
    @app.get("/premium")
    async def premium(payment=Depends(gateway.require("$0.001"))):
        return {"data": "paid content", "paid_by": payment.payer}

The 402 response structure (x402 v2):
    {
        "x402Version": 2,
        "accepts": [{
            "scheme": "exact",
            "network": "eip155:5042002",
            "asset": "0xUSDC",
            "amount": "1000",  # atomic units
            "maxTimeoutSeconds": 345600,
            "payTo": "0xSeller",
            "extra": {
                "name": "GatewayWalletBatched",
                "version": "1",
                "verifyingContract": "0xGateway"
            }
        }]
    }
"""

from __future__ import annotations

import base64
import inspect
import json
from dataclasses import dataclass
from typing import Any

from omniclaw.protocols.nanopayments import (
    MAX_TIMEOUT_SECONDS,
    X402_VERSION,
)
from omniclaw.protocols.nanopayments.client import NanopaymentClient
from omniclaw.protocols.nanopayments.exceptions import (
    InvalidPriceError,
    NoNetworksAvailableError,
)
from omniclaw.protocols.nanopayments.types import (
    PaymentInfo,
    PaymentPayload,
    PaymentRequirements,
    SupportedKind,
)

# =============================================================================
# SETTLEMENT RESPONSE (x402 v2 PAYMENT-RESPONSE header format)
# =============================================================================


@dataclass
class SettlementResponse:
    """
    x402 v2 SettlementResponse format for PAYMENT-RESPONSE header.

    Per x402 v2 spec, this header is required on ALL responses (success AND failure)
    from paid endpoints. The header is base64-encoded JSON with:
        {success, transaction, network, payer, errorReason?}
    """

    success: bool
    transaction: str
    network: str
    payer: str
    error_reason: str | None = None

    def to_base64_header(self) -> str:
        """Encode as base64 for the PAYMENT-RESPONSE header."""
        return base64.b64encode(json.dumps(self.to_dict()).encode()).decode()

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        d = {
            "success": self.success,
            "transaction": self.transaction,
            "network": self.network,
            "payer": self.payer,
        }
        if self.error_reason:
            d["errorReason"] = self.error_reason
        return d


# =============================================================================
# PRICE PARSING
# =============================================================================


def parse_price(price_str: str) -> int:
    """
    Parse a price string to USDC atomic units (6 decimals).

    Accepts:
        "$0.001" -> 1000
        "0.001"  -> 1000
        "$1"     -> 1000000
        "1000000" -> 1000000 (atomic)
        "1000"   -> 1000000 (dollars)

    Returns:
        Amount in USDC atomic units (int).

    Raises:
        InvalidPriceError: If the price string cannot be parsed.
    """
    if not price_str:
        raise InvalidPriceError(price=price_str)

    original = price_str.strip()

    # Remove dollar sign
    numeric = original[1:].strip() if original.startswith("$") else original

    # Check if it's a decimal (has a decimal point)
    if "." in numeric:
        # It's a dollar amount with decimals — convert to atomic
        try:
            from decimal import Decimal, InvalidOperation

            value = Decimal(numeric)
            return int(value * Decimal(1_000_000))
        except (ValueError, InvalidOperation, ArithmeticError):
            raise InvalidPriceError(price=price_str) from None

    # It's a plain integer — treat as atomic units if >= 1M,
    # otherwise as whole dollars multiplied by 1M
    try:
        value = int(numeric)
    except ValueError:
        raise InvalidPriceError(price=price_str) from None

    if value >= 1_000_000:
        return value
    return value * 1_000_000


# =============================================================================
# GATEWAY MIDDLEWARE
# =============================================================================


class GatewayMiddleware:
    """
    FastAPI/Starlette middleware for x402 payment gating.

    Sellers use this to protect their endpoints.
    When a buyer requests without payment: returns 402.
    When a buyer requests with valid payment: settles and serves content.

    Args:
        seller_address: EOA address that receives payments.
        nanopayment_client: NanopaymentClient for fetching supported networks.
        supported_kinds: Pre-fetched supported payment kinds. If None, fetches automatically.
        auto_fetch_networks: If True, fetches networks on first request if not provided.
        facilitator: Optional custom facilitator. If None, uses nanopayment_client (Circle).
    """

    def __init__(
        self,
        seller_address: str,
        nanopayment_client: NanopaymentClient,
        supported_kinds: list[SupportedKind] | None = None,
        auto_fetch_networks: bool = True,
        facilitator: Any = None,
    ) -> None:
        # Validate seller_address is a valid EVM address
        if not seller_address:
            raise ValueError("seller_address is required")
        if not seller_address.startswith("0x"):
            raise ValueError("seller_address must be an EVM address (starts with 0x)")
        if len(seller_address) != 42:
            raise ValueError(
                f"seller_address must be 42 characters (42 hex chars), got {len(seller_address)}"
            )
        # Validate hex characters
        try:
            int(seller_address[2:], 16)
        except ValueError:
            raise ValueError("seller_address contains invalid hex characters") from None

        self._seller_address = seller_address.lower()  # Normalize to lowercase
        self._client = nanopayment_client
        self._supported_kinds: list[SupportedKind] | None = supported_kinds
        self._auto_fetch = auto_fetch_networks
        self._facilitator = facilitator
        self._facilitator_name = facilitator.name if facilitator else "circle"

    def _uses_gateway_batched_scheme(self) -> bool:
        """Return True when this middleware should advertise Circle's GatewayWalletBatched."""
        return not self._facilitator or str(self._facilitator_name).lower() == "circle"

    # -------------------------------------------------------------------------
    # Supported networks management
    # -------------------------------------------------------------------------

    async def _get_supported_kinds(self) -> list[SupportedKind]:
        """Get supported payment kinds, fetching if needed."""
        if self._supported_kinds is not None:
            return self._supported_kinds

        # If using custom facilitator (not Circle), try to get from facilitator
        if self._facilitator:
            try:
                facilitator_networks = await self._facilitator.get_supported_networks()
                # Convert facilitator networks to SupportedKind format
                supported = []
                for net in facilitator_networks:
                    network = net.get("network") or net.get("chainId")
                    if network:
                        supported.append(
                            SupportedKind(
                                x402_version=2,
                                scheme="exact",
                                network=network,
                                extra={
                                    "verifyingContract": net.get("verifyingContract", "0x"),
                                    "usdcAddress": net.get(
                                        "usdcAddress", "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
                                    ),
                                },
                            )
                        )
                if supported:
                    self._supported_kinds = supported
                    return self._supported_kinds
            except Exception:
                pass

        # Fallback: use default networks for non-Circle facilitators
        if self._facilitator and not self._supported_kinds:
            # Use Base Sepolia and Ethereum as defaults for other facilitators
            self._supported_kinds = [
                SupportedKind(
                    x402_version=2,
                    scheme="exact",
                    network="eip155:84532",  # Base Sepolia
                    extra={
                        "verifyingContract": "0xfab807B4563D2292a72a3e53F5CcF5E3B7eD86d4",
                        "usdcAddress": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                    },
                ),
                SupportedKind(
                    x402_version=2,
                    scheme="exact",
                    network="eip155:1",  # Ethereum Mainnet
                    extra={
                        "verifyingContract": "0x097707E2b3cD7C6D6fC8E2D3B5F5cC5E7F7E7E7E7",
                        "usdcAddress": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                    },
                ),
            ]
            return self._supported_kinds

        # Use Circle client
        if self._client:
            self._supported_kinds = await self._client.get_supported(force_refresh=True)
            if not self._supported_kinds:
                raise NoNetworksAvailableError()
            return self._supported_kinds

        return []

    # -------------------------------------------------------------------------
    # Accepts array builder
    # -------------------------------------------------------------------------

    def _build_accepts_array(
        self,
        price_atomic: int,
        kinds: list[SupportedKind] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the accepts array for a 402 response.

        Args:
            price_atomic: Price in USDC atomic units.
            kinds: Optional pre-fetched kinds. If None, fetches synchronously.

        For each supported network, creates an entry with:
        - scheme: "exact"
        - network: CAIP-2
        - asset: USDC address
        - amount: price in atomic units
        - maxTimeoutSeconds: 345600 (4 days)
        - payTo: seller address
        - extra: GatewayWalletBatched metadata
        """
        if kinds is None:
            kinds = self._supported_kinds
        if kinds is None:
            return []  # No networks available

        accepts = []
        use_gateway_batched = self._uses_gateway_batched_scheme()
        for kind in kinds:
            verifying_contract = kind.verifying_contract
            usdc_address = kind.usdc_address

            if not usdc_address:
                continue

            accept: dict[str, Any] = {
                "scheme": "exact",
                "network": kind.network,
                "asset": usdc_address,
                "amount": str(price_atomic),
                "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
                "payTo": self._seller_address,
            }
            if use_gateway_batched:
                if not verifying_contract:
                    continue
                accept["extra"] = {
                    "name": "GatewayWalletBatched",
                    "version": "1",
                    "verifyingContract": verifying_contract,
                }
            accepts.append(accept)

        return accepts

    # -------------------------------------------------------------------------
    # 402 response builder
    # -------------------------------------------------------------------------

    async def _build_402_response(
        self,
        price_usd: str,
        *,
        resource_url: str = "",
        method: str = "GET",
    ) -> dict[str, Any]:
        """
        Build the x402 v2 402 response body.

        Returns:
            Dict with x402Version and accepts array.
        """
        price_atomic = parse_price(price_usd)

        create_accepts = getattr(self._facilitator, "create_accepts", None)
        if self._facilitator and inspect.iscoroutinefunction(create_accepts):
            accepts = await create_accepts(
                resource_url=resource_url,
                method=method,
                price=price_usd,
                server_wallet_address=self._seller_address,
            )
            return {
                "x402Version": X402_VERSION,
                "accepts": accepts,
            }

        # Get supported kinds - handle both Circle and other facilitators
        kinds = None
        if self._supported_kinds is None and self._facilitator:
            # Try to get from facilitator
            kinds = await self._get_supported_kinds()
        elif self._supported_kinds:
            kinds = self._supported_kinds
        elif self._client:
            # Try to get from Circle client
            kinds = await self._get_supported_kinds()

        accepts = self._build_accepts_array(price_atomic, kinds)

        return {
            "x402Version": X402_VERSION,
            "accepts": accepts,
        }

    # -------------------------------------------------------------------------
    # Payment handling
    # -------------------------------------------------------------------------

    def _parse_payment_signature(
        self,
        header_value: str,
    ) -> PaymentPayload:
        """
        Parse and validate the PAYMENT-SIGNATURE header.

        Args:
            header_value: The base64-encoded JSON PaymentPayload.

        Returns:
            Parsed PaymentPayload.

        Raises:
            ValueError: If parsing fails.
        """
        try:
            decoded = base64.b64decode(header_value)
            data = json.loads(decoded)
            if int(data.get("x402Version", X402_VERSION)) == X402_VERSION and not data.get(
                "accepted"
            ):
                raise ValueError("Missing accepted requirements in PAYMENT-SIGNATURE payload")
            return PaymentPayload.from_dict(data)
        except Exception as exc:
            raise ValueError(f"Failed to parse PAYMENT-SIGNATURE: {exc}") from exc

    def _encode_requirements(
        self,
        body: dict[str, Any],
    ) -> str:
        """Encode requirements dict as base64 for the PAYMENT-REQUIRED header."""
        return base64.b64encode(json.dumps(body).encode()).decode()

    # -------------------------------------------------------------------------
    # Public handler
    # -------------------------------------------------------------------------

    async def handle(
        self,
        request_headers: dict[str, str],
        price_usd: str,
        *,
        resource_url: str = "",
        method: str = "GET",
    ) -> PaymentInfo:
        """
        Handle payment for a request.

        Checks for PAYMENT-SIGNATURE header. If present, verifies and settles.
        If absent, raises HTTPException(402).

        Args:
            request_headers: Request headers dict.
            price_usd: Price in USD string (e.g. "$0.001").

        Returns:
            PaymentInfo if payment verified and settled.

        Raises:
            HTTPException(402): If payment is missing or invalid.
                The detail dict contains the requirements for payment.
        """
        # Check for PAYMENT-SIGNATURE header
        sig_header = request_headers.get("payment-signature") or request_headers.get(
            "PAYMENT-SIGNATURE"
        )

        if not sig_header:
            # Build 402 response
            body = await self._build_402_response(
                price_usd,
                resource_url=resource_url,
                method=method,
            )
            header_value = self._encode_requirements(body)
            raise PaymentRequiredHTTPError(
                status_code=402,
                detail=body,
                headers={"PAYMENT-REQUIRED": header_value},
            )

        # Parse and verify payment
        try:
            payload = self._parse_payment_signature(sig_header)
        except ValueError as exc:
            raise PaymentRequiredHTTPError(
                status_code=402,
                detail={"error": str(exc)},
                headers={},
            ) from None

        # Build requirements from the payment payload.
        # Circle Gateway uses GatewayWalletBatched metadata; external facilitators use standard exact.
        gateway_kind = None
        facilitator_requirements: dict[str, Any] | None = None
        if payload.payload.authorization:
            auth = payload.payload.authorization
            expected_amount = str(parse_price(price_usd))
            if str(auth.value) != expected_amount:
                raise PaymentRequiredHTTPError(
                    status_code=402,
                    detail={
                        "error": (
                            f"Amount mismatch. Expected {expected_amount} atomic units, "
                            f"got {auth.value}."
                        )
                    },
                    headers={},
                )
            accepted = payload.accepted.to_dict() if payload.accepted else None
            if not accepted:
                raise PaymentRequiredHTTPError(
                    status_code=402,
                    detail={"error": "Missing accepted requirements in PAYMENT-SIGNATURE payload"},
                    headers={},
                )
            if str(accepted.get("network", "")) != payload.network:
                raise PaymentRequiredHTTPError(
                    status_code=402,
                    detail={"error": "Accepted requirements network does not match payload"},
                    headers={},
                )
            if str(accepted.get("amount", "")) != expected_amount:
                raise PaymentRequiredHTTPError(
                    status_code=402,
                    detail={"error": "Accepted requirements amount does not match price"},
                    headers={},
                )
            if str(accepted.get("payTo", "")).lower() != self._seller_address.lower():
                raise PaymentRequiredHTTPError(
                    status_code=402,
                    detail={"error": "Accepted requirements payTo does not match seller"},
                    headers={},
                )
            # Build requirements from payload
            from omniclaw.protocols.nanopayments.types import (
                PaymentRequirementsExtra,
                PaymentRequirementsKind,
            )

            # Get supported kinds and find matching network
            supported_kinds = await self._get_supported_kinds()

            # Find the kind matching the payment's network
            matching_kind = None
            verifying_contract = None
            usdc_address = None

            for kind in supported_kinds:
                if kind.network == payload.network:
                    matching_kind = kind
                    verifying_contract = kind.verifying_contract
                    usdc_address = kind.usdc_address
                    break

            # If no supported kinds at all, we can't process this payment
            if not supported_kinds:
                raise PaymentRequiredHTTPError(
                    status_code=502,
                    detail={"error": "No supported payment networks available"},
                    headers={},
                )

            if matching_kind is None:
                raise PaymentRequiredHTTPError(
                    status_code=402,
                    detail={"error": f"Unsupported payment network: {payload.network}"},
                    headers={},
                )

            if not usdc_address:
                raise PaymentRequiredHTTPError(
                    status_code=502,
                    detail={"error": f"Missing contract addresses for network {payload.network}"},
                    headers={},
                )
            if str(accepted.get("asset", "")).lower() != usdc_address.lower():
                raise PaymentRequiredHTTPError(
                    status_code=402,
                    detail={"error": "Accepted requirements asset does not match network"},
                    headers={},
                )

            if self._uses_gateway_batched_scheme():
                if not verifying_contract:
                    raise PaymentRequiredHTTPError(
                        status_code=502,
                        detail={
                            "error": f"Missing verifying contract for network {payload.network}"
                        },
                        headers={},
                    )
                accepted_extra = accepted.get("extra") or {}
                if str(accepted_extra.get("verifyingContract", "")).lower() != (
                    verifying_contract.lower()
                ):
                    raise PaymentRequiredHTTPError(
                        status_code=402,
                        detail={
                            "error": "Accepted requirements verifying contract does not match network"
                        },
                        headers={},
                    )
                gateway_kind = PaymentRequirementsKind(
                    scheme="exact",
                    network=payload.network,
                    asset=usdc_address,
                    amount=auth.value,
                    max_timeout_seconds=MAX_TIMEOUT_SECONDS,
                    pay_to=self._seller_address,
                    extra=PaymentRequirementsExtra(
                        name="GatewayWalletBatched",
                        version="1",
                        verifying_contract=verifying_contract,
                    ),
                )
            else:
                facilitator_requirements = {
                    "x402Version": X402_VERSION,
                    "accepts": [
                        {
                            "scheme": "exact",
                            "network": payload.network,
                            "asset": usdc_address,
                            "amount": auth.value,
                            "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
                            "payTo": self._seller_address,
                        }
                    ],
                }

        if gateway_kind is None and facilitator_requirements is None:
            raise PaymentRequiredHTTPError(
                status_code=402,
                detail={"error": "Missing authorization in PAYMENT-SIGNATURE payload"},
                headers={},
            )

        requirements = None
        if gateway_kind is not None:
            requirements = PaymentRequirements(
                x402_version=X402_VERSION,
                accepts=(gateway_kind,),
            )

        # Settle the payment - use facilitator if provided, otherwise use Circle client
        try:
            if self._facilitator:
                payload_dict = payload.to_dict()
                req_dict = (
                    facilitator_requirements
                    if facilitator_requirements is not None
                    else requirements.to_dict()
                )
                settle_resp = await self._facilitator.settle(payload_dict, req_dict)
                settle_success = settle_resp.success
                settle_payer = settle_resp.payer
                settle_tx = settle_resp.transaction
            else:
                settle_resp = await self._client.settle(
                    payload=payload,
                    requirements=requirements,
                )
                settle_success = settle_resp.success
                settle_payer = settle_resp.payer
                settle_tx = settle_resp.transaction
        except Exception as exc:
            raise PaymentRequiredHTTPError(
                status_code=402,
                detail={"error": f"Settlement failed: {exc}"},
                headers={},
            ) from None

        return PaymentInfo(
            verified=settle_success,
            payer=settle_payer or payload.payload.authorization.from_address,
            amount=payload.payload.authorization.value,
            network=payload.network,
            transaction=settle_tx,
        )

    # -------------------------------------------------------------------------
    # FastAPI dependency
    # -------------------------------------------------------------------------

    def require(self, price: str):
        """
        Returns a FastAPI dependency for route protection.

        Usage:
            @app.get("/premium")
            async def premium(payment=Depends(gateway.require("$0.001"))):
                return {"data": "paid content", "paid_by": payment.payer}

        Note:
            This requires a Request object to be in scope. Use the `handle`
            method directly for more control.

        IMPORTANT: Per x402 v2 spec, you MUST include the PAYMENT-RESPONSE header
        in your response. Use build_payment_response_header() or payment_response_headers()
        to get the header value.
        """
        from fastapi import HTTPException, Request

        async def dependency(request: Request) -> PaymentInfo:
            headers = dict(request.headers)
            try:
                return await self.handle(
                    headers,
                    price,
                    resource_url=str(request.url),
                    method=request.method,
                )
            except PaymentRequiredHTTPError as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=exc.detail,
                    headers=exc.headers,
                ) from None

        return dependency

    # -------------------------------------------------------------------------
    # PAYMENT-RESPONSE header helpers (x402 v2 spec)
    # -------------------------------------------------------------------------

    def build_payment_response_header(self, payment_info: PaymentInfo) -> str:
        """
        Build PAYMENT-RESPONSE header value from PaymentInfo.

        Per x402 v2 spec, this header is required on ALL responses (success AND failure)
        from paid endpoints. The header is base64-encoded JSON.

        Args:
            payment_info: The PaymentInfo returned by handle() or require()

        Returns:
            Base64-encoded JSON string for the PAYMENT-RESPONSE header.
        """
        return SettlementResponse(
            success=payment_info.verified,
            transaction=payment_info.transaction or "",
            network=payment_info.network,
            payer=payment_info.payer,
        ).to_base64_header()

    def payment_response_headers(self, payment_info: PaymentInfo) -> dict[str, str]:
        """
        Get headers dict including PAYMENT-RESPONSE for route handlers.

        Convenience method that returns a dict with the PAYMENT-RESPONSE header
        already set. Merge this with your response headers.

        Usage:
            @app.get("/premium")
            async def premium(payment=Depends(gateway.require("$0.001"))):
                return JSONResponse(
                    {"data": "premium data"},
                    headers=gateway.payment_response_headers(payment)
                )

        Args:
            payment_info: The PaymentInfo returned by handle() or require()

        Returns:
            Dict with "PAYMENT-RESPONSE" key.
        """
        return {"PAYMENT-RESPONSE": self.build_payment_response_header(payment_info)}


# =============================================================================
# HTTP EXCEPTION HELPER
# =============================================================================


class PaymentRequiredHTTPError(Exception):
    """
    Raised internally to trigger a 402 response.

    Not a real HTTPException — caught by the FastAPI dependency wrapper.
    """

    def __init__(
        self,
        status_code: int,
        detail: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.headers = headers
        super().__init__(str(detail))
