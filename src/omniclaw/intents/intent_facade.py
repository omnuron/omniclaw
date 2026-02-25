"""
Payment Intent Facade for OmniClaw.

Provides the `client.intent.create/confirm/cancel` API according to the
OmniClaw vision document.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from omniclaw.core.types import PaymentIntent, PaymentResult

if TYPE_CHECKING:
    from omniclaw.client import OmniClaw

logger = logging.getLogger(__name__)


class PaymentIntentFacade:
    """
    Facade for managing payment intents via the `client.intent` property.

    This provides the user-friendly API described in the vision document:
    - client.intent.create(...)
    - client.intent.confirm(...)
    - client.intent.cancel(...)
    """

    def __init__(self, client: OmniClaw) -> None:
        """
        Initialize the facade.

        Args:
            client: The main OmniClaw client instance
        """
        self._client = client

    async def create(
        self,
        wallet_id: str,
        recipient: str,
        amount: str | float,
        purpose: str | None = None,
        expires_in: int | None = None,
        destination_chain: str | None = None,
        **kwargs: Any,
    ) -> PaymentIntent:
        """
        Create a new payment intent (Phase 1 of 2-phase commit).

        This will:
        1. Parse amount and identify missing context
        2. Simulate the payment (including guard checks)
        3. If simulation passes, create the intent
        4. Reserve the funds in the wallet so they can't be spent elsewhere

        Args:
            wallet_id: Source wallet ID
            recipient: Payment recipient (address, URL, etc.)
            amount: Amount to pay
            purpose: Human-readable purpose of the payment
            expires_in: Expiration time in seconds
            destination_chain: Optional destination chain for cross-chain
            **kwargs: Additional parameters for specific protocols

        Returns:
            Created PaymentIntent (status: REQUIRES_CONFIRMATION)
        """
        return await self._client.create_payment_intent(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=amount,
            purpose=purpose,
            expires_in=expires_in,
            destination_chain=destination_chain,
            **kwargs,
        )

    async def confirm(self, intent_id: str) -> PaymentResult:
        """
        Confirm and execute a payment intent (Phase 2 of 2-phase commit).

        This will:
        1. Load the intent and verify it's in REQUIRES_CONFIRMATION state
        2. Execute the payment using the previously reserved funds
        3. Update the intent status
        4. Release the fund reservation

        Args:
            intent_id: ID of the intent to confirm

        Returns:
            PaymentResult indicating success or failure
        """
        return await self._client.confirm_payment_intent(intent_id)

    async def cancel(self, intent_id: str, reason: str | None = None) -> PaymentIntent:
        """
        Cancel a payment intent.

        This will release any funds reserved for the intent.

        Args:
            intent_id: ID of the intent to cancel
            reason: Optional reason for cancellation

        Returns:
            Updated PaymentIntent (status: CANCELED)
        """
        return await self._client.cancel_payment_intent(intent_id, reason=reason)

    async def get(self, intent_id: str) -> PaymentIntent | None:
        """
        Get a payment intent by ID.

        Args:
            intent_id: ID of the intent to retrieve

        Returns:
            PaymentIntent or None if not found
        """
        return await self._client.get_payment_intent(intent_id)
