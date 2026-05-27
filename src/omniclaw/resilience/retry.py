"""
Retry Strategies using Tenacity.

Standard retry policies for payment infrastructure.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from omniclaw.core.exceptions import (
    PaymentError,
    PaymentOutcomeUnknownError,
    TransactionTimeoutError,
)

try:
    from tenacity import (
        AsyncRetrying,
        retry,
        retry_if_exception,
        stop_after_attempt,
        wait_exponential,
    )
except ImportError:
    # Fallback/Mock if tenacity missing (though we added it)
    def retry(*args, **kwargs):
        def decorator(f):
            return f

        return decorator

    AsyncRetrying = None
    retry_if_exception = None
    stop_after_attempt = None
    wait_exponential = None


def is_transient_error(exception: Exception) -> bool:
    """Check whether an exception is explicitly safe to retry.

    Payment execution retries must not infer safety from generic timeout strings. Callers
    can mark pre-submission operations with ``retry_safe=True`` when a repeated attempt
    cannot create another economic action.
    """
    if isinstance(exception, PaymentOutcomeUnknownError | TransactionTimeoutError | PaymentError):
        return False
    return bool(getattr(exception, "retry_safe", False))


# Standard Retry Policy
# Retries 5 times with exponential backoff (1s, 2s, 4s, 8s, 16s)
# Only on transient errors.
retry_policy = retry(
    retry=retry_if_exception(is_transient_error),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    stop=stop_after_attempt(5),
    reraise=True,
    before_sleep=lambda retry_state: logging.warning(
        f"Retrying payment action... (Attempt {retry_state.attempt_number})"
    ),
)


async def execute_with_retry(func: Callable[..., Any], *args, **kwargs) -> Any:
    """Execute an async function with standard retry policy."""
    async for attempt in AsyncRetrying(
        retry=retry_if_exception(is_transient_error),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        stop=stop_after_attempt(5),
        reraise=True,
    ):
        with attempt:
            return await func(*args, **kwargs)
