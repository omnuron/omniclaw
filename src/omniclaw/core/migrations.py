"""Utilities for one-off/backfill migrations of payment status data."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_PAYMENT_STATUS_NORMALIZATION = {
    "completed": "settled",
    "processing": "pending_settlement",
}


def normalize_payment_status_value(raw_status: str | None) -> str | None:
    """Normalize legacy payment status values to strict-settlement equivalents."""
    if raw_status is None:
        return None
    return _PAYMENT_STATUS_NORMALIZATION.get(raw_status, raw_status)


def normalize_ledger_entry(entry: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """
    Normalize a ledger entry for strict settlement metadata.

    - Leaves ledger `status` value unchanged for backward compatibility.
    - Backfills `metadata.settlement_final` based on known terminal states.
    """
    normalized = deepcopy(entry)
    metadata = dict(normalized.get("metadata") or {})
    status = str(normalized.get("status") or "").lower()
    changed = False

    if status == "completed":
        if metadata.get("settlement_final") is not True:
            metadata["settlement_final"] = True
            changed = True
    elif status == "pending":
        if metadata.get("transaction_id") and "settlement_final" not in metadata:
            metadata["settlement_final"] = False
            changed = True
    elif status in ("failed", "cancelled") and "settlement_final" not in metadata:
        metadata["settlement_final"] = False
        changed = True

    if metadata != normalized.get("metadata"):
        normalized["metadata"] = metadata
        changed = True

    return normalized, changed


def backfill_ledger_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Apply normalize_ledger_entry over a batch and return change count."""
    normalized_entries: list[dict[str, Any]] = []
    changed_count = 0
    for entry in entries:
        normalized, changed = normalize_ledger_entry(entry)
        normalized_entries.append(normalized)
        if changed:
            changed_count += 1
    return normalized_entries, changed_count
