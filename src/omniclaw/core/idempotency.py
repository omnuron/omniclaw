"""
Idempotency key helpers for payment flows.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any


def _normalize_part(value: Any) -> str:
    """Normalize a value into a deterministic string for hashing."""
    if value is None:
        return ""
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if isinstance(value, Decimal):
        return _normalize_decimal(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _normalize_decimal(Decimal(str(value)))
    if isinstance(value, str):
        stripped = value.strip()
        maybe_decimal = _try_parse_decimal(stripped)
        if maybe_decimal is not None:
            return _normalize_decimal(maybe_decimal)
        return stripped
    return str(value).strip()


def _try_parse_decimal(raw: str) -> Decimal | None:
    """Parse decimal-looking strings; leave non-numeric strings untouched."""
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _normalize_decimal(value: Decimal) -> str:
    """Canonical decimal string without scientific notation/trailing zeros."""
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized in {"", "-0"}:
        return "0"
    return normalized


def derive_idempotency_key(namespace: str, *parts: Any, prefix: str = "omniclaw") -> str:
    """
    Build a deterministic idempotency key.

    The returned key is stable for equivalent semantic inputs and safe to pass
    to upstream providers that enforce idempotency.
    """
    normalized_parts = [_normalize_part(part) for part in parts]
    raw = "|".join([prefix, namespace, *normalized_parts])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}:{namespace}:{digest}"


__all__ = ["derive_idempotency_key"]
