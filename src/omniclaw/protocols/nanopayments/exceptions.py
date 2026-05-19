"""
Exception hierarchy for OmniClaw Nanopayments.

All nanopayment errors inherit from NanopaymentError.
This allows catching all nanopayment-related errors with one exception type.
"""

from __future__ import annotations

from typing import Any

# =============================================================================
# BASE EXCEPTION
# =============================================================================


class NanopaymentError(Exception):
    """
    Base exception for all nanopayment-related errors.

    Catch this to handle any nanopayment error.
    Subclass-specific errors provide more detail.
    """

    def __init__(
        self,
        message: str,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def __repr__(self) -> str:
        if self.code:
            return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"
        return f"{self.__class__.__name__}({self.message!r})"

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "code": self.code,
            "details": self.details,
        }


# =============================================================================
# CRYPTO / SIGNING ERRORS
# =============================================================================


class SigningError(NanopaymentError):
    """
    Raised when EIP-3009 signing fails.

    Common causes:
    - Invalid private key format
    - Missing required fields in authorization
    - Invalid chain ID or verifying contract
    - Message encoding errors
    """

    pass


class InvalidPrivateKeyError(SigningError):
    """Raised when the provided private key is invalid."""

    def __init__(self, reason: str = "Invalid format or length") -> None:
        super().__init__(
            message=f"Invalid private key: {reason}",
            code="INVALID_PRIVATE_KEY",
            details={"reason": reason},
        )


class SignatureVerificationError(SigningError):
    """Raised when signature verification fails internally."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            message=f"Signature verification failed: {reason}",
            code="SIGNATURE_VERIFICATION_FAILED",
            details={"reason": reason},
        )


# =============================================================================
# GATEWAY API ERRORS
# =============================================================================


class GatewayAPIError(NanopaymentError):
    """
    Raised when Circle Gateway returns an HTTP error.

    This covers non-2xx responses from Gateway endpoints.
    Check the 'code' and 'details' for specific error information.
    """

    def __init__(
        self,
        message: str,
        status_code: int,
        response_body: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="GATEWAY_API_ERROR",
            details={
                "status_code": status_code,
                "response_body": response_body,
            },
        )
        self.status_code = status_code
        self.response_body = response_body


class GatewayTimeoutError(GatewayAPIError):
    """Raised when Circle Gateway request times out."""

    def __init__(self, endpoint: str) -> None:
        super().__init__(
            message=f"Circle Gateway request timed out: {endpoint}",
            status_code=0,
            response_body=None,
        )
        self.code = "GATEWAY_TIMEOUT"


class GatewayConnectionError(GatewayAPIError):
    """Raised when cannot connect to Circle Gateway."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            message=f"Cannot connect to Circle Gateway: {reason}",
            status_code=0,
            response_body=None,
        )
        self.code = "GATEWAY_CONNECTION_ERROR"


# =============================================================================
# VERIFICATION ERRORS
# =============================================================================


class VerificationError(NanopaymentError):
    """
    Raised when payment signature verification fails.

    Returned when Circle Gateway /verify returns isValid=false.
    Check 'code' for the specific rejection reason.

    Error codes from Gateway:
    - unsupported_scheme
    - unsupported_network
    - unsupported_asset
    - invalid_payload
    - address_mismatch
    - amount_mismatch
    - invalid_signature
    - authorization_not_yet_valid
    - authorization_expired
    - authorization_validity_too_short
    - self_transfer
    - insufficient_balance
    - nonce_already_used
    """

    def __init__(self, reason: str, payer: str | None = None) -> None:
        super().__init__(
            message=f"Payment verification failed: {reason}",
            code="VERIFICATION_FAILED",
            details={"reason": reason, "payer": payer},
        )
        self.reason = reason
        self.payer = payer


class InvalidSignatureError(VerificationError):
    """Raised when the EIP-3009 signature is invalid."""

    def __init__(
        self,
        reason: str | None = None,
        payer: str | None = None,
    ) -> None:
        # Support both: InvalidSignatureError("wrong length") and
        # InvalidSignatureError(reason="invalid_signature", payer=...)
        if reason:
            super().__init__(reason=f"invalid_signature: {reason}", payer=payer)
        else:
            super().__init__(reason="invalid_signature", payer=payer)
        self.code = "INVALID_SIGNATURE"


class AuthorizationExpiredError(VerificationError):
    """Raised when the authorization's validBefore timestamp has passed."""

    def __init__(
        self,
        reason: str | None = None,
        payer: str | None = None,
    ) -> None:
        super().__init__(
            reason=reason if reason else "authorization_expired",
            payer=payer,
        )
        self.code = "AUTHORIZATION_EXPIRED"


class AuthorizationNotYetValidError(VerificationError):
    """Raised when validAfter is in the future."""

    def __init__(
        self,
        reason: str | None = None,
        payer: str | None = None,
    ) -> None:
        super().__init__(
            reason=reason if reason else "authorization_not_yet_valid",
            payer=payer,
        )
        self.code = "AUTHORIZATION_NOT_YET_VALID"


class NonceReusedError(VerificationError):
    """Raised when the nonce has already been used."""

    def __init__(
        self,
        reason: str | None = None,
        payer: str | None = None,
    ) -> None:
        super().__init__(
            reason=reason if reason else "nonce_already_used",
            payer=payer,
        )
        self.code = "NONCE_REUSED"


class InsufficientBalanceError(VerificationError):
    """Raised when Gateway balance is insufficient."""

    def __init__(
        self,
        reason: str | None = None,
        payer: str | None = None,
    ) -> None:
        super().__init__(
            reason=reason if reason else "insufficient_balance",
            payer=payer,
        )
        self.code = "INSUFFICIENT_BALANCE"


# =============================================================================
# SETTLEMENT ERRORS
# =============================================================================


class SettlementError(NanopaymentError):
    """
    Raised when payment settlement fails.

    Returned when Circle Gateway /settle returns success=false.
    These are payment-level failures, distinct from verification failures.
    """

    def __init__(
        self,
        reason: str,
        transaction: str | None = None,
        payer: str | None = None,
    ) -> None:
        super().__init__(
            message=f"Payment settlement failed: {reason}",
            code="SETTLEMENT_FAILED",
            details={
                "reason": reason,
                "transaction": transaction,
                "payer": payer,
            },
        )
        self.reason = reason
        self.transaction = transaction
        self.payer = payer


class InsufficientGatewayBalanceError(SettlementError):
    """Raised when the Gateway wallet balance is insufficient for the payment."""

    def __init__(self, required: str, available: str) -> None:
        super().__init__(
            reason="insufficient_balance",
            payer=None,
        )
        self.code = "INSUFFICIENT_GATEWAY_BALANCE"
        self.details["required"] = required
        self.details["available"] = available


# =============================================================================
# NETWORK / CONFIGURATION ERRORS
# =============================================================================


class UnsupportedNetworkError(NanopaymentError):
    """
    Raised when the specified network is not supported by Circle Gateway.

    Common causes:
    - Network not in the supported list from /v1/x402/supported
    - Network doesn't exist in Circle's Gateway configuration
    - Chain ID format is wrong (should be CAIP-2: 'eip155:chainId')
    """

    def __init__(self, network: str) -> None:
        super().__init__(
            message=f"Unsupported network: {network}",
            code="UNSUPPORTED_NETWORK",
            details={"network": network},
        )
        self.network = network


class NetworkMismatchError(NanopaymentError):
    """
    Raised when buyer and seller are on different networks and
    cross-chain Gateway settlement is not available.
    """

    def __init__(self, buyer_network: str, seller_network: str) -> None:
        super().__init__(
            message=f"Network mismatch: buyer={buyer_network}, seller={seller_network}",
            code="NETWORK_MISMATCH",
            details={
                "buyer_network": buyer_network,
                "seller_network": seller_network,
            },
        )


class UnsupportedSchemeError(NanopaymentError):
    """
    Raised when the payment requirements specify an unsupported scheme.

    Currently only 'exact' scheme is supported.
    """

    def __init__(self, scheme: str) -> None:
        super().__init__(
            message=f"Unsupported payment scheme: {scheme}",
            code="UNSUPPORTED_SCHEME",
            details={"scheme": scheme},
        )


class MissingVerifyingContractError(NanopaymentError):
    """
    Raised when the verifying contract address is missing from requirements.

    For GatewayWalletBatched payments, the requirements MUST contain
    extra.verifyingContract.
    """

    def __init__(self) -> None:
        super().__init__(
            message="Missing verifyingContract in payment requirements",
            code="MISSING_VERIFYING_CONTRACT",
        )


# =============================================================================
# KEY MANAGEMENT ERRORS
# =============================================================================


class KeyManagementError(NanopaymentError):
    """Base for key management related errors."""

    pass


class KeyNotFoundError(KeyManagementError):
    """Raised when a requested key alias does not exist."""

    def __init__(self, alias: str) -> None:
        super().__init__(
            message=f"Key not found: {alias}",
            code="KEY_NOT_FOUND",
            details={"alias": alias},
        )
        self.alias = alias


class KeyEncryptionError(KeyManagementError):
    """Raised when key encryption or decryption fails."""

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(
            message=f"Key encryption failed during {operation}: {reason}",
            code="KEY_ENCRYPTION_ERROR",
            details={"operation": operation, "reason": reason},
        )


class DuplicateKeyAliasError(KeyManagementError):
    """Raised when adding a key with an alias that already exists."""

    def __init__(self, alias: str) -> None:
        super().__init__(
            message=f"Key alias already exists: {alias}",
            code="DUPLICATE_KEY_ALIAS",
            details={"alias": alias},
        )
        self.alias = alias


class NoDefaultKeyError(KeyManagementError):
    """Raised when no default key is set and no alias is specified."""

    def __init__(self) -> None:
        super().__init__(
            message="No default key set. Call sdk.set_default_key() first.",
            code="NO_DEFAULT_KEY",
        )


# =============================================================================
# GATEWAY WALLET ERRORS
# =============================================================================


class GatewayWalletError(NanopaymentError):
    """Base for Gateway Wallet contract operation errors."""

    pass


class DepositError(GatewayWalletError):
    """Raised when deposit to Gateway Wallet fails."""

    def __init__(self, reason: str, tx_hash: str | None = None) -> None:
        super().__init__(
            message=f"Gateway deposit failed: {reason}",
            code="DEPOSIT_ERROR",
            details={"reason": reason, "tx_hash": tx_hash},
        )


class WithdrawError(GatewayWalletError):
    """Raised when withdrawal from Gateway Wallet fails."""

    def __init__(self, reason: str, tx_hash: str | None = None) -> None:
        super().__init__(
            message=f"Gateway withdrawal failed: {reason}",
            code="WITHDRAW_ERROR",
            details={"reason": reason, "tx_hash": tx_hash},
        )


class ERC20ApprovalError(GatewayWalletError):
    """Raised when USDC ERC-20 approval fails."""

    def __init__(self, reason: str, tx_hash: str | None = None) -> None:
        super().__init__(
            message=f"USDC approval failed: {reason}",
            code="ERC20_APPROVAL_ERROR",
            details={"reason": reason, "tx_hash": tx_hash},
        )


class InsufficientGasError(GatewayWalletError):
    """
    Raised when the wallet has insufficient ETH for gas on deposit operations.

    The deposit to Gateway Wallet is an on-chain transaction that requires ETH
    to pay for gas. This error indicates the ETH balance is below the
    recommended reserve.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(
            message=f"Insufficient ETH for gas: {reason}",
            code="INSUFFICIENT_GAS",
            details={"reason": reason},
        )


# =============================================================================
# MIDDLEWARE ERRORS
# =============================================================================


class MiddlewareError(NanopaymentError):
    """Base for x402 seller-gate errors kept for compatibility."""

    pass


class InvalidPriceError(MiddlewareError):
    """Raised when a price string cannot be parsed."""

    def __init__(self, price: str) -> None:
        super().__init__(
            message=f"Invalid price format: {price}",
            code="INVALID_PRICE",
            details={"price": price},
        )
        self.price = price


class PaymentRequiredError(MiddlewareError):
    """
    Raised when a payment is required but not provided.
    """

    def __init__(self, requirements_body: dict[str, Any]) -> None:
        super().__init__(
            message="Payment required",
            code="PAYMENT_REQUIRED",
            details={"requirements": requirements_body},
        )
        self.requirements_body = requirements_body


class NoNetworksAvailableError(MiddlewareError):
    """Raised when no supported networks are available from Gateway."""

    def __init__(self) -> None:
        super().__init__(
            message="No supported networks available from Circle Gateway",
            code="NO_NETWORKS_AVAILABLE",
        )


class NanopaymentNotInitializedError(NanopaymentError):
    """
    Raised when a nanopayment operation is attempted but nanopayments
    are not initialized (disabled or failed to initialize).
    """

    def __init__(self) -> None:
        super().__init__(
            message="Nanopayments are not initialized. "
            "Set nanopayments_enabled=True in Config to enable.",
            code="NOT_INITIALIZED",
        )
