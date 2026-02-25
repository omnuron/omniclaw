"""
Ledger for transaction logging.

Simple ledger that uses the unified StorageBackend for persistence.
No separate abstraction layer - just uses storage directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omniclaw.storage.base import StorageBackend


class LedgerEntryType(str, Enum):
    """Types of ledger entries."""

    PAYMENT = "payment"
    REFUND = "refund"
    TRANSFER = "transfer"
    FEE = "fee"


class LedgerEntryStatus(str, Enum):
    """Status of ledger entries."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


@dataclass
class LedgerEntry:
    """
    A single ledger entry representing a transaction.

    Attributes:
        id: Unique entry ID
        timestamp: When the transaction occurred
        wallet_id: Source wallet
        wallet_set_id: Wallet set for grouping
        recipient: Payment recipient
        amount: Transaction amount
        entry_type: Type of entry (payment, refund, etc.)
        status: Current status
        tx_hash: Blockchain transaction hash
        method: Payment method used
        purpose: Human-readable purpose
        metadata: Additional data
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    wallet_id: str = ""
    wallet_set_id: str | None = None
    recipient: str = ""
    amount: Decimal = Decimal("0")
    entry_type: LedgerEntryType = LedgerEntryType.PAYMENT
    status: LedgerEntryStatus = LedgerEntryStatus.PENDING
    tx_hash: str | None = None
    method: str = ""
    purpose: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "wallet_id": self.wallet_id,
            "wallet_set_id": self.wallet_set_id,
            "recipient": self.recipient,
            "amount": str(self.amount),
            "entry_type": self.entry_type.value,
            "status": self.status.value,
            "tx_hash": self.tx_hash,
            "method": self.method,
            "purpose": self.purpose,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedgerEntry:
        """Create LedgerEntry from dictionary."""
        amount = Decimal(str(data.get("amount", "0")))

        ts_str = data.get("timestamp")
        timestamp = datetime.fromisoformat(ts_str) if ts_str else datetime.now()

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            timestamp=timestamp,
            wallet_id=data.get("wallet_id", ""),
            wallet_set_id=data.get("wallet_set_id"),
            recipient=data.get("recipient", ""),
            amount=amount,
            entry_type=LedgerEntryType(data.get("entry_type", LedgerEntryType.PAYMENT.value)),
            status=LedgerEntryStatus(data.get("status", LedgerEntryStatus.PENDING.value)),
            tx_hash=data.get("tx_hash"),
            method=data.get("method", ""),
            purpose=data.get("purpose"),
            metadata=data.get("metadata", {}),
        )


class Ledger:
    """
    Transaction ledger using StorageBackend.

    Simple class that stores and retrieves ledger entries.
    Uses the unified StorageBackend - no separate abstraction needed.
    """

    COLLECTION = "ledger_entries"

    def __init__(self, storage: StorageBackend) -> None:
        """
        Initialize ledger with storage backend.

        Args:
            storage: The unified storage backend (InMemory, Redis, etc.)
        """
        self._storage = storage

    async def record(self, entry: LedgerEntry) -> str:
        """
        Record a transaction.

        Args:
            entry: Ledger entry to record

        Returns:
            Entry ID
        """
        await self._storage.save(self.COLLECTION, entry.id, entry.to_dict())
        return entry.id

    async def get(self, entry_id: str) -> LedgerEntry | None:
        """
        Get entry by ID.

        Args:
            entry_id: Entry ID

        Returns:
            LedgerEntry or None if not found
        """
        data = await self._storage.get(self.COLLECTION, entry_id)
        if not data:
            return None
        return LedgerEntry.from_dict(data)

    async def update_status(
        self,
        entry_id: str,
        status: LedgerEntryStatus,
        tx_hash: str | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> bool:
        """
        Update entry status and metadata.

        Args:
            entry_id: Entry ID
            status: New status
            tx_hash: Optional transaction hash
            metadata_updates: Optional metadata updates to merge

        Returns:
            True if updated, False if not found
        """
        data = await self._storage.get(self.COLLECTION, entry_id)
        if not data:
            return False

        updates = {"status": status.value}
        if tx_hash:
            updates["tx_hash"] = tx_hash

        if metadata_updates:
            # Need to get current metadata first to merge?
            # Merge metadata updates into existing metadata (read-modify-write)
            current_metadata = data.get("metadata", {})
            current_metadata.update(metadata_updates)
            updates["metadata"] = current_metadata

        await self._storage.update(self.COLLECTION, entry_id, updates)
        return True

    async def query(
        self,
        wallet_id: str | None = None,
        wallet_set_id: str | None = None,
        recipient: str | None = None,
        entry_type: LedgerEntryType | None = None,
        status: LedgerEntryStatus | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 100,
    ) -> list[LedgerEntry]:
        """
        Query ledger entries.

        Args:
            wallet_id: Filter by wallet
            wallet_set_id: Filter by wallet set
            recipient: Filter by recipient
            entry_type: Filter by type
            status: Filter by status
            from_date: Entries after this date
            to_date: Entries before this date
            limit: Maximum entries to return

        Returns:
            List of matching entries
        """
        filters = {}
        if wallet_id:
            filters["wallet_id"] = wallet_id
        if wallet_set_id:
            filters["wallet_set_id"] = wallet_set_id
        if recipient:
            filters["recipient"] = recipient
        if entry_type:
            filters["entry_type"] = entry_type.value
        if status:
            filters["status"] = status.value

        # Fetch with extra buffer for date filtering
        fetch_limit = limit * 2 if (from_date or to_date) else limit

        raw_results = await self._storage.query(self.COLLECTION, filters=filters, limit=fetch_limit)

        entries = [LedgerEntry.from_dict(d) for d in raw_results]

        # Apply date filters
        if from_date or to_date:
            entries = [
                e
                for e in entries
                if (not from_date or e.timestamp >= from_date)
                and (not to_date or e.timestamp <= to_date)
            ]

        # Sort by timestamp descending
        entries.sort(key=lambda e: e.timestamp, reverse=True)

        return entries[:limit]

    async def get_total_spent(
        self,
        wallet_id: str,
        from_date: datetime | None = None,
    ) -> Decimal:
        """
        Get total amount spent by a wallet.

        Args:
            wallet_id: Wallet ID
            from_date: Optional start date

        Returns:
            Total spent amount
        """
        filters = {
            "wallet_id": wallet_id,
            "status": LedgerEntryStatus.COMPLETED.value,
        }

        raw_results = await self._storage.query(self.COLLECTION, filters)

        total = Decimal("0")
        for data in raw_results:
            entry = LedgerEntry.from_dict(data)

            if entry.entry_type not in (LedgerEntryType.PAYMENT, LedgerEntryType.TRANSFER):
                continue

            if from_date and entry.timestamp < from_date:
                continue

            total += entry.amount

        return total

    async def clear(self) -> int:
        """
        Clear all ledger entries.

        Returns:
            Number of entries cleared
        """
        return await self._storage.clear(self.COLLECTION)
