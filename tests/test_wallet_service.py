"""Unit tests for WalletService."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from omniagentpay.core.config import Config
from omniagentpay.core.exceptions import InsufficientBalanceError, WalletError
from omniagentpay.core.types import (
    AccountType,
    Balance,
    CustodyType,
    FeeLevel,
    Network,
    TokenInfo,
    TransactionInfo,
    TransactionState,
    WalletInfo,
    WalletSetInfo,
    WalletState,
)
from omniagentpay.wallet.service import TransferResult, WalletService


@pytest.fixture
def mock_config() -> Config:
    """Create a mock config."""
    return Config(
        circle_api_key="test_key",
        entity_secret="test_secret",
        network=Network.ARC_TESTNET,
        default_wallet_id="default-wallet-123",
    )


@pytest.fixture
def mock_circle_client() -> MagicMock:
    """Create a mock CircleClient."""
    return MagicMock()


@pytest.fixture
def wallet_service(mock_config: Config, mock_circle_client: MagicMock) -> WalletService:
    """Create WalletService with mocked dependencies."""
    return WalletService(mock_config, mock_circle_client)


@pytest.fixture
def sample_wallet_set() -> WalletSetInfo:
    """Create sample wallet set."""
    from datetime import datetime
    return WalletSetInfo(
        id="ws-123",
        name="Test Wallet Set",
        custody_type=CustodyType.DEVELOPER,
        create_date=datetime.now(),
        update_date=datetime.now(),
    )


@pytest.fixture
def sample_wallet() -> WalletInfo:
    """Create sample wallet."""
    return WalletInfo(
        id="wallet-123",
        address="0xabc123...",
        blockchain="ARC-TESTNET",
        state=WalletState.LIVE,
        wallet_set_id="ws-123",
        custody_type=CustodyType.DEVELOPER,
        account_type=AccountType.SCA,
    )


@pytest.fixture
def sample_usdc_balance() -> Balance:
    """Create sample USDC balance."""
    return Balance(
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


class TestWalletSetOperations:
    """Tests for wallet set operations."""
    
    def test_create_wallet_set(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet_set: WalletSetInfo,
    ) -> None:
        """Test creating a wallet set."""
        mock_circle_client.create_wallet_set.return_value = sample_wallet_set
        
        result = wallet_service.create_wallet_set("Test Wallet Set")
        
        assert result.id == "ws-123"
        assert result.name == "Test Wallet Set"
        mock_circle_client.create_wallet_set.assert_called_once_with("Test Wallet Set")
    
    def test_list_wallet_sets(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet_set: WalletSetInfo,
    ) -> None:
        """Test listing wallet sets."""
        mock_circle_client.list_wallet_sets.return_value = [sample_wallet_set]
        
        result = wallet_service.list_wallet_sets()
        
        assert len(result) == 1
        assert result[0].id == "ws-123"
    
    def test_get_wallet_set(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet_set: WalletSetInfo,
    ) -> None:
        """Test getting a wallet set."""
        mock_circle_client.get_wallet_set.return_value = sample_wallet_set
        
        result = wallet_service.get_wallet_set("ws-123")
        
        assert result.id == "ws-123"
        mock_circle_client.get_wallet_set.assert_called_once_with("ws-123")


class TestWalletOperations:
    """Tests for wallet operations."""
    
    def test_create_wallet(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet: WalletInfo,
    ) -> None:
        """Test creating a wallet."""
        mock_circle_client.create_wallets.return_value = [sample_wallet]
        
        result = wallet_service.create_wallet("ws-123")
        
        assert result.id == "wallet-123"
        assert result.address == "0xabc123..."
        mock_circle_client.create_wallets.assert_called_once()
    
    def test_create_wallet_uses_config_network(
        self,
        mock_config: Config,
        mock_circle_client: MagicMock,
        sample_wallet: WalletInfo,
    ) -> None:
        """Test create_wallet uses config network by default."""
        service = WalletService(mock_config, mock_circle_client)
        mock_circle_client.create_wallets.return_value = [sample_wallet]
        
        service.create_wallet("ws-123")
        
        call_kwargs = mock_circle_client.create_wallets.call_args
        assert call_kwargs.kwargs["blockchain"] == Network.ARC_TESTNET
    
    def test_create_wallet_empty_result_raises(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
    ) -> None:
        """Test create_wallet raises on empty result."""
        mock_circle_client.create_wallets.return_value = []
        
        with pytest.raises(WalletError, match="No wallets created"):
            wallet_service.create_wallet("ws-123")
    
    def test_create_multiple_wallets(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet: WalletInfo,
    ) -> None:
        """Test creating multiple wallets."""
        mock_circle_client.create_wallets.return_value = [sample_wallet, sample_wallet]
        
        result = wallet_service.create_wallets("ws-123", count=2)
        
        assert len(result) == 2
    
    def test_get_wallet(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet: WalletInfo,
    ) -> None:
        """Test getting a wallet."""
        mock_circle_client.get_wallet.return_value = sample_wallet
        
        result = wallet_service.get_wallet("wallet-123")
        
        assert result.id == "wallet-123"
    
    def test_get_wallet_uses_cache(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet: WalletInfo,
    ) -> None:
        """Test wallet caching."""
        mock_circle_client.get_wallet.return_value = sample_wallet
        
        # First call
        wallet_service.get_wallet("wallet-123")
        # Second call should use cache
        wallet_service.get_wallet("wallet-123")
        
        # Should only call API once
        mock_circle_client.get_wallet.assert_called_once()
    
    def test_list_wallets(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet: WalletInfo,
    ) -> None:
        """Test listing wallets."""
        mock_circle_client.list_wallets.return_value = [sample_wallet]
        
        result = wallet_service.list_wallets()
        
        assert len(result) == 1
    
    def test_get_default_wallet(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet: WalletInfo,
    ) -> None:
        """Test getting default wallet from config."""
        mock_circle_client.get_wallet.return_value = sample_wallet
        
        result = wallet_service.get_default_wallet()
        
        assert result.id == "wallet-123"
    
    def test_get_default_wallet_not_configured_raises(
        self,
        mock_circle_client: MagicMock,
    ) -> None:
        """Test get_default_wallet raises when not configured."""
        config = Config(
            circle_api_key="test",
            entity_secret="test",
            default_wallet_id=None,
        )
        service = WalletService(config, mock_circle_client)
        
        with pytest.raises(WalletError, match="No default wallet configured"):
            service.get_default_wallet()


class TestBalanceOperations:
    """Tests for balance operations."""
    
    def test_get_balances(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_usdc_balance: Balance,
    ) -> None:
        """Test getting all balances."""
        mock_circle_client.get_wallet_balances.return_value = [sample_usdc_balance]
        
        result = wallet_service.get_balances("wallet-123")
        
        assert len(result) == 1
        assert result[0].currency == "USDC"
    
    def test_get_usdc_balance(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_usdc_balance: Balance,
    ) -> None:
        """Test getting USDC balance."""
        mock_circle_client.get_usdc_balance.return_value = sample_usdc_balance
        
        result = wallet_service.get_usdc_balance("wallet-123")
        
        assert result.amount == Decimal("100.00")
        assert result.currency == "USDC"
    
    def test_get_usdc_balance_none_raises(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
    ) -> None:
        """Test get_usdc_balance raises when no USDC."""
        mock_circle_client.get_usdc_balance.return_value = None
        
        with pytest.raises(WalletError, match="no USDC balance"):
            wallet_service.get_usdc_balance("wallet-123")
    
    def test_get_usdc_balance_amount(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_usdc_balance: Balance,
    ) -> None:
        """Test getting USDC balance amount."""
        mock_circle_client.get_usdc_balance.return_value = sample_usdc_balance
        
        result = wallet_service.get_usdc_balance_amount("wallet-123")
        
        assert result == Decimal("100.00")
    
    def test_get_usdc_balance_amount_returns_zero_when_none(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
    ) -> None:
        """Test get_usdc_balance_amount returns 0 when no USDC."""
        mock_circle_client.get_usdc_balance.return_value = None
        
        result = wallet_service.get_usdc_balance_amount("wallet-123")
        
        assert result == Decimal("0")
    
    def test_has_sufficient_balance(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_usdc_balance: Balance,
    ) -> None:
        """Test checking sufficient balance."""
        mock_circle_client.get_usdc_balance.return_value = sample_usdc_balance
        
        assert wallet_service.has_sufficient_balance("wallet-123", Decimal("50.00")) is True
        assert wallet_service.has_sufficient_balance("wallet-123", Decimal("100.00")) is True
        assert wallet_service.has_sufficient_balance("wallet-123", Decimal("150.00")) is False
    
    def test_ensure_sufficient_balance(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_usdc_balance: Balance,
    ) -> None:
        """Test ensure_sufficient_balance returns balance when sufficient."""
        mock_circle_client.get_usdc_balance.return_value = sample_usdc_balance
        
        result = wallet_service.ensure_sufficient_balance("wallet-123", Decimal("50.00"))
        
        assert result.amount == Decimal("100.00")
    
    def test_ensure_sufficient_balance_raises_when_insufficient(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_usdc_balance: Balance,
    ) -> None:
        """Test ensure_sufficient_balance raises when insufficient."""
        mock_circle_client.get_usdc_balance.return_value = sample_usdc_balance
        
        with pytest.raises(InsufficientBalanceError) as exc_info:
            wallet_service.ensure_sufficient_balance("wallet-123", Decimal("150.00"))
        
        assert exc_info.value.current_balance == Decimal("100.00")
        assert exc_info.value.required_amount == Decimal("150.00")
        assert exc_info.value.shortfall == Decimal("50.00")


class TestTransferOperations:
    """Tests for transfer operations."""
    
    def test_transfer_success(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_usdc_balance: Balance,
    ) -> None:
        """Test successful transfer."""
        mock_circle_client.get_usdc_balance.return_value = sample_usdc_balance
        mock_circle_client.find_usdc_token_id.return_value = "usdc-token-id"
        mock_circle_client.create_transfer.return_value = TransactionInfo(
            id="tx-123",
            state=TransactionState.INITIATED,
        )
        
        result = wallet_service.transfer(
            wallet_id="wallet-123",
            destination_address="0xdest...",
            amount=Decimal("10.00"),
        )
        
        assert result.success is True
        assert result.transaction is not None
    
    def test_transfer_fails_without_usdc_token(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_usdc_balance: Balance,
    ) -> None:
        """Test transfer fails when USDC token not found."""
        mock_circle_client.get_usdc_balance.return_value = sample_usdc_balance
        mock_circle_client.find_usdc_token_id.return_value = None
        
        result = wallet_service.transfer(
            wallet_id="wallet-123",
            destination_address="0xdest...",
            amount=Decimal("10.00"),
        )
        
        assert result.success is False
        assert "USDC token ID" in str(result.error)
    
    def test_transfer_checks_balance(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_usdc_balance: Balance,
    ) -> None:
        """Test transfer checks balance by default."""
        mock_circle_client.get_usdc_balance.return_value = sample_usdc_balance
        
        with pytest.raises(InsufficientBalanceError):
            wallet_service.transfer(
                wallet_id="wallet-123",
                destination_address="0xdest...",
                amount=Decimal("500.00"),  # More than balance
            )
    
    def test_transfer_skip_balance_check(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
    ) -> None:
        """Test transfer can skip balance check."""
        mock_circle_client.find_usdc_token_id.return_value = "usdc-token-id"
        mock_circle_client.create_transfer.return_value = TransactionInfo(
            id="tx-123",
            state=TransactionState.INITIATED,
        )
        
        result = wallet_service.transfer(
            wallet_id="wallet-123",
            destination_address="0xdest...",
            amount=Decimal("500.00"),
            check_balance=False,
        )
        
        assert result.success is True


class TestUtilityMethods:
    """Tests for utility methods."""
    
    def test_setup_agent_wallet(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet_set: WalletSetInfo,
        sample_wallet: WalletInfo,
    ) -> None:
        """Test setup_agent_wallet convenience method."""
        mock_circle_client.create_wallet_set.return_value = sample_wallet_set
        mock_circle_client.create_wallets.return_value = [sample_wallet]
        
        ws, wallet = wallet_service.setup_agent_wallet("My Agent")
        
        assert ws.id == "ws-123"
        assert wallet.id == "wallet-123"
    
    def test_get_or_create_default_wallet_set_existing(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet_set: WalletSetInfo,
    ) -> None:
        """Test get_or_create finds existing wallet set."""
        mock_circle_client.list_wallet_sets.return_value = [sample_wallet_set]
        
        result = wallet_service.get_or_create_default_wallet_set("Test Wallet Set")
        
        assert result.id == "ws-123"
        mock_circle_client.create_wallet_set.assert_not_called()
    
    def test_get_or_create_default_wallet_set_creates_new(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet_set: WalletSetInfo,
    ) -> None:
        """Test get_or_create creates when not found."""
        mock_circle_client.list_wallet_sets.return_value = []
        mock_circle_client.create_wallet_set.return_value = sample_wallet_set
        
        result = wallet_service.get_or_create_default_wallet_set("New Set")
        
        assert result.id == "ws-123"
        mock_circle_client.create_wallet_set.assert_called_once()
    
    def test_clear_cache(
        self,
        wallet_service: WalletService,
        mock_circle_client: MagicMock,
        sample_wallet: WalletInfo,
    ) -> None:
        """Test cache clearing."""
        mock_circle_client.get_wallet.return_value = sample_wallet
        
        # Populate cache
        wallet_service.get_wallet("wallet-123")
        assert len(wallet_service._wallet_cache) == 1
        
        # Clear cache
        wallet_service.clear_cache()
        
        assert len(wallet_service._wallet_cache) == 0


class TestTransferResult:
    """Tests for TransferResult dataclass."""
    
    def test_is_pending_no_transaction(self) -> None:
        """Test is_pending with no transaction."""
        result = TransferResult(success=False, error="No token")
        
        assert result.is_pending is False
    
    def test_is_pending_with_pending_transaction(self) -> None:
        """Test is_pending with pending transaction."""
        result = TransferResult(
            success=True,
            transaction=TransactionInfo(id="tx-1", state=TransactionState.PENDING),
        )
        
        assert result.is_pending is True
    
    def test_is_pending_with_completed_transaction(self) -> None:
        """Test is_pending with completed transaction."""
        result = TransferResult(
            success=True,
            transaction=TransactionInfo(id="tx-1", state=TransactionState.COMPLETE),
        )
        
        assert result.is_pending is False
