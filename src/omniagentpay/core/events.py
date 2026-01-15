"""
Core Event Types for OmniAgentPay.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class NotificationType(str, Enum):
    """Types of webhook notifications."""
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_CANCELED = "payment.canceled"
    UNKNOWN = "unknown"

@dataclass
class WebhookEvent:
    """
    Parsed webhook event.
    
    Provides type-safe access to common fields while preserving raw data.
    """
    id: str
    type: NotificationType
    timestamp: datetime
    data: dict[str, Any]
    raw_payload: dict[str, Any]
