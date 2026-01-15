"""Unit tests for types module."""

from datetime import datetime
from decimal import Decimal

import pytest

from omniagentpay.core.types import (
    AccountType,
    Balance,
    CustodyType,
    FeeLevel,
    Network,
    PaymentMethod,
    PaymentRequest,
    PaymentResult,
    PaymentStatus,
    SimulationResult,
    TokenInfo,
    TransactionInfo,
    TransactionState,
    WalletInfo,
    WalletSetInfo,
    WalletState,
)


class TestNetworkEnum:
    """Tests for Network enum."""
    
    def test_eth_sepolia_value(self) -> None:
        """Test ETH Sepolia has correct value."""
        assert Network.ARC_TESTNET.value == "ARC-TESTNET"
    
    def test_eth_mainnet_value(self) -> None:
        """Test ETH mainnet has correct value."""
        assert Network.ETH.value == "ETH"
    
    def test_from_string_case_insensitive(self) -> None:
        """Test Network.from_string handles different cases."""
        assert Network.from_string("arc-testnet") == Network.ARC_TESTNET
        assert Network.from_string("ARC-TESTNET") == Network.ARC_TESTNET
        assert Network.from_string("Arc-Testnet") == Network.ARC_TESTNET
        assert Network.from_string("arb") == Network.ARB
        assert Network.from_string("sol-devnet") == Network.SOL_DEVNET
        assert Network.from_string("eth-sepolia") == Network.ETH_SEPOLIA
    
    def test_from_string_unknown_raises(self) -> None:
        """Test from_string raises for unknown network."""
        with pytest.raises(ValueError, match="Unknown network"):
            Network.from_string("unknown-chain")
    
    def test_is_testnet(self) -> None:
        """Test is_testnet detection."""
        assert Network.ARC_TESTNET.is_testnet() is True
        assert Network.ARB_SEPOLIA.is_testnet() is True
        assert Network.MATIC_AMOY.is_testnet() is True
        assert Network.SOL_DEVNET.is_testnet() is True
        assert Network.EVM_TESTNET.is_testnet() is True
        assert Network.ETH.is_testnet() is False
        assert Network.ARB.is_testnet() is False
        assert Network.SOL.is_testnet() is False


class TestPaymentMethodEnum:
    """Tests for PaymentMethod enum."""
    
    def test_values(self) -> None:
        """Test payment method values."""
        assert PaymentMethod.X402.value == "x402"
        assert PaymentMethod.TRANSFER.value == "transfer"
        assert PaymentMethod.CROSSCHAIN.value == "crosschain"


class TestPaymentStatusEnum:
    """Tests for PaymentStatus enum."""
    
    def test_values(self) -> None:
        """Test payment status values."""
        assert PaymentStatus.PENDING.value == "pending"
        assert PaymentStatus.PROCESSING.value == "processing"
        assert PaymentStatus.COMPLETED.value == "completed"
        assert PaymentStatus.FAILED.value == "failed"


class TestTokenInfo:
    """Tests for TokenInfo dataclass."""
    
    def test_from_api_response_usdc(self) -> None:
        """Test parsing USDC token from API response."""
        data = {
            "id": "7adb2b7d-c9cd-5164-b2d4-b73b088274dc",
            "blockchain": "ARC-TESTNET",
            "tokenAddress": "0x9999f7fea5938fd3b1e26a12c3f2fb024e194f97",
            "standard": "ERC20",
            "name": "USD Coin",
            "symbol": "USDC",
            "decimals": 6,
            "isNative": False,
        }
        
        token = TokenInfo.from_api_response(data)
        
        assert token.id == "7adb2b7d-c9cd-5164-b2d4-b73b088274dc"
        assert token.blockchain == "ARC-TESTNET"
        assert token.symbol == "USDC"
        assert token.name == "USD Coin"
        assert token.decimals == 6
        assert token.is_native is False
        assert token.token_address == "0x9999f7fea5938fd3b1e26a12c3f2fb024e194f97"
        assert token.standard == "ERC20"
    
    def test_from_api_response_native(self) -> None:
        """Test parsing native token from API response."""
        data = {
            "id": "e4f549f9-a910-59b1-b5cd-8f972871f5db",
            "blockchain": "ARC-TESTNET",
            "name": "Arc",
            "symbol": "ARC",
            "decimals": 18,
            "isNative": True,
        }
        
        token = TokenInfo.from_api_response(data)
        
        assert token.is_native is True
        assert token.token_address is None
        assert token.standard is None


class TestBalance:
    """Tests for Balance dataclass."""
    
    def test_from_api_response(self) -> None:
        """Test parsing balance from API response."""
        data = {
            "token": {
                "id": "7adb2b7d-c9cd-5164-b2d4-b73b088274dc",
                "blockchain": "ARC-TESTNET",
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "isNative": False,
            },
            "amount": "100.50",
        }
        
        balance = Balance.from_api_response(data)
        
        assert balance.amount == Decimal("100.50")
        assert balance.currency == "USDC"
        assert balance.token.symbol == "USDC"


class TestWalletSetInfo:
    """Tests for WalletSetInfo dataclass."""
    
    def test_from_api_response(self) -> None:
        """Test parsing wallet set from API response."""
        data = {
            "id": "0189bc61-7fe4-70f3-8a1b-0d14426397cb",
            "name": "My Agent Wallet Set",
            "custodyType": "DEVELOPER",
            "updateDate": "2023-08-03T17:10:51Z",
            "createDate": "2023-08-03T17:10:51Z",
        }
        
        ws = WalletSetInfo.from_api_response(data)
        
        assert ws.id == "0189bc61-7fe4-70f3-8a1b-0d14426397cb"
        assert ws.name == "My Agent Wallet Set"
        assert ws.custody_type == CustodyType.DEVELOPER
        assert isinstance(ws.create_date, datetime)


class TestWalletInfo:
    """Tests for WalletInfo dataclass."""
    
    def test_from_api_response(self) -> None:
        """Test parsing wallet from API response."""
        data = {
            "id": "ce714f5b-0d8e-4062-9454-61aa1154869b",
            "state": "LIVE",
            "walletSetId": "0189bc61-7fe4-70f3-8a1b-0d14426397cb",
            "custodyType": "DEVELOPER",
            "address": "0xf5c83e5fede8456929d0f90e8c541dcac3d63835",
            "blockchain": "ARC-TESTNET",
            "accountType": "SCA",
            "updateDate": "2023-08-03T19:33:14Z",
            "createDate": "2023-08-03T19:33:14Z",
        }
        
        wallet = WalletInfo.from_api_response(data)
        
        assert wallet.id == "ce714f5b-0d8e-4062-9454-61aa1154869b"
        assert wallet.address == "0xf5c83e5fede8456929d0f90e8c541dcac3d63835"
        assert wallet.blockchain == "ARC-TESTNET"
        assert wallet.state == WalletState.LIVE
        assert wallet.custody_type == CustodyType.DEVELOPER
        assert wallet.account_type == AccountType.SCA


class TestTransactionInfo:
    """Tests for TransactionInfo dataclass."""
    
    def test_from_api_response(self) -> None:
        """Test parsing transaction from API response."""
        data = {
            "id": "1af639ce-c8b2-54a6-af49-7aebc95aaac1",
            "state": "COMPLETE",
            "blockchain": "ARC-TESTNET",
            "txHash": "0x8a3d4f2e...",
            "walletId": "ce714f5b-0d8e-4062-9454-61aa1154869b",
        }
        
        tx = TransactionInfo.from_api_response(data)
        
        assert tx.id == "1af639ce-c8b2-54a6-af49-7aebc95aaac1"
        assert tx.state == TransactionState.COMPLETE
        assert tx.tx_hash == "0x8a3d4f2e..."
        assert tx.is_successful() is True
        assert tx.is_terminal() is True
    
    def test_pending_transaction_not_terminal(self) -> None:
        """Test pending transaction is not terminal."""
        data = {
            "id": "test-id",
            "state": "PENDING",
        }
        
        tx = TransactionInfo.from_api_response(data)
        
        assert tx.is_terminal() is False
        assert tx.is_successful() is False


class TestPaymentRequest:
    """Tests for PaymentRequest dataclass."""
    
    def test_valid_request(self) -> None:
        """Test creating a valid payment request."""
        request = PaymentRequest(
            wallet_id="wallet-123",
            recipient="https://api.example.com",
            amount=Decimal("10.00"),
            purpose="API access",
        )
        
        assert request.wallet_id == "wallet-123"
        assert request.recipient == "https://api.example.com"
        assert request.amount == Decimal("10.00")
        assert request.purpose == "API access"
    
    def test_zero_amount_raises(self) -> None:
        """Test zero amount raises ValueError."""
        with pytest.raises(ValueError, match="Amount must be positive"):
            PaymentRequest(
                wallet_id="wallet-123",
                recipient="0x...",
                amount=Decimal("0"),
            )
    
    def test_negative_amount_raises(self) -> None:
        """Test negative amount raises ValueError."""
        with pytest.raises(ValueError, match="Amount must be positive"):
            PaymentRequest(
                wallet_id="wallet-123",
                recipient="0x...",
                amount=Decimal("-5.00"),
            )
    
    def test_empty_recipient_raises(self) -> None:
        """Test empty recipient raises ValueError."""
        with pytest.raises(ValueError, match="Recipient is required"):
            PaymentRequest(
                wallet_id="wallet-123",
                recipient="",
                amount=Decimal("10.00"),
            )
    
    def test_empty_wallet_id_raises(self) -> None:
        """Test empty wallet_id raises ValueError."""
        with pytest.raises(ValueError, match="Wallet ID is required"):
            PaymentRequest(
                wallet_id="",
                recipient="0x...",
                amount=Decimal("10.00"),
            )


class TestPaymentResult:
    """Tests for PaymentResult dataclass."""
    
    def test_successful_result(self) -> None:
        """Test successful payment result."""
        result = PaymentResult(
            success=True,
            transaction_id="tx-123",
            blockchain_tx="0x8a3d...",
            amount=Decimal("10.00"),
            recipient="https://api.example.com",
            method=PaymentMethod.X402,
            status=PaymentStatus.COMPLETED,
            guards_passed=["BudgetGuard", "RateLimitGuard"],
        )
        
        assert result.success is True
        assert result.transaction_id == "tx-123"
        assert result.method == PaymentMethod.X402
        assert "BudgetGuard" in result.guards_passed
    
    def test_failed_result(self) -> None:
        """Test failed payment result."""
        result = PaymentResult(
            success=False,
            transaction_id=None,
            blockchain_tx=None,
            amount=Decimal("100.00"),
            recipient="0x...",
            method=PaymentMethod.TRANSFER,
            status=PaymentStatus.FAILED,
            error="Insufficient balance",
        )
        
        assert result.success is False
        assert result.error == "Insufficient balance"


class TestSimulationResult:
    """Tests for SimulationResult dataclass."""
    
    def test_simulation_would_succeed(self) -> None:
        """Test successful simulation."""
        result = SimulationResult(
            would_succeed=True,
            route=PaymentMethod.X402,
            guards_that_would_pass=["BudgetGuard", "RateLimitGuard"],
            guards_that_would_fail=[],
        )
        
        assert result.would_succeed is True
        assert result.route == PaymentMethod.X402
    
    def test_simulation_would_fail(self) -> None:
        """Test failed simulation."""
        result = SimulationResult(
            would_succeed=False,
            route=PaymentMethod.TRANSFER,
            guards_that_would_pass=["RateLimitGuard"],
            guards_that_would_fail=["BudgetGuard"],
            reason="Budget exceeded: 95/100 daily",
        )
        
        assert result.would_succeed is False
        assert "BudgetGuard" in result.guards_that_would_fail
        assert result.reason == "Budget exceeded: 95/100 daily"
