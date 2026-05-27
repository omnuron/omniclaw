"""Buyer-side audit reconstruction records."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omniclaw.storage.base import StorageBackend


@dataclass
class AuditEvent:
    """Single buyer-side authorization/audit event."""

    event_type: str
    wallet_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    intent_id: str | None = None
    ledger_entry_id: str | None = None
    agent_id: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    previous_hash: str | None = None
    event_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "wallet_id": self.wallet_id,
            "intent_id": self.intent_id,
            "ledger_entry_id": self.ledger_entry_id,
            "agent_id": self.agent_id,
            "correlation_id": self.correlation_id,
            "payload": self.payload,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEvent:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            event_type=data["event_type"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            wallet_id=data["wallet_id"],
            intent_id=data.get("intent_id"),
            ledger_entry_id=data.get("ledger_entry_id"),
            agent_id=data.get("agent_id"),
            correlation_id=data.get("correlation_id"),
            payload=data.get("payload", {}),
            previous_hash=data.get("previous_hash"),
            event_hash=data.get("event_hash"),
        )

    def hash_payload(self) -> dict[str, Any]:
        """Return the event fields covered by the audit hash."""
        data = self.to_dict()
        data.pop("event_hash", None)
        return data


class BuyerAuditLog:
    """Append-style audit log for reconstructing buyer-side authorization chains."""

    COLLECTION = "buyer_audit_events"
    CHAIN_COLLECTION = "buyer_audit_chains"

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    @staticmethod
    def _derive_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def record(
        self,
        event_type: str,
        *,
        wallet_id: str,
        intent_id: str | None = None,
        ledger_entry_id: str | None = None,
        agent_id: str | None = None,
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        chain_key = f"wallet:{wallet_id}"
        lock_key = f"lock:audit:{chain_key}"
        lock_token = await self._storage.acquire_lock(lock_key, ttl=10)
        if not lock_token:
            raise RuntimeError(f"Audit chain is locked: {wallet_id}")

        event = AuditEvent(
            event_type=event_type,
            wallet_id=wallet_id,
            intent_id=intent_id,
            ledger_entry_id=ledger_entry_id,
            agent_id=agent_id,
            correlation_id=correlation_id,
            payload=payload or {},
        )
        try:
            chain_state = await self._storage.get(self.CHAIN_COLLECTION, chain_key) or {}
            event.previous_hash = chain_state.get("head_hash")
            event.event_hash = self._derive_hash(event.hash_payload())
            await self._storage.save(self.COLLECTION, event.id, event.to_dict())
            await self._storage.save(
                self.CHAIN_COLLECTION,
                chain_key,
                {
                    "head_hash": event.event_hash,
                    "last_event_id": event.id,
                    "updated_at": event.timestamp.isoformat(),
                },
            )
            return event.id
        finally:
            await self._storage.release_lock(lock_key, lock_token)

    async def trace(
        self,
        *,
        wallet_id: str | None = None,
        intent_id: str | None = None,
        ledger_entry_id: str | None = None,
        correlation_id: str | None = None,
        limit: int | None = 100,
        allow_unfiltered: bool = False,
    ) -> list[AuditEvent]:
        filters: dict[str, Any] = {}
        if wallet_id:
            filters["wallet_id"] = wallet_id
        if intent_id:
            filters["intent_id"] = intent_id
        if ledger_entry_id:
            filters["ledger_entry_id"] = ledger_entry_id
        if correlation_id:
            filters["correlation_id"] = correlation_id

        if not filters and not allow_unfiltered:
            raise ValueError("At least one audit trace selector is required.")

        raw_events = await self._storage.query(
            self.COLLECTION,
            filters=filters or None,
            limit=limit,
        )
        events = [AuditEvent.from_dict(event) for event in raw_events]
        events.sort(key=lambda event: event.timestamp)
        return events

    @classmethod
    def verify_events(cls, events: list[AuditEvent]) -> bool:
        """Verify each event hash."""
        for event in events:
            if not event.event_hash:
                return False
            expected_hash = cls._derive_hash(event.hash_payload())
            if expected_hash != event.event_hash:
                return False
        return True

    async def verify_wallet_chain(self, wallet_id: str) -> bool:
        """Verify the full hash-chain order for one wallet's audit events."""
        events = await self.trace(wallet_id=wallet_id, limit=None)
        if not self.verify_events(events):
            return False
        previous_event: AuditEvent | None = None
        for event in events:
            if previous_event and event.previous_hash != previous_event.event_hash:
                return False
            previous_event = event
        return True


__all__ = ["AuditEvent", "BuyerAuditLog"]
