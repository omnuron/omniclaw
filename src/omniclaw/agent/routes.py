"""API routes for agent server."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from omniclaw.agent.auth import AuthenticatedAgent, TokenAuth
from omniclaw.agent.models import (
    AddressResponse,
    BalanceResponse,
    CanPayResponse,
    CreateIntentRequest,
    HealthResponse,
    IntentResponse,
    ListTransactionsResponse,
    ListWalletsResponse,
    PayRequest,
    PayResponse,
    SimulateRequest,
    SimulateResponse,
    TransactionInfo,
    WalletInfo,
    X402PayRequest,
    X402VerifyRequest,
)
from omniclaw.agent.policy import PolicyManager, WalletManager
from omniclaw.core.logging import get_logger

if TYPE_CHECKING:
    from omniclaw import OmniClaw

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agent"])


async def get_policy_manager(request: Request) -> PolicyManager:
    return request.app.state.policy_mgr


async def get_wallet_manager(request: Request) -> WalletManager:
    return request.app.state.wallet_mgr


async def get_token_auth(request: Request) -> TokenAuth:
    return request.app.state.auth


async def get_omniclaw_client(request: Request) -> OmniClaw:
    return request.app.state.client


security = HTTPBearer()


async def get_current_agent(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth: TokenAuth = Depends(get_token_auth),
) -> AuthenticatedAgent:
    return await auth.authenticate(credentials)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="healthy")


@router.get("/address", response_model=AddressResponse)
async def get_address(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
):
    address = await wallet_mgr.get_wallet_address()
    if not address:
        raise HTTPException(status_code=404, detail="Wallet not found")

    return AddressResponse(
        wallet_id=agent.wallet_id,
        alias="primary",
        address=address,
    )


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
):
    balance = await wallet_mgr.get_wallet_balance()
    if balance is None:
        raise HTTPException(status_code=404, detail="Wallet not found")

    return BalanceResponse(
        wallet_id=agent.wallet_id,
        available=str(balance),
    )


@router.post("/pay", response_model=PayResponse)
async def pay(
    request: PayRequest,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    if not policy_mgr.is_valid_recipient(request.recipient):
        raise HTTPException(status_code=400, detail="Recipient not allowed by policy")

    amount = Decimal(request.amount)
    allowed, reason = policy_mgr.check_limits(amount)
    if not allowed:
        raise HTTPException(status_code=400, detail=reason)

    requires_confirmation = policy_mgr.requires_confirmation(amount)

    try:
        result = await client.pay(
            wallet_id=agent.wallet_id,
            recipient=request.recipient,
            amount=str(amount),
            purpose=request.purpose,
            idempotency_key=request.idempotency_key,
            destination_chain=request.destination_chain,
            fee_level=request.fee_level,
            check_trust=request.check_trust,
            skip_guards=request.skip_guards,
            metadata=request.metadata,
        )

        return PayResponse(
            success=result.success,
            transaction_id=result.transaction_id,
            blockchain_tx=result.blockchain_tx,
            amount=str(result.amount),
            recipient=result.recipient,
            status=result.status.value if hasattr(result.status, "value") else str(result.status),
            method=result.method.value if hasattr(result.method, "value") else str(result.method),
            error=result.error,
            requires_confirmation=requires_confirmation,
        )
    except Exception as e:
        logger.error(f"Payment failed: {e}")
        return PayResponse(
            success=False,
            amount=request.amount,
            recipient=request.recipient,
            status="FAILED",
            method="TRANSFER",
            error=str(e),
            requires_confirmation=False,
        )


@router.post("/simulate", response_model=SimulateResponse)
async def simulate(
    request: SimulateRequest,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    if not policy_mgr.is_valid_recipient(request.recipient):
        return SimulateResponse(
            would_succeed=False, route="TRANSFER", reason="Recipient not allowed by policy"
        )

    amount = Decimal(request.amount)
    allowed, reason = policy_mgr.check_limits(amount)
    if not allowed:
        return SimulateResponse(would_succeed=False, route="TRANSFER", reason=reason)

    try:
        result = await client.simulate(
            wallet_id=agent.wallet_id,
            recipient=request.recipient,
            amount=str(amount),
            check_trust=request.check_trust,
            skip_guards=request.skip_guards,
        )

        return SimulateResponse(
            would_succeed=result.would_succeed,
            route=result.route.value if hasattr(result.route, "value") else str(result.route),
            reason=result.reason,
            guards_that_would_pass=result.guards_that_would_pass,
        )
    except Exception as e:
        return SimulateResponse(would_succeed=False, route="TRANSFER", reason=str(e))


@router.get("/transactions", response_model=ListTransactionsResponse)
async def list_transactions(
    limit: int = 20,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    try:
        transactions = await client.list_transactions(wallet_id=agent.wallet_id)
        transactions = transactions[:limit]

        return ListTransactionsResponse(
            transactions=[
                TransactionInfo(
                    id=tx.id,
                    wallet_id=tx.wallet_id,
                    recipient=tx.recipient,
                    amount=str(tx.amount),
                    status=tx.status.value if hasattr(tx.status, "value") else str(tx.status),
                    tx_hash=tx.tx_hash,
                    created_at=tx.created_at.isoformat() if tx.created_at else None,
                )
                for tx in transactions
            ],
            total=len(transactions),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/intents", response_model=IntentResponse)
async def create_intent(
    request: CreateIntentRequest,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    if not policy_mgr.is_valid_recipient(request.recipient):
        raise HTTPException(status_code=400, detail="Recipient not allowed by policy")

    amount = Decimal(request.amount)
    allowed, reason = policy_mgr.check_limits(amount)
    if not allowed:
        raise HTTPException(status_code=400, detail=reason)

    try:
        intent = await client.create_payment_intent(
            wallet_id=agent.wallet_id,
            recipient=request.recipient,
            amount=str(amount),
            purpose=request.purpose,
            expires_in=request.expires_in,
            idempotency_key=request.idempotency_key,
            check_trust=request.check_trust,
            **(request.metadata or {}),
        )

        return IntentResponse(
            intent_id=intent.id,
            wallet_id=intent.wallet_id,
            recipient=intent.recipient,
            amount=str(intent.amount),
            status=intent.status.value if hasattr(intent.status, "value") else str(intent.status),
            expires_at=intent.expires_at.isoformat() if intent.expires_at else None,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/intents/{intent_id}", response_model=IntentResponse)
async def get_intent(
    intent_id: str,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    try:
        intent = await client.get_payment_intent(intent_id)
        if not intent:
            raise HTTPException(status_code=404, detail="Intent not found")

        if intent.wallet_id != agent.wallet_id:
            raise HTTPException(status_code=403, detail="Intent belongs to different wallet")

        return IntentResponse(
            intent_id=intent.id,
            wallet_id=intent.wallet_id,
            recipient=intent.recipient,
            amount=str(intent.amount),
            status=intent.status.value if hasattr(intent.status, "value") else str(intent.status),
            expires_at=intent.expires_at.isoformat() if intent.expires_at else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/intents/{intent_id}/confirm", response_model=PayResponse)
async def confirm_intent(
    intent_id: str,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    try:
        intent = await client.get_payment_intent(intent_id)
        if not intent:
            raise HTTPException(status_code=404, detail="Intent not found")

        if intent.wallet_id != agent.wallet_id:
            raise HTTPException(status_code=403, detail="Intent belongs to different wallet")

        result = await client.confirm_payment_intent(intent_id)

        return PayResponse(
            success=result.success,
            transaction_id=result.transaction_id,
            blockchain_tx=result.blockchain_tx,
            amount=str(result.amount),
            recipient=result.recipient,
            status=result.status.value if hasattr(result.status, "value") else str(result.status),
            method=result.method.value if hasattr(result.method, "value") else str(result.method),
            error=result.error,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/intents/{intent_id}", response_model=IntentResponse)
async def cancel_intent(
    intent_id: str,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    try:
        intent = await client.get_payment_intent(intent_id)
        if not intent:
            raise HTTPException(status_code=404, detail="Intent not found")

        if intent.wallet_id != agent.wallet_id:
            raise HTTPException(status_code=403, detail="Intent belongs to different wallet")

        cancelled = await client.cancel_payment_intent(intent_id)

        return IntentResponse(
            intent_id=cancelled.id,
            wallet_id=cancelled.wallet_id,
            recipient=cancelled.recipient,
            amount=str(cancelled.amount),
            status=cancelled.status.value
            if hasattr(cancelled.status, "value")
            else str(cancelled.status),
            expires_at=cancelled.expires_at.isoformat() if cancelled.expires_at else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/can-pay", response_model=CanPayResponse)
async def can_pay(
    recipient: str,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
):
    is_valid = policy_mgr.is_valid_recipient(recipient)
    if is_valid:
        return CanPayResponse(can_pay=True)
    else:
        return CanPayResponse(can_pay=False, reason="Recipient not allowed by policy")


@router.get("/wallets", response_model=ListWalletsResponse)
async def list_wallets(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
):
    address = await wallet_mgr.get_wallet_address()
    wallet_id = policy_mgr.get_wallet_id()
    policy = policy_mgr.get_policy()

    # Send a mock policy block for the CLI display
    policy_dict = policy.to_dict()

    wallets = [
        WalletInfo(
            alias="primary",
            wallet_id=wallet_id or "",
            address=address or "",
            fund_address=address,
            policy=policy_dict,
        )
    ]

    return ListWalletsResponse(wallets=wallets)


@router.post("/x402/pay", response_model=PayResponse)
async def x402_pay(
    request: X402PayRequest,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    """Execute an automated x402 payment flow."""
    try:
        from omniclaw.protocols.x402 import X402Adapter

        adapter = X402Adapter(client.config, client.wallet_service)

        result = await adapter.execute(
            wallet_id=agent.wallet_id,
            recipient=request.url,
            amount=Decimal(request.max_amount or "10.0"),  # Default cap
            idempotency_key=request.idempotency_key,
            method=request.method,
            body=request.body,
            headers=request.headers,
        )

        return PayResponse(
            success=result.success,
            transaction_id=result.transaction_id,
            blockchain_tx=result.blockchain_tx,
            amount=str(result.amount),
            recipient=result.recipient,
            status=result.status.value if hasattr(result.status, "value") else str(result.status),
            method="X402",
            error=result.error,
        )
    except Exception as e:
        logger.error(f"x402 payment failed: {e}")
        return PayResponse(
            success=False,
            amount="0",
            recipient=request.url,
            status="FAILED",
            method="X402",
            error=str(e),
        )


@router.post("/x402/verify")
async def x402_verify(
    request: X402VerifyRequest,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    """Verify an incoming x402 payment signature (for 'omniclaw-cli serve')."""
    # This is a stub for now, in a real implementation it would verify the signature
    # against the blockchain or a local cache.
    return {"valid": True, "amount": request.amount, "sender": request.sender}
