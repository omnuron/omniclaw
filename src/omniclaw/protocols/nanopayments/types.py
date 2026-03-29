"""
Type definitions for Circle Gateway Nanopayments.

All types match Circle's x402 v2 protocol specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# =============================================================================
# PAYMENT REQUIREMENTS (from 402 response / seller side)
# =============================================================================


@dataclass(frozen=True)
class PaymentRequirementsExtra:
    """
    Extra metadata for Circle Gateway batched payments.

    The 'name' field is CRITICAL: it identifies this as a GatewayWalletBatched
    payment vs a standard on-chain payment.

    Attributes:
        name: Must be 'GatewayWalletBatched' for Circle batched payments.
        version: Scheme version, typically '1'.
        verifying_contract: The Gateway Wallet contract address on the target chain.
            This is NOT the USDC token address — they are different contracts.
    """

    name: str
    """Scheme identifier. Must be 'GatewayWalletBatched'."""

    version: str
    """Scheme version, typically '1'."""

    verifying_contract: str
    """
    Gateway Wallet contract address on the target blockchain.
    Used as the EIP-712 verifying contract for signature verification.
    """

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentRequirementsExtra:
        """Create from dict."""
        return cls(
            name=data.get("name", ""),
            version=data.get("version", ""),
            verifying_contract=data.get("verifyingContract", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "verifyingContract": self.verifying_contract,
        }


@dataclass(frozen=True)
class PaymentRequirementsKind:
    """
    A single accepted payment method from the server's 402 response.

    The 'accepts' array in a 402 response contains one or more of these.
    The client picks the one that matches their network/wallet.
    """

    scheme: str
    """Payment scheme. Always 'exact' for fixed-price payments."""

    network: str
    """
    CAIP-2 network identifier, e.g. 'eip155:5042002' for Arc Testnet.
    Format: 'eip155:<chainId>'
    """

    asset: str
    """
    USDC token contract address on this network.
    Different on each chain — fetch from /v1/x402/supported.
    """

    amount: str
    """
    Payment amount in USDC atomic units (6 decimals).
    e.g. '1000' = 0.001 USDC = $0.001.
    """

    max_timeout_seconds: int
    """
    Maximum validity window for the payment authorization.
    Must be 345600 (4 days) for Circle Gateway.
    """

    pay_to: str
    """Seller's wallet address that receives the payment."""

    extra: PaymentRequirementsExtra
    """Gateway-specific metadata."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentRequirementsKind:
        """Create from dict."""
        extra_data = data.get("extra", {})
        return cls(
            scheme=data.get("scheme", ""),
            network=data.get("network", ""),
            asset=data.get("asset", ""),
            amount=data.get("amount", ""),
            max_timeout_seconds=data.get("maxTimeoutSeconds", 0),
            pay_to=data.get("payTo", ""),
            extra=PaymentRequirementsExtra.from_dict(extra_data),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "scheme": self.scheme,
            "network": self.network,
            "asset": self.asset,
            "amount": self.amount,
            "maxTimeoutSeconds": self.max_timeout_seconds,
            "payTo": self.pay_to,
            "extra": self.extra.to_dict(),
        }


@dataclass(frozen=True)
class PaymentRequirements:
    """
    Complete payment requirements parsed from a 402 response.

    Parsed from the JSON body of a 402 response.
    Contains one or more accepted payment methods.
    """

    x402_version: int
    """x402 protocol version. Should be 2."""

    accepts: tuple[PaymentRequirementsKind, ...]
    """All payment methods accepted by the server."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentRequirements:
        """Create from dict."""
        accepts_list = data.get("accepts", [])
        accepts = tuple(PaymentRequirementsKind.from_dict(a) for a in accepts_list)
        return cls(
            x402_version=data.get("x402Version", 2),
            accepts=accepts,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "x402Version": self.x402_version,
            "accepts": [a.to_dict() for a in self.accepts],
        }

    def find_gateway_kind(self) -> PaymentRequirementsKind | None:
        """
        Find the first accepted kind that uses Circle Gateway batching.

        Returns:
            The PaymentRequirementsKind with extra.name == "GatewayWalletBatched",
            or None if not found.
        """
        for kind in self.accepts:
            if kind.extra.name == "GatewayWalletBatched":
                return kind
        return None


# =============================================================================
# EIP-3009 AUTHORIZATION (buyer side)
# =============================================================================


@dataclass(frozen=True)
class EIP3009Authorization:
    """
    EIP-3009 TransferWithAuthorization message.

    This is the core EIP-3009 structure that the buyer signs.
    The signature authorizes Circle Gateway to transfer USDC from their
    Gateway balance to the seller.

    Attributes:
        from_address: Buyer's EOA address (the payer).
        to: Seller's address from 'payTo' field in requirements.
        value: Amount in USDC atomic units as string.
        valid_after: Unix timestamp when authorization becomes valid. '0' = immediate.
        valid_before: Unix timestamp when authorization expires.
            MUST be at least 3 days in the future for Gateway.
        nonce: Random 32-byte value for replay protection.
            Must be unique per (from, to) pair.
    """

    from_address: str
    """Buyer's EOA address."""

    to: str
    """Seller's address (payTo from requirements)."""

    value: str
    """Amount in USDC atomic units (6 decimals)."""

    valid_after: str
    """Unix timestamp when valid. '0' = immediately valid."""

    valid_before: str
    """
    Unix timestamp when authorization expires.
    MUST be >= now + 3 days for Gateway to accept it.
    """

    nonce: str
    """
    Random 32-byte value (64 hex chars with 0x prefix).
    Provides replay protection.
    """

    @classmethod
    def create(
        cls,
        from_address: str,
        to: str,
        value: str,
        valid_before: int,
        nonce: str,
    ) -> EIP3009Authorization:
        """
        Factory method to create an authorization with valid_after=0.

        Args:
            from_address: Buyer EOA address.
            to: Seller address.
            value: Amount in USDC atomic units.
            valid_before: Unix timestamp (must be >= now + 3 days).
            nonce: Random 32-byte hex string.
        """
        return cls(
            from_address=from_address,
            to=to,
            value=value,
            valid_after="0",
            valid_before=str(valid_before),
            nonce=nonce,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "from": self.from_address,
            "to": self.to,
            "value": self.value,
            "validAfter": self.valid_after,
            "validBefore": self.valid_before,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EIP3009Authorization:
        """Create from dict."""
        return cls(
            from_address=data.get("from", ""),
            to=data.get("to", ""),
            value=data.get("value", ""),
            valid_after=data.get("validAfter", "0"),
            valid_before=data.get("validBefore", ""),
            nonce=data.get("nonce", ""),
        )


# =============================================================================
# PAYMENT PAYLOAD (buyer side)
# =============================================================================


@dataclass(frozen=True)
class ResourceInfo:
    """
    Information about the resource being paid for in an x402 payment.

    Required by Circle Gateway in the paymentPayload.resource field.

    The URL is the resource identifier. Description and MIME type provide
    additional context for the payment.
    """

    url: str
    """URL of the resource being accessed."""

    description: str
    """Human-readable description of the resource."""

    mime_type: str
    """Expected MIME type of the resource response."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "url": self.url,
            "description": self.description,
            "mimeType": self.mime_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceInfo:
        """Create from dict."""
        return cls(
            url=data.get("url", ""),
            description=data.get("description", ""),
            mime_type=data.get("mimeType", ""),
        )


@dataclass(frozen=True)
class PaymentPayloadInner:
    """
    Inner payload containing the EIP-3009 signature and authorization.
    """

    signature: str
    """
    Hex-encoded ECDSA signature (65 bytes: r + s + v).
    Prefix with '0x'.
    """

    authorization: EIP3009Authorization
    """The signed EIP-3009 authorization."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "signature": self.signature,
            "authorization": self.authorization.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentPayloadInner:
        """Create from dict."""
        return cls(
            signature=data.get("signature", ""),
            authorization=EIP3009Authorization.from_dict(data.get("authorization", {})),
        )


@dataclass(frozen=True)
class PaymentPayload:
    """
    Complete payment payload sent in the PAYMENT-SIGNATURE header.

    This is the x402 v2 payload structure that contains the EIP-3009
    signature authorizing the payment.

    Serialized as JSON, then base64-encoded, then sent as a header.

    The 'resource' field is required by Circle Gateway. It identifies what
    resource is being paid for.
    """

    x402_version: int
    """Always 2 for x402 v2."""

    scheme: str
    """Always 'exact'."""

    network: str
    """CAIP-2 network identifier."""

    payload: PaymentPayloadInner
    """Contains signature and authorization."""

    resource: ResourceInfo | None = None
    """
    Information about the resource being paid for.

    Required by Circle Gateway. Set this to identify the resource being accessed.
    """

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        result: dict[str, Any] = {
            "x402Version": self.x402_version,
            "scheme": self.scheme,
            "network": self.network,
            "payload": self.payload.to_dict(),
        }
        if self.resource is not None:
            result["resource"] = self.resource.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentPayload:
        """Create from dict parsed from JSON."""
        resource_data = data.get("resource")
        resource = ResourceInfo.from_dict(resource_data) if resource_data else None
        return cls(
            x402_version=data.get("x402Version", 2),
            scheme=data.get("scheme", "exact"),
            network=data.get("network", ""),
            payload=PaymentPayloadInner.from_dict(data.get("payload", {})),
            resource=resource,
        )


# =============================================================================
# API RESPONSE TYPES
# =============================================================================


@dataclass(frozen=True)
class VerifyResponse:
    """
    Response from Circle Gateway /v1/x402/verify endpoint.

    Note: In production, always use /v1/x402/settle directly.
    The verify endpoint is for debugging only.
    """

    is_valid: bool
    """True if the payment signature is valid."""

    payer: str | None
    """Payer address if valid, None otherwise."""

    invalid_reason: str | None
    """
    Reason for invalidity if is_valid is False.
    See error codes in constants.
    """

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "isValid": self.is_valid,
            "payer": self.payer,
            "invalidReason": self.invalid_reason,
        }


@dataclass(frozen=True)
class SettleResponse:
    """
    Response from Circle Gateway /v1/x402/settle endpoint.

    settle() is the primary method for production flows.
    It has low latency and guarantees atomic settlement.
    """

    success: bool
    """True if settlement succeeded."""

    transaction: str | None
    """Batch reference ID from Circle Gateway."""

    payer: str | None
    """Payer address."""

    error_reason: str | None
    """Error reason if success is False. See error codes."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "success": self.success,
            "transaction": self.transaction,
            "payer": self.payer,
            "errorReason": self.error_reason,
        }


# =============================================================================
# SUPPORTED NETWORKS
# =============================================================================


@dataclass(frozen=True)
class SupportedKind:
    """
    A payment kind supported by Circle Gateway.

    Fetched from /v1/x402/supported at initialization.
    Contains chain configuration needed for signing and verification.
    """

    x402_version: int
    """x402 protocol version."""

    scheme: str
    """Payment scheme."""

    network: str
    """CAIP-2 network identifier."""

    extra: dict[str, Any] | None
    """
    Additional metadata. For GatewayWalletBatched, contains:
    - verifyingContract: Gateway Wallet contract address
    - usdcAddress: USDC token address on this chain
    """

    @property
    def verifying_contract(self) -> str | None:
        """Get Gateway Wallet contract address if available."""
        if self.extra:
            return self.extra.get("verifyingContract")
        return None

    @property
    def usdc_address(self) -> str | None:
        """Get USDC token address if available."""
        if self.extra:
            return self.extra.get("usdcAddress")
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SupportedKind:
        """Create from dict."""
        return cls(
            x402_version=data.get("x402Version", 2),
            scheme=data.get("scheme", "exact"),
            network=data.get("network", ""),
            extra=data.get("extra"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "x402Version": self.x402_version,
            "scheme": self.scheme,
            "network": self.network,
            "extra": self.extra,
        }


# =============================================================================
# GATEWAY BALANCE
# =============================================================================


@dataclass(frozen=True)
class GatewayBalance:
    """
    Balance information for a Gateway Wallet.

    Represents USDC held in the Gateway Wallet contract,
    separate from the Circle MPC wallet balance.
    """

    total: int
    """Total USDC in Gateway (atomic units)."""

    available: int
    """
    Available USDC for new payments.
    May be less than total due to pending settlements.
    """

    formatted_total: str
    """Human-readable total (e.g., '150.50 USDC')."""

    formatted_available: str
    """Human-readable available (e.g., '148.25 USDC')."""

    @property
    def total_decimal(self) -> str:
        """Total as decimal USDC string."""
        return self.formatted_total.split()[0]

    @property
    def available_decimal(self) -> str:
        """Available as decimal USDC string."""
        return self.formatted_available.split()[0]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "total": self.total,
            "available": self.available,
            "formatted_total": self.formatted_total,
            "formatted_available": self.formatted_available,
        }


# =============================================================================
# PAYMENT RESULT
# =============================================================================


@dataclass(frozen=True)
class NanopaymentResult:
    """
    Result of a nanopayment execution.

    Returned by NanopaymentAdapter after successful payment.
    """

    success: bool
    """True if payment was settled successfully."""

    payer: str
    """Payer's EOA address."""

    seller: str
    """Seller's address."""

    transaction: str
    """
    Transaction reference from Circle Gateway.
    For settled payments, this is the batch reference ID.
    """

    amount_usdc: str
    """Amount paid in USDC decimal (e.g., '0.001')."""

    amount_atomic: str
    """Amount paid in USDC atomic units."""

    network: str
    """CAIP-2 network identifier used."""

    response_data: Any | None
    """
    Response body from the resource server.
    Present for URL-based payments, None for direct transfers.
    """

    is_nanopayment: bool = True
    """Always True for nanopayments. Used to distinguish from standard transfers."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "success": self.success,
            "payer": self.payer,
            "seller": self.seller,
            "transaction": self.transaction,
            "amount_usdc": self.amount_usdc,
            "amount_atomic": self.amount_atomic,
            "network": self.network,
            "response_data": self.response_data,
            "is_nanopayment": self.is_nanopayment,
        }


# =============================================================================
# SELLER PAYMENT INFO
# =============================================================================


@dataclass(frozen=True)
class PaymentInfo:
    """
    Payment information for a seller receiving payment.

    Attached to requests in @agent.sell() decorated functions
    via agent.current_payment().
    """

    verified: bool
    """True if the payment was verified and settled."""

    payer: str
    """Buyer's address."""

    amount: str
    """Amount in USDC atomic units."""

    network: str
    """CAIP-2 network identifier."""

    transaction: str | None
    """Batch reference from settlement."""

    @property
    def amount_decimal(self) -> str:
        """Amount as decimal USDC string."""
        from decimal import Decimal

        return str(Decimal(self.amount) / Decimal("1000000"))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "verified": self.verified,
            "payer": self.payer,
            "amount": self.amount,
            "amount_decimal": self.amount_decimal,
            "network": self.network,
            "transaction": self.transaction,
        }


# =============================================================================
# WALLET OPERATION RESULTS
# =============================================================================


@dataclass(frozen=True)
class DepositResult:
    """
    Result of a deposit to the Gateway Wallet.
    """

    approval_tx_hash: str | None
    """None if no approval was needed (already had sufficient allowance)."""

    deposit_tx_hash: str | None
    """The on-chain transaction hash for the deposit. None if skipped due to insufficient gas."""

    amount: int
    """Amount deposited in USDC atomic units."""

    formatted_amount: str
    """Human-readable amount (e.g., '10.000000 USDC')."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "approval_tx_hash": self.approval_tx_hash,
            "deposit_tx_hash": self.deposit_tx_hash,
            "amount": self.amount,
            "formatted_amount": self.formatted_amount,
        }


@dataclass(frozen=True)
class WithdrawResult:
    """
    Result of a withdrawal from the Gateway Wallet.
    """

    mint_tx_hash: str | None
    """For cross-chain withdrawals: the mint transaction hash."""

    amount: int
    """Amount withdrawn in USDC atomic units."""

    formatted_amount: str
    """Human-readable amount."""

    source_chain: str
    """CAIP-2 source chain."""

    destination_chain: str
    """CAIP-2 destination chain."""

    recipient: str
    """Recipient address."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "mint_tx_hash": self.mint_tx_hash,
            "amount": self.amount,
            "formatted_amount": self.formatted_amount,
            "source_chain": self.source_chain,
            "destination_chain": self.destination_chain,
            "recipient": self.recipient,
        }
