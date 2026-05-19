"""
Tests for nanopayments exception hierarchy.

Phase 1: Foundation
"""

from omniclaw.protocols.nanopayments import (
    AuthorizationExpiredError,
    DepositError,
    DuplicateKeyAliasError,
    ERC20ApprovalError,
    GatewayAPIError,
    GatewayConnectionError,
    GatewayTimeoutError,
    InsufficientBalanceError,
    InsufficientGatewayBalanceError,
    InvalidPriceError,
    InvalidPrivateKeyError,
    InvalidSignatureError,
    KeyEncryptionError,
    KeyNotFoundError,
    NanopaymentError,
    NetworkMismatchError,
    NoDefaultKeyError,
    NonceReusedError,
    PaymentRequiredError,
    SettlementError,
    SigningError,
    UnsupportedNetworkError,
    UnsupportedSchemeError,
    VerificationError,
    WithdrawError,
)


class TestExceptionHierarchy:
    """Tests that exceptions form correct hierarchy."""

    def test_all_signing_errors_inherit_from_nanopayment_error(self):
        """Every signing error should be catchable as NanopaymentError."""
        exc = SigningError("test")
        assert isinstance(exc, NanopaymentError)

    def test_all_api_errors_inherit_from_nanopayment_error(self):
        """Every API error should be catchable as NanopaymentError."""
        exc = GatewayAPIError("test", 500)
        assert isinstance(exc, NanopaymentError)

    def test_all_verification_errors_inherit_from_nanopayment_error(self):
        """Every verification error should be catchable as NanopaymentError."""
        exc = VerificationError("test")
        assert isinstance(exc, NanopaymentError)

    def test_all_settlement_errors_inherit_from_nanopayment_error(self):
        """Every settlement error should be catchable as NanopaymentError."""
        exc = SettlementError("test")
        assert isinstance(exc, NanopaymentError)

    def test_all_key_errors_inherit_from_nanopayment_error(self):
        """Every key error should be catchable as NanopaymentError."""
        exc = KeyNotFoundError("alias")
        assert isinstance(exc, NanopaymentError)

    def test_all_wallet_errors_inherit_from_nanopayment_error(self):
        """Every wallet error should be catchable as NanopaymentError."""
        exc = DepositError("test")
        assert isinstance(exc, NanopaymentError)

    def test_all_middleware_errors_inherit_from_nanopayment_error(self):
        """Every middleware error should be catchable as NanopaymentError."""
        exc = InvalidPriceError("test")
        assert isinstance(exc, NanopaymentError)

    def test_catch_all_with_base_exception(self):
        """Can catch all nanopayment errors with NanopaymentError."""
        errors = [
            SigningError("test"),
            GatewayAPIError("test", 500),
            VerificationError("test"),
            SettlementError("test"),
            KeyNotFoundError("alias"),
            DepositError("test"),
            InvalidPriceError("test"),
        ]
        for exc in errors:
            assert isinstance(exc, NanopaymentError)


class TestSigningError:
    """Tests for SigningError and subclasses."""

    def test_invalid_private_key_error(self):
        exc = InvalidPrivateKeyError("key too short")
        assert "Invalid private key" in exc.message
        assert exc.code == "INVALID_PRIVATE_KEY"
        assert exc.details["reason"] == "key too short"

    def test_exception_to_dict(self):
        exc = InvalidPrivateKeyError("key too short")
        d = exc.to_dict()
        assert d["error"] == "InvalidPrivateKeyError"
        assert "Invalid private key" in d["message"]
        assert d["code"] == "INVALID_PRIVATE_KEY"


class TestGatewayAPIError:
    """Tests for GatewayAPIError."""

    def test_includes_status_code(self):
        exc = GatewayAPIError("Server error", status_code=500, response_body='{"error": "test"}')
        assert exc.status_code == 500
        assert exc.response_body == '{"error": "test"}'
        assert exc.code == "GATEWAY_API_ERROR"

    def test_timeout_error(self):
        exc = GatewayTimeoutError("/x402/v1/settle")
        assert "timed out" in exc.message
        assert exc.code == "GATEWAY_TIMEOUT"

    def test_connection_error(self):
        exc = GatewayConnectionError("Cannot resolve host")
        assert "Cannot connect" in exc.message
        assert exc.code == "GATEWAY_CONNECTION_ERROR"

    def test_str_returns_message(self):
        exc = GatewayAPIError("test message", 500)
        assert str(exc) == "test message"


class TestVerificationError:
    """Tests for VerificationError and subclasses."""

    def test_authorization_expired(self):
        exc = AuthorizationExpiredError()
        assert "authorization_expired" in exc.reason
        assert exc.code == "AUTHORIZATION_EXPIRED"

    def test_nonce_reused(self):
        exc = NonceReusedError()
        assert "nonce_already_used" in exc.reason
        assert exc.code == "NONCE_REUSED"

    def test_insufficient_balance(self):
        exc = InsufficientBalanceError()
        assert "insufficient_balance" in exc.reason
        assert exc.code == "INSUFFICIENT_BALANCE"

    def test_invalid_signature(self):
        exc = InvalidSignatureError("wrong length")
        assert "invalid_signature" in exc.reason
        assert exc.code == "INVALID_SIGNATURE"


class TestSettlementError:
    """Tests for SettlementError."""

    def test_with_transaction_reference(self):
        exc = SettlementError(
            reason="insufficient_balance",
            transaction="batch-123",
            payer="0xBuyer123",
        )
        assert exc.reason == "insufficient_balance"
        assert exc.transaction == "batch-123"
        assert exc.payer == "0xBuyer123"

    def test_insufficient_gateway_balance(self):
        exc = InsufficientGatewayBalanceError(required="1000000", available="500000")
        assert exc.code == "INSUFFICIENT_GATEWAY_BALANCE"
        assert exc.details["required"] == "1000000"
        assert exc.details["available"] == "500000"


class TestKeyManagementErrors:
    """Tests for key management errors."""

    def test_key_not_found(self):
        exc = KeyNotFoundError("alice-nano")
        assert "alice-nano" in exc.message
        assert exc.code == "KEY_NOT_FOUND"
        assert exc.alias == "alice-nano"

    def test_duplicate_key_alias(self):
        exc = DuplicateKeyAliasError("bob-nano")
        assert "bob-nano" in exc.message
        assert exc.code == "DUPLICATE_KEY_ALIAS"
        assert exc.alias == "bob-nano"

    def test_no_default_key(self):
        exc = NoDefaultKeyError()
        assert "No default key" in exc.message
        assert exc.code == "NO_DEFAULT_KEY"

    def test_encryption_error(self):
        exc = KeyEncryptionError("decrypt", "invalid padding")
        assert "decrypt" in exc.message
        assert "invalid padding" in exc.message


class TestNetworkErrors:
    """Tests for network-related errors."""

    def test_unsupported_network(self):
        exc = UnsupportedNetworkError("solana")
        assert "solana" in exc.message
        assert exc.code == "UNSUPPORTED_NETWORK"
        assert exc.network == "solana"

    def test_network_mismatch(self):
        exc = NetworkMismatchError("eip155:5042002", "eip155:84532")
        assert "5042002" in exc.message
        assert "84532" in exc.message
        assert exc.details["buyer_network"] == "eip155:5042002"

    def test_unsupported_scheme(self):
        exc = UnsupportedSchemeError("some-scheme")
        assert "some-scheme" in exc.message
        assert exc.code == "UNSUPPORTED_SCHEME"


class TestMiddlewareErrors:
    """Tests for compatibility x402 402 errors."""

    def test_invalid_price(self):
        exc = InvalidPriceError("not a number")
        assert "Invalid price format" in exc.message
        assert exc.code == "INVALID_PRICE"
        assert exc.price == "not a number"

    def test_payment_required(self):
        exc = PaymentRequiredError({"accepts": []})
        assert exc.requirements_body == {"accepts": []}
        assert exc.code == "PAYMENT_REQUIRED"


class TestWalletErrors:
    """Tests for Gateway Wallet operation errors."""

    def test_deposit_error(self):
        exc = DepositError("reverted", tx_hash="0xTx123")
        assert "Gateway deposit failed" in exc.message
        assert exc.code == "DEPOSIT_ERROR"
        assert exc.details["tx_hash"] == "0xTx123"

    def test_withdraw_error(self):
        exc = WithdrawError("failed", tx_hash="0xTx456")
        assert "Gateway withdrawal failed" in exc.message
        assert exc.code == "WITHDRAW_ERROR"

    def test_erc20_approval_error(self):
        exc = ERC20ApprovalError("insufficient funds", tx_hash="0xApprove123")
        assert "USDC approval failed" in exc.message
        assert exc.code == "ERC20_APPROVAL_ERROR"


class TestExceptionRepr:
    """Tests for exception repr."""

    def test_repr_with_code(self):
        exc = InvalidPrivateKeyError("test")
        r = repr(exc)
        assert "InvalidPrivateKeyError" in r
        assert "INVALID_PRIVATE_KEY" in r

    def test_repr_without_code(self):
        exc = NanopaymentError("simple message")
        r = repr(exc)
        assert "NanopaymentError" in r
        assert "simple message" in r
