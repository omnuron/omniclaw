"""
Webhook Parser Infrastructure.
"""

import base64
import json
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from omniclaw.core.events import NotificationType, WebhookEvent
from omniclaw.core.exceptions import ValidationError


class InvalidSignatureError(ValidationError):
    """Raised when webhook signature verification fails."""

    pass


class DuplicateWebhookError(ValidationError):
    """Raised when a webhook notificationId has already been processed."""

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
        # Circle production retries can span hours. Keep future skew tight, but allow older
        # signed payloads to arrive inside an operational retry window.
        self._max_replay_age_seconds = int(
            os.environ.get("OMNICLAW_WEBHOOK_MAX_REPLAY_AGE_SECONDS", "43200")
        )
        self._max_future_skew_seconds = int(
            os.environ.get("OMNICLAW_WEBHOOK_MAX_FUTURE_SKEW_SECONDS", "300")
        )
        self._dedup_db_path = os.environ.get("OMNICLAW_WEBHOOK_DEDUP_DB_PATH")
        self._dedup_enabled = (
            os.environ.get("OMNICLAW_WEBHOOK_DEDUP_ENABLED", "true").lower() == "true"
        )
        self._init_dedup_store()

    def _init_dedup_store(self) -> None:
        if not self._dedup_enabled or not self._dedup_db_path:
            return
        directory = os.path.dirname(self._dedup_db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with closing(sqlite3.connect(self._dedup_db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_webhooks (
                    notification_id TEXT PRIMARY KEY,
                    processed_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _mark_notification_processed(self, notification_id: str) -> bool:
        """
        Persist notificationId for idempotent consumption.

        Returns:
            True if notification_id was newly recorded, False if duplicate.
        """
        if not self._dedup_enabled:
            return True
        if not self._dedup_db_path:
            # No persistent store configured; treat as non-duplicate.
            return True

        now_iso = datetime.utcnow().isoformat()
        with closing(sqlite3.connect(self._dedup_db_path)) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO processed_webhooks(notification_id, processed_at)
                VALUES (?, ?)
                """,
                (notification_id, now_iso),
            )
            conn.commit()
            return cursor.rowcount == 1

    @staticmethod
    def _header_value(headers: Mapping[str, str], name: str) -> str | None:
        for key, value in headers.items():
            if key.lower() == name.lower():
                return value
        return None

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

        signature = self._header_value(headers, "x-circle-signature")
        if not signature:
            signature = self._header_value(headers, "circle-signature")
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
                    # Circle currently returns DER-encoded ECDSA public keys for CPN webhooks.
                    # Legacy paths may still use raw Ed25519 public bytes.
                    try:
                        public_key = serialization.load_der_public_key(key_bytes)
                    except Exception:
                        public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
                except Exception:
                    pass

            if not public_key:
                raise InvalidSignatureError(
                    "Could not parse verification key (expected PEM, Hex, or Base64)"
                )

            # Verify based on key type
            if isinstance(public_key, Ed25519PublicKey):
                public_key.verify(signature_bytes, payload_bytes)
            elif isinstance(public_key, ec.EllipticCurvePublicKey):
                public_key.verify(signature_bytes, payload_bytes, ec.ECDSA(hashes.SHA256()))
            else:
                raise InvalidSignatureError(
                    f"Unsupported public key type: {type(public_key).__name__}"
                )
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
            if self.verification_key:
                raise InvalidSignatureError(
                    "Raw webhook payload is required when signature verification is enabled"
                )
            data = payload

        # Calculate chronological timestamp before Event Mapping to enforce Replay Window
        # Extract Timestamp from Circle's createDate field. Missing creates validation error.
        timestamp: datetime
        timestamp_header = self._header_value(headers, "x-circle-timestamp")
        if timestamp_header:
            try:
                timestamp = datetime.utcfromtimestamp(int(timestamp_header))
            except Exception as e:
                raise ValidationError(f"Invalid x-circle-timestamp header: {e}") from e
        else:
            if "createDate" not in data:
                raise ValidationError("Missing 'createDate' in payload for replay protection")
            try:
                timestamp_raw = datetime.fromisoformat(data["createDate"].replace("Z", "+00:00"))
                timestamp = (
                    timestamp_raw.replace(tzinfo=None) if timestamp_raw.tzinfo else timestamp_raw
                )
            except Exception as e:
                raise ValidationError(f"Invalid 'createDate' format: {e}") from e

        # 2. Defend Against Replay Attacks.
        # Accept delayed deliveries within retry window, but reject far-future timestamps.
        age_seconds = (datetime.utcnow() - timestamp).total_seconds()
        if age_seconds < -self._max_future_skew_seconds:
            raise InvalidSignatureError(
                "Webhook payload timestamp is too far in the future "
                f"({-age_seconds:.1f}s > {self._max_future_skew_seconds}s)"
            )
        if age_seconds > self._max_replay_age_seconds:
            raise InvalidSignatureError(
                "Webhook payload exceeds replay age window "
                f"({age_seconds:.1f}s > {self._max_replay_age_seconds}s)"
            )

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

        notification_id = str(data.get("notificationId", "")).strip()
        if not notification_id:
            raise ValidationError("Missing 'notificationId' in payload")

        if not self._mark_notification_processed(notification_id):
            raise DuplicateWebhookError(f"Duplicate webhook notificationId: {notification_id}")

        return WebhookEvent(
            id=notification_id,
            type=event_type,
            timestamp=timestamp,
            data=data.get("notification", {}),
            raw_payload=data,
        )
