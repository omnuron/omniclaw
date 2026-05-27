"""
NanopaymentAdapter: Buyer-side execution engine for Circle Gateway nanopayments.

Handles two payment scenarios:
1. x402 URL: Detects GatewayWalletBatched in 402 response, signs, retries
2. Direct address: Routes micro-payments through Gateway instead of on-chain

Graceful Degradation:
    If no GatewayWalletBatched scheme is found, raises UnsupportedSchemeError
    so OmniClaw's PaymentRouter can fall back to existing x402 (on-chain) flow.

Auto-topup:
    Before each payment, checks Gateway balance and deposits if below threshold.
    This ensures payments don't fail due to insufficient Gateway balance.

Circuit Breaker:
    Tracks consecutive settlement failures. If failures exceed the threshold,
    nanopayments are temporarily disabled (half-open after recovery period).
    This prevents cascading failures when Circle Gateway is degraded.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from omniclaw.core.types import PaymentMethod, PaymentResult, PaymentStatus
from omniclaw.protocols.nanopayments import (
    DEFAULT_GATEWAY_AUTO_TOPUP_AMOUNT,
    DEFAULT_GATEWAY_AUTO_TOPUP_THRESHOLD,
)
from omniclaw.protocols.nanopayments.client import NanopaymentClient
from omniclaw.protocols.nanopayments.exceptions import (
    GatewayAPIError,
    GatewayConnectionError,
    GatewayTimeoutError,
    InsufficientBalanceError,
    NonceReusedError,
    SettlementError,
    UnsupportedNetworkError,
    UnsupportedSchemeError,
)
from omniclaw.protocols.nanopayments.signing import EIP3009Signer
from omniclaw.protocols.nanopayments.types import (
    GatewayBalance,
    NanopaymentResult,
    PaymentPayload,
    PaymentRequirements,
    SettleResponse,
)

if TYPE_CHECKING:
    from omniclaw.protocols.nanopayments.types import (
        PaymentRequirementsKind,
    )
    from omniclaw.protocols.nanopayments.types import (
        ResourceInfo as ResourceInfoType,
    )

logger = logging.getLogger(__name__)

# Success status codes from HTTP responses
_SUCCESS_STATUS_CODES = (200, 201, 202, 204)


def _decimal_to_atomic(amount_decimal: str) -> int:
    """Convert decimal USDC to atomic units."""
    amount = Decimal(amount_decimal)
    scaled = amount * Decimal(1_000_000)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"USDC amount has more than 6 decimal places: {amount_decimal}")
    return int(scaled)


def _atomic_to_decimal(amount_atomic: int | str) -> str:
    """Convert atomic units to decimal USDC string."""
    return str(Decimal(str(amount_atomic)) / Decimal("1000000"))


def _is_success_status(status_code: int) -> bool:
    """Check if HTTP status code indicates success."""
    return status_code in _SUCCESS_STATUS_CODES


def _find_raw_gateway_kind(payment_required: dict[str, Any]) -> dict[str, Any] | None:
    """Return the unmodified Gateway accept object advertised by the seller."""
    accepts = payment_required.get("accepts")
    if not isinstance(accepts, list):
        return None
    for accept in accepts:
        if not isinstance(accept, dict):
            continue
        extra = accept.get("extra")
        if isinstance(extra, dict) and extra.get("name") == "GatewayWalletBatched":
            return dict(accept)
    return None


def _with_gateway_verifying_contract(
    accepted: dict[str, Any],
    verifying_contract: str,
) -> dict[str, Any]:
    """Preserve seller-advertised Gateway metadata while filling the contract if absent."""
    result = dict(accepted)
    extra = dict(result.get("extra") or {})
    if verifying_contract and not extra.get("verifyingContract"):
        extra["verifyingContract"] = verifying_contract
    result["extra"] = extra
    return result


def _gateway_valid_before(accepted: dict[str, Any]) -> int:
    extra = accepted.get("extra") if isinstance(accepted.get("extra"), dict) else {}
    min_validity = _positive_int(extra.get("minValiditySeconds"))
    max_timeout = _positive_int(accepted.get("maxTimeoutSeconds"))
    window = max(min_validity or 0, 345600)
    if min_validity:
        window = min_validity + 60
    if max_timeout:
        window = min(window, max_timeout)
    return int(time.time()) + window


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


# =============================================================================
# CIRCUIT BREAKER
# =============================================================================


class NanopaymentCircuitBreaker:
    """
    Circuit breaker for nanopayment settlement failures.

    Tracks consecutive failures and trips the circuit when the threshold is exceeded.
    The circuit starts CLOSED (normal operation), trips to OPEN (failing fast),
    and after the recovery period, goes HALF-OPEN (trial request).

    Usage:
        cb = NanopaymentCircuitBreaker(failure_threshold=5, recovery_seconds=60)
        if cb.is_available():
            try:
                await settle(...)
                cb.record_success()
            except SettlementError as exc:
                cb.record_failure()
                if cb.is_open():
                    raise CircuitOpenError(...)
        else:
            raise CircuitOpenError(...)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_seconds: float = 60.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._consecutive_failures = 0
        self._last_failure_time: float | None = None
        self._state = "closed"  # closed, open, half_open

    @property
    def state(self) -> str:
        """Current circuit state: 'closed', 'open', or 'half_open'."""
        if self._state == "open" and self._last_failure_time is not None:
            elapsed = time.monotonic() - self._last_failure_time
            # Small epsilon avoids flakiness at exact float boundaries.
            if elapsed + 1e-9 >= self._recovery_seconds:
                self._state = "half_open"
        return self._state

    def is_available(self) -> bool:
        """True if the circuit allows requests (closed or half_open)."""
        return self.state != "open"

    def record_success(self) -> None:
        """Record a successful settlement."""
        if self._state == "half_open":
            logger.info("Nanopayment circuit: half-open request succeeded, closing circuit")
        self._consecutive_failures = 0
        self._state = "closed"
        self._last_failure_time = None

    def record_failure(self) -> None:
        """Record a failed settlement."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()
        if self._consecutive_failures >= self._failure_threshold:
            if self._state != "open":
                logger.warning(
                    f"Nanopayment circuit: tripped open after {self._consecutive_failures} "
                    f"consecutive failures. Recovery in {self._recovery_seconds}s."
                )
            self._state = "open"

    def record_error(self) -> None:
        """
        Record a non-settlement error (HTTP timeout, connection error).
        These don't trip the circuit but do count toward the threshold.
        """
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()
        if self._consecutive_failures >= self._failure_threshold:
            self._state = "open"
            logger.warning(
                f"Nanopayment circuit: tripped open after {self._consecutive_failures} "
                f"consecutive errors. Recovery in {self._recovery_seconds}s."
            )

    def reset(self) -> None:
        """Manually reset the circuit to closed state."""
        self._consecutive_failures = 0
        self._last_failure_time = None
        self._state = "closed"


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and nanopayments are unavailable."""

    def __init__(self, recovery_seconds: float) -> None:
        self.recovery_seconds = recovery_seconds
        super().__init__(
            f"Circuit breaker is open. Nanopayments temporarily unavailable. "
            f"Retry in {recovery_seconds:.0f}s."
        )


class NanopaymentAdapter:
    """
    Buyer-side adapter for Circle Gateway nanopayments.

    Plugs into OmniClaw's PaymentRouter to handle Gateway nanopayments
    when the seller supports them.

    Features:
    - Circuit breaker: Tracks settlement failures and opens circuit when threshold exceeded
    - Retry logic: Retries transient settlement errors with exponential backoff
    - Auto-topup: Automatically deposits when Gateway balance is low
    - Idempotency: Uses EIP-3009 nonce as idempotency key for safe retries

    Args:
        signer: EIP3009Signer for signing payments (from raw private key).
        nanopayment_client: NanopaymentClient for settling payments.
        http_client: Shared httpx.AsyncClient for HTTP requests.
        network: CAIP-2 network identifier.
        auto_topup_enabled: If True, auto-deposit when balance is low.
        auto_topup_threshold: Threshold in USDC decimal (e.g. "1.00").
        auto_topup_amount: Amount to deposit when topping up.
        circuit_breaker: Circuit breaker instance. If None, creates default.
        retry_attempts: Max retry attempts for transient settlement errors.
        retry_base_delay: Base delay in seconds for exponential backoff.
    """

    def __init__(
        self,
        signer: EIP3009Signer,
        nanopayment_client: NanopaymentClient,
        http_client: httpx.AsyncClient,
        network: str = "eip155:5042002",
        auto_topup_enabled: bool = True,
        auto_topup_threshold: str = DEFAULT_GATEWAY_AUTO_TOPUP_THRESHOLD,
        auto_topup_amount: str = DEFAULT_GATEWAY_AUTO_TOPUP_AMOUNT,
        circuit_breaker: NanopaymentCircuitBreaker | None = None,
        retry_attempts: int = 3,
        retry_base_delay: float = 0.5,
        strict_settlement: bool = False,
        rpc_url: str | None = None,
    ) -> None:
        self._signer = signer
        self._network = network
        self._client = nanopayment_client
        self._http = http_client
        self._auto_topup = auto_topup_enabled
        self._topup_threshold = auto_topup_threshold
        self._topup_amount = auto_topup_amount
        self._circuit_breaker = circuit_breaker or NanopaymentCircuitBreaker()
        self._retry_attempts = retry_attempts
        self._retry_base_delay = retry_base_delay
        self._strict_settlement = strict_settlement
        self._rpc_url = rpc_url

    @property
    def address(self) -> str:
        """
        The EOA address derived from the private key.

        This is the address that will be recorded as the payer
        in Circle Gateway's settlement records.
        """
        return self._signer.address

    @property
    def signer(self) -> EIP3009Signer:
        """
        The EIP3009Signer instance for signing payments.

        This is used internally for on-chain operations like deposits.
        """
        return self._signer

    @classmethod
    def from_private_key(
        cls,
        private_key: str,
        nanopayment_client: NanopaymentClient,
        http_client: httpx.AsyncClient,
        network: str = "eip155:5042002",
        **kwargs: Any,
    ) -> NanopaymentAdapter:
        """
        Create adapter from a raw private key.

        Args:
            private_key: Raw EOA private key hex.
            nanopayment_client: Circle Gateway API client.
            http_client: Shared httpx client.
            network: CAIP-2 network (default Arc Testnet).
            **kwargs: Passed to __init__ (e.g. auto_topup_enabled).
        """
        signer = EIP3009Signer(private_key)
        return cls(
            signer=signer,
            nanopayment_client=nanopayment_client,
            http_client=http_client,
            network=network,
            **kwargs,
        )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _get_address(self) -> str:
        """Get payer EOA address from signer."""
        return self._signer.address

    def _sign(
        self,
        requirements: PaymentRequirementsKind,
        resource: ResourceInfoType | None = None,
        amount_atomic: int | None = None,
        valid_before: int | None = None,
    ) -> PaymentPayload:
        """Sign a payment using the EIP-3009 signer."""
        if amount_atomic is None:
            amount_atomic = int(requirements.amount)
        payload = self._signer.sign_transfer_with_authorization(
            requirements=requirements,
            amount_atomic=amount_atomic,
            valid_before=valid_before,
        )
        # Attach resource info if provided
        if resource is not None:
            payload = PaymentPayload(
                x402_version=payload.x402_version,
                scheme=payload.scheme,
                network=payload.network,
                payload=payload.payload,
                resource=resource,
            )
        return payload

    @staticmethod
    def _encode_payment_signature_header(
        payload: PaymentPayload,
        accepted: PaymentRequirementsKind | dict[str, Any],
    ) -> str:
        """
        Encode the x402 v2 payment header sent back to the seller.

        x402 v2 requires the retry payload to include the selected `accepted`
        requirement. Circle settlement also receives this requirement separately,
        but external sellers validate the raw PAYMENT-SIGNATURE header before
        accepting the paid retry.
        """
        payment_payload = payload.to_dict()
        payment_payload["accepted"] = (
            accepted.to_dict() if hasattr(accepted, "to_dict") else dict(accepted)
        )
        return base64.b64encode(json.dumps(payment_payload).encode("utf-8")).decode("ascii")

    @staticmethod
    def _extra_value(gateway_kind: Any, key: str, snake_key: str | None = None) -> Any:
        extra = getattr(gateway_kind, "extra", None) or {}
        if isinstance(extra, dict):
            return extra.get(key) or (extra.get(snake_key) if snake_key else None)
        return getattr(extra, snake_key or key, None)

    @staticmethod
    def _kind_value(gateway_kind: Any, key: str, fallback: str | None = None) -> Any:
        value = getattr(gateway_kind, key, None)
        if value is not None:
            return value
        if fallback:
            return getattr(gateway_kind, fallback, None)
        return None

    async def _gateway_verifying_contract(self, gateway_kind: Any) -> str:
        verifying_contract = self._extra_value(
            gateway_kind,
            "verifyingContract",
            "verifying_contract",
        )
        if verifying_contract:
            return str(verifying_contract)
        network = str(self._kind_value(gateway_kind, "network") or "")
        if self._client.has_api_key:
            return await self._client.get_verifying_contract(network)
        raise GatewayAPIError(
            message=(
                "Seller x402 Gateway requirement did not include extra.verifyingContract, "
                "and CIRCLE_API_KEY is not configured to resolve it from Circle Gateway."
            ),
            status_code=0,
            response_body=None,
        )

    async def get_onchain_available_balance(
        self,
        gateway_kind: Any,
    ) -> GatewayBalance:
        """Read GatewayWalletBatched balance directly from the Gateway contract."""
        verifying_contract = await self._gateway_verifying_contract(gateway_kind)
        available = await self._get_onchain_available_atomic(
            gateway_kind=gateway_kind,
            verifying_contract=verifying_contract,
        )
        formatted = f"{Decimal(available) / Decimal(1_000_000):.6f} USDC"
        return GatewayBalance(
            total=available,
            available=available,
            formatted_total=formatted,
            formatted_available=formatted,
        )

    async def _gateway_available_balance(
        self,
        gateway_kind: Any,
    ) -> GatewayBalance:
        if self._client.has_api_key:
            return await self._client.check_balance(
                address=self._get_address(),
                network=str(self._kind_value(gateway_kind, "network") or ""),
            )
        return await self.get_onchain_available_balance(gateway_kind)

    async def _get_onchain_available_atomic(
        self,
        *,
        gateway_kind: Any,
        verifying_contract: str,
    ) -> int:
        if not self._rpc_url:
            raise GatewayAPIError(
                message=(
                    "OMNICLAW_RPC_URL is required to check x402 Gateway balance without "
                    "CIRCLE_API_KEY."
                ),
                status_code=0,
                response_body=None,
            )
        usdc_address = self._kind_value(gateway_kind, "asset")
        if not usdc_address:
            raise GatewayAPIError(
                message=(
                    "Seller x402 Gateway requirement did not include the USDC asset address; "
                    "cannot check Gateway balance without Circle API metadata."
                ),
                status_code=0,
                response_body=None,
            )
        try:
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(self._rpc_url))
            gateway = w3.eth.contract(
                address=Web3.to_checksum_address(verifying_contract),
                abi=[
                    {
                        "inputs": [
                            {"internalType": "address", "name": "token", "type": "address"},
                            {
                                "internalType": "address",
                                "name": "depositor",
                                "type": "address",
                            },
                        ],
                        "name": "availableBalance",
                        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                        "stateMutability": "view",
                        "type": "function",
                    }
                ],
            )
            return int(
                gateway.functions.availableBalance(
                    Web3.to_checksum_address(usdc_address),
                    Web3.to_checksum_address(self._get_address()),
                ).call()
            )
        except GatewayAPIError:
            raise
        except Exception as exc:
            raise GatewayAPIError(
                message=f"Gateway on-chain balance check failed: {exc}",
                status_code=0,
                response_body=str(exc),
            ) from exc

    # -------------------------------------------------------------------------
    # x402 URL payment
    # -------------------------------------------------------------------------

    async def pay_x402_url(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: bytes | None = None,
    ) -> NanopaymentResult:
        """
        Pay for a URL-based resource via x402 with Gateway batching.

        Flow:
        1. Send initial HTTP request
        2. If not 402, return response directly (free resource)
        3. Parse 402 response (PAYMENT-REQUIRED header + JSON body)
        4. Check for GatewayWalletBatched in accepts array
        5. If not found: raise UnsupportedSchemeError (router falls back)
        6. Get verifying_contract from NanopaymentClient if not in requirements
        7. Auto-topup if balance is low
        8. Call signer to create signed PaymentPayload
        9. Retry request with PAYMENT-SIGNATURE header
        10. Settle payment with Circle Gateway
        11. Return NanopaymentResult

        CRITICAL: If user got content (HTTP 200), payment should succeed even if
        Circle Gateway settlement has transient issues. Only fail if the content
        was NOT delivered to the user.

        Args:
            url: The resource URL to request.
            method: HTTP method (GET, POST, etc.).
            headers: Additional headers for the request.
            body: Request body for POST/PUT methods.


        Returns:
            NanopaymentResult with payment details and response data.

        Raises:
            UnsupportedSchemeError: If GatewayWalletBatched is not supported.
            GatewayAPIError: On HTTP errors.
            SettlementError: On payment settlement failure (only if content not delivered).
        """
        headers = dict(headers) if headers else {}

        # Step 1: Initial request
        try:
            initial_resp = await self._http.request(
                method=method.upper(),
                url=url,
                headers=headers,
                content=body,
            )
        except httpx.TimeoutException as exc:
            raise GatewayAPIError(
                message=f"Request timed out: {url}",
                status_code=0,
                response_body=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise GatewayAPIError(
                message=f"Request failed: {exc}",
                status_code=0,
                response_body=str(exc),
            ) from exc

        # Step 2: Not a payment response
        if initial_resp.status_code != 402:
            return NanopaymentResult(
                success=_is_success_status(initial_resp.status_code),
                payer="",
                seller="",
                transaction="",
                amount_usdc="0",
                amount_atomic="0",
                network="",
                response_data=initial_resp.text if initial_resp.content else None,
                is_nanopayment=False,
            )

        # Step 3: Parse 402 response
        # HTTP headers are case-insensitive per RFC 7230 - check both variants
        payment_required = initial_resp.headers.get("payment-required") or initial_resp.headers.get(
            "PAYMENT-REQUIRED"
        )
        if not payment_required:
            raise GatewayAPIError(
                message="402 response missing PAYMENT-REQUIRED header",
                status_code=402,
                response_body=initial_resp.text,
            )

        try:
            req_bytes = base64.b64decode(payment_required)
            req_data = json.loads(req_bytes)
            requirements = PaymentRequirements.from_dict(req_data)
        except Exception as exc:
            raise GatewayAPIError(
                message=f"Failed to parse PAYMENT-REQUIRED header: {exc}",
                status_code=402,
                response_body=initial_resp.text,
            ) from exc

        # Extract resource info from 402 response body (required by Circle Gateway)
        from omniclaw.protocols.nanopayments.types import ResourceInfo

        resource: ResourceInfo | None = None
        try:
            body_data = json.loads(initial_resp.text) if initial_resp.text else {}
            resource_data = body_data.get("resource")
            if resource_data:
                resource = ResourceInfo.from_dict(resource_data)
        except Exception:
            pass  # resource is optional; we'll fall back to URL-based construction

        # If no resource found in body, construct from the URL
        if resource is None:
            # Parse URL to build resource info
            from urllib.parse import urlparse

            parsed = urlparse(url)
            description = f"x402 payment for {parsed.path or '/'}"
            mime_type = "application/json"  # Default; x402 APIs typically return JSON
            resource = ResourceInfo(
                url=url,
                description=description,
                mime_type=mime_type,
            )

        # Step 4: Find GatewayWalletBatched scheme
        gateway_kind = requirements.find_gateway_kind()
        if gateway_kind is None:
            raise UnsupportedSchemeError(
                scheme=str([k.extra.name for k in requirements.accepts]),
            )
        raw_gateway_kind = _find_raw_gateway_kind(req_data) or gateway_kind.to_dict()

        # Step 5: Get verifying contract if missing
        verifying_contract = await self._gateway_verifying_contract(gateway_kind)
        raw_gateway_kind = _with_gateway_verifying_contract(raw_gateway_kind, verifying_contract)

        # Build updated requirements with verifying contract
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsExtra,
            PaymentRequirementsKind,
        )

        updated_kind = PaymentRequirementsKind(
            scheme=gateway_kind.scheme,
            network=gateway_kind.network,
            asset=gateway_kind.asset,
            amount=gateway_kind.amount,
            max_timeout_seconds=gateway_kind.max_timeout_seconds,
            pay_to=gateway_kind.pay_to,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract=verifying_contract,
            ),
        )
        # Step 6: Check balance - FAIL if insufficient
        payer_address = self._get_address()
        balance = await self._gateway_available_balance(gateway_kind)
        payment_amount_atomic = int(updated_kind.amount)
        if balance.available < payment_amount_atomic:
            raise InsufficientBalanceError(
                reason=f"Insufficient balance: available {balance.available}, required {payment_amount_atomic}",
                payer=payer_address,
            )

        # Step 7: Sign payment (pass resource for Circle Gateway)
        payer_address = self._get_address()
        payload = self._sign(
            requirements=updated_kind,
            resource=resource,
            valid_before=_gateway_valid_before(raw_gateway_kind),
        )

        # Step 8: Retry with payment header
        payment_sig_header = self._encode_payment_signature_header(
            payload=payload,
            accepted=raw_gateway_kind,
        )

        retry_headers = dict(headers)
        retry_headers["PAYMENT-SIGNATURE"] = payment_sig_header

        try:
            retry_resp = await self._http.request(
                method=method.upper(),
                url=url,
                headers=retry_headers,
                content=body,
            )
        except httpx.TimeoutException as exc:
            raise GatewayAPIError(
                message=f"Retry request timed out: {url}",
                status_code=0,
                response_body=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise GatewayAPIError(
                message=f"Retry request failed: {exc}",
                status_code=0,
                response_body=str(exc),
            ) from exc

        # Step 9: Seller-side settlement via PAYMENT-RESPONSE header (x402 v2)
        content_delivered = _is_success_status(retry_resp.status_code)
        payment_response = retry_resp.headers.get("payment-response") or retry_resp.headers.get(
            "PAYMENT-RESPONSE"
        )
        settlement_succeeded = False
        transaction = ""
        if payment_response:
            try:
                decoded = base64.b64decode(payment_response)
                data = json.loads(decoded)
                settlement_succeeded = bool(data.get("success"))
                transaction = str(data.get("transaction") or "")
            except Exception as exc:
                if self._strict_settlement and not content_delivered:
                    raise SettlementError(
                        reason=f"Invalid PAYMENT-RESPONSE header: {exc}",
                        transaction=None,
                        payer=payer_address,
                    ) from exc
                logger.warning(
                    "Invalid PAYMENT-RESPONSE header (payer=%s): %s",
                    payer_address,
                    exc,
                )
        else:
            if self._strict_settlement and not content_delivered:
                raise SettlementError(
                    reason="Missing PAYMENT-RESPONSE header",
                    transaction=None,
                    payer=payer_address,
                )
            logger.warning(
                "Missing PAYMENT-RESPONSE header (payer=%s)",
                payer_address,
            )

        # Step 10: Determine final success status
        # If content was delivered, we treat the user request as successful even when
        # settlement is delayed/degraded. Reconciliation can retry settlement later.
        final_success = (
            settlement_succeeded
            if self._strict_settlement
            else (settlement_succeeded or content_delivered)
        )

        # Step 11: Return result
        amount_decimal = _atomic_to_decimal(updated_kind.amount)
        response_data = retry_resp.text if retry_resp.content else None

        return NanopaymentResult(
            success=final_success,
            payer=payer_address,
            seller=updated_kind.pay_to,
            transaction=transaction,
            amount_usdc=amount_decimal,
            amount_atomic=updated_kind.amount,
            network=updated_kind.network,
            response_data=response_data,
            is_nanopayment=True,
        )

    # -------------------------------------------------------------------------
    # Direct address payment
    # -------------------------------------------------------------------------

    async def pay_direct(
        self,
        seller_address: str,
        amount_usdc: str,
        network: str,
    ) -> NanopaymentResult:
        """
        Pay a direct address via Gateway nanopayment.

        Used when:
        - Recipient is a 0x address
        - Amount is below the micro_payment_threshold

        Flow:
        1. Get supported networks and find matching network
        2. Get verifying contract and USDC address from client
        3. Build PaymentRequirements from scratch
        4. Auto-topup if balance is low
        5. Call signer to create signed PaymentPayload
        6. Call NanopaymentClient.settle()
        7. Return NanopaymentResult

        Args:
            seller_address: The seller's EOA address.
            amount_usdc: Amount in USDC decimal string (e.g. "0.001").
            network: CAIP-2 network identifier.


        Returns:
            NanopaymentResult with payment details.

        Raises:
            SettlementError: On payment settlement failure.
        """
        if not self._client.has_api_key:
            raise GatewayAPIError(
                message=(
                    "Direct address Gateway settlement requires CIRCLE_API_KEY. "
                    "Use an x402 URL seller flow, or configure Circle API credentials for "
                    "direct Gateway settlement."
                ),
                status_code=0,
                response_body=None,
            )
        # Step 1: Resolve contract addresses
        verifying_contract = await self._client.get_verifying_contract(network)
        usdc_address = await self._client.get_usdc_address(network)

        # Step 2: Build requirements
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsExtra,
            PaymentRequirementsKind,
        )

        amount_atomic = _decimal_to_atomic(amount_usdc)

        kind = PaymentRequirementsKind(
            scheme="exact",
            network=network,
            asset=usdc_address,
            amount=str(amount_atomic),
            max_timeout_seconds=345600,
            pay_to=seller_address,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract=verifying_contract,
            ),
        )
        requirements = PaymentRequirements(
            x402_version=2,
            accepts=(kind,),
        )

        # Step 3: Check balance - FAIL if insufficient
        payer_address = self._get_address()
        balance = await self._client.check_balance(
            address=payer_address,
            network=network,
        )
        if balance.available < amount_atomic:
            raise InsufficientBalanceError(
                reason=f"Insufficient balance: available {balance.available}, required {amount_atomic}",
                payer=payer_address,
            )

        # Step 4: Get payer address
        payer_address = self._get_address()

        # Step 5: Build resource info (required by Circle Gateway)
        from omniclaw.protocols.nanopayments.types import ResourceInfo

        resource = ResourceInfo(
            url=f"direct:{seller_address}",
            description=f"Nanopayment to {seller_address} on {network}",
            mime_type="application/json",
        )

        # Step 6: Sign
        payload = self._sign(
            requirements=kind,
            amount_atomic=amount_atomic,
            resource=resource,
        )

        # Step 6: Settle with circuit breaker and retry
        try:
            settle_resp = await self._settle_with_retry(
                payload=payload,
                requirements=requirements,
            )
        except CircuitOpenError as exc:
            raise SettlementError(
                reason=f"Nanopayments temporarily unavailable (circuit breaker open): {exc}",
                transaction=None,
                payer=payer_address,
            ) from exc

        # Step 7: Return result
        return NanopaymentResult(
            success=settle_resp.success if settle_resp else False,
            payer=payer_address,
            seller=seller_address,
            transaction=settle_resp.transaction if settle_resp else "",
            amount_usdc=amount_usdc,
            amount_atomic=str(amount_atomic),
            network=network,
            response_data=None,
            is_nanopayment=True,
        )

    # -------------------------------------------------------------------------
    # Settlement with circuit breaker and retry
    # -------------------------------------------------------------------------

    async def _settle_with_retry(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> SettleResponse | None:
        """
        Settle a payment with circuit breaker and retry logic.

        Circuit breaker: If too many consecutive failures, raises CircuitOpenError.
        Retry: Retries transient errors (timeout, connection) with exponential backoff.

        Non-transient errors (nonce reused, insufficient balance) are NOT retried.

        Args:
            payload: The signed PaymentPayload.
            requirements: The PaymentRequirements.

        Returns:
            SettleResponse on success, None on non-fatal errors (e.g. content delivered
            but settlement had transient issue).

        Raises:
            CircuitOpenError: If circuit breaker is open.
            SettlementError: On non-recoverable settlement failures.
            GatewayTimeoutError: On HTTP timeout (after retry exhaustion).
            GatewayConnectionError: On connection errors (after retry exhaustion).
        """
        # Check circuit breaker
        if not self._circuit_breaker.is_available():
            raise CircuitOpenError(recovery_seconds=self._circuit_breaker._recovery_seconds)

        last_error: Exception | None = None
        for attempt in range(self._retry_attempts + 1):
            try:
                settle_resp = await self._client.settle(
                    payload=payload,
                    requirements=requirements,
                )
                self._circuit_breaker.record_success()
                return settle_resp
            except GatewayTimeoutError as exc:
                # Transient: retry with backoff
                last_error = exc
                self._circuit_breaker.record_error()
                if attempt < self._retry_attempts:
                    delay = self._retry_base_delay * (2**attempt)
                    logger.warning(
                        f"Settlement timeout (attempt {attempt + 1}/{self._retry_attempts + 1}), "
                        f"retrying in {delay:.1f}s: {exc}"
                    )
                    import asyncio

                    await asyncio.sleep(delay)
                # else: no more retries, raise
            except GatewayConnectionError as exc:
                # Transient: retry with backoff
                last_error = exc
                self._circuit_breaker.record_error()
                if attempt < self._retry_attempts:
                    delay = self._retry_base_delay * (2**attempt)
                    logger.warning(
                        f"Settlement connection error (attempt {attempt + 1}/{self._retry_attempts + 1}), "
                        f"retrying in {delay:.1f}s: {exc}"
                    )
                    import asyncio

                    await asyncio.sleep(delay)
                # else: no more retries, raise
            except NonceReusedError:
                # Non-recoverable - nonce already used
                self._circuit_breaker.record_failure()
                raise
            except InsufficientBalanceError:
                # Non-recoverable - insufficient balance
                self._circuit_breaker.record_failure()
                raise
            except SettlementError as exc:
                # Check if this is a transient error or not
                if "timeout" in str(exc).lower() or "connection" in str(exc).lower():
                    last_error = exc
                    self._circuit_breaker.record_error()
                    if attempt < self._retry_attempts:
                        delay = self._retry_base_delay * (2**attempt)
                        logger.warning(
                            f"Settlement error (attempt {attempt + 1}/{self._retry_attempts + 1}), "
                            f"retrying in {delay:.1f}s: {exc}"
                        )
                        import asyncio

                        await asyncio.sleep(delay)
                    else:
                        self._circuit_breaker.record_failure()
                        raise
                else:
                    # Non-transient settlement error
                    self._circuit_breaker.record_failure()
                    raise

        # All retries exhausted
        if last_error:
            raise last_error
        return None

    def get_circuit_breaker_state(self) -> str:
        """Get the current circuit breaker state."""
        return self._circuit_breaker.state

    # -------------------------------------------------------------------------
    # Auto-topup
    # -------------------------------------------------------------------------

    async def _check_and_topup(
        self,
        threshold: str | None = None,
        topup_amount: str | None = None,
    ) -> bool:
        """
        Check gateway balance and auto-topup if needed.

        Returns True if topup was performed, False otherwise.

        NOTE: This requires the GatewayWalletManager to be set via set_wallet_manager().
        Without it, this method only logs a warning.
        """
        if not hasattr(self, "_wallet_manager") or self._wallet_manager is None:
            logger.debug(
                "GatewayWalletManager not configured. "
                "Auto-topup disabled. Set via set_wallet_manager() for auto-topup support."
            )
            return False

        threshold = threshold or self._topup_threshold
        topup_amount = topup_amount or self._topup_amount

        try:
            payer_address = self._get_address()
            balance = await self._client.check_balance(
                address=payer_address,
                network=self._network,
            )
        except Exception as exc:
            logger.warning(f"Failed to check balance for auto-topup: {exc}")
            return False

        if Decimal(balance.available_decimal) >= Decimal(threshold):
            return False

        # Balance is low — need to top up
        logger.info(
            f"Gateway balance low ({balance.available_decimal} < {threshold}). "
            f"Auto-topup with {topup_amount} USDC."
        )

        try:
            result = await self._wallet_manager.deposit(topup_amount)
            logger.info(f"Auto-topup successful: tx={result.deposit_tx_hash}")
            return True
        except Exception as exc:
            logger.error(f"Auto-topup failed: {exc}")
            return False

    def set_wallet_manager(self, wallet_manager: Any) -> None:
        """
        Set the GatewayWalletManager for auto-topup functionality.

        Args:
            wallet_manager: GatewayWalletManager instance.
        """
        self._wallet_manager = wallet_manager

    # -------------------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------------------

    def configure_auto_topup(
        self,
        enabled: bool | None = None,
        threshold: str | None = None,
        amount: str | None = None,
    ) -> None:
        """Update auto-topup configuration."""
        if enabled is not None:
            self._auto_topup = enabled
        if threshold is not None:
            self._topup_threshold = threshold
        if amount is not None:
            self._topup_amount = amount


# =============================================================================
# NANOPAYMENT PROTOCOL ADAPTER (Router integration)
# =============================================================================


def _is_url(recipient: str) -> bool:
    """Check if recipient is a URL (http/https)."""
    return recipient.startswith("http://") or recipient.startswith("https://")


def _is_address(recipient: str) -> bool:
    """Check if recipient is an EVM address."""
    return recipient.startswith("0x") and len(recipient) == 42


class NanopaymentProtocolAdapter:
    """
    ProtocolAdapter wrapper for NanopaymentAdapter.

    Integrates NanopaymentAdapter into OmniClaw's PaymentRouter so that
    URL and micro-payment address payments are automatically routed to
    Circle Gateway nanopayments when nanopayments are enabled.

    Routing rules:
      - URL recipients (https://...)  → pay_x402_url()
      - Address recipients below micro_threshold → pay_direct()
      - Otherwise → falls through to other adapters (no nanopayment)

    Priority: 10 (highest) — checked before X402Adapter and TransferAdapter.
    """

    method = "nanopayment"

    def __init__(
        self,
        nanopayment_adapter: NanopaymentAdapter,
        micro_threshold_usdc: str = "1.00",
    ) -> None:
        self._adapter = nanopayment_adapter
        self._micro_threshold = micro_threshold_usdc

    def supports(
        self,
        recipient: str,
        source_network: str | None = None,
        destination_chain: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Check if this adapter can handle the recipient via nanopayments."""
        # URL → can try x402 with Gateway
        if _is_url(recipient):
            preferred_url_route = kwargs.get("preferred_url_route")
            return preferred_url_route != "x402"
        # EVM address below micro threshold
        if _is_address(recipient):
            if not self._adapter._client.has_api_key:
                return False
            amount = kwargs.get("amount")
            if amount is not None:
                threshold = Decimal(self._micro_threshold)
                payment_amount = Decimal(str(amount))
                if payment_amount < threshold:
                    return True
        return False

    def get_priority(self) -> int:
        """Priority 5 — must run before generic x402 for URL payments."""
        return 5

    async def execute(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal,
        fee_level: Any = None,
        idempotency_key: str | None = None,
        purpose: str | None = None,
        destination_chain: str | None = None,
        source_network: str | None = None,
        wait_for_completion: bool = False,
        timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> PaymentResult:
        """
        Execute a payment via Circle Gateway nanopayments.

        Args:
            wallet_id: Source wallet ID (used for ledger/tracking only).
            recipient: URL or EVM address.
            amount: Payment amount in USDC decimal.
            **kwargs: Additional parameters (ignored).

        Returns:
            PaymentResult with nanopayment details.
        """
        strict_settlement = bool(getattr(self._adapter, "_strict_settlement", False))
        try:
            if _is_url(recipient):
                result = await self._adapter.pay_x402_url(
                    url=recipient,
                )
            else:
                # Address payment below micro threshold
                network = destination_chain or source_network
                if not network:
                    network = self._adapter._network
                result = await self._adapter.pay_direct(
                    seller_address=recipient,
                    amount_usdc=str(amount),
                    network=str(network),
                )

            return PaymentResult(
                success=result.success,
                transaction_id=result.transaction or None,
                blockchain_tx=None,
                amount=Decimal(result.amount_usdc) if result.amount_usdc else amount,
                recipient=recipient,
                method=PaymentMethod.NANOPAYMENT,
                status=(
                    PaymentStatus.SETTLED
                    if result.success and strict_settlement
                    else (
                        PaymentStatus.COMPLETED
                        if result.success
                        else (
                            PaymentStatus.FAILED_FINAL
                            if strict_settlement
                            else PaymentStatus.FAILED
                        )
                    )
                ),
                error=None if result.success else "Nanopayment settlement failed",
                resource_data=result.response_data,
                metadata={
                    "nanopayment": True,
                    "payer": result.payer,
                    "seller": result.seller,
                    "amount_atomic": result.amount_atomic,
                    "network": result.network,
                    "is_nanopayment": result.is_nanopayment,
                },
            )

        except (UnsupportedSchemeError, CircuitOpenError, UnsupportedNetworkError) as exc:
            # Safe fallback: seller does not support GatewayWalletBatched,
            # circuit is open, or network is not supported for nanopayments.
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=recipient,
                method=PaymentMethod.NANOPAYMENT,
                status=PaymentStatus.FAILED,
                error=f"Nanopayment failed (falling back): {exc}",
                metadata={"fallback_eligible": True},
            )
        except Exception as exc:
            # Other failures may occur after partial protocol execution;
            # do not fallback automatically to avoid accidental double-pay.
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=recipient,
                method=PaymentMethod.NANOPAYMENT,
                status=PaymentStatus.FAILED,
                error=f"Nanopayment failed (falling back disabled): {exc}",
                metadata={"fallback_eligible": False},
            )

    async def simulate(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Simulate a nanopayment without executing."""
        return {
            "would_succeed": True,
            "method": self.method,
            "recipient": recipient,
            "amount": str(amount),
            "estimated_fee": "0",  # Nanopayments are gasless
        }
