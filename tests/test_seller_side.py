"""
Seller-Side x402 Tests.

Tests the seller/server side of x402 payments:
- Decimal price parsing (no float precision bugs)
- 402 response generation (x402 v2 spec)
- Payment verification flow with facilitator
- Multi-facilitator support (Circle, Coinbase, etc.)
- Scheme detection (exact vs GatewayWalletBatched)
- Network/USDC contract configuration

Run with:
    pytest tests/test_seller_side.py -v -s
"""

import base64
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from omniclaw.seller import PaymentScheme, Seller, create_seller


def _with_accepted(payload: dict, accepted: dict) -> dict:
    """Attach required x402 v2 selected requirements to a test payment payload."""
    payload["x402Version"] = 2
    payload["accepted"] = accepted
    payload.setdefault("network", accepted.get("network"))
    return payload


# =============================================================================
# TEST PRICE PARSING (Decimal precision — critical fix)
# =============================================================================


class TestPriceParsing:
    """Verify Decimal-based price parsing — no float, no rounding."""

    def test_parse_one_tenth_cent(self):
        """$0.001 → 1000 atomic units."""
        seller = Seller(seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123", name="Test")
        seller.add_endpoint("/test", "$0.001", "Test")
        endpoints = seller.get_endpoints()
        accepts = seller._create_accepts(endpoints["/test"])
        assert accepts[0]["amount"] == "1000"

    def test_parse_one_cent(self):
        """$0.01 → 10000 atomic units."""
        seller = Seller(seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123", name="Test")
        seller.add_endpoint("/test", "$0.01", "Test")
        accepts = seller._create_accepts(seller.get_endpoints()["/test"])
        assert accepts[0]["amount"] == "10000"

    def test_parse_one_dollar(self):
        """$1.00 → 1000000 atomic units."""
        seller = Seller(seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123", name="Test")
        seller.add_endpoint("/test", "$1.00", "Test")
        accepts = seller._create_accepts(seller.get_endpoints()["/test"])
        assert accepts[0]["amount"] == "1000000"

    def test_different_prices_produce_different_amounts(self):
        """$0.001 and $0.01 MUST produce different atomic values (critical bug fix)."""
        seller = Seller(seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123", name="Test")
        seller.add_endpoint("/cheap", "$0.001")
        seller.add_endpoint("/expensive", "$0.01")

        a = seller._create_accepts(seller.get_endpoints()["/cheap"])[0]["amount"]
        b = seller._create_accepts(seller.get_endpoints()["/expensive"])[0]["amount"]
        assert a != b
        assert a == "1000"
        assert b == "10000"

    def test_zero_price_rejected(self):
        """Zero price is not allowed."""
        seller = Seller(seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123", name="Test")
        with pytest.raises(ValueError, match="positive"):
            seller.add_endpoint("/test", "$0")

    def test_negative_price_rejected(self):
        """Negative price is not allowed."""
        seller = Seller(seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123", name="Test")
        with pytest.raises(ValueError):
            seller.add_endpoint("/test", "-$1.00")

    def test_invalid_format_rejected(self):
        """Non-numeric strings should raise."""
        seller = Seller(seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123", name="Test")
        with pytest.raises(ValueError):
            seller.add_endpoint("/test", "abc")


# =============================================================================
# TEST 402 RESPONSE GENERATION (x402 v2)
# =============================================================================


class Test402ResponseGeneration:
    """Test generating 402 Payment Required responses."""

    def test_create_basic_402_response(self):
        """402 response has correct x402 v2 structure."""
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test API",
            network="eip155:84532",
        )
        seller.add_endpoint("/test", "$0.001", "Test endpoint")

        headers, body = seller.create_402_response("/test", "http://localhost/test")

        assert "payment-required" in headers
        decoded = json.loads(base64.b64decode(headers["payment-required"]))

        assert decoded["x402Version"] == 2
        assert "accepts" in decoded
        assert len(decoded["accepts"]) > 0

        accept = decoded["accepts"][0]
        assert accept["amount"] == "1000"
        assert accept["scheme"] == "exact"
        assert accept["network"] == "eip155:84532"
        assert accept["asset"] == "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
        assert accept["payTo"] == "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123"

    def test_unregistered_endpoint_returns_empty(self):
        """Unregistered path returns empty response."""
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        headers, body = seller.create_402_response("/nonexistent", "http://localhost/x")
        assert headers == {}


# =============================================================================
# TEST ENDPOINT CREATION
# =============================================================================


class TestEndpointCreation:
    """Test creating seller endpoints."""

    def test_add_multiple_endpoints(self):
        """Adding multiple endpoints works."""
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/weather", "$0.001", "Weather data")
        seller.add_endpoint("/premium", "$0.01", "Premium content")

        endpoints = seller.get_endpoints()
        assert len(endpoints) == 2
        assert "/weather" in endpoints
        assert "/premium" in endpoints

    def test_protect_decorator_registers_endpoint(self):
        """@seller.protect registers endpoint."""
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )

        @seller.protect("/get_weather", "$0.001", "Weather")
        def get_weather():
            pass

        endpoints = seller.get_endpoints()
        assert "/get_weather" in endpoints

    def test_endpoint_stores_decimal_price(self):
        """Endpoints store Decimal price, not float."""
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        ep = seller.get_endpoints()["/test"]
        assert isinstance(ep.price_usd, Decimal)
        assert ep.price_usd == Decimal("0.001")

    def test_both_schemes_added_by_default(self):
        """Endpoints support both exact + GatewayWalletBatched by default."""
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        ep = seller.get_endpoints()["/test"]
        assert PaymentScheme.EXACT in ep.schemes
        assert PaymentScheme.GATEWAY_BATCHED in ep.schemes


# =============================================================================
# TEST GATEWAY CONTRACT CONFIGURATION
# =============================================================================


class TestGatewayContractConfig:
    """Test that fake gateway contract is never used."""

    def test_no_fake_gateway_contract(self):
        """Gateway contract must NOT contain placeholder/fake values."""
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        # Without CIRCLE_GATEWAY_CONTRACT env var, should be empty
        assert seller._gateway_contract != "0x1234567890abcdef1234567890abcdef12345678"

    def test_gateway_batched_skipped_without_contract(self, monkeypatch):
        """GatewayWalletBatched should be skipped if no gateway contract configured."""
        monkeypatch.delenv("CIRCLE_GATEWAY_CONTRACT", raising=False)
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        accepts = seller._create_accepts(seller.get_endpoints()["/test"])
        schemes = [a["scheme"] for a in accepts]
        # Without gateway contract, only "exact" should be present
        assert "exact" in schemes
        assert not any(
            (a.get("extra", {}) or {}).get("name") == "GatewayWalletBatched" for a in accepts
        )

    def test_gateway_batched_included_with_contract(self, monkeypatch):
        """GatewayWalletBatched should be included when gateway contract is set."""
        monkeypatch.setenv("CIRCLE_GATEWAY_CONTRACT", "0xABCD1234ABCD1234ABCD1234ABCD1234ABCD1234")
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        accepts = seller._create_accepts(seller.get_endpoints()["/test"])
        schemes = [a["scheme"] for a in accepts]
        assert "exact" in schemes
        # Verify the correct contract is used
        gw_accept = [
            a for a in accepts if (a.get("extra", {}) or {}).get("name") == "GatewayWalletBatched"
        ][0]
        assert (
            gw_accept["extra"]["verifyingContract"] == "0xABCD1234ABCD1234ABCD1234ABCD1234ABCD1234"
        )
        assert gw_accept["extra"]["version"] == "1"

    def test_exact_accept_does_not_advertise_gateway_metadata(self):
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001", schemes=[PaymentScheme.EXACT])
        accept = seller._create_accepts(seller.get_endpoints()["/test"])[0]
        assert accept["scheme"] == "exact"
        assert "extra" not in accept


class TestSellerSecurityHardening:
    """Regression tests for seller-side anti-tamper and replay protections."""

    def test_replay_nonce_is_rejected(self):
        import time

        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        accepted = seller._create_accepts(seller.get_endpoints()["/test"])[0]

        payload = _with_accepted(
            {
            "scheme": "exact",
            "network": accepted["network"],
            "payload": {
                "authorization": {
                    "from": "0xAAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
                    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                    "value": "1000",
                    "validAfter": "0",
                    "validBefore": str(int(time.time()) + 300),
                    "nonce": "0x" + "11" * 32,
                },
                "signature": "",
            },
            },
            accepted,
        )

        is_valid, _, record = seller.verify_payment(payload, accepted, verify_signature=False)
        assert is_valid is True
        assert record is not None

        is_valid_2, err_2, _ = seller.verify_payment(payload, accepted, verify_signature=False)
        assert is_valid_2 is False
        assert "nonce" in err_2.lower()

    def test_v2_payment_without_accepted_is_rejected(self):
        import time

        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        accepted = seller._create_accepts(seller.get_endpoints()["/test"])[0]

        payload = {
            "x402Version": 2,
            "scheme": "exact",
            "network": accepted["network"],
            "payload": {
                "authorization": {
                    "from": "0xAAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
                    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                    "value": "1000",
                    "validAfter": "0",
                    "validBefore": str(int(time.time()) + 300),
                    "nonce": "0x" + "22" * 32,
                },
                "signature": "",
            },
        }

        is_valid, error, record = seller.verify_payment(payload, accepted, verify_signature=False)

        assert is_valid is False
        assert record is None
        assert "Missing accepted requirements" in error

    def test_strict_gateway_contract_mode_rejects_missing_contract(self, monkeypatch):
        monkeypatch.setenv("OMNICLAW_SELLER_STRICT_GATEWAY_CONTRACT", "true")
        monkeypatch.delenv("CIRCLE_GATEWAY_CONTRACT", raising=False)
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Strict Test",
        )
        with pytest.raises(ValueError, match="CIRCLE_GATEWAY_CONTRACT"):
            seller.add_endpoint("/strict", "$0.001")

    def test_require_distributed_nonce_without_redis_fails_fast(self, monkeypatch):
        monkeypatch.setenv("OMNICLAW_SELLER_REQUIRE_DISTRIBUTED_NONCE", "true")
        monkeypatch.delenv("OMNICLAW_SELLER_NONCE_REDIS_URL", raising=False)
        with pytest.raises(RuntimeError, match="REQUIRE_DISTRIBUTED_NONCE"):
            Seller(
                seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                name="Nonce Strict",
            )

    def test_gateway_signature_verification_requires_complete_domain_fields(self):
        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Domain Strict",
        )
        accepted = {
            "network": "eip155:84532",
            "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
            "extra": {
                "name": "GatewayWalletBatched",
                # version and verifyingContract intentionally missing
            },
        }
        ok, error = seller._verify_eip3009_signature(
            authorization={
                "from": "0xAAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
                "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                "value": "1000",
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x" + "11" * 32,
            },
            signature="0x",
            accepted=accepted,
        )
        assert ok is False
        assert "Missing required EIP-712 domain fields" in error


# =============================================================================
# TEST PAYMENT VERIFICATION
# =============================================================================


class TestPaymentVerification:
    """Test payment verification logic."""

    def test_basic_verify_timeout_check(self):
        """Expired payment should be rejected."""
        import time

        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        endpoints = seller.get_endpoints()
        accepted = seller._create_accepts(endpoints["/test"])[0]

        payload = _with_accepted(
            {
            "scheme": "exact",
            "payload": {
                "authorization": {
                    "from": "0xAAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
                    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                    "value": "1000",
                    "validAfter": "0",
                    "validBefore": str(int(time.time()) - 100),  # Already expired
                    "nonce": "0x" + "00" * 32,
                },
                "signature": "",
            },
            },
            accepted,
        )

        is_valid, error, record = seller.verify_payment(payload, accepted, verify_signature=False)
        assert is_valid is False
        assert "expired" in error.lower()

    def test_basic_verify_wrong_recipient(self):
        """Payment to wrong address should be rejected."""
        import time

        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        accepted = seller._create_accepts(seller.get_endpoints()["/test"])[0]

        payload = _with_accepted(
            {
            "scheme": "exact",
            "payload": {
                "authorization": {
                    "from": "0xAAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
                    "to": "0xDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF",
                    "value": "1000",
                    "validAfter": "0",
                    "validBefore": str(int(time.time()) + 300),
                    "nonce": "0x" + "00" * 32,
                },
                "signature": "",
            },
            },
            accepted,
        )

        is_valid, error, record = seller.verify_payment(payload, accepted, verify_signature=False)
        assert is_valid is False
        assert "recipient" in error.lower()

    def test_basic_verify_insufficient_amount(self):
        """Underpayment should be rejected."""
        import time

        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        accepted = seller._create_accepts(seller.get_endpoints()["/test"])[0]

        payload = _with_accepted(
            {
            "scheme": "exact",
            "payload": {
                "authorization": {
                    "from": "0xAAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
                    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                    "value": "500",  # Less than 1000 required
                    "validAfter": "0",
                    "validBefore": str(int(time.time()) + 300),
                    "nonce": "0x" + "00" * 32,
                },
                "signature": "",
            },
            },
            accepted,
        )

        is_valid, error, record = seller.verify_payment(payload, accepted, verify_signature=False)
        assert is_valid is False
        assert "insufficient" in error.lower()

    def test_basic_verify_valid_payment(self):
        """Valid payment should pass."""
        import time

        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
        )
        seller.add_endpoint("/test", "$0.001")
        accepted = seller._create_accepts(seller.get_endpoints()["/test"])[0]

        payload = _with_accepted(
            {
            "scheme": "exact",
            "payload": {
                "authorization": {
                    "from": "0xAAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
                    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                    "value": "1000",
                    "validAfter": "0",
                    "validBefore": str(int(time.time()) + 300),
                    "nonce": "0x" + "00" * 32,
                },
                "signature": "",
            },
            },
            accepted,
        )

        is_valid, error, record = seller.verify_payment(payload, accepted, verify_signature=False)
        assert is_valid is True
        assert record is not None
        assert record.amount == 1000


# =============================================================================
# TEST FACILITATOR INTEGRATION
# =============================================================================


class TestFacilitatorIntegration:
    """Test seller with Circle Gateway facilitator."""

    @pytest.mark.asyncio
    async def test_verify_routes_to_facilitator(self):
        """When facilitator is configured, verify routes to it."""
        mock_facilitator = AsyncMock()
        mock_facilitator.verify.return_value = MagicMock(
            is_valid=True,
            payer="0xAAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
            invalid_reason=None,
        )

        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
            facilitator=mock_facilitator,
        )
        seller.add_endpoint("/test", "$0.001")
        accepted = seller._create_accepts(seller.get_endpoints()["/test"])[0]

        is_valid, error, record = await seller.verify_payment_async(
            _with_accepted({"scheme": "exact", "payload": {}}, accepted),
            accepted,
        )

        assert is_valid is True
        mock_facilitator.verify.assert_called_once()

    @pytest.mark.asyncio
    async def test_settle_routes_to_facilitator(self):
        """When facilitator is configured, settle routes to it."""
        mock_facilitator = AsyncMock()
        mock_facilitator.settle.return_value = MagicMock(
            success=True,
            payer="0xAAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
            error_reason=None,
        )

        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
            facilitator=mock_facilitator,
        )
        seller.add_endpoint("/test", "$0.001")
        accepted = seller._create_accepts(seller.get_endpoints()["/test"])[0]

        is_valid, error, record = await seller.verify_payment_async(
            _with_accepted({"scheme": "exact", "payload": {}}, accepted),
            accepted,
            settle_payment=True,
        )

        assert is_valid is True
        mock_facilitator.settle.assert_called_once()

    @pytest.mark.asyncio
    async def test_facilitator_rejection_returns_error(self):
        """Facilitator rejection returns proper error."""
        mock_facilitator = AsyncMock()
        mock_facilitator.verify.return_value = MagicMock(
            is_valid=False,
            payer=None,
            invalid_reason="invalid_signature",
        )

        seller = Seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test",
            facilitator=mock_facilitator,
        )
        seller.add_endpoint("/test", "$0.001")
        accepted = seller._create_accepts(seller.get_endpoints()["/test"])[0]

        is_valid, error, record = await seller.verify_payment_async(
            _with_accepted({"scheme": "exact", "payload": {}}, accepted),
            accepted,
        )

        assert is_valid is False
        assert "invalid_signature" in error


# =============================================================================
# TEST CREATE_SELLER FACTORY
# =============================================================================


class TestCreateSeller:
    """Test the create_seller factory function."""

    def test_create_basic_seller(self):
        """Factory creates a proper Seller instance."""
        seller = create_seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Test API",
        )
        assert isinstance(seller, Seller)
        assert seller.config.seller_address == "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123"
        assert seller.config.name == "Test API"
        assert seller.config.network == "eip155:84532"


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
