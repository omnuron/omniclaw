"""
Unit tests for OmniClaw Client (Multi-tenant).

Tests the main SDK entry point with per-wallet/wallet-set guards.
"""

import os
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from omniclaw.client import GuardManager, OmniClaw
from omniclaw.core.exceptions import ConfigurationError
from omniclaw.core.types import (
    Network,
    PaymentMethod,
    PaymentResult,
    PaymentStatus,
)
from omniclaw.guards.budget import BudgetGuard
from omniclaw.guards.single_tx import SingleTxGuard
from omniclaw.onboarding import store_managed_credentials


@pytest.fixture
def mock_env():
    """Set up mock environment variables."""
    with patch.dict(
        os.environ,
        {
            "CIRCLE_API_KEY": "test_api_key",
            "ENTITY_SECRET": "test_secret",
            "OMNICLAW_STORAGE_BACKEND": "memory",
        },
    ):
        yield


@pytest.fixture
def client(mock_env) -> OmniClaw:
    """Create client with mocked environment."""
    return OmniClaw(network=Network.ARC_TESTNET)


class TestClientInitialization:
    """Tests for client initialization."""

    def test_init_with_explicit_credentials(self):
        client = OmniClaw(
            circle_api_key="explicit_key",
            entity_secret="explicit_secret",
            network=Network.ARC_TESTNET,
        )
        assert client.config.circle_api_key == "explicit_key"
        assert client.config.network == Network.ARC_TESTNET

    def test_init_with_env_vars(self, mock_env):
        client = OmniClaw()
        assert client.config.circle_api_key == "test_api_key"

    def test_init_no_default_wallet(self, mock_env):
        """Multi-tenant: no default_wallet_id parameter."""
        client = OmniClaw()
        # No default wallet - must provide wallet_id on each operation
        assert not hasattr(client, "_default_wallet_id") or client._default_wallet_id is None

    def test_init_loads_entity_secret_from_managed_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            xdg_config_home = Path(tmpdir) / "xdg"
            with patch.dict(
                os.environ,
                {
                    "CIRCLE_API_KEY": "managed_api_key",
                    "XDG_CONFIG_HOME": str(xdg_config_home),
                },
                clear=True,
            ):
                store_managed_credentials(
                    "managed_api_key",
                    "managed_secret",
                    source="test",
                )

                client = OmniClaw(network=Network.ARC_TESTNET)
                assert client.config.entity_secret == "managed_secret"

    def test_init_production_requires_hardening_envs(self):
        with patch.dict(
            os.environ,
            {
                "CIRCLE_API_KEY": "prod_api_key",
                "ENTITY_SECRET": "prod_entity_secret",
                "OMNICLAW_ENV": "production",
            },
            clear=True,
        ), pytest.raises(
            ConfigurationError, match="Missing required production environment variables"
        ):
            OmniClaw(network=Network.ARC_TESTNET)

    def test_init_production_requires_strict_settlement(self):
        with patch.dict(
            os.environ,
            {
                "CIRCLE_API_KEY": "prod_api_key",
                "ENTITY_SECRET": "prod_entity_secret",
                "OMNICLAW_ENV": "production",
                "OMNICLAW_SELLER_NONCE_REDIS_URL": "redis://localhost:6379/0",
                "OMNICLAW_WEBHOOK_VERIFICATION_KEY": "dummy-key",
                "OMNICLAW_WEBHOOK_DEDUP_DB_PATH": "/tmp/omniclaw_webhook_dedup.sqlite3",
                "OMNICLAW_STRICT_SETTLEMENT": "false",
            },
            clear=True,
        ), pytest.raises(ConfigurationError, match="OMNICLAW_STRICT_SETTLEMENT must be true"):
            OmniClaw(network=Network.ARC_TESTNET)


class TestGuardManager:
    """Tests for GuardManager (per-wallet/wallet-set guards)."""

    @pytest.mark.asyncio
    async def test_add_guard_for_wallet(self):
        from omniclaw.storage.memory import InMemoryStorage

        storage = InMemoryStorage()
        gm = GuardManager(storage)
        guard = SingleTxGuard(max_amount=Decimal("50.00"), name="test")
        await gm.add_guard("wallet-123", guard)

        chain = await gm.get_wallet_guards("wallet-123")
        assert chain is not None
        assert len(chain) == 1

    @pytest.mark.asyncio
    async def test_add_guard_for_wallet_set(self):
        from omniclaw.storage.memory import InMemoryStorage

        storage = InMemoryStorage()
        gm = GuardManager(storage)
        guard = BudgetGuard(daily_limit=Decimal("100.00"), name="set_budget")
        await gm.add_guard_for_set("walletset-456", guard)

        chain = await gm.get_wallet_set_guards("walletset-456")
        assert chain is not None
        assert len(chain) == 1

    @pytest.mark.asyncio
    async def test_remove_guard_from_wallet(self):
        from omniclaw.storage.memory import InMemoryStorage

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
        from omniclaw.storage.memory import InMemoryStorage

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
        from omniclaw.storage.memory import InMemoryStorage

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
        from omniclaw.ledger import LedgerEntry

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
        client._wallet_service.get_usdc_balance_amount = lambda wid: Decimal("100.00")

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

        from omniclaw.ledger import LedgerEntryStatus

        assert entries[0].status == LedgerEntryStatus.BLOCKED


class TestPayRequiresWallet:
    """Tests that pay() requires wallet_id."""

    @pytest.mark.asyncio
    async def test_pay_empty_wallet_raises(self, client):
        from omniclaw.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            await client.pay(
                wallet_id="",  # Empty
                recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
                amount=Decimal("10.00"),
            )


class TestPayIdempotency:
    @pytest.mark.asyncio
    async def test_pay_derives_deterministic_idempotency_key(self, client):
        from unittest.mock import AsyncMock

        captured_keys: list[str] = []

        async def _mock_pay(**kwargs):
            captured_keys.append(kwargs["idempotency_key"])
            return PaymentResult(
                success=True,
                transaction_id="tx-1",
                blockchain_tx="0xabc",
                amount=Decimal("1.00"),
                recipient=kwargs["recipient"],
                method=PaymentMethod.TRANSFER,
                status=PaymentStatus.COMPLETED,
            )

        client._wallet_service.get_usdc_balance_amount = lambda _wid: Decimal("100.00")
        client._router.pay = AsyncMock(side_effect=_mock_pay)

        await client.pay(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("1.00"),
            skip_guards=True,
        )
        await client.pay(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("1.00"),
            skip_guards=True,
        )

        assert len(captured_keys) == 2
        assert captured_keys[0] == captured_keys[1]


class TestSettlementReconciliation:
    @pytest.mark.asyncio
    async def test_finalize_pending_settlement_marks_completed(self, client):
        from omniclaw.ledger import LedgerEntry, LedgerEntryStatus

        entry = LedgerEntry(
            wallet_id="wallet-123",
            recipient="0x742d35Cc6634C0532925a3b844Bc9e7595f5e4a0",
            amount=Decimal("1.00"),
            status=LedgerEntryStatus.PENDING,
            metadata={"settlement_final": False},
        )
        await client.ledger.record(entry)

        updated = await client.finalize_pending_settlement(
            entry.id,
            settled=True,
            settlement_tx_hash="0xminttx",
            reason="Mint confirmed",
        )
        assert updated.status == LedgerEntryStatus.COMPLETED
        assert updated.metadata["settlement_final"] is True
        assert updated.tx_hash == "0xminttx"

    @pytest.mark.asyncio
    async def test_list_pending_settlements_filters_by_status(self, client):
        from omniclaw.ledger import LedgerEntry, LedgerEntryStatus

        await client.ledger.record(
            LedgerEntry(
                wallet_id="wallet-123",
                recipient="0x1111111111111111111111111111111111111111",
                amount=Decimal("1.00"),
                status=LedgerEntryStatus.PENDING,
            )
        )
        await client.ledger.record(
            LedgerEntry(
                wallet_id="wallet-123",
                recipient="0x2222222222222222222222222222222222222222",
                amount=Decimal("1.00"),
                status=LedgerEntryStatus.COMPLETED,
            )
        )

        pending = await client.list_pending_settlements(wallet_id="wallet-123")
        assert all(p.status == LedgerEntryStatus.PENDING for p in pending)

    @pytest.mark.asyncio
    async def test_reconcile_pending_settlements_finalizes_completed(self, client):
        from omniclaw.ledger import LedgerEntry, LedgerEntryStatus

        entry = LedgerEntry(
            wallet_id="wallet-123",
            recipient="0x3333333333333333333333333333333333333333",
            amount=Decimal("2.00"),
            status=LedgerEntryStatus.PENDING,
            metadata={"transaction_id": "tx-123"},
        )
        await client.ledger.record(entry)

        tx_info = MagicMock()
        tx_info.state = "COMPLETE"
        tx_info.tx_hash = "0xcomplete"
        tx_info.fee_level = None

        circle = MagicMock()
        circle.get_transaction.return_value = tx_info
        client._wallet_service = MagicMock()
        client._wallet_service._circle = circle

        stats = await client.reconcile_pending_settlements(wallet_id="wallet-123")

        assert stats["processed"] >= 1
        assert stats["finalized"] >= 1

        updated = await client.ledger.get(entry.id)
        assert updated is not None
        assert updated.status == LedgerEntryStatus.COMPLETED
        assert updated.metadata.get("settlement_final") is True
