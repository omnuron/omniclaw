from __future__ import annotations

import pytest

from omniclaw.storage.file import FileStorage
from omniclaw.storage.memory import InMemoryStorage


@pytest.mark.asyncio
async def test_memory_query_handles_scalar_atomic_counters():
    storage = InMemoryStorage()
    await storage.atomic_add("guard_state", "counter", "10")

    rows = await storage.query("guard_state")

    assert rows == [{"value": "10", "_key": "counter"}]


@pytest.mark.asyncio
async def test_file_query_handles_scalar_atomic_counters(tmp_path):
    storage = FileStorage(base_dir=tmp_path)
    await storage.atomic_add("guard_state", "counter", "10")

    rows = await storage.query("guard_state")

    assert rows == [{"value": "10", "_key": "counter"}]
