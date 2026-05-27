"""API routes for agent server."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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
    X402InspectRequest,
    X402InspectResponse,
)
from omniclaw.agent.policy import PolicyManager, WalletManager
from omniclaw.core.logging import get_logger
from omniclaw.core.types import PaymentMethod
from omniclaw.guards.confirmations import ConfirmationStore

if TYPE_CHECKING:
    from omniclaw import OmniClaw

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agent"])


def _fmt_amount(value: object) -> str:
    try:
        amount = Decimal(str(value))
        if amount.copy_abs() < Decimal("0.01") and amount != 0:
            return f"{amount.quantize(Decimal('0.000001'))}".rstrip("0").rstrip(".")
        return f"{amount.quantize(Decimal('0.01'))}"
    except Exception:
        return str(value)


def _x402_selected_amount_exceeds_cap(selected_kind: Any, amount_cap: str | None) -> bool:
    if not selected_kind or amount_cap is None:
        return False
    return selected_kind.get_amount_usdc() > Decimal(str(amount_cap))


def _rail_for_selected_route(selected_route: object) -> str | None:
    route = str(selected_route or "").strip().lower()
    if route in {"nanopayment", "x402"}:
        return "x402"
    return None


def _public_x402_route(selected_route: object) -> str | None:
    """Expose buyer-facing rail names; keep Gateway as an internal x402 path."""
    if _rail_for_selected_route(selected_route) == "x402":
        return "x402"
    return None


def _public_payment_method(recipient: str, method: object) -> str:
    if recipient.startswith(("http://", "https://")):
        return "x402"
    value = str(method.value if hasattr(method, "value") else method or "").strip().lower()
    if value in {"transfer", "crosschain"}:
        return "circle_transfer"
    return value or "circle_transfer"


def _policy_rail_enabled(policy_mgr: PolicyManager, rail: str, wallet_id: str | None) -> bool:
    if hasattr(policy_mgr, "is_rail_enabled"):
        return bool(policy_mgr.is_rail_enabled(rail, wallet_id))
    return True


def _server_rail_enabled(client: OmniClaw, rail: str) -> bool:
    config = getattr(client, "config", None)
    if config is None:
        return False
    if rail == "circle_transfer":
        return bool(getattr(config, "enable_circle_transfer", False))
    if rail == "x402":
        return bool(
            getattr(config, "enable_x402", False)
            or getattr(config, "enable_gateway", False)
            or getattr(config, "enable_x402_exact", False)
        )
    if rail == "gateway":
        return bool(getattr(config, "enable_gateway", False))
    if rail == "x402_exact":
        return bool(getattr(config, "enable_x402_exact", False))
    return False


def _server_x402_route_enabled(client: OmniClaw, selected_route: object) -> bool:
    route = str(selected_route or "").strip().lower()
    if route == "nanopayment":
        return _server_rail_enabled(client, "gateway")
    if route == "x402":
        return _server_rail_enabled(client, "x402_exact")
    return False


def _server_x402_route_disabled_reason(selected_route: object) -> str:
    route = str(selected_route or "").strip().lower()
    if route == "nanopayment":
        return "x402 Gateway nanopayment execution is disabled by server config"
    if route == "x402":
        return "standard x402 execution is disabled by server config"
    return "x402 execution is disabled by server config"


def _private_key_address(private_key: str | None) -> str | None:
    if not private_key:
        return None
    try:
        from eth_account import Account

        key = private_key if private_key.startswith("0x") else f"0x{private_key}"
        return Account.from_key(key).address
    except Exception:
        return None


def _client_signer_address(client: OmniClaw) -> str | None:
    if getattr(client, "_nano_adapter", None):
        return client._nano_adapter.address
    config = getattr(client, "config", None)
    private_key = getattr(config, "nanopayments_private_key", None) or os.environ.get(
        "OMNICLAW_PRIVATE_KEY"
    )
    return _private_key_address(private_key)


def _find_adapter_by_method(client: OmniClaw, method: PaymentMethod | str):
    for adapter in client._router.get_adapters():
        adapter_method = getattr(adapter, "method", None)
        adapter_value = adapter_method.value if hasattr(adapter_method, "value") else adapter_method
        target_value = method.value if hasattr(method, "value") else method
        if adapter_value == target_value:
            return adapter
    return None


async def _choose_x402_route(
    *,
    client: OmniClaw,
    wallet_id: str,
    x402_adapter: Any,
    requirements: Any,
    allow_gateway: bool = True,
    allow_x402_exact: bool = True,
) -> dict[str, object]:
    agent_network = x402_adapter._resolve_agent_network(wallet_id, None)
    selected_gateway_kind = requirements.select_preferred_kind(
        prefer_gateway=True,
        source_network=agent_network,
    )
    selected_exact_kind = requirements.select_preferred_kind(
        prefer_gateway=False,
        source_network=agent_network,
    )
    gateway_available_balance: str | None = None
    gateway_ready: bool | None = None
    gateway_reason: str | None = None

    async def onchain_gateway_balance() -> Any:
        if hasattr(client, "get_gateway_onchain_balance_for_kind"):
            return await client.get_gateway_onchain_balance_for_kind(selected_gateway_kind)
        return await client.get_gateway_onchain_balance(wallet_id)

    if selected_gateway_kind is not None and allow_gateway:
        if client._nano_adapter is None:
            gateway_ready = False
            gateway_reason = "Gateway route is advertised but nanopayments are not enabled"
        else:
            try:
                balance = await client.get_gateway_balance(wallet_id)
                gateway_available_balance = balance.formatted_available
                required_atomic = int(selected_gateway_kind.amount_atomic)
                gateway_ready = balance.available >= required_atomic
                if gateway_ready:
                    gateway_reason = "Gateway balance is sufficient for GatewayWalletBatched"
                else:
                    # Fallback to direct on-chain balance when API-reported balance is stale/lagging.
                    try:
                        onchain_balance = await onchain_gateway_balance()
                        if onchain_balance.available >= required_atomic:
                            gateway_available_balance = onchain_balance.formatted_available
                            gateway_ready = True
                            gateway_reason = (
                                "Gateway on-chain balance is sufficient (API balance appears stale)"
                            )
                        else:
                            gateway_reason = "Gateway balance is below the required amount"
                    except Exception:
                        gateway_reason = "Gateway balance is below the required amount"
            except Exception as exc:
                try:
                    required_atomic = int(selected_gateway_kind.amount_atomic)
                    onchain_balance = await onchain_gateway_balance()
                    gateway_available_balance = onchain_balance.formatted_available
                    gateway_ready = onchain_balance.available >= required_atomic
                    gateway_reason = (
                        "Gateway on-chain balance is sufficient"
                        if gateway_ready
                        else "Gateway on-chain balance is below the required amount"
                    )
                except Exception:
                    gateway_ready = False
                    gateway_reason = f"Gateway balance check failed: {exc}"

    if selected_gateway_kind is not None and allow_gateway and gateway_ready:
        return {
            "selected_kind": selected_gateway_kind,
            "selected_route": "nanopayment",
            "payment_source": "gateway_balance",
            "gateway_available_balance": gateway_available_balance,
            "gateway_ready": gateway_ready,
            "gateway_reason": gateway_reason,
        }

    if selected_exact_kind is not None and allow_x402_exact:
        return {
            "selected_kind": selected_exact_kind,
            "selected_route": "x402",
            "payment_source": "direct_wallet",
            "gateway_available_balance": gateway_available_balance,
            "gateway_ready": gateway_ready,
            "gateway_reason": gateway_reason,
        }

    if selected_gateway_kind is not None and allow_gateway:
        return {
            "selected_kind": selected_gateway_kind,
            "selected_route": "nanopayment",
            "payment_source": "gateway_balance",
            "gateway_available_balance": gateway_available_balance,
            "gateway_ready": gateway_ready,
            "gateway_reason": gateway_reason,
        }

    return {
        "selected_kind": None,
        "selected_route": None,
        "payment_source": None,
        "gateway_available_balance": gateway_available_balance,
        "gateway_ready": gateway_ready,
        "gateway_reason": gateway_reason,
    }


async def _inspect_x402_target(
    *,
    client: OmniClaw,
    wallet_id: str,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | bytes | None = None,
    allow_gateway: bool = True,
    allow_x402_exact: bool = True,
) -> dict[str, object]:
    x402_adapter = _find_adapter_by_method(client, PaymentMethod.X402)
    if x402_adapter is None:
        return {
            "ok": False,
            "requires_payment": False,
            "reason": "X402 adapter is not registered",
        }

    try:
        response, requirements = await x402_adapter._request_with_402_check(
            url,
            method=method,
            headers=headers,
            content=body,
        )
    except Exception as exc:
        return {
            "ok": False,
            "requires_payment": False,
            "reason": f"Inspection request failed: {exc}",
        }

    router_method = client.detect_method(url)
    router_route = router_method.value if hasattr(router_method, "value") else str(router_method)

    if response.status_code != 402:
        return {
            "ok": True,
            "requires_payment": False,
            "reason": "Endpoint does not currently require payment",
            "router_detected_route": router_route,
            "selected_route": None,
            "payment_source": None,
            "seller_accepts": [],
            "selected_kind": None,
            "x402_adapter": x402_adapter,
        }

    if not requirements:
        return {
            "ok": False,
            "requires_payment": True,
            "reason": "Endpoint returned 402 but payment requirements could not be parsed",
            "router_detected_route": router_route,
            "seller_accepts": [],
            "selected_kind": None,
            "x402_adapter": x402_adapter,
        }

    route_choice = await _choose_x402_route(
        client=client,
        wallet_id=wallet_id,
        x402_adapter=x402_adapter,
        requirements=requirements,
        allow_gateway=allow_gateway,
        allow_x402_exact=allow_x402_exact,
    )
    selected_kind = route_choice["selected_kind"]
    selected_route = route_choice["selected_route"]
    payment_source = route_choice["payment_source"]

    seller_accepts: list[dict[str, object]] = []
    for kind in requirements.accepts:
        seller_accepts.append(
            {
                "scheme": kind.scheme,
                "network": kind.network,
                "asset": kind.asset,
                "amount_atomic": kind.amount_atomic,
                "amount_usdc": str(kind.get_amount_usdc()),
                "pay_to": kind.recipient,
                "facilitator_name": kind.facilitator_name or None,
                "is_gateway_batched": kind.is_gateway_batched,
            }
        )

    return {
        "ok": True,
        "requires_payment": True,
        "reason": None,
        "router_detected_route": selected_route,
        "selected_route": selected_route,
        "payment_source": payment_source,
        "seller_accepts": seller_accepts,
        "selected_kind": selected_kind,
        "x402_adapter": x402_adapter,
        "gateway_available_balance": route_choice["gateway_available_balance"],
        "gateway_ready": route_choice["gateway_ready"],
        "gateway_reason": route_choice["gateway_reason"],
    }


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


async def require_owner(request: Request) -> None:
    """Require owner token for privileged actions."""
    expected = os.environ.get("OMNICLAW_OWNER_TOKEN")
    if not expected:
        raise HTTPException(status_code=500, detail="OMNICLAW_OWNER_TOKEN not configured")
    provided = request.headers.get("X-Omniclaw-Owner-Token")
    if provided != expected:
        raise HTTPException(status_code=403, detail="Invalid owner token")


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok")


@router.get("/address", response_model=AddressResponse)
async def get_address(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )

    eoa_address = _client_signer_address(client)
    circle_address = await wallet_mgr.get_wallet_address(agent.wallet_id)
    address = eoa_address or circle_address

    if not address:
        raise HTTPException(status_code=404, detail="Wallet not found")

    wallet_cfg = policy_mgr.get_wallet_config(agent.wallet_id)
    alias = wallet_cfg.get("alias") or agent.wallet_id.replace("pending-", "")

    return AddressResponse(
        wallet_id=agent.wallet_id,
        alias=alias,
        address=address,
        eoa_address=eoa_address,
        circle_wallet_address=circle_address,
    )


@router.get("/nano-address")
async def get_nano_address(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    """Get or create nanopayment address for this agent."""
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )

    try:
        # Direct private key mode - return EOA address
        if client._nano_adapter:
            nano_addr = client._nano_adapter.address
        else:
            raise HTTPException(
                status_code=500,
                detail="Nanopayments not initialized (direct key required)",
            )

        return {"address": nano_addr, "wallet_id": agent.wallet_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get nano address: {e}") from e


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )

    if client._nano_adapter:
        note = None
        try:
            gateway_balance = await client.get_gateway_balance(agent.wallet_id)
        except Exception as exc:
            gateway_balance = None
            note = (
                "Gateway API balance unavailable. x402 Gateway payments use seller-specific "
                f"on-chain balance checks when needed: {exc}"
            )
        available = gateway_balance.available_decimal if gateway_balance else "0.00"
        total = gateway_balance.total_decimal if gateway_balance else None
        reserved = None
        source = "gateway_api" if gateway_balance else "unavailable"
    else:
        balance = await wallet_mgr.get_wallet_balance(agent.wallet_id)
        if balance is None:
            raise HTTPException(status_code=404, detail="Wallet not found")
        available = str(balance)
        total = None
        reserved = None
        source = "circle_wallet"
        note = None

    return BalanceResponse(
        wallet_id=agent.wallet_id,
        available=_fmt_amount(available),
        total=_fmt_amount(total) if total is not None else None,
        reserved=reserved,
        source=source,
        note=note,
    )


@router.get("/balance-detail")
async def get_detailed_balance(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    """Get detailed balance including Gateway on-chain balance."""
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )

    eoa_address = _client_signer_address(client)
    circle_address = await wallet_mgr.get_wallet_address(agent.wallet_id)
    circle_balance = await wallet_mgr.get_wallet_balance(agent.wallet_id)
    gateway_balance = None
    gateway_onchain_balance = None
    gateway_balance_note = None
    gateway_onchain_balance_note = None
    if client._nano_adapter:
        try:
            gateway_balance = await client.get_gateway_balance(agent.wallet_id)
        except Exception as exc:
            gateway_balance = None
            gateway_balance_note = (
                "Gateway API balance unavailable. x402 Gateway payments can still use "
                f"seller-specific on-chain checks: {exc}"
            )
        try:
            gateway_onchain_balance = await client.get_gateway_onchain_balance(agent.wallet_id)
        except Exception as exc:
            gateway_onchain_balance = None
            gateway_onchain_balance_note = (
                "Generic Gateway on-chain balance unavailable without configured Gateway "
                f"metadata: {exc}"
            )
    payment_address = (
        await client.get_payment_address(agent.wallet_id) if client._nano_client else None
    )
    payment_gateway_balance = None
    if payment_address:
        try:
            payment_gateway_balance = await client.get_gateway_balance_for_address(payment_address)
        except Exception:
            payment_gateway_balance = None

    return {
        "wallet_id": agent.wallet_id,
        "eoa_address": eoa_address,
        "gateway_balance": _fmt_amount(gateway_balance.available_decimal)
        if gateway_balance
        else "0.00",
        "gateway_balance_atomic": gateway_balance.available if gateway_balance else 0,
        "gateway_total_atomic": gateway_balance.total if gateway_balance else 0,
        "gateway_balance_available": gateway_balance is not None,
        "gateway_balance_note": gateway_balance_note,
        "gateway_onchain_balance": _fmt_amount(gateway_onchain_balance.available_decimal)
        if gateway_onchain_balance
        else "0.00",
        "gateway_onchain_balance_atomic": gateway_onchain_balance.available
        if gateway_onchain_balance
        else 0,
        "gateway_onchain_balance_available": gateway_onchain_balance is not None,
        "gateway_onchain_balance_note": gateway_onchain_balance_note,
        "circle_wallet_address": circle_address,
        "circle_wallet_balance": _fmt_amount(circle_balance)
        if circle_balance is not None
        else "0.00",
        "payment_address": payment_address,
        "payment_gateway_balance": (
            _fmt_amount(payment_gateway_balance.available_decimal)
            if payment_gateway_balance
            else None
        ),
        "payment_gateway_balance_atomic": (
            payment_gateway_balance.available if payment_gateway_balance else None
        ),
    }


@router.post("/deposit")
async def deposit_to_gateway(
    amount: str = ...,
    check_gas: bool = False,
    skip_if_insufficient_gas: bool = True,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    """
    Deposit USDC to Gateway wallet from EOA.

    This moves USDC from the agent's EOA into their Gateway balance.
    Required before making/receiving nanopayments.

    Args:
        amount: Amount in USDC (e.g., "10.00")
        check_gas: Check gas balance before deposit
        skip_if_insufficient_gas: Skip if not enough gas for deposit tx
    """
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )
    if not _policy_rail_enabled(policy_mgr, "x402", agent.wallet_id):
        raise HTTPException(status_code=400, detail="x402 rail is disabled by policy")
    if not _server_rail_enabled(client, "gateway"):
        raise HTTPException(
            status_code=400,
            detail="x402 Gateway nanopayment funding is disabled by server config",
        )

    try:
        result = await client.deposit_to_gateway(
            wallet_id=agent.wallet_id,
            amount_usdc=amount,
            check_gas=check_gas,
            skip_if_insufficient_gas=skip_if_insufficient_gas,
        )

        return {
            "success": result.deposit_tx_hash is not None,
            "amount_deposited": result.formatted_amount,
            "approval_tx_hash": result.approval_tx_hash,
            "deposit_tx_hash": result.deposit_tx_hash,
            "message": "Deposited to Gateway" if result.deposit_tx_hash else "Deposit failed",
        }
    except Exception as e:
        import traceback

        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}") from e


@router.post("/withdraw")
async def withdraw_from_gateway(
    request: Request = None,  # type: ignore[assignment]
    amount: str = ...,
    destination_chain: str | None = None,
    recipient: str | None = None,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    """
    Withdraw USDC from Gateway wallet via Circle API.

    Args:
        amount: Amount in USDC (e.g., "1.00")
        destination_chain: Optional CAIP-2 chain for cross-chain withdrawal
        recipient: Optional destination address (defaults to own address)
    """
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )
    if not _policy_rail_enabled(policy_mgr, "x402", agent.wallet_id):
        raise HTTPException(status_code=400, detail="x402 rail is disabled by policy")
    if not _server_rail_enabled(client, "gateway"):
        raise HTTPException(
            status_code=400,
            detail="x402 Gateway nanopayment withdrawal is disabled by server config",
        )
    if recipient is not None and request is not None:
        await require_owner(request)
    elif recipient is not None:
        raise HTTPException(status_code=403, detail="Owner token required")

    try:
        from decimal import Decimal

        if recipient is None:
            wallet_cfg = policy_mgr.get_wallet_config(agent.wallet_id)
            recipient = wallet_cfg.get("address")
            if not recipient:
                raise HTTPException(
                    status_code=400,
                    detail="No default withdrawal address in policy. Set wallets.<alias>.address or pass recipient.",
                )
        if not policy_mgr.is_valid_recipient(recipient, agent.wallet_id):
            raise HTTPException(
                status_code=400, detail="Withdrawal recipient not allowed by policy"
            )

        requested_amount = Decimal(str(amount))
        try:
            result = await client.withdraw_from_gateway(
                wallet_id=agent.wallet_id,
                amount_usdc=amount,
                destination_chain=destination_chain,
                recipient=recipient,
            )
            burn_tx_hash = getattr(result, "burn_tx_hash", None)
            mint_tx_hash = getattr(result, "mint_tx_hash", None)
            status = getattr(result, "status", None) or ("COMPLETED" if mint_tx_hash else "PENDING")
            return {
                "success": bool(mint_tx_hash),
                "amount_withdrawn": _fmt_amount(result.formatted_amount.split()[0]) + " USDC",
                "burn_tx_hash": burn_tx_hash,
                "mint_tx_hash": mint_tx_hash,
                "status": status,
                "message": "Withdrawal initiated",
            }
        except Exception as exc:
            available = await client.get_gateway_balance(agent.wallet_id)
            if (
                destination_chain is None
                and requested_amount > Decimal("0.10")
                and Decimal(str(available.available_decimal)) >= requested_amount
                and "insufficient_balance" in str(exc).lower()
            ):
                remaining = requested_amount
                mint_tx_hashes = []
                chunk_size = Decimal("0.10")
                while remaining > Decimal("0"):
                    chunk = min(chunk_size, remaining)
                    chunk_result = await client.withdraw_from_gateway(
                        wallet_id=agent.wallet_id,
                        amount_usdc=str(chunk),
                        destination_chain=destination_chain,
                        recipient=recipient,
                    )
                    mint_tx_hash = getattr(chunk_result, "mint_tx_hash", None)
                    if mint_tx_hash:
                        mint_tx_hashes.append(mint_tx_hash)
                    remaining -= chunk
                return {
                    "success": True,
                    "amount_withdrawn": _fmt_amount(requested_amount) + " USDC",
                    "burn_tx_hash": None,
                    "mint_tx_hash": mint_tx_hashes[-1] if mint_tx_hashes else None,
                    "mint_tx_hashes": mint_tx_hashes,
                    "status": "COMPLETED",
                    "message": f"Withdrawal initiated in {len(mint_tx_hashes)} chunks of up to {chunk_size} USDC",
                }
            raise exc
    except Exception as e:
        import traceback

        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}") from e


@router.post("/withdraw-trustless")
async def withdraw_trustless(
    request: Request,
    amount: str = ...,
    agent: AuthenticatedAgent = Depends(get_current_agent),
):
    """
    Initiate trustless withdrawal directly on-chain (~7-day delay).

    This bypasses Circle's API and withdraws directly to the agent's own address.
    """
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )

    try:
        import os
        from datetime import datetime, timedelta

        from omniclaw.core.types import network_to_caip2
        from omniclaw.protocols.nanopayments.client import NanopaymentClient
        from omniclaw.protocols.nanopayments.wallet import GatewayWalletManager

        private_key_str = os.environ.get("OMNICLAW_PRIVATE_KEY")
        if not private_key_str:
            raise HTTPException(status_code=500, detail="OMNICLAW_PRIVATE_KEY not configured")

        config = request.app.state.config if hasattr(request.app.state, "config") else {}
        network = config.get("nanopay_network") or network_to_caip2(
            os.environ.get("OMNICLAW_NETWORK", "ARC-TESTNET")
        )
        rpc_url = config.get("rpc_url") or os.environ.get("OMNICLAW_RPC_URL") or ""
        if not network or ":" not in network:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Invalid nanopayments network. Set OMNICLAW_NETWORK to an EVM chain "
                    "that maps to a CAIP-2 chain ID (e.g., ETH-SEPOLIA)."
                ),
            )
        if not rpc_url:
            raise HTTPException(status_code=500, detail="OMNICLAW_RPC_URL not configured")

        nanopayment_client = NanopaymentClient(
            api_key=os.environ.get("CIRCLE_API_KEY"),
        )

        manager = GatewayWalletManager(
            private_key=private_key_str,
            network=network,
            rpc_url=rpc_url,
            nanopayment_client=nanopayment_client,
        )

        delay_blocks = await manager.get_withdrawal_delay()

        delay_seconds = delay_blocks * 12
        available_after = datetime.now() + timedelta(seconds=delay_seconds)

        tx_hash = await manager.initiate_trustless_withdrawal(amount_usdc=amount)

        return {
            "success": True,
            "tx_hash": tx_hash,
            "amount": amount,
            "delay_blocks": delay_blocks,
            "available_after": available_after.isoformat(),
            "message": f"Trustless withdrawal initiated. Wait ~{delay_blocks} blocks before completing.",
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}") from e


@router.post("/withdraw-trustless/complete")
async def complete_trustless_withdrawal(
    request: Request,
    agent: AuthenticatedAgent = Depends(get_current_agent),
):
    """
    Complete a trustless withdrawal after the delay has passed.
    """
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )

    try:
        import os

        from omniclaw.core.types import network_to_caip2
        from omniclaw.protocols.nanopayments.client import NanopaymentClient
        from omniclaw.protocols.nanopayments.wallet import GatewayWalletManager

        private_key_str = os.environ.get("OMNICLAW_PRIVATE_KEY")
        if not private_key_str:
            raise HTTPException(status_code=500, detail="OMNICLAW_PRIVATE_KEY not configured")

        config = request.app.state.config if hasattr(request.app.state, "config") else {}
        network = config.get("nanopay_network") or network_to_caip2(
            os.environ.get("OMNICLAW_NETWORK", "ARC-TESTNET")
        )
        rpc_url = config.get("rpc_url") or os.environ.get("OMNICLAW_RPC_URL") or ""
        if not network or ":" not in network:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Invalid nanopayments network. Set OMNICLAW_NETWORK to an EVM chain "
                    "that maps to a CAIP-2 chain ID (e.g., ETH-SEPOLIA)."
                ),
            )
        if not rpc_url:
            raise HTTPException(status_code=500, detail="OMNICLAW_RPC_URL not configured")

        nanopayment_client = NanopaymentClient(
            api_key=os.environ.get("CIRCLE_API_KEY"),
        )

        manager = GatewayWalletManager(
            private_key=private_key_str,
            network=network,
            rpc_url=rpc_url,
            nanopayment_client=nanopayment_client,
        )

        current_block = manager._w3.eth.block_number
        gateway_address = await manager._resolve_gateway_address()
        usdc_address = await manager._resolve_usdc_address()
        gateway = manager._get_gateway_contract(gateway_address)
        withdrawal_block = gateway.functions.withdrawalBlock(usdc_address, manager._address).call()

        if withdrawal_block == 0:
            raise HTTPException(
                status_code=400,
                detail="No withdrawal initiated. Call /withdraw-trustless first.",
            )

        if current_block < withdrawal_block:
            blocks_remaining = withdrawal_block - current_block
            raise HTTPException(
                status_code=425,
                detail=f"Withdrawal not ready. {blocks_remaining} blocks remaining.",
            )

        tx_hash = await manager.complete_trustless_withdrawal()

        return {
            "success": True,
            "tx_hash": tx_hash,
            "message": "Trustless withdrawal completed.",
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}") from e


@router.get("/deposit-address")
async def get_deposit_address(
    request: Request,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    """
    Get the EOA address for depositing USDC from external sources.

    This is the address to send USDC to from faucet or other wallets.
    Then use /deposit to move it to Gateway, or it auto-deposits for nanopayments.
    """
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )
    if not _policy_rail_enabled(policy_mgr, "x402", agent.wallet_id):
        raise HTTPException(status_code=400, detail="x402 rail is disabled by policy")
    if not _server_rail_enabled(client, "gateway"):
        raise HTTPException(
            status_code=400,
            detail="x402 Gateway nanopayment funding is disabled by server config",
        )

    eoa_address = _client_signer_address(client)
    if not eoa_address:
        raise HTTPException(
            status_code=500,
            detail="Nanopayments not initialized (direct key required)",
        )

    config = request.app.state.config if hasattr(request.app.state, "config") else {}
    from omniclaw.core.types import network_to_caip2

    network = config.get("nanopay_network") or network_to_caip2(
        os.getenv("OMNICLAW_NETWORK", "ARC-TESTNET")
    )

    if not network:
        raise HTTPException(
            status_code=500,
            detail=(
                "Nanopayments network is not configured. Set OMNICLAW_NETWORK to an "
                "EVM chain that maps to a CAIP-2 chain ID."
            ),
        )

    return {
        "address": eoa_address,
        "network": network,
        "instructions": "Send USDC to this address, then call /deposit to move to Gateway",
    }


@router.post("/pay", response_model=PayResponse)
async def pay(
    request: PayRequest,
    raw_request: Request = None,  # type: ignore[assignment]
    agent: AuthenticatedAgent = Depends(get_current_agent),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )

    if request.skip_guards and raw_request is not None:
        await require_owner(raw_request)
    elif request.skip_guards:
        raise HTTPException(status_code=403, detail="Owner token required")

    if not policy_mgr.is_valid_recipient(request.recipient, agent.wallet_id):
        raise HTTPException(status_code=400, detail="Recipient not allowed by policy")

    is_url_payment = request.recipient.startswith("http")
    amount_raw = request.amount
    x402_details: dict[str, object] | None = None
    preferred_url_route: str | None = None
    if is_url_payment:
        if not _policy_rail_enabled(policy_mgr, "x402", agent.wallet_id):
            raise HTTPException(status_code=400, detail="x402 rail is disabled by policy")
        if not _server_rail_enabled(client, "x402"):
            raise HTTPException(
                status_code=400, detail="x402 payments are disabled by server config"
            )
        x402_details = await _inspect_x402_target(
            client=client,
            wallet_id=agent.wallet_id,
            url=request.recipient,
            method=request.method,
            headers=request.headers,
            body=request.body,
            allow_gateway=_policy_rail_enabled(policy_mgr, "x402", agent.wallet_id)
            and _server_rail_enabled(client, "gateway"),
            allow_x402_exact=_policy_rail_enabled(policy_mgr, "x402", agent.wallet_id)
            and _server_rail_enabled(client, "x402_exact"),
        )
        if not x402_details.get("ok"):
            raise HTTPException(status_code=400, detail=str(x402_details.get("reason")))

        if bool(x402_details.get("requires_payment")):
            selected_kind = x402_details.get("selected_kind")
            preferred_url_route = str(x402_details.get("selected_route") or "") or None
            if selected_kind is None:
                raise HTTPException(
                    status_code=400,
                    detail=str(
                        x402_details.get("reason")
                        or "Seller does not advertise a buyer-supported x402 payment kind"
                    ),
                )
            selected_rail = _rail_for_selected_route(preferred_url_route)
            if selected_rail is None:
                raise HTTPException(
                    status_code=400,
                    detail="Seller selected an unsupported x402 payment route",
                )
            if selected_rail and not _policy_rail_enabled(
                policy_mgr, selected_rail, agent.wallet_id
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Payment rail '{selected_rail}' is disabled by policy",
                )
            if selected_rail and not _server_x402_route_enabled(client, preferred_url_route):
                raise HTTPException(
                    status_code=400,
                    detail=_server_x402_route_disabled_reason(preferred_url_route),
                )
            if _x402_selected_amount_exceeds_cap(selected_kind, amount_raw):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"x402 price {selected_kind.get_amount_usdc()} exceeds max amount "
                        f"{amount_raw}"
                    ),
                )
            amount_raw = str(selected_kind.get_amount_usdc())
        elif amount_raw is None:
            amount_raw = "0.00"

    if amount_raw is None:
        raise HTTPException(status_code=400, detail="amount is required for direct transfers")
    if not is_url_payment:
        if not _policy_rail_enabled(policy_mgr, "circle_transfer", agent.wallet_id):
            raise HTTPException(
                status_code=400, detail="Circle transfer rail is disabled by policy"
            )
        if not _server_rail_enabled(client, "circle_transfer"):
            raise HTTPException(
                status_code=400, detail="Circle transfer rail is disabled by server config"
            )

    amount = Decimal(amount_raw)
    allowed, reason = policy_mgr.check_limits(amount, agent.wallet_id)
    if not allowed:
        raise HTTPException(status_code=400, detail=reason)

    try:
        metadata = dict(request.metadata or {})
        if is_url_payment:
            metadata.setdefault("method", request.method)
            if request.body is not None:
                metadata.setdefault("body", request.body)
            if request.headers is not None:
                metadata.setdefault("headers", request.headers)

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
            method=request.method,
            request_body=request.body,
            request_headers=request.headers,
            metadata=metadata or None,
            preferred_url_route=preferred_url_route,
        )
        requires_confirmation = bool(
            result.metadata.get("confirmation_required") if result.metadata else False
        )
        confirmation_id = result.metadata.get("confirmation_id") if result.metadata else None

        return PayResponse(
            success=result.success,
            transaction_id=result.transaction_id,
            blockchain_tx=result.blockchain_tx,
            amount=_fmt_amount(result.amount),
            recipient=result.recipient,
            status=result.status.value
            if result.status and hasattr(result.status, "value")
            else (str(result.status) if result.status else "failed"),
            method=_public_payment_method(result.recipient, result.method),
            error=result.error,
            requires_confirmation=requires_confirmation,
            confirmation_id=confirmation_id,
            response_data=result.resource_data,
        )
    except Exception as e:
        logger.error(f"Payment failed: {e}")
        return PayResponse(
            success=False,
            amount=_fmt_amount(amount_raw),
            recipient=request.recipient,
            status="FAILED",
            method="x402" if is_url_payment else "TRANSFER",
            error=str(e),
            requires_confirmation=False,
        )


@router.post("/simulate", response_model=SimulateResponse)
async def simulate(
    request: SimulateRequest,
    raw_request: Request = None,  # type: ignore[assignment]
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    if request.skip_guards and raw_request is not None:
        await require_owner(raw_request)
    elif request.skip_guards:
        raise HTTPException(status_code=403, detail="Owner token required")

    if not policy_mgr.is_valid_recipient(request.recipient, agent.wallet_id):
        return SimulateResponse(
            would_succeed=False, route="TRANSFER", reason="Recipient not allowed by policy"
        )

    is_url_payment = request.recipient.startswith("http")
    amount_raw = request.amount
    route_name = "x402" if is_url_payment else "TRANSFER"
    if is_url_payment:
        if not _policy_rail_enabled(policy_mgr, "x402", agent.wallet_id):
            return SimulateResponse(
                would_succeed=False, route="x402", reason="x402 rail is disabled by policy"
            )
        if not _server_rail_enabled(client, "x402"):
            return SimulateResponse(
                would_succeed=False,
                route="x402",
                reason="x402 payments are disabled by server config",
            )
        x402_details = await _inspect_x402_target(
            client=client,
            wallet_id=agent.wallet_id,
            url=request.recipient,
            method=request.method,
            headers=request.headers,
            body=request.body,
            allow_gateway=_policy_rail_enabled(policy_mgr, "x402", agent.wallet_id)
            and _server_rail_enabled(client, "gateway"),
            allow_x402_exact=_policy_rail_enabled(policy_mgr, "x402", agent.wallet_id)
            and _server_rail_enabled(client, "x402_exact"),
        )
        if not x402_details.get("ok"):
            return SimulateResponse(
                would_succeed=False, route="x402", reason=str(x402_details.get("reason"))
            )
        if bool(x402_details.get("requires_payment")):
            selected_kind = x402_details.get("selected_kind")
            selected_route = x402_details.get("selected_route")
            if selected_kind is None:
                return SimulateResponse(
                    would_succeed=False,
                    route="x402",
                    reason=str(
                        x402_details.get("reason")
                        or "Seller does not advertise a buyer-supported x402 payment kind"
                    ),
                )
            if _rail_for_selected_route(selected_route) is None:
                return SimulateResponse(
                    would_succeed=False,
                    route="x402",
                    reason="Seller selected an unsupported x402 payment route",
                )
            if _x402_selected_amount_exceeds_cap(selected_kind, amount_raw):
                return SimulateResponse(
                    would_succeed=False,
                    route="x402",
                    reason=(
                        f"x402 price {selected_kind.get_amount_usdc()} exceeds max amount "
                        f"{amount_raw}"
                    ),
                )
            amount_raw = str(selected_kind.get_amount_usdc())
            allowed, reason = policy_mgr.check_limits(Decimal(amount_raw), agent.wallet_id)
            if not allowed:
                return SimulateResponse(would_succeed=False, route="x402", reason=reason)
            route_name = "x402"
            if selected_route == "nanopayment":
                return SimulateResponse(
                    would_succeed=bool(x402_details.get("gateway_ready")),
                    route=route_name,
                    reason=str(x402_details.get("gateway_reason") or ""),
                )
            x402_adapter = x402_details.get("x402_adapter")
            if x402_adapter is not None:
                try:
                    sim_result = await x402_adapter.simulate(
                        wallet_id=agent.wallet_id,
                        recipient=request.recipient,
                        amount=Decimal(amount_raw),
                        method=request.method,
                        request_body=request.body,
                        request_headers=request.headers,
                    )
                    return SimulateResponse(
                        would_succeed=bool(sim_result.get("would_succeed")),
                        route=route_name,
                        reason=sim_result.get("reason"),
                    )
                except Exception as exc:
                    return SimulateResponse(would_succeed=False, route=route_name, reason=str(exc))
        elif amount_raw is None:
            amount_raw = "0.00"

    if not is_url_payment and amount_raw is None:
        return SimulateResponse(
            would_succeed=False, route="TRANSFER", reason="amount is required for direct transfers"
        )
    if not is_url_payment and not _policy_rail_enabled(
        policy_mgr, "circle_transfer", agent.wallet_id
    ):
        return SimulateResponse(
            would_succeed=False,
            route="TRANSFER",
            reason="Circle transfer rail is disabled by policy",
        )
    if not is_url_payment and not _server_rail_enabled(client, "circle_transfer"):
        return SimulateResponse(
            would_succeed=False,
            route="TRANSFER",
            reason="Circle transfer rail is disabled by server config",
        )

    amount = Decimal(str(amount_raw))
    allowed, reason = policy_mgr.check_limits(amount, agent.wallet_id)
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
            route=result.route.value
            if result.route and hasattr(result.route, "value")
            else str(result.route or route_name),
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
        entries = await client._ledger.query(wallet_id=agent.wallet_id, limit=limit)
        return ListTransactionsResponse(
            transactions=[
                TransactionInfo(
                    id=entry.id,
                    wallet_id=entry.wallet_id,
                    recipient=entry.recipient,
                    amount=_fmt_amount(entry.amount),
                    status=entry.status.value,
                    tx_hash=entry.tx_hash,
                    created_at=entry.timestamp.isoformat() if entry.timestamp else None,
                )
                for entry in entries
            ],
            total=len(entries),
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
    if not policy_mgr.is_valid_recipient(request.recipient, agent.wallet_id):
        raise HTTPException(status_code=400, detail="Recipient not allowed by policy")

    amount = Decimal(request.amount)
    allowed, reason = policy_mgr.check_limits(amount, agent.wallet_id)
    if not allowed:
        raise HTTPException(status_code=400, detail=reason)
    is_url_payment = request.recipient.startswith("http")
    if is_url_payment:
        if not _policy_rail_enabled(policy_mgr, "x402", agent.wallet_id):
            raise HTTPException(status_code=400, detail="x402 rail is disabled by policy")
        if not _server_rail_enabled(client, "x402"):
            raise HTTPException(
                status_code=400, detail="x402 payments are disabled by server config"
            )
    else:
        if not _policy_rail_enabled(policy_mgr, "circle_transfer", agent.wallet_id):
            raise HTTPException(
                status_code=400, detail="Circle transfer rail is disabled by policy"
            )
        if not _server_rail_enabled(client, "circle_transfer"):
            raise HTTPException(
                status_code=400, detail="Circle transfer rail is disabled by server config"
            )

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
            status=intent.status.value
            if intent.status and hasattr(intent.status, "value")
            else (str(intent.status) if intent.status else "failed"),
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
            status=intent.status.value
            if intent.status and hasattr(intent.status, "value")
            else (str(intent.status) if intent.status else "failed"),
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
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    try:
        intent = await client.get_payment_intent(intent_id)
        if not intent:
            raise HTTPException(status_code=404, detail="Intent not found")

        if intent.wallet_id != agent.wallet_id:
            raise HTTPException(status_code=403, detail="Intent belongs to different wallet")
        if not policy_mgr.is_valid_recipient(intent.recipient, agent.wallet_id):
            raise HTTPException(status_code=400, detail="Recipient not allowed by policy")
        allowed, reason = policy_mgr.check_limits(Decimal(str(intent.amount)), agent.wallet_id)
        if not allowed:
            raise HTTPException(status_code=400, detail=reason)
        if intent.recipient.startswith("http"):
            route = (intent.metadata or {}).get("simulated_route")
            rail = _rail_for_selected_route(route)
            if rail is None:
                raise HTTPException(
                    status_code=400,
                    detail="Intent authorized route is missing or unsupported; refusing execution",
                )
            if rail and not _policy_rail_enabled(policy_mgr, rail, agent.wallet_id):
                raise HTTPException(
                    status_code=400, detail=f"Payment rail '{rail}' is disabled by policy"
                )
            if rail and not _server_x402_route_enabled(client, route):
                raise HTTPException(
                    status_code=400,
                    detail=_server_x402_route_disabled_reason(route),
                )
        else:
            if not _policy_rail_enabled(policy_mgr, "circle_transfer", agent.wallet_id):
                raise HTTPException(
                    status_code=400, detail="Circle transfer rail is disabled by policy"
                )
            if not _server_rail_enabled(client, "circle_transfer"):
                raise HTTPException(
                    status_code=400, detail="Circle transfer rail is disabled by server config"
                )

        result = await client.confirm_payment_intent(intent_id)

        return PayResponse(
            success=result.success,
            transaction_id=result.transaction_id,
            blockchain_tx=result.blockchain_tx,
            amount=_fmt_amount(result.amount),
            recipient=result.recipient,
            status=result.status.value
            if result.status and hasattr(result.status, "value")
            else (str(result.status) if result.status else "failed"),
            method=_public_payment_method(result.recipient, result.method),
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


@router.get("/confirmations/{confirmation_id}")
async def get_confirmation(
    confirmation_id: str,
    _: None = Depends(require_owner),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    store = ConfirmationStore(client._storage)
    record = await store.get(confirmation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    return record


@router.post("/confirmations/{confirmation_id}/approve")
async def approve_confirmation(
    confirmation_id: str,
    _: None = Depends(require_owner),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    store = ConfirmationStore(client._storage)
    record = await store.approve(confirmation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    return record


@router.post("/confirmations/{confirmation_id}/deny")
async def deny_confirmation(
    confirmation_id: str,
    _: None = Depends(require_owner),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    store = ConfirmationStore(client._storage)
    record = await store.deny(confirmation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    return record


@router.get("/can-pay", response_model=CanPayResponse)
async def can_pay(
    recipient: str,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    is_valid = policy_mgr.is_valid_recipient(recipient, agent.wallet_id)
    if not is_valid:
        return CanPayResponse(can_pay=False, reason="Recipient not allowed by policy")
    if not recipient.startswith("http"):
        if not _policy_rail_enabled(policy_mgr, "circle_transfer", agent.wallet_id):
            return CanPayResponse(
                can_pay=False, reason="Circle transfer rail is disabled by policy"
            )
        if not _server_rail_enabled(client, "circle_transfer"):
            return CanPayResponse(
                can_pay=False, reason="Circle transfer rail is disabled by server config"
            )
        return CanPayResponse(can_pay=True)

    if not _policy_rail_enabled(policy_mgr, "x402", agent.wallet_id):
        return CanPayResponse(can_pay=False, reason="x402 rail is disabled by policy")
    if not _server_rail_enabled(client, "x402"):
        return CanPayResponse(can_pay=False, reason="x402 payments are disabled by server config")

    inspection = await _inspect_x402_target(
        client=client,
        wallet_id=agent.wallet_id,
        url=recipient,
        allow_gateway=_policy_rail_enabled(policy_mgr, "x402", agent.wallet_id)
        and _server_rail_enabled(client, "gateway"),
        allow_x402_exact=_policy_rail_enabled(policy_mgr, "x402", agent.wallet_id)
        and _server_rail_enabled(client, "x402_exact"),
    )
    if not inspection.get("ok"):
        return CanPayResponse(can_pay=False, reason=str(inspection.get("reason")))
    if not inspection.get("requires_payment"):
        return CanPayResponse(can_pay=True)
    selected_kind = inspection.get("selected_kind")
    if selected_kind is None:
        return CanPayResponse(
            can_pay=False,
            reason=str(
                inspection.get("reason")
                or "Seller does not advertise a buyer-supported x402 payment kind"
            ),
        )
    selected_route = inspection.get("selected_route")
    if _rail_for_selected_route(selected_route) is None:
        return CanPayResponse(
            can_pay=False, reason="Seller selected an unsupported x402 payment route"
        )
    if inspection.get("selected_route") == "nanopayment" and not inspection.get("gateway_ready"):
        return CanPayResponse(can_pay=False, reason=str(inspection.get("gateway_reason") or ""))
    return CanPayResponse(can_pay=True)


@router.get("/wallets", response_model=ListWalletsResponse)
async def list_wallets(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    wallet_mgr: WalletManager = Depends(get_wallet_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    is_pending = agent.wallet_id.startswith("pending-")
    address = await wallet_mgr.get_wallet_address(agent.wallet_id)

    wallet_cfg = policy_mgr.get_wallet_config(agent.wallet_id)
    address = address or wallet_cfg.get("gateway_eoa_address") or _client_signer_address(client)
    alias = wallet_cfg.get("alias") or agent.wallet_id.replace("pending-", "")

    policy = policy_mgr.get_policy()

    # Send a mock policy block for the CLI display
    # We check for to_dict or just use empty dict
    policy_dict = {}
    if hasattr(policy, "to_dict"):
        policy_dict = policy.to_dict()

    wallets = [
        WalletInfo(
            alias=alias,
            wallet_id=agent.wallet_id,
            address=address or ("INITIALIZING..." if is_pending else "NONE"),
            fund_address=address,
            policy=policy_dict,
        )
    ]

    return ListWalletsResponse(wallets=wallets)


@router.post("/x402/inspect", response_model=X402InspectResponse)
async def x402_inspect(
    request: X402InspectRequest,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    policy_mgr: PolicyManager = Depends(get_policy_manager),
    client: OmniClaw = Depends(get_omniclaw_client),
):
    """Inspect an x402 endpoint and report which buyer route OmniClaw would use."""
    if agent.wallet_id.startswith("pending-"):
        raise HTTPException(
            status_code=425,
            detail="Wallet is currently initializing. Please try again in a few seconds.",
        )

    if not policy_mgr.is_valid_recipient(request.url, agent.wallet_id):
        return X402InspectResponse(
            url=request.url,
            requires_payment=False,
            buyer_ready=False,
            reason="Recipient not allowed by policy",
            router_detected_route="transfer",
        )

    if not _policy_rail_enabled(policy_mgr, "x402", agent.wallet_id):
        return X402InspectResponse(
            url=request.url,
            requires_payment=False,
            buyer_ready=False,
            reason="x402 rail is disabled by policy",
            router_detected_route="x402",
        )
    if not _server_rail_enabled(client, "x402"):
        return X402InspectResponse(
            url=request.url,
            requires_payment=False,
            buyer_ready=False,
            reason="x402 payments are disabled by server config",
            router_detected_route="x402",
        )

    inspection = await _inspect_x402_target(
        client=client,
        wallet_id=agent.wallet_id,
        url=request.url,
        method=request.method,
        headers=request.headers,
        body=request.body,
        allow_gateway=_policy_rail_enabled(policy_mgr, "x402", agent.wallet_id)
        and _server_rail_enabled(client, "gateway"),
        allow_x402_exact=_policy_rail_enabled(policy_mgr, "x402", agent.wallet_id)
        and _server_rail_enabled(client, "x402_exact"),
    )
    if not inspection.get("ok"):
        return X402InspectResponse(
            url=request.url,
            requires_payment=False,
            buyer_ready=False,
            reason=str(inspection.get("reason")),
        )

    if not inspection.get("requires_payment"):
        return X402InspectResponse(
            url=request.url,
            requires_payment=False,
            buyer_ready=True,
            reason=str(inspection.get("reason")),
            router_detected_route=inspection.get("router_detected_route"),
            selected_route=None,
            payment_source=None,
        )

    x402_adapter = inspection["x402_adapter"]
    selected_kind = inspection.get("selected_kind")
    selected_route = inspection.get("selected_route")
    payment_source = inspection.get("payment_source")
    seller_accepts = inspection.get("seller_accepts") or []

    buyer_address = _client_signer_address(client)

    gateway_available_balance = inspection.get("gateway_available_balance")
    buyer_ready = False
    reason: str | None = None

    if selected_kind is None:
        reason = "Seller does not advertise a buyer-supported x402 payment kind"
    elif _x402_selected_amount_exceeds_cap(selected_kind, request.amount):
        reason = f"x402 price {selected_kind.get_amount_usdc()} exceeds max amount {request.amount}"
    elif _rail_for_selected_route(selected_route) is None:
        reason = "Seller selected an unsupported x402 payment route"
    elif (selected_rail := _rail_for_selected_route(selected_route)) and not _policy_rail_enabled(
        policy_mgr, selected_rail, agent.wallet_id
    ):
        reason = f"Payment rail '{selected_rail}' is disabled by policy"
    elif selected_route in {"nanopayment", "x402"} and not _server_x402_route_enabled(
        client, selected_route
    ):
        reason = _server_x402_route_disabled_reason(selected_route)
    elif selected_route == "nanopayment":
        buyer_ready = bool(inspection.get("gateway_ready"))
        reason = str(inspection.get("gateway_reason") or "")
    else:
        sim_result = await x402_adapter.simulate(
            wallet_id=agent.wallet_id,
            recipient=request.url,
            amount=selected_kind.get_amount_usdc(),
            method=request.method,
            request_body=request.body,
            request_headers=request.headers,
        )
        buyer_ready = bool(sim_result.get("would_succeed"))
        reason = sim_result.get("reason")

    return X402InspectResponse(
        url=request.url,
        requires_payment=True,
        buyer_ready=buyer_ready,
        reason=reason,
        router_detected_route=_public_x402_route(inspection.get("router_detected_route")),
        selected_route=_public_x402_route(selected_route),
        payment_source=payment_source,
        buyer_address=buyer_address,
        gateway_available_balance=gateway_available_balance,
        selected_scheme=selected_kind.scheme if selected_kind else None,
        selected_network=selected_kind.network if selected_kind else None,
        selected_amount_atomic=selected_kind.amount_atomic if selected_kind else None,
        selected_amount_usdc=str(selected_kind.get_amount_usdc()) if selected_kind else None,
        selected_pay_to=selected_kind.recipient if selected_kind else None,
        seller_accepts=seller_accepts,
    )
