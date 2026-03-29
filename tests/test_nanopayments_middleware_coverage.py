"""
Additional tests for GatewayMiddleware to cover uncovered lines.

Covers:
- parse_price with invalid Decimal (lines 90-96)
- parse_price with plain integer fallback (lines 98-107)
- seller_address validation in __init__ (lines 138-150)
- _get_supported_kinds() (lines 161-168)
- handle() error handling for networks (lines 361-378)
- handle() settlement exception (lines 399-410)
- require() FastAPI dependency (lines 424-450)
"""

import json
import base64
from decimal import Decimal, InvalidOperation
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omniclaw.protocols.nanopayments.client import NanopaymentClient
from omniclaw.protocols.nanopayments.exceptions import (
    InvalidPriceError,
    NoNetworksAvailableError,
)
from omniclaw.protocols.nanopayments.middleware import (
    GatewayMiddleware,
    PaymentRequiredHTTPError,
    parse_price,
    NoNetworksAvailableError as MiddlewareNoNetworksAvailableError,
)
from omniclaw.protocols.nanopayments.types import (
    EIP3009Authorization,
    PaymentPayload,
    PaymentPayloadInner,
    SupportedKind,
)


# =============================================================================
# PARSE_PRICE TESTS - UNCOVERED LINES
# =============================================================================


class TestParsePriceUncovered:
    def test_invalid_decimal_raises(self):
        """Lines 90-96: Invalid Decimal raises InvalidPriceError."""
        # Test with an invalid decimal string that fails Decimal parsing
        # The code catches (ValueError, InvalidOperation, ArithmeticError)
        with pytest.raises(InvalidPriceError):
            parse_price("abc")  # Invalid decimal - not a number

        with pytest.raises(InvalidPriceError):
            parse_price("1..2")  # Multiple decimal points

        with pytest.raises(InvalidPriceError):
            parse_price("")  # Empty string after dollar removed

    def test_plain_integer_dollar_fallback(self):
        """Lines 98-107: Plain integer < 1M treated as dollars."""
        # Test that integers below 1M are multiplied by 1M
        assert parse_price("100") == 100_000_000  # $100 = 100M atomic
        assert parse_price("500") == 500_000_000
        assert parse_price("0") == 0

        # Test integers >= 1M are treated as atomic
        assert parse_price("1000000") == 1_000_000
        assert parse_price("5000000") == 5_000_000


# =============================================================================
# HELPER FUNCTIONS
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


def _make_kinds_with_missing_contracts() -> list[SupportedKind]:
    """SupportedKinds with missing contract addresses."""
    return [
        SupportedKind(
            x402_version=2,
            scheme="exact",
            network="eip155:5042002",
            extra={
                "verifyingContract": None,  # Missing
                "usdcAddress": None,  # Missing
            },
        ),
    ]


def _make_client(return_value: list[SupportedKind] | None = None) -> MagicMock:
    """NanopaymentClient mock."""
    mock = MagicMock(spec=NanopaymentClient)
    if return_value is not None:
        mock.get_supported = AsyncMock(return_value=return_value)
    return mock


# =============================================================================
# SELLER_ADDRESS VALIDATION TESTS
# =============================================================================


class TestSellerAddressValidation:
    def test_empty_string_raises(self):
        """Lines 138-139: Empty string raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            GatewayMiddleware(
                seller_address="",
                nanopayment_client=_make_client(),
            )
        assert "seller_address is required" in str(exc_info.value)

    def test_missing_0x_prefix_raises(self):
        """Lines 140-141: Not starting with 0x raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            GatewayMiddleware(
                seller_address="abc123def4567890123456789012345678901",
                nanopayment_client=_make_client(),
            )
        assert "must be an EVM address" in str(exc_info.value)

    def test_wrong_length_raises(self):
        """Lines 142-145: Wrong length raises ValueError."""
        # Too short
        with pytest.raises(ValueError) as exc_info:
            GatewayMiddleware(
                seller_address="0x" + "a" * 30,
                nanopayment_client=_make_client(),
            )
        assert "must be 42 characters" in str(exc_info.value)

        # Too long
        with pytest.raises(ValueError) as exc_info:
            GatewayMiddleware(
                seller_address="0x" + "a" * 50,
                nanopayment_client=_make_client(),
            )
        assert "must be 42 characters" in str(exc_info.value)

    def test_invalid_hex_chars_raises(self):
        """Lines 146-150: Invalid hex characters raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            GatewayMiddleware(
                seller_address="0x" + "g" * 40,  # 'g' is not valid hex
                nanopayment_client=_make_client(),
            )
        assert "invalid hex characters" in str(exc_info.value)


# =============================================================================
# _GET_SUPPORTED_KINDS TESTS
# =============================================================================


class TestGetSupportedKinds:
    @pytest.mark.asyncio
    async def test_returns_cached_if_set(self):
        """Lines 163-164: Returns cached _supported_kinds if set."""
        kinds = _make_kinds()
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=kinds,
        )

        result = await middleware._get_supported_kinds()
        assert result == kinds
        # Should not call client
        middleware._client.get_supported.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetches_if_none(self):
        """Lines 165-167: Fetches from client if _supported_kinds is None."""
        mock_client = _make_client(_make_kinds())
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=mock_client,
            supported_kinds=None,  # Not pre-set
        )

        result = await middleware._get_supported_kinds()

        assert len(result) == 2
        mock_client.get_supported.assert_called_once_with(force_refresh=True)

    @pytest.mark.asyncio
    async def test_empty_fetch_raises(self):
        """Lines 166-167: Empty fetch raises NoNetworksAvailableError."""
        mock_client = _make_client([])  # Empty list
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=mock_client,
            supported_kinds=None,
        )

        with pytest.raises(MiddlewareNoNetworksAvailableError):
            await middleware._get_supported_kinds()

    @pytest.mark.asyncio
    async def test_none_fetch_raises(self):
        """Lines 166-167: None return raises NoNetworksAvailableError."""
        mock_client = MagicMock(spec=NanopaymentClient)
        mock_client.get_supported = AsyncMock(return_value=None)  # Explicitly returns None
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=mock_client,
            supported_kinds=None,
        )

        with pytest.raises(MiddlewareNoNetworksAvailableError):
            await middleware._get_supported_kinds()


# =============================================================================
# HANDLE ERROR HANDLING TESTS
# =============================================================================


class TestHandleErrorHandling:
    @pytest.mark.asyncio
    async def test_no_networks_available_raises_no_networks_error(self):
        """When _get_supported_kinds() returns empty, NoNetworksAvailableError propagates."""
        # This test verifies that when get_supported returns empty list,
        # _get_supported_kinds raises NoNetworksAvailableError (line 166-167)
        # which propagates up from handle() - this is the actual code path
        mock_client = MagicMock(spec=NanopaymentClient)
        mock_client.get_supported = AsyncMock(return_value=[])

        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=mock_client,
            supported_kinds=None,  # Will trigger fetch
        )

        # Try to handle with a payment - should raise NoNetworksAvailableError
        # from _get_supported_kinds() before we reach the 402 response logic
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

        # The actual behavior: NoNetworksAvailableError is raised by _get_supported_kinds
        with pytest.raises(NoNetworksAvailableError):
            await middleware.handle(
                {"payment-signature": sig_header},
                "$0.001",
            )

    @pytest.mark.asyncio
    async def test_empty_supported_kinds_preloaded_raises_502(self):
        """Lines 366-371: When supported_kinds=[], handle returns 502."""
        # When supported_kinds is pre-set to empty list (not None),
        # _get_supported_kinds returns [] directly without calling client,
        # and the code at lines 366-371 runs
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=[],  # Pre-set to empty - bypasses client call
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

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await middleware.handle(
                {"payment-signature": sig_header},
                "$0.001",
            )

        assert exc_info.value.status_code == 502
        assert "No supported payment networks available" in exc_info.value.detail["error"]

    @pytest.mark.asyncio
    async def test_missing_contract_addresses_raises_502(self):
        """Lines 373-378: Missing verifying_contract or usdc_address returns 502."""
        # Create a payload with a network that has no contracts
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds_with_missing_contracts(),
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

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await middleware.handle(
                {"payment-signature": sig_header},
                "$0.001",
            )

        assert exc_info.value.status_code == 502
        assert "Missing contract addresses" in exc_info.value.detail["error"]

    @pytest.mark.asyncio
    async def test_settlement_exception_returns_402(self):
        """Lines 399-410: Settlement exception returns 402."""
        mock_client = _make_client(_make_kinds())
        mock_client.settle = AsyncMock(side_effect=Exception("Settlement failed"))

        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=mock_client,
            supported_kinds=_make_kinds(),
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

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await middleware.handle(
                {"payment-signature": sig_header},
                "$0.001",
            )

        assert exc_info.value.status_code == 402
        assert "Settlement failed" in exc_info.value.detail["error"]


# =============================================================================
# REQUIRE FASTAPI DEPENDENCY TESTS
# =============================================================================


class TestRequire:
    @pytest.mark.asyncio
    async def test_require_returns_dependency_function(self):
        """Lines 424-450: require() returns a function that can be used as FastAPI dependency."""
        pytest.importorskip("fastapi")
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(_make_kinds()),
            supported_kinds=_make_kinds(),
        )

        result = middleware.require("$0.001")

        # Should return a callable
        assert callable(result)

        # The returned function should accept a request and call handle()
        # Let's test that it internally calls parse_price
        # by checking the behavior when request has no payment

        # Create a mock request
        mock_request = MagicMock()
        mock_request.headers = {}  # No payment signature

        # When called, should raise HTTPException (not PaymentRequiredHTTPError)
        # because the dependency wraps it

        # The dependency should call parse_price internally
        # If parse_price fails, it should propagate
        # But we can't easily test this without FastAPI's Depends
        # Let's verify the function structure at least

        # Verify it's a coroutine function
        import inspect

        assert inspect.iscoroutinefunction(result)

    @pytest.mark.asyncio
    async def test_require_dependency_calls_handle(self):
        """The dependency calls handle() with headers and price."""
        pytest.importorskip("fastapi")
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(_make_kinds()),
            supported_kinds=_make_kinds(),
        )

        dependency = middleware.require("$0.001")

        # Mock request with valid payment
        mock_request = MagicMock()

        # Build a valid payment payload
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

        mock_client = _make_client(_make_kinds())
        mock_client.settle = AsyncMock(
            return_value=MagicMock(
                success=True,
                transaction="batch-123",
                payer="0x" + "a" * 40,
            )
        )

        # Replace client
        middleware._client = mock_client

        # Create dependency with mocked request
        mock_request.headers = {
            "payment-signature": base64.b64encode(json.dumps(payload.to_dict()).encode()).decode()
        }

        # Call the dependency
        result = await dependency(mock_request)

        # Should return PaymentInfo
        assert result.verified is True
        assert result.transaction == "batch-123"

    @pytest.mark.asyncio
    async def test_require_dependency_wraps_402_to_http_exception(self):
        """Lines 443-448: Wraps PaymentRequiredHTTPError to HTTPException."""
        pytest.importorskip("fastapi")
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(_make_kinds()),
            supported_kinds=_make_kinds(),
        )

        dependency = middleware.require("$0.001")

        # Mock request without payment
        mock_request = MagicMock()
        mock_request.headers = {}

        from fastapi import HTTPException

        # Should raise HTTPException with 402
        with pytest.raises(HTTPException) as exc_info:
            await dependency(mock_request)

        assert exc_info.value.status_code == 402
        assert "accepts" in exc_info.value.detail  # 402 response body


# =============================================================================
# ADDITIONAL COVERAGE TESTS
# =============================================================================


class TestBuildAcceptsArray:
    def test_skips_kinds_without_contracts(self):
        """_build_accepts_array skips kinds without verifying_contract or usdc_address."""
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds_with_missing_contracts(),
        )

        accepts = middleware._build_accepts_array(1000)

        # Should be empty because both kinds have missing contracts
        assert accepts == []

    def test_build_accepts_array_with_none_kinds(self):
        """Lines 196-198: Returns empty list if kinds is None."""
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=None,
        )

        accepts = middleware._build_accepts_array(1000, kinds=None)
        assert accepts == []


class TestParsePaymentSignature:
    def test_invalid_base64_raises(self):
        """Invalid base64 in signature raises ValueError."""
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )

        with pytest.raises(ValueError) as exc_info:
            middleware._parse_payment_signature("not-valid-base64!!!")

        assert "Failed to parse PAYMENT-SIGNATURE" in str(exc_info.value)

    def test_invalid_json_raises(self):
        """Invalid JSON in signature raises ValueError."""
        middleware = GatewayMiddleware(
            seller_address="0x" + "a" * 40,
            nanopayment_client=_make_client(),
            supported_kinds=_make_kinds(),
        )

        # Valid base64 but not JSON
        invalid_json = base64.b64encode(b"not json").decode()

        with pytest.raises(ValueError) as exc_info:
            middleware._parse_payment_signature(invalid_json)

        assert "Failed to parse PAYMENT-SIGNATURE" in str(exc_info.value)


# =============================================================================
# ADAPTER ERROR PATH TESTS (adapter.py uncovered lines)
# =============================================================================


class TestAdapterX402URLErrorPaths:
    """Test adapter pay_x402_url() error paths for adapter.py coverage."""

    @pytest.mark.asyncio
    async def test_initial_request_timeout(self):
        """Lines 288-293: Initial request TimeoutException → GatewayAPIError."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        import httpx

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        with pytest.raises(Exception) as exc_info:
            await adapter.pay_x402_url("https://api.example.com/data")
        assert "timed out" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_initial_request_request_error(self):
        """Lines 294-299: Initial request RequestError → GatewayAPIError."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        import httpx

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=httpx.RequestError("failed"))

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        with pytest.raises(Exception):
            await adapter.pay_x402_url("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_402_missing_payment_required_header(self):
        """Lines 320-325: 402 without PAYMENT-REQUIRED header → GatewayAPIError."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.headers = {}  # No header
        mock_resp.text = "Payment Required"

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_resp)

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        with pytest.raises(Exception):
            await adapter.pay_x402_url("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_402_malformed_base64(self):
        """Lines 331-336: Invalid base64 in PAYMENT-REQUIRED → GatewayAPIError."""
        import base64
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.headers = {"payment-required": "not-valid-base64!!!"}
        mock_resp.text = ""

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_resp)

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        with pytest.raises(Exception):
            await adapter.pay_x402_url("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_gateway_kind_not_found(self):
        """Lines 340-343: No GatewayWalletBatched scheme → UnsupportedSchemeError."""
        import base64
        import json
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import UnsupportedSchemeError

        req = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "asset": "0x" + "d" * 40,
                    "amount": "1000000",
                    "maxTimeoutSeconds": 345600,
                    "payTo": "0x" + "b" * 40,
                    "extra": {
                        "name": "NotGateway",  # Wrong name
                        "version": "1",
                        "verifyingContract": "0x" + "c" * 40,
                    },
                },
            ],
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.headers = {
            "payment-required": base64.b64encode(json.dumps(req).encode()).decode()
        }
        mock_resp.text = ""

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_resp)

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        with pytest.raises(UnsupportedSchemeError):
            await adapter.pay_x402_url("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_missing_verifying_contract_fetches_from_client(self):
        """Lines 347-350: Missing verifying_contract calls get_verifying_contract()."""
        import base64
        import json
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.types import PaymentPayload

        req = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "asset": "0x" + "d" * 40,
                    "amount": "1000000",
                    "maxTimeoutSeconds": 345600,
                    "payTo": "0x" + "b" * 40,
                    "extra": {
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": None,
                    },
                },
            ],
        }

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {
            "payment-required": base64.b64encode(json.dumps(req).encode()).decode()
        }
        mock_resp_402.text = ""

        mock_resp_retry = MagicMock()
        mock_resp_retry.status_code = 200
        mock_resp_retry.content = b"ok"
        mock_resp_retry.text = "ok"

        mock_payload = MagicMock(spec=PaymentPayload)
        mock_payload.to_dict.return_value = {}

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock(return_value=mock_payload)

        mock_client = MagicMock()
        mock_client.get_verifying_contract = AsyncMock(return_value="0x" + "c" * 40)
        mock_client.settle = AsyncMock(return_value=MagicMock(success=True, transaction="tx123"))

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=[mock_resp_402, mock_resp_retry])

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        await adapter.pay_x402_url("https://api.example.com/data")
        mock_client.get_verifying_contract.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_topup_failure_in_pay_x402_url_continues(self):
        """Lines 378-381: Auto-topup failure in pay_x402_url logs but continues."""
        import base64
        import json
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.types import PaymentPayload

        req = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "asset": "0x" + "d" * 40,
                    "amount": "1000000",
                    "maxTimeoutSeconds": 345600,
                    "payTo": "0x" + "b" * 40,
                    "extra": {
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": "0x" + "c" * 40,
                    },
                },
            ],
        }

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {
            "payment-required": base64.b64encode(json.dumps(req).encode()).decode()
        }
        mock_resp_402.text = ""

        mock_resp_retry = MagicMock()
        mock_resp_retry.status_code = 200
        mock_resp_retry.content = b"ok"
        mock_resp_retry.text = "ok"

        mock_payload = MagicMock(spec=PaymentPayload)
        mock_payload.to_dict.return_value = {}

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock(return_value=mock_payload)
        mock_vault.get_balance = AsyncMock(return_value=MagicMock(available_decimal="0.01"))

        mock_wm = MagicMock()
        mock_wm.deposit = AsyncMock(side_effect=Exception("Deposit failed"))

        mock_client = MagicMock()
        mock_client.settle = AsyncMock(return_value=MagicMock(success=True, transaction="tx123"))

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=[mock_resp_402, mock_resp_retry])

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=True,
        )
        adapter.set_wallet_manager(mock_wm)

        # Should NOT raise
        result = await adapter.pay_x402_url("https://api.example.com/data")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_retry_request_timeout(self):
        """Lines 405-416: Retry request TimeoutException → GatewayAPIError."""
        import base64
        import json
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.types import PaymentPayload
        import httpx

        req = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "asset": "0x" + "d" * 40,
                    "amount": "1000000",
                    "maxTimeoutSeconds": 345600,
                    "payTo": "0x" + "b" * 40,
                    "extra": {
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": "0x" + "c" * 40,
                    },
                },
            ],
        }

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {
            "payment-required": base64.b64encode(json.dumps(req).encode()).decode()
        }
        mock_resp_402.text = ""

        mock_payload = MagicMock(spec=PaymentPayload)
        mock_payload.to_dict.return_value = {}

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock(return_value=mock_payload)

        mock_client = MagicMock()
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(
            side_effect=[mock_resp_402, httpx.TimeoutException("timeout")]
        )

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        with pytest.raises(Exception):
            await adapter.pay_x402_url("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_raises_when_content_not_delivered(self):
        """Lines 426-439: Circuit open + non-success status → CircuitOpenError."""
        import base64
        import json
        from omniclaw.protocols.nanopayments.adapter import (
            CircuitOpenError,
            NanopaymentAdapter,
            NanopaymentCircuitBreaker,
        )
        from omniclaw.protocols.nanopayments.types import PaymentPayload

        req = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "asset": "0x" + "d" * 40,
                    "amount": "1000000",
                    "maxTimeoutSeconds": 345600,
                    "payTo": "0x" + "b" * 40,
                    "extra": {
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": "0x" + "c" * 40,
                    },
                },
            ],
        }

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {
            "payment-required": base64.b64encode(json.dumps(req).encode()).decode()
        }
        mock_resp_402.text = ""

        mock_resp_retry = MagicMock()
        mock_resp_retry.status_code = 500
        mock_resp_retry.content = b"error"
        mock_resp_retry.text = "error"

        mock_payload = MagicMock(spec=PaymentPayload)
        mock_payload.to_dict.return_value = {}

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock(return_value=mock_payload)

        mock_client = MagicMock()
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=[mock_resp_402, mock_resp_retry])

        cb = NanopaymentCircuitBreaker(failure_threshold=1)
        cb.record_failure()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            circuit_breaker=cb,
            auto_topup_enabled=False,
        )

        with pytest.raises(CircuitOpenError):
            await adapter.pay_x402_url("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_non_recoverable_settlement_error_raises(self):
        """Lines 466-484: NonceReusedError + non-success → raises immediately."""
        import base64
        import json
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import NonceReusedError
        from omniclaw.protocols.nanopayments.types import PaymentPayload

        req = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "asset": "0x" + "d" * 40,
                    "amount": "1000000",
                    "maxTimeoutSeconds": 345600,
                    "payTo": "0x" + "b" * 40,
                    "extra": {
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": "0x" + "c" * 40,
                    },
                },
            ],
        }

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {
            "payment-required": base64.b64encode(json.dumps(req).encode()).decode()
        }
        mock_resp_402.text = ""

        mock_resp_retry = MagicMock()
        mock_resp_retry.status_code = 500
        mock_resp_retry.content = b"error"
        mock_resp_retry.text = "error"

        mock_payload = MagicMock(spec=PaymentPayload)
        mock_payload.to_dict.return_value = {}

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock(return_value=mock_payload)

        mock_client = MagicMock()
        mock_client.settle = AsyncMock(side_effect=NonceReusedError())

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=[mock_resp_402, mock_resp_retry])

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        with pytest.raises(NonceReusedError):
            await adapter.pay_x402_url("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_settlement_success_after_retry(self):
        """Lines 638-739: Settlement succeeds after transient timeout retry."""
        import base64
        import json
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import GatewayTimeoutError
        from omniclaw.protocols.nanopayments.types import PaymentPayload

        req = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "asset": "0x" + "d" * 40,
                    "amount": "1000000",
                    "maxTimeoutSeconds": 345600,
                    "payTo": "0x" + "b" * 40,
                    "extra": {
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": "0x" + "c" * 40,
                    },
                },
            ],
        }

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {
            "payment-required": base64.b64encode(json.dumps(req).encode()).decode()
        }
        mock_resp_402.text = ""

        mock_resp_retry = MagicMock()
        mock_resp_retry.status_code = 200
        mock_resp_retry.content = b"ok"
        mock_resp_retry.text = "ok"

        mock_payload = MagicMock(spec=PaymentPayload)
        mock_payload.to_dict.return_value = {}

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock(return_value=mock_payload)

        mock_client = MagicMock()
        mock_client.settle = AsyncMock(
            side_effect=[
                GatewayTimeoutError("timeout"),
                MagicMock(success=True, transaction="tx123"),
            ]
        )

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=[mock_resp_402, mock_resp_retry])

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
            retry_attempts=1,
            retry_base_delay=0.001,
        )

        result = await adapter.pay_x402_url("https://api.example.com/data")
        assert result.success is True
        assert mock_client.settle.call_count == 2

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_in_settle_with_retry(self):
        """Lines 665-667: _settle_with_retry raises CircuitOpenError when open."""
        from omniclaw.protocols.nanopayments.adapter import (
            CircuitOpenError,
            NanopaymentAdapter,
            NanopaymentCircuitBreaker,
        )

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()

        cb = NanopaymentCircuitBreaker(failure_threshold=1)
        cb.record_failure()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            circuit_breaker=cb,
            auto_topup_enabled=False,
        )

        with pytest.raises(CircuitOpenError):
            await adapter._settle_with_retry(payload=MagicMock(), requirements=MagicMock())


# =============================================================================
# ADAPTER pay_direct ERROR PATH TESTS
# =============================================================================


class TestAdapterPayDirectErrorPaths:
    """Test adapter pay_direct() error paths for adapter.py coverage."""

    @pytest.mark.asyncio
    async def test_pay_direct_auto_topup_failure_continues(self):
        """Lines 591-596: Auto-topup failure in pay_direct logs but continues."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock()
        mock_vault.get_balance = AsyncMock(return_value=MagicMock(available_decimal="0.01"))

        mock_wm = MagicMock()
        mock_wm.deposit = AsyncMock(side_effect=Exception("Deposit failed"))

        mock_client = MagicMock()
        mock_client.get_verifying_contract = AsyncMock(return_value="0x" + "c" * 40)
        mock_client.get_usdc_address = AsyncMock(return_value="0x" + "d" * 40)
        mock_client.settle = AsyncMock(return_value=MagicMock(success=True, transaction="tx123"))

        mock_http = AsyncMock()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=True,
        )
        adapter.set_wallet_manager(mock_wm)

        result = await adapter.pay_direct(
            seller_address="0x" + "b" * 40,
            amount_usdc="0.001",
            network="eip155:5042002",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_pay_direct_circuit_breaker_open(self):
        """Lines 609-619: Circuit open in pay_direct → SettlementError."""
        from omniclaw.protocols.nanopayments.adapter import (
            NanopaymentAdapter,
            NanopaymentCircuitBreaker,
            SettlementError,
        )

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock()

        mock_client = MagicMock()
        mock_client.get_verifying_contract = AsyncMock(return_value="0x" + "c" * 40)
        mock_client.get_usdc_address = AsyncMock(return_value="0x" + "d" * 40)

        mock_http = AsyncMock()

        cb = NanopaymentCircuitBreaker(failure_threshold=1)
        cb.record_failure()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            circuit_breaker=cb,
            auto_topup_enabled=False,
        )

        with pytest.raises(SettlementError) as exc_info:
            await adapter.pay_direct(
                seller_address="0x" + "b" * 40,
                amount_usdc="0.001",
                network="eip155:5042002",
            )
        assert "circuit" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_pay_direct_no_wallet_manager_returns_false_topup(self):
        """Lines 763-777: _check_and_topup with no wallet manager returns False."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=True,  # Enabled but no wallet manager
        )

        result = await adapter._check_and_topup()
        assert result is False


# =============================================================================
# PROTOCOL ADAPTER execute() TESTS
# =============================================================================


class TestProtocolAdapterExecute:
    """Test NanopaymentProtocolAdapter.execute() fallback paths."""

    @pytest.mark.asyncio
    async def test_execute_pay_direct_no_network_uses_env_var(self):
        """Lines 929-943: execute() with no network uses NANOPAYMENTS_DEFAULT_NETWORK."""
        import os
        from omniclaw.protocols.nanopayments.adapter import (
            NanopaymentProtocolAdapter,
        )
        from decimal import Decimal

        mock_adapter = AsyncMock()
        mock_adapter.pay_direct = AsyncMock(
            return_value=MagicMock(
                success=True,
                transaction="tx123",
                payer="0x" + "a" * 40,
                seller="0x" + "b" * 40,
                amount_usdc="0.001",
                amount_atomic="1000",
                network="eip155:5042002",
                is_nanopayment=True,
            )
        )

        protocol = NanopaymentProtocolAdapter(
            nanopayment_adapter=mock_adapter,
            micro_threshold_usdc="1.00",
        )

        with patch.dict(os.environ, {"NANOPAYMENTS_DEFAULT_NETWORK": "eip155:5042002"}):
            result = await protocol.execute(
                wallet_id="wallet-123",
                recipient="0x" + "b" * 40,
                amount=Decimal("0.001"),
            )

        mock_adapter.pay_direct.assert_called_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_pay_x402_url_no_network_uses_env_var(self):
        """Lines 929-943: execute() with URL recipient and no network uses env var."""
        import os
        from omniclaw.protocols.nanopayments.adapter import (
            NanopaymentProtocolAdapter,
        )
        from decimal import Decimal

        mock_adapter = AsyncMock()
        mock_adapter.pay_x402_url = AsyncMock(
            return_value=MagicMock(
                success=True,
                transaction="tx123",
                payer="0x" + "a" * 40,
                seller="0x" + "b" * 40,
                amount_usdc="0",
                amount_atomic="0",
                network="",
                is_nanopayment=False,
            )
        )

        protocol = NanopaymentProtocolAdapter(
            nanopayment_adapter=mock_adapter,
            micro_threshold_usdc="1.00",
        )

        with patch.dict(os.environ, {"NANOPAYMENTS_DEFAULT_NETWORK": "eip155:5042002"}):
            result = await protocol.execute(
                wallet_id="wallet-123",
                recipient="https://api.example.com/data",
                amount=Decimal("0.001"),
            )

        mock_adapter.pay_x402_url.assert_called_once()


# =============================================================================
# SIGNING MODULE COVERAGE TESTS
# =============================================================================


class TestSigningModuleCoverage:
    """Test signing module functions for signing.py coverage."""

    def test_build_eip712_domain_empty_verifying_contract(self):
        """Lines 112-116: Empty verifying_contract raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_domain, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_domain(chain_id=1, verifying_contract="")
        assert exc_info.value.code == "MISSING_VERIFYING_CONTRACT"

    def test_build_eip712_domain_invalid_prefix(self):
        """Lines 118-122: Invalid address prefix raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_domain, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_domain(chain_id=1, verifying_contract="abc123")
        assert exc_info.value.code == "INVALID_ADDRESS_FORMAT"

    def test_build_eip712_domain_invalid_chain_id(self):
        """Lines 124-128: Invalid chain_id raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_domain, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_domain(chain_id=0, verifying_contract="0x" + "a" * 40)
        assert exc_info.value.code == "INVALID_CHAIN_ID"

    def test_build_eip712_message_invalid_from_address(self):
        """Lines 170-174: Invalid from_address raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_message, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_message(
                from_address="not-an-address",
                to_address="0x" + "b" * 40,
                value=1000,
            )
        assert exc_info.value.code == "INVALID_FROM_ADDRESS"

    def test_build_eip712_message_invalid_to_address(self):
        """Lines 176-180: Invalid to_address raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_message, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_message(
                from_address="0x" + "a" * 40,
                to_address="also-not-address",
                value=1000,
            )
        assert exc_info.value.code == "INVALID_TO_ADDRESS"

    def test_build_eip712_message_self_transfer(self):
        """Lines 182-186: Same from/to address raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_message, SigningError

        addr = "0x" + "a" * 40
        with pytest.raises(SigningError) as exc_info:
            build_eip712_message(
                from_address=addr,
                to_address=addr,
                value=1000,
            )
        assert exc_info.value.code == "SELF_TRANSFER"

    def test_build_eip712_message_negative_value(self):
        """Lines 188-193: Negative value raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_message, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_message(
                from_address="0x" + "a" * 40,
                to_address="0x" + "b" * 40,
                value=-100,
            )
        assert exc_info.value.code == "INVALID_VALUE"

    def test_build_eip712_message_valid_before_too_soon(self):
        """Lines 199-206: valid_before too soon raises SigningError."""
        import time
        from omniclaw.protocols.nanopayments.signing import build_eip712_message, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_message(
                from_address="0x" + "a" * 40,
                to_address="0x" + "b" * 40,
                value=1000,
                valid_before=int(time.time()) + 100,  # Too soon
            )
        assert exc_info.value.code == "VALID_BEFORE_TOO_SOON"

    def test_build_eip712_message_invalid_nonce_prefix(self):
        """Lines 213-217: Nonce without 0x prefix raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_message, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_message(
                from_address="0x" + "a" * 40,
                to_address="0x" + "b" * 40,
                value=1000,
                nonce="deadbeef" * 8,
            )
        assert exc_info.value.code == "INVALID_NONCE_FORMAT"

    def test_build_eip712_message_invalid_nonce_length(self):
        """Lines 220-224: Nonce wrong length raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_message, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_message(
                from_address="0x" + "a" * 40,
                to_address="0x" + "b" * 40,
                value=1000,
                nonce="0x" + "ab" * 10,  # 20 bytes, not 32
            )
        assert exc_info.value.code == "INVALID_NONCE_LENGTH"

    def test_build_eip712_message_invalid_nonce_hex(self):
        """Lines 227-233: Nonce with invalid hex raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import build_eip712_message, SigningError

        with pytest.raises(SigningError) as exc_info:
            build_eip712_message(
                from_address="0x" + "a" * 40,
                to_address="0x" + "b" * 40,
                value=1000,
                nonce="0x" + "g" * 64,  # 'g' is invalid hex
            )
        assert exc_info.value.code == "INVALID_NONCE_HEX"

    def test_eip3009_signer_invalid_key_length(self):
        """Lines 317-320: Private key wrong length raises InvalidPrivateKeyError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import InvalidPrivateKeyError

        with pytest.raises(InvalidPrivateKeyError):
            EIP3009Signer("0x" + "ab" * 31)  # 62 chars

    def test_eip3009_signer_invalid_key_hex(self):
        """Lines 322-326: Private key invalid hex raises InvalidPrivateKeyError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import InvalidPrivateKeyError

        with pytest.raises(InvalidPrivateKeyError):
            EIP3009Signer("0x" + "g" * 64)  # 'g' invalid hex

    def test_eip3009_signer_wrong_scheme(self):
        """Lines 402-406: Wrong scheme raises UnsupportedSchemeError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import UnsupportedSchemeError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        signer = EIP3009Signer("0x" + "1" * 64)
        kind = PaymentRequirementsKind(
            scheme="wrong-scheme",
            network="eip155:5042002",
            asset="0x" + "d" * 40,
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="NotGateway",
                version="1",
                verifying_contract="0x" + "c" * 40,
            ),
        )

        with pytest.raises(UnsupportedSchemeError):
            signer.sign_transfer_with_authorization(kind)

    def test_eip3009_signer_missing_verifying_contract(self):
        """Lines 408-415: Missing verifying_contract raises MissingVerifyingContractError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import MissingVerifyingContractError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        signer = EIP3009Signer("0x" + "1" * 64)
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0x" + "d" * 40,
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract=None,
            ),
        )

        with pytest.raises(MissingVerifyingContractError):
            signer.sign_transfer_with_authorization(kind)

    def test_eip3009_signer_amount_exceeds_requirement(self):
        """Lines 421-427: amount_atomic > required raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import SigningError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        signer = EIP3009Signer("0x" + "1" * 64)
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0x" + "d" * 40,
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract="0x" + "c" * 40,
            ),
        )

        with pytest.raises(SigningError) as exc_info:
            signer.sign_transfer_with_authorization(kind, amount_atomic=2000)
        assert exc_info.value.code == "AMOUNT_EXCEEDS_REQUIREMENT"

    def test_eip3009_signer_invalid_network_format(self):
        """Lines 432-435: Non-eip155 network raises UnsupportedNetworkError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import UnsupportedNetworkError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        signer = EIP3009Signer("0x" + "1" * 64)
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="cosmos:stargaze",
            asset="0x" + "d" * 40,
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract="0x" + "c" * 40,
            ),
        )

        with pytest.raises(UnsupportedNetworkError):
            signer.sign_transfer_with_authorization(kind)

    def test_eip3009_signer_missing_verifying_contract(self):
        """Lines 408-415: Missing verifying_contract raises MissingVerifyingContractError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import MissingVerifyingContractError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        signer = EIP3009Signer("0x" + "1" * 64)
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0x" + "d" * 40,
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract=None,
            ),
        )

        with pytest.raises(MissingVerifyingContractError):
            signer.sign_transfer_with_authorization(kind)

    def test_eip3009_signer_amount_exceeds_requirement(self):
        """Lines 421-427: amount_atomic > required raises SigningError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import SigningError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        signer = EIP3009Signer("0x" + "1" * 64)
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0x" + "d" * 40,
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract="0x" + "c" * 40,
            ),
        )

        with pytest.raises(SigningError) as exc_info:
            signer.sign_transfer_with_authorization(kind, amount_atomic=2000)
        assert exc_info.value.code == "AMOUNT_EXCEEDS_REQUIREMENT"

    def test_eip3009_signer_invalid_network_format(self):
        """Lines 432-435: Non-eip155 network raises UnsupportedNetworkError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import UnsupportedNetworkError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        signer = EIP3009Signer("0x" + "1" * 64)
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="cosmos:stargaze",
            asset="0x" + "d" * 40,
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract="0x" + "c" * 40,
            ),
        )

        with pytest.raises(UnsupportedNetworkError):
            signer.sign_transfer_with_authorization(kind)

    def test_generate_eoa_keypair_returns_valid(self):
        """Line 635: generate_eoa_keypair() returns valid (key, address)."""
        from omniclaw.protocols.nanopayments.signing import generate_eoa_keypair

        private_key, address = generate_eoa_keypair()
        assert private_key.startswith("0x")
        assert len(private_key) == 66
        assert address.startswith("0x")
        assert len(address) == 42

    def test_parse_caip2_chain_id_invalid_format(self):
        """Lines 571-572: parse_caip2_chain_id raises ValueError for invalid format."""
        from omniclaw.protocols.nanopayments.signing import parse_caip2_chain_id

        with pytest.raises(ValueError) as exc_info:
            parse_caip2_chain_id("cosmos:stargaze")
        assert "Invalid CAIP-2 format" in str(exc_info.value)

    def test_parse_caip2_chain_id_invalid_chain_id(self):
        """Lines 574-577: parse_caip2_chain_id raises ValueError for invalid chain ID."""
        from omniclaw.protocols.nanopayments.signing import parse_caip2_chain_id

        with pytest.raises(ValueError) as exc_info:
            parse_caip2_chain_id("eip155:not-a-number")
        assert "Invalid chain ID" in str(exc_info.value)
