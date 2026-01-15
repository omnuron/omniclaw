"""
Abstract Storage Backend for OmniAgentPay.

Provides pluggable persistence layer for ledger, guards, and other stateful components.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """
    Abstract base class for storage backends.
    
    Provides simple CRUD operations for storing/retrieving data.
    Implementations can use any persistence layer (memory, Redis, SQLite, etc.)
    """
    
    @abstractmethod
    async def save(
        self,
        collection: str,
        key: str,
        data: dict[str, Any],
    ) -> None:
        """
        Save data to storage.
        
        Args:
            collection: Collection/table name
            key: Unique key for the record
            data: Data to store (must be JSON-serializable)
        """
        ...
    
    @abstractmethod
    async def get(
        self,
        collection: str,
        key: str,
    ) -> dict[str, Any] | None:
        """
        Get data from storage.
        
        Args:
            collection: Collection/table name
            key: Record key
            
        Returns:
            Data dict or None if not found
        """
        ...
    
    @abstractmethod
    async def delete(
        self,
        collection: str,
        key: str,
    ) -> bool:
        """
        Delete data from storage.
        
        Args:
            collection: Collection/table name
            key: Record key
            
        Returns:
            True if deleted, False if not found
        """
        ...
    
    @abstractmethod
    async def query(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Query data with optional filters.
        
        Args:
            collection: Collection/table name
            filters: Key-value pairs to filter by (exact match)
            limit: Maximum records to return
            offset: Number of records to skip
            
        Returns:
            List of matching records
        """
        ...
    
    @abstractmethod
    async def update(
        self,
        collection: str,
        key: str,
        data: dict[str, Any],
    ) -> bool:
        """
        Update existing data.
        
        Args:
            collection: Collection/table name
            key: Record key
            data: Fields to update (merged with existing)
            
        Returns:
            True if updated, False if not found
        """
        ...
    
    @abstractmethod
    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """
        Count records in collection.
        
        Args:
            collection: Collection/table name
            filters: Optional filters
            
        Returns:
            Count of matching records
        """
        ...
    
    @abstractmethod
    async def clear(self, collection: str) -> int:
        """
        Clear all records from a collection.
        
        Args:
            collection: Collection/table name
            
        Returns:
            Number of records deleted
        """
        ...
    
    @abstractmethod
    async def atomic_add(
        self,
        collection: str,
        key: str,
        amount: str,
    ) -> str:
        """
        Atomically add amount to a numeric value stored at key.
        
        Args:
            collection: Collection/table name
            key: Record key
            amount: Amount to add (as decimal string)
            
        Returns:
            New total value as string
        """
        ...

    async def health_check(self) -> bool:
        """
        Check if storage is healthy and connected.
        
        Returns:
            True if healthy
        """
        return True


# Storage backend registry for dependency injection
_STORAGE_BACKENDS: dict[str, type[StorageBackend]] = {}


def register_storage_backend(name: str, backend_class: type[StorageBackend]) -> None:
    """Register a storage backend by name."""
    _STORAGE_BACKENDS[name] = backend_class


def get_storage_backend(name: str) -> type[StorageBackend] | None:
    """Get a registered storage backend by name."""
    return _STORAGE_BACKENDS.get(name)


def list_storage_backends() -> list[str]:
    """List all registered storage backend names."""
    return list(_STORAGE_BACKENDS.keys())
