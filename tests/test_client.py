"""
Unit tests for OmniAgentPay Client (Multi-tenant).

Tests the main SDK entry point with per-wallet/wallet-set guards.
"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock, patch
import os

from omniagentpay.client import OmniAgentPay, GuardManager
from omniagentpay.core.types import (
    Network,
    PaymentMethod,
    PaymentStatus,
    PaymentResult,
    SimulationResult,
)
from omniagentpay.guards.budget import BudgetGuard
from omniagentpay.guards.single_tx import SingleTxGuard
from omniagentpay.guards.base import GuardChain, PaymentContext


@pytest.fixture
def mock_env():
    """Set up mock environment variables."""
    with patch.dict(os.environ, {
        "CIRCLE_API_KEY": "test_api_key",
        "ENTITY_SECRET": "test_secret",
    }):
        yield


@pytest.fixture
def client(mock_env) -> OmniAgentPay:
    """Create client with mocked environment."""
    return OmniAgentPay(network=Network.ARC_TESTNET)


class TestClientInitialization:
    """Tests for client initialization."""
    
    def test_init_with_explicit_credentials(self):
        client = OmniAgentPay(
            circle_api_key="explicit_key",
            entity_secret="explicit_secret",
            network=Network.ARC_TESTNET,
        )
        assert client.config.circle_api_key == "explicit_key"
        assert client.config.network == Network.ARC_TESTNET
    
    def test_init_with_env_vars(self, mock_env):
        client = OmniAgentPay()
        assert client.config.circle_api_key == "test_api_key"
    
    def test_init_no_default_wallet(self, mock_env):
        """Multi-tenant: no default_wallet_id parameter."""
        client = OmniAgentPay()
        # No default wallet - must provide wallet_id on each operation
        assert not hasattr(client, "_default_wallet_id") or client._default_wallet_id is None


class TestGuardManager:
    """Tests for GuardManager (per-wallet/wallet-set guards)."""
    
    @pytest.mark.asyncio
    async def test_add_guard_for_wallet(self):
        from omniagentpay.storage.memory import InMemoryStorage
        storage = InMemoryStorage()
        gm = GuardManager(storage)
        guard = SingleTxGuard(max_amount=Decimal("50.00"), name="test")
        await gm.add_guard("wallet-123", guard)
        
        chain = await gm.get_wallet_guards("wallet-123")
        assert chain is not None
        assert len(chain) == 1
    
    @pytest.mark.asyncio
    async def test_add_guard_for_wallet_set(self):
        from omniagentpay.storage.memory import InMemoryStorage
        storage = InMemoryStorage()
        gm = GuardManager(storage)
        guard = BudgetGuard(daily_limit=Decimal("100.00"), name="set_budget")
        await gm.add_guard_for_set("walletset-456", guard)
        
        chain = await gm.get_wallet_set_guards("walletset-456")
        assert chain is not None
        assert len(chain) == 1
    
    @pytest.mark.asyncio
    async def test_remove_guard_from_wallet(self):
        from omniagentpay.storage.memory import InMemoryStorage
        storage = InMemoryStorage()
        gm = GuardManager(storage)
        guard = SingleTxGuard(max_amount=Decimal("50.00"), name="test_guard")
        await gm.add_guard("wallet-123", guard)
        
        result = await gm.remove_guard("wallet-123", "test_guard")
        assert result is True
        chain = await gm.get_wallet_guards("wallet-123")
        assert len(chain) == 0
    
    @pytest.mark.asyncio
    async def test_get_combined_guard_chain(self):
        from omniagentpay.storage.memory import InMemoryStorage
        storage = InMemoryStorage()
        gm = GuardManager(storage)
        
        # Add wallet-set level guard
        set_guard = BudgetGuard(daily_limit=Decimal("500.00"), name="set_budget")
        await gm.add_guard_for_set("walletset-456", set_guard)
        
        # Add wallet-specific guard
        wallet_guard = SingleTxGuard(max_amount=Decimal("25.00"), name="wallet_limit")
        await gm.add_guard("wallet-123", wallet_guard)
        
        # Get combined chain
        chain = await gm.get_guard_chain("wallet-123", "walletset-456")
        assert len(chain) == 2
    
    @pytest.mark.asyncio
    async def test_list_guard_names(self):
        from omniagentpay.storage.memory import InMemoryStorage
        storage = InMemoryStorage()
        gm = GuardManager(storage)
        await gm.add_guard("w1", SingleTxGuard(max_amount=Decimal("10"), name="guard1"))
        await gm.add_guard("w1", BudgetGuard(daily_limit=Decimal("100"), name="guard2"))
        
        names = await gm.list_wallet_guard_names("w1")
        assert "guard1" in names
        assert "guard2" in names


class TestClientGuardManagement:
    """Tests for client.guards property (GuardManager)."""
    
    @pytest.mark.asyncio
    async def test_add_guard_via_client(self, client):
        guard = SingleTxGuard(max_amount=Decimal("50.00"), name="test")
        await client.guards.add_guard("wallet-123", guard)
        
        chain = await client.guards.get_wallet_guards("wallet-123")
        assert chain is not None
        assert len(chain) == 1
    
    @pytest.mark.asyncio
    async def test_add_guard_for_set_via_client(self, client):
        guard = BudgetGuard(daily_limit=Decimal("100.00"), name="set_budget")
        await client.guards.add_guard_for_set("walletset-456", guard)
        
        chain = await client.guards.get_wallet_set_guards("walletset-456")
        assert chain is not None


class TestLedgerProperty:
    """Tests for ledger property."""
    
    def test_ledger_exists(self, client):
        assert client.ledger is not None
    
    @pytest.mark.asyncio
    async def test_ledger_records_entries(self, client):
        from omniagentpay.ledger import LedgerEntry
        
        entry = LedgerEntry(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("10.00"),
        )
        await client.ledger.record(entry)
        
        retrieved = await client.ledger.get(entry.id)
        assert retrieved is not None


class TestCanPay:
    """Tests for can_pay() method."""
    
    def test_can_pay_evm_address(self, client):
        result = client.can_pay("0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0")
        assert result is True
    
    def test_cannot_pay_invalid_recipient(self, client):
        result = client.can_pay("invalid-recipient")
        assert result is False


class TestDetectMethod:
    """Tests for detect_method()."""
    
    def test_detect_transfer(self, client):
        method = client.detect_method("0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0")
        assert method == PaymentMethod.TRANSFER
    
    def test_detect_none_for_invalid(self, client):
        method = client.detect_method("invalid")
        assert method is None


class TestSimulate:
    """Tests for simulate() method."""
    
    @pytest.mark.asyncio
    async def test_simulate_requires_wallet_id(self, client):
        # wallet_id is now required
        result = await client.simulate(
            wallet_id="",  # Empty string
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("10.00"),
        )
        assert result.would_succeed is False
        assert "wallet_id" in result.reason.lower() or "required" in result.reason.lower()
    
    @pytest.mark.asyncio
    async def test_simulate_blocked_by_guard(self, client):
        # Add guard for this wallet
        await client.guards.add_guard(
            "wallet-123",
            SingleTxGuard(max_amount=Decimal("5.00"), name="limit"),
        )
        
        result = await client.simulate(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("10.00"),
        )
        assert result.would_succeed is False
        assert "guard" in result.reason.lower() or "blocked" in result.reason.lower()


class TestPayBlocked:
    """Tests for pay() when blocked by guards."""
    
    @pytest.mark.asyncio
    async def test_pay_blocked_by_single_tx_guard(self, client):
        # Add guard for this wallet
        await client.guards.add_guard(
            "wallet-123",
            SingleTxGuard(max_amount=Decimal("5.00"), name="limit"),
        )
        
        result = await client.pay(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("10.00"),
        )
        
        assert result.success is False
        assert result.status == PaymentStatus.BLOCKED
    
    @pytest.mark.asyncio
    async def test_pay_blocked_records_to_ledger(self, client):
        await client.guards.add_guard(
            "wallet-123",
            SingleTxGuard(max_amount=Decimal("5.00"), name="limit"),
        )
        
        await client.pay(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("10.00"),
        )
        
        entries = await client.ledger.query(wallet_id="wallet-123", limit=1)
        assert len(entries) == 1
        
        from omniagentpay.ledger import LedgerEntryStatus
        assert entries[0].status == LedgerEntryStatus.BLOCKED


class TestPayRequiresWallet:
    """Tests that pay() requires wallet_id."""
    
    @pytest.mark.asyncio
    async def test_pay_empty_wallet_raises(self, client):
        from omniagentpay.core.exceptions import ValidationError
        
        with pytest.raises(ValidationError):
            await client.pay(
                wallet_id="",  # Empty
                recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
                amount=Decimal("10.00"),
            )
