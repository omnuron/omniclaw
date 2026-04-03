"""
Agent-facing MCP server for the OmniClaw SDK.

Exposes ONLY agent-safe tools. Guard management, trust policy management,
user wallets, webhook processing, and other admin/infrastructure tools
have been removed — agents must not modify their own guardrails.

Agent-safe tools (16 total):
  - create_agent_wallet      — Agent wallet provisioning
  - list_wallets, get_wallet  — Wallet info
  - check_balance, get_balances — Balance checks
  - pay, simulate_payment, batch_pay — Payment operations
  - create/confirm/cancel/get_payment_intent — Intent lifecycle
  - list_transactions, sync_transaction — Transaction tracking
  - can_pay_recipient, detect_payment_method — Routing checks
  - trust_lookup              — Read-only trust evaluation
  - ledger_get_entry          — Read own ledger entry
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from app.core.config import settings
from app.mcp.auth import get_auth_provider
from app.payments.omniclaw_client import OmniclawPaymentClient

logger = structlog.get_logger(__name__)

async def mcp_lifespan(server: FastMCP):
    """Lifecycle manager for the MCP server resources."""
    logger.info(
        "mcp_startup_init",
        env=settings.ENVIRONMENT,
        project=settings.PROJECT_NAME,
        network=settings.OMNICLAW_NETWORK,
    )

    # Validate production environment
    if settings.ENVIRONMENT == "prod":
        from omniclaw.onboarding import load_managed_entity_secret

        api_key = settings.CIRCLE_API_KEY.get_secret_value() if settings.CIRCLE_API_KEY else None
        managed_secret = load_managed_entity_secret(api_key) if api_key else None
        if not settings.ENTITY_SECRET and not managed_secret:
            raise RuntimeError("Missing ENTITY_SECRET in production")

    # Warm up client singleton
    await OmniclawPaymentClient.get_instance()
    logger.info("mcp_startup_ready")

    try:
        yield
    finally:
        # Shutdown: Clean up your resources here
        await OmniclawPaymentClient.close_instance()
        logger.info("mcp_shutdown_complete")


mcp = FastMCP(
    name="OmniClaw MCP Server",
    instructions=(
        "Production MCP server for Omniclaw SDK agent operations: "
        "wallet management, guarded payments, payment intents, "
        "transaction sync, and trust checks."
    ),
    auth=get_auth_provider() if settings.MCP_REQUIRE_AUTH else None,
    lifespan=mcp_lifespan,
)


async def _client() -> OmniclawPaymentClient:
    return await OmniclawPaymentClient.get_instance()


def _fail(tool: str, exc: Exception) -> ToolError:
    logger.error("mcp_tool_failed", tool=tool, error=str(exc), exc_info=True)
    return ToolError(f"{tool} failed: {exc}")


# ─────────────────────────────────────────────────────────────────────
# Agent Setup
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def create_agent_wallet(
    agent_name: Annotated[
        str, Field(min_length=1, description="Agent identifier or friendly name")
    ],
    blockchain: Annotated[
        str | None,
        Field(
            default=None, description="Optional network override (e.g. ARC-TESTNET, ETH-SEPOLIA)"
        ),
    ] = None,
    apply_default_guards: Annotated[
        bool,
        Field(default=True, description="Apply default guardrail configuration immediately"),
    ] = True,
) -> dict[str, Any]:
    """Create an agent wallet (and wallet set) with optional default guardrails."""
    try:
        client = await _client()
        result = await client.create_agent_wallet(
            agent_name=agent_name,
            blockchain=blockchain,
            apply_default_guards=apply_default_guards,
        )
        return {"status": "success", **result}
    except Exception as exc:
        raise _fail("create_agent_wallet", exc)


# ─────────────────────────────────────────────────────────────────────
# Wallet Info
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def list_wallets(
    wallet_set_id: Annotated[
        str | None,
        Field(default=None, description="Optional wallet set ID filter"),
    ] = None,
) -> dict[str, Any]:
    """List wallets (optionally scoped to a wallet set)."""
    try:
        client = await _client()
        result = await client.list_wallets(wallet_set_id=wallet_set_id)
        return {"status": "success", "wallets": result}
    except Exception as exc:
        raise _fail("list_wallets", exc)


@mcp.tool()
async def get_wallet(
    wallet_id: Annotated[str, Field(min_length=1, description="Wallet ID")],
) -> dict[str, Any]:
    """Get wallet metadata by ID."""
    try:
        client = await _client()
        result = await client.get_wallet(wallet_id)
        return {"status": "success", "wallet": result}
    except Exception as exc:
        raise _fail("get_wallet", exc)


# ─────────────────────────────────────────────────────────────────────
# Balance
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def check_balance(
    wallet_id: Annotated[str, Field(min_length=1, description="Wallet ID")],
) -> dict[str, Any]:
    """Get current wallet USDC balance."""
    try:
        client = await _client()
        result = await client.get_wallet_usdc_balance(wallet_id)
        return {"status": "success", **result}
    except Exception as exc:
        raise _fail("check_balance", exc)


@mcp.tool()
async def get_balances(
    wallet_id: Annotated[str, Field(min_length=1, description="Wallet ID")],
) -> dict[str, Any]:
    """Get all token balances for a wallet."""
    try:
        client = await _client()
        result = await client.get_balances(wallet_id)
        return {"status": "success", **result}
    except Exception as exc:
        raise _fail("get_balances", exc)


# ─────────────────────────────────────────────────────────────────────
# Payments
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def simulate(
    wallet_id: Annotated[str, Field(min_length=1, description="Source wallet ID")],
    recipient: Annotated[str, Field(min_length=1, description="Recipient address/URL")],
    amount: Annotated[str, Field(min_length=1, description="USDC amount as string")],
    wallet_set_id: Annotated[
        str | None,
        Field(default=None, description="Optional wallet set ID if looking up an agent wallet"),
    ] = None,
    check_trust: Annotated[
        bool | None,
        Field(default=None, description="Override Trust Gate check (None = SDK default)"),
    ] = None,
) -> dict[str, Any]:
    """Simulate a payment without moving funds."""
    try:
        client = await _client()
        result = await client.simulate_payment(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=amount,
            wallet_set_id=wallet_set_id,
            check_trust=check_trust,
        )
        return {"status": "success", "simulation": result}
    except Exception as exc:
        raise _fail("simulate", exc)


@mcp.tool()
async def pay(
    wallet_id: Annotated[str, Field(min_length=1, description="Source wallet ID")],
    recipient: Annotated[str, Field(min_length=1, description="Recipient address/URL")],
    amount: Annotated[str, Field(min_length=1, description="USDC amount as string")],
    destination_chain: Annotated[
        str | None,
        Field(
            default=None, description="Optional cross-chain destination network (e.g. ARB-MAINNET)"
        ),
    ] = None,
    wallet_set_id: Annotated[
        str | None,
        Field(default=None, description="Optional wallet set ID"),
    ] = None,
    purpose: Annotated[
        str | None, Field(default=None, description="Optional payment purpose")
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Field(default=None, description="Optional caller-provided idempotency key"),
    ] = None,
    fee_level: Annotated[
        str,
        Field(default="medium", description="Fee tier to use (low, medium, high)"),
    ] = "medium",
    strategy: Annotated[
        str,
        Field(
            default="retry_then_fail", description="Execution strategy (fail_fast, retry_then_fail)"
        ),
    ] = "retry_then_fail",
    check_trust: Annotated[
        bool | None,
        Field(default=None, description="Override Trust Gate check (None = SDK default)"),
    ] = None,
    consume_intent_id: Annotated[
        str | None,
        Field(default=None, description="Optional intent ID to consume with this payment"),
    ] = None,
    wait_for_completion: Annotated[
        bool,
        Field(default=False, description="Wait for provider completion before returning"),
    ] = False,
    timeout_seconds: Annotated[
        float | None,
        Field(default=None, description="Optional custom timeout in seconds"),
    ] = None,
) -> dict[str, Any]:
    """Execute a guarded payment."""
    try:
        client = await _client()
        result = await client.execute_payment(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=amount,
            destination_chain=destination_chain,
            wallet_set_id=wallet_set_id,
            purpose=purpose,
            idempotency_key=idempotency_key,
            fee_level=fee_level,
            strategy=strategy,
            check_trust=check_trust,
            consume_intent_id=consume_intent_id,
            wait_for_completion=wait_for_completion,
            timeout_seconds=timeout_seconds,
        )
        return {"status": "success", "payment": result}
    except Exception as exc:
        raise _fail("pay", exc)


@mcp.tool()
async def batch_pay(
    requests: Annotated[
        list[dict[str, Any]],
        Field(
            description="List of payment request specifications. Must include wallet_id, recipient, amount, fee_level, destination_chain, idempotency_key"
        ),
    ],
) -> dict[str, Any]:
    """Execute multiple payments as a batch."""
    try:
        client = await _client()
        result = await client.batch_pay(
            requests=requests,
        )
        return {"status": "success", "batch_result": result}
    except Exception as exc:
        raise _fail("batch_pay", exc)


# ─────────────────────────────────────────────────────────────────────
# Payment Intents
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def create_payment_intent(
    wallet_id: Annotated[str, Field(min_length=1, description="Source wallet ID")],
    recipient: Annotated[str, Field(min_length=1, description="Recipient address/URL")],
    amount: Annotated[str, Field(min_length=1, description="USDC amount as string")],
    destination_chain: Annotated[
        str | None,
        Field(default=None, description="Optional intent destination network"),
    ] = None,
    purpose: Annotated[str | None, Field(default=None, description="Intent purpose")] = None,
    expires_in: Annotated[
        int | None, Field(default=None, ge=1, description="Intent TTL in seconds")
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Field(default=None, description="Optional idempotency key"),
    ] = None,
    metadata: Annotated[
        dict[str, Any] | None,
        Field(default=None, description="Additional metadata to persist with intent"),
    ] = None,
) -> dict[str, Any]:
    """Create a payment intent (authorization phase)."""
    try:
        client = await _client()
        result = await client.create_payment_intent(
            wallet_id=wallet_id,
            recipient=recipient,
            amount=amount,
            purpose=purpose,
            expires_in=expires_in,
            idempotency_key=idempotency_key,
            metadata=metadata,
            **({"destination_chain": destination_chain} if destination_chain else {}),
        )
        return {"status": "success", "intent": result}
    except Exception as exc:
        raise _fail("create_payment_intent", exc)


@mcp.tool()
async def get_payment_intent(
    intent_id: Annotated[str, Field(min_length=1, description="Payment intent ID")],
) -> dict[str, Any]:
    """Fetch a payment intent by ID."""
    try:
        client = await _client()
        result = await client.get_payment_intent(intent_id)
        return {"status": "success", "intent": result}
    except Exception as exc:
        raise _fail("get_payment_intent", exc)


@mcp.tool()
async def confirm_payment_intent(
    intent_id: Annotated[str, Field(min_length=1, description="Payment intent ID")],
) -> dict[str, Any]:
    """Confirm and execute a payment intent (capture phase)."""
    try:
        client = await _client()
        result = await client.confirm_intent(intent_id)
        return {"status": "success", "payment": result}
    except Exception as exc:
        raise _fail("confirm_payment_intent", exc)


@mcp.tool()
async def cancel_intent(
    intent_id: Annotated[str, Field(min_length=1, description="Payment intent ID")],
    reason: Annotated[str | None, Field(default=None, description="Optional cancel reason")] = None,
) -> dict[str, Any]:
    """Cancel a payment intent and release reserved funds."""
    try:
        client = await _client()
        result = await client.cancel_intent(intent_id, reason=reason)
        return {"status": "success", "intent": result}
    except Exception as exc:
        raise _fail("cancel_intent", exc)


# ─────────────────────────────────────────────────────────────────────
# Transactions
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def list_transactions(
    wallet_id: Annotated[
        str | None, Field(default=None, description="Optional wallet ID filter")
    ] = None,
    blockchain: Annotated[
        str | None, Field(default=None, description="Optional network filter")
    ] = None,
) -> dict[str, Any]:
    """List provider transactions for a wallet or globally."""
    try:
        client = await _client()
        result = await client.list_transactions(wallet_id=wallet_id, blockchain=blockchain)
        return {"status": "success", **result}
    except Exception as exc:
        raise _fail("list_transactions", exc)


@mcp.tool()
async def sync_transaction(
    ledger_entry_id: Annotated[str, Field(min_length=1, description="Ledger entry ID")],
) -> dict[str, Any]:
    """Sync a ledger entry with current provider transaction state."""
    try:
        client = await _client()
        result = await client.sync_transaction(ledger_entry_id)
        return {"status": "success", **result}
    except Exception as exc:
        raise _fail("sync_transaction", exc)


# ─────────────────────────────────────────────────────────────────────
# Routing & Trust (read-only)
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def can_pay(
    recipient: Annotated[str, Field(min_length=1, description="Recipient address/URL")],
) -> dict[str, Any]:
    """Check if any Omniclaw payment adapter can handle this recipient."""
    try:
        client = await _client()
        result = await client.can_pay(recipient)
        return {"status": "success", **result}
    except Exception as exc:
        raise _fail("can_pay", exc)


@mcp.tool()
async def detect_payment_method(
    recipient: Annotated[str, Field(min_length=1, description="Recipient address/URL")],
) -> dict[str, Any]:
    """Detect which payment method Omniclaw would route to."""
    try:
        client = await _client()
        result = await client.detect_method(recipient)
        return {"status": "success", **result}
    except Exception as exc:
        raise _fail("detect_payment_method", exc)


@mcp.tool()
async def trust_lookup(
    recipient_address: Annotated[str, Field(min_length=1, description="Recipient wallet address")],
    amount: Annotated[
        str, Field(default="0", description="Reference amount for policy evaluation")
    ] = "0",
    wallet_id: Annotated[
        str | None, Field(default=None, description="Wallet ID for wallet-specific policy")
    ] = None,
    network: Annotated[str | None, Field(default=None, description="Network override")] = None,
) -> dict[str, Any]:
    """Run ERC-8004 Trust Gate evaluation."""
    try:
        client = await _client()
        result = await client.trust_lookup(
            recipient_address=recipient_address,
            amount=amount,
            wallet_id=wallet_id,
            network=network,
        )
        return {"status": "success", **result}
    except Exception as exc:
        raise _fail("trust_lookup", exc)


# ─────────────────────────────────────────────────────────────────────
# Ledger (read-only, single entry)
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def ledger_get_entry(
    entry_id: Annotated[str, Field(min_length=1, description="Ledger entry ID")],
) -> dict[str, Any]:
    """Get a ledger entry by ID."""
    try:
        client = await _client()
        result = await client.ledger_get_entry(entry_id)
        return {"status": "success", **result}
    except Exception as exc:
        raise _fail("ledger_get_entry", exc)
