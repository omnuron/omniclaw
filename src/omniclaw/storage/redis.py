"""
Redis Storage Backend.

Production-ready storage backend using Redis for persistence and caching.
Requires redis-py package.
"""

from __future__ import annotations

import json
import os
from typing import Any

from omniclaw.storage.base import StorageBackend, register_storage_backend


class RedisStorage(StorageBackend):
    """
    Redis storage backend.

    Uses Redis for persistent storage. Suitable for production.
    Requires: pip install redis
    """

    def __init__(
        self,
        redis_url: str | None = None,
        prefix: str = "omniclaw",
    ) -> None:
        """
        Initialize Redis storage.

        Args:
            redis_url: Redis connection URL (or from OMNICLAW_REDIS_URL env)
            prefix: Key prefix for all storage keys
        """
        self._redis_url = redis_url or os.environ.get(
            "OMNICLAW_REDIS_URL",
            "redis://localhost:6379/0",
        )
        self._prefix = prefix
        self._client = None

    def _get_client(self):
        """Lazy-load Redis client."""
        if self._client is None:
            try:
                import redis.asyncio as redis
            except ImportError:
                raise ImportError(
                    "redis package required for RedisStorage. Install with: pip install redis"
                ) from None
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def _make_key(self, collection: str, key: str) -> str:
        """Create Redis key from collection and key."""
        return f"{self._prefix}:{collection}:{key}"

    def _make_collection_pattern(self, collection: str) -> str:
        """Create pattern to match all keys in collection."""
        return f"{self._prefix}:{collection}:*"

    async def save(
        self,
        collection: str,
        key: str,
        data: dict[str, Any],
    ) -> None:
        """Save data to Redis."""
        client = self._get_client()
        redis_key = self._make_key(collection, key)
        await client.set(redis_key, json.dumps(data))

        # Also add to collection index
        await client.sadd(f"{self._prefix}:{collection}:_index", key)

    async def get(
        self,
        collection: str,
        key: str,
    ) -> dict[str, Any] | None:
        """Get data from Redis."""
        client = self._get_client()
        redis_key = self._make_key(collection, key)
        data = await client.get(redis_key)

        if data is None:
            return None

        try:
            return json.loads(data)
        except json.JSONDecodeError:
            # Fallback for keys created via atomic_add (raw strings)
            return {"value": data}

    async def delete(
        self,
        collection: str,
        key: str,
    ) -> bool:
        """Delete data from Redis."""
        client = self._get_client()
        redis_key = self._make_key(collection, key)
        result = await client.delete(redis_key)

        # Remove from index
        await client.srem(f"{self._prefix}:{collection}:_index", key)

        return result > 0

    async def atomic_add(
        self,
        collection: str,
        key: str,
        amount: str,
    ) -> str:
        """Atomically add amount."""
        client = self._get_client()
        redis_key = self._make_key(collection, key)

        # INCRBYFLOAT is atomic
        new_val = await client.incrbyfloat(redis_key, float(amount))

        # Add to index so it can be cleared/counted
        await client.sadd(f"{self._prefix}:{collection}:_index", key)

        return str(new_val)

    async def query(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query data with optional filters."""
        client = self._get_client()

        # Get all keys in collection from index
        index_key = f"{self._prefix}:{collection}:_index"
        keys = await client.smembers(index_key)

        results = []
        for key in keys:
            data = await self.get(collection, key)
            if data is None:
                continue

            # Apply filters
            if filters:
                match = True
                for filter_key, filter_value in filters.items():
                    if data.get(filter_key) != filter_value:
                        match = False
                        break
                if not match:
                    continue

            data["_key"] = key
            results.append(data)

        # Apply offset and limit
        results = results[offset:]
        if limit is not None:
            results = results[:limit]

        return results

    async def update(
        self,
        collection: str,
        key: str,
        data: dict[str, Any],
    ) -> bool:
        """Update existing data."""
        existing = await self.get(collection, key)
        if existing is None:
            return False

        existing.update(data)
        await self.save(collection, key, existing)
        return True

    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Count records in collection."""
        if filters:
            results = await self.query(collection, filters)
            return len(results)

        client = self._get_client()
        index_key = f"{self._prefix}:{collection}:_index"
        return await client.scard(index_key)

    async def clear(self, collection: str) -> int:
        """Clear all records from a collection."""
        client = self._get_client()

        # Get all keys
        index_key = f"{self._prefix}:{collection}:_index"
        keys = await client.smembers(index_key)

        count = len(keys)

        # Delete all keys
        for key in keys:
            await self.delete(collection, key)

        return count

    async def health_check(self) -> bool:
        """Check Redis connection."""
        try:
            client = self._get_client()
            await client.ping()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None


# Register backend
register_storage_backend("redis", RedisStorage)
