"""
Tests for the Circuit Breaker resilience module.

Verifies the full lifecycle: CLOSED → OPEN → HALF_OPEN → CLOSED,
failure counting, recovery timeout, and context manager behavior.
"""

import asyncio
import time

import pytest

from omniclaw.resilience.circuit import CircuitBreaker, CircuitOpenError, CircuitState
from omniclaw.storage.memory import InMemoryStorage


@pytest.fixture
def storage():
    return InMemoryStorage()


@pytest.fixture
def circuit(storage):
    return CircuitBreaker(
        "test_service",
        storage,
        failure_threshold=3,
        recovery_timeout=1,  # Short for testing
    )


@pytest.mark.asyncio
async def test_starts_closed(circuit):
    """Circuit starts in CLOSED state."""
    state = await circuit.get_state()
    assert state == CircuitState.CLOSED
    assert await circuit.is_available() is True


@pytest.mark.asyncio
async def test_trips_after_threshold(circuit):
    """Circuit trips to OPEN after failure_threshold failures."""
    # Record 2 failures — should stay CLOSED
    await circuit.record_failure()
    await circuit.record_failure()
    assert await circuit.get_state() == CircuitState.CLOSED

    # Third failure trips it
    await circuit.record_failure()
    assert await circuit.get_state() == CircuitState.OPEN
    assert await circuit.is_available() is False


@pytest.mark.asyncio
async def test_recovery_timeout(circuit):
    """Circuit transitions to HALF_OPEN after recovery_timeout."""
    # Trip the circuit
    await circuit.record_failure()
    await circuit.record_failure()
    await circuit.record_failure()
    assert await circuit.get_state() == CircuitState.OPEN

    # Wait for recovery timeout (1s)
    await asyncio.sleep(1.1)

    # Should transition to HALF_OPEN
    assert await circuit.is_available() is True
    assert await circuit.get_state() == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_half_open_success_closes(circuit):
    """Success in HALF_OPEN transitions back to CLOSED."""
    # Trip and wait for recovery
    await circuit.record_failure()
    await circuit.record_failure()
    await circuit.record_failure()
    await asyncio.sleep(1.1)

    # Transition to HALF_OPEN via is_available check
    assert await circuit.is_available() is True

    # Record success in HALF_OPEN
    await circuit.record_success()
    assert await circuit.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_failure_reopens(circuit):
    """Failure in HALF_OPEN immediately reopens the circuit."""
    # Trip and wait for recovery
    await circuit.record_failure()
    await circuit.record_failure()
    await circuit.record_failure()
    await asyncio.sleep(1.1)

    # Enter HALF_OPEN
    assert await circuit.is_available() is True

    # Fail again — should trip immediately back to OPEN
    await circuit.record_failure()
    assert await circuit.get_state() == CircuitState.OPEN


@pytest.mark.asyncio
async def test_success_decrements_failures(circuit):
    """In CLOSED state, success decrements failure count by 1."""
    # Record 2 failures
    await circuit.record_failure()
    await circuit.record_failure()

    # Record 1 success — should decrement to 1
    await circuit.record_success()

    # 1 more failure should NOT trip (we're at 2, threshold is 3)
    await circuit.record_failure()
    assert await circuit.get_state() == CircuitState.CLOSED

    # But another failure SHOULD trip (now at 3)
    await circuit.record_failure()
    assert await circuit.get_state() == CircuitState.OPEN


@pytest.mark.asyncio
async def test_context_manager_success(circuit):
    """Context manager records success on clean exit."""
    async with circuit:
        pass  # No exception = success

    # Circuit should still be closed
    assert await circuit.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_context_manager_failure(circuit):
    """Context manager records failure on exception."""
    with pytest.raises(ValueError):
        async with circuit:
            raise ValueError("simulated failure")

    # Should have 1 failure recorded
    assert await circuit.get_state() == CircuitState.CLOSED  # Still under threshold


@pytest.mark.asyncio
async def test_context_manager_open_raises(circuit):
    """Context manager raises CircuitOpenError when circuit is OPEN."""
    # Trip the circuit
    await circuit.trip()

    with pytest.raises(CircuitOpenError) as exc_info:
        async with circuit:
            pass  # Should never reach here

    assert exc_info.value.service == "test_service"


@pytest.mark.asyncio
async def test_manual_close(circuit):
    """Manually closing resets all state."""
    await circuit.trip()
    assert await circuit.get_state() == CircuitState.OPEN

    await circuit.close()
    assert await circuit.get_state() == CircuitState.CLOSED
    assert await circuit.is_available() is True
