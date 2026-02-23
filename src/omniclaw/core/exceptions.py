"""
Exception hierarchy for OmniClaw SDK.

All SDK-specific exceptions inherit from OmniClawError for easy catching.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


class OmniClawError(Exception):
    """
    Base exception for all OmniClaw SDK errors.

    Catch this to handle any SDK-related exception.

    Example:
        >>> try:
        ...     client.pay(...)
        ... except OmniClawError as e:
        ...     print(f"Payment SDK error: {e}")
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class ConfigurationError(OmniClawError):
    """
    Configuration is missing or invalid.

    Raised when:
    - Required configuration values are not provided
    - Configuration values fail validation
    - Environment variables are not set
    """

    pass


class WalletError(OmniClawError):
    """
    Wallet operation failed.

    Raised when:
    - Wallet creation fails
    - Wallet not found
    - Wallet is in invalid state (e.g., frozen)
    """

    def __init__(
        self,
        message: str,
        wallet_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.wallet_id = wallet_id


class PaymentError(OmniClawError):
    """
    Base exception for payment-related errors.

    Raised when:
    - Payment fails to execute
    - Payment validation fails
    - External services return errors
    """

    def __init__(
        self,
        message: str,
        recipient: str | None = None,
        amount: Decimal | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.recipient = recipient
        self.amount = amount


class GuardError(PaymentError):
    """
    A guard rejected the payment.

    Raised when:
    - BudgetGuard: Daily/weekly/monthly spending limit exceeded
    - RateLimitGuard: Too many transactions in time window
    - SingleTxGuard: Transaction amount exceeds maximum
    - RecipientGuard: Recipient not in allowlist

    Example:
        >>> try:
        ...     client.pay("https://api.expensive.com", "1000.00")
        ... except GuardError as e:
        ...     print(f"Blocked by {e.guard_name}: {e.reason}")
    """

    def __init__(
        self,
        message: str,
        guard_name: str,
        reason: str,
        recipient: str | None = None,
        amount: Decimal | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, recipient, amount, details)
        self.guard_name = guard_name
        self.reason = reason

    def __str__(self) -> str:
        return f"[{self.guard_name}] {self.reason}"


class ProtocolError(PaymentError):
    """
    Protocol adapter error.

    Raised when:
    - Protocol-specific parsing fails
    - Invalid protocol response
    - Unsupported protocol features
    """

    def __init__(
        self,
        message: str,
        protocol: str = "unknown",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.protocol = protocol

    def __str__(self) -> str:
        return f"[{self.protocol}] {self.message}"


class ValidationError(OmniClawError):
    """
    Input validation error.

    Raised when:
    - Required parameters are missing
    - Parameter values are invalid
    """

    pass


class InsufficientBalanceError(PaymentError):
    """
    Wallet does not have enough balance for the payment.

    Raised when:
    - Wallet balance is less than payment amount
    - Balance check fails before payment execution
    """

    def __init__(
        self,
        message: str,
        current_balance: Decimal,
        required_amount: Decimal,
        wallet_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details, amount=required_amount)
        self.current_balance = current_balance
        self.required_amount = required_amount
        self.wallet_id = wallet_id
        self.shortfall = required_amount - current_balance

    def __str__(self) -> str:
        return (
            f"{self.message} | "
            f"Balance: {self.current_balance}, Required: {self.required_amount}, "
            f"Shortfall: {self.shortfall}"
        )


class NetworkError(OmniClawError):
    """
    Network or API communication error.

    Raised when:
    - HTTP request fails (timeout, connection error)
    - API returns unexpected response
    - Rate limiting encountered
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        url: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.status_code = status_code
        self.url = url

    def is_rate_limited(self) -> bool:
        """Check if this is a rate limit error."""
        return self.status_code == 429

    def is_server_error(self) -> bool:
        """Check if this is a server-side error."""
        return self.status_code is not None and 500 <= self.status_code < 600


class X402Error(PaymentError):
    """
    x402 protocol error.

    Raised when:
    - Server returns 402 but payment requirements are invalid
    - Payment signature verification fails
    - Settlement fails
    - Resource access denied after payment
    """

    def __init__(
        self,
        message: str,
        url: str,
        stage: str,  # "requirements", "verification", "settlement", "access"
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, recipient=url, details=details)
        self.url = url
        self.stage = stage

    def __str__(self) -> str:
        return f"[x402:{self.stage}] {self.message} (URL: {self.url})"


class CrosschainError(PaymentError):
    """
    Cross-chain transfer error.

    Raised when:
    - Bridge Kit transfer fails
    - CCTP attestation not received
    - Gateway deposit/mint fails
    """

    def __init__(
        self,
        message: str,
        source_chain: str,
        destination_chain: str,
        method: str,  # "bridge_kit", "cctp", "gateway"
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.source_chain = source_chain
        self.destination_chain = destination_chain
        self.method = method

    def __str__(self) -> str:
        return (
            f"[crosschain:{self.method}] {self.message} "
            f"({self.source_chain} → {self.destination_chain})"
        )


class TransactionTimeoutError(PaymentError):
    """
    Transaction timed out waiting for confirmation.

    Raised when:
    - Transaction is pending for too long
    - Polling for transaction status exceeded timeout
    """

    def __init__(
        self,
        message: str,
        transaction_id: str,
        last_state: str,
        timeout_seconds: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.transaction_id = transaction_id
        self.last_state = last_state
        self.timeout_seconds = timeout_seconds


class IdempotencyError(PaymentError):
    """
    Idempotency key conflict.

    Raised when:
    - Same idempotency key used with different parameters
    - Previous payment with same key has different outcome
    """

    def __init__(
        self,
        message: str,
        idempotency_key: str,
        existing_transaction_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.idempotency_key = idempotency_key
        self.existing_transaction_id = existing_transaction_id
