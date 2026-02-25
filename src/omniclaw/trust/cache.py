"""
Trust Cache — TTL-based caching for ERC-8004 lookups.

Uses StorageBackend (Redis or InMemory) with key patterns and TTLs
matching §7.1 of the system design spec:
- Identity: 5 min TTL
- Reputation: 2 min TTL
- Metadata: 10 min TTL
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Awaitable

from omniclaw.core.logging import get_logger
from omniclaw.storage.base import StorageBackend

logger = get_logger("trust.cache")

# TTLs in seconds (from spec §7.1)
IDENTITY_TTL = 300    # 5 minutes
REPUTATION_TTL = 120  # 2 minutes
METADATA_TTL = 600    # 10 minutes
POLICY_TTL = 3600     # 60 minutes

COLLECTION = "trust_cache"


class TrustCache:
    """
    TTL-based cache backed by StorageBackend.

    Key pattern: trust:{chain_id}:{address}:{data_type}
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    @staticmethod
    def _key(chain_id: str, address: str, data_type: str) -> str:
        """Build cache key."""
        return f"trust:{chain_id}:{address.lower()}:{data_type}"

    async def get(
        self,
        chain_id: str,
        address: str,
        data_type: str,
    ) -> dict[str, Any] | None:
        """
        Get cached value if not expired.

        Returns None on miss or expiry.
        """
        key = self._key(chain_id, address, data_type)
        entry = await self._storage.get(COLLECTION, key)

        if entry is None:
            return None

        # Check TTL
        expires_at = entry.get("_expires_at", 0)
        if time.time() > expires_at:
            # Expired — remove and return miss
            await self._storage.delete(COLLECTION, key)
            return None

        return entry.get("data")

    async def set(
        self,
        chain_id: str,
        address: str,
        data_type: str,
        data: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """
        Store value with TTL.

        Args:
            chain_id: Chain identifier
            address: Wallet address
            data_type: "identity", "reputation", or "metadata"
            data: Value to cache
            ttl: TTL in seconds (uses default for data_type if None)
        """
        if ttl is None:
            ttl = self._default_ttl(data_type)

        key = self._key(chain_id, address, data_type)
        await self._storage.save(COLLECTION, key, {
            "data": data,
            "_expires_at": time.time() + ttl,
            "_data_type": data_type,
        })

    async def invalidate(
        self,
        chain_id: str,
        address: str,
        data_type: str | None = None,
    ) -> None:
        """Invalidate cache for an address (all types or specific type)."""
        if data_type:
            key = self._key(chain_id, address, data_type)
            await self._storage.delete(COLLECTION, key)
        else:
            for dt in ("identity", "reputation", "metadata"):
                key = self._key(chain_id, address, dt)
                await self._storage.delete(COLLECTION, key)

    async def get_or_fetch(
        self,
        chain_id: str,
        address: str,
        data_type: str,
        fetch_fn: Callable[[], Awaitable[dict[str, Any] | None]],
        ttl: int | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """
        Get from cache or fetch and store.

        Returns:
            Tuple of (data, cache_hit)
        """
        cached = await self.get(chain_id, address, data_type)
        if cached is not None:
            return cached, True

        # Cache miss — fetch
        data = await fetch_fn()
        if data is not None:
            await self.set(chain_id, address, data_type, data, ttl)

        return data, False

    @staticmethod
    def _default_ttl(data_type: str) -> int:
        """Get default TTL for a data type."""
        ttls = {
            "identity": IDENTITY_TTL,
            "reputation": REPUTATION_TTL,
            "metadata": METADATA_TTL,
            "policy": POLICY_TTL,
        }
        return ttls.get(data_type, IDENTITY_TTL)


__all__ = ["TrustCache"]
