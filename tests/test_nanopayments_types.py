"""
Tests for nanopayments type definitions.

Phase 1: Foundation
"""

from omniclaw.protocols.nanopayments import (
    DepositResult,
    EIP3009Authorization,
    GatewayBalance,
    NanopaymentResult,
    PaymentPayload,
    PaymentPayloadInner,
    PaymentRequirements,
    PaymentRequirementsExtra,
    PaymentRequirementsKind,
    SettleResponse,
    SupportedKind,
    VerifyResponse,
    WithdrawResult,
)


class TestPaymentRequirementsExtra:
    """Tests for PaymentRequirementsExtra."""

    def test_create_with_required_fields(self):
        extra = PaymentRequirementsExtra(
            name="GatewayWalletBatched",
            version="1",
            verifying_contract="0xGatewayWallet1234567890123456789012345678901234567",
        )
        assert extra.name == "GatewayWalletBatched"
        assert extra.version == "1"
        assert extra.verifying_contract == "0xGatewayWallet1234567890123456789012345678901234567"

    def test_to_dict(self):
        extra = PaymentRequirementsExtra(
            name="GatewayWalletBatched",
            version="1",
            verifying_contract="0xGateway123",
        )
        d = extra.to_dict()
        assert d["name"] == "GatewayWalletBatched"
        assert d["version"] == "1"
        assert d["verifyingContract"] == "0xGateway123"

    def test_from_dict(self):
        data = {
            "name": "GatewayWalletBatched",
            "version": "1",
            "verifyingContract": "0xGateway123",
        }
        extra = PaymentRequirementsExtra.from_dict(data)
        assert extra.name == "GatewayWalletBatched"
        assert extra.version == "1"
        assert extra.verifying_contract == "0xGateway123"

    def test_from_dict_with_missing_fields(self):
        data = {}
        extra = PaymentRequirementsExtra.from_dict(data)
        assert extra.name == ""
        assert extra.version == ""
        assert extra.verifying_contract == ""


class TestPaymentRequirementsKind:
    """Tests for PaymentRequirementsKind."""

    def test_create_with_required_fields(self):
        extra = PaymentRequirementsExtra(
            name="GatewayWalletBatched",
            version="1",
            verifying_contract="0xGateway123",
        )
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0xUSDC123",
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0xSeller1234567890123456789012345678901234567",
            extra=extra,
        )
        assert kind.scheme == "exact"
        assert kind.network == "eip155:5042002"
        assert kind.amount == "1000"
        assert kind.extra.name == "GatewayWalletBatched"

    def test_to_dict(self):
        extra = PaymentRequirementsExtra(
            name="GatewayWalletBatched",
            version="1",
            verifying_contract="0xGateway123",
        )
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0xUSDC123",
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0xSeller123",
            extra=extra,
        )
        d = kind.to_dict()
        assert d["scheme"] == "exact"
        assert d["network"] == "eip155:5042002"
        assert d["maxTimeoutSeconds"] == 345600
        assert d["payTo"] == "0xSeller123"
        assert d["extra"]["name"] == "GatewayWalletBatched"

    def test_from_dict(self):
        data = {
            "scheme": "exact",
            "network": "eip155:5042002",
            "asset": "0xUSDC123",
            "amount": "1000",
            "maxTimeoutSeconds": 345600,
            "payTo": "0xSeller123",
            "extra": {
                "name": "GatewayWalletBatched",
                "version": "1",
                "verifyingContract": "0xGateway123",
            },
        }
        kind = PaymentRequirementsKind.from_dict(data)
        assert kind.scheme == "exact"
        assert kind.network == "eip155:5042002"
        assert kind.extra.name == "GatewayWalletBatched"


class TestPaymentRequirements:
    """Tests for PaymentRequirements."""

    def test_find_gateway_kind_returns_match(self):
        extra = PaymentRequirementsExtra(
            name="GatewayWalletBatched",
            version="1",
            verifying_contract="0xGateway123",
        )
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0xUSDC123",
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0xSeller123",
            extra=extra,
        )
        reqs = PaymentRequirements(x402_version=2, accepts=(kind,))
        found = reqs.find_gateway_kind()
        assert found is not None
        assert found.network == "eip155:5042002"

    def test_find_gateway_kind_returns_none_when_not_found(self):
        extra = PaymentRequirementsExtra(
            name="NotGatewayBatched",
            version="1",
            verifying_contract="0xGateway123",
        )
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0xUSDC123",
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0xSeller123",
            extra=extra,
        )
        reqs = PaymentRequirements(x402_version=2, accepts=(kind,))
        found = reqs.find_gateway_kind()
        assert found is None

    def test_to_dict_and_from_dict_roundtrip(self):
        extra = PaymentRequirementsExtra(
            name="GatewayWalletBatched",
            version="1",
            verifying_contract="0xGateway123",
        )
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0xUSDC123",
            amount="1000",
            max_timeout_seconds=345600,
            pay_to="0xSeller123",
            extra=extra,
        )
        original = PaymentRequirements(x402_version=2, accepts=(kind,))
        d = original.to_dict()
        restored = PaymentRequirements.from_dict(d)
        assert restored.x402_version == 2
        assert len(restored.accepts) == 1
        assert restored.accepts[0].network == "eip155:5042002"


class TestEIP3009Authorization:
    """Tests for EIP3009Authorization."""

    def test_create_with_valid_fields(self):
        auth = EIP3009Authorization.create(
            from_address="0xBuyer1234567890123456789012345678901234567",
            to="0xSeller1234567890123456789012345678901234567",
            value="1000",
            valid_before=1742000000,
            nonce="0x" + "ab" * 32,
        )
        assert auth.from_address == "0xBuyer1234567890123456789012345678901234567"
        assert auth.to == "0xSeller1234567890123456789012345678901234567"
        assert auth.value == "1000"
        assert auth.valid_after == "0"
        assert auth.valid_before == "1742000000"
        assert auth.nonce.startswith("0x")
        assert len(auth.nonce) == 66  # 0x + 64 hex chars

    def test_to_dict(self):
        auth = EIP3009Authorization.create(
            from_address="0xBuyer123",
            to="0xSeller123",
            value="1000",
            valid_before=1742000000,
            nonce="0x" + "ab" * 32,
        )
        d = auth.to_dict()
        assert d["from"] == "0xBuyer123"
        assert d["to"] == "0xSeller123"
        assert d["value"] == "1000"
        assert d["validAfter"] == "0"
        assert d["validBefore"] == "1742000000"

    def test_from_dict(self):
        data = {
            "from": "0xBuyer123",
            "to": "0xSeller123",
            "value": "1000",
            "validAfter": "0",
            "validBefore": "1742000000",
            "nonce": "0x" + "ab" * 32,
        }
        auth = EIP3009Authorization.from_dict(data)
        assert auth.from_address == "0xBuyer123"
        assert auth.value == "1000"
        assert auth.valid_after == "0"


class TestPaymentPayload:
    """Tests for PaymentPayload."""

    def test_to_dict_structure(self):
        auth = EIP3009Authorization.create(
            from_address="0xBuyer1234567890123456789012345678901234567",
            to="0xSeller1234567890123456789012345678901234567",
            value="1000",
            valid_before=1742000000,
            nonce="0x" + "ab" * 32,
        )
        payload = PaymentPayload(
            x402_version=2,
            scheme="exact",
            network="eip155:5042002",
            payload=PaymentPayloadInner(
                signature="0x" + "ff" * 64 + "1b",
                authorization=auth,
            ),
        )

        d = payload.to_dict()
        assert d["x402Version"] == 2
        assert d["scheme"] == "exact"
        assert d["network"] == "eip155:5042002"
        assert "signature" in d["payload"]
        assert "authorization" in d["payload"]
        assert (
            d["payload"]["authorization"]["from"] == "0xBuyer1234567890123456789012345678901234567"
        )

    def test_from_dict_roundtrip(self):
        original = {
            "x402Version": 2,
            "scheme": "exact",
            "network": "eip155:5042002",
            "payload": {
                "signature": "0x" + "ff" * 64 + "1b",
                "authorization": {
                    "from": "0xBuyer123",
                    "to": "0xSeller123",
                    "value": "1000",
                    "validAfter": "0",
                    "validBefore": "1742000000",
                    "nonce": "0x" + "ab" * 32,
                },
            },
        }

        payload = PaymentPayload.from_dict(original)
        assert payload.x402_version == 2
        assert payload.scheme == "exact"
        assert payload.network == "eip155:5042002"
        assert payload.payload.authorization.from_address == "0xBuyer123"

        # Roundtrip
        regenerated = payload.to_dict()
        assert regenerated == original


class TestVerifyResponse:
    """Tests for VerifyResponse."""

    def test_valid_response(self):
        resp = VerifyResponse(is_valid=True, payer="0xBuyer123", invalid_reason=None)
        assert resp.is_valid is True
        assert resp.payer == "0xBuyer123"
        assert resp.invalid_reason is None

    def test_invalid_response(self):
        resp = VerifyResponse(is_valid=False, payer=None, invalid_reason="invalid_signature")
        assert resp.is_valid is False
        assert resp.payer is None
        assert resp.invalid_reason == "invalid_signature"

    def test_to_dict(self):
        resp = VerifyResponse(is_valid=True, payer="0xBuyer123", invalid_reason=None)
        d = resp.to_dict()
        assert d["isValid"] is True
        assert d["payer"] == "0xBuyer123"


class TestSettleResponse:
    """Tests for SettleResponse."""

    def test_successful_response(self):
        resp = SettleResponse(
            success=True,
            transaction="batch-ref-123",
            payer="0xBuyer123",
            error_reason=None,
        )
        assert resp.success is True
        assert resp.transaction == "batch-ref-123"
        assert resp.payer == "0xBuyer123"

    def test_failed_response(self):
        resp = SettleResponse(
            success=False,
            transaction=None,
            payer="0xBuyer123",
            error_reason="insufficient_balance",
        )
        assert resp.success is False
        assert resp.transaction is None
        assert resp.error_reason == "insufficient_balance"


class TestSupportedKind:
    """Tests for SupportedKind."""

    def test_verifying_contract_extraction(self):
        kind = SupportedKind(
            x402_version=2,
            scheme="exact",
            network="eip155:5042002",
            extra={
                "verifyingContract": "0xGateway123",
                "usdcAddress": "0xUSDC123",
            },
        )
        assert kind.verifying_contract == "0xGateway123"
        assert kind.usdc_address == "0xUSDC123"

    def test_no_extra_returns_none(self):
        kind = SupportedKind(
            x402_version=2,
            scheme="exact",
            network="eip155:5042002",
            extra=None,
        )
        assert kind.verifying_contract is None
        assert kind.usdc_address is None

    def test_from_dict(self):
        data = {
            "x402Version": 2,
            "scheme": "exact",
            "network": "eip155:5042002",
            "extra": {"verifyingContract": "0xGateway123"},
        }
        kind = SupportedKind.from_dict(data)
        assert kind.x402_version == 2
        assert kind.network == "eip155:5042002"
        assert kind.verifying_contract == "0xGateway123"


class TestGatewayBalance:
    """Tests for GatewayBalance."""

    def test_decimal_properties(self):
        balance = GatewayBalance(
            total=1_000_000,  # 1 USDC
            available=500_000,  # 0.5 USDC
            formatted_total="1.000000 USDC",
            formatted_available="0.500000 USDC",
        )
        assert balance.total_decimal == "1.000000"
        assert balance.available_decimal == "0.500000"

    def test_to_dict(self):
        balance = GatewayBalance(
            total=1_000_000,
            available=500_000,
            formatted_total="1.000000 USDC",
            formatted_available="0.500000 USDC",
        )
        d = balance.to_dict()
        assert d["total"] == 1_000_000
        assert d["available"] == 500_000


class TestNanopaymentResult:
    """Tests for NanopaymentResult."""

    def test_creation(self):
        result = NanopaymentResult(
            success=True,
            payer="0xBuyer123",
            seller="0xSeller123",
            transaction="batch-ref",
            amount_usdc="0.001",
            amount_atomic="1000",
            network="eip155:5042002",
            response_data={"result": "success"},
        )
        assert result.success is True
        assert result.payer == "0xBuyer123"
        assert result.amount_usdc == "0.001"
        assert result.is_nanopayment is True

    def test_response_data_none_for_direct_transfer(self):
        result = NanopaymentResult(
            success=True,
            payer="0xBuyer123",
            seller="0xSeller123",
            transaction="batch-ref",
            amount_usdc="0.001",
            amount_atomic="1000",
            network="eip155:5042002",
            response_data=None,
        )
        assert result.response_data is None


class TestDepositResult:
    """Tests for DepositResult."""

    def test_creation(self):
        result = DepositResult(
            approval_tx_hash="0xApprovalHash",
            deposit_tx_hash="0xDepositHash",
            amount=10_000_000,  # 10 USDC
            formatted_amount="10.000000 USDC",
        )
        assert result.approval_tx_hash == "0xApprovalHash"
        assert result.deposit_tx_hash == "0xDepositHash"
        assert result.amount == 10_000_000


class TestWithdrawResult:
    """Tests for WithdrawResult."""

    def test_creation(self):
        result = WithdrawResult(
            mint_tx_hash="0xMintHash",
            amount=5_000_000,
            formatted_amount="5.000000 USDC",
            source_chain="eip155:5042002",
            destination_chain="eip155:84532",
            recipient="0xRecipient1234567890123456789012345678901234567",
        )
        assert result.mint_tx_hash == "0xMintHash"
        assert result.amount == 5_000_000
        assert result.destination_chain == "eip155:84532"
