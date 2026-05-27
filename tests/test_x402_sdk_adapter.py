from __future__ import annotations

import base64
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from omniclaw.agent.models import PayRequest
from omniclaw.agent.routes import _choose_x402_route, pay
from omniclaw.core.types import Network, PaymentMethod, PaymentResult, PaymentStatus
from omniclaw.protocols.x402 import X402Adapter


def _make_payment_required_header(url: str) -> str:
    from x402.http import encode_payment_required_header
    from x402.schemas import PaymentRequired, PaymentRequirements, ResourceInfo

    payment_required = PaymentRequired(
        error="Payment Required",
        resource=ResourceInfo(url=url, description="paid resource", mime_type="application/json"),
        accepts=[
            PaymentRequirements(
                scheme="exact",
                network="eip155:84532",
                asset="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                amount="250000",
                pay_to="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                max_timeout_seconds=300,
                extra={"name": "USD Coin", "version": "2"},
            )
        ],
    )
    return encode_payment_required_header(payment_required)


def _make_payment_response_header(*, success: bool, error_reason: str | None = None) -> str:
    from x402.http import encode_payment_response_header
    from x402.schemas import SettleResponse

    settle_response = SettleResponse(
        success=success,
        error_reason=error_reason,
        transaction="0xsettlement",
        network="eip155:84532",
        payer="0xa6b9b6244A5AD5FC2eF2BEB67ce04b75A0dB91D7",
    )
    return encode_payment_response_header(settle_response)


def _make_adapter(transport: httpx.MockTransport) -> X402Adapter:
    config = SimpleNamespace(
        nanopayments_private_key="0x59c6995e998f97a5a0044976f7d4d0cbafc4b9d96ec4f38f5dc7065f6a7e0c72",
        payment_strict_settlement=True,
    )
    wallet_service = SimpleNamespace(
        get_wallet=lambda wallet_id: SimpleNamespace(blockchain=Network.BASE_SEPOLIA.value)
    )
    http_client = httpx.AsyncClient(transport=transport, timeout=5.0)
    return X402Adapter(config=config, wallet_service=wallet_service, http_client=http_client)


@pytest.mark.asyncio
async def test_execute_uses_sdk_payment_signature_and_settle_response():
    url = "https://seller.example/compute"
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "PAYMENT-SIGNATURE" not in request.headers:
            return httpx.Response(
                402,
                headers={"PAYMENT-REQUIRED": _make_payment_required_header(url)},
                json={"error": "Payment Required"},
            )

        assert request.headers["PAYMENT-SIGNATURE"]
        payment_payload = json.loads(base64.b64decode(request.headers["PAYMENT-SIGNATURE"]))
        assert payment_payload["x402Version"] == 2
        assert payment_payload["accepted"]["scheme"] == "exact"
        assert payment_payload["accepted"]["network"] == "eip155:84532"
        assert payment_payload["accepted"]["amount"] == "250000"
        assert payment_payload["accepted"]["payTo"] == "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
        return httpx.Response(
            200,
            headers={"PAYMENT-RESPONSE": _make_payment_response_header(success=True)},
            json={"ok": True, "job": "done"},
        )

    adapter = _make_adapter(httpx.MockTransport(handler))
    result = await adapter.execute(
        wallet_id="buyer-wallet",
        recipient=url,
        amount=Decimal("0.25"),
        method="POST",
        request_body=b'{"task":"prime-count"}',
        request_headers={"x-trace-id": "abc123"},
    )

    assert result.success is True
    assert result.method == PaymentMethod.X402
    assert result.status == PaymentStatus.SETTLED
    assert result.transaction_id == "0xsettlement"
    assert result.blockchain_tx == "0xsettlement"
    assert result.amount == Decimal("0.25")
    assert result.resource_data == {"ok": True, "job": "done"}
    assert len(calls) == 2
    assert calls[0].headers["x-trace-id"] == "abc123"
    assert calls[1].headers["x-trace-id"] == "abc123"
    assert calls[1].method == "POST"


def test_ensure_v2_payload_has_accepted_patches_missing_sdk_field():
    from x402.schemas import PaymentRequired, PaymentRequirements, ResourceInfo

    selected = PaymentRequirements(
        scheme="exact",
        network="eip155:84532",
        asset="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        amount="250000",
        pay_to="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
        max_timeout_seconds=300,
        extra={"name": "USD Coin", "version": "2"},
    )
    payment_required = PaymentRequired(
        error="Payment Required",
        resource=ResourceInfo(
            url="https://seller.example/compute",
            description="paid resource",
            mime_type="application/json",
        ),
        accepts=[selected],
    )
    incomplete_payload = SimpleNamespace(
        x402_version=2,
        payload={
            "authorization": {
                "from": "0xCa7fc646D249442404e43e9ce3B9015241ABcCEE",
                "to": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "value": "250000",
                "validAfter": "1776868697",
                "validBefore": "1776869597",
                "nonce": "0x1cd5a89daa51bb8b7f113f02dd5a7c4b833e5a17e5b653d41e09eef8c1189524",
            },
            "signature": "0xsignature",
        },
    )

    patched = X402Adapter._ensure_v2_payload_has_accepted(
        payment_payload=incomplete_payload,
        selected_requirements=selected,
        payment_required=payment_required,
    )

    dumped = patched.model_dump(by_alias=True)
    assert dumped["accepted"]["scheme"] == "exact"
    assert dumped["accepted"]["network"] == "eip155:84532"
    assert dumped["accepted"]["amount"] == "250000"
    assert dumped["resource"]["url"] == "https://seller.example/compute"


@pytest.mark.asyncio
async def test_execute_returns_failed_final_when_seller_rejects_payment():
    url = "https://seller.example/compute"

    async def handler(request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" not in request.headers:
            return httpx.Response(
                402,
                headers={"PAYMENT-REQUIRED": _make_payment_required_header(url)},
                json={"error": "Payment Required"},
            )

        return httpx.Response(
            402,
            headers={
                "PAYMENT-RESPONSE": _make_payment_response_header(
                    success=False,
                    error_reason="insufficient balance",
                )
            },
            json={"error": "insufficient balance"},
        )

    adapter = _make_adapter(httpx.MockTransport(handler))
    result = await adapter.execute(
        wallet_id="buyer-wallet",
        recipient=url,
        amount=Decimal("0.25"),
    )

    assert result.success is False
    assert result.status == PaymentStatus.FAILED_FINAL
    assert "insufficient balance" in (result.error or "")
    assert result.transaction_id == "0xsettlement"


@pytest.mark.asyncio
async def test_simulate_reports_insufficient_direct_wallet_balance(
    monkeypatch: pytest.MonkeyPatch,
):
    url = "https://seller.example/compute"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            headers={"PAYMENT-REQUIRED": _make_payment_required_header(url)},
            json={"error": "Payment Required"},
        )

    adapter = _make_adapter(httpx.MockTransport(handler))
    monkeypatch.setattr(
        adapter,
        "_check_direct_exact_balance",
        lambda selected_requirements: {
            "balance_check": "failed",
            "buyer_address": "0xa6b9b6244A5AD5FC2eF2BEB67ce04b75A0dB91D7",
            "direct_wallet_balance_atomic": "150000",
            "direct_wallet_balance": "0.15",
            "direct_wallet_required_atomic": "250000",
            "direct_wallet_required": "0.25",
            "direct_wallet_has_enough": False,
        },
    )

    result = await adapter.simulate(
        wallet_id="buyer-wallet",
        recipient=url,
        amount=Decimal("0.25"),
    )

    assert result["would_succeed"] is False
    assert result["balance_check"] == "failed"
    assert result["direct_wallet_balance"] == "0.15"
    assert result["direct_wallet_required"] == "0.25"
    assert "needs 0.25 USDC" in result["reason"]


@pytest.mark.asyncio
async def test_pay_route_uses_seller_declared_amount_for_url_payments(
    monkeypatch: pytest.MonkeyPatch,
):
    payment_result = PaymentResult(
        success=True,
        transaction_id="tx-2",
        blockchain_tx="0xdef",
        amount=Decimal("0.25"),
        recipient="https://seller.example/compute",
        method=PaymentMethod.X402,
        status=PaymentStatus.SETTLED,
        resource_data={"ok": True},
        metadata={},
    )
    client = SimpleNamespace(
        config=SimpleNamespace(enable_gateway=False, enable_x402_exact=True),
        pay=AsyncMock(return_value=payment_result),
    )
    selected_kind = SimpleNamespace(get_amount_usdc=lambda: Decimal("0.25"))

    async def fake_inspect_x402_target(**kwargs):
        return {
            "ok": True,
            "requires_payment": True,
            "selected_kind": selected_kind,
            "selected_route": "x402",
        }

    monkeypatch.setattr(
        "omniclaw.agent.routes._inspect_x402_target",
        fake_inspect_x402_target,
    )
    request = PayRequest(
        recipient="https://seller.example/compute",
        amount=None,
        method="POST",
        body='{"task":"prime-count"}',
        headers={"x-trace-id": "abc123"},
    )
    agent = SimpleNamespace(wallet_id="buyer-wallet")
    wallet_mgr = SimpleNamespace()
    policy_mgr = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        check_limits=lambda amount, wallet_id: (True, None),
    )

    response = await pay(
        request=request,
        agent=agent,
        wallet_mgr=wallet_mgr,
        policy_mgr=policy_mgr,
        client=client,
    )

    client.pay.assert_awaited_once_with(
        wallet_id="buyer-wallet",
        recipient="https://seller.example/compute",
        amount="0.25",
        purpose=None,
        idempotency_key=None,
        destination_chain=None,
        fee_level=None,
        check_trust=False,
        skip_guards=False,
        method="POST",
        request_body='{"task":"prime-count"}',
        request_headers={"x-trace-id": "abc123"},
        metadata={
            "method": "POST",
            "body": '{"task":"prime-count"}',
            "headers": {"x-trace-id": "abc123"},
        },
        preferred_url_route="x402",
    )
    assert response.success is True
    assert response.method == "x402"
    assert response.amount == "0.25"


@pytest.mark.asyncio
async def test_pay_route_uses_zero_amount_for_free_url(monkeypatch: pytest.MonkeyPatch):
    payment_result = PaymentResult(
        success=True,
        transaction_id=None,
        blockchain_tx=None,
        amount=Decimal("0"),
        recipient="https://seller.example/free",
        method=PaymentMethod.X402,
        status=PaymentStatus.COMPLETED,
        resource_data={"ok": True},
        metadata={"http_status": 200},
    )
    client = SimpleNamespace(
        config=SimpleNamespace(enable_gateway=False, enable_x402_exact=True),
        pay=AsyncMock(return_value=payment_result),
    )

    async def fake_inspect_x402_target(**kwargs):
        return {
            "ok": True,
            "requires_payment": False,
            "reason": "Endpoint does not currently require payment",
        }

    monkeypatch.setattr(
        "omniclaw.agent.routes._inspect_x402_target",
        fake_inspect_x402_target,
    )
    request = PayRequest(recipient="https://seller.example/free", amount=None)
    agent = SimpleNamespace(wallet_id="buyer-wallet")
    wallet_mgr = SimpleNamespace()
    policy_mgr = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        check_limits=lambda amount, wallet_id: (True, None),
    )

    response = await pay(
        request=request,
        agent=agent,
        wallet_mgr=wallet_mgr,
        policy_mgr=policy_mgr,
        client=client,
    )

    client.pay.assert_awaited_once_with(
        wallet_id="buyer-wallet",
        recipient="https://seller.example/free",
        amount="0.00",
        purpose=None,
        idempotency_key=None,
        destination_chain=None,
        fee_level=None,
        check_trust=False,
        skip_guards=False,
        method="GET",
        request_body=None,
        request_headers=None,
        metadata={"method": "GET"},
        preferred_url_route=None,
    )
    assert response.success is True
    assert response.amount == "0.00"


@pytest.mark.asyncio
async def test_choose_x402_route_prefers_exact_when_gateway_is_unfunded():
    exact_kind = SimpleNamespace(
        amount_atomic=250000,
        is_gateway_batched=False,
        get_amount_usdc=lambda: Decimal("0.25"),
    )
    gateway_kind = SimpleNamespace(
        amount_atomic=250000,
        is_gateway_batched=True,
        get_amount_usdc=lambda: Decimal("0.25"),
    )
    requirements = SimpleNamespace(
        select_preferred_kind=lambda *, prefer_gateway, source_network: (
            gateway_kind if prefer_gateway else exact_kind
        )
    )
    client = SimpleNamespace(
        _nano_adapter=object(),
        get_gateway_balance=AsyncMock(
            return_value=SimpleNamespace(
                available=0,
                formatted_available="0.00",
            )
        ),
        get_gateway_onchain_balance=AsyncMock(
            return_value=SimpleNamespace(
                available=0,
                formatted_available="0.00",
            )
        ),
    )
    x402_adapter = SimpleNamespace(
        _resolve_agent_network=lambda wallet_id, destination_chain: "eip155:84532"
    )

    route = await _choose_x402_route(
        client=client,
        wallet_id="buyer-wallet",
        x402_adapter=x402_adapter,
        requirements=requirements,
    )

    assert route["selected_route"] == "x402"
    assert route["payment_source"] == "direct_wallet"
    assert route["selected_kind"] is exact_kind
    assert route["gateway_ready"] is False
    assert route["gateway_available_balance"] == "0.00"


@pytest.mark.asyncio
async def test_choose_x402_route_keeps_gateway_when_it_is_the_only_option():
    gateway_kind = SimpleNamespace(
        amount_atomic=250000,
        is_gateway_batched=True,
        get_amount_usdc=lambda: Decimal("0.25"),
    )
    requirements = SimpleNamespace(
        select_preferred_kind=lambda *, prefer_gateway, source_network: (
            gateway_kind if prefer_gateway else None
        )
    )
    client = SimpleNamespace(
        _nano_adapter=object(),
        get_gateway_balance=AsyncMock(
            return_value=SimpleNamespace(
                available=0,
                formatted_available="0.00",
            )
        ),
        get_gateway_onchain_balance=AsyncMock(
            return_value=SimpleNamespace(
                available=0,
                formatted_available="0.00",
            )
        ),
    )
    x402_adapter = SimpleNamespace(
        _resolve_agent_network=lambda wallet_id, destination_chain: "eip155:84532"
    )

    route = await _choose_x402_route(
        client=client,
        wallet_id="buyer-wallet",
        x402_adapter=x402_adapter,
        requirements=requirements,
    )

    assert route["selected_route"] == "nanopayment"
    assert route["payment_source"] == "gateway_balance"
    assert route["selected_kind"] is gateway_kind
    assert route["gateway_ready"] is False


@pytest.mark.asyncio
async def test_choose_x402_route_uses_onchain_fallback_when_api_balance_is_stale():
    gateway_kind = SimpleNamespace(
        amount_atomic=250000,
        is_gateway_batched=True,
        get_amount_usdc=lambda: Decimal("0.25"),
    )
    requirements = SimpleNamespace(
        select_preferred_kind=lambda *, prefer_gateway, source_network: (
            gateway_kind if prefer_gateway else None
        )
    )
    client = SimpleNamespace(
        _nano_adapter=object(),
        get_gateway_balance=AsyncMock(
            return_value=SimpleNamespace(
                available=0,
                formatted_available="0.00",
            )
        ),
        get_gateway_onchain_balance=AsyncMock(
            return_value=SimpleNamespace(
                available=300000,
                formatted_available="0.30",
            )
        ),
    )
    x402_adapter = SimpleNamespace(
        _resolve_agent_network=lambda wallet_id, destination_chain: "eip155:84532"
    )

    route = await _choose_x402_route(
        client=client,
        wallet_id="buyer-wallet",
        x402_adapter=x402_adapter,
        requirements=requirements,
    )

    assert route["selected_route"] == "nanopayment"
    assert route["payment_source"] == "gateway_balance"
    assert route["selected_kind"] is gateway_kind
    assert route["gateway_ready"] is True
    assert route["gateway_available_balance"] == "0.30"
    assert (
        route["gateway_reason"]
        == "Gateway on-chain balance is sufficient (API balance appears stale)"
    )


@pytest.mark.asyncio
async def test_pay_route_inspects_url_even_when_amount_is_supplied(
    monkeypatch: pytest.MonkeyPatch,
):
    payment_result = PaymentResult(
        success=True,
        transaction_id="tx-3",
        blockchain_tx="0x987",
        amount=Decimal("0.25"),
        recipient="https://seller.example/compute",
        method=PaymentMethod.X402,
        status=PaymentStatus.SETTLED,
        resource_data={"ok": True},
        metadata={},
    )
    client = SimpleNamespace(
        config=SimpleNamespace(enable_gateway=False, enable_x402_exact=True),
        pay=AsyncMock(return_value=payment_result),
    )
    selected_kind = SimpleNamespace(get_amount_usdc=lambda: Decimal("0.25"))

    async def fake_inspect_x402_target(**kwargs):
        return {
            "ok": True,
            "requires_payment": True,
            "selected_kind": selected_kind,
            "selected_route": "x402",
        }

    monkeypatch.setattr(
        "omniclaw.agent.routes._inspect_x402_target",
        fake_inspect_x402_target,
    )
    request = PayRequest(
        recipient="https://seller.example/compute",
        amount="0.25",
        method="GET",
    )
    agent = SimpleNamespace(wallet_id="buyer-wallet")
    wallet_mgr = SimpleNamespace()
    policy_mgr = SimpleNamespace(
        is_valid_recipient=lambda recipient, wallet_id: True,
        check_limits=lambda amount, wallet_id: (True, None),
    )

    response = await pay(
        request=request,
        agent=agent,
        wallet_mgr=wallet_mgr,
        policy_mgr=policy_mgr,
        client=client,
    )

    client.pay.assert_awaited_once_with(
        wallet_id="buyer-wallet",
        recipient="https://seller.example/compute",
        amount="0.25",
        purpose=None,
        idempotency_key=None,
        destination_chain=None,
        fee_level=None,
        check_trust=False,
        skip_guards=False,
        method="GET",
        request_body=None,
        request_headers=None,
        metadata={"method": "GET"},
        preferred_url_route="x402",
    )
    assert response.success is True
    assert response.method == "x402"
