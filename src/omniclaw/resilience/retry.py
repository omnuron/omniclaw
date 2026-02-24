"""
Retry Strategies using Tenacity.

Standard retry policies for payment infrastructure.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

try:
    from tenacity import (
        AsyncRetrying,
        retry,
        retry_if_exception_type,
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
    retry_if_exception_type = None
    stop_after_attempt = None
    wait_exponential = None


def is_transient_error(exception: Exception) -> bool:
    """Check if exception is a transient network/infrastructure error."""
    # This is a heuristic. We'll refine it with specific SDK errors later.
    msg = str(exception).lower()
    return any(
        x in msg
        for x in [
            "timeout",
            "connection refused",
            "500",
            "502",
            "503",
            "504",
            "network error",
            "rate limit",  # Sometimes retryable with backoff
        ]
    )


# Standard Retry Policy
# Retries 5 times with exponential backoff (1s, 2s, 4s, 8s, 16s)
# Only on transient errors.
retry_policy = retry(
    retry=retry_if_exception_type(Exception) & retry_if_exception_type(is_transient_error),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    stop=stop_after_attempt(5),
    reraise=True,
    before_sleep=lambda retry_state: logging.warning(
        f"Retrying payment action... (Attempt {retry_state.attempt_number})"
    ),
)


async def execute_with_retry(
    func: Callable[..., Any],
    *args,
    **kwargs
) -> Any:
    """Execute an async function with standard retry policy."""
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type(Exception) & retry_if_exception_type(is_transient_error),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        stop=stop_after_attempt(5),
        reraise=True,
    ):
        with attempt:
            return await func(*args, **kwargs)
