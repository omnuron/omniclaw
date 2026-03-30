"""
NanopaymentClient for Circle Gateway REST API.

Wraps the Circle Gateway endpoints:
- GET  /v1/x402/supported  — supported networks (CAIP-2 format)
- POST /v1/balances        — check Gateway wallet balance
- POST /v1/x402/verify     — verify a payment signature (debug only)
- POST /v1/x402/settle     — settle a payment (production primary path)

All network calls are async. Production code should use settle() directly,
never verify() followed by settle().

Network Format:
    Internally we use CAIP-2 identifiers (e.g., "eip155:5042002").
    The /v1/x402/supported endpoint returns networks in CAIP-2 format directly.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from omniclaw.protocols.nanopayments import (
    CAIP2_TO_CIRCLE_DOMAIN,
    CIRCLE_DOMAIN_TO_CAIP2,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    GATEWAY_API_MAINNET,
    GATEWAY_API_TESTNET,
    GATEWAY_BALANCES_PATH,
    GATEWAY_X402_SETTLE_PATH,
    GATEWAY_X402_SUPPORTED_PATH,
    GATEWAY_X402_VERIFY_PATH,
    SUPPORTED_NETWORKS_CACHE_TTL_SECONDS,
)
from omniclaw.protocols.nanopayments.exceptions import (
    GatewayAPIError,
    GatewayConnectionError,
    GatewayTimeoutError,
    InsufficientBalanceError,
    InvalidSignatureError,
    NetworkMismatchError,
    NonceReusedError,
    SettlementError,
    UnsupportedNetworkError,
    VerificationError,
)
from omniclaw.protocols.nanopayments.types import (
    GatewayBalance,
    PaymentPayload,
    PaymentRequirements,
    SettleResponse,
    SupportedKind,
    VerifyResponse,
)

# ---------------------------------------------------------------------------
# Error code -> exception class mapping for settlement failures
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Network format conversion helpers
# ---------------------------------------------------------------------------


def _caip2_to_circle_network(caip2: str) -> str:
    """
    Convert CAIP-2 network identifier to Circle's network format.

    CAIP-2: "eip155:5042002" -> Circle: "arc-testnet"
    CAIP-2: "eip155:8453" -> Circle: "base"
    """
    chain_id = _parse_caip2_chain_id(caip2)
    domain = CAIP2_TO_CIRCLE_DOMAIN.get(caip2)
    if domain is not None:
        return _CIRCLE_DOMAIN_NAME.get(domain, str(domain))
    return str(chain_id)


def _parse_caip2_chain_id(network: str) -> int:
    """
    Parse chain ID from CAIP-2 network identifier.

    "eip155:5042002" -> 5042002
    """
    if ":" in network:
        parts = network.rsplit(":", 1)
        if len(parts) == 2:
            try:
                return int(parts[1])
            except ValueError:
                pass
    return 0


# Circle domain ID to human-readable network name mapping
_CIRCLE_DOMAIN_NAME: dict[int, str] = {
    0: "ethereum",
    1: "avalanche",
    2: "optimism",
    3: "arbitrum",
    5: "solana",
    6: "base",
    7: "polygon",
    10: "unichain",
    13: "sonic",
    14: "worldchain",
    16: "sei",
    19: "hyperevm",
    26: "arc-testnet",
}


def _caip2_to_gateway_network(caip2: str) -> str:
    """
    Convert CAIP-2 to Circle Gateway network name used in API bodies.

    This converts "eip155:5042002" -> "arc-testnet", "eip155:8453" -> "base", etc.
    Falls back to the numeric chain ID if no mapping exists.
    """
    domain = CAIP2_TO_CIRCLE_DOMAIN.get(caip2)
    if domain is not None:
        return _CIRCLE_DOMAIN_NAME.get(domain, str(domain))
    chain_id = _parse_caip2_chain_id(caip2)
    if chain_id > 0:
        return str(chain_id)
    return caip2


def _gateway_network_to_caip2(gateway_network: str, domain_id: int | None = None) -> str:
    """
    Convert Circle Gateway network name to CAIP-2 format.

    Handles known network names ("base", "arc-testnet") as well as numeric IDs.
    """
    if gateway_network in _CIRCLE_DOMAIN_NAME.values():
        for dom_id, name in _CIRCLE_DOMAIN_NAME.items():
            if name == gateway_network:
                return CIRCLE_DOMAIN_TO_CAIP2.get(dom_id, gateway_network)
    if gateway_network.isdigit():
        chain_id = int(gateway_network)
        return CIRCLE_DOMAIN_TO_CAIP2.get(chain_id, f"eip155:{gateway_network}")
    return gateway_network


def _caip2_to_circle_domain_id(caip2: str) -> int:
    """Get Circle domain ID from CAIP-2 network."""
    domain = CAIP2_TO_CIRCLE_DOMAIN.get(caip2)
    if domain is not None:
        return domain
    return 0


def _to_int(value: Any) -> int:
    """Safely convert a value to int, returning 0 on failure."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return 0


# =============================================================================
# CIRCLE API REQUEST/RESPONSE FORMATTERS
# =============================================================================


def _convert_payload_for_circle(payload_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Convert our PaymentPayload dict to Circle Gateway's expected format.

    Circle's PaymentPayload expects:
        - x402Version: int
        - accepted: PaymentRequirements dict (the requirements we chose)
        - payload: { authorization: {...}, signature: "0x..." }
        - resource: optional ResourceInfo
        - extensions: optional

    Our PaymentPayload.to_dict() produces:
        - x402Version: int
        - scheme: str
        - network: str
        - payload: { authorization: {...}, signature: "0x..." }

    This function restructures our format into Circle's expected format.
    """
    # Extract the inner payload (authorization + signature)
    inner_payload = payload_dict.get("payload", {})

    # Build the authorization object exactly as Circle expects
    authorization = inner_payload.get("authorization", {})

    # Build Circle's payload format
    circle_payload: dict[str, Any] = {
        "authorization": {
            "from": authorization.get("from"),
            "to": authorization.get("to"),
            "value": authorization.get("value"),
            "validAfter": authorization.get("validAfter"),
            "validBefore": authorization.get("validBefore"),
            "nonce": authorization.get("nonce"),
        },
        "signature": inner_payload.get("signature"),
    }

    # The "accepted" field will be set by the caller (we return the base payload)
    result: dict[str, Any] = {
        "x402Version": payload_dict.get("x402Version", 2),
        "payload": circle_payload,
    }

    # Include accepted requirements if present in the original dict
    if "accepted" in payload_dict:
        result["accepted"] = payload_dict["accepted"]

    # Include resource if present
    if "resource" in payload_dict:
        result["resource"] = payload_dict["resource"]

    # Include scheme and network at top level (Circle may use these)
    if "scheme" in payload_dict:
        result["scheme"] = payload_dict["scheme"]
    if "network" in payload_dict:
        result["network"] = payload_dict["network"]

    return result


def _convert_requirements_for_circle(req_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Convert our PaymentRequirements dict to Circle Gateway's expected format.

    Circle's PaymentRequirements (in the 'accepted' field) expects:
        - scheme: str (e.g., "exact")
        - network: str (CAIP-2 format, e.g., "eip155:5042002")
        - asset: str (USDC address)
        - amount: str (atomic units)
        - payTo: str (seller address)
        - maxTimeoutSeconds: int
        - extra: optional scheme-specific params

    Our PaymentRequirementsKind.to_dict() produces:
        - scheme, network, asset, amount, maxTimeoutSeconds, payTo
        - extra: { name, version, verifyingContract, usdcAddress }

    NOTE: The network field must remain in CAIP-2 format. Circle REJECTS human-readable
    names (e.g. "arc-testnet") with "Invalid network format (expected CAIP-2)".
    We keep the network as-is since get_supported() and 402 responses return CAIP-2.
    """
    accepts = req_dict.get("accepts", [])
    if not accepts:
        return req_dict

    converted_accepts = []
    for kind in accepts:
        extra = kind.get("extra", {})

        # Keep network as CAIP-2 — Circle accepts CAIP-2 and rejects human-readable names.
        # The network from get_supported() and 402 responses is already in CAIP-2 format.
        network = kind.get("network", "")

        # Build the converted kind
        converted_kind: dict[str, Any] = {
            "scheme": kind.get("scheme", "exact"),
            "network": network,
            "asset": kind.get("asset", ""),
            "amount": kind.get("amount", ""),
            "payTo": kind.get("payTo", ""),
            "maxTimeoutSeconds": kind.get("maxTimeoutSeconds", 345600),
        }

        # Include extra if it has meaningful data
        if extra:
            converted_kind["extra"] = extra

        converted_accepts.append(converted_kind)

    return {
        "x402Version": req_dict.get("x402Version", 2),
        "accepts": converted_accepts,
    }


_SETTLEMENT_ERROR_CODE_MAP: dict[str, type[VerificationError]] = {
    "invalid_signature": InvalidSignatureError,
    "authorization_not_yet_valid": VerificationError,
    "authorization_expired": VerificationError,
    "authorization_validity_too_short": VerificationError,
    "self_transfer": VerificationError,
    "insufficient_balance": InsufficientBalanceError,
    "nonce_already_used": NonceReusedError,
    "network_mismatch": NetworkMismatchError,
    "unsupported_scheme": UnsupportedNetworkError,
    "unsupported_network": UnsupportedNetworkError,
    "unsupported_asset": VerificationError,
    "invalid_payload": VerificationError,
    "address_mismatch": VerificationError,
    "amount_mismatch": VerificationError,
    "unsupported_domain": VerificationError,
    "wallet_not_found": VerificationError,
    "settle_exact_evm_transaction_confirmation_timed_out": SettlementError,
    "settle_exact_node_failure": SettlementError,
    "settle_exact_failed_onchain": SettlementError,
    "settle_exact_svm_block_height_exceeded": SettlementError,
    "settle_exact_svm_transaction_confirmation_timed_out": SettlementError,
    "unexpected_error": SettlementError,
}


# =============================================================================
# INTERNAL HTTP CLIENT
# =============================================================================


class NanopaymentHTTPClient:
    """
    Thin async HTTP wrapper for Circle Gateway API calls.

    Handles:
    - Authorization header injection (CIRCLE_API_KEY)
    - Timeout enforcement
    - Connection error wrapping
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> NanopaymentHTTPClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout, connect=10.0),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        """
        Perform a GET request. Raises on connection errors / timeouts.
        """
        assert self._client is not None, "HTTP client not opened (use async context manager)"
        try:
            return await self._client.get(path, **kwargs)
        except httpx.TimeoutException as exc:
            raise GatewayTimeoutError(endpoint=path) from exc
        except httpx.ConnectError as exc:
            raise GatewayConnectionError(reason=str(exc)) from exc
        except httpx.RequestError as exc:
            raise GatewayConnectionError(reason=str(exc)) from exc

    async def post(
        self,
        path: str,
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Perform a POST request. Raises on connection errors / timeouts.

        Args:
            path: API path.
            idempotency_key: Optional idempotency key for safe retries.
                If provided, included as Idempotency-Key header.
            **kwargs: Passed to httpx (e.g., json=body).
        """
        assert self._client is not None, "HTTP client not opened (use async context manager)"
        headers = kwargs.pop("headers", {})
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            return await self._client.post(path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise GatewayTimeoutError(endpoint=path) from exc
        except httpx.ConnectError as exc:
            raise GatewayConnectionError(reason=str(exc)) from exc
        except httpx.RequestError as exc:
            raise GatewayConnectionError(reason=str(exc)) from exc


# =============================================================================
# NANOPAYMENT CLIENT
# =============================================================================


class NanopaymentClient:
    """
    Async client for Circle Gateway nanopayments API.

    Args:
        environment: 'testnet' or 'mainnet'. Defaults to reading
            NANOPAYMENTS_ENVIRONMENT env var, then 'testnet'.
        api_key: Circle API key. Defaults to CIRCLE_API_KEY env var.
        base_url: Override base URL for testing.
        timeout: Request timeout in seconds. Default 30.
    """

    def __init__(
        self,
        environment: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        env = environment or os.environ.get("NANOPAYMENTS_ENVIRONMENT", "testnet")
        if env not in ("testnet", "mainnet"):
            raise ValueError(f"environment must be 'testnet' or 'mainnet', got {env!r}")

        self._environment = env
        self._base_url = base_url or (
            GATEWAY_API_TESTNET if env == "testnet" else GATEWAY_API_MAINNET
        )
        self._api_key = api_key or os.environ.get("CIRCLE_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "Circle API key is required. Set CIRCLE_API_KEY or pass api_key explicitly."
            )
        self._timeout = timeout

        # Supported networks cache
        self._supported_cache: list[SupportedKind] | None = None
        self._supported_cache_time: float = 0.0

    # -------------------------------------------------------------------------
    # Supported networks (with in-memory cache)
    # -------------------------------------------------------------------------

    async def get_supported(
        self,
        force_refresh: bool = False,
    ) -> list[SupportedKind]:
        """
        Fetch the list of supported networks from Circle Gateway.

        Results are cached for 1 hour (SUPPORTED_NETWORKS_CACHE_TTL_SECONDS).
        Use force_refresh=True to bypass the cache.

        Args:
            force_refresh: If True, bypass cache and refetch from Gateway.

        Returns:
            List of SupportedKind, each describing a supported network/scheme.

        Raises:
            GatewayAPIError: On HTTP errors from Circle.
            GatewayTimeoutError: On request timeout.
        """
        now = time.monotonic()
        cache_valid = (
            self._supported_cache is not None
            and (now - self._supported_cache_time) < SUPPORTED_NETWORKS_CACHE_TTL_SECONDS
        )

        if cache_valid and not force_refresh:
            assert self._supported_cache is not None
            return self._supported_cache

        async with NanopaymentHTTPClient(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout,
        ) as http:
            resp = await http.get(GATEWAY_X402_SUPPORTED_PATH)

        if not httpx.codes.is_success(resp.status_code):
            raise GatewayAPIError(
                message=f"Gateway {GATEWAY_X402_SUPPORTED_PATH} returned {resp.status_code}",
                status_code=resp.status_code,
                response_body=resp.text,
            )

        data = resp.json()
        kinds: list[SupportedKind] = []
        for kind_data in data.get("kinds", []):
            extra = kind_data.get("extra", {})
            assets = extra.get("assets", [])
            usdc_address = extra.get("usdcAddress")
            for asset in assets:
                if asset.get("symbol") == "USDC":
                    usdc_address = asset.get("address")
                    break

            kinds.append(
                SupportedKind(
                    x402_version=kind_data.get("x402Version", 2),
                    scheme=kind_data.get("scheme", "exact"),
                    network=kind_data.get("network", ""),
                    extra={
                        "name": extra.get("name", "GatewayWalletBatched"),
                        "version": extra.get("version", "1"),
                        "verifyingContract": extra.get("verifyingContract", ""),
                        "usdcAddress": usdc_address or "",
                    },
                )
            )

        self._supported_cache = kinds
        self._supported_cache_time = now
        return kinds

    async def get_verifying_contract(self, network: str) -> str:
        """
        Get the Gateway Wallet contract address for a CAIP-2 network.

        Args:
            network: CAIP-2 identifier (e.g. 'eip155:5042002').

        Returns:
            The Gateway Wallet contract address on that network.

        Raises:
            UnsupportedNetworkError: If the network is not supported.
        """
        supported = await self.get_supported()
        for kind in supported:
            if kind.network == network:
                addr = kind.verifying_contract
                if addr:
                    return addr
        raise UnsupportedNetworkError(network=network)

    async def get_usdc_address(self, network: str) -> str:
        """
        Get the USDC token contract address for a CAIP-2 network.

        Args:
            network: CAIP-2 identifier.

        Returns:
            The USDC contract address on that network.

        Raises:
            UnsupportedNetworkError: If the network is not supported.
        """
        supported = await self.get_supported()
        for kind in supported:
            if kind.network == network:
                addr = kind.usdc_address
                if addr:
                    return addr
        raise UnsupportedNetworkError(network=network)

    # -------------------------------------------------------------------------
    # Verify (debug only — use settle() in production)
    # -------------------------------------------------------------------------

    async def verify(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> VerifyResponse:
        """
        Verify a payment payload against requirements.

        WARNING: For debugging only. Use settle() in production.
        The verify-then-settle pattern adds latency and is not atomic.
        Circle recommends calling settle() directly.

        Args:
            payload: The signed PaymentPayload from the buyer.
            requirements: The PaymentRequirements parsed from the 402 response.

        Returns:
            VerifyResponse with is_valid, payer, and invalid_reason.

        Raises:
            GatewayAPIError: On HTTP errors.
        """
        body: dict[str, Any] = {
            "paymentPayload": _convert_payload_for_circle(payload.to_dict()),
            "paymentRequirements": _convert_requirements_for_circle(requirements.to_dict()),
        }

        async with NanopaymentHTTPClient(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout,
        ) as http:
            resp = await http.post(GATEWAY_X402_VERIFY_PATH, json=body)

        if not httpx.codes.is_success(resp.status_code):
            raise GatewayAPIError(
                message=f"Gateway /verify returned {resp.status_code}",
                status_code=resp.status_code,
                response_body=resp.text,
            )

        data = resp.json()
        return VerifyResponse(
            is_valid=data.get("isValid", False),
            payer=data.get("payer"),
            invalid_reason=data.get("invalidReason"),
        )

    # -------------------------------------------------------------------------
    # Settle (production primary path)
    # -------------------------------------------------------------------------

    async def settle(
        self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
        idempotency_key: str | None = None,
    ) -> SettleResponse:
        """
        Settle a nanopayment with Circle Gateway.

        This is the PRIMARY production method. Always call settle() directly;
        never verify() then settle(). settle() is atomic and optimized for
        low latency.

        Args:
            payload: The signed PaymentPayload authorizing the transfer.
            requirements: The PaymentRequirements from the 402 response.
            idempotency_key: Optional idempotency key for safe retries.
                If not provided, uses the EIP-3009 authorization nonce
                (which is already unique per payment) as the idempotency key.

        Returns:
            SettleResponse on success (success=True, transaction set).

        Raises:
            SettlementError: On settlement failure (e.g. insufficient balance).
            GatewayAPIError: On HTTP-level errors (auth failure, etc.).
            GatewayTimeoutError: On request timeout.
        """
        # Convert to Circle API format
        payload_dict = payload.to_dict()
        req_dict = requirements.to_dict()

        # Build Circle's PaymentPayload with 'accepted' field
        circle_payload = _convert_payload_for_circle(payload_dict)
        # The 'accepted' field contains the specific PaymentRequirementsKind we chose
        circle_accepted = _convert_requirements_for_circle(req_dict)
        if circle_accepted.get("accepts"):
            circle_payload["accepted"] = circle_accepted["accepts"][0]

        # Use the EIP-3009 nonce as the idempotency key if not provided.
        if idempotency_key is None:
            auth = getattr(payload.payload, "authorization", None)
            if auth and hasattr(auth, "nonce") and auth.nonce:
                idempotency_key = auth.nonce.hex() if isinstance(auth.nonce, bytes) else auth.nonce

        body: dict[str, Any] = {
            "paymentPayload": circle_payload,
            "paymentRequirements": circle_accepted["accepts"][0]
            if circle_accepted.get("accepts")
            else req_dict,
        }

        async with NanopaymentHTTPClient(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout,
        ) as http:
            resp = await http.post(
                GATEWAY_X402_SETTLE_PATH,
                json=body,
                idempotency_key=idempotency_key,
            )

        # HTTP 402 with payment-specific error body
        if resp.status_code == 402:
            body_data = resp.json()
            error_reason = body_data.get("errorReason", "settlement_declined")
            payer = body_data.get("payer")
            raise _map_settlement_error(error_reason, payer=payer)

        if not httpx.codes.is_success(resp.status_code):
            raise GatewayAPIError(
                message=f"Gateway /settle returned {resp.status_code}",
                status_code=resp.status_code,
                response_body=resp.text,
            )

        data = resp.json()
        success = data.get("success", False)
        transaction = data.get("transaction")
        payer = data.get("payer")
        error_reason = data.get("errorReason")

        if not success:
            raise _map_settlement_error(error_reason, transaction=transaction, payer=payer)

        return SettleResponse(
            success=True,
            transaction=transaction,
            payer=payer,
            error_reason=None,
        )

    # -------------------------------------------------------------------------
    # Balance
    # -------------------------------------------------------------------------

    async def check_balance(
        self,
        address: str,
        network: str,
    ) -> GatewayBalance:
        """
        Check the Gateway wallet balance for an address on a network.

        Args:
            address: The EOA address to query.
            network: CAIP-2 network identifier (e.g. 'eip155:5042002').

        Returns:
            GatewayBalance with total, available, and formatted amounts.

        Raises:
            UnsupportedNetworkError: If the network is not supported.
            GatewayAPIError: On HTTP errors.
        """
        await self.get_supported()

        circle_domain_id = _caip2_to_circle_domain_id(network)
        body: dict[str, Any] = {
            "token": "USDC",
            "sources": [
                {
                    "domain": circle_domain_id,
                    "depositor": address,
                }
            ],
        }

        async with NanopaymentHTTPClient(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=self._timeout,
        ) as http:
            resp = await http.post(GATEWAY_BALANCES_PATH, json=body)

        if resp.status_code == 404:
            raise UnsupportedNetworkError(network=network)

        if not httpx.codes.is_success(resp.status_code):
            raise GatewayAPIError(
                message=f"Gateway /balances returned {resp.status_code}",
                status_code=resp.status_code,
                response_body=resp.text,
            )

        data = resp.json()
        balances = data.get("balances", [])
        total = 0
        available = 0
        formatted_total = "0 USDC"
        formatted_available = "0 USDC"
        if balances:
            bal = balances[0]
            # Circle returns "balance" field with string amount, no separate available field
            balance_str = bal.get("balance", "0")
            total = _to_int(balance_str)
            available = total  # Gateway balance is fully available
            from decimal import Decimal

            formatted_total = f"{Decimal(total) / Decimal(1_000_000):.6f} USDC"
            formatted_available = formatted_total
        return GatewayBalance(
            total=total,
            available=available,
            formatted_total=formatted_total,
            formatted_available=formatted_available,
        )


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _map_settlement_error(
    error_reason: str | None,
    transaction: str | None = None,
    payer: str | None = None,
) -> SettlementError:
    """
    Map a settlement error reason string to the appropriate exception type.
    """
    exc_class = _SETTLEMENT_ERROR_CODE_MAP.get(error_reason or "", SettlementError)
    # VerificationError subclasses accept (reason, payer); SettlementError accepts
    # (reason, transaction, payer).
    if issubclass(exc_class, VerificationError):
        return exc_class(
            reason=error_reason or "settlement_declined",
            payer=payer,
        )
    return exc_class(
        reason=error_reason or "settlement_declined",
        transaction=transaction,
        payer=payer,
    )
