"""Buyer-side audit reconstruction records."""

from __future__ import annotations

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
        )


class BuyerAuditLog:
    """Append-style audit log for reconstructing buyer-side authorization chains."""

    COLLECTION = "buyer_audit_events"

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

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
        event = AuditEvent(
            event_type=event_type,
            wallet_id=wallet_id,
            intent_id=intent_id,
            ledger_entry_id=ledger_entry_id,
            agent_id=agent_id,
            correlation_id=correlation_id,
            payload=payload or {},
        )
        await self._storage.save(self.COLLECTION, event.id, event.to_dict())
        return event.id

    async def trace(
        self,
        *,
        wallet_id: str | None = None,
        intent_id: str | None = None,
        ledger_entry_id: str | None = None,
        correlation_id: str | None = None,
        limit: int = 100,
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


__all__ = ["AuditEvent", "BuyerAuditLog"]
