"""
Unit tests for Ledger module.

Tests LedgerEntry and Ledger class.
"""

from decimal import Decimal

import pytest

from omniclaw.ledger import (
    Ledger,
    LedgerEntry,
    LedgerEntryStatus,
    LedgerEntryType,
)
from omniclaw.storage.memory import InMemoryStorage


class TestLedgerEntry:
    """Tests for LedgerEntry dataclass."""

    def test_default_values(self):
        entry = LedgerEntry()
        assert entry.id is not None
        assert entry.status == LedgerEntryStatus.PENDING
        assert entry.entry_type == LedgerEntryType.PAYMENT
        assert entry.amount == Decimal("0")

    def test_custom_values(self):
        entry = LedgerEntry(
            wallet_id="wallet-123",
            recipient="0xabc",
            amount=Decimal("50.00"),
            purpose="API payment",
            status=LedgerEntryStatus.COMPLETED,
        )
        assert entry.wallet_id == "wallet-123"
        assert entry.recipient == "0xabc"
        assert entry.amount == Decimal("50.00")
        assert entry.purpose == "API payment"
        assert entry.status == LedgerEntryStatus.COMPLETED

    def test_to_dict(self):
        entry = LedgerEntry(
            wallet_id="w1",
            recipient="0x123",
            amount=Decimal("10.00"),
        )
        d = entry.to_dict()

        assert d["wallet_id"] == "w1"
        assert d["recipient"] == "0x123"
        assert d["amount"] == "10.00"
        assert "timestamp" in d
        assert "id" in d


class TestLedgerEntryStatus:
    """Tests for LedgerEntryStatus enum."""

    def test_all_statuses_exist(self):
        assert LedgerEntryStatus.PENDING.value == "pending"
        assert LedgerEntryStatus.COMPLETED.value == "completed"
        assert LedgerEntryStatus.FAILED.value == "failed"
        assert LedgerEntryStatus.CANCELLED.value == "cancelled"
        assert LedgerEntryStatus.BLOCKED.value == "blocked"


class TestLedger:
    """Tests for Ledger implementation."""

    @pytest.fixture
    def ledger(self) -> Ledger:
        storage = InMemoryStorage()
        return Ledger(storage)

    @pytest.mark.asyncio
    async def test_record_entry(self, ledger):
        entry = LedgerEntry(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("25.00"),
        )

        entry_id = await ledger.record(entry)
        assert entry_id == entry.id

    @pytest.mark.asyncio
    async def test_get_entry(self, ledger):
        entry = LedgerEntry(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("25.00"),
        )
        await ledger.record(entry)

        retrieved = await ledger.get(entry.id)
        assert retrieved is not None
        assert retrieved.wallet_id == "w1"
        assert retrieved.amount == Decimal("25.00")

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, ledger):
        retrieved = await ledger.get("nonexistent-id")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_update_status(self, ledger):
        entry = LedgerEntry(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("25.00"),
            status=LedgerEntryStatus.PENDING,
        )
        await ledger.record(entry)

        success = await ledger.update_status(
            entry.id,
            LedgerEntryStatus.COMPLETED,
            tx_hash="0xtxhash123",
        )

        assert success is True

        retrieved = await ledger.get(entry.id)
        assert retrieved.status == LedgerEntryStatus.COMPLETED
        assert retrieved.tx_hash == "0xtxhash123"

    @pytest.mark.asyncio
    async def test_query_by_wallet(self, ledger):
        # Add entries for different wallets
        entry1 = LedgerEntry(wallet_id="w1", recipient="0xa", amount=Decimal("10"))
        entry2 = LedgerEntry(wallet_id="w1", recipient="0xb", amount=Decimal("20"))
        entry3 = LedgerEntry(wallet_id="w2", recipient="0xc", amount=Decimal("30"))

        await ledger.record(entry1)
        await ledger.record(entry2)
        await ledger.record(entry3)

        results = await ledger.query(wallet_id="w1")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_query_by_status(self, ledger):
        entry1 = LedgerEntry(wallet_id="w1", recipient="0xa", amount=Decimal("10"))
        entry2 = LedgerEntry(wallet_id="w1", recipient="0xb", amount=Decimal("20"))

        await ledger.record(entry1)
        await ledger.record(entry2)
        await ledger.update_status(entry1.id, LedgerEntryStatus.COMPLETED)

        results = await ledger.query(status=LedgerEntryStatus.PENDING)
        assert len(results) == 1
        assert results[0].id == entry2.id

    @pytest.mark.asyncio
    async def test_query_by_recipient(self, ledger):
        entry1 = LedgerEntry(wallet_id="w1", recipient="0xabc", amount=Decimal("10"))
        entry2 = LedgerEntry(wallet_id="w1", recipient="0xdef", amount=Decimal("20"))

        await ledger.record(entry1)
        await ledger.record(entry2)

        results = await ledger.query(recipient="0xabc")
        assert len(results) == 1
        assert results[0].recipient == "0xabc"

    @pytest.mark.asyncio
    async def test_query_with_limit(self, ledger):
        for i in range(10):
            entry = LedgerEntry(
                wallet_id="w1",
                recipient="0xabc",
                amount=Decimal(f"{i}.00"),
            )
            await ledger.record(entry)

        results = await ledger.query(limit=5)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_get_total_spent(self, ledger):
        entry1 = LedgerEntry(
            wallet_id="w1",
            recipient="0xa",
            amount=Decimal("10.00"),
            status=LedgerEntryStatus.COMPLETED,
        )
        entry2 = LedgerEntry(
            wallet_id="w1",
            recipient="0xb",
            amount=Decimal("25.00"),
            status=LedgerEntryStatus.COMPLETED,
        )
        entry3 = LedgerEntry(
            wallet_id="w1",
            recipient="0xc",
            amount=Decimal("15.00"),
            status=LedgerEntryStatus.PENDING,  # Not completed
        )

        await ledger.record(entry1)
        await ledger.record(entry2)
        await ledger.record(entry3)

        # Update statuses to reflect what we set
        await ledger.update_status(entry1.id, LedgerEntryStatus.COMPLETED)
        await ledger.update_status(entry2.id, LedgerEntryStatus.COMPLETED)

        total = await ledger.get_total_spent("w1")
        # Should only count COMPLETED entries
        assert total == Decimal("35.00")

    @pytest.mark.asyncio
    async def test_blocked_entries_recorded(self, ledger):
        entry = LedgerEntry(
            wallet_id="w1",
            recipient="0xabc",
            amount=Decimal("100.00"),
            status=LedgerEntryStatus.PENDING,
        )
        await ledger.record(entry)

        await ledger.update_status(entry.id, LedgerEntryStatus.BLOCKED)

        retrieved = await ledger.get(entry.id)
        assert retrieved.status == LedgerEntryStatus.BLOCKED
