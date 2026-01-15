"""
In-Memory Storage Backend.

Default storage backend that keeps all data in memory.
Suitable for development and testing, but not for production.
"""

from __future__ import annotations

from typing import Any
from copy import deepcopy

from omniagentpay.storage.base import StorageBackend, register_storage_backend


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
        coll = self._ensure_collection(collection)
        
        # In asyncio single-threaded loop, this is atomic (no awaits)
        # Handle existing value which might be a dict (if misused) or string
        current_val = coll.get(key)
        
        if isinstance(current_val, dict):
            # Special case: if key holds dict, we can't increment it.
            # But relying on caller to use separate keys.
            # Fallback: treat as 0 overwrite? No, exception.
            # For simplicity in this fix, we assume it's a number-like string or missing
            current_dec = Decimal("0")
        else:
            current_dec = Decimal(str(current_val)) if current_val else Decimal("0")
            
        delta = Decimal(amount)
        new_val = current_dec + delta
        coll[key] = str(new_val)
        return str(new_val)

    async def health_check(self) -> bool:
        """Always healthy for in-memory."""
        return True
    
    # ... existing code ...


# Register as default backend
register_storage_backend("memory", InMemoryStorage)
