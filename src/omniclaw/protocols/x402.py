"""X402Adapter - HTTP 402 Payment Required protocol support."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from omniclaw.core.exceptions import ProtocolError
from omniclaw.core.logging import get_logger
from omniclaw.core.types import (
    FeeLevel,
    PaymentMethod,
    PaymentResult,
    PaymentStatus,
)
from omniclaw.protocols.base import ProtocolAdapter

if TYPE_CHECKING:
    from omniclaw.core.config import Config
    from omniclaw.wallet.service import WalletService


# Header names
HEADER_PAYMENT_SIGNATURE = "PAYMENT-SIGNATURE"  # V2
HEADER_PAYMENT_RESPONSE = "PAYMENT-RESPONSE"   # V2
HEADER_PAYMENT_REQUIRED_V1 = "X-Payment-Required"  # V1 Legacy

# URL pattern for detecting x402-compatible endpoints
URL_PATTERN = re.compile(r"^https?://")


@dataclass
class PaymentRequirements:
    """Payment requirements parsed from a 402 response."""

    scheme: str
    network: str
    max_amount_required: str  # Smallest unit
    resource: str
    description: str
    recipient: str
    extra: dict[str, Any] | None = None

    @classmethod
    def from_response(cls, response: httpx.Response) -> PaymentRequirements:
        """Parse requirements from 402 response (Body or Header)."""
        # Try V2 Body (JSON)
        try:
            data = response.json()
            if "requirements" in data:
                data = data["requirements"]

            return cls(
                scheme=data.get("scheme", "exact"),
                network=data.get("network", ""),
                max_amount_required=data.get("maxAmountRequired", data.get("amount", "0")),
                resource=data.get("resource", str(response.url)),
                description=data.get("description", ""),
                recipient=data.get("paymentAddress", data.get("recipient", "")),
                extra=data.get("extra"),
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
                scheme=data.get("scheme", "exact"),
                network=data.get("network", ""),
                max_amount_required=data.get("maxAmountRequired", "0"),
                resource=data.get("resource", ""),
                description=data.get("description", ""),
                recipient=data.get("paymentAddress", data.get("recipient", "")),
                extra=data.get("extra"),
            )
        except Exception as e:
            raise ProtocolError(f"Failed to parse payment requirements: {e}") from e

    def get_amount_usdc(self) -> Decimal:
        """Get amount in USDC (assuming 6 decimals for USDC)."""
        try:
            # Amount is usually in smallest unit (e.g., for USDC with 6 decimals)
            amount_int = int(self.max_amount_required)
            return Decimal(amount_int) / Decimal(10**6)
        except Exception:
            return Decimal(self.max_amount_required)


@dataclass
class PaymentPayload:
    """
    Payment payload to send with the request.

    Sent in the PAYMENT-SIGNATURE header (V2) or X-Payment (V1).
    """

    x402_version: int = 2
    scheme: str = "exact"
    network: str = ""
    payload: dict = None  # Payment-specific payload
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

    def supports(self, recipient: str, source_network: Network | str | None = None, destination_chain: Network | str | None = None, **kwargs: Any) -> bool:
        """
        Check if recipient is a URL (potentially x402-enabled).

        Args:
            recipient: Potential URL
            **kwargs: Additional context

        Returns:
            True if recipient is a valid HTTP(S) URL
        """
        return bool(URL_PATTERN.match(recipient))

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
        """Execute an x402 payment (V2)."""
        url = recipient

        try:
            # Check for 402
            response, requirements = await self._request_with_402_check(
                url,
                method="GET",
                json=None,
                headers=None,
            )

            if response.status_code != 402:
                return PaymentResult(
                    success=True,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=Decimal("0"),
                    recipient=url,
                    method=self.method,
                    status=PaymentStatus.COMPLETED,
                    metadata={"http_status": response.status_code, "note": "No 402"},
                )

            if not requirements:
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=amount,
                    recipient=url,
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error="Server returned 402 but extraction failed",
                )

            # Validate Amount
            required_amount = requirements.get_amount_usdc()
            if required_amount > amount:
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=required_amount,
                    recipient=url,
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error=f"Required {required_amount} > Max {amount}",
                )

            # Transfer to seller
            payment_address = requirements.recipient
            if not payment_address:
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=required_amount,
                    recipient=url,
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error="No payment address found in requirements",
                )

            # Resolve network
            from omniclaw.core.types import Network
            if source_network:
                if isinstance(source_network, Network):
                    agent_network = source_network
                else:
                    agent_network = Network.from_string(str(source_network))
            else:
                agent_wallet = self._wallet_service.get_wallet(wallet_id)
                agent_network = Network.from_string(agent_wallet.blockchain)

            # Parse seller's network from requirements - MUST succeed
            seller_network_str = requirements.network.upper().replace("-", "_")
            try:
                seller_network = Network.from_string(seller_network_str)
            except Exception as e:
                return PaymentResult(
                    success=False,
                    transaction_id=None,
                    blockchain_tx=None,
                    amount=required_amount,
                    recipient=url,
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error=f"Invalid network in payment requirements: {requirements.network}",
                )

            # Check if cross-chain transfer is needed
            is_cross_chain = agent_network != seller_network

            if is_cross_chain:
                # Cross-chain: Use GatewayAdapter (CCTP)
                self._logger.info(
                    f"x402 cross-chain: {agent_network.value} → {seller_network.value}"
                )
                from omniclaw.protocols.gateway import GatewayAdapter
                
                gateway = GatewayAdapter(self._config, self._wallet_service)
                gateway_result = await gateway.execute(
                    wallet_id=wallet_id,
                    recipient=payment_address,
                    amount=required_amount,
                    purpose=purpose,
                    fee_level=fee_level,
                    wait_for_completion=True,
                    destination_chain=seller_network,
                    source_network=agent_network,
                )

                if not gateway_result.success:
                    return PaymentResult(
                        success=False,
                        transaction_id=gateway_result.transaction_id,
                        blockchain_tx=gateway_result.blockchain_tx,
                        amount=required_amount,
                        recipient=url,
                        method=self.method,
                        status=PaymentStatus.FAILED,
                        error=f"Cross-chain transfer failed: {gateway_result.error}",
                    )

                # Use gateway result for payment proof
                transfer_tx_hash = gateway_result.blockchain_tx
                transfer_tx_id = gateway_result.transaction_id
            else:
                # Same chain: Direct transfer
                transfer_result = self._wallet_service.transfer(
                    wallet_id=wallet_id,
                    destination_address=payment_address,
                    amount=required_amount,
                    fee_level=fee_level,
                    wait_for_completion=True,
                )

                if not transfer_result.success:
                    return PaymentResult(
                        success=False,
                        transaction_id=transfer_result.transaction.id
                        if transfer_result.transaction
                        else None,
                        blockchain_tx=transfer_result.tx_hash,
                        amount=required_amount,
                        recipient=url,
                        method=self.method,
                        status=PaymentStatus.FAILED,
                        error=f"Transfer failed: {transfer_result.error}",
                    )

                transfer_tx_hash = transfer_result.tx_hash
                transfer_tx_id = (
                    transfer_result.transaction.id if transfer_result.transaction else None
                )

            # Create Payload (V2)
            payload = PaymentPayload(
                x402_version=2,
                scheme=requirements.scheme,
                network=requirements.network,
                resource=url,
                payload={
                    "transactionHash": transfer_tx_hash,
                    "fromAddress": self._wallet_service.get_wallet(wallet_id).address,
                    "toAddress": payment_address,
                    "amount": str(required_amount),
                },
            )

            # Retry with PAYMENT-SIGNATURE
            payment_header = payload.to_header()
            headers = {HEADER_PAYMENT_SIGNATURE: payment_header}

            client = await self._get_http_client()
            final_response = await client.request(
                "GET",
                url,
                headers=headers,
            )

            if final_response.status_code == 200:
                # Parse response body
                try:
                    response_data = final_response.json()
                except Exception:
                    response_data = final_response.text
                
                return PaymentResult(
                    success=True,
                    transaction_id=transfer_tx_id,
                    blockchain_tx=transfer_tx_hash,
                    amount=required_amount,
                    recipient=url,
                    method=self.method,
                    status=PaymentStatus.COMPLETED,
                    resource_data=response_data,  # Store the actual API response
                    metadata={
                        "http_status": final_response.status_code,
                        "payment_response": final_response.headers.get(HEADER_PAYMENT_RESPONSE, ""),
                        "cross_chain": is_cross_chain,
                    },
                )
            else:
                return PaymentResult(
                    success=False,
                    transaction_id=transfer_tx_id,
                    blockchain_tx=transfer_tx_hash,
                    amount=required_amount,
                    recipient=url,
                    method=self.method,
                    status=PaymentStatus.FAILED,
                    error=f"Rejected: HTTP {final_response.status_code}",
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
            response, requirements = await self._request_with_402_check(recipient)

            if response.status_code != 402:
                result["would_succeed"] = True
                result["reason"] = "Resource does not require payment"
                result["http_status"] = response.status_code
                return result

            if requirements:
                required_amount = requirements.get_amount_usdc()
                result["required_amount"] = str(required_amount)
                result["payment_address"] = requirements.recipient
                result["description"] = requirements.description

                if required_amount <= amount:
                    # Check wallet balance
                    balance = self._wallet_service.get_usdc_balance_amount(wallet_id)
                    if balance >= required_amount:
                        result["would_succeed"] = True
                        result["current_balance"] = str(balance)
                    else:
                        result["would_succeed"] = False
                        result["reason"] = f"Insufficient balance: {balance} < {required_amount}"
                else:
                    result["would_succeed"] = False
                    result["reason"] = f"Required amount {required_amount} exceeds max {amount}"
            else:
                result["would_succeed"] = False
                result["reason"] = "No payment requirements in 402 response"

        except Exception as e:
            result["would_succeed"] = False
            result["reason"] = f"Error checking URL: {e}"

        return result

    def get_priority(self) -> int:
        """X402 has higher priority than transfer for URLs."""
        return 10


# Export for convenience
__all__ = ["X402Adapter", "PaymentRequirements", "PaymentPayload"]
