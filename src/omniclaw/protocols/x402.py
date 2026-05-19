"""X402Adapter - HTTP 402 Payment Required protocol support."""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from omniclaw.core.exceptions import ProtocolError, WalletError
from omniclaw.core.idempotency import derive_idempotency_key
from omniclaw.core.logging import get_logger
from omniclaw.core.types import (
    FeeLevel,
    Network,
    PaymentMethod,
    PaymentResult,
    PaymentStatus,
    network_to_caip2,
)
from omniclaw.protocols.base import ProtocolAdapter
from omniclaw.protocols.x402_compat import patch_x402_web3_compat

if TYPE_CHECKING:
    from omniclaw.core.config import Config
    from omniclaw.wallet.service import WalletService


# Header names
HEADER_PAYMENT_SIGNATURE = "PAYMENT-SIGNATURE"  # V2
HEADER_PAYMENT_RESPONSE = "PAYMENT-RESPONSE"  # V2
HEADER_PAYMENT_REQUIRED_V1 = "X-Payment-Required"  # V1 Legacy

# URL pattern for detecting x402-compatible endpoints
HTTPS_URL_PATTERN = re.compile(r"^https://")
HTTP_URL_PATTERN = re.compile(r"^http://")

_CAIP2_TO_NETWORK: dict[str, Network] = {
    "eip155:1": Network.ETH,
    "eip155:11155111": Network.ETH_SEPOLIA,
    "eip155:43114": Network.AVAX,
    "eip155:43113": Network.AVAX_FUJI,
    "eip155:137": Network.MATIC,
    "eip155:80002": Network.MATIC_AMOY,
    "eip155:42161": Network.ARB,
    "eip155:421614": Network.ARB_SEPOLIA,
    "eip155:8453": Network.BASE,
    "eip155:84532": Network.BASE_SEPOLIA,
    "eip155:10": Network.OP,
    "eip155:11155420": Network.OP_SEPOLIA,
    "eip155:5042002": Network.ARC_TESTNET,
}


def _resolve_network(value: str) -> Network | None:
    if not value:
        return None
    value_norm = value.strip().lower()
    if value_norm in _CAIP2_TO_NETWORK:
        return _CAIP2_TO_NETWORK[value_norm]
    try:
        return Network.from_string(value)
    except Exception:
        return None


@dataclass(frozen=True)
class AcceptedPaymentKind:
    """A single accepted x402 payment kind advertised by the seller."""

    scheme: str
    network: str
    amount_atomic: str
    recipient: str
    extra: dict[str, Any] | None = None
    asset: str | None = None
    max_timeout_seconds: int | None = None

    @property
    def facilitator_name(self) -> str:
        extra = self.extra or {}
        return str(extra.get("name") or "").strip()

    @property
    def is_gateway_batched(self) -> bool:
        return self.facilitator_name == "GatewayWalletBatched"

    def get_amount_usdc(self) -> Decimal:
        try:
            return Decimal(int(self.amount_atomic)) / Decimal(10**6)
        except Exception:
            return Decimal(self.amount_atomic)


@dataclass
class PaymentRequirements:
    """Payment requirements parsed from a 402 response."""

    accepts: tuple[AcceptedPaymentKind, ...]
    resource: str
    description: str = ""
    x402_version: int = 2

    @classmethod
    def from_response(cls, response: httpx.Response) -> PaymentRequirements:
        """Parse requirements from 402 response (V2 Header, V2 Body, or V1 Header)."""
        # Try V2 Header (PAYMENT-REQUIRED, base64-encoded JSON)
        # HTTP headers are case-insensitive per RFC 7230
        payment_required_v2 = response.headers.get("payment-required") or response.headers.get(
            "PAYMENT-REQUIRED"
        )
        if payment_required_v2:
            try:
                decoded = base64.b64decode(payment_required_v2)
                data = json.loads(decoded)
                # V2 format: {x402Version, accepts: [{scheme, network, asset, amount, payTo, ...}]}
                accepts = data.get("accepts", [])
                if accepts:
                    return cls(
                        accepts=tuple(cls._parse_kind(kind) for kind in accepts),
                        resource=str(response.url),
                        description="",
                        x402_version=int(data.get("x402Version", 2) or 2),
                    )
            except Exception:
                pass

        # Try V2 Body (JSON)
        try:
            data = response.json()
            if "requirements" in data:
                data = data["requirements"]

            # Handle V2 body with 'accepts' array
            accepts = data.get("accepts")
            if accepts and isinstance(accepts, list):
                return cls(
                    accepts=tuple(cls._parse_kind(kind) for kind in accepts),
                    resource=str(response.url),
                    description="",
                    x402_version=int(data.get("x402Version", 2) or 2),
                )

            # Legacy body format
            return cls(
                accepts=(
                    AcceptedPaymentKind(
                        scheme=data.get("scheme", "exact"),
                        network=data.get("network", ""),
                        amount_atomic=data.get("maxAmountRequired", data.get("amount", "0")),
                        recipient=data.get("paymentAddress", data.get("recipient", "")),
                        extra=data.get("extra"),
                    ),
                ),
                resource=data.get("resource", str(response.url)),
                description=data.get("description", ""),
                x402_version=2,
            )
        except Exception:
            pass

        # Try V1 Header
        header_val = response.headers.get(HEADER_PAYMENT_REQUIRED_V1)
        if header_val:
            return cls.from_header(header_val)

        raise ProtocolError(
            "No valid x402 payment requirements found in 402 response (Body or Header)"
        )

    @classmethod
    def from_header(cls, header_value: str) -> PaymentRequirements:
        """Parse from base64-encoded header value (V1)."""
        try:
            decoded = base64.b64decode(header_value)
            data = json.loads(decoded)
            return cls(
                accepts=(
                    AcceptedPaymentKind(
                        scheme=data.get("scheme", "exact"),
                        network=data.get("network", ""),
                        amount_atomic=data.get("maxAmountRequired", "0"),
                        recipient=data.get("paymentAddress", data.get("recipient", "")),
                        extra=data.get("extra"),
                    ),
                ),
                resource=data.get("resource", ""),
                description=data.get("description", ""),
                x402_version=1,
            )
        except Exception as e:
            raise ProtocolError(f"Failed to parse payment requirements: {e}") from e

    @staticmethod
    def _parse_kind(kind: dict[str, Any]) -> AcceptedPaymentKind:
        return AcceptedPaymentKind(
            scheme=kind.get("scheme", "exact"),
            network=kind.get("network", ""),
            amount_atomic=kind.get("amount", "0"),
            recipient=kind.get("payTo", ""),
            extra=kind.get("extra"),
            asset=kind.get("asset"),
            max_timeout_seconds=kind.get("maxTimeoutSeconds"),
        )

    def select_preferred_kind(
        self,
        *,
        prefer_gateway: bool = False,
        source_network: Network | None = None,
    ) -> AcceptedPaymentKind | None:
        """
        Select the best supported x402 kind from the seller's advertised accepts list.

        Buyer-side policy:
        - If prefer_gateway=True, prefer GatewayWalletBatched on the buyer's current network
        - Otherwise ignore GatewayWalletBatched and choose a non-gateway exact kind
        - Prefer same-network kinds before cross-network kinds
        """
        if not self.accepts:
            return None

        target_caip2 = None
        if source_network is not None:
            target_caip2 = {
                Network.ETH: "eip155:1",
                Network.ETH_SEPOLIA: "eip155:11155111",
                Network.AVAX: "eip155:43114",
                Network.AVAX_FUJI: "eip155:43113",
                Network.MATIC: "eip155:137",
                Network.MATIC_AMOY: "eip155:80002",
                Network.ARB: "eip155:42161",
                Network.ARB_SEPOLIA: "eip155:421614",
                Network.BASE: "eip155:8453",
                Network.BASE_SEPOLIA: "eip155:84532",
                Network.OP: "eip155:10",
                Network.OP_SEPOLIA: "eip155:11155420",
                Network.ARC_TESTNET: "eip155:5042002",
            }.get(source_network)

        candidates = [
            kind
            for kind in self.accepts
            if kind.scheme == "exact"
            and (kind.is_gateway_batched if prefer_gateway else not kind.is_gateway_batched)
        ]
        if not candidates:
            return None

        same_network = [
            kind for kind in candidates if target_caip2 and kind.network == target_caip2
        ]
        if same_network:
            return same_network[0]
        return candidates[0]


def _is_allowed_insecure_http(url: str) -> bool:
    """Allow HTTP URLs only for localhost/private networks in non-production."""
    if not HTTP_URL_PATTERN.match(url):
        return False
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1"}:
        return True

    env = os.environ.get("OMNICLAW_ENV", "development").lower()
    if env in {"prod", "production", "mainnet"}:
        return False

    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return host.endswith(".local")


@dataclass
class PaymentPayload:
    """
    Payment payload to send with the request.

    Sent in the PAYMENT-SIGNATURE header (V2) or X-Payment (V1).
    """

    x402_version: int = 2
    scheme: str = "exact"
    network: str = ""
    payload: dict | None = None  # Payment-specific payload
    resource: str = ""

    def to_header(self) -> str:
        """Encode as base64 header value."""
        data = {
            "x402Version": self.x402_version,
            "scheme": self.scheme,
            "network": self.network,
            "payload": self.payload or {},
            "resource": self.resource,
        }
        json_str = json.dumps(data)
        return base64.b64encode(json_str.encode()).decode()


class _OmniClawExactSigner:
    """Minimal EVM signer for the upstream x402 exact client."""

    def __init__(self, private_key: str) -> None:
        from eth_account import Account

        self._private_key = private_key
        self._account = Account.from_key(private_key)

    @property
    def address(self) -> str:
        return self._account.address

    def sign_typed_data(
        self,
        domain: Any,
        types: dict[str, list[Any]],
        primary_type: str,
        message: dict[str, Any],
    ) -> bytes:
        from eth_account import Account
        from eth_account.messages import encode_typed_data

        if isinstance(domain, dict):
            domain_dict = domain
        else:
            domain_dict = {
                "name": getattr(domain, "name", None),
                "chainId": getattr(domain, "chain_id", None),
                "verifyingContract": getattr(domain, "verifying_contract", None),
            }
            domain_version = getattr(domain, "version", None)
            if domain_version:
                domain_dict["version"] = domain_version
        domain_dict = {key: value for key, value in domain_dict.items() if value is not None}

        domain_field_map = {
            "name": {"name": "name", "type": "string"},
            "version": {"name": "version", "type": "string"},
            "chainId": {"name": "chainId", "type": "uint256"},
            "verifyingContract": {"name": "verifyingContract", "type": "address"},
            "salt": {"name": "salt", "type": "bytes32"},
        }
        full_types: dict[str, list[dict[str, str]]] = {
            "EIP712Domain": [
                domain_field_map[key] for key in domain_dict if key in domain_field_map
            ]
        }
        for type_name, fields in types.items():
            full_types[type_name] = [
                {"name": field.name, "type": field.type} if hasattr(field, "name") else field
                for field in fields
            ]

        message_copy = dict(message)
        if "nonce" in message_copy and isinstance(message_copy["nonce"], bytes):
            message_copy["nonce"] = "0x" + message_copy["nonce"].hex()

        signable = encode_typed_data(
            full_message={
                "types": full_types,
                "primaryType": primary_type,
                "domain": domain_dict,
                "message": message_copy,
            }
        )
        signed = Account.sign_message(signable, self._private_key)
        return bytes(signed.signature)


class X402Adapter(ProtocolAdapter):
    """
    Adapter for x402 HTTP Payment Required protocol.

    Handles payments to URLs that return HTTP 402 status codes.

    Flow:
    1. Request the URL (GET/POST)
    2. If 402 received, parse X-Payment-Required header
    3. Create payment using Circle wallet
    4. Send payment proof in X-Payment header
    5. Receive response with resource
    """

    def __init__(
        self,
        config: Config,
        wallet_service: WalletService,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Initialize X402Adapter.

        Args:
            config: SDK configuration
            wallet_service: Wallet service for payments
            http_client: Optional custom HTTP client
        """
        self._config = config
        self._wallet_service = wallet_service
        self._http_client = http_client
        self._logger = get_logger("x402")

    @property
    def method(self) -> PaymentMethod:
        """Return payment method type."""
        return PaymentMethod.X402

    def supports(
        self,
        recipient: str,
        source_network: Network | str | None = None,
        destination_chain: Network | str | None = None,
        **kwargs: Any,
    ) -> bool:
        """
        Check if recipient is a URL (potentially x402-enabled).

        Args:
            recipient: Potential URL
            **kwargs: Additional context

        Returns:
            True if recipient is a valid HTTP(S) URL
        """
        return bool(HTTPS_URL_PATTERN.match(recipient) or _is_allowed_insecure_http(recipient))

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def _request_with_402_check(
        self,
        url: str,
        method: str = "GET",
        **kwargs: Any,
    ) -> tuple[httpx.Response, PaymentRequirements | None]:
        """Make request and parse requirements if 402."""
        client = await self._get_http_client()
        response = await client.request(method, url, **kwargs)

        if response.status_code == 402:
            try:
                requirements = PaymentRequirements.from_response(response)
                return response, requirements
            except ProtocolError:
                return response, None

        return response, None

    @staticmethod
    def _atomic_to_decimal(amount_atomic: str) -> Decimal:
        return Decimal(int(amount_atomic)) / Decimal(10**6)

    @staticmethod
    def _decimal_to_atomic(amount_decimal: Decimal) -> int:
        return int((amount_decimal * Decimal(10**6)).to_integral_value())

    @staticmethod
    def _decode_response_body(response: httpx.Response) -> Any:
        try:
            return response.json()
        except Exception:
            return response.text

    @staticmethod
    def _requirement_value(requirements: Any, *names: str) -> Any:
        for name in names:
            if isinstance(requirements, dict) and name in requirements:
                return requirements[name]
            if hasattr(requirements, name):
                return getattr(requirements, name)
        return None

    def _resolve_agent_network(
        self,
        wallet_id: str,
        source_network: Network | str | None,
    ) -> Network | None:
        if source_network:
            if isinstance(source_network, Network):
                return source_network
            return Network.from_string(str(source_network))

        try:
            agent_wallet = self._wallet_service.get_wallet(wallet_id)
            return Network.from_string(agent_wallet.blockchain)
        except Exception:
            return None

    def _get_generic_x402_private_key(self) -> str:
        private_key = self._config.nanopayments_private_key or os.environ.get(
            "OMNICLAW_PRIVATE_KEY"
        )
        if not private_key:
            raise WalletError("OMNICLAW_PRIVATE_KEY is required for generic x402 exact payments")
        if not private_key.startswith("0x"):
            private_key = f"0x{private_key}"
        return private_key

    def _build_sdk_http_client(
        self,
        *,
        max_amount: Decimal,
        preferred_network: str | None,
    ) -> tuple[Any, dict[str, Any]]:
        patch_x402_web3_compat()

        from x402.client import max_amount as x402_max_amount
        from x402.client import prefer_network as x402_prefer_network
        from x402.client import prefer_scheme as x402_prefer_scheme
        from x402.client import x402Client
        from x402.http import x402HTTPClient
        from x402.mechanisms.evm.exact.client import ExactEvmScheme

        x402_client = x402Client()
        x402_client.register(
            "eip155:*",
            ExactEvmScheme(_OmniClawExactSigner(self._get_generic_x402_private_key())),
        )
        x402_client.register_policy(x402_prefer_scheme("exact"))
        if preferred_network:
            x402_client.register_policy(x402_prefer_network(preferred_network))
        x402_client.register_policy(x402_max_amount(self._decimal_to_atomic(max_amount)))

        selection_state: dict[str, Any] = {}

        async def _capture_selection(ctx: Any) -> None:
            selection_state["requirements"] = ctx.selected_requirements

        x402_client.on_after_payment_creation(_capture_selection)
        return x402HTTPClient(x402_client), selection_state

    @staticmethod
    def _payload_has_accepted(payment_payload: Any) -> bool:
        accepted = getattr(payment_payload, "accepted", None)
        if accepted is not None:
            return True
        if hasattr(payment_payload, "model_dump"):
            try:
                dumped = payment_payload.model_dump(by_alias=True, exclude_none=True)
                return bool(dumped.get("accepted"))
            except Exception:
                return False
        return False

    @classmethod
    def _ensure_v2_payload_has_accepted(
        cls,
        *,
        payment_payload: Any,
        selected_requirements: Any,
        payment_required: Any,
    ) -> Any:
        """
        Ensure x402 v2 retry payloads include the selected `accepted` requirement.

        x402 v2 makes PaymentPayload.accepted required. Some SDK/client
        combinations have returned a signed payload object without that field,
        which causes strict sellers to reject the retry request before
        settlement.
        """
        if getattr(payment_payload, "x402_version", 2) != 2:
            return payment_payload
        if cls._payload_has_accepted(payment_payload):
            return payment_payload

        try:
            from x402.schemas import PaymentPayload as X402PaymentPayload

            payload_data: dict[str, Any]
            if hasattr(payment_payload, "model_dump"):
                payload_data = payment_payload.model_dump(by_alias=True, exclude_none=True)
            else:
                payload_data = dict(getattr(payment_payload, "__dict__", {}))

            payload_data["accepted"] = selected_requirements
            if not payload_data.get("resource"):
                resource = getattr(payment_required, "resource", None)
                if resource is not None:
                    payload_data["resource"] = resource

            return X402PaymentPayload.model_validate(payload_data)
        except Exception:
            with suppress(Exception):
                payment_payload.accepted = selected_requirements
            return payment_payload

    @staticmethod
    def _selected_requirements_from_payload_or_response(
        *,
        payment_payload: Any,
        payment_required: Any,
        selection_state: dict[str, Any],
    ) -> Any:
        selected_requirements = selection_state.get("requirements") or getattr(
            payment_payload, "accepted", None
        )
        if selected_requirements is not None:
            return selected_requirements

        accepts = getattr(payment_required, "accepts", None)
        if accepts:
            return accepts[0]

        raise ProtocolError("x402 payment payload did not include accepted requirements")

    def _resolve_exact_balance_rpc_url(self, selected_network: Network | None) -> str | None:
        config_rpc_url = getattr(self._config, "rpc_url", None)
        config_network = _resolve_network(str(getattr(self._config, "network", "") or ""))
        if config_rpc_url and (selected_network is None or config_network == selected_network):
            return str(config_rpc_url)

        if selected_network is None:
            return str(config_rpc_url) if config_rpc_url else None

        return str(config_rpc_url) if config_rpc_url else None

    def _check_direct_exact_balance(self, selected_requirements: Any) -> dict[str, Any]:
        """
        Best-effort direct-wallet token balance check for x402 exact payments.

        This is used by simulate/inspect only. It prevents readiness reports from
        claiming a buyer is ready when the signer can produce a payload but the
        wallet cannot actually settle the selected requirement.
        """
        if os.environ.get("OMNICLAW_X402_BALANCE_CHECK", "true").lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            return {"balance_check": "skipped", "balance_check_reason": "disabled"}

        network_value = str(self._requirement_value(selected_requirements, "network") or "")
        asset = self._requirement_value(selected_requirements, "asset")
        amount_value = self._requirement_value(selected_requirements, "amount")
        selected_network = _resolve_network(network_value)
        if not selected_network or not asset or amount_value is None:
            return {
                "balance_check": "skipped",
                "balance_check_reason": "missing selected network, asset, or amount",
            }

        rpc_url = self._resolve_exact_balance_rpc_url(selected_network)
        if not rpc_url:
            return {
                "balance_check": "skipped",
                "balance_check_reason": f"no RPC URL configured for {network_value}",
            }

        try:
            private_key = self._get_generic_x402_private_key()

            from eth_account import Account
            from web3 import Web3

            account = Account.from_key(private_key)
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
            token = w3.eth.contract(
                address=Web3.to_checksum_address(str(asset)),
                abi=[
                    {
                        "inputs": [{"name": "account", "type": "address"}],
                        "name": "balanceOf",
                        "outputs": [{"type": "uint256"}],
                        "stateMutability": "view",
                        "type": "function",
                    }
                ],
            )
            balance_atomic = int(
                token.functions.balanceOf(Web3.to_checksum_address(account.address)).call()
            )
            required_atomic = int(str(amount_value))
            balance_decimal = self._atomic_to_decimal(str(balance_atomic))
            required_decimal = self._atomic_to_decimal(str(required_atomic))
            has_enough = balance_atomic >= required_atomic
            return {
                "balance_check": "passed" if has_enough else "failed",
                "buyer_address": account.address,
                "direct_wallet_balance_atomic": str(balance_atomic),
                "direct_wallet_balance": str(balance_decimal),
                "direct_wallet_required_atomic": str(required_atomic),
                "direct_wallet_required": str(required_decimal),
                "direct_wallet_has_enough": has_enough,
                "direct_wallet_rpc_url": rpc_url,
            }
        except Exception as exc:
            return {
                "balance_check": "skipped",
                "balance_check_reason": f"balance read failed: {exc}",
            }

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
        """Execute an x402 exact payment using the upstream x402 SDK."""
        url = recipient
        strict_settlement = bool(getattr(self._config, "payment_strict_settlement", False))
        request_method = str(kwargs.get("http_method", kwargs.get("method", "GET"))).upper()
        request_headers = kwargs.get("request_headers") or kwargs.get("headers")
        request_json = kwargs.get("request_json")
        request_body = kwargs.get("request_body", kwargs.get("body"))
        agent_network = self._resolve_agent_network(wallet_id, source_network)
        agent_caip2 = network_to_caip2(agent_network)

        try:
            client = await self._get_http_client()
            initial_response = await client.request(
                request_method,
                url,
                headers=request_headers,
                json=request_json,
                content=request_body,
            )

            if initial_response.status_code != 402:
                return PaymentResult(
                    success=True,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=Decimal("0"),
                    recipient=url,
                    method=self.method,
                    status=PaymentStatus.COMPLETED,
                    metadata={"http_status": initial_response.status_code, "note": "No 402"},
                )

            x402_http_client, selection_state = self._build_sdk_http_client(
                max_amount=amount,
                preferred_network=agent_caip2,
            )

            await initial_response.aread()
            get_header, body_data = x402_http_client._handle_402_common(
                dict(initial_response.headers),
                initial_response.content or None,
            )
            payment_required = x402_http_client.get_payment_required_response(get_header, body_data)
            canonical_idempotency_key = idempotency_key or derive_idempotency_key(
                "x402",
                wallet_id,
                url,
                request_method,
                request_json,
                request_body,
                agent_caip2,
            )
            payment_payload = await x402_http_client.create_payment_payload(payment_required)
            selected_requirements = self._selected_requirements_from_payload_or_response(
                payment_payload=payment_payload,
                payment_required=payment_required,
                selection_state=selection_state,
            )
            payment_payload = self._ensure_v2_payload_has_accepted(
                payment_payload=payment_payload,
                selected_requirements=selected_requirements,
                payment_required=payment_required,
            )
            required_amount = self._atomic_to_decimal(str(selected_requirements.amount))
            payment_address = str(selected_requirements.pay_to)

            retry_headers: dict[str, str] = {}
            if isinstance(request_headers, dict):
                for key, value in request_headers.items():
                    retry_headers[str(key)] = str(value)
            retry_headers.update(x402_http_client.encode_payment_signature_header(payment_payload))

            final_response = await client.request(
                request_method,
                url,
                headers=retry_headers,
                json=request_json,
                content=request_body,
            )

            settle_response = None
            settle_error: str | None = None
            try:
                settle_response = x402_http_client.get_payment_settle_response(
                    lambda name: final_response.headers.get(name)
                )
            except Exception as exc:
                settle_error = str(exc)

            response_data = self._decode_response_body(final_response)
            settled_ok = bool(settle_response and settle_response.success)
            transaction_id = (
                str(settle_response.transaction)
                if settle_response and getattr(settle_response, "transaction", None)
                else None
            )
            settlement_network = (
                str(settle_response.network)
                if settle_response and getattr(settle_response, "network", None)
                else None
            )
            payer = (
                str(settle_response.payer)
                if settle_response and getattr(settle_response, "payer", None)
                else None
            )
            metadata = {
                "http_status": final_response.status_code,
                "scheme": str(selected_requirements.scheme),
                "payment_network": str(selected_requirements.network),
                "settlement_network": settlement_network,
                "payment_asset": str(selected_requirements.asset),
                "amount_atomic": str(selected_requirements.amount),
                "payer": payer,
                "pay_to": payment_address,
                "idempotency_key": canonical_idempotency_key,
            }

            if 200 <= final_response.status_code < 300:
                if strict_settlement and not settled_ok:
                    error_message = (
                        (
                            getattr(settle_response, "error_message", None)
                            if settle_response
                            else None
                        )
                        or (
                            getattr(settle_response, "error_reason", None)
                            if settle_response
                            else None
                        )
                        or settle_error
                        or "Missing PAYMENT-RESPONSE header"
                    )
                    return PaymentResult(
                        success=False,
                        transaction_id=transaction_id,
                        blockchain_tx=transaction_id,
                        amount=required_amount,
                        recipient=url,
                        method=self.method,
                        status=PaymentStatus.FAILED_FINAL,
                        error=f"x402 settlement failed: {error_message}",
                        resource_data=response_data,
                        metadata=metadata,
                    )

                return PaymentResult(
                    success=True,
                    transaction_id=transaction_id,
                    blockchain_tx=transaction_id,
                    amount=required_amount,
                    recipient=url,
                    method=self.method,
                    status=PaymentStatus.SETTLED if strict_settlement else PaymentStatus.COMPLETED,
                    resource_data=response_data,
                    metadata=metadata,
                )

            error_message = (
                (getattr(settle_response, "error_message", None) if settle_response else None)
                or (getattr(settle_response, "error_reason", None) if settle_response else None)
                or f"Rejected: HTTP {final_response.status_code}"
            )
            return PaymentResult(
                success=False,
                transaction_id=transaction_id,
                blockchain_tx=transaction_id,
                amount=required_amount,
                recipient=url,
                method=self.method,
                status=PaymentStatus.FAILED_FINAL if strict_settlement else PaymentStatus.FAILED,
                error=f"x402 payment rejected: {error_message}",
                resource_data=response_data,
                metadata=metadata,
            )

        except Exception as e:
            return PaymentResult(
                success=False,
                transaction_id=None,
                blockchain_tx=None,
                amount=amount,
                recipient=url,
                method=self.method,
                status=PaymentStatus.FAILED,
                error=f"x402 error: {str(e)}",
            )

    async def simulate(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Simulate an x402 payment.

        Makes a request to check if the URL requires payment and returns
        the payment requirements without actually paying.
        """
        result: dict[str, Any] = {
            "method": self.method.value,
            "recipient": recipient,
            "amount": str(amount),
        }

        if not self.supports(recipient):
            result["would_succeed"] = False
            result["reason"] = f"Invalid URL format: {recipient}"
            return result

        try:
            response, _ = await self._request_with_402_check(recipient)

            if response.status_code != 402:
                result["would_succeed"] = True
                result["reason"] = "Resource does not require payment"
                result["http_status"] = response.status_code
                return result

            agent_network = self._resolve_agent_network(wallet_id, kwargs.get("source_network"))
            agent_caip2 = network_to_caip2(agent_network)
            x402_http_client, selection_state = self._build_sdk_http_client(
                max_amount=amount,
                preferred_network=agent_caip2,
            )
            await response.aread()
            get_header, body_data = x402_http_client._handle_402_common(
                dict(response.headers),
                response.content or None,
            )
            payment_required = x402_http_client.get_payment_required_response(get_header, body_data)
            payment_payload = await x402_http_client.create_payment_payload(payment_required)
            selected_requirements = self._selected_requirements_from_payload_or_response(
                payment_payload=payment_payload,
                payment_required=payment_required,
                selection_state=selection_state,
            )

            required_amount = self._atomic_to_decimal(str(selected_requirements.amount))
            result["would_succeed"] = True
            result["required_amount"] = str(required_amount)
            result["payment_address"] = str(selected_requirements.pay_to)
            result["payment_network"] = str(selected_requirements.network)
            result["payment_asset"] = str(selected_requirements.asset)
            result["scheme"] = str(selected_requirements.scheme)
            balance_check = self._check_direct_exact_balance(selected_requirements)
            result.update(balance_check)
            if balance_check.get("balance_check") == "failed":
                result["would_succeed"] = False
                result["reason"] = (
                    "Buyer can create a valid x402 payment payload, but the direct wallet "
                    f"has {balance_check.get('direct_wallet_balance')} USDC and needs "
                    f"{balance_check.get('direct_wallet_required')} USDC on "
                    f"{selected_requirements.network}."
                )
            elif balance_check.get("balance_check") == "passed":
                result["reason"] = (
                    "Buyer can create a valid x402 payment payload and has enough direct "
                    "wallet USDC for the selected requirement."
                )
            else:
                result["reason"] = (
                    "Buyer can create a valid x402 payment payload. "
                    "Direct wallet balance check was skipped; execution still depends on "
                    "the remote payment handler and on-chain balance."
                )

        except Exception as e:
            result["would_succeed"] = False
            result["reason"] = f"Error checking URL: {e}"

        return result

    def get_priority(self) -> int:
        """X402 has higher priority than transfer for URLs."""
        return 10


# Export for convenience
__all__ = ["X402Adapter", "PaymentRequirements", "PaymentPayload"]
