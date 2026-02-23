"""
PaymentIntentService - Manages lifecycle of Payment Intents.

Handles storage and retrieval of intents for Authorize/Capture workflows.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from omniclaw.core.exceptions import ValidationError
from omniclaw.core.types import PaymentIntent, PaymentIntentStatus

if TYPE_CHECKING:
    from omniclaw.storage.base import StorageBackend


class PaymentIntentService:
    """
    Service for managing Payment Intents.

    Persists intents to storage backend (Redis/Memory).
    """

    COLLECTION = "payment_intents"

    def __init__(self, storage: StorageBackend) -> None:
        """Initialize with storage backend."""
        self._storage = storage

    def _make_key(self, intent_id: str) -> str:
        """Create storage key for intent."""
        return f"intent:{intent_id}"

    async def create(
        self,
        wallet_id: str,
        recipient: str,
        amount: Decimal,
        currency: str = "USDC",
        metadata: dict[str, Any] | None = None,
        client_secret: str | None = None,
    ) -> PaymentIntent:
        """
        Create a new payment intent.

        Args:
            wallet_id: Source wallet ID
            recipient: Payment recipient
            amount: Amount to pay
            currency: Currency code (default USDC)
            metadata: Additional metadata
            client_secret: Optional client secret for future use

        Returns:
            PaymentIntent instance
        """
        intent_id = str(uuid.uuid4())
        intent = PaymentIntent(
            id=intent_id,
            wallet_id=wallet_id,
            recipient=recipient,
            amount=amount,
            currency=currency,
            status=PaymentIntentStatus.REQUIRES_CONFIRMATION,
            created_at=datetime.utcnow(),
            metadata=metadata or {},
            client_secret=client_secret,
        )

        await self._save(intent)
        return intent

    async def get(self, intent_id: str) -> PaymentIntent | None:
        """Get intent by ID."""
        return await self._load(intent_id)

    async def update_status(self, intent_id: str, status: PaymentIntentStatus) -> PaymentIntent:
        """
        Update intent status.

        Args:
            intent_id: Intent ID
            status: New status

        Raises:
            ValidationError: If intent not found
        """
        intent = await self.get(intent_id)
        if not intent:
            raise ValidationError(f"Intent not found: {intent_id}")

        intent.status = status
        await self._save(intent)
        return intent

    async def _save(self, intent: PaymentIntent) -> None:
        """Save intent to storage."""
        key = self._make_key(intent.id)
        await self._storage.save(self.COLLECTION, key, intent.to_dict())

    async def _load(self, intent_id: str) -> PaymentIntent | None:
        """Load intent from storage."""
        key = self._make_key(intent_id)
        data = await self._storage.get(self.COLLECTION, key)
        if not data:
            return None
        return PaymentIntent.from_dict(data)
