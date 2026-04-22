"""
End-to-end test for Circle Gateway Facilitator integration.

This tests the complete flow:
1. Seller creates with facilitator
2. Client makes request to protected endpoint
3. Seller returns 402 with payment requirements
4. Client pays (simulated)
5. Seller verifies via facilitator
6. Seller settles via facilitator
"""

from unittest.mock import Mock

import pytest

from omniclaw.seller import CircleGatewayFacilitator, create_seller
from omniclaw.seller.facilitator import SettleResult, VerifyResult


def create_mock_facilitator(verify_result=None, settle_result=None):
    """Create a mock facilitator with configurable results."""

    async def mock_verify(payload, requirements):
        if verify_result:
            return verify_result
        return VerifyResult(
            is_valid=True,
            payer="0xbuyer1234567890abcdef1234567890abcdef12",
            invalid_reason=None,
        )

    async def mock_settle(payload, requirements):
        if settle_result:
            return settle_result
        return SettleResult(
            success=True,
            transaction="tx_123456",
            network="eip155:84532",
            error_reason=None,
            payer="0xbuyer1234567890abcdef1234567890abcdef12",
        )

    facilitator = Mock(spec=CircleGatewayFacilitator)
    facilitator.verify = mock_verify
    facilitator.settle = mock_settle
    facilitator.base_url = "https://gateway-api-testnet.circle.com"
    facilitator.environment = "testnet"
    return facilitator


class TestFacilitatorIntegration:
    """Test facilitator integration end-to-end."""

    def test_seller_created_with_facilitator(self):
        """Test seller has facilitator configured."""
        facilitator = create_mock_facilitator()
        seller = create_seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Weather API",
            facilitator=facilitator,
        )
        assert seller._facilitator is not None

    def test_seller_without_facilitator(self):
        """Test seller without facilitator works."""
        seller = create_seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Weather API",
        )
        assert seller._facilitator is None

    def test_verify_payment_with_facilitator(self):
        """Test payment verification via facilitator."""
        facilitator = create_mock_facilitator()
        seller = create_seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Weather API",
            facilitator=facilitator,
        )

        payment_payload = {
            "x402Version": 2,
            "scheme": "exact",
            "payload": {
                "authorization": {
                    "from": "0xbuyer1234567890abcdef1234567890abcdef12",
                    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                    "value": "1000",
                    "validAfter": 0,
                    "validBefore": 9999999999,
                    "nonce": "0x" + "00" * 32,
                },
                "signature": "0xabc123...",
            },
        }

        accepted = {
            "scheme": "exact",
            "network": "eip155:84532",
            "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
            "amount": "1000",
            "payTo": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            "maxTimeoutSeconds": 345600,
        }
        payment_payload["network"] = accepted["network"]
        payment_payload["accepted"] = accepted

        is_valid, error, record = seller.verify_payment(
            payment_payload=payment_payload,
            accepted=accepted,
            verify_signature=False,
            settle_payment=False,
        )

        assert is_valid is True
        assert error == ""
        assert record is not None
        assert record.buyer_address == "0xbuyer1234567890abcdef1234567890abcdef12"
        assert record.status.value == "verified"

    def test_settle_payment_with_facilitator(self):
        """Test payment settlement via facilitator."""
        facilitator = create_mock_facilitator()
        seller = create_seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Weather API",
            facilitator=facilitator,
        )

        payment_payload = {
            "x402Version": 2,
            "scheme": "exact",
            "payload": {
                "authorization": {
                    "from": "0xbuyer1234567890abcdef1234567890abcdef12",
                    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                    "value": "1000",
                    "validAfter": 0,
                    "validBefore": 9999999999,
                    "nonce": "0x" + "00" * 32,
                },
                "signature": "0xabc123...",
            },
        }

        accepted = {
            "scheme": "exact",
            "network": "eip155:84532",
            "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
            "amount": "1000",
            "payTo": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            "maxTimeoutSeconds": 345600,
        }
        payment_payload["network"] = accepted["network"]
        payment_payload["accepted"] = accepted

        is_valid, error, record = seller.verify_payment(
            payment_payload=payment_payload,
            accepted=accepted,
            verify_signature=False,
            settle_payment=True,
        )

        assert is_valid is True
        assert error == ""
        assert record is not None
        assert record.status.value == "settled"

    def test_facilitator_verification_failure(self):
        """Test facilitator returns invalid."""
        facilitator = create_mock_facilitator(
            verify_result=VerifyResult(
                is_valid=False,
                payer="0xbuyer123",
                invalid_reason="insufficient_balance",
            )
        )
        seller = create_seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Weather API",
            facilitator=facilitator,
        )

        payment_payload = {
            "x402Version": 2,
            "scheme": "exact",
            "payload": {
                "authorization": {
                    "from": "0xbuyer123",
                    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                    "value": "1000",
                    "validAfter": 0,
                    "validBefore": 9999999999,
                    "nonce": "0x" + "00" * 32,
                },
                "signature": "0xabc123...",
            },
        }

        accepted = {
            "scheme": "exact",
            "network": "eip155:84532",
            "amount": "1000",
            "payTo": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
        }
        payment_payload["network"] = accepted["network"]
        payment_payload["accepted"] = accepted

        is_valid, error, record = seller.verify_payment(
            payment_payload=payment_payload,
            accepted=accepted,
            settle_payment=False,
        )

        assert is_valid is False
        assert "insufficient_balance" in error
        assert record is None

    def test_facilitator_settlement_failure(self):
        """Test facilitator settlement fails."""
        facilitator = create_mock_facilitator(
            settle_result=SettleResult(
                success=False,
                transaction="",
                network="eip155:84532",
                error_reason="invalid_signature",
                payer="0xbuyer123",
            )
        )
        seller = create_seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Weather API",
            facilitator=facilitator,
        )

        payment_payload = {
            "x402Version": 2,
            "scheme": "exact",
            "payload": {
                "authorization": {
                    "from": "0xbuyer123",
                    "to": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
                    "value": "1000",
                    "validAfter": 0,
                    "validBefore": 9999999999,
                    "nonce": "0x" + "00" * 32,
                },
                "signature": "0xinvalid...",
            },
        }

        accepted = {
            "scheme": "exact",
            "network": "eip155:84532",
            "amount": "1000",
            "payTo": "0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
        }
        payment_payload["network"] = accepted["network"]
        payment_payload["accepted"] = accepted

        is_valid, error, record = seller.verify_payment(
            payment_payload=payment_payload,
            accepted=accepted,
            settle_payment=True,
        )

        assert is_valid is False
        assert "Settlement failed" in error
        assert "invalid_signature" in error
        assert record is None


class TestFacilitatorFactory:
    """Test facilitator factory function."""

    def test_create_facilitator_testnet(self):
        """Test creating facilitator for testnet."""
        from omniclaw.seller import create_facilitator

        facilitator = create_facilitator(
            provider="circle",
            api_key="test_key",
            environment="testnet",
        )

        assert facilitator.base_url == "https://gateway-api-testnet.circle.com"
        assert facilitator.environment == "testnet"

    def test_create_facilitator_mainnet(self):
        """Test creating facilitator for mainnet."""
        from omniclaw.seller import create_facilitator

        facilitator = create_facilitator(
            provider="circle",
            api_key="test_key",
            environment="mainnet",
        )

        assert facilitator.base_url == "https://gateway-api.circle.com"
        assert facilitator.environment == "mainnet"

    def test_create_facilitator_requires_api_key(self):
        """Test facilitator requires API key."""
        from omniclaw.seller import create_facilitator

        with pytest.raises(ValueError, match="api_key"):
            create_facilitator(provider="circle", api_key="")

    def test_create_all_facilitators(self):
        """Test creating all supported facilitators."""
        from omniclaw.seller import SUPPORTED_FACILITATORS, create_facilitator

        for name in SUPPORTED_FACILITATORS:
            f = create_facilitator(provider=name, api_key="test_key")
            assert f.name == name, f"Expected {name}, got {f.name}"


class TestSellerAutoFacilitator:
    """Test seller auto-creates facilitator from API key."""

    def test_seller_with_circle_api_key(self):
        """Test seller auto-creates facilitator when API key provided."""
        seller = create_seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Weather API",
            circle_api_key="test_key_123",
        )

        assert seller._facilitator is not None
        assert seller._facilitator.environment == "testnet"

    def test_seller_with_mainnet_environment(self):
        """Test seller with mainnet environment."""
        seller = create_seller(
            seller_address="0x742d35Cc6634C0532925a3b844Bc9e7595f1E123",
            name="Weather API",
            circle_api_key="test_key_123",
            facilitator_environment="mainnet",
        )

        assert seller._facilitator is not None
        assert seller._facilitator.environment == "mainnet"
        assert seller._facilitator.base_url == "https://gateway-api.circle.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
