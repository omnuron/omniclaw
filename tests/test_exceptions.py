"""Unit tests for exceptions module."""

from decimal import Decimal

import pytest

from omniagentpay.core.exceptions import (
    ConfigurationError,
    CrosschainError,
    GuardError,
    IdempotencyError,
    InsufficientBalanceError,
    NetworkError,
    OmniAgentPayError,
    PaymentError,
    TransactionTimeoutError,
    WalletError,
    X402Error,
)


class TestOmniAgentPayError:
    """Tests for base exception."""
    
    def test_basic_error(self) -> None:
        """Test basic error creation."""
        error = OmniAgentPayError("Something went wrong")
        
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.details == {}
    
    def test_error_with_details(self) -> None:
        """Test error with details dict."""
        error = OmniAgentPayError(
            "API failed",
            details={"status_code": 500, "response": "Internal error"},
        )
        
        assert "API failed" in str(error)
        assert "Details:" in str(error)
        assert error.details["status_code"] == 500
    
    def test_is_catchable_as_base_type(self) -> None:
        """Test that specific errors can be caught as base type."""
        try:
            raise WalletError("Wallet not found")
        except OmniAgentPayError as e:
            assert "Wallet not found" in str(e)


class TestConfigurationError:
    """Tests for ConfigurationError."""
    
    def test_configuration_error(self) -> None:
        """Test configuration error creation."""
        error = ConfigurationError("Missing API key")
        
        assert isinstance(error, OmniAgentPayError)
        assert "Missing API key" in str(error)


class TestWalletError:
    """Tests for WalletError."""
    
    def test_wallet_error_with_id(self) -> None:
        """Test wallet error with wallet ID."""
        error = WalletError(
            "Wallet not found",
            wallet_id="wallet-123",
        )
        
        assert error.wallet_id == "wallet-123"
        assert isinstance(error, OmniAgentPayError)


class TestPaymentError:
    """Tests for PaymentError."""
    
    def test_payment_error(self) -> None:
        """Test payment error creation."""
        error = PaymentError(
            "Payment failed",
            recipient="0x123...",
            amount=Decimal("10.00"),
        )
        
        assert error.recipient == "0x123..."
        assert error.amount == Decimal("10.00")


class TestGuardError:
    """Tests for GuardError."""
    
    def test_guard_error(self) -> None:
        """Test guard error creation."""
        error = GuardError(
            "Payment blocked",
            guard_name="BudgetGuard",
            reason="Daily limit exceeded: 95/100 USDC",
            amount=Decimal("10.00"),
        )
        
        assert error.guard_name == "BudgetGuard"
        assert error.reason == "Daily limit exceeded: 95/100 USDC"
        assert isinstance(error, PaymentError)
    
    def test_guard_error_str(self) -> None:
        """Test guard error string format."""
        error = GuardError(
            "Blocked",
            guard_name="RateLimitGuard",
            reason="Too many transactions",
        )
        
        assert "[RateLimitGuard]" in str(error)
        assert "Too many transactions" in str(error)


class TestInsufficientBalanceError:
    """Tests for InsufficientBalanceError."""
    
    def test_insufficient_balance(self) -> None:
        """Test insufficient balance error."""
        error = InsufficientBalanceError(
            "Not enough USDC",
            current_balance=Decimal("5.00"),
            required_amount=Decimal("10.00"),
            wallet_id="wallet-123",
        )
        
        assert error.current_balance == Decimal("5.00")
        assert error.required_amount == Decimal("10.00")
        assert error.shortfall == Decimal("5.00")
        assert error.wallet_id == "wallet-123"
    
    def test_insufficient_balance_str(self) -> None:
        """Test string representation."""
        error = InsufficientBalanceError(
            "Insufficient",
            current_balance=Decimal("2.50"),
            required_amount=Decimal("10.00"),
        )
        
        str_repr = str(error)
        assert "Balance: 2.50" in str_repr
        assert "Required: 10.00" in str_repr
        assert "Shortfall: 7.50" in str_repr


class TestNetworkError:
    """Tests for NetworkError."""
    
    def test_network_error(self) -> None:
        """Test network error creation."""
        error = NetworkError(
            "API timeout",
            status_code=504,
            url="https://api.circle.com/v1/wallets",
        )
        
        assert error.status_code == 504
        assert error.url == "https://api.circle.com/v1/wallets"
    
    def test_is_rate_limited(self) -> None:
        """Test rate limit detection."""
        rate_limited = NetworkError("Too many requests", status_code=429)
        not_rate_limited = NetworkError("Server error", status_code=500)
        
        assert rate_limited.is_rate_limited() is True
        assert not_rate_limited.is_rate_limited() is False
    
    def test_is_server_error(self) -> None:
        """Test server error detection."""
        server_error = NetworkError("Internal error", status_code=500)
        gateway_error = NetworkError("Bad gateway", status_code=502)
        client_error = NetworkError("Not found", status_code=404)
        
        assert server_error.is_server_error() is True
        assert gateway_error.is_server_error() is True
        assert client_error.is_server_error() is False


class TestX402Error:
    """Tests for X402Error."""
    
    def test_x402_error(self) -> None:
        """Test x402 error creation."""
        error = X402Error(
            "Payment verification failed",
            url="https://api.paid.com/resource",
            stage="verification",
        )
        
        assert error.url == "https://api.paid.com/resource"
        assert error.stage == "verification"
        assert isinstance(error, PaymentError)
    
    def test_x402_error_str(self) -> None:
        """Test x402 error string format."""
        error = X402Error(
            "Settlement failed",
            url="https://api.example.com",
            stage="settlement",
        )
        
        str_repr = str(error)
        assert "[x402:settlement]" in str_repr
        assert "Settlement failed" in str_repr
        assert "https://api.example.com" in str_repr


class TestCrosschainError:
    """Tests for CrosschainError."""
    
    def test_crosschain_error(self) -> None:
        """Test crosschain error creation."""
        error = CrosschainError(
            "Bridge transfer failed",
            source_chain="ARC",
            destination_chain="BASE",
            method="bridge_kit",
        )
        
        assert error.source_chain == "ARC"
        assert error.destination_chain == "BASE"
        assert error.method == "bridge_kit"
    
    def test_crosschain_error_str(self) -> None:
        """Test string representation."""
        error = CrosschainError(
            "Attestation timeout",
            source_chain="ETH",
            destination_chain="ARC",
            method="cctp",
        )
        
        str_repr = str(error)
        assert "[crosschain:cctp]" in str_repr
        assert "ETH → ARC" in str_repr


class TestTransactionTimeoutError:
    """Tests for TransactionTimeoutError."""
    
    def test_timeout_error(self) -> None:
        """Test timeout error creation."""
        error = TransactionTimeoutError(
            "Transaction pending too long",
            transaction_id="tx-123",
            last_state="PENDING",
            timeout_seconds=120.0,
        )
        
        assert error.transaction_id == "tx-123"
        assert error.last_state == "PENDING"
        assert error.timeout_seconds == 120.0


class TestIdempotencyError:
    """Tests for IdempotencyError."""
    
    def test_idempotency_error(self) -> None:
        """Test idempotency error creation."""
        error = IdempotencyError(
            "Duplicate request with different parameters",
            idempotency_key="idem-key-123",
            existing_transaction_id="tx-456",
        )
        
        assert error.idempotency_key == "idem-key-123"
        assert error.existing_transaction_id == "tx-456"


class TestExceptionHierarchy:
    """Tests for exception inheritance."""
    
    def test_all_errors_inherit_from_base(self) -> None:
        """Test all errors inherit from OmniAgentPayError."""
        errors = [
            ConfigurationError("test"),
            WalletError("test"),
            PaymentError("test"),
            GuardError("test", guard_name="Test", reason="test"),
            InsufficientBalanceError("test", Decimal("0"), Decimal("1")),
            NetworkError("test"),
            X402Error("test", url="http://test", stage="test"),
            CrosschainError("test", "A", "B", "cctp"),
            TransactionTimeoutError("test", "tx", "PENDING", 60.0),
            IdempotencyError("test", "key"),
        ]
        
        for error in errors:
            assert isinstance(error, OmniAgentPayError)
    
    def test_payment_errors_inherit_correctly(self) -> None:
        """Test payment error hierarchy."""
        guard_error = GuardError("test", guard_name="Test", reason="test")
        balance_error = InsufficientBalanceError("test", Decimal("0"), Decimal("1"))
        x402_error = X402Error("test", url="http://test", stage="test")
        crosschain_error = CrosschainError("test", "A", "B", "cctp")
        
        assert isinstance(guard_error, PaymentError)
        assert isinstance(balance_error, PaymentError)
        assert isinstance(x402_error, PaymentError)
        assert isinstance(crosschain_error, PaymentError)
