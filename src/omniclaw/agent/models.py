"""Pydantic models for agent server API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PayRequest(BaseModel):
    """Payment request."""

    recipient: str = Field(..., description="Payment recipient (address or URL)")
    amount: str | None = Field(None, description="Amount in USDC")
    purpose: str | None = Field(None, description="Payment purpose")
    idempotency_key: str | None = Field(None, description="Idempotency key for deduplication")
    destination_chain: str | None = Field(None, description="Target network for cross-chain")
    fee_level: str | None = Field(None, description="Gas fee level (LOW, MEDIUM, HIGH)")
    check_trust: bool = Field(False, description="Run ERC-8004 Trust Gate check")
    skip_guards: bool = Field(False, description="Skip policy guards (OWNER ONLY)")
    method: str = Field("GET", description="HTTP method for x402 URL payments")
    body: str | None = Field(None, description="Request body for x402 URL payments")
    headers: dict[str, str] | None = Field(
        None, description="Request headers for x402 URL payments"
    )
    metadata: dict[str, Any] | None = Field(None, description="Additional context")


class PayResponse(BaseModel):
    """Payment response."""

    success: bool
    transaction_id: str | None = None
    blockchain_tx: str | None = None
    amount: str
    recipient: str
    status: str
    method: str
    error: str | None = None
    requires_confirmation: bool = False
    confirmation_id: str | None = None
    response_data: Any | None = None


class BalanceResponse(BaseModel):
    """Balance response."""

    wallet_id: str
    available: str
    reserved: str | None = None
    total: str | None = None
    source: str | None = None
    note: str | None = None


class SimulateRequest(BaseModel):
    """Simulation request."""

    recipient: str
    amount: str | None = None
    check_trust: bool = False
    skip_guards: bool = False
    method: str = Field("GET", description="HTTP method for x402 URL payments")
    body: str | None = Field(None, description="Request body for x402 URL payments")
    headers: dict[str, str] | None = Field(
        None, description="Request headers for x402 URL payments"
    )


class SimulateResponse(BaseModel):
    """Simulation response."""

    would_succeed: bool
    route: str
    reason: str | None = None
    guards_that_would_pass: list[str] = Field(default_factory=list)


class TransactionInfo(BaseModel):
    """Transaction info."""

    id: str
    wallet_id: str
    recipient: str
    amount: str
    status: str
    tx_hash: str | None = None
    created_at: str | None = None


class ListTransactionsResponse(BaseModel):
    """List transactions response."""

    transactions: list[TransactionInfo]
    total: int


class CreateIntentRequest(BaseModel):
    """Create intent request."""

    recipient: str
    amount: str
    purpose: str | None = None
    expires_in: int | None = Field(None, description="Expires in seconds")
    idempotency_key: str | None = Field(None, description="Idempotency key")
    check_trust: bool = False
    metadata: dict[str, Any] | None = None


class IntentResponse(BaseModel):
    """Intent response."""

    intent_id: str
    wallet_id: str
    recipient: str
    amount: str
    status: str
    expires_at: str | None = None


class ConfirmIntentRequest(BaseModel):
    """Confirm intent request."""

    intent_id: str


class CancelIntentRequest(BaseModel):
    """Cancel intent request."""

    reason: str | None = None


class CanPayRequest(BaseModel):
    """Can pay request."""

    recipient: str


class CanPayResponse(BaseModel):
    """Can pay response."""

    can_pay: bool
    reason: str | None = None


class AddressResponse(BaseModel):
    """Wallet address response."""

    wallet_id: str
    alias: str
    address: str
    eoa_address: str | None = None
    circle_wallet_address: str | None = None


class WalletInfo(BaseModel):
    """Wallet info response."""

    alias: str
    wallet_id: str
    address: str
    fund_address: str | None = None
    policy: dict[str, Any] = Field(default_factory=dict)


class ListWalletsResponse(BaseModel):
    """List wallets response."""

    wallets: list[WalletInfo]


class ErrorResponse(BaseModel):
    """Error response."""

    error: str
    detail: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str = "1.0.0"


class X402InspectRequest(BaseModel):
    """X402 inspection request."""

    url: str = Field(..., description="x402 Service URL")
    amount: str | None = Field(None, description="Optional max payment amount in USDC")
    method: str = Field("GET", description="HTTP method")
    body: str | None = Field(None, description="Request body")
    headers: dict[str, str] | None = Field(None, description="Request headers")


class X402InspectResponse(BaseModel):
    """X402 inspection response."""

    url: str
    requires_payment: bool
    buyer_ready: bool
    reason: str | None = None
    router_detected_route: str | None = None
    selected_route: str | None = None
    payment_source: str | None = None
    buyer_address: str | None = None
    gateway_available_balance: str | None = None
    selected_scheme: str | None = None
    selected_network: str | None = None
    selected_amount_atomic: str | None = None
    selected_amount_usdc: str | None = None
    selected_pay_to: str | None = None
    seller_accepts: list[dict[str, Any]] = Field(default_factory=list)
