"""
File-based storage backend for OmniClaw.

Stores data in JSON files in ~/.omniclaw/data/
"""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from omniclaw.storage.base import StorageBackend


class FileStorage(StorageBackend):
    """
    File-based storage using JSON files.

    Data is stored in ~/.omniclaw/data/{collection}.json
    Each collection is a separate JSON file with key-value pairs.

    Supports locks via file-based locking.
    """

    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir or (Path.home() / ".omniclaw" / "data")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._locks_dir = self._base_dir / "_locks"
        self._locks_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, collection: str) -> Path:
        safe_name = collection.replace("/", "_").replace(":", "_")
        return self._base_dir / f"{safe_name}.json"

    async def _read_collection(self, collection: str) -> dict[str, Any]:
        file_path = self._get_file_path(collection)
        if not file_path.exists():
            return {}
        try:
            return json.loads(file_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    async def _write_collection(self, collection: str, data: dict[str, Any]) -> None:
        file_path = self._get_file_path(collection)
        file_path.write_text(json.dumps(data, indent=2))

    async def save(
        self,
        collection: str,
        key: str,
        data: dict[str, Any],
    ) -> None:
        async with self._lock:
            existing = await self._read_collection(collection)
            existing[key] = data
            await self._write_collection(collection, existing)

    async def get(
        self,
        collection: str,
        key: str,
    ) -> dict[str, Any] | None:
        data = await self._read_collection(collection)
        return data.get(key)

    async def delete(
        self,
        collection: str,
        key: str,
    ) -> bool:
        async with self._lock:
            data = await self._read_collection(collection)
            if key in data:
                del data[key]
                await self._write_collection(collection, data)
                return True
            return False

    async def list_keys(
        self,
        collection: str,
    ) -> list[str]:
        data = await self._read_collection(collection)
        return list(data.keys())

    async def query(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        data = await self._read_collection(collection)

        results = []
        for key, value in data.items():
            if not isinstance(value, dict):
                value = {"value": value}

            if filters:
                match = True
                for filter_key, filter_value in filters.items():
                    if value.get(filter_key) != filter_value:
                        match = False
                        break
                if not match:
                    continue

            result = dict(value)
            result["_key"] = key
            results.append(result)

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
        async with self._lock:
            existing = await self._read_collection(collection)
            if key not in existing:
                return False
            existing[key].update(data)
            await self._write_collection(collection, existing)
            return True

    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        if filters:
            results = await self.query(collection, filters)
            return len(results)
        data = await self._read_collection(collection)
        return len(data)

    async def clear(self, collection: str) -> int:
        async with self._lock:
            data = await self._read_collection(collection)
            count = len(data)
            await self._write_collection(collection, {})
            return count

    async def atomic_add(
        self,
        collection: str,
        key: str,
        amount: str,
    ) -> str:
        async with self._lock:
            data = await self._read_collection(collection)

            current_val = data.get(key, "0")
            try:
                current = Decimal(str(current_val))
            except Exception:
                current = Decimal("0")

            added = Decimal(str(amount))
            new_val = current + added
            data[key] = str(new_val)

            await self._write_collection(collection, data)
            return str(new_val)

    async def create_budget_reservation(
        self,
        collection: str,
        reservation_key: str,
        period_limits: dict[str, str],
        amount: str,
        record: dict[str, Any],
    ) -> str:
        """Atomically create a budget reservation if every period has capacity."""
        async with self._lock:
            data = await self._read_collection(collection)
            amount_dec = Decimal(str(amount))

            for period_key, limit in period_limits.items():
                main = Decimal(str(data.get(period_key, "0")))
                reserved = Decimal(str(data.get(f"{period_key}:reserved", "0")))
                if main + reserved + amount_dec > Decimal(str(limit)):
                    return f"limit_exceeded:{period_key}"

            data[reservation_key] = record
            for period_key in period_limits:
                reserved_key = f"{period_key}:reserved"
                current = Decimal(str(data.get(reserved_key, "0")))
                data[reserved_key] = str(current + amount_dec)

            await self._write_collection(collection, data)
            return "reserved"

    async def commit_budget_reservation(
        self,
        collection: str,
        reservation_key: str,
        period_keys: list[str],
        amount: str,
        committed_at: str,
    ) -> str:
        """Atomically commit a budget reservation and mark it single-use."""
        async with self._lock:
            data = await self._read_collection(collection)
            record = data.get(reservation_key)
            if not record:
                return "missing"
            status = record.get("status")
            if status != "reserved":
                return str(status)

            amount_dec = Decimal(str(amount))
            for period_key in period_keys:
                main = Decimal(str(data.get(period_key, "0")))
                reserved_key = f"{period_key}:reserved"
                reserved = Decimal(str(data.get(reserved_key, "0")))
                data[period_key] = str(main + amount_dec)
                data[reserved_key] = str(reserved - amount_dec)

            record["status"] = "committed"
            record["committed_at"] = committed_at
            await self._write_collection(collection, data)
            return "committed"

    async def release_budget_reservation(
        self,
        collection: str,
        reservation_key: str,
        period_keys: list[str],
        amount: str,
        released_at: str,
    ) -> str:
        """Atomically release a budget reservation and mark it single-use."""
        async with self._lock:
            data = await self._read_collection(collection)
            record = data.get(reservation_key)
            if not record:
                return "missing"
            status = record.get("status")
            if status != "reserved":
                return str(status)

            amount_dec = Decimal(str(amount))
            for period_key in period_keys:
                reserved_key = f"{period_key}:reserved"
                reserved = Decimal(str(data.get(reserved_key, "0")))
                data[reserved_key] = str(reserved - amount_dec)

            record["status"] = "released"
            record["released_at"] = released_at
            await self._write_collection(collection, data)
            return "released"

    async def acquire_lock(
        self,
        key: str,
        ttl: int = 30,
    ) -> str | None:
        lock_file = self._locks_dir / f"{key}.lock"
        token = str(uuid.uuid4())

        async with self._lock:
            if lock_file.exists():
                try:
                    content = json.loads(lock_file.read_text())
                    import time

                    if content.get("expires", 0) > time.time():
                        return None
                except Exception:
                    pass

            import time

            lock_file.write_text(json.dumps({"token": token, "expires": time.time() + ttl}))
            return token

    async def release_lock(
        self,
        key: str,
        token: str | None = None,
    ) -> bool:
        lock_file = self._locks_dir / f"{key}.lock"

        async with self._lock:
            if not lock_file.exists():
                return False

            try:
                content = json.loads(lock_file.read_text())
                if token is None or content.get("token") == token:
                    lock_file.unlink()
                    return True
                return False
            except Exception:
                return False

    async def refresh_lock(
        self,
        key: str,
        token: str,
        ttl: int = 30,
    ) -> bool:
        lock_file = self._locks_dir / f"{key}.lock"

        async with self._lock:
            if not lock_file.exists():
                return False

            try:
                content = json.loads(lock_file.read_text())
                if content.get("token") == token:
                    import time

                    content["expires"] = time.time() + ttl
                    lock_file.write_text(json.dumps(content))
                    return True
                return False
            except Exception:
                return False
