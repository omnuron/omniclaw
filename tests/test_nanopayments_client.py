"""Tests for nanopayment Gateway API client configuration."""

import base64
import json
import os
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter, NanopaymentProtocolAdapter
from omniclaw.protocols.nanopayments.client import NanopaymentClient
from omniclaw.protocols.nanopayments.exceptions import GatewayAPIError
from omniclaw.protocols.nanopayments.types import NanopaymentResult
from omniclaw.protocols.x402 import AcceptedPaymentKind


def test_nanopayment_client_allows_no_circle_api_key() -> None:
    with patch.dict(os.environ, {}, clear=True):
        client = NanopaymentClient(api_key=None)

    assert client.has_api_key is False


@pytest.mark.asyncio
async def test_gateway_api_helper_calls_require_circle_api_key() -> None:
    with patch.dict(os.environ, {}, clear=True):
        client = NanopaymentClient(api_key=None)

    with pytest.raises(GatewayAPIError, match="requires CIRCLE_API_KEY"):
        await client.check_balance(
            address="0x0000000000000000000000000000000000000001",
            network="eip155:5042002",
        )


@pytest.mark.asyncio
async def test_x402_gateway_url_payment_without_circle_api_uses_onchain_balance() -> None:
    url = "http://127.0.0.1:4023/compute?size=20"
    calls: list[httpx.Request] = []

    payment_required = {
        "x402Version": 2,
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:5042002",
                "asset": "0x3600000000000000000000000000000000000000",
                "amount": "1000",
                "payTo": "0x4cfdD69a2A89B91f3c12588085f098C268Ea8631",
                "maxTimeoutSeconds": 604900,
                "extra": {
                    "name": "GatewayWalletBatched",
                    "version": "1",
                    "verifyingContract": "0x0077777d7EBA4688BDeF3E311b846F25870A19B9",
                    "minValiditySeconds": 604800,
                    "assets": [
                        {
                            "symbol": "USDC",
                            "address": "0x3600000000000000000000000000000000000000",
                            "decimals": 6,
                        }
                    ],
                },
            }
        ],
    }
    payment_required_header = base64.b64encode(json.dumps(payment_required).encode()).decode()
    payment_response_header = base64.b64encode(
        json.dumps({"success": True, "transaction": "0xsettled"}).encode()
    ).decode()

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "POST"
        assert request.headers.get("x-trace-id") == "abc123"
        assert request.content == b'{"input":20}'
        if "PAYMENT-SIGNATURE" not in request.headers:
            return httpx.Response(
                402,
                headers={"PAYMENT-REQUIRED": payment_required_header},
                json={
                    "resource": {
                        "url": url,
                        "description": "compute",
                        "mimeType": "application/json",
                    }
                },
            )
        payload = json.loads(base64.b64decode(request.headers["PAYMENT-SIGNATURE"]))
        assert payload["accepted"]["extra"]["name"] == "GatewayWalletBatched"
        assert (
            payload["accepted"]["extra"]["verifyingContract"]
            == payment_required["accepts"][0]["extra"]["verifyingContract"]
        )
        return httpx.Response(
            200,
            headers={"PAYMENT-RESPONSE": payment_response_header},
            json={"ok": True},
        )

    with patch.dict(os.environ, {}, clear=True):
        client = NanopaymentClient(api_key=None)
    client.check_balance = AsyncMock(side_effect=AssertionError("Circle API balance not used"))  # type: ignore[method-assign]
    client.get_supported = AsyncMock(side_effect=AssertionError("Circle API metadata not used"))  # type: ignore[method-assign]

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = NanopaymentAdapter.from_private_key(
        private_key="0x59c6995e998f97a5a0044976f7d4d0cbafc4b9d96ec4f38f5dc7065f6a7e0c72",
        nanopayment_client=client,
        http_client=http_client,
        network="eip155:5042002",
        rpc_url="http://127.0.0.1:8545",
    )
    adapter._get_onchain_available_atomic = AsyncMock(return_value=10_000)  # type: ignore[method-assign]

    try:
        result = await adapter.pay_x402_url(
            url,
            method="POST",
            headers={"x-trace-id": "abc123"},
            body='{"input":20}',
            max_amount_usdc="0.001",
        )
    finally:
        await http_client.aclose()

    assert result.success is True
    assert result.transaction == "0xsettled"
    assert result.amount_atomic == "1000"
    assert len(calls) == 2
    client.check_balance.assert_not_awaited()
    client.get_supported.assert_not_awaited()
    adapter._get_onchain_available_atomic.assert_awaited_once()


@pytest.mark.asyncio
async def test_protocol_adapter_forwards_x402_request_details() -> None:
    nano_result = NanopaymentResult(
        success=True,
        payer="0xpayer",
        seller="0xseller",
        transaction="batch-1",
        amount_usdc="0.001",
        amount_atomic="1000",
        network="eip155:5042002",
        response_data={"ok": True},
        is_nanopayment=True,
    )
    adapter = SimpleNamespace(
        pay_x402_url=AsyncMock(return_value=nano_result),
        _strict_settlement=False,
    )
    protocol = NanopaymentProtocolAdapter(adapter)  # type: ignore[arg-type]

    result = await protocol.execute(
        wallet_id="wallet-1",
        recipient="https://seller.example/compute",
        amount=Decimal("0.001"),
        method="POST",
        request_headers={"x-trace-id": "abc123"},
        request_body='{"input":20}',
    )

    adapter.pay_x402_url.assert_awaited_once_with(
        url="https://seller.example/compute",
        method="POST",
        headers={"x-trace-id": "abc123"},
        body='{"input":20}',
        max_amount_usdc="0.001",
    )
    assert result.success is True
    assert result.metadata["payment_source"] == "gateway_balance"
    assert result.metadata["execution_route"] == "GatewayWalletBatched"
    assert result.metadata["facilitator"] == "GatewayWalletBatched"


@pytest.mark.asyncio
async def test_onchain_balance_accepts_x402_accepted_kind_shape() -> None:
    with patch.dict(os.environ, {}, clear=True):
        client = NanopaymentClient(api_key=None)
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )
    adapter = NanopaymentAdapter.from_private_key(
        private_key="0x59c6995e998f97a5a0044976f7d4d0cbafc4b9d96ec4f38f5dc7065f6a7e0c72",
        nanopayment_client=client,
        http_client=http_client,
        network="eip155:5042002",
        rpc_url="http://127.0.0.1:8545",
    )
    adapter._get_onchain_available_atomic = AsyncMock(return_value=1000)  # type: ignore[method-assign]
    kind = AcceptedPaymentKind(
        scheme="exact",
        network="eip155:5042002",
        amount_atomic="1000",
        recipient="0x4cfdD69a2A89B91f3c12588085f098C268Ea8631",
        asset="0x3600000000000000000000000000000000000000",
        extra={
            "name": "GatewayWalletBatched",
            "version": "1",
            "verifyingContract": "0x0077777d7EBA4688BDeF3E311b846F25870A19B9",
        },
    )

    try:
        balance = await adapter.get_onchain_available_balance(kind)
    finally:
        await http_client.aclose()

    assert balance.available == 1000


@pytest.mark.asyncio
async def test_direct_address_nanopayment_requires_circle_api_helper() -> None:
    with patch.dict(os.environ, {}, clear=True):
        client = NanopaymentClient(api_key=None)
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )
    adapter = NanopaymentAdapter.from_private_key(
        private_key="0x59c6995e998f97a5a0044976f7d4d0cbafc4b9d96ec4f38f5dc7065f6a7e0c72",
        nanopayment_client=client,
        http_client=http_client,
        network="eip155:5042002",
        rpc_url="http://127.0.0.1:8545",
    )
    protocol_adapter = NanopaymentProtocolAdapter(adapter, micro_threshold_usdc="1.00")

    try:
        assert (
            protocol_adapter.supports(
                "0x4cfdD69a2A89B91f3c12588085f098C268Ea8631",
                amount="0.01",
            )
            is False
        )
    finally:
        await http_client.aclose()
