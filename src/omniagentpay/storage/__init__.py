"""
Storage backends for OmniAgentPay.

Provides pluggable persistence for ledger, guards, and other stateful components.

Configuration via environment:
    OMNIAGENT_STORAGE_BACKEND=memory  # or 'redis'
    OMNIAGENT_REDIS_URL=redis://localhost:6379/0

Example:
    >>> from omniagentpay.storage import get_storage, InMemoryStorage, RedisStorage
    >>> 
    >>> # Get storage from environment
    >>> storage = get_storage()
    >>> 
    >>> # Or create specific backend
    >>> storage = InMemoryStorage()
    >>> storage = RedisStorage(redis_url="redis://localhost:6379")
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from omniagentpay.storage.base import (
    StorageBackend,
    get_storage_backend,
    list_storage_backends,
    register_storage_backend,
)
from omniagentpay.storage.memory import InMemoryStorage

# Import Redis storage to register it (optional dependency)
try:
    from omniagentpay.storage.redis import RedisStorage
except ImportError:
    RedisStorage = None  # type: ignore


def get_storage(backend_name: str | None = None) -> StorageBackend:
    """
    Get storage backend from environment or by name.
    
    Args:
        backend_name: Backend name, or None to read from OMNIAGENT_STORAGE_BACKEND env
        
    Returns:
        StorageBackend instance
        
    Raises:
        ValueError: If backend name is unknown
    """
    if backend_name is None:
        backend_name = os.environ.get("OMNIAGENT_STORAGE_BACKEND", "memory")
    
    backend_class = get_storage_backend(backend_name)
    
    if backend_class is None:
        available = list_storage_backends()
        raise ValueError(
            f"Unknown storage backend: '{backend_name}'. "
            f"Available: {', '.join(available)}"
        )
    
    return backend_class()


__all__ = [
    "StorageBackend",
    "InMemoryStorage",
    "RedisStorage",
    "get_storage",
    "get_storage_backend",
    "list_storage_backends",
    "register_storage_backend",
]
