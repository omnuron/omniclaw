"""
Fund Lock Service (2-Phase Commit).

Provides a locking mechanism to prevent race conditions during payment execution.
Ensures that multiple agents sharing the same wallet do not double-spend funds.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniclaw.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class FundLockService:
    """
    Service for managing fund locks (mutexes).

    Implements a distributed lock pattern using the storage backend.
    """

    def __init__(self, storage: StorageBackend) -> None:
        """
        Initialize lock service.

        Args:
            storage: Storage backend (Redis/Memory)
        """
        self._storage = storage

    async def acquire(
        self,
        wallet_id: str,
        amount: Decimal,
        ttl: int = 30,
        retry_count: int = 3,
        retry_delay: float = 0.5,
    ) -> str | None:
        """
        Acquire a lock for a wallet.

        This is a coarse-grained lock that serializes access to the wallet
        for the duration of the transaction setup (Phase 1).

        Args:
            wallet_id: Wallet ID to lock
            amount: Amount being spent (for logging/future optimization)
            ttl: Lock time-to-live in seconds
            retry_count: Number of retries if lock is held
            retry_delay: Delay between retries

        Returns:
            lock_token (str) if successful, None if failed
        """
        lock_key = f"lock:wallet:{wallet_id}"
        
        for i in range(retry_count + 1):
            token = await self._storage.acquire_lock(lock_key, ttl)
            if token:
                logger.debug(f"Acquired lock for wallet {wallet_id} (token: {token[:8]}...)")
                return token
            
            if i < retry_count:
                logger.debug(f"Wallet {wallet_id} locked, retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
        
        logger.warning(f"Failed to acquire lock for wallet {wallet_id} after {retry_count} retries")
        return None

    async def release_with_key(self, wallet_id: str, lock_token: str) -> bool:
        """
        Release a previously acquired lock using wallet_id and token.

        Args:
            wallet_id: The wallet ID the lock was acquired for
            lock_token: The ownership token returned by acquire()

        Returns:
            True if released, False if not found or token mismatch
        """
        lock_key = f"lock:wallet:{wallet_id}"
        result = await self._storage.release_lock(lock_key, lock_token)
        if result:
            logger.debug(f"Released lock for wallet {wallet_id}")
        return result
