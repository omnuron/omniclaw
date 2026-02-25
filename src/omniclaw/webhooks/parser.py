"""
Webhook Parser Infrastructure.
"""

import base64
import contextlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from omniclaw.core.events import NotificationType, WebhookEvent
from omniclaw.core.exceptions import ValidationError


class InvalidSignatureError(ValidationError):
    """Raised when webhook signature verification fails."""

    pass


class WebhookParser:
    """
    Framework-agnostic webhook parser.

    Validates signatures and converts raw payloads into strictly typed Events.
    Does NOT handle HTTP transport - that is the application's responsibility.
    """

    def __init__(self, verification_key: str | None = None) -> None:
        """
        Initialize parser.

        Args:
            verification_key: Optional public key for signature verification.
        """
        self.verification_key = verification_key

    def verify_signature(self, payload: str | bytes, headers: Mapping[str, str]) -> bool:
        """
        Verify the webhook signature.

        Args:
            payload: Raw request body
            headers: Request headers

        Returns:
            True if valid
        """
        if not self.verification_key:
            return True

        signature = headers.get("x-circle-signature")
        if not signature:
            raise InvalidSignatureError("Missing x-circle-signature header")

        try:
            # Prepare payload bytes
            payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload

            # Decode signature
            try:
                signature_bytes = base64.b64decode(signature)
            except Exception:
                raise InvalidSignatureError("Invalid base64 signature") from None

            # Load Public Key
            public_key = None

            # 1. Try PEM
            if "-----BEGIN PUBLIC KEY-----" in self.verification_key:
                try:
                    public_key = serialization.load_pem_public_key(
                        self.verification_key.encode("utf-8")
                    )
                except Exception as e:
                    raise InvalidSignatureError(f"Invalid PEM key: {e}") from e

            # 2. Try Hex
            if not public_key:
                try:
                    key_bytes = bytes.fromhex(self.verification_key)
                    public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
                except ValueError:
                    pass

            # 3. Try Base64
            if not public_key:
                try:
                    key_bytes = base64.b64decode(self.verification_key)
                    public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
                except Exception:
                    pass

            if not public_key:
                raise InvalidSignatureError(
                    "Could not parse verification key (expected PEM, Hex, or Base64)"
                )

            # Verify
            if not isinstance(public_key, Ed25519PublicKey):
                # Circle uses Ed25519, ensures we loaded the right type if PEM had something else
                raise InvalidSignatureError("Key is not an Ed25519PublicKey")

            public_key.verify(signature_bytes, payload_bytes)
            return True

        except InvalidSignature:
            raise InvalidSignatureError("Signature mismatch") from None
        except InvalidSignatureError:
            raise
        except Exception as e:
            raise InvalidSignatureError(f"Verification failed: {e}") from e

    def handle(
        self, payload: str | bytes | dict[str, Any], headers: Mapping[str, str]
    ) -> WebhookEvent:
        """
        Parse and validate a webhook request.

        Args:
            payload: Raw body (bytes/str) or parsed dict
            headers: Request headers

        Returns:
            WebhookEvent

        Raises:
            InvalidSignatureError: If signature invalid
            ValidationError: If payload malformed
        """
        # 1. Verify Signature (if raw payload provided)
        if isinstance(payload, (str, bytes)):
            if not self.verify_signature(payload, headers):
                raise InvalidSignatureError("Invalid webhook signature")

            # Parse JSON
            try:
                if isinstance(payload, bytes):
                    data = json.loads(payload.decode("utf-8"))
                else:
                    data = json.loads(payload)
            except json.JSONDecodeError as e:
                raise ValidationError(f"Invalid JSON payload: {e}") from e
        else:
            data = payload

        # 2. Map Event
        if "notificationType" not in data:
            # Try loose check if it's just the notification object?
            # Circle usually wraps in {notificationType: ..., notification: ...}
            raise ValidationError("Missing 'notificationType' in payload")

        event_type_str = data["notificationType"]

        # Map string to Enum
        try:
            # Example mapping for Circle V2 events
            if "payment_completed" in event_type_str:
                event_type = NotificationType.PAYMENT_COMPLETED
            elif "payment_failed" in event_type_str:
                event_type = NotificationType.PAYMENT_FAILED
            elif "payment_canceled" in event_type_str:
                event_type = NotificationType.PAYMENT_CANCELED
            else:
                event_type = NotificationType.UNKNOWN
        except ValueError:
            event_type = NotificationType.UNKNOWN

        # Extract Timestamp from Circle's customDate field, falling back to current time
        timestamp = datetime.utcnow()
        if "customDate" in data:
            with contextlib.suppress(Exception):
                timestamp = datetime.fromisoformat(data["customDate"])

        return WebhookEvent(
            id=data.get("notificationId", "unknown"),
            type=event_type,
            timestamp=timestamp,
            data=data.get("notification", {}),
            raw_payload=data,
        )
