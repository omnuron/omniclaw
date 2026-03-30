"""Pydantic models for agent server API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PayRequest(BaseModel):
    """Payment request."""

    recipient: str = Field(..., description="Payment recipient (address or URL)")
    amount: str = Field(..., description="Amount in USDC")
    purpose: str | None = Field(None, description="Payment purpose")
    idempotency_key: str | None = Field(None, description="Idempotency key for deduplication")
    destination_chain: str | None = Field(None, description="Target network for cross-chain")
    fee_level: str | None = Field(None, description="Gas fee level (LOW, MEDIUM, HIGH)")
    check_trust: bool = Field(False, description="Run ERC-8004 Trust Gate check")
    skip_guards: bool = Field(False, description="Skip policy guards (OWNER ONLY)")
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


class BalanceResponse(BaseModel):
    """Balance response."""

    wallet_id: str
    available: str
    reserved: str | None = None
    total: str | None = None


class SimulateRequest(BaseModel):
    """Simulation request."""

    recipient: str
    amount: str
    check_trust: bool = False
    skip_guards: bool = False


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
