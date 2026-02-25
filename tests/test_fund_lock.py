"""Tests for FundLockService."""

import asyncio
from decimal import Decimal

import pytest

from omniclaw.ledger.lock import FundLockService
from omniclaw.storage.memory import InMemoryStorage
from omniclaw.storage.redis import RedisStorage

# Since Redis requires a running instance, we'll primarily test
# the logic with InMemoryStorage and mock/skip Redis if not available.


@pytest.fixture
def memory_storage():
    """Provides memory storage."""
    return InMemoryStorage()


@pytest.fixture
def lock_service(memory_storage):
    """Provides lock service."""
    return FundLockService(memory_storage)


@pytest.mark.asyncio
async def test_acquire_and_release_lock(lock_service):
    """Test basic lock acquire and release."""
    wallet_id = "test-wallet-1"
    amount = Decimal("10.0")

    lock_token = await lock_service.acquire(wallet_id, amount)
    assert lock_token is not None
    assert isinstance(lock_token, str)

    # Try to acquire again, should fail/retry and return None eventually
    lock_token_2 = await lock_service.acquire(wallet_id, amount, retry_count=1, retry_delay=0.1)
    assert lock_token_2 is None

    # Release first lock using wallet_id + token
    released = await lock_service.release_with_key(wallet_id, lock_token)
    assert released is True

    # Now we should be able to acquire again
    lock_token_3 = await lock_service.acquire(wallet_id, amount)
    assert lock_token_3 is not None
    await lock_service.release_with_key(wallet_id, lock_token_3)


@pytest.mark.asyncio
async def test_lock_ttl(memory_storage):
    """Test that locks expire after TTL."""
    service = FundLockService(memory_storage)
    wallet_id = "test-wallet-2"
    amount = Decimal("5.0")

    # Acquire lock with very short TTL
    lock_token = await service.acquire(wallet_id, amount, ttl=1)
    assert lock_token is not None

    # Second acquire should fail immediately
    lock_token_2 = await service.acquire(wallet_id, amount, retry_count=0)
    assert lock_token_2 is None

    # Wait for TTL to expire
    await asyncio.sleep(1.1)

    # Now should be able to acquire
    lock_token_3 = await service.acquire(wallet_id, amount, retry_count=0)
    assert lock_token_3 is not None
    await service.release_with_key(wallet_id, lock_token_3)


@pytest.mark.asyncio
async def test_retry_mechanism(lock_service):
    """Test that retry mechanism waits and acquires if lock is freed."""
    wallet_id = "test-wallet-3"
    amount = Decimal("1.0")

    # Acquire lock
    lock_token = await lock_service.acquire(wallet_id, amount)
    
    # Run a background task to release it after 0.2s
    async def delayed_release():
        await asyncio.sleep(0.2)
        await lock_service.release_with_key(wallet_id, lock_token)

    asyncio.create_task(delayed_release())

    # This should block, then succeed when background task releases it
    lock_token_2 = await lock_service.acquire(wallet_id, amount, retry_count=5, retry_delay=0.1)
    assert lock_token_2 is not None
    
    await lock_service.release_with_key(wallet_id, lock_token_2)


@pytest.mark.asyncio
async def test_token_ownership(lock_service):
    """Test that a lock cannot be released with a wrong token."""
    wallet_id = "test-wallet-4"
    amount = Decimal("1.0")

    lock_token = await lock_service.acquire(wallet_id, amount)
    assert lock_token is not None

    # Try to release with a wrong token
    wrong_release = await lock_service.release_with_key(wallet_id, "wrong-token")
    assert wrong_release is False

    # Lock is still held, so another acquire should fail
    lock_token_2 = await lock_service.acquire(wallet_id, amount, retry_count=0)
    assert lock_token_2 is None

    # Release with correct token
    correct_release = await lock_service.release_with_key(wallet_id, lock_token)
    assert correct_release is True
