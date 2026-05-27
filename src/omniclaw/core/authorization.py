"""Authorization binding helpers for payment intents."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any


def _normalize_decimal(value: Decimal | str | int | float) -> str:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    normalized = format(decimal_value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _normalize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def build_authorization_snapshot(
    *,
    wallet_id: str,
    recipient: str,
    amount: Decimal,
    currency: str,
    purpose: str | None,
    expires_at: datetime | None,
    route: str | None,
    idempotency_key: str | None,
    policy_snapshot_hash: str | None,
) -> dict[str, Any]:
    """Build the canonical buyer-side authorization snapshot for an intent."""
    return {
        "amount": _normalize_decimal(amount),
        "currency": currency,
        "expires_at": _normalize_datetime(expires_at),
        "idempotency_key": idempotency_key,
        "policy_snapshot_hash": policy_snapshot_hash,
        "purpose": purpose,
        "recipient": recipient,
        "route": route,
        "wallet_id": wallet_id,
    }


def derive_authorization_digest(snapshot: dict[str, Any]) -> str:
    """Derive a deterministic digest for an authorization snapshot."""
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bind_authorization(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return stored binding metadata for a canonical authorization snapshot."""
    return {
        "authorization_snapshot": snapshot,
        "authorization_digest": derive_authorization_digest(snapshot),
    }


def verify_authorization_binding(
    *,
    stored_snapshot: dict[str, Any] | None,
    stored_digest: str | None,
    current_snapshot: dict[str, Any],
) -> bool:
    """Return True when the current snapshot matches the stored binding."""
    if not stored_snapshot or not stored_digest:
        return False
    if stored_snapshot != current_snapshot:
        return False
    return derive_authorization_digest(current_snapshot) == stored_digest


__all__ = [
    "bind_authorization",
    "build_authorization_snapshot",
    "derive_authorization_digest",
    "verify_authorization_binding",
]
