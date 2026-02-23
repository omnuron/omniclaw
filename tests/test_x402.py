"""
Test suite for x402 protocol implementation.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch
from omniclaw.core.types import Network, PaymentMethod, PaymentStatus
from omniclaw.protocols.x402 import (
    X402Adapter,
    PaymentRequirements,
    PaymentPayload,
)


class TestPaymentRequirements:
    """Test payment requirements parsing."""
    
    def test_get_amount_usdc(self):
        """Test USDC amount conversion."""
        req = PaymentRequirements(
            scheme="exact",
            network="arc-testnet",
            max_amount_required="100000",  # 0.1 USDC in subunits
            resource="http://example.com",
            description="Test",
            recipient="0x123"
        )
        
        amount = req.get_amount_usdc()
        assert amount == Decimal("0.1")
    
    def test_from_header_v1(self):
        """Test parsing from V1 header."""
        import base64
        import json
        
        data = {
            "scheme": "exact",
            "network": "base",
            "maxAmountRequired": "50000",
            "resource": "http://test.com",
            "description": "Test payment",
            "paymentAddress": "0xabc"
        }
        
        header_value = base64.b64encode(json.dumps(data).encode()).decode()
        req = PaymentRequirements.from_header(header_value)
        
        assert req.scheme == "exact"
        assert req.network == "base"
        assert req.recipient == "0xabc"


class TestPaymentPayload:
    """Test payment payload generation."""
    
    def test_to_header(self):
        """Test payload encoding to header."""
        payload = PaymentPayload(
            x402_version=2,
            scheme="exact",
            network="arc-testnet",
            payload={
                "fromAddress": "0x123",
                "toAddress": "0x456",
                "amount": "0.1",
            },
            resource="http://test.com"
        )
        
        header = payload.to_header()
        
        # Should be base64 encoded
        assert len(header) > 0
        
        # Should decode to JSON
        import base64
        import json
        decoded = json.loads(base64.b64decode(header))
        assert decoded["x402Version"] == 2
        assert decoded["scheme"] == "exact"


class TestX402Adapter:
    """Test x402 adapter functionality."""
    
    @pytest.fixture
    def mock_config(self):
        """Create mock config."""
        config = Mock()
        config.network = Network.ARC_TESTNET
        config.http_timeout = 30.0
        return config
    
    @pytest.fixture
    def mock_wallet_service(self):
        """Create mock wallet service."""
        service = Mock()
        service.transfer = AsyncMock(return_value=Mock(
            id="tx_123",
            tx_hash="0xabc",
        ))
        service.get_wallet = Mock(return_value=Mock(
            blockchain="ARC-TESTNET"
        ))
        return service
    
    @pytest.fixture
    def adapter(self, mock_config, mock_wallet_service):
        """Create X402Adapter instance."""
        return X402Adapter(mock_config, mock_wallet_service)
    
    def test_supports_http_urls(self, adapter):
        """Test that adapter recognizes HTTP URLs."""
        assert adapter.supports("http://example.com") is True
        assert adapter.supports("https://example.com") is True
        assert adapter.supports("0x1234567890") is False
    
    def test_method_property(self, adapter):
        """Test payment method identification."""
        assert adapter.method == PaymentMethod.X402
    
    @pytest.mark.asyncio
    async def test_cross_chain_detection(self, adapter, mock_wallet_service):
        """Test cross-chain payment detection."""
        with patch.object(adapter, '_request_with_402_check', new_callable=AsyncMock) as mock_request:
            # Simulate 402 response
            mock_response = Mock()
            mock_response.status_code = 402
            
            mock_requirements = PaymentRequirements(
                scheme="exact",
                network="base-sepolia",  # Different from ARC
                max_amount_required="100000",
                resource="http://test.com",
                description="Test",
                recipient="0x123"
            )
            
            mock_request.return_value = (mock_response, mock_requirements)
            
            # Should detect cross-chain and use GatewayAdapter
            with patch('omniclaw.protocols.gateway.GatewayAdapter') as mock_gateway:
                mock_gateway_instance = Mock()
                mock_gateway_instance.execute = AsyncMock(return_value=Mock(
                    success=True,
                    transaction_id="cctp_tx",
                ))
                mock_gateway.return_value = mock_gateway_instance
                
                result = await adapter.execute(
                    wallet_id="wallet_1",
                    recipient="http://test.com/premium",
                    amount=Decimal("1.0")
                )
                
                # Should have called gateway for cross-chain
                assert mock_gateway.called


class TestX402Integration:
    """Integration tests for x402 protocol."""
    
    @pytest.mark.asyncio
    async def test_same_chain_payment_flow(self):
        """Test complete same-chain x402 flow."""
        # This would test the full flow end-to-end
        # Mock HTTP client, wallet service, etc.
        pass  # Placeholder for full integration test


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
