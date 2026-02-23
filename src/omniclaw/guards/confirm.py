"""
ConfirmGuard - Requires explicit confirmation for payments.

Simple guard that requires confirmation above a threshold or for all payments.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

from omniclaw.guards.base import Guard, GuardResult, PaymentContext

# Type for confirmation callback
ConfirmCallback = Callable[[PaymentContext], Awaitable[bool]]


class ConfirmGuard(Guard):
    """
    Guard that requires explicit confirmation for payments.

    Useful for high-value transactions or sensitive recipients.

    Two modes of operation:
    1. **Callback mode**: Provide a callback that gets called for confirmation
    2. **Threshold only**: Blocks payments above threshold (requires external handling)
    """

    def __init__(
        self,
        confirm_callback: ConfirmCallback | None = None,
        threshold: Decimal | None = None,
        always_confirm: bool = False,
        name: str = "confirm",
    ) -> None:
        """
        Initialize ConfirmGuard.

        Args:
            confirm_callback: Async function to call for confirmation
            threshold: Only confirm payments above this amount
            always_confirm: If True, confirm all payments
            name: Guard name for identification
        """
        self._name = name
        self._callback = confirm_callback
        self._threshold = threshold
        self._always_confirm = always_confirm

    @property
    def name(self) -> str:
        return self._name

    @property
    def threshold(self) -> Decimal | None:
        return self._threshold

    def _needs_confirmation(self, amount: Decimal) -> bool:
        """Check if amount requires confirmation."""
        if self._always_confirm:
            return True
        return self._threshold is not None and amount >= self._threshold

    async def check(self, context: PaymentContext) -> GuardResult:
        """Check if payment is confirmed."""
        if not self._needs_confirmation(context.amount):
            return GuardResult(
                allowed=True,
                guard_name=self.name,
                metadata={"confirmation_required": False},
            )

        # If we have a callback, use it
        if self._callback is not None:
            try:
                confirmed = await self._callback(context)
                if confirmed:
                    return GuardResult(
                        allowed=True,
                        guard_name=self.name,
                        metadata={"confirmation_required": True, "confirmed": True},
                    )
                else:
                    return GuardResult(
                        allowed=False,
                        reason="Payment not confirmed by user",
                        guard_name=self.name,
                        metadata={"confirmation_required": True, "confirmed": False},
                    )
            except Exception as e:
                return GuardResult(
                    allowed=False,
                    reason=f"Confirmation callback failed: {e}",
                    guard_name=self.name,
                    metadata={"confirmation_required": True, "error": str(e)},
                )

        # No callback - block and indicate confirmation needed
        return GuardResult(
            allowed=False,
            reason=(
                f"Payment of {context.amount} requires confirmation. "
                "Set a confirm_callback or handle confirmation externally."
            ),
            guard_name=self.name,
            metadata={
                "confirmation_required": True,
                "amount": str(context.amount),
                "threshold": str(self._threshold) if self._threshold else None,
            },
        )

    def reset(self) -> None:
        """No state to reset."""
        pass
