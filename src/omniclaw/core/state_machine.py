"""State transition rules for payment and intent lifecycles."""

from __future__ import annotations

from omniclaw.core.exceptions import ValidationError
from omniclaw.core.types import PaymentIntentStatus, PaymentStatus

_PAYMENT_TRANSITIONS: dict[PaymentStatus, set[PaymentStatus]] = {
    PaymentStatus.AUTHORIZED: {
        PaymentStatus.PENDING_SETTLEMENT,
        PaymentStatus.PROCESSING,
        PaymentStatus.SETTLED,
        PaymentStatus.FAILED_FINAL,
        PaymentStatus.CANCELLED,
    },
    PaymentStatus.PENDING: {
        PaymentStatus.AUTHORIZED,
        PaymentStatus.PROCESSING,
        PaymentStatus.PENDING_SETTLEMENT,
        PaymentStatus.SETTLED,
        PaymentStatus.FAILED,
        PaymentStatus.FAILED_FINAL,
        PaymentStatus.CANCELLED,
        PaymentStatus.BLOCKED,
    },
    PaymentStatus.PROCESSING: {
        PaymentStatus.PENDING_SETTLEMENT,
        PaymentStatus.SETTLED,
        PaymentStatus.FAILED,
        PaymentStatus.FAILED_FINAL,
        PaymentStatus.CANCELLED,
    },
    PaymentStatus.PENDING_SETTLEMENT: {
        PaymentStatus.SETTLED,
        PaymentStatus.FAILED,
        PaymentStatus.FAILED_FINAL,
    },
    PaymentStatus.COMPLETED: set(),
    PaymentStatus.SETTLED: set(),
    PaymentStatus.FAILED: set(),
    PaymentStatus.FAILED_FINAL: set(),
    PaymentStatus.CANCELLED: set(),
    PaymentStatus.BLOCKED: set(),
}

_INTENT_TRANSITIONS: dict[PaymentIntentStatus, set[PaymentIntentStatus]] = {
    PaymentIntentStatus.REQUIRES_CONFIRMATION: {
        PaymentIntentStatus.REQUIRES_REVIEW,
        PaymentIntentStatus.PROCESSING,
        PaymentIntentStatus.CANCELED,
        PaymentIntentStatus.FAILED,
    },
    PaymentIntentStatus.REQUIRES_REVIEW: {
        PaymentIntentStatus.REQUIRES_CONFIRMATION,
        PaymentIntentStatus.PROCESSING,
        PaymentIntentStatus.CANCELED,
        PaymentIntentStatus.FAILED,
    },
    PaymentIntentStatus.PROCESSING: {
        PaymentIntentStatus.SUCCEEDED,
        PaymentIntentStatus.FAILED,
    },
    PaymentIntentStatus.SUCCEEDED: set(),
    PaymentIntentStatus.CANCELED: set(),
    PaymentIntentStatus.FAILED: set(),
}


def is_irreversible_success_status(status: PaymentStatus) -> bool:
    """Return True when payment status guarantees irreversible success."""
    return status in (PaymentStatus.SETTLED, PaymentStatus.COMPLETED)


def is_accepted_inflight_status(status: PaymentStatus) -> bool:
    """Return True when a payment is accepted but not yet irreversibly final."""
    return status in (
        PaymentStatus.AUTHORIZED,
        PaymentStatus.PENDING,
        PaymentStatus.PROCESSING,
        PaymentStatus.PENDING_SETTLEMENT,
    )


def is_effective_success_status(status: PaymentStatus) -> bool:
    """Return True for both irreversibly successful and accepted in-flight states."""
    return is_irreversible_success_status(status) or is_accepted_inflight_status(status)


def ensure_payment_transition(
    current: PaymentStatus, new: PaymentStatus, *, context: str = "payment"
) -> None:
    """Validate payment state transition and raise ValidationError if invalid."""
    if current == new:
        return
    if new in _PAYMENT_TRANSITIONS.get(current, set()):
        return
    raise ValidationError(f"Invalid {context} status transition: {current.value} -> {new.value}")


def ensure_intent_transition(
    current: PaymentIntentStatus,
    new: PaymentIntentStatus,
    *,
    context: str = "payment_intent",
) -> None:
    """Validate payment-intent state transition and raise ValidationError if invalid."""
    if current == new:
        return
    if new in _INTENT_TRANSITIONS.get(current, set()):
        return
    raise ValidationError(f"Invalid {context} status transition: {current.value} -> {new.value}")
