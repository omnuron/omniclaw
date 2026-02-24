"""
In-Memory Storage Backend.

Default storage backend that keeps all data in memory.
Suitable for development and testing, but not for production.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from omniclaw.storage.base import StorageBackend, register_storage_backend


class InMemoryStorage(StorageBackend):
    """
    In-memory storage backend.

    Stores all data in Python dicts. Data is lost when process ends.
    Thread-safe for basic operations.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    def _ensure_collection(self, collection: str) -> dict[str, dict[str, Any]]:
        """Ensure collection exists and return it."""
        if collection not in self._data:
            self._data[collection] = {}
        return self._data[collection]

    async def save(
        self,
        collection: str,
        key: str,
        data: dict[str, Any],
    ) -> None:
        """Save data to memory."""
        coll = self._ensure_collection(collection)
        coll[key] = deepcopy(data)

    async def get(
        self,
        collection: str,
        key: str,
    ) -> dict[str, Any] | None:
        """Get data from memory."""
        coll = self._ensure_collection(collection)
        data = coll.get(key)
        return deepcopy(data) if data else None

    async def delete(
        self,
        collection: str,
        key: str,
    ) -> bool:
        """Delete data from memory."""
        coll = self._ensure_collection(collection)
        if key in coll:
            del coll[key]
            return True
        return False

    async def query(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query data with optional filters."""
        coll = self._ensure_collection(collection)

        results = []
        for key, data in coll.items():
            # Apply filters
            if filters:
                match = True
                for filter_key, filter_value in filters.items():
                    if data.get(filter_key) != filter_value:
                        match = False
                        break
                if not match:
                    continue

            # Include key in result
            result = deepcopy(data)
            result["_key"] = key
            results.append(result)

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
        coll = self._ensure_collection(collection)
        if key not in coll:
            return False

        coll[key].update(deepcopy(data))
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

        coll = self._ensure_collection(collection)
        return len(coll)

    async def clear(self, collection: str) -> int:
        """Clear all records from a collection."""
        coll = self._ensure_collection(collection)
        count = len(coll)
        coll.clear()
        return count

    async def atomic_add(
        self,
        collection: str,
        key: str,
        amount: str,
    ) -> str:
        """Atomically add amount."""
        from decimal import Decimal

        # Ensure collection exists
        if collection not in self._data:
            self._data[collection] = {}
        coll = self._data[collection]

        # Get current value
        current_val = coll.get(key)
        
        # Parse current value
        try:
            current_dec = Decimal(str(current_val)) if current_val is not None else Decimal("0")
        except Exception:
             # If it's a dict or invalid, start from 0
            current_dec = Decimal("0")

        delta = Decimal(amount)
        new_val = current_dec + delta
        
        # Store as string to match Redis behavior
        coll[key] = str(new_val)
        return str(new_val)

    async def acquire_lock(
        self,
        key: str,
        ttl: int = 30,
    ) -> bool:
        """Acquire lock (simple in-memory implementation)."""
        import time
        
        # Use a hidden collection for locks
        if "_locks" not in self._data:
            self._data["_locks"] = {}
        locks = self._data["_locks"]
        
        now = time.time()
        
        # Check if lock exists and is valid
        if key in locks:
            expiry = locks[key]
            # If expiry is in future, it's locked
            if now < float(expiry):
                return False 
            
        # Set lock (acquire)
        locks[key] = now + ttl
        return True

    async def release_lock(
        self,
        key: str,
    ) -> bool:
        """Release lock."""
        if "_locks" not in self._data:
            return False
            
        locks = self._data["_locks"]
        if key in locks:
            del locks[key]
            return True
        return False

    async def health_check(self) -> bool:
        """Always healthy for in-memory."""
        return True

    # ... existing code ...


# Register as default backend
register_storage_backend("memory", InMemoryStorage)
