"""
Distributed Circuit Breaker Implementation.

Uses StorageBackend (Redis) to maintain state across multiple agent instances.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import TYPE_CHECKING, Any

from omniclaw.core.logging import get_logger

if TYPE_CHECKING:
    from omniclaw.storage.base import StorageBackend


class CircuitState(str, Enum):
    """Circuit Breaker States."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, block requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitOpenError(Exception):
    """Raised when execution is attempted on an OPEN circuit."""

    def __init__(self, service: str, recovery_time: float):
        self.service = service
        self.recovery_time = recovery_time
        super().__init__(f"Circuit OPEN for {service}. Retrying after {recovery_time}")


class CircuitBreaker:
    """
    Distributed Circuit Breaker.

    Wraps critical external calls. If failures exceed threshold,
    it "trips" (OPEN) and blocks calls for `recovery_timeout` seconds.
    Then it enters HALF_OPEN to test connectivity.
    """

    def __init__(
        self,
        service_name: str,
        storage: StorageBackend,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        cleanup_window: int = 60,  # Rolling window in seconds
    ) -> None:
        """
        Initialize Circuit Breaker.

        Args:
            service_name: Unique ID for the service (e.g., "circle_api")
            storage: Storage backend (Redis required for distributed)
            failure_threshold: Number of failures before tripping
            recovery_timeout: Seconds to wait before attempting recovery
            cleanup_window: Time window for failure counting
        """
        self.service = service_name
        self._storage = storage
        self.threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.cleanup_window = cleanup_window
        self._logger = get_logger(f"circuit.{service_name}")

        # Keys
        self._key_state = f"circuit:{service_name}:state"
        self._key_failures = f"circuit:{service_name}:failures"
        self._key_recovery = f"circuit:{service_name}:recovery_ts"

    async def get_state(self) -> CircuitState:
        """Get current circuit state."""
        data = await self._storage.get("resilience", self._key_state)
        if not data:
            return CircuitState.CLOSED
        return CircuitState(data.get("state", CircuitState.CLOSED.value))

    async def _set_state(self, state: CircuitState) -> None:
        """Set circuit state."""
        await self._storage.save(
            "resilience", self._key_state, {"state": state.value}
        )
        self._logger.info(f"Circuit state changed to: {state.value}")

    async def is_available(self) -> bool:
        """Check if service is available (CLOSED or HALF_OPEN)."""
        state = await self.get_state()

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            recovery_data = await self._storage.get("resilience", self._key_recovery)
            if not recovery_data:
                # Should not happen if open, but auto-recover
                await self._set_state(CircuitState.HALF_OPEN)
                return True

            recovery_ts = float(recovery_data.get("ts", 0))
            if time.time() > recovery_ts:
                self._logger.info("Recovery timeout passed. Entering HALF_OPEN.")
                await self._set_state(CircuitState.HALF_OPEN)
                return True

            return False

        # HALF_OPEN: We allow traffic, but failure will trip immediately
        return True

    async def record_failure(self) -> None:
        """Record a failure event."""
        state = await self.get_state()

        if state == CircuitState.HALF_OPEN:
            # If we fail in HALF_OPEN, immediate trip back to OPEN
            self._logger.warning("Failure in HALF_OPEN. Tripping back to OPEN.")
            await self.trip()
            return

        # Atomic increment via storage backend
        val_str = await self._storage.atomic_add(
            "resilience", self._key_failures, "1"
        )
        current_failures = int(float(val_str))

        self._logger.warning(
            f"Failure recorded. Count: {current_failures}/{self.threshold}"
        )

        if current_failures >= self.threshold:
            await self.trip()

    async def record_success(self) -> None:
        """Record a success event."""
        state = await self.get_state()

        if state == CircuitState.HALF_OPEN:
            self._logger.info("Success in HALF_OPEN. Closing circuit.")
            await self.close()
        elif state == CircuitState.CLOSED:
            # Decrement failure count by 1 (gradual recovery rather than instant reset)
            # This prevents a single success from wiping out a burst of recent failures
            val_str = await self._storage.atomic_add(
                "resilience", self._key_failures, "-1"
            )
            current = int(float(val_str))
            if current <= 0:
                # Clean up when count reaches zero
                await self._storage.delete("resilience", self._key_failures)

    async def trip(self) -> None:
        """Trip the circuit to OPEN."""
        recovery_time = time.time() + self.recovery_timeout
        await self._set_state(CircuitState.OPEN)
        await self._storage.save(
            "resilience", self._key_recovery, {"ts": str(recovery_time)}
        )
        self._logger.critical(
            f"Circuit TRIPPED. Blocking requests for {self.recovery_timeout}s."
        )

    async def close(self) -> None:
        """Close the circuit (Recovered)."""
        await self._set_state(CircuitState.CLOSED)
        await self._storage.delete("resilience", self._key_failures)
        await self._storage.delete("resilience", self._key_recovery)
        self._logger.info("Circuit CLOSED. Service restored.")

    async def __aenter__(self):
        """Context manager entry."""
        if not await self.is_available():
            # Get recovery time for error message
            data = await self._storage.get("resilience", self._key_recovery)
            recovery_ts = float(data.get("ts", 0)) if data else 0
            raise CircuitOpenError(self.service, recovery_ts)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type is None:
            await self.record_success()
        else:
            # All exceptions within the circuit context are treated as infrastructure failures.
            # Business logic errors (e.g. validation) should be caught outside the circuit block.
            await self.record_failure()
            return False  # Propagate exception
