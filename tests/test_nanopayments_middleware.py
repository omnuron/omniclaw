"""
Tests for GatewayMiddleware (Phase 7: seller-side payment gate).

Tests verify:
- 402 response structure (x402 v2 spec)
- maxTimeoutSeconds is 345600
- extra.name is "GatewayWalletBatched"
- parse_price handles all formats
- Payment handling
"""

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from omniclaw.protocols.nanopayments import (
    MAX_TIMEOUT_SECONDS,
    X402_VERSION,
)
from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
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
    PaymentRequirementsExtra,
    PaymentRequirementsKind,
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

    @pytest.mark.asyncio
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

    async def test_402_body_has_max_timeout(self):
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

    @pytest.mark.asyncio
    async def test_non_circle_facilitator_advertises_standard_exact(self):
        facilitator = MagicMock()
        facilitator.name = "coinbase"

        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
            facilitator=facilitator,
        )

        body = await middleware._build_402_response("$0.001")

        for accept in body["accepts"]:
            assert accept["scheme"] == "exact"
            assert "extra" not in accept

    async def test_external_facilitator_can_create_accepts(self):
        facilitator = AsyncMock()
        facilitator.name = "thirdweb"
        facilitator.create_accepts.return_value = [
            {
                "scheme": "exact",
                "network": "eip155:84532",
                "amount": "10000",
                "payTo": "0x" + "b" * 40,
                "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
            }
        ]
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=None,
            facilitator=facilitator,
        )

        body = await middleware._build_402_response(
            "$0.01",
            resource_url="https://seller.example.com/compute",
            method="GET",
        )

        facilitator.create_accepts.assert_awaited_once_with(
            resource_url="https://seller.example.com/compute",
            method="GET",
            price="$0.01",
            server_wallet_address="0x" + "a" * 40,
        )
        assert body["x402Version"] == 2
        assert body["accepts"][0]["network"] == "eip155:84532"

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
    def test_payment_signature_header_includes_accepted_requirements(self):
        """Buyer retry header must include x402 v2 accepted requirements."""
        authorization = EIP3009Authorization.create(
            from_address="0x" + "a" * 40,
            to="0x" + "b" * 40,
            value="440",
            valid_before=9999999999,
            nonce="0x" + "c" * 64,
        )
        payload = PaymentPayload(
            x402_version=2,
            scheme="exact",
            network="eip155:11155111",
            payload=PaymentPayloadInner(
                signature="0x" + "d" * 130,
                authorization=authorization,
            ),
        )
        accepted = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:11155111",
            asset="0x1c7d4b196cb0c7b01d743fbc6116a902379c7238",
            amount="440",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract="0x" + "e" * 40,
            ),
        )

        sig_header = NanopaymentAdapter._encode_payment_signature_header(payload, accepted)
        decoded = json.loads(base64.b64decode(sig_header))

        assert decoded["x402Version"] == 2
        assert decoded["scheme"] == "exact"
        assert decoded["network"] == "eip155:11155111"
        assert decoded["accepted"]["scheme"] == "exact"
        assert decoded["accepted"]["network"] == "eip155:11155111"
        assert decoded["accepted"]["amount"] == "440"
        assert decoded["accepted"]["extra"]["name"] == "GatewayWalletBatched"

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
            accepted=PaymentRequirementsKind(
                scheme="exact",
                network="eip155:5042002",
                asset="0xUsdcArcTestnet",
                amount="1000",
                max_timeout_seconds=345600,
                pay_to="0x" + "a" * 40,
                extra=PaymentRequirementsExtra(
                    name="GatewayWalletBatched",
                    version="1",
                    verifying_contract="0x" + "c" * 40,
                ),
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
    async def test_handle_rejects_v2_payment_without_accepted(self):
        """OmniClaw seller must reject malformed x402 v2 retry payloads."""
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
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await middleware.handle({"payment-signature": sig_header}, "$0.001")

        assert "Missing accepted requirements" in exc_info.value.detail["error"]

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

    @pytest.mark.asyncio
    async def test_non_circle_facilitator_settle_uses_standard_exact_requirements(self):
        facilitator = AsyncMock()
        facilitator.name = "coinbase"
        facilitator.settle.return_value = MagicMock(
            success=True,
            transaction="fac-123",
            payer="0x" + "a" * 40,
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
            accepted=PaymentRequirementsKind(
                scheme="exact",
                network="eip155:5042002",
                asset="0xUsdcArcTestnet",
                amount="1000",
                max_timeout_seconds=345600,
                pay_to="0x" + "a" * 40,
                extra=PaymentRequirementsExtra(
                    name="",
                    version="",
                    verifying_contract="",
                ),
            ),
        )
        sig_header = base64.b64encode(json.dumps(payload.to_dict()).encode()).decode()

        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
            facilitator=facilitator,
        )

        info = await middleware.handle({"payment-signature": sig_header}, "$0.001")

        assert info.verified is True
        assert info.transaction == "fac-123"
        facilitator.settle.assert_awaited_once()
        _, req_dict = facilitator.settle.await_args.args
        accepted = req_dict["accepts"][0]
        assert accepted["scheme"] == "exact"
        assert "extra" not in accepted
