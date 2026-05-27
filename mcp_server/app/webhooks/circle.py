from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import settings
from omniclaw.webhooks.parser import InvalidSignatureError, WebhookParser

router = APIRouter()
logger = structlog.get_logger(__name__)


async def _fetch_circle_public_key_by_id(key_id: str) -> str | None:
    """Fetch webhook public key from Circle using X-Circle-Key-Id."""
    circle_key = settings.CIRCLE_API_KEY
    if not key_id or not circle_key:
        return None
    api_key = circle_key.get_secret_value()
    url = f"https://api.circle.com/v2/cpn/notifications/publicKey/{key_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            public_key = data.get("publicKey")
            return str(public_key) if public_key else None
    except Exception:
        return None


async def verify_circle_signature(
    request: Request,
    signature: str,
    key_id: str | None = None,
    timestamp: str | None = None,
):
    """
    Verify Circle webhook signature using OmniClaw's parser.
    """
    verification_key_secret = settings.OMNICLAW_WEBHOOK_VERIFICATION_KEY
    verification_key = (
        verification_key_secret.get_secret_value() if verification_key_secret else None
    )
    if not verification_key and key_id:
        verification_key = await _fetch_circle_public_key_by_id(key_id)
    if settings.ENVIRONMENT == "dev" and not verification_key:
        return True

    if not verification_key:
        raise HTTPException(
            status_code=500,
            detail="Webhook verification key is not configured",
        )

    body = await request.body()
    parser = WebhookParser(verification_key=verification_key)
    headers = {"x-circle-signature": signature}
    if key_id:
        headers["x-circle-key-id"] = key_id
    if timestamp:
        headers["x-circle-timestamp"] = timestamp
    try:
        parser.verify_signature(payload=body, headers=headers)
    except InvalidSignatureError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid webhook signature: {exc}") from exc
    return True


@router.post("/circle")
async def circle_webhook(
    request: Request,
    x_circle_signature: str = Header(...),
    x_circle_key_id: str | None = Header(default=None),
    x_circle_timestamp: str | None = Header(default=None),
):
    """
    Handle Circle webhooks for payment events.
    """
    await verify_circle_signature(
        request,
        x_circle_signature,
        key_id=x_circle_key_id,
        timestamp=x_circle_timestamp,
    )

    payload = await request.json()
    event_type = payload.get("type")
    logger.info("circle_webhook_received", event_type=event_type, payload=payload)

    try:
        if event_type == "payment.sent":
            await handle_payment_sent(payload)
        elif event_type == "payment.received":
            await handle_payment_received(payload)
        elif event_type == "transaction.failed":
            await handle_transaction_failed(payload)
        else:
            logger.info("unhandled_event_type", event_type=event_type)

        return {"status": "processed"}

    except Exception as e:
        logger.error("webhook_processing_failed", error=str(e), event_type=event_type)
        raise HTTPException(status_code=500, detail="Webhook processing failed") from e


async def handle_payment_sent(payload: dict[str, Any]):
    """Handle payment sent event."""
    logger.info("handling_payment_sent", data=payload)
    # implementation details...


async def handle_payment_received(payload: dict[str, Any]):
    """Handle payment received event."""
    logger.info("handling_payment_received", data=payload)
    # implementation details...


async def handle_transaction_failed(payload: dict[str, Any]):
    """Handle transaction failed event."""
    logger.info("handling_transaction_failed", data=payload)
    # implementation details...
