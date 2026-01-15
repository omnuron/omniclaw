"""Unit tests for PaymentRouter and TransferAdapter."""

from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock
import pytest

from omniagentpay.core.config import Config
from omniagentpay.payment.router import PaymentRouter
from omniagentpay.protocols.transfer import TransferAdapter, EVM_ADDRESS_PATTERN
from omniagentpay.core.types import (
    Balance,
    FeeLevel,
    Network,
    PaymentMethod,
    PaymentStatus,
    TokenInfo,
    TransactionInfo,
    TransactionState,
)
from omniagentpay.wallet.service import TransferResult


@pytest.fixture
def mock_config() -> Config:
    """Create mock config."""
    return Config(
        circle_api_key="test_key",
        entity_secret="test_secret",
        network=Network.ARC_TESTNET,
    )


@pytest.fixture
def mock_wallet_service() -> MagicMock:
    """Create mock wallet service."""
    service = MagicMock()
    
    # Default balance
    service.get_usdc_balance.return_value = Balance(
        amount=Decimal("100.00"),
        token=TokenInfo(
            id="usdc-token-id",
            blockchain="ARC-TESTNET",
            symbol="USDC",
            name="USD Coin",
            decimals=6,
            is_native=False,
        ),
    )

    # Mock get_wallet
    mock_wallet = MagicMock()
    mock_wallet.blockchain = "ARC-TESTNET"
    service.get_wallet.return_value = mock_wallet
    
    return service


@pytest.fixture
def transfer_adapter(mock_config: Config, mock_wallet_service: MagicMock) -> TransferAdapter:
    """Create TransferAdapter."""
    return TransferAdapter(mock_config, mock_wallet_service)


@pytest.fixture
def payment_router(mock_config: Config, mock_wallet_service: MagicMock) -> PaymentRouter:
    """Create PaymentRouter with TransferAdapter registered."""
    router = PaymentRouter(mock_config, mock_wallet_service)
    router.register_adapter(TransferAdapter(mock_config, mock_wallet_service))
    return router


class TestTransferAdapterSupports:
    """Tests for TransferAdapter.supports()."""
    
    def test_supports_evm_address(self, transfer_adapter: TransferAdapter) -> None:
        """Test EVM address detection."""
        valid_addresses = [
            "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            "0xABCDEF1234567890abcdef1234567890ABCDEF12",
            "0x0000000000000000000000000000000000000000",
        ]
        
        for addr in valid_addresses:
            assert transfer_adapter.supports(addr) is True, f"Should support {addr}"
    
    def test_rejects_invalid_evm_address(self, transfer_adapter: TransferAdapter) -> None:
        """Test invalid EVM addresses rejected."""
        invalid_addresses = [
            "0x742d35Cc6634C0532925a3b844Bc9e7595",  # Too short
            "742d35Cc6634C0532925a3b844Bc9e7595f5e4a",  # Missing 0x
            "0xGGGG35Cc6634C0532925a3b844Bc9e7595f5e4a",  # Invalid hex
            "0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a12",  # Too long
        ]
        
        for addr in invalid_addresses:
            assert transfer_adapter.supports(addr) is False, f"Should reject {addr}"
    
    def test_supports_solana_address(self, transfer_adapter: TransferAdapter) -> None:
        """Test Solana address detection."""
        valid_addresses = [
            "9FMYUH1mcQ9F12yjjk6BciTuBC5kvMKadThs941v5vk7",
            "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
        ]
        
        for addr in valid_addresses:
             # Must pass destination_chain or source_network context for non-default network
            assert transfer_adapter.supports(addr, source_network=Network.SOL) is True, f"Should support {addr}"
    
    def test_rejects_urls(self, transfer_adapter: TransferAdapter) -> None:
        """Test URLs rejected (those are for X402)."""
        urls = [
            "https://api.example.com",
            "http://localhost:8080",
            "https://api.paid.com/resource",
        ]
        
        for url in urls:
            assert transfer_adapter.supports(url) is False, f"Should reject URL {url}"


@pytest.mark.asyncio
class TestTransferAdapterExecute:
    """Tests for TransferAdapter.execute()."""
    
    async def test_execute_success(
        self,
        transfer_adapter: TransferAdapter,
        mock_wallet_service: MagicMock,
    ) -> None:
        """Test successful transfer execution."""
        mock_wallet_service.transfer.return_value = TransferResult(
            success=True,
            transaction=TransactionInfo(
                id="tx-123",
                state=TransactionState.COMPLETE,
                tx_hash="0xabc...",
            ),
            tx_hash="0xabc...",
        )
        
        result = await transfer_adapter.execute(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("10.00"),
            purpose="Test payment",
        )
        
        assert result.success is True
        assert result.method == PaymentMethod.TRANSFER
        assert result.transaction_id == "tx-123"
        assert result.blockchain_tx == "0xabc..."
    
    async def test_execute_invalid_address_fails(
        self,
        transfer_adapter: TransferAdapter,
        mock_wallet_service: MagicMock,
    ) -> None:
        """Test invalid address returns error."""
        # Mock wallet service to raise error for invalid address
        from omniagentpay.core.exceptions import WalletError
        mock_wallet_service.transfer.side_effect = WalletError("Invalid recipient address")

        result = await transfer_adapter.execute(
            wallet_id="wallet-123",
            recipient="invalid-address",
            amount=Decimal("10.00"),
        )
        
        assert result.success is False
        assert result.status == PaymentStatus.FAILED
        assert "Invalid recipient address" in str(result.error)
    
    async def test_execute_transfer_failure(
        self,
        transfer_adapter: TransferAdapter,
        mock_wallet_service: MagicMock,
    ) -> None:
        """Test transfer failure propagates."""
        mock_wallet_service.transfer.return_value = TransferResult(
            success=False,
            error="Insufficient balance",
        )
        
        result = await transfer_adapter.execute(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("10.00"),
        )
        
        assert result.success is False
        assert "Insufficient balance" in str(result.error)


@pytest.mark.asyncio
class TestTransferAdapterSimulate:
    """Tests for TransferAdapter.simulate()."""
    
    async def test_simulate_success(
        self,
        transfer_adapter: TransferAdapter,
        mock_wallet_service: MagicMock,
    ) -> None:
        """Test successful simulation."""
        result = await transfer_adapter.simulate(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("50.00"),
        )
        
        assert result["would_succeed"] is True
        assert result["current_balance"] == "100.00"
        assert result["remaining_balance"] == "50.00"
    
    async def test_simulate_insufficient_balance(
        self,
        transfer_adapter: TransferAdapter,
        mock_wallet_service: MagicMock,
    ) -> None:
        """Test simulation with insufficient balance."""
        result = await transfer_adapter.simulate(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("150.00"),  # More than balance
        )
        
        assert result["would_succeed"] is False
        assert "Insufficient balance" in result["reason"]
        assert result["shortfall"] == "50.00"
    
    async def test_simulate_invalid_address(
        self,
        transfer_adapter: TransferAdapter,
    ) -> None:
        """Test simulation with invalid address."""
        result = await transfer_adapter.simulate(
            wallet_id="wallet-123",
            recipient="invalid-address",
            amount=Decimal("10.00"),
        )
        
        assert result["would_succeed"] is False
        assert "Invalid address" in result["reason"]


class TestPaymentRouterRegistration:
    """Tests for PaymentRouter adapter registration."""
    
    def test_register_adapter(
        self,
        payment_router: PaymentRouter,
    ) -> None:
        """Test adapter registration."""
        adapters = payment_router.get_adapters()
        
        assert len(adapters) == 1
        assert adapters[0].method == PaymentMethod.TRANSFER
    
    def test_unregister_adapter(
        self,
        payment_router: PaymentRouter,
    ) -> None:
        """Test adapter unregistration."""
        payment_router.unregister_adapter(PaymentMethod.TRANSFER)
        
        assert len(payment_router.get_adapters()) == 0


class TestPaymentRouterDetection:
    """Tests for PaymentRouter method detection."""
    
    def test_detect_transfer_method(
        self,
        payment_router: PaymentRouter,
    ) -> None:
        """Test detecting transfer method."""
        method = payment_router.detect_method("0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0")
        
        assert method == PaymentMethod.TRANSFER
    
    def test_detect_unknown_returns_none(
        self,
        payment_router: PaymentRouter,
    ) -> None:
        """Test unknown recipient returns None."""
        method = payment_router.detect_method("https://api.example.com")
        
        # X402 adapter not registered
        assert method is None
    
    def test_can_handle(
        self,
        payment_router: PaymentRouter,
    ) -> None:
        """Test can_handle check."""
        assert payment_router.can_handle("0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0") is True
        assert payment_router.can_handle("https://api.example.com") is False


@pytest.mark.asyncio
class TestPaymentRouterPay:
    """Tests for PaymentRouter.pay()."""
    
    async def test_pay_routes_to_transfer(
        self,
        payment_router: PaymentRouter,
        mock_wallet_service: MagicMock,
    ) -> None:
        """Test payment routes to transfer adapter."""
        mock_wallet_service.transfer.return_value = TransferResult(
            success=True,
            transaction=TransactionInfo(
                id="tx-123",
                state=TransactionState.COMPLETE,
            ),
        )
        
        result = await payment_router.pay(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount="10.00",
        )
        
        assert result.method == PaymentMethod.TRANSFER
    
    async def test_pay_no_adapter_fails(
        self,
        payment_router: PaymentRouter,
    ) -> None:
        """Test payment fails when no adapter found."""
        result = await payment_router.pay(
            wallet_id="wallet-123",
            recipient="https://api.example.com",  # X402 not registered
            amount="10.00",
        )
        
        assert result.success is False
        assert "No adapter found" in str(result.error)
    
    async def test_pay_includes_guards_passed(
        self,
        payment_router: PaymentRouter,
        mock_wallet_service: MagicMock,
    ) -> None:
        """Test guards_passed is included in result."""
        mock_wallet_service.transfer.return_value = TransferResult(
            success=True,
            transaction=TransactionInfo(id="tx-123", state=TransactionState.COMPLETE),
        )
        
        result = await payment_router.pay(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount="10.00",
            guards_passed=["BudgetGuard", "RateLimitGuard"],
        )
        
        assert "BudgetGuard" in result.guards_passed
        assert "RateLimitGuard" in result.guards_passed


@pytest.mark.asyncio
class TestPaymentRouterSimulate:
    """Tests for PaymentRouter.simulate()."""
    
    async def test_simulate_returns_result(
        self,
        payment_router: PaymentRouter,
        mock_wallet_service: MagicMock,
    ) -> None:
        """Test simulation returns SimulationResult."""
        result = await payment_router.simulate(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount="50.00",
        )
        
        assert result.would_succeed is True
        assert result.route == PaymentMethod.TRANSFER
    
    async def test_simulate_no_adapter(
        self,
        payment_router: PaymentRouter,
    ) -> None:
        """Test simulation fails when no adapter found."""
        result = await payment_router.simulate(
            wallet_id="wallet-123",
            recipient="https://api.example.com",
            amount="10.00",
        )
        
        assert result.would_succeed is False
        assert "No adapter found" in str(result.reason)
