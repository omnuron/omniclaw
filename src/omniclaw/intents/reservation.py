"""
Fund Reservation Service (Layer 2 Locking).

Tracks fund holds for pending intents to prevent double-spending
between 2-phase commits and direct payments.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniclaw.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class ReservationService:
    """
    Service for managing fund reservations.

    Used by the 2-phase commit system to reserve funds when a payment intent
    is created, so that subsequent payments or intents don't double-spend
    the same funds.
    """

    COLLECTION = "fund_reservations"

    def __init__(self, storage: StorageBackend) -> None:
        """
        Initialize reservation service.

        Args:
            storage: Storage backend
        """
        self._storage = storage

    async def reserve(
        self, wallet_id: str, amount: Decimal, intent_id: str, expires_at: datetime | None = None
    ) -> str:
        """
        Create a fund reservation.

        Args:
            wallet_id: Wallet ID
            amount: Amount to reserve
            intent_id: Associated payment intent ID
            expires_at: Optional timestamp threshold for reservation invalidation

        Returns:
            Reservation ID (same as intent_id for simplicity)
        """
        data = {
            "wallet_id": wallet_id,
            "amount": str(amount),
            "intent_id": intent_id,
            "created_at": datetime.now().isoformat(),
        }
        if expires_at:
            data["expires_at"] = expires_at.isoformat()

        await self._storage.save(self.COLLECTION, intent_id, data)
        logger.debug(f"Reserved {amount} for wallet {wallet_id} (Intent: {intent_id})")
        return intent_id

    async def release(self, intent_id: str) -> bool:
        """
        Release a fund reservation.

        Args:
            intent_id: Payment intent ID

        Returns:
            True if released, False if not found
        """
        result = await self._storage.delete(self.COLLECTION, intent_id)
        if result:
            logger.debug(f"Released reservation for intent {intent_id}")
        return result

    async def get_reserved_total(self, wallet_id: str) -> Decimal:
        """
        Get the total reserved amount for a wallet.

        Args:
            wallet_id: Wallet ID

        Returns:
            Total reserved amount across all active intents
        """
        filters = {"wallet_id": wallet_id}
        reservations = await self._storage.query(self.COLLECTION, filters=filters)

        total = Decimal("0")
        now = datetime.utcnow()
        for res in reservations:
            # Replay Sweeping Logic:
            # If the reservation has an expires_at block and it's breached,
            # auto-delete it natively to prevent DoS Wallet Locking holes.
            if "expires_at" in res:
                try:
                    expiration_raw = datetime.fromisoformat(res["expires_at"])
                    expiration = (
                        expiration_raw.replace(tzinfo=None)
                        if expiration_raw.tzinfo
                        else expiration_raw
                    )
                    if now > expiration:
                        logger.info(
                            f"Sweeping mathematically expired reservation: {res.get('intent_id')}"
                        )
                        await self.release(res.get("intent_id", ""))
                        continue
                except Exception:
                    logger.warning(
                        "Malformed reservation expiry for intent %s; releasing reservation defensively.",
                        res.get("intent_id"),
                    )
                    await self.release(res.get("intent_id", ""))
                    continue

            amount_str = res.get("amount", "0")
            try:
                total += Decimal(amount_str)
            except Exception as e:
                message = (
                    "Corrupted reservation amount detected "
                    f"(intent={res.get('intent_id')}, value={amount_str!r}): {e}"
                )
                logger.error(message)
                # Fail closed: do not continue if reservation data is corrupted.
                raise ValueError(message) from e

        logger.debug(f"Wallet {wallet_id} has {total} in active reservations")
        return total
