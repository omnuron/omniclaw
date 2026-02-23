import json
import os
import sys
from unittest.mock import MagicMock

# Setup Mocks
sys.modules["circle"] = MagicMock()
sys.modules["circle.web3"] = MagicMock()
os.environ["CIRCLE_API_KEY"] = "mock_key"
os.environ["ENTITY_SECRET"] = "mock_secret"

from omniclaw import Network, OmniClaw  # noqa: E402
from omniclaw.core.events import NotificationType  # noqa: E402


def test_webhooks():
    print("=== Testing Webhook Parser (Parser-Only Architecture) ===")

    client = OmniClaw(network=Network.ARC_TESTNET)

    # Mock Payload (Circle Style)
    payload = {
        "notificationType": "payments.payment_completed",
        "notificationId": "notif-uuid-123",
        "customDate": "2023-01-01T00:00:00Z",
        "notification": {
            "id": "tx-uuid-456",
            "amount": "10.00",
            "currency": "USD",
            "status": "complete",
        },
    }

    headers = {"x-circle-signature": "mock-signature", "x-circle-key-id": "mock-key-id"}

    # 1. Parse JSON Dict
    print("\n1. Parsing Dict Payload...")
    event = client.webhooks.handle(payload, headers)
    print(f"   Event Type: {event.type}")
    print(f"   Event ID: {event.id}")

    assert event.type == NotificationType.PAYMENT_COMPLETED
    assert event.id == "notif-uuid-123"
    print("   ✅ Parsed successfully")

    # 2. Parse Raw Bytes
    print("\n2. Parsing Raw Bytes...")
    raw_body = json.dumps(payload).encode("utf-8")
    event2 = client.webhooks.handle(raw_body, headers)

    assert event2.data["id"] == "tx-uuid-456"
    print("   ✅ Parsed raw bytes successfully")

    print("\n✅ Webhook Tests Passed!")


if __name__ == "__main__":
    test_webhooks()
