"""
Tests for GatewayMiddleware (Phase 7: seller-side payment gate).

Tests verify:
- 402 response structure (x402 v2 spec)
- maxTimeoutSeconds is 345600
- extra.name is "GatewayWalletBatched"
- parse_price handles all formats
- Payment handling
"""

import json
import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from omniclaw.protocols.nanopayments import (
    MAX_TIMEOUT_SECONDS,
    X402_VERSION,
)
from omniclaw.protocols.nanopayments.client import NanopaymentClient
from omniclaw.protocols.nanopayments.exceptions import InvalidPriceError
from omniclaw.protocols.nanopayments.middleware import (
    GatewayMiddleware,
    PaymentRequiredHTTPError,
    parse_price,
)
from omniclaw.protocols.nanopayments.types import (
    EIP3009Authorization,
    PaymentPayload,
    PaymentPayloadInner,
    SupportedKind,
)


# =============================================================================
# PARSE_PRICE TESTS
# =============================================================================


class TestParsePrice:
    def test_dollar_sign_removed(self):
        assert parse_price("$0.001") == 1000
        assert parse_price("$1") == 1_000_000
        assert parse_price("$0.000001") == 1

    def test_decimal_without_dollar(self):
        assert parse_price("0.001") == 1000
        assert parse_price("1.00") == 1_000_000
        assert parse_price("0.5") == 500_000

    def test_integer_plain_dollars(self):
        """Integer <= 1M is treated as whole dollars."""
        assert parse_price("100") == 100_000_000  # $100
        assert parse_price("1") == 1_000_000  # $1

    def test_integer_atomic_units(self):
        """Integer > 1M is treated as atomic units."""
        assert parse_price("1000000") == 1_000_000  # 1M atomic = $1

    def test_whitespace_stripped(self):
        assert parse_price("  $0.001  ") == 1000
        assert parse_price("  0.001  ") == 1000

    def test_large_dollar_amount(self):
        assert parse_price("$100") == 100_000_000
        assert parse_price("$999.99") == 999_990_000

    def test_invalid_price_raises(self):
        with pytest.raises(InvalidPriceError):
            parse_price("not a price")
        with pytest.raises(InvalidPriceError):
            parse_price("")
        with pytest.raises(InvalidPriceError):
            parse_price(None)  # type: ignore

    def test_edge_cases(self):
        assert parse_price("$0.000001") == 1  # minimum USDC
        assert parse_price("0") == 0


# =============================================================================
# GATEWAY MIDDLEWARE TESTS
# =============================================================================


def _make_kinds() -> list[SupportedKind]:
    """Real SupportedKind objects for testing."""
    return [
        SupportedKind(
            x402_version=2,
            scheme="exact",
            network="eip155:5042002",
            extra={
                "verifyingContract": "0x" + "c" * 40,
                "usdcAddress": "0xUsdcArcTestnet",
            },
        ),
        SupportedKind(
            x402_version=2,
            scheme="exact",
            network="eip155:1",
            extra={
                "verifyingContract": "0x" + "d" * 40,
                "usdcAddress": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            },
        ),
    ]


def _make_client() -> MagicMock:
    """NanopaymentClient mock."""
    mock = MagicMock(spec=NanopaymentClient)
    mock.get_supported = AsyncMock(return_value=_make_kinds())
    return mock


class TestGatewayMiddleware:
    """Tests for GatewayMiddleware 402 response structure."""

    async def test_402_body_has_correct_x402_version(self):
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )
        body = await middleware._build_402_response("$0.001")
        assert body["x402Version"] == X402_VERSION

    async def test_402_body_has_correct_scheme(self):
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )
        body = await middleware._build_402_response("$0.001")
        for accept in body["accepts"]:
            assert accept["scheme"] == "exact"

    async def test_402_body_max_timeout_is_345600(self):
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )
        body = await middleware._build_402_response("$0.001")
        for accept in body["accepts"]:
            assert accept["maxTimeoutSeconds"] == MAX_TIMEOUT_SECONDS == 345600

    async def test_402_body_has_gateway_wallet_batched(self):
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )
        body = await middleware._build_402_response("$0.001")
        for accept in body["accepts"]:
            assert accept["extra"]["name"] == "GatewayWalletBatched"

    async def test_402_body_has_verifying_contract(self):
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )
        body = await middleware._build_402_response("$0.001")
        for accept in body["accepts"]:
            assert "verifyingContract" in accept["extra"]
            assert accept["extra"]["verifyingContract"].startswith("0x")

    async def test_402_body_has_correct_amount(self):
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )
        body = await middleware._build_402_response("$0.001")
        for accept in body["accepts"]:
            assert accept["amount"] == "1000"  # 0.001 * 1_000_000

    async def test_402_body_pay_to_is_seller_address(self):
        seller = "0x" + "a" * 40
        middleware = GatewayMiddleware(
            seller_address=seller,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )
        body = await middleware._build_402_response("$0.001")
        for accept in body["accepts"]:
            assert accept["payTo"] == seller

    async def test_402_body_one_entry_per_network(self):
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )
        body = await middleware._build_402_response("$1.00")
        assert len(body["accepts"]) == 2

    async def test_payment_required_header_is_valid_base64(self):
        """PAYMENT-REQUIRED header must be valid base64."""
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )
        body = await middleware._build_402_response("$0.001")
        header = middleware._encode_requirements(body)

        decoded = base64.b64decode(header)
        parsed = json.loads(decoded)
        assert parsed["x402Version"] == 2


# =============================================================================
# HANDLE TESTS
# =============================================================================


class TestHandle:
    @pytest.mark.asyncio
    async def test_handle_without_payment_raises_402(self):
        """Request without PAYMENT-SIGNATURE header returns 402."""
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await middleware.handle({}, "$0.001")

        assert exc_info.value.status_code == 402
        assert "PAYMENT-REQUIRED" in exc_info.value.headers

    @pytest.mark.asyncio
    async def test_handle_with_valid_payment_returns_payment_info(self):
        """Valid PAYMENT-SIGNATURE returns PaymentInfo."""
        mock_client = _make_client()
        mock_client.settle = AsyncMock(
            return_value=MagicMock(
                success=True,
                transaction="batch-123",
                payer="0x" + "a" * 40,
            )
        )

        authorization = EIP3009Authorization.create(
            from_address="0x" + "a" * 40,
            to="0x" + "a" * 40,
            value="1000",
            valid_before=9999999999,
            nonce="0x" + "b" * 64,
        )
        payload = PaymentPayload(
            x402_version=2,
            scheme="exact",
            network="eip155:5042002",
            payload=PaymentPayloadInner(
                signature="0x" + "c" * 130,
                authorization=authorization,
            ),
        )

        sig_header = base64.b64encode(json.dumps(payload.to_dict()).encode()).decode()

        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=mock_client,
            supported_kinds=_make_kinds(),
        )

        info = await middleware.handle(
            {"payment-signature": sig_header},
            "$0.001",
        )

        assert info.verified is True
        assert info.transaction == "batch-123"

    @pytest.mark.asyncio
    async def test_handle_with_invalid_signature_raises_402(self):
        """Invalid PAYMENT-SIGNATURE header returns 402."""
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await middleware.handle(
                {"payment-signature": "not-valid-base64!!!"},
                "$0.001",
            )

        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_handle_with_missing_payment_and_no_networks_returns_empty(self):
        """No supported networks: empty accepts array."""
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=[],  # No networks
        )

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await middleware.handle({}, "$0.001")

        body = exc_info.value.detail
        assert body["x402Version"] == 2
        assert body["accepts"] == []
