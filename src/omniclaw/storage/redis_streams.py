"""
Redis Streams Helpers.

Low-level XADD / XREAD / XREADGROUP / XACK wrappers for the OmniClaw event bus.
Uses the same lazy-init pattern as RedisStorage.
"""

from __future__ import annotations

import os
from typing import Any

from omniclaw.core.logging import get_logger

logger = get_logger("storage.redis_streams")


class RedisStreamClient:
    """
    Thin wrapper around redis.asyncio for Redis Streams operations.

    Provides XADD, XREAD, consumer group management, and XACK.
    Lazily connects to Redis on first use.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or os.environ.get(
            "OMNICLAW_REDIS_URL", "redis://localhost:6379/0"
        )
        self._client: Any | None = None

    async def _get_client(self) -> Any:
        """Lazy-load async Redis client."""
        if self._client is None:
            try:
                import redis.asyncio as aioredis

                self._client = aioredis.from_url(self._redis_url, decode_responses=True)
            except ImportError:
                logger.error("redis package not installed. Install with: pip install redis")
                raise
        return self._client

    async def xadd(
        self,
        stream_key: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        """
        Append an entry to a Redis Stream.

        Args:
            stream_key: Stream key name (e.g. 'omniclaw:events')
            fields: Dict of field-value pairs to store
            maxlen: Optional MAXLEN cap for the stream
            approximate: Use '~' for approximate trimming (default True, better perf)

        Returns:
            The auto-generated stream entry ID (e.g. '1677123456789-0')
        """
        client = await self._get_client()
        entry_id: str = await client.xadd(
            stream_key,
            fields,
            maxlen=maxlen,
            approximate=approximate,
        )
        return entry_id

    async def xread(
        self,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[Any]:
        """
        Read new entries from one or more streams.

        Args:
            streams: Dict of {stream_key: last_id} (use '0' for beginning, '$' for new only)
            count: Max entries to return per stream
            block: Block for N milliseconds (None = don't block)

        Returns:
            List of [stream_key, [(entry_id, fields), ...]]
        """
        client = await self._get_client()
        result = await client.xread(streams, count=count, block=block)
        return result or []

    async def create_consumer_group(
        self,
        stream_key: str,
        group_name: str,
        start_id: str = "0",
        mkstream: bool = True,
    ) -> bool:
        """
        Create a consumer group for a stream.

        Args:
            stream_key: Stream key
            group_name: Consumer group name
            start_id: ID to start reading from ('0' = beginning, '$' = new only)
            mkstream: Create the stream if it doesn't exist

        Returns:
            True if created, False if already exists
        """
        client = await self._get_client()
        try:
            await client.xgroup_create(stream_key, group_name, id=start_id, mkstream=mkstream)
            return True
        except Exception as e:
            if "BUSYGROUP" in str(e):
                # Group already exists
                return False
            raise

    async def xreadgroup(
        self,
        group_name: str,
        consumer_name: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[Any]:
        """
        Read entries from a stream as part of a consumer group.

        Args:
            group_name: Consumer group name
            consumer_name: Consumer name within the group
            streams: Dict of {stream_key: '>'} for new entries
            count: Max entries to return
            block: Block for N milliseconds

        Returns:
            List of [stream_key, [(entry_id, fields), ...]]
        """
        client = await self._get_client()
        result = await client.xreadgroup(
            group_name, consumer_name, streams, count=count, block=block
        )
        return result or []

    async def xack(
        self,
        stream_key: str,
        group_name: str,
        *entry_ids: str,
    ) -> int:
        """
        Acknowledge processed entries in a consumer group.

        Args:
            stream_key: Stream key
            group_name: Consumer group name
            entry_ids: One or more entry IDs to acknowledge

        Returns:
            Number of entries acknowledged
        """
        client = await self._get_client()
        return await client.xack(stream_key, group_name, *entry_ids)

    async def xlen(self, stream_key: str) -> int:
        """Get the number of entries in a stream."""
        client = await self._get_client()
        return await client.xlen(stream_key)

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
