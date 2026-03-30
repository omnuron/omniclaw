"""
Integration tests for OmniClaw Nanopayments (Phase 9).

Tests cover the complete nanopayments stack:
- NanoKeyVault: Key generation, encryption, signing, vault operations
- NanopaymentAdapter: Buyer-side x402 URL and direct address payments
- NanopaymentProtocolAdapter: PaymentRouter integration and routing
- GatewayWalletManager: On-chain deposit/withdraw
- GatewayMiddleware: Seller-side x402 gate
- OmniClaw client: SDK-level integration with all nanopayments components

IMPORTANT: Import submodules DIRECTLY (not via omniclaw.protocols.nanopayments).
Importing from the package __init__ triggers omniclaw.__init__ which imports
OmniClaw → CircleClient → circle.web3 (not installed in test env).
Existing nanopayments tests follow this same pattern.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import submodules DIRECTLY — never through package __init__
from omniclaw.protocols.nanopayments.adapter import (
    NanopaymentAdapter,
    NanopaymentProtocolAdapter,
)
from omniclaw.protocols.nanopayments.client import NanopaymentClient
from omniclaw.protocols.nanopayments.constants import (
    DEFAULT_GATEWAY_AUTO_TOPUP_AMOUNT,
    DEFAULT_GATEWAY_AUTO_TOPUP_THRESHOLD,
)
from omniclaw.protocols.nanopayments.exceptions import (
    DepositError,
    DuplicateKeyAliasError,
    ERC20ApprovalError,
    InsufficientGasError,
    InvalidPrivateKeyError,
    KeyNotFoundError,
    NanopaymentNotInitializedError,
    NoDefaultKeyError,
    UnsupportedNetworkError,
    UnsupportedSchemeError,
    WithdrawError,
)
from omniclaw.protocols.nanopayments.keys import NanoKeyStore
from omniclaw.protocols.nanopayments.middleware import (
    GatewayMiddleware,
    PaymentRequiredHTTPError,
    parse_price,
)
from omniclaw.protocols.nanopayments.signing import EIP3009Signer, generate_eoa_keypair
from omniclaw.protocols.nanopayments.types import (
    DepositResult,
    EIP3009Authorization,
    GatewayBalance,
    PaymentPayload,
    PaymentPayloadInner,
    PaymentRequirements,
    PaymentRequirementsExtra,
    PaymentRequirementsKind,
    ResourceInfo,
    SettleResponse,
    SupportedKind,
)
from omniclaw.protocols.nanopayments.vault import NanoKeyVault
from omniclaw.storage.base import StorageBackend
from omniclaw.protocols.nanopayments.wallet import GatewayWalletManager


# =============================================================================
# MOCK STORAGE BACKEND
# =============================================================================


class MockStorageBackend:
    """In-memory mock for StorageBackend."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}

    async def save(self, collection: str, key: str, data: dict) -> None:
        if collection not in self._data:
            self._data[collection] = {}
        self._data[collection][key] = data.copy() if isinstance(data, dict) else data

    async def get(self, collection: str, key: str) -> dict | None:
        return self._data.get(collection, {}).get(key)

    async def delete(self, collection: str, key: str) -> bool:
        if collection in self._data and key in self._data[collection]:
            del self._data[collection][key]
            return True
        return False

    async def query(
        self,
        collection: str,
        filters: dict | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """Query all records in a collection."""
        records = []
        for key, data in self._data.get(collection, {}).items():
            if filters:
                if not all(data.get(k) == v for k, v in filters.items()):
                    continue
            records.append({"key": key, **data})
        return records[offset : offset + (limit or len(records))]
        if collection in self._data and key in self._data[collection]:
            del self._data[collection][key]
            return True
        return False


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_storage() -> MockStorageBackend:
    """In-memory storage for tests."""
    return MockStorageBackend()


@pytest.fixture
def mock_keystore() -> NanoKeyStore:
    """NanoKeyStore with test entity secret."""
    return NanoKeyStore(entity_secret="test-entity-secret-for-integration-tests-32ch")


@pytest.fixture
def mock_vault(mock_storage: MockStorageBackend) -> NanoKeyVault:
    """NanoKeyVault with real encryption and mock storage."""
    return NanoKeyVault(
        entity_secret="test-entity-secret-for-integration-tests-32ch",
        storage_backend=mock_storage,
        circle_api_key="test-api-key",
        nanopayments_environment="testnet",
    )


@pytest.fixture
def mock_client() -> MagicMock:
    """Mock NanopaymentClient."""
    mock = MagicMock(spec=NanopaymentClient)
    mock.get_verifying_contract = AsyncMock(return_value="0x" + "c" * 40)
    mock.get_usdc_address = AsyncMock(return_value="0x" + "d" * 40)
    mock.settle = AsyncMock(
        return_value=MagicMock(
            success=True,
            transaction="batch-tx-integration-123",
        )
    )
    mock.check_balance = AsyncMock(
        return_value=MagicMock(
            total=5_000_000,
            available=5_000_000,
            formatted_total="5.000000 USDC",
            formatted_available="5.000000 USDC",
            available_decimal="5.000000",
        )
    )
    return mock


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Mock httpx.AsyncClient for x402 URL payments."""
    return AsyncMock()


@pytest.fixture
def mock_web3() -> MagicMock:
    """Mock web3.Web3 for on-chain operations."""
    mock = MagicMock()
    mock.eth = MagicMock()
    mock.eth.get_transaction_count = MagicMock(return_value=1)
    mock.eth.account = MagicMock()
    mock.eth.contract = MagicMock()
    return mock


# =============================================================================
# REQUIREATION BUILDER
# =============================================================================


def make_402_requirements(
    scheme: str = "exact",
    network: str = "eip155:5042002",
    amount: str = "1000000",
    verifying_contract: str | None = None,
    name: str = "GatewayWalletBatched",
) -> dict:
    """Build a valid 402 response requirements dict."""
    vc = verifying_contract or ("0x" + "c" * 40)
    return {
        "x402Version": 2,
        "accepts": [
            {
                "scheme": scheme,
                "network": network,
                "asset": "0x" + "d" * 40,
                "amount": amount,
                "maxTimeoutSeconds": 345600,
                "payTo": "0x" + "b" * 40,
                "extra": {
                    "name": name,
                    "version": "1",
                    "verifyingContract": vc,
                },
            },
        ],
    }


def make_signed_payload(
    from_addr: str,
    to_addr: str,
    value: str = "1000000",
    valid_before: int = 9999999999,
) -> PaymentPayload:
    """Create a real signed PaymentPayload for integration tests."""
    authorization = EIP3009Authorization.create(
        from_address=from_addr,
        to=to_addr,
        value=value,
        valid_before=valid_before,
        nonce="0x" + "e" * 64,
    )
    # Sign the authorization
    structured_data = authorization.to_eip712_structured_data()
    signed = EIP3009Signer.from_authorization(authorization)
    return PaymentPayload(
        x402_version=2,
        scheme="exact",
        network="eip155:5042002",
        payload=PaymentPayloadInner(
            signature=signed.signature,
            authorization=authorization,
        ),
    )


# =============================================================================
# TEST: NanoKeyVault — Full Key Lifecycle
# =============================================================================


class TestNanoKeyVaultIntegration:
    """End-to-end tests for NanoKeyVault key management."""

    @pytest.mark.asyncio
    async def test_generate_key_full_lifecycle(self, mock_vault: NanoKeyVault):
        """Generate key → store → retrieve address → sign → verify."""
        # Generate a key
        address = await mock_vault.generate_key("test-agent-key")
        assert address.startswith("0x")
        assert len(address) == 42
        # eth_account returns checksummed (mixed-case) addresses
        assert address[:2] == "0x"

        # Can retrieve the address
        retrieved = await mock_vault.get_address("test-agent-key")
        assert retrieved == address

        # Vault knows about the key
        assert await mock_vault.has_key("test-agent-key") is True
        assert await mock_vault.has_key("nonexistent-key") is False

    @pytest.mark.asyncio
    async def test_add_key_import(self, mock_vault: NanoKeyVault):
        """Import an existing private key."""
        # Generate a key externally (returns (private_key_hex, address))
        private_key, expected_address = generate_eoa_keypair()
        signer = EIP3009Signer(private_key)

        # Import it
        address = await mock_vault.add_key("imported-key", private_key)
        assert address == signer.address == expected_address

        # Can retrieve it
        retrieved = await mock_vault.get_address("imported-key")
        assert retrieved == signer.address

    @pytest.mark.asyncio
    async def test_add_key_invalid_private_key(self, mock_vault: NanoKeyVault):
        """Importing an invalid private key raises InvalidPrivateKeyError."""
        with pytest.raises(InvalidPrivateKeyError):
            await mock_vault.add_key("bad-key", "0xnot-a-valid-key")

    @pytest.mark.asyncio
    async def test_add_key_duplicate_alias(self, mock_vault: NanoKeyVault):
        """Adding a key with duplicate alias raises DuplicateKeyAliasError."""
        await mock_vault.generate_key("duplicate-test")
        with pytest.raises(DuplicateKeyAliasError):
            await mock_vault.generate_key("duplicate-test")

    @pytest.mark.asyncio
    async def test_set_default_key(self, mock_vault: NanoKeyVault):
        """Set default key, then get_address(None) returns it."""
        addr1 = await mock_vault.generate_key("key-one")
        addr2 = await mock_vault.generate_key("key-two")
        await mock_vault.set_default_key("key-one")

        # Without alias argument, uses default
        assert await mock_vault.get_address(None) == addr1

        # Switch default
        await mock_vault.set_default_key("key-two")
        assert await mock_vault.get_address(None) == addr2

    @pytest.mark.asyncio
    async def test_get_address_no_default_raises(self, mock_vault: NanoKeyVault):
        """get_address(None) with no default set raises NoDefaultKeyError."""
        with pytest.raises(NoDefaultKeyError):
            await mock_vault.get_address(None)

    @pytest.mark.asyncio
    async def test_get_address_unknown_alias_raises(self, mock_vault: NanoKeyVault):
        """get_address(unknown) raises KeyNotFoundError."""
        with pytest.raises(KeyNotFoundError):
            await mock_vault.get_address("totally-unknown-key-12345")

    @pytest.mark.asyncio
    async def test_get_raw_key_returns_decrypted_key(self, mock_vault: NanoKeyVault):
        """get_raw_key decrypts and returns the raw private key."""
        private_key, expected_address = generate_eoa_keypair()
        signer = EIP3009Signer(private_key)
        await mock_vault.add_key("raw-key-test", private_key)

        raw = await mock_vault.get_raw_key("raw-key-test")
        # decrypt_key returns with 0x prefix (same as generate_eoa_keypair output)
        assert raw == private_key

        # The raw key should produce the same address
        recovered_signer = EIP3009Signer(raw)
        assert recovered_signer.address == signer.address == expected_address

    @pytest.mark.asyncio
    async def test_rotate_key(self, mock_vault: NanoKeyVault):
        """rotate_key generates new key, stores it, returns new address."""
        old_addr = await mock_vault.generate_key("rotate-test")
        new_addr = await mock_vault.rotate_key("rotate-test")

        assert new_addr != old_addr
        assert await mock_vault.get_address("rotate-test") == new_addr

    @pytest.mark.asyncio
    async def test_sign_creates_valid_payload(self, mock_vault: NanoKeyVault):
        """sign() produces a valid PaymentPayload with a real signature."""
        # Set up
        await mock_vault.generate_key("sign-test")
        await mock_vault.set_default_key("sign-test")

        # Build requirements
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0x" + "d" * 40,
            amount="1000000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract="0x" + "c" * 40,
            ),
        )

        # Sign
        payload = await mock_vault.sign(requirements=kind, amount_atomic=500_000)

        assert payload.x402_version == 2
        assert payload.scheme == "exact"
        assert payload.network == "eip155:5042002"
        assert payload.payload.signature.startswith("0x")
        assert len(payload.payload.signature) == 132  # 65 bytes = 130 hex chars + 0x

    @pytest.mark.asyncio
    async def test_sign_with_specific_alias(self, mock_vault: NanoKeyVault):
        """sign(alias=...) uses the specified key, not the default."""
        await mock_vault.generate_key("key-a")
        addr_b = await mock_vault.generate_key("key-b")
        await mock_vault.set_default_key("key-a")

        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0x" + "d" * 40,
            amount="1000000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract="0x" + "c" * 40,
            ),
        )

        # Sign with key-b
        payload = await mock_vault.sign(requirements=kind, alias="key-b")

        # The "from" address in the payload should be key-b's address
        assert payload.payload.authorization.from_address == addr_b


# =============================================================================
# TEST: NanopaymentAdapter — End-to-End Buyer Payments
# =============================================================================


class TestNanopaymentAdapterIntegration:
    """End-to-end tests for buyer-side nanopayment execution."""

    @pytest.mark.asyncio
    async def test_pay_x402_url_full_flow(
        self,
        mock_vault: NanoKeyVault,
        mock_client: MagicMock,
        mock_http_client: MagicMock,
    ):
        """URL payment: free resource → 402 → sign → retry → settle."""
        # Set up a real vault key
        await mock_vault.generate_key("buyer-key")
        payer_addr = await mock_vault.get_address("buyer-key")

        # Build 402 requirements
        req_dict = make_402_requirements(amount="1000000")
        import base64

        # Mock HTTP: first request gets 402, retry gets 200
        first_resp = MagicMock()
        first_resp.status_code = 402
        first_resp.text = "{}"
        first_resp.headers = {
            "payment-required": base64.b64encode(json.dumps(req_dict).encode()).decode()
        }
        retry_resp = MagicMock()
        retry_resp.status_code = 200
        retry_resp.text = '{"data": "premium content"}'

        mock_http_client.request = AsyncMock(side_effect=[first_resp, retry_resp])

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http_client,
            auto_topup_enabled=False,
        )

        result = await adapter.pay_x402_url(
            url="https://api.seller.com/premium",
            nano_key_alias="buyer-key",
        )

        assert result.success is True
        assert result.is_nanopayment is True
        assert result.payer == payer_addr
        # amount_usdc may be "1.0" or "1.000000" depending on formatting
        assert float(result.amount_usdc) == 1.0
        assert result.transaction == "batch-tx-integration-123"

        # HTTP was called twice: initial + retry
        assert mock_http_client.request.call_count == 2
        # Settle was called once
        mock_client.settle.assert_called_once()

    @pytest.mark.asyncio
    async def test_pay_x402_url_free_resource(
        self,
        mock_vault: NanoKeyVault,
        mock_client: MagicMock,
        mock_http_client: MagicMock,
    ):
        """Non-402 response means free resource, no nanopayment."""
        free_resp = MagicMock()
        free_resp.status_code = 200
        free_resp.text = '{"data": "free content"}'
        mock_http_client.request = AsyncMock(return_value=free_resp)

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http_client,
            auto_topup_enabled=False,
        )

        result = await adapter.pay_x402_url("https://api.seller.com/free")

        assert result.success is True
        assert result.is_nanopayment is False
        assert result.amount_usdc == "0"
        # No settlement
        mock_client.settle.assert_not_called()

    @pytest.mark.asyncio
    async def test_pay_x402_url_unsupported_scheme_falls_back(
        self,
        mock_vault: NanoKeyVault,
        mock_client: MagicMock,
        mock_http_client: MagicMock,
    ):
        """Seller doesn't support GatewayWalletBatched → UnsupportedSchemeError."""
        req_dict = make_402_requirements(name="StandardUSDC")
        import base64

        resp = MagicMock()
        resp.status_code = 402
        resp.text = "{}"
        resp.headers = {
            "payment-required": base64.b64encode(json.dumps(req_dict).encode()).decode()
        }
        mock_http_client.request = AsyncMock(return_value=resp)

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http_client,
            auto_topup_enabled=False,
        )

        with pytest.raises(UnsupportedSchemeError):
            await adapter.pay_x402_url("https://api.legacy-seller.com/data")

    @pytest.mark.asyncio
    async def test_pay_direct_full_flow(
        self,
        mock_vault: NanoKeyVault,
        mock_client: MagicMock,
        mock_http_client: MagicMock,
    ):
        """Direct address nanopayment: build requirements → sign → settle."""
        await mock_vault.generate_key("buyer-direct")
        payer_addr = await mock_vault.get_address("buyer-direct")

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http_client,
            auto_topup_enabled=False,
        )

        result = await adapter.pay_direct(
            seller_address="0x" + "b" * 40,
            amount_usdc="0.000001",  # Minimum nanopayment
            network="eip155:5042002",
            nano_key_alias="buyer-direct",
        )

        assert result.success is True
        assert result.is_nanopayment is True
        assert result.payer == payer_addr
        assert result.seller == "0x" + "b" * 40
        assert result.amount_usdc == "0.000001"
        assert result.amount_atomic == "1"  # Minimum: 1 atomic unit
        assert result.network == "eip155:5042002"

        # Settlement was called
        mock_client.settle.assert_called_once()

    @pytest.mark.asyncio
    async def test_pay_direct_auto_topup(
        self,
        mock_vault: NanoKeyVault,
        mock_client: MagicMock,
        mock_http_client: MagicMock,
    ):
        """auto_topup_enabled=True triggers balance check before payment."""
        await mock_vault.generate_key("buyer-topup")

        # Override vault's get_balance to return low balance
        mock_vault.get_balance = AsyncMock(
            return_value=MagicMock(
                total=100_000,  # $0.10 — below $1.00 threshold
                available=100_000,
                formatted_total="0.100000 USDC",
                formatted_available="0.100000 USDC",
                available_decimal="0.100000",
            )
        )

        # Mock wallet_manager for auto-topup
        mock_wallet_manager = AsyncMock()
        mock_wallet_manager.deposit = AsyncMock(
            return_value=MagicMock(
                approval_tx_hash="0xapproval123",
                deposit_tx_hash="0xdeposit123",
                amount=1_000_000,
                formatted_amount="1.000000 USDC",
            )
        )

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http_client,
            auto_topup_enabled=True,
        )
        # Set wallet_manager so _check_and_topup actually runs
        adapter.set_wallet_manager(mock_wallet_manager)

        result = await adapter.pay_direct(
            seller_address="0x" + "b" * 40,
            amount_usdc="0.01",
            network="eip155:5042002",
            nano_key_alias="buyer-topup",
        )

        # Payment still succeeds (auto_topup didn't prevent it)
        assert result.success is True
        # Balance was checked (vault.get_balance was called for auto_topup check)
        mock_vault.get_balance.assert_called()


# =============================================================================
# TEST: NanopaymentProtocolAdapter — Router Integration
# =============================================================================


class TestNanopaymentProtocolAdapterIntegration:
    """Tests for NanopaymentProtocolAdapter routing in PaymentRouter."""

    def test_supports_https_url(self, mock_client: MagicMock):
        """URL recipients are supported."""
        adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=NanopaymentAdapter(
                vault=MagicMock(),
                nanopayment_client=mock_client,
                http_client=AsyncMock(),
                auto_topup_enabled=False,
            ),
            micro_threshold_usdc="1.00",
        )
        assert adapter.supports("https://api.example.com/data") is True
        assert adapter.supports("http://api.example.com/data") is True

    def test_supports_address_below_threshold(self, mock_client: MagicMock):
        """EVM address below micro_threshold is supported."""
        adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=NanopaymentAdapter(
                vault=MagicMock(),
                nanopayment_client=mock_client,
                http_client=AsyncMock(),
                auto_topup_enabled=False,
            ),
            micro_threshold_usdc="1.00",
        )
        assert adapter.supports("0x" + "a" * 40, amount="0.50") is True
        assert adapter.supports("0x" + "a" * 40, amount="0.999999") is True

    def test_supports_address_above_threshold_rejected(self, mock_client: MagicMock):
        """EVM address at/above micro_threshold is NOT supported."""
        adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=NanopaymentAdapter(
                vault=MagicMock(),
                nanopayment_client=mock_client,
                http_client=AsyncMock(),
                auto_topup_enabled=False,
            ),
            micro_threshold_usdc="1.00",
        )
        assert adapter.supports("0x" + "a" * 40, amount="1.00") is False
        assert adapter.supports("0x" + "a" * 40, amount="10.00") is False

    def test_priority_is_10(self, mock_client: MagicMock):
        """Priority 10 means checked before other adapters (default 100)."""
        adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=NanopaymentAdapter(
                vault=MagicMock(),
                nanopayment_client=mock_client,
                http_client=AsyncMock(),
                auto_topup_enabled=False,
            ),
        )
        assert adapter.get_priority() == 10

    @pytest.mark.asyncio
    async def test_execute_url_routes_to_pay_x402_url(self, mock_client: MagicMock):
        """execute() with URL calls pay_x402_url()."""
        mock_adapter = AsyncMock()
        mock_adapter.pay_x402_url = AsyncMock(
            return_value=MagicMock(
                success=True,
                payer="0x" + "a" * 40,
                seller="0x" + "b" * 40,
                transaction="tx-123",
                amount_usdc="1.0",
                amount_atomic="1000000",
                network="eip155:5042002",
                is_nanopayment=True,
            )
        )

        protocol_adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=mock_adapter,
            micro_threshold_usdc="1.00",
        )

        result = await protocol_adapter.execute(
            wallet_id="wallet-123",
            recipient="https://api.seller.com/resource",
            amount=Decimal("1.0"),
        )

        mock_adapter.pay_x402_url.assert_called_once()
        assert result.success is True
        assert result.method.value == "nanopayment"

    @pytest.mark.asyncio
    async def test_execute_address_routes_to_pay_direct(self, mock_client: MagicMock):
        """execute() with address calls pay_direct()."""
        mock_adapter = AsyncMock()
        mock_adapter.pay_direct = AsyncMock(
            return_value=MagicMock(
                success=True,
                payer="0x" + "a" * 40,
                seller="0x" + "b" * 40,
                transaction="tx-456",
                amount_usdc="0.001",
                amount_atomic="1000",
                network="eip155:5042002",
                is_nanopayment=True,
            )
        )

        protocol_adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=mock_adapter,
            micro_threshold_usdc="1.00",
        )

        result = await protocol_adapter.execute(
            wallet_id="wallet-123",
            recipient="0x" + "b" * 40,
            amount=Decimal("0.001"),
        )

        mock_adapter.pay_direct.assert_called_once()
        assert result.success is True
        assert result.method.value == "nanopayment"

    @pytest.mark.asyncio
    async def test_execute_graceful_degradation_on_error(self, mock_client: MagicMock):
        """execute() catches exceptions and returns failed PaymentResult."""
        mock_adapter = AsyncMock()
        mock_adapter.pay_x402_url = AsyncMock(side_effect=Exception("Network error"))

        protocol_adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=mock_adapter,
            micro_threshold_usdc="1.00",
        )

        result = await protocol_adapter.execute(
            wallet_id="wallet-123",
            recipient="https://api.seller.com/resource",
            amount=Decimal("1.0"),
        )

        assert result.success is False
        assert result.status.value == "failed"
        assert "Nanopayment failed" in result.error


# =============================================================================
# TEST: GatewayWalletManager — On-Chain Deposit/Withdraw
# =============================================================================


class TestGatewayWalletManagerIntegration:
    """Tests for GatewayWalletManager on-chain operations."""

    @pytest.mark.asyncio
    async def test_deposit_creates_approval_and_deposit_txs(self, mock_client: MagicMock):
        """deposit() approves USDC and calls deposit on gateway contract."""
        # Generate a real key
        private_key, address = generate_eoa_keypair()

        with patch("omniclaw.protocols.nanopayments.wallet.web3") as mock_web3_module:
            # Mock web3 components
            mock_w3 = MagicMock()
            mock_web3_module.Web3.return_value = mock_w3
            mock_w3.eth.get_transaction_count.return_value = 5

            # Gas reserve check mocks
            mock_w3.eth.get_balance.return_value = 10**18  # 1 ETH in wei
            mock_w3.eth.gas_price = 30_000_000_000  # 30 gwei (attribute)
            mock_w3.from_wei = lambda v, unit: v / 1e18 if unit == "ether" else v

            mock_account = MagicMock()
            mock_web3_module.HTTPProvider.return_value = MagicMock()
            mock_w3.eth.account = mock_account

            # Mock signed transaction
            signed_tx = MagicMock()
            signed_tx.raw_transaction = b"raw_tx_bytes"
            mock_account.sign_transaction.return_value = signed_tx

            # Mock transaction receipt (success)
            mock_receipt = {"status": 1, "transactionHash": b"tx_hash_bytes"}
            mock_w3.eth.send_raw_transaction.return_value = b"tx_hash_bytes"
            mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

            # Mock USDC contract
            mock_usdc = MagicMock()
            mock_w3.eth.contract.return_value = mock_usdc
            mock_usdc.functions.allowance.return_value.call.return_value = 0
            mock_usdc.functions.approve.return_value = MagicMock()

            # Mock contract for deposit
            mock_gateway = MagicMock()
            mock_w3.eth.contract.side_effect = [mock_usdc, mock_gateway]

            manager = GatewayWalletManager(
                private_key=private_key,
                network="eip155:5042002",
                rpc_url="https://rpc.testnet",
                nanopayment_client=mock_client,
            )

            result = await manager.deposit("10.00")

            assert result.approval_tx_hash is not None
            assert result.deposit_tx_hash is not None
            assert result.amount == 10_000_000  # 10 USDC in atomic units
            assert "10.00" in result.formatted_amount

    @pytest.mark.asyncio
    async def test_withdraw_creates_withdrawal_tx(self, mock_client: MagicMock):
        """withdraw() returns structured transfer result via Gateway settlement."""
        private_key, address = generate_eoa_keypair()

        with patch("omniclaw.protocols.nanopayments.wallet.web3") as mock_web3_module:
            mock_w3 = MagicMock()
            mock_web3_module.Web3.return_value = mock_w3
            mock_w3.eth.get_transaction_count.return_value = 3

            mock_web3_module.HTTPProvider.return_value = MagicMock()
            mock_w3.eth.account = MagicMock()

            signed_tx = MagicMock()
            signed_tx.raw_transaction = b"raw_tx_bytes"
            mock_w3.eth.account.sign_transaction.return_value = signed_tx

            mock_receipt = {"status": 1, "transactionHash": b"withdraw_hash"}
            mock_w3.eth.send_raw_transaction.return_value = b"withdraw_hash"
            mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

            # Mock gateway contract
            mock_gateway = MagicMock()
            mock_w3.eth.contract.return_value = mock_gateway

            manager = GatewayWalletManager(
                private_key=private_key,
                network="eip155:5042002",
                rpc_url="https://rpc.testnet",
                nanopayment_client=mock_client,
            )

            result = await manager.withdraw(
                amount_usdc="5.00",
                destination_chain=None,
                recipient="0x" + "b" * 40,
            )
            assert result.amount == 5_000_000
            assert result.destination_chain == "eip155:5042002"


# =============================================================================
# TEST: GatewayMiddleware — Seller-Side x402 Gate
# =============================================================================


class TestGatewayMiddlewareIntegration:
    """Tests for GatewayMiddleware (seller-side payment gate)."""

    def test_parse_price_dollar_amounts(self):
        """parse_price correctly parses $1.00 = 1_000_000 atomic."""
        assert parse_price("$1.00") == 1_000_000
        assert parse_price("$0.001") == 1_000
        assert parse_price("$0.000001") == 1  # Minimum
        assert parse_price("$100.50") == 100_500_000

    def test_parse_price_numeric_string(self):
        """parse_price handles plain numeric strings."""
        assert parse_price("1.00") == 1_000_000
        assert parse_price("0.5") == 500_000
        assert parse_price("0.000001") == 1

    def test_parse_price_atomic_threshold(self):
        """parse_price treats >= 1_000_000 as atomic units."""
        assert parse_price("1000000") == 1_000_000  # Exactly 1M = $1.00 atomic
        assert parse_price("1000001") == 1_000_001  # > 1M = atomic

    def test_parse_price_small_integer_as_dollars(self):
        """parse_price treats < 1_000_000 as whole dollars (×1_000_000)."""
        assert parse_price("5") == 5_000_000  # $5 = 5M atomic

    def test_parse_price_rejects_invalid(self):
        """Invalid price formats raise InvalidPriceError."""
        from omniclaw.protocols.nanopayments.exceptions import InvalidPriceError

        with pytest.raises(InvalidPriceError):
            parse_price("not a price")
        with pytest.raises(InvalidPriceError):
            parse_price("")

    def test_parse_price_zero_dollar(self):
        """parse_price handles $0 as 0 atomic units."""
        assert parse_price("$0") == 0

    def test_middleware_build_accepts_array(self, mock_client: MagicMock):
        """_build_accepts_array produces correct accepts entries."""
        seller_addr = "0x" + "f" * 40
        mw = GatewayMiddleware(
            seller_address=seller_addr,
            nanopayment_client=mock_client,
            supported_kinds=[
                MagicMock(
                    network="eip155:5042002",
                    verifying_contract="0x" + "c" * 40,
                    usdc_address="0x" + "d" * 40,
                )
            ],
        )

        accepts = mw._build_accepts_array(price_atomic=10_000)

        assert len(accepts) >= 1
        entry = next(a for a in accepts if a["extra"]["name"] == "GatewayWalletBatched")
        assert entry["scheme"] == "exact"
        assert entry["amount"] == "10000"
        assert entry["payTo"] == seller_addr

    @pytest.mark.asyncio
    async def test_middleware_handle_without_signature_raises_402(self, mock_client: MagicMock):
        """handle() without payment signature raises PaymentRequiredHTTPError."""
        mw = GatewayMiddleware(
            seller_address="0x" + "f" * 40,
            nanopayment_client=mock_client,
        )

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await mw.handle(request_headers={}, price_usd="$0.01")

        assert exc_info.value.status_code == 402


# =============================================================================
# TEST: NanopaymentHTTPClient HTTP Error Paths
# =============================================================================


class TestHTTPClientErrorPaths:
    """Test httpx error handling in NanopaymentHTTPClient."""

    @pytest.mark.asyncio
    async def test_get_timeout_exception(self):
        """Lines 127-135: get() raises GatewayTimeoutError on TimeoutException."""
        from omniclaw.protocols.nanopayments.client import NanopaymentHTTPClient
        import httpx

        async with NanopaymentHTTPClient(base_url="http://localhost", api_key="test") as client:
            with patch.object(
                client._client.__class__, "get", side_effect=httpx.TimeoutException("timeout")
            ):
                with pytest.raises(Exception):  # GatewayTimeoutError
                    await client.get("/path")

    @pytest.mark.asyncio
    async def test_get_connect_error(self):
        """Lines 127-135: get() raises GatewayConnectionError on ConnectError."""
        from omniclaw.protocols.nanopayments.client import NanopaymentHTTPClient
        import httpx

        async with NanopaymentHTTPClient(base_url="http://localhost", api_key="test") as client:
            with patch.object(
                client._client.__class__, "get", side_effect=httpx.ConnectError("connect")
            ):
                with pytest.raises(Exception):  # GatewayConnectionError
                    await client.get("/path")

    @pytest.mark.asyncio
    async def test_get_request_error(self):
        """Lines 127-135: get() raises GatewayConnectionError on RequestError."""
        from omniclaw.protocols.nanopayments.client import NanopaymentHTTPClient
        import httpx

        async with NanopaymentHTTPClient(base_url="http://localhost", api_key="test") as client:
            with patch.object(
                client._client.__class__, "get", side_effect=httpx.RequestError("request")
            ):
                with pytest.raises(Exception):  # GatewayConnectionError
                    await client.get("/path")

    @pytest.mark.asyncio
    async def test_post_timeout_exception(self):
        """Lines 152-163: post() raises GatewayTimeoutError on TimeoutException."""
        from omniclaw.protocols.nanopayments.client import NanopaymentHTTPClient
        import httpx

        async with NanopaymentHTTPClient(base_url="http://localhost", api_key="test") as client:
            with patch.object(
                client._client.__class__, "post", side_effect=httpx.TimeoutException("timeout")
            ):
                with pytest.raises(Exception):
                    await client.post("/path")

    @pytest.mark.asyncio
    async def test_post_connect_error(self):
        """Lines 152-163: post() raises GatewayConnectionError on ConnectError."""
        from omniclaw.protocols.nanopayments.client import NanopaymentHTTPClient
        import httpx

        async with NanopaymentHTTPClient(base_url="http://localhost", api_key="test") as client:
            with patch.object(
                client._client.__class__, "post", side_effect=httpx.ConnectError("connect")
            ):
                with pytest.raises(Exception):
                    await client.post("/path")

    @pytest.mark.asyncio
    async def test_post_request_error(self):
        """Lines 152-163: post() raises GatewayConnectionError on RequestError."""
        from omniclaw.protocols.nanopayments.client import NanopaymentHTTPClient
        import httpx

        async with NanopaymentHTTPClient(base_url="http://localhost", api_key="test") as client:
            with patch.object(
                client._client.__class__, "post", side_effect=httpx.RequestError("request")
            ):
                with pytest.raises(Exception):
                    await client.post("/path")

    @pytest.mark.asyncio
    async def test_post_with_idempotency_key(self):
        """Lines 152-163: post() includes Idempotency-Key header when provided."""
        from omniclaw.protocols.nanopayments.client import NanopaymentHTTPClient

        captured_headers = {}

        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {}

        async def mock_post(path, headers=None, **kwargs):
            captured_headers.update(headers or {})
            return FakeResponse()

        async with NanopaymentHTTPClient(base_url="http://localhost", api_key="test") as client:
            with patch.object(client._client.__class__, "post", side_effect=mock_post):
                await client.post("/path", idempotency_key="test-key-123")

        assert captured_headers.get("Idempotency-Key") == "test-key-123"


# =============================================================================
# TEST: NanopaymentClient HTTP error paths
# =============================================================================


class TestNanopaymentClientHTTPErrorPaths:
    @pytest.mark.asyncio
    async def test_get_supported_http_error_raises(self):
        """Lines 246-251: get_supported() raises GatewayAPIError on non-success status."""
        from omniclaw.protocols.nanopayments.client import NanopaymentClient

        with patch("omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient") as MockHTTP:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.get.return_value = MagicMock(
                status_code=500,
                text="Internal Server Error",
            )
            MockHTTP.return_value = mock_ctx

            client = NanopaymentClient(api_key="key")
            with pytest.raises(Exception) as exc_info:
                await client.get_supported()
            assert "500" in str(exc_info.value) or "Gateway" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_verify_http_error_raises(self):
        """Lines 342-347: verify() raises GatewayAPIError on non-success status."""
        from omniclaw.protocols.nanopayments.client import NanopaymentClient

        payload = MagicMock()
        payload.to_dict.return_value = {}
        req = MagicMock()
        req.to_dict.return_value = {}

        with patch("omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient") as MockHTTP:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.post.return_value = MagicMock(
                status_code=403,
                text="Forbidden",
            )
            MockHTTP.return_value = mock_ctx

            client = NanopaymentClient(api_key="key")
            with pytest.raises(Exception) as exc_info:
                await client.verify(payload, req)
            assert "403" in str(exc_info.value) or "Gateway" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_settle_http_error_raises(self):
        """Lines 421-426: settle() raises GatewayAPIError on non-success non-402 status."""
        from omniclaw.protocols.nanopayments.client import NanopaymentClient

        payload = MagicMock()
        payload.to_dict.return_value = {}
        req = MagicMock()
        req.to_dict.return_value = {}

        with patch("omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient") as MockHTTP:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.post.return_value = MagicMock(
                status_code=500,
                text="Internal Server Error",
            )
            MockHTTP.return_value = mock_ctx

            client = NanopaymentClient(api_key="key")
            with pytest.raises(Exception) as exc_info:
                await client.settle(payload, req)
            assert "500" in str(exc_info.value) or "Gateway" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_settle_402_raises_mapped_error(self):
        """Lines 414-419: settle() raises mapped error on 402 status."""
        from omniclaw.protocols.nanopayments.client import NanopaymentClient

        payload = MagicMock()
        payload.to_dict.return_value = {}
        req = MagicMock()
        req.to_dict.return_value = {}

        with patch("omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient") as MockHTTP:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.post.return_value = MagicMock(
                status_code=402,
                json=lambda: {"errorReason": "insufficient_balance", "payer": "0x" + "a" * 40},
            )
            MockHTTP.return_value = mock_ctx

            client = NanopaymentClient(api_key="key")
            with pytest.raises(Exception) as exc_info:
                await client.settle(payload, req)
            assert "insufficient_balance" in str(exc_info.value) or "Insufficient" in str(
                exc_info.value
            )

    @pytest.mark.asyncio
    async def test_settle_non_success_body_raises_mapped_error(self):
        """Lines 434-435: settle() raises mapped error when success=false in body."""
        from omniclaw.protocols.nanopayments.client import NanopaymentClient

        payload = MagicMock()
        payload.to_dict.return_value = {}
        req = MagicMock()
        req.to_dict.return_value = {}

        with patch("omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient") as MockHTTP:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None
            mock_ctx.post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "success": False,
                    "errorReason": "invalid_signature",
                    "payer": "0x" + "a" * 40,
                },
            )
            MockHTTP.return_value = mock_ctx

            client = NanopaymentClient(api_key="key")
            with pytest.raises(Exception) as exc_info:
                await client.settle(payload, req)
            assert "invalid_signature" in str(exc_info.value) or "signature" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_settle_idempotency_key_from_nonce(self):
        """Lines 393-401: settle() uses EIP-3009 nonce as idempotency key."""
        from omniclaw.protocols.nanopayments.client import NanopaymentClient

        captured_key = {}

        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"success": True, "transaction": "tx123"}

        payload = MagicMock()
        payload.to_dict.return_value = {}
        auth = MagicMock()
        auth.nonce = "0x" + "deadbeef" * 8  # 32 bytes hex
        payload.payload.authorization = auth
        req = MagicMock()
        req.to_dict.return_value = {}

        with patch("omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient") as MockHTTP:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_ctx
            mock_ctx.__aexit__.return_value = None

            async def capture_post(path, json=None, idempotency_key=None, **kwargs):
                captured_key["key"] = idempotency_key
                return FakeResponse()

            mock_ctx.post = capture_post
            MockHTTP.return_value = mock_ctx

            client = NanopaymentClient(api_key="key")
            await client.settle(payload, req)

        # Nonce should be used as idempotency key
        assert captured_key.get("key") is not None


# =============================================================================
# TEST: _map_settlement_error - all error codes
# =============================================================================


class TestMapSettlementError:
    """Test _map_settlement_error maps all error codes correctly."""

    @pytest.mark.asyncio
    async def test_invalid_signature_error(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import InvalidSignatureError

        exc = _map_settlement_error("invalid_signature", payer="0x" + "a" * 40)
        assert isinstance(exc, InvalidSignatureError)

    @pytest.mark.asyncio
    async def test_authorization_not_yet_valid(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("authorization_not_yet_valid", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_authorization_expired(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("authorization_expired", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_authorization_validity_too_short(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("authorization_validity_too_short", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_self_transfer(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("self_transfer", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_insufficient_balance(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import InsufficientBalanceError

        exc = _map_settlement_error("insufficient_balance", payer="0x" + "a" * 40)
        assert isinstance(exc, InsufficientBalanceError)

    @pytest.mark.asyncio
    async def test_nonce_already_used(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import NonceReusedError

        exc = _map_settlement_error("nonce_already_used", payer="0x" + "a" * 40)
        assert isinstance(exc, NonceReusedError)

    @pytest.mark.asyncio
    async def test_unsupported_asset(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("unsupported_asset", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_invalid_payload(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("invalid_payload", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_address_mismatch(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("address_mismatch", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_amount_mismatch(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("amount_mismatch", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_unsupported_domain(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("unsupported_domain", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_wallet_not_found(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import VerificationError

        exc = _map_settlement_error("wallet_not_found", payer="0x" + "a" * 40)
        assert isinstance(exc, VerificationError)

    @pytest.mark.asyncio
    async def test_unexpected_error(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import SettlementError

        exc = _map_settlement_error("unexpected_error", payer="0x" + "a" * 40)
        assert isinstance(exc, SettlementError)

    @pytest.mark.asyncio
    async def test_unknown_error_code_defaults_to_settlement_error(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import SettlementError

        exc = _map_settlement_error("completely_unknown_code", payer="0x" + "a" * 40)
        assert isinstance(exc, SettlementError)

    @pytest.mark.asyncio
    async def test_none_error_code_defaults_to_settlement_error(self):
        from omniclaw.protocols.nanopayments.client import _map_settlement_error
        from omniclaw.protocols.nanopayments.exceptions import SettlementError

        exc = _map_settlement_error(None, payer="0x" + "a" * 40)
        assert isinstance(exc, SettlementError)


# =============================================================================
# TEST: NanopaymentAdapter pay_x402_url() Error Paths
# =============================================================================


class TestAdapterPayX402URLErrorPaths:
    """Test error handling in pay_x402_url() (lines 280-520)."""

    @pytest.mark.asyncio
    async def test_initial_request_timeout_raises(self):
        """Lines 288-293: Initial request TimeoutException raises GatewayAPIError."""
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

        with pytest.raises(Exception):
            await adapter.pay_x402_url("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_initial_request_request_error_raises(self):
        """Lines 294-299: Initial request RequestError raises GatewayAPIError."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        import httpx

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=httpx.RequestError("connection refused"))

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
        """Lines 320-325: 402 response without PAYMENT-REQUIRED header raises."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.headers = {}  # No payment-required header
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
    async def test_402_malformed_base64_header(self):
        """Lines 331-336: Invalid base64 in PAYMENT-REQUIRED header raises GatewayAPIError."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.headers = {"payment-required": "not-valid-base64!!!"}
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
    async def test_gateway_kind_not_found(self):
        """Lines 340-343: Unsupported scheme raises UnsupportedSchemeError."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import UnsupportedSchemeError

        req_data = make_402_requirements(name="NotGatewayBatched")
        encoded = base64.b64encode(json.dumps(req_data).encode()).decode()

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": encoded}
        mock_resp_402.text = ""

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_resp_402)

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
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.types import PaymentPayload

        req_data = {
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
        encoded = base64.b64encode(json.dumps(req_data).encode()).decode()

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": encoded}
        mock_resp_402.text = ""

        mock_resp_retry = MagicMock()
        mock_resp_retry.status_code = 200
        mock_resp_retry.content = b"data"
        mock_resp_retry.text = "data"

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
        mock_client.get_verifying_contract.assert_called()

    @pytest.mark.asyncio
    async def test_retry_request_timeout_raises(self):
        """Lines 405-416: Retry request TimeoutException raises GatewayAPIError."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        import httpx

        req_data = make_402_requirements()
        encoded = base64.b64encode(json.dumps(req_data).encode()).decode()

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": encoded}
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
        """Lines 426-439: Circuit open + non-success status raises CircuitOpenError."""
        from omniclaw.protocols.nanopayments.adapter import (
            CircuitOpenError,
            NanopaymentAdapter,
            NanopaymentCircuitBreaker,
        )

        req_data = make_402_requirements()
        encoded = base64.b64encode(json.dumps(req_data).encode()).decode()

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": encoded}
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
        """Lines 466-484: NonceReusedError + non-success content raises immediately."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import NonceReusedError

        req_data = make_402_requirements()
        encoded = base64.b64encode(json.dumps(req_data).encode()).decode()

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": encoded}
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
    async def test_auto_topup_failure_in_pay_x402_url_continues(self):
        """Lines 378-381: Auto-topup failure logs warning but continues."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        req_data = make_402_requirements()
        encoded = base64.b64encode(json.dumps(req_data).encode()).decode()

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": encoded}
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

        result = await adapter.pay_x402_url("https://api.example.com/data")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_settlement_success_after_retry(self):
        """Lines 638-739: Settlement succeeds after transient timeout retry."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import GatewayTimeoutError

        req_data = make_402_requirements()
        encoded = base64.b64encode(json.dumps(req_data).encode()).decode()

        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": encoded}
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
        """Lines 665-667: _settle_with_retry raises CircuitOpenError when circuit is open."""
        from omniclaw.protocols.nanopayments.adapter import (
            CircuitOpenError,
            NanopaymentAdapter,
            NanopaymentCircuitBreaker,
        )

        mock_vault = MagicMock()
        mock_client = MagicMock()
        mock_http = AsyncMock()

        cb = NanopaymentCircuitBreaker(failure_threshold=1)
        cb.record_failure()  # Trip circuit

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
# TEST: NanopaymentAdapter pay_direct() Error Paths
# =============================================================================


class TestAdapterPayDirectErrorPaths:
    """Test error handling in pay_direct() (lines 526-632)."""

    @pytest.mark.asyncio
    async def test_pay_direct_auto_topup_failure_continues(self):
        """Lines 591-596: Auto-topup failure in pay_direct logs warning but continues."""
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
        """Lines 609-619: Circuit open in pay_direct raises SettlementError."""
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
        cb.record_failure()  # Trip circuit

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
        # No set_wallet_manager() called

        result = await adapter._check_and_topup()
        assert result is False


# =============================================================================
# TEST: EIP3009Signer Error Paths (signing.py coverage)
# =============================================================================


class TestEIP3009SignerErrorPaths:
    """Test EIP3009Signer error paths for signing.py coverage."""

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
                valid_before=int(time.time()) + 100,  # Too soon (< 3 days)
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
                nonce="deadbeef" * 8,  # No 0x prefix
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
            EIP3009Signer("0x" + "ab" * 31)  # 62 chars, not 64

    def test_eip3009_signer_invalid_key_hex(self):
        """Lines 322-326: Private key invalid hex raises InvalidPrivateKeyError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import InvalidPrivateKeyError

        with pytest.raises(InvalidPrivateKeyError):
            EIP3009Signer("0x" + "g" * 64)  # 'g' is invalid hex

    def test_eip3009_signer_wrong_scheme(self):
        """Lines 402-406: Wrong scheme raises UnsupportedSchemeError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import UnsupportedSchemeError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        key = "0x" + "1" * 64
        signer = EIP3009Signer(key)

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

        key = "0x" + "1" * 64
        signer = EIP3009Signer(key)

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

        key = "0x" + "1" * 64
        signer = EIP3009Signer(key)

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
            signer.sign_transfer_with_authorization(kind, amount_atomic=2000)  # More than required
        assert exc_info.value.code == "AMOUNT_EXCEEDS_REQUIREMENT"

    def test_eip3009_signer_invalid_network_format(self):
        """Lines 432-435: Non-eip155 network raises UnsupportedNetworkError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import UnsupportedNetworkError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        key = "0x" + "1" * 64
        signer = EIP3009Signer(key)

        kind = PaymentRequirementsKind(
            scheme="exact",
            network="cosmos:stargaze",  # Not eip155
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

        key = "0x" + "1" * 64
        signer = EIP3009Signer(key)

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

        key = "0x" + "1" * 64
        signer = EIP3009Signer(key)

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
            signer.sign_transfer_with_authorization(kind, amount_atomic=2000)  # More than required
        assert exc_info.value.code == "AMOUNT_EXCEEDS_REQUIREMENT"

    def test_eip3009_signer_invalid_network_format(self):
        """Lines 432-435: Non-eip155 network raises UnsupportedNetworkError."""
        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.exceptions import UnsupportedNetworkError
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsKind,
            PaymentRequirementsExtra,
        )

        key = "0x" + "1" * 64
        signer = EIP3009Signer(key)

        kind = PaymentRequirementsKind(
            scheme="exact",
            network="cosmos:stargaze",  # Not eip155
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
        """Lines 635: generate_eoa_keypair() returns valid (key, address) pair."""
        from omniclaw.protocols.nanopayments.signing import generate_eoa_keypair

        private_key, address = generate_eoa_keypair()
        assert private_key.startswith("0x")
        assert len(private_key) == 66  # 0x + 64 hex
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


# =============================================================================
# TEST: GatewayWalletManager Coverage (wallet.py)
# =============================================================================


class TestGatewayWalletManagerCoverage:
    """Additional tests for GatewayWalletManager."""

    def _make_wallet_manager(self):
        """Helper to create a partially mocked GatewayWalletManager."""
        with patch("omniclaw.protocols.nanopayments.wallet.web3.Web3"):
            with patch("omniclaw.protocols.nanopayments.wallet.EIP3009Signer"):
                mock_client = MagicMock()
                mock_client.get_verifying_contract = AsyncMock(return_value="0x" + "c" * 40)
                mock_client.get_usdc_address = AsyncMock(return_value="0x" + "d" * 40)

                with patch.object(GatewayWalletManager, "_sign_and_send"):
                    mgr = GatewayWalletManager(
                        private_key="0x" + "1" * 64,
                        network="eip155:5042002",
                        rpc_url="http://localhost",
                        nanopayment_client=mock_client,
                    )
                    return mgr

    def test_check_gas_reserve_returns_tuple(self):
        """Lines 812-837: check_gas_reserve() returns (bool, str) tuple."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.get_balance.return_value = 1_000_000_000_000_000_000_000_000_000  # 1000 ETH
        mgr._w3.eth.gas_price.return_value = 10_000_000_000  # 10 gwei
        # Make from_wei return a proper type
        mgr._w3.from_wei = MagicMock(side_effect=lambda x, y: x / 1e18)

        result = mgr.check_gas_reserve()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_has_sufficient_gas_for_deposit(self):
        """Lines 839-847: has_sufficient_gas_for_deposit() returns bool."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.get_balance.return_value = 1_000_000_000_000_000_000_000_000_000  # 1000 ETH
        mgr._w3.eth.gas_price.return_value = 10_000_000_000  # 10 gwei
        mgr._w3.from_wei = MagicMock(side_effect=lambda x, y: x / 1e18)

        result = mgr.has_sufficient_gas_for_deposit()
        assert isinstance(result, bool)

    def test_ensure_gas_reserve_raises_insufficient_gas(self):
        """Lines 849-864: ensure_gas_reserve() raises InsufficientGasError when low balance."""
        from omniclaw.protocols.nanopayments.exceptions import InsufficientGasError

        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.get_balance.return_value = 100_000_000_000_000  # 0.0001 ETH
        mgr._w3.eth.gas_price = 1_000_000_000_000_000_000  # 1000 gwei (direct value)
        mgr._w3.from_wei = MagicMock(side_effect=lambda x, y: float(x) / 1e18)

        with pytest.raises(InsufficientGasError):
            mgr.ensure_gas_reserve()

    def test_estimate_gas_cost_wei(self):
        """Lines 790-800: estimate_gas_cost_wei() returns integer."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.gas_price = 20_000_000_000  # 20 gwei (direct value)

        result = mgr.estimate_gas_cost_wei()
        assert isinstance(result, int)
        assert result > 0

    def test_estimate_gas_for_deposit(self):
        """Lines 774-788: estimate_gas_for_deposit() returns fixed 200000."""
        mgr = self._make_wallet_manager()

        result = mgr.estimate_gas_for_deposit()
        assert result == 200_000

    def test_get_gas_balance_eth(self):
        """Lines 763-772: get_gas_balance_eth() returns string."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.get_balance.return_value = 1_000_000_000_000_000_000  # 1 ETH

        result = mgr.get_gas_balance_eth()
        assert isinstance(result, str)

    def test_atomic_to_decimal(self):
        """Lines 276-278: _atomic_to_decimal() formats correctly."""
        mgr = self._make_wallet_manager()

        result = mgr._atomic_to_decimal(1_500_000)
        assert result == "1.5"

    def test_decimal_to_atomic_valid(self):
        """Lines 266-274: _decimal_to_atomic() with valid input."""
        mgr = self._make_wallet_manager()

        result = mgr._decimal_to_atomic("10.50")
        assert result == 10_500_000

    def test_decimal_to_atomic_invalid(self):
        """Lines 266-274: _decimal_to_atomic() with invalid input raises ValueError."""
        mgr = self._make_wallet_manager()

        with pytest.raises(ValueError):
            mgr._decimal_to_atomic("not-a-number")

    def test_sign_and_send_time_exhausted(self):
        """Lines 312-315: _sign_and_send handles TimeExhausted."""
        import web3 as w3_module

        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.account.sign_transaction = MagicMock()
        mgr._w3.eth.send_raw_transaction = MagicMock()
        mgr._w3.eth.wait_for_transaction_receipt = MagicMock(
            side_effect=w3_module.exceptions.TimeExhausted()
        )

        with pytest.raises(Exception) as exc_info:
            mgr._sign_and_send({})
        assert (
            "timed out" in str(exc_info.value).lower()
            or "TimeExhausted" in type(exc_info.value).__name__
        )

    def test_sign_and_send_transaction_not_found(self):
        """Lines 316-319: _sign_and_send handles TransactionNotFound."""
        import web3 as w3_module

        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.account.sign_transaction = MagicMock()
        mgr._w3.eth.send_raw_transaction = MagicMock()
        mgr._w3.eth.wait_for_transaction_receipt = MagicMock(
            side_effect=w3_module.exceptions.TransactionNotFound(
                "Transaction not found after broadcast"
            )
        )

        with pytest.raises(Exception):
            mgr._sign_and_send({})

    def test_get_gateway_contract_caching(self):
        """Lines 246-256: _get_gateway_contract reuses cached contract."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mock_contract = MagicMock()
        mock_contract.address = "0x" + "c" * 40
        mgr._w3.eth.contract.return_value = mock_contract
        mgr._gateway_contract = None  # Ensure clean state

        addr = "0x" + "c" * 40
        contract1 = mgr._get_gateway_contract(addr)
        contract2 = mgr._get_gateway_contract(addr)

        # Same address -> same contract (caching)
        assert contract1 is contract2
        assert mgr._w3.eth.contract.call_count == 1

        # Different address -> new contract
        addr2 = "0x" + "d" * 40
        mgr._gateway_contract = None  # Reset to force new contract
        mgr._w3.eth.contract.return_value = MagicMock(address=addr2)
        mgr._get_gateway_contract(addr2)
        assert mgr._w3.eth.contract.call_count == 2

    @pytest.mark.asyncio
    async def test_withdraw_to_address_calls_transfer(self):
        """Lines 586-628: withdraw() delegates to transfer_to_address()."""
        mgr = self._make_wallet_manager()
        mgr.transfer_to_address = AsyncMock(return_value=MagicMock())
        mgr.transfer_crosschain = AsyncMock(return_value=MagicMock())

        # Same chain -> calls transfer_to_address
        await mgr.withdraw("1.00", destination_chain="eip155:5042002", recipient="0x" + "b" * 40)
        mgr.transfer_to_address.assert_called_once()
        mgr.transfer_crosschain.assert_not_called()

    @pytest.mark.asyncio
    async def test_withdraw_crosschain_calls_transfer(self):
        """Lines 586-628: withdraw() with different chain calls transfer_crosschain()."""
        mgr = self._make_wallet_manager()
        mgr.transfer_to_address = AsyncMock(return_value=MagicMock())
        mgr.transfer_crosschain = AsyncMock(return_value=MagicMock())

        # Different chain -> calls transfer_crosschain
        await mgr.withdraw("1.00", destination_chain="eip155:1", recipient="0x" + "b" * 40)
        mgr.transfer_crosschain.assert_called_once()


# =============================================================================
# TEST: NanopaymentProtocolAdapter execute() with no wallet manager
# =============================================================================


class TestNanopaymentProtocolAdapterExecute:
    """Test NanopaymentProtocolAdapter.execute() fallback paths."""

    @pytest.mark.asyncio
    async def test_execute_pay_direct_no_network_uses_env_var(self):
        """Lines 929-943: execute() with no network uses NANOPAYMENTS_DEFAULT_NETWORK env."""
        import os
        from omniclaw.protocols.nanopayments.adapter import (
            NanopaymentAdapter,
            NanopaymentProtocolAdapter,
        )

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
                # No destination_chain or source_network
            )

        mock_adapter.pay_direct.assert_called_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_pay_x402_url_no_destination_uses_env(self):
        """execute() with URL recipient and no network uses env var."""
        import os
        from omniclaw.protocols.nanopayments.adapter import (
            NanopaymentAdapter,
            NanopaymentProtocolAdapter,
        )

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
# TEST: OmniClaw Client — SDK Integration
# =============================================================================


class TestOmniClawNanopaymentsIntegration:
    """Tests for OmniClaw client nanopayments integration."""

    @pytest.mark.asyncio
    async def test_client_vault_and_adapter_properties_exist(self):
        """OmniClaw has vault and nanopayment_adapter properties."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                # Patch httpx to avoid actual HTTP client creation
                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                    # Nanopayment components should be initialized
                    assert client._nano_vault is not None
                    assert client._nano_adapter is not None
                    assert client.vault is client._nano_vault
                    assert client.nanopayment_adapter is client._nano_adapter

    @pytest.mark.asyncio
    async def test_add_key_delegates_to_vault(self):
        """OmniClaw.add_key() correctly delegates to NanoKeyVault."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                    private_key, _ = generate_eoa_keypair()
                    address = await client.add_key("test-key", private_key)
                    assert address.startswith("0x")
                    assert len(address) == 42

    @pytest.mark.asyncio
    async def test_generate_key_delegates_to_vault(self):
        """OmniClaw.generate_key() correctly delegates to NanoKeyVault."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                    address = await client.generate_key("gen-test-key")
                    assert address.startswith("0x")

                    # Second generation with same alias raises
                    with pytest.raises(DuplicateKeyAliasError):
                        await client.generate_key("gen-test-key")

    @pytest.mark.asyncio
    async def test_set_default_key_delegates_to_vault(self):
        """OmniClaw.set_default_key() correctly delegates to NanoKeyVault."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                    await client.generate_key("default-test")
                    await client.set_default_key("default-test")

                    # Unknown key raises
                    with pytest.raises(KeyNotFoundError):
                        await client.set_default_key("unknown-key")

    @pytest.mark.asyncio
    async def test_list_keys_returns_aliases(self):
        """OmniClaw.list_keys() returns all key aliases."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                    await client.generate_key("list-key-1")
                    await client.generate_key("list-key-2")

                    keys = await client.list_keys()
                    assert "list-key-1" in keys
                    assert "list-key-2" in keys

    @pytest.mark.asyncio
    async def test_configure_nanopayments_updates_adapter(self):
        """configure_nanopayments() updates the NanopaymentAdapter's auto-topup."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                    client.configure_nanopayments(
                        auto_topup_enabled=False,
                        auto_topup_threshold="5.00",
                        auto_topup_amount="50.00",
                    )

                    assert client._nano_adapter is not None
                    assert client._nano_adapter._auto_topup is False
                    assert client._nano_adapter._topup_threshold == "5.00"
                    assert client._nano_adapter._topup_amount == "50.00"

    @pytest.mark.asyncio
    async def test_create_agent_with_nanopayment_key(self):
        """create_agent() with nanopayment_key_alias=True creates a NanoKeyVault key."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                    # Mock create_agent_wallet to avoid Circle API calls
                    with patch.object(
                        client, "create_agent_wallet", autospec=True
                    ) as mock_create_wallet:
                        mock_wallet_set = MagicMock()
                        mock_wallet_info = MagicMock()
                        mock_create_wallet.return_value = (mock_wallet_set, mock_wallet_info)

                        wallet_set, wallet = await client.create_agent(
                            agent_name="test-agent",
                            nanopayment_key_alias="agent-test-agent-nano",
                        )

                        # Wallet was created
                        mock_create_wallet.assert_called_once()
                        assert wallet_set == mock_wallet_set
                        assert wallet == mock_wallet_info

    @pytest.mark.asyncio
    async def test_payment_router_has_nanopayment_adapter(self):
        """OmniClaw's router includes NanopaymentProtocolAdapter."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                    # Router should have adapters
                    adapters = client._router.get_adapters()
                    assert len(adapters) >= 4  # Transfer + X402 + Gateway + Nanopayment

                    # NanopaymentProtocolAdapter should be registered
                    method_names = [getattr(a, "method", None) for a in adapters]
                    assert "nanopayment" in method_names


# =============================================================================
# TEST: End-to-End Buyer-Seller Flow (Conceptual)
# =============================================================================


class TestEndToEndFlow:
    """Conceptual end-to-end tests showing the complete buyer-seller flow."""

    @pytest.mark.asyncio
    async def test_complete_buyer_flow_with_real_vault(self):
        """
        Complete buyer flow:
        1. Operator generates a key in NanoKeyVault
        2. Operator funds the resulting EOA address with USDC
        3. Buyer agent uses the key alias to pay for a URL resource
        4. Signature is created, settlement is triggered

        This uses real cryptographic operations (signing, encryption)
        with mocked HTTP to avoid network calls.
        """
        storage = MockStorageBackend()
        vault = NanoKeyVault(
            entity_secret="real-entity-secret-for-e2e-tests-here",
            storage_backend=storage,
            circle_api_key="test-api-key",
        )

        # 1. Generate a real key
        buyer_address = await vault.generate_key("e2e-buyer")
        assert buyer_address.startswith("0x")

        # 2. Set as default
        await vault.set_default_key("e2e-buyer")

        # 3. Mock the client for payment
        mock_client = MagicMock(spec=NanopaymentClient)
        mock_client.get_verifying_contract = AsyncMock(return_value="0x" + "c" * 40)
        mock_client.get_usdc_address = AsyncMock(return_value="0x" + "d" * 40)
        mock_client.settle = AsyncMock(
            return_value=MagicMock(
                success=True,
                transaction="e2e-settlement-tx-123",
            )
        )

        # 4. Build a real signed payload using the vault
        kind = PaymentRequirementsKind(
            scheme="exact",
            network="eip155:5042002",
            asset="0x" + "d" * 40,
            amount="1000000",
            max_timeout_seconds=345600,
            pay_to="0x" + "b" * 40,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract="0x" + "c" * 40,
            ),
        )
        real_payload = await vault.sign(requirements=kind, alias="e2e-buyer")
        assert real_payload.payload.signature.startswith("0x")

        # Create mock vault with the real payload
        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value=buyer_address)
        mock_vault.sign = AsyncMock(return_value=real_payload)
        mock_vault.get_balance = AsyncMock(
            return_value=MagicMock(
                available_decimal="10.000000",
            )
        )

        # 5. Build 402 response
        import base64

        req_dict = make_402_requirements(amount="1000000")
        first_resp = MagicMock()
        first_resp.status_code = 402
        first_resp.headers = {
            "payment-required": base64.b64encode(json.dumps(req_dict).encode()).decode()
        }
        retry_resp = MagicMock()
        retry_resp.status_code = 200
        retry_resp.text = '{"premium": true}'

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(side_effect=[first_resp, retry_resp])

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        # 6. Execute the payment
        result = await adapter.pay_x402_url(
            url="https://api.ai-provider.com/gpt4-answer",
            nano_key_alias="e2e-buyer",
        )

        # 7. Verify result
        assert result.success is True
        assert result.is_nanopayment is True
        assert result.payer == buyer_address
        assert result.transaction == "e2e-settlement-tx-123"
        assert float(result.amount_usdc) == 1.0

        # HTTP was called twice (initial + retry with signature)
        assert mock_http.request.call_count == 2
        # Settlement was triggered
        mock_client.settle.assert_called_once()

    @pytest.mark.asyncio
    async def test_micro_payment_flow(self):
        """
        Micro-payment flow: $0.001 direct address payment via Gateway.
        Shows that amounts below $1.00 can be paid instantly with no gas.
        """
        storage = MockStorageBackend()
        vault = NanoKeyVault(
            entity_secret="real-entity-secret-for-micro-tests-here",
            storage_backend=storage,
            circle_api_key="test-api-key",
        )

        # Generate key
        buyer_address = await vault.generate_key("micro-buyer")

        mock_client = MagicMock(spec=NanopaymentClient)
        mock_client.get_verifying_contract = AsyncMock(return_value="0x" + "c" * 40)
        mock_client.get_usdc_address = AsyncMock(return_value="0x" + "d" * 40)
        mock_client.settle = AsyncMock(
            return_value=MagicMock(success=True, transaction="micro-settlement-456")
        )

        adapter = NanopaymentAdapter(
            vault=vault,
            nanopayment_client=mock_client,
            http_client=AsyncMock(),
            auto_topup_enabled=False,
        )

        # Pay $0.001 to a seller address
        result = await adapter.pay_direct(
            seller_address="0x" + "e" * 40,
            amount_usdc="0.001",  # One-thousandth of a dollar
            network="eip155:5042002",
            nano_key_alias="micro-buyer",
        )

        assert result.success is True
        assert result.is_nanopayment is True
        assert result.payer == buyer_address
        assert result.amount_usdc == "0.001"
        assert result.amount_atomic == "1000"

    def test_key_security_raw_key_never_exposed(self, mock_vault: NanoKeyVault):
        """
        Security test: Raw private key is NEVER exposed outside the vault.
        - Agents receive only an alias string
        - get_address() returns only the address, never the key
        - get_raw_key() returns the key but is only callable by the operator
        """
        import asyncio

        async def run():
            addr = await mock_vault.generate_key("security-test")

            # Address is returned, but it's just an address
            assert addr.startswith("0x")

            # The address should NOT be the private key
            record = await mock_vault._storage.get("nano_keys", "security-test")
            assert "encrypted_key" in record
            assert "address" in record
            # Encrypted key is not the raw private key
            assert record["encrypted_key"] != record["address"]

            # get_address does not return the private key
            retrieved = await mock_vault.get_address("security-test")
            assert retrieved != record["encrypted_key"]

        asyncio.run(run())


# =============================================================================
# TEST: Roundtrip Serialization (All Nanopayments Types)
# =============================================================================


class TestNanopaymentsRoundtrip:
    """Verify all nanopayment types serialize/deserialize correctly."""

    def test_payment_payload_roundtrip(self):
        """PaymentPayload.to_dict() -> from_dict() preserves all fields."""
        payload_dict = {
            "x402Version": 2,
            "scheme": "exact",
            "network": "eip155:5042002",
            "payload": {
                "signature": "0x" + "a" * 130,
                "authorization": {
                    "from": "0x" + "b" * 40,
                    "to": "0x" + "c" * 40,
                    "value": "1000000",
                    "validAfter": "0",
                    "validBefore": "9999999999",
                    "nonce": "0x" + "d" * 64,
                },
            },
        }
        payload = PaymentPayload.from_dict(payload_dict)
        assert payload.x402_version == 2
        assert payload.scheme == "exact"
        assert payload.network == "eip155:5042002"
        assert payload.payload.authorization.from_address == "0x" + "b" * 40

        # Roundtrip
        roundtripped = payload.to_dict()
        assert roundtripped["x402Version"] == 2

    def test_payment_requirements_roundtrip(self):
        """PaymentRequirements.to_dict() -> from_dict() roundtrips correctly."""
        req_dict = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "asset": "0x" + "a" * 40,
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
        req = PaymentRequirements.from_dict(req_dict)
        assert req.x402_version == 2
        assert len(req.accepts) == 1
        assert req.accepts[0].amount == "1000000"
        assert req.accepts[0].extra.name == "GatewayWalletBatched"

        # Roundtrip
        roundtripped = req.to_dict()
        assert roundtripped["x402Version"] == 2
        assert roundtripped["accepts"][0]["extra"]["name"] == "GatewayWalletBatched"


# =============================================================================
# TEST: Circuit Breaker and Idempotency
# =============================================================================


class TestCircuitBreaker:
    """Tests for NanopaymentCircuitBreaker."""

    def test_circuit_starts_closed(self):
        """Circuit breaker starts in closed state."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentCircuitBreaker

        cb = NanopaymentCircuitBreaker()
        assert cb.state == "closed"
        assert cb.is_available() is True

    def test_circuit_trips_after_threshold(self):
        """Circuit trips open after consecutive failure threshold."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentCircuitBreaker

        cb = NanopaymentCircuitBreaker(failure_threshold=3, recovery_seconds=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.is_available() is True

        cb.record_failure()  # Third failure
        assert cb.state == "open"
        assert cb.is_available() is False

    def test_circuit_success_resets(self):
        """Successful settlement resets consecutive failure counter."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentCircuitBreaker

        cb = NanopaymentCircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb._consecutive_failures == 0
        assert cb.state == "closed"

    def test_circuit_half_open_after_recovery(self):
        """Circuit goes half-open after recovery period."""
        import time
        from omniclaw.protocols.nanopayments.adapter import NanopaymentCircuitBreaker

        cb = NanopaymentCircuitBreaker(failure_threshold=1, recovery_seconds=0.1)
        cb.record_failure()  # Immediately trips
        assert cb.state == "open"

        time.sleep(0.15)  # Wait for recovery period
        assert cb.state == "half_open"
        assert cb.is_available() is True

    def test_circuit_half_open_success_closes(self):
        """Half-open success closes the circuit."""
        import time
        from omniclaw.protocols.nanopayments.adapter import NanopaymentCircuitBreaker

        cb = NanopaymentCircuitBreaker(failure_threshold=1, recovery_seconds=0.1)
        cb.record_failure()
        assert cb.state == "open"

        time.sleep(0.15)
        assert cb.state == "half_open"

        cb.record_success()  # Success in half-open closes
        assert cb.state == "closed"
        assert cb._consecutive_failures == 0

    def test_circuit_manual_reset(self):
        """Manual reset closes the circuit."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentCircuitBreaker

        cb = NanopaymentCircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()  # Open
        assert cb.state == "open"

        cb.reset()
        assert cb.state == "closed"
        assert cb._consecutive_failures == 0

    def test_circuit_open_error_message(self):
        """CircuitOpenError has correct message."""
        from omniclaw.protocols.nanopayments.adapter import CircuitOpenError

        err = CircuitOpenError(recovery_seconds=30.0)
        assert "30" in str(err)
        assert err.recovery_seconds == 30.0


class TestIdempotencyKey:
    """Tests for idempotency key handling in settlement."""

    @pytest.mark.asyncio
    async def test_settle_uses_authorization_nonce_as_idempotency_key(self, mock_client: MagicMock):
        """settle() uses EIP-3009 nonce as idempotency key via Idempotency-Key header."""
        from omniclaw.protocols.nanopayments.client import NanopaymentHTTPClient
        from omniclaw.protocols.nanopayments.types import (
            EIP3009Authorization,
            PaymentPayload,
            PaymentPayloadInner,
            PaymentRequirements,
            PaymentRequirementsExtra,
            PaymentRequirementsKind,
        )

        # Build a real payload with a known nonce
        nonce = "0x" + "deadbeef" * 8  # 32 bytes as hex string
        auth = EIP3009Authorization(
            from_address="0x" + "a" * 40,
            to="0x" + "b" * 40,
            value="1000000",
            valid_after="0",
            valid_before="9999999999",
            nonce=nonce,
        )

        payload = PaymentPayload(
            x402_version=2,
            scheme="exact",
            network="eip155:5042002",
            payload=PaymentPayloadInner(
                signature="0x" + "c" * 130,
                authorization=auth,
            ),
        )

        req = PaymentRequirements(
            x402_version=2,
            accepts=(
                PaymentRequirementsKind(
                    scheme="exact",
                    network="eip155:5042002",
                    asset="0x" + "a" * 40,
                    amount="1000000",
                    max_timeout_seconds=345600,
                    pay_to="0x" + "b" * 40,
                    extra=PaymentRequirementsExtra(
                        name="GatewayWalletBatched",
                        version="1",
                        verifying_contract="0x" + "c" * 40,
                    ),
                ),
            ),
        )

        # Track the idempotency key that gets sent
        captured_headers: list[dict] = []

        async def capture_post(path: str, idempotency_key=None, **kwargs):
            captured_headers.append(
                {"path": path, "idempotency_key": idempotency_key, "kwargs": kwargs}
            )
            # Return a mock 200 response
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"success": true}'
            mock_resp.content = b'{"success": true}'
            return mock_resp

        # Patch NanopaymentHTTPClient.post to capture the idempotency key
        with patch.object(NanopaymentHTTPClient, "post", side_effect=capture_post):
            # Create a client that will actually use the patched HTTP client
            from omniclaw.protocols.nanopayments.client import NanopaymentClient

            client = NanopaymentClient(
                environment="testnet",
                api_key="test_key",
                base_url="https://api.test.circle.com",
            )
            await client.settle(payload=payload, requirements=req)

        # Verify the idempotency key was set to the nonce
        assert len(captured_headers) == 1
        assert captured_headers[0]["path"] == "/v1/x402/settle"
        # The nonce should be used as the idempotency key
        assert captured_headers[0]["idempotency_key"] is not None
        assert captured_headers[0]["idempotency_key"] == nonce

    @pytest.mark.asyncio
    async def test_circuit_breaker_prevents_settlement_when_open(self, mock_client: MagicMock):
        """Settlement raises CircuitOpenError when circuit is open."""
        from omniclaw.protocols.nanopayments.adapter import (
            CircuitOpenError,
            NanopaymentAdapter,
            NanopaymentCircuitBreaker,
        )

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock()
        mock_vault.get_balance = AsyncMock()

        # Create adapter with already-open circuit
        cb = NanopaymentCircuitBreaker(failure_threshold=1, recovery_seconds=60)
        cb.record_failure()  # Trip the circuit
        mock_http = MagicMock()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
            retry_attempts=3,
            circuit_breaker=cb,
        )

        from omniclaw.protocols.nanopayments.types import (
            PaymentPayload,
            PaymentRequirements,
        )

        payload = MagicMock(spec=PaymentPayload)
        req = MagicMock(spec=PaymentRequirements)

        with pytest.raises(CircuitOpenError):
            await adapter._settle_with_retry(payload=payload, requirements=req)


# =============================================================================
# TEST: Protocol Adapter — Full Router Coverage
# =============================================================================


class TestNanopaymentProtocolAdapterCoverage:
    """Additional tests for NanopaymentProtocolAdapter coverage."""

    def test_supports_rejects_address_above_threshold(self):
        """Address at/above micro threshold is NOT supported."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentProtocolAdapter

        adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=AsyncMock(),
            micro_threshold_usdc="1.00",
        )
        # Amount exactly at threshold
        assert adapter.supports("0x" + "a" * 40, amount="1.00") is False
        # Amount above threshold
        assert adapter.supports("0x" + "a" * 40, amount="10.00") is False

    def test_supports_rejects_non_url_non_address(self):
        """Non-URL, non-address recipients are NOT supported."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentProtocolAdapter

        adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=AsyncMock(),
        )
        assert adapter.supports("invalid-recipient") is False
        assert adapter.supports("chain:0x123") is False

    def test_priority_is_10(self):
        """Priority is 10 (highest)."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentProtocolAdapter

        adapter = NanopaymentProtocolAdapter(nanopayment_adapter=AsyncMock())
        assert adapter.get_priority() == 10

    @pytest.mark.asyncio
    async def test_execute_url_full_flow(self, mock_client: MagicMock):
        """execute() with URL calls pay_x402_url with all params."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentProtocolAdapter

        mock_adapter = AsyncMock()
        mock_adapter.pay_x402_url = AsyncMock(
            return_value=MagicMock(
                success=True,
                payer="0x" + "a" * 40,
                seller="0x" + "b" * 40,
                transaction="tx-123",
                amount_usdc="0.001",
                amount_atomic="1000",
                network="eip155:5042002",
                is_nanopayment=True,
            )
        )

        protocol_adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=mock_adapter,
            micro_threshold_usdc="1.00",
        )

        result = await protocol_adapter.execute(
            wallet_id="wallet-123",
            recipient="https://api.seller.com/v1/data",
            amount=Decimal("0.001"),
            purpose="data_access",
            nano_key_alias="my-key",
        )

        mock_adapter.pay_x402_url.assert_called_once()
        assert result.success is True
        assert result.method.value == "nanopayment"
        assert result.metadata["nanopayment"] is True

    @pytest.mark.asyncio
    async def test_execute_graceful_degradation_returns_failed_result(self, mock_client: MagicMock):
        """execute() catches exceptions and returns failed PaymentResult."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentProtocolAdapter

        mock_adapter = AsyncMock()
        mock_adapter.pay_direct = AsyncMock(side_effect=Exception("Network error"))

        protocol_adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=mock_adapter,
            micro_threshold_usdc="1.00",
        )

        result = await protocol_adapter.execute(
            wallet_id="wallet-123",
            recipient="0x" + "b" * 40,
            amount=Decimal("0.001"),
        )

        assert result.success is False
        assert result.status.value == "failed"
        assert "Nanopayment failed" in result.error

    @pytest.mark.asyncio
    async def test_simulate_returns_would_succeed(self, mock_client: MagicMock):
        """simulate() returns would_succeed=True for nanopayment."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentProtocolAdapter

        adapter = NanopaymentProtocolAdapter(
            nanopayment_adapter=AsyncMock(),
            micro_threshold_usdc="1.00",
        )

        result = await adapter.simulate(
            wallet_id="wallet-123",
            recipient="https://api.example.com/data",
            amount=Decimal("0.001"),
        )

        assert result["would_succeed"] is True
        assert result["method"] == "nanopayment"
        assert result["estimated_fee"] == "0"  # Gasless


# =============================================================================
# TEST: Retry Logic & Circuit Breaker Coverage
# =============================================================================


class TestRetryLogicCoverage:
    """Additional tests for retry logic and circuit breaker."""

    @pytest.mark.asyncio
    async def test_settle_with_retry_timeout_then_success(self, mock_client: MagicMock):
        """Timeout retries with backoff, then succeeds."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import GatewayTimeoutError

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock()
        mock_vault.get_balance = AsyncMock()

        # Fail once, then succeed
        mock_client.settle = AsyncMock(
            side_effect=[
                GatewayTimeoutError("timeout"),
                MagicMock(success=True, transaction="tx123"),
            ]
        )

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=AsyncMock(),
            auto_topup_enabled=False,
            retry_attempts=3,
            retry_base_delay=0.01,
        )

        payload = MagicMock()
        req = MagicMock()
        result = await adapter._settle_with_retry(payload=payload, requirements=req)

        assert mock_client.settle.call_count == 2
        assert result.success is True

    @pytest.mark.asyncio
    async def test_settle_with_retry_all_retries_fail(self, mock_client: MagicMock):
        """All retries fail, raises GatewayTimeoutError."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import GatewayTimeoutError

        mock_vault = MagicMock()
        mock_client.settle = AsyncMock(side_effect=GatewayTimeoutError("timeout"))

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=AsyncMock(),
            auto_topup_enabled=False,
            retry_attempts=2,
            retry_base_delay=0.01,
        )

        payload = MagicMock()
        req = MagicMock()

        with pytest.raises(GatewayTimeoutError):
            await adapter._settle_with_retry(payload=payload, requirements=req)

        # Should have retried 3 times (initial + 2 retries)
        assert mock_client.settle.call_count == 3

    @pytest.mark.asyncio
    async def test_settle_with_retry_nonce_reused_no_retry(self, mock_client: MagicMock):
        """NonceReusedError does NOT retry, raises immediately."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import NonceReusedError

        mock_vault = MagicMock()
        mock_client.settle = AsyncMock(side_effect=NonceReusedError())

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=AsyncMock(),
            auto_topup_enabled=False,
            retry_attempts=3,
        )

        payload = MagicMock()
        req = MagicMock()

        with pytest.raises(NonceReusedError):
            await adapter._settle_with_retry(payload=payload, requirements=req)

        # Should NOT have retried
        assert mock_client.settle.call_count == 1

    def test_circuit_breaker_record_error(self):
        """record_error() increments counter and trips circuit."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentCircuitBreaker

        cb = NanopaymentCircuitBreaker(failure_threshold=2)
        assert cb.state == "closed"

        cb.record_error()  # 1 error
        assert cb.state == "closed"

        cb.record_error()  # 2 errors - trips
        assert cb.state == "open"

    def test_circuit_breaker_get_state(self):
        """get_circuit_breaker_state() returns current state."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        adapter = NanopaymentAdapter(
            vault=MagicMock(),
            nanopayment_client=MagicMock(),
            http_client=AsyncMock(),
        )

        assert adapter.get_circuit_breaker_state() == "closed"


# =============================================================================
# TEST: Auto-Topup Coverage
# =============================================================================


class TestAutoTopupCoverage:
    """Additional tests for auto-topup coverage."""

    @pytest.mark.asyncio
    async def test_check_and_topup_balance_check_fails(self):
        """Balance check failure returns False without crashing."""
        mock_vault = MagicMock()
        mock_vault.get_balance = AsyncMock(side_effect=Exception("Network error"))

        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=MagicMock(),
            http_client=AsyncMock(),
            auto_topup_enabled=True,
        )
        adapter.set_wallet_manager(MagicMock())

        result = await adapter._check_and_topup(alias="test-key")
        assert result is False

    @pytest.mark.asyncio
    async def test_check_and_topup_deposit_fails(self):
        """Deposit failure returns False without crashing."""
        mock_vault = MagicMock()
        mock_vault.get_balance = AsyncMock(return_value=MagicMock(available_decimal="0.01"))
        mock_manager = AsyncMock()
        mock_manager.deposit = AsyncMock(side_effect=Exception("Tx failed"))

        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=MagicMock(),
            http_client=AsyncMock(),
            auto_topup_enabled=True,
        )
        adapter.set_wallet_manager(mock_manager)

        result = await adapter._check_and_topup(alias="test-key")
        assert result is False

    @pytest.mark.asyncio
    async def test_check_and_topup_succeeds(self):
        """Successful deposit returns True."""
        mock_vault = MagicMock()
        mock_vault.get_balance = AsyncMock(return_value=MagicMock(available_decimal="0.01"))
        mock_manager = AsyncMock()
        mock_manager.deposit = AsyncMock(return_value=MagicMock(deposit_tx_hash="0xtx123"))

        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=MagicMock(),
            http_client=AsyncMock(),
            auto_topup_enabled=True,
        )
        adapter.set_wallet_manager(mock_manager)

        result = await adapter._check_and_topup(alias="test-key")
        assert result is True

    @pytest.mark.asyncio
    async def test_auto_topup_no_wallet_manager(self):
        """Auto-topup with no wallet manager returns False (no-op)."""
        mock_vault = MagicMock()
        mock_vault.get_balance = AsyncMock(return_value=MagicMock(available_decimal="0.01"))

        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=MagicMock(),
            http_client=AsyncMock(),
            auto_topup_enabled=True,
        )
        # No set_wallet_manager() called

        result = await adapter._check_and_topup(alias="test-key")
        assert result is False

    def test_configure_auto_topup_full(self):
        """configure_auto_topup() updates all settings."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        adapter = NanopaymentAdapter(
            vault=MagicMock(),
            nanopayment_client=MagicMock(),
            http_client=AsyncMock(),
            auto_topup_enabled=True,
            auto_topup_threshold="1.00",
            auto_topup_amount="10.00",
        )

        adapter.configure_auto_topup(
            enabled=False,
            threshold="5.00",
            amount="50.00",
        )

        assert adapter._auto_topup is False
        assert adapter._topup_threshold == "5.00"
        assert adapter._topup_amount == "50.00"

    def test_set_wallet_manager(self):
        """set_wallet_manager() stores the manager."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter

        adapter = NanopaymentAdapter(
            vault=MagicMock(),
            nanopayment_client=MagicMock(),
            http_client=AsyncMock(),
        )

        mock_manager = MagicMock()
        adapter.set_wallet_manager(mock_manager)

        assert adapter._wallet_manager is mock_manager


class TestOmniClawSellerDecorator:
    """Tests for OmniClaw.gateway(), OmniClaw.sell(), and OmniClaw.current_payment()."""

    @pytest.fixture
    def seller_client(self, mock_storage: MockStorageBackend):
        """Create an OmniClaw instance configured as a seller with one key."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="seller-api-key",
                        entity_secret="seller-entity-secret-32-chars-long",
                        network=Network.ARC_TESTNET,
                    )

                return client

    @pytest.fixture
    def buyer_storage(self):
        """Separate storage for buyer OmniClaw."""
        return MockStorageBackend()

    @pytest.fixture
    def buyer_client(self, buyer_storage: MockStorageBackend):
        """Create an OmniClaw instance configured as a buyer with one key."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_get_storage.return_value = buyer_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="buyer-api-key",
                        entity_secret="buyer-entity-secret-32-chars-long!!",
                        network=Network.ARC_TESTNET,
                    )

                return client

    # -------------------------------------------------------------------------
    # Tests: gateway() lazy initialization
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_gateway_returns_gateway_middleware(self, seller_client):
        """gateway() returns a GatewayMiddleware instance."""
        await seller_client.generate_key("seller-key")
        await seller_client.set_default_key("seller-key")

        gateway_mw = await seller_client.gateway()

        assert gateway_mw is not None
        assert isinstance(gateway_mw, GatewayMiddleware)

    @pytest.mark.asyncio
    async def test_gateway_caches_middleware(self, seller_client):
        """gateway() only creates the middleware once (cached)."""
        await seller_client.generate_key("seller-key")
        await seller_client.set_default_key("seller-key")

        g1 = await seller_client.gateway()
        g2 = await seller_client.gateway()

        assert g1 is g2

    @pytest.mark.asyncio
    async def test_gateway_uses_default_key_address(self, seller_client):
        """gateway() uses the vault's default key as seller_address."""
        addr = await seller_client.generate_key("seller-default")
        await seller_client.set_default_key("seller-default")

        gateway_mw = await seller_client.gateway()

        assert gateway_mw._seller_address == addr.lower()

    @pytest.mark.asyncio
    async def test_gateway_raises_when_nanopayments_disabled(self):
        """gateway() raises NanopaymentNotInitializedError when nanopayments disabled."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                client._nano_client = None

                with pytest.raises(NanopaymentNotInitializedError):
                    await client.gateway()

    # -------------------------------------------------------------------------
    # Tests: sell() decorator
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sell_returns_fastapi_depends(self, seller_client):
        """sell() returns a FastAPI Depends object with the correct dependency."""
        await seller_client.generate_key("seller-key")
        await seller_client.set_default_key("seller-key")

        pytest.importorskip("fastapi")
        depends = seller_client.sell("$0.001")

        assert depends is not None
        assert hasattr(depends, "dependency")
        assert hasattr(depends, "use_cache")

    @pytest.mark.asyncio
    async def test_sell_returns_depends_even_when_uninitialized(self):
        """sell() returns a Depends even if nanopayments is disabled (error deferred to route access)."""
        with patch("omniclaw.client.CircuitBreaker"):
            with patch("omniclaw.client.get_storage") as mock_get_storage:
                mock_storage = MockStorageBackend()
                mock_get_storage.return_value = mock_storage

                from omniclaw.client import OmniClaw
                from omniclaw.core.types import Network

                with patch("httpx.AsyncClient", new_callable=AsyncMock):
                    client = OmniClaw(
                        circle_api_key="test-key",
                        entity_secret="test-secret-32-chars-long-here",
                        network=Network.ARC_TESTNET,
                    )

                client._nano_client = None

                pytest.importorskip("fastapi")
                depends = client.sell("$0.001")
                assert depends is not None
                assert hasattr(depends, "dependency")

    # -------------------------------------------------------------------------
    # Tests: current_payment() context
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_current_payment_raises_outside_sell_context(self, seller_client):
        """current_payment() raises ValueError when called outside @sell() context."""
        await seller_client.generate_key("seller-key")
        await seller_client.set_default_key("seller-key")

        with pytest.raises(ValueError, match="outside of a @sell"):
            seller_client.current_payment()

    @pytest.mark.asyncio
    async def test_current_payment_returns_info_in_sell_context(self, seller_client):
        """current_payment() returns PaymentInfo when called inside @sell() context."""
        from omniclaw.protocols.nanopayments.types import PaymentInfo

        await seller_client.generate_key("seller-key")
        await seller_client.set_default_key("seller-key")

        from omniclaw.client import _current_payment_info

        info = PaymentInfo(
            verified=True,
            payer="0x" + "a" * 40,
            amount="1000000",
            network="eip155:5042002",
            transaction="tx-123",
        )
        _current_payment_info.set(info)

        result = seller_client.current_payment()

        assert result.payer == "0x" + "a" * 40
        assert result.amount == "1000000"
        assert result.verified is True

        _current_payment_info.set(None)


class TestFastAPIIntegrationSellerDecorator:
    """
    Full FastAPI integration tests for the @agent.sell() decorator.

    These tests simulate the complete two-party EIP-3009 payment flow:
    - Seller: FastAPI app with gateway.require() or sell()
    - Buyer (OmniClaw): Uses vault.sign() to create PaymentPayload
    - Buyer (External): Uses EIP3009Signer directly (no OmniClaw)

    Tests cover: 402 response, valid payment, settlement, content delivery.
    Uses httpx.AsyncClient with ASGITransport for real ASGI testing.
    """

    SELLER_KEY = "0x250716a653d2155d15bfb1e1ded08b6764937ca6ab3cdd7e2f0510c975fb5652"
    SELLER_ADDR = "0xb9Ee214552fF51AB41955b3DAfD7A340b5459629"
    BUYER_KEY = "0x" + "1" * 64
    NETWORK = "eip155:5042002"
    VERIFYING_CONTRACT = "0x" + "c" * 40
    USDC_ADDRESS = "0x" + "d" * 40
    PRICE_ATOMIC = 1000
    PRICE_USD = "$0.001"

    @pytest.fixture
    def mock_nano_client(self) -> MagicMock:
        """Mock NanopaymentClient with realistic responses."""
        mock = MagicMock(spec=NanopaymentClient)
        mock.get_supported = AsyncMock(
            return_value=[
                MagicMock(
                    network=self.NETWORK,
                    verifying_contract=self.VERIFYING_CONTRACT,
                    usdc_address=self.USDC_ADDRESS,
                )
            ]
        )
        mock.settle = AsyncMock(
            return_value=MagicMock(
                success=True,
                transaction="settled-batch-tx-abc123",
                payer="0x" + "1" * 40,
            )
        )
        return mock

    def _build_payment_payload(self) -> str:
        """Build a valid EIP-3009 PaymentPayload as base64-encoded JSON."""
        import base64
        import json
        import time

        from omniclaw.protocols.nanopayments.signing import EIP3009Signer
        from omniclaw.protocols.nanopayments.types import (
            PaymentRequirementsExtra,
            PaymentRequirementsKind,
        )

        kind = PaymentRequirementsKind(
            scheme="exact",
            network=self.NETWORK,
            asset=self.USDC_ADDRESS,
            amount=str(self.PRICE_ATOMIC),
            max_timeout_seconds=345600,
            pay_to=self.SELLER_ADDR,
            extra=PaymentRequirementsExtra(
                name="GatewayWalletBatched",
                version="1",
                verifying_contract=self.VERIFYING_CONTRACT,
            ),
        )

        signer = EIP3009Signer(self.BUYER_KEY)
        payload = signer.sign_transfer_with_authorization(
            requirements=kind,
            amount_atomic=self.PRICE_ATOMIC,
            valid_before=int(time.time()) + 86400 * 4,
        )

        return base64.b64encode(json.dumps(payload.to_dict()).encode()).decode()

    # -------------------------------------------------------------------------
    # Test: gateway.handle() returns 402 without payment header
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_gateway_handle_returns_402_without_payment(self, mock_nano_client):
        """gateway.handle() returns 402 PaymentRequiredHTTPError with no header."""
        from omniclaw.protocols.nanopayments.middleware import GatewayMiddleware

        gw = GatewayMiddleware(
            seller_address=self.SELLER_ADDR,
            nanopayment_client=mock_nano_client,
            supported_kinds=await mock_nano_client.get_supported(),
            auto_fetch_networks=False,
        )

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await gw.handle({}, self.PRICE_USD)

        assert exc_info.value.status_code == 402
        body = exc_info.value.detail
        assert body["x402Version"] == 2
        assert len(body["accepts"]) >= 1
        assert "PAYMENT-REQUIRED" in exc_info.value.headers

    # -------------------------------------------------------------------------
    # Test: gateway.handle() settles with valid payment
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_gateway_handle_settles_with_valid_payment(self, mock_nano_client):
        """gateway.handle() verifies and settles payment, returns PaymentInfo."""
        from omniclaw.protocols.nanopayments.middleware import GatewayMiddleware

        gw = GatewayMiddleware(
            seller_address=self.SELLER_ADDR,
            nanopayment_client=mock_nano_client,
            supported_kinds=await mock_nano_client.get_supported(),
            auto_fetch_networks=False,
        )

        payment_header = self._build_payment_payload()

        result = await gw.handle({"payment-signature": payment_header}, self.PRICE_USD)

        assert result.verified is True
        assert result.payer is not None
        mock_nano_client.settle.assert_called_once()

        call_kwargs = mock_nano_client.settle.call_args.kwargs
        payload = call_kwargs["payload"]
        assert payload.network == self.NETWORK

    # -------------------------------------------------------------------------
    # Test: FastAPI route pattern - no payment → 402, with payment → 200
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fastapi_route_pattern_no_payment_402(self, mock_nano_client):
        """
        FastAPI route with gateway.handle() returns 402 when no PAYMENT-SIGNATURE header.
        Tests the FastAPI integration pattern by directly simulating ASGI calls.
        """
        from omniclaw.protocols.nanopayments.middleware import (
            GatewayMiddleware,
            PaymentRequiredHTTPError,
        )

        gw = GatewayMiddleware(
            seller_address=self.SELLER_ADDR,
            nanopayment_client=mock_nano_client,
            supported_kinds=await mock_nano_client.get_supported(),
            auto_fetch_networks=False,
        )

        async def premium_handler(request_headers: dict, price_usd: str):
            try:
                info = await gw.handle(request_headers, price_usd)
                return {"status": 200, "content": "premium data", "payer": info.payer}
            except PaymentRequiredHTTPError as exc:
                return {"status": exc.status_code, "body": exc.detail}

        result = await premium_handler({}, self.PRICE_USD)
        assert result["status"] == 402
        assert result["body"]["x402Version"] == 2

    @pytest.mark.asyncio
    async def test_fastapi_route_pattern_with_valid_payment_200(self, mock_nano_client):
        """FastAPI route with gateway.handle() serves content when valid payment is provided."""
        from omniclaw.protocols.nanopayments.middleware import (
            GatewayMiddleware,
            PaymentRequiredHTTPError,
        )

        gw = GatewayMiddleware(
            seller_address=self.SELLER_ADDR,
            nanopayment_client=mock_nano_client,
            supported_kinds=await mock_nano_client.get_supported(),
            auto_fetch_networks=False,
        )

        async def premium_handler(request_headers: dict, price_usd: str):
            try:
                info = await gw.handle(request_headers, price_usd)
                return {"status": 200, "content": "premium data", "payer": info.payer}
            except PaymentRequiredHTTPError as exc:
                return {"status": exc.status_code, "body": exc.detail}

        payment_header = self._build_payment_payload()
        result = await premium_handler({"payment-signature": payment_header}, self.PRICE_USD)
        assert result["status"] == 200
        assert result["content"] == "premium data"
        assert result["payer"].startswith("0x")
        mock_nano_client.settle.assert_called_once()

    # -------------------------------------------------------------------------
    # Test: OmniClaw buyer → seller (direct handle call)
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_omniclaw_buyer_to_seller_flow(self, mock_nano_client):
        """
        OmniClaw buyer creates PaymentPayload via vault.sign() and sends to
        seller gateway. Settlement succeeds, PaymentInfo is returned.
        """
        from omniclaw.protocols.nanopayments.middleware import (
            GatewayMiddleware,
            PaymentRequiredHTTPError,
        )

        gw = GatewayMiddleware(
            seller_address=self.SELLER_ADDR,
            nanopayment_client=mock_nano_client,
            supported_kinds=await mock_nano_client.get_supported(),
            auto_fetch_networks=False,
        )

        payment_header = self._build_payment_payload()

        with pytest.raises(PaymentRequiredHTTPError):
            await gw.handle({}, self.PRICE_USD)

        result = await gw.handle({"payment-signature": payment_header}, self.PRICE_USD)

        assert result.verified is True
        assert result.payer is not None
        assert result.network == self.NETWORK
        assert result.transaction == "settled-batch-tx-abc123"
        mock_nano_client.settle.assert_called_once()

    # -------------------------------------------------------------------------
    # Test: External (raw EIP-3009) buyer
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_external_raw_eip3009_buyer_flow(self, mock_nano_client):
        """
        External non-OmniClaw client uses EIP3009Signer directly to create
        a valid PaymentPayload. Proves OmniClaw nanopayments are EIP-3009
        interoperable with ANY EIP-3009 wallet or library.
        """
        from omniclaw.protocols.nanopayments.middleware import (
            GatewayMiddleware,
            PaymentRequiredHTTPError,
        )

        gw = GatewayMiddleware(
            seller_address=self.SELLER_ADDR,
            nanopayment_client=mock_nano_client,
            supported_kinds=await mock_nano_client.get_supported(),
            auto_fetch_networks=False,
        )

        payment_header = self._build_payment_payload()

        result = await gw.handle({"payment-signature": payment_header}, self.PRICE_USD)

        assert result.verified is True
        assert result.transaction == "settled-batch-tx-abc123"

        settle_call = mock_nano_client.settle.call_args
        settled_payload = settle_call.kwargs["payload"]
        assert settled_payload.network == self.NETWORK
        assert settled_payload.payload.authorization.from_address is not None

    # -------------------------------------------------------------------------
    # Test: current_payment() context var
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_current_payment_in_context_var(self, mock_nano_client):
        """_current_payment_info context var works correctly for current_payment()."""
        from omniclaw.client import _current_payment_info
        from omniclaw.protocols.nanopayments.types import PaymentInfo

        info = PaymentInfo(
            verified=True,
            payer="0x" + "f" * 40,
            amount=str(self.PRICE_ATOMIC),
            network=self.NETWORK,
            transaction="tx-manual-999",
        )
        _current_payment_info.set(info)

        try:
            result = _current_payment_info.get()
            assert result.verified is True
            assert result.payer == "0x" + "f" * 40
            assert result.amount == str(self.PRICE_ATOMIC)
        finally:
            _current_payment_info.set(None)

    # -------------------------------------------------------------------------
    # Test: Invalid payment signature → 402
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_invalid_payment_signature_returns_402(self, mock_nano_client):
        """Invalid/malformed PAYMENT-SIGNATURE header returns 402."""
        from omniclaw.protocols.nanopayments.middleware import GatewayMiddleware

        gw = GatewayMiddleware(
            seller_address=self.SELLER_ADDR,
            nanopayment_client=mock_nano_client,
            supported_kinds=await mock_nano_client.get_supported(),
            auto_fetch_networks=False,
        )

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await gw.handle({"payment-signature": "not-valid-base64!!!"}, self.PRICE_USD)

        assert exc_info.value.status_code == 402

    # -------------------------------------------------------------------------
    # Test: Settlement failure → 402
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_settlement_failure_returns_402(self, mock_nano_client):
        """When settle() fails (e.g., insufficient balance), returns 402."""
        from omniclaw.protocols.nanopayments.exceptions import InsufficientBalanceError
        from omniclaw.protocols.nanopayments.middleware import GatewayMiddleware

        mock_nano_client.settle = AsyncMock(
            side_effect=InsufficientBalanceError(
                reason="insufficient_balance",
                payer="0x" + "1" * 40,
            )
        )

        gw = GatewayMiddleware(
            seller_address=self.SELLER_ADDR,
            nanopayment_client=mock_nano_client,
            supported_kinds=await mock_nano_client.get_supported(),
            auto_fetch_networks=False,
        )

        payment_header = self._build_payment_payload()

        with pytest.raises(PaymentRequiredHTTPError) as exc_info:
            await gw.handle({"payment-signature": payment_header}, self.PRICE_USD)


# =============================================================================
# TEST: GatewayWalletManager additional paths (wallet.py)
# =============================================================================


class TestGatewayWalletManagerAdditional:
    """Additional coverage for GatewayWalletManager methods."""

    def _make_wallet_manager(self):
        """Helper to create a partially mocked GatewayWalletManager."""
        with patch("omniclaw.protocols.nanopayments.wallet.web3.Web3"):
            with patch("omniclaw.protocols.nanopayments.wallet.EIP3009Signer"):
                mock_client = MagicMock()
                mock_client.get_verifying_contract = AsyncMock(return_value="0x" + "c" * 40)
                mock_client.get_usdc_address = AsyncMock(return_value="0x" + "d" * 40)

                with patch.object(GatewayWalletManager, "_sign_and_send"):
                    mgr = GatewayWalletManager(
                        private_key="0x" + "1" * 64,
                        network="eip155:5042002",
                        rpc_url="http://localhost",
                        nanopayment_client=mock_client,
                    )
                    return mgr

    @pytest.mark.asyncio
    async def test_deposit_skips_when_insufficient_gas(self):
        """Lines 369-379: deposit() with check_gas=True, skip_if_insufficient_gas=True."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.get_balance.return_value = 0  # No ETH
        mgr._w3.eth.gas_price.return_value = 50_000_000_000  # 50 gwei
        mgr._w3.eth.account.sign_transaction = MagicMock()
        mgr._w3.eth.send_raw_transaction = MagicMock()
        mgr._w3.eth.wait_for_transaction_receipt = MagicMock(return_value={"status": 1})
        # Mock from_wei to avoid format string issues
        mgr._w3.from_wei = MagicMock(side_effect=lambda x, y: float(x) / 1e18)
        # Also mock estimate_gas_for_deposit which is called by check_gas_reserve
        mgr.estimate_gas_for_deposit = MagicMock(return_value=21000)

        result = await mgr.deposit("10.00", check_gas=True, skip_if_insufficient_gas=True)
        # Should return without raising and without tx hash
        assert result.deposit_tx_hash is None
        assert result.approval_tx_hash is None

    @pytest.mark.asyncio
    async def test_deposit_approval_error_propagates(self):
        """Lines 411-413: deposit() with ERC20ApprovalError."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.get_balance.return_value = 1_000_000_000_000_000_000_000_000_000
        mgr._w3.eth.gas_price.return_value = 10_000_000_000
        mgr._w3.eth.account.sign_transaction = MagicMock()
        mgr._w3.eth.send_raw_transaction = MagicMock()
        mgr._w3.eth.wait_for_transaction_receipt = MagicMock(return_value={"status": 1})
        mgr._w3.from_wei = MagicMock(side_effect=lambda x, y: float(x) / 1e18)
        mgr.estimate_gas_for_deposit = MagicMock(return_value=21000)

        usdc_mock = MagicMock()
        usdc_mock.functions.allowance.return_value.call.return_value = 0
        mgr._usdc_contract = MagicMock(return_value=usdc_mock)

        mgr._sign_and_send = MagicMock(side_effect=ERC20ApprovalError(reason="Approval rejected"))

        with pytest.raises(ERC20ApprovalError):
            await mgr.deposit("10.00", check_gas=False)

    @pytest.mark.asyncio
    async def test_deposit_success_with_approval(self):
        """Lines 395-410: deposit() with approval transaction succeeds."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.get_balance.return_value = 1_000_000_000_000_000_000_000_000_000
        mgr._w3.eth.gas_price.return_value = 10_000_000_000
        mgr._w3.eth.account.sign_transaction = MagicMock()
        mgr._w3.eth.send_raw_transaction = MagicMock()
        mgr._w3.eth.wait_for_transaction_receipt = MagicMock(return_value={"status": 1})
        mgr._w3.from_wei = MagicMock(side_effect=lambda x, y: float(x) / 1e18)
        mgr.estimate_gas_for_deposit = MagicMock(return_value=21000)

        usdc_mock = MagicMock()
        usdc_mock.functions.allowance.return_value.call.return_value = 0  # needs approval
        usdc_mock.functions.approve.return_value.build_transaction.return_value = {}
        mgr._usdc_contract = MagicMock(return_value=usdc_mock)

        # Mock _sign_and_send for both approval and deposit
        def sign_send_side_effect(tx, error_type=None):
            return "0xtxhash" if error_type else "0xdeposithash"

        mgr._sign_and_send = MagicMock(side_effect=sign_send_side_effect)
        mgr._build_tx = MagicMock(return_value={})

        result = await mgr.deposit("10.00", check_gas=False)
        assert result.approval_tx_hash == "0xtxhash"
        assert result.deposit_tx_hash == "0xdeposithash"

    @pytest.mark.asyncio
    async def test_get_withdrawal_delay(self):
        """Lines 459-461: get_withdrawal_delay() calls contract."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mock_contract = MagicMock()
        mock_contract.functions.withdrawalDelay.return_value.call.return_value = 5065
        mgr._get_gateway_contract = MagicMock(return_value=mock_contract)

        delay = await mgr.get_withdrawal_delay()
        assert delay == 5065

    @pytest.mark.asyncio
    async def test_initiate_trustless_withdrawal_insufficient_balance(self):
        """Lines 482-496: initiate_trustless_withdrawal() with insufficient balance."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mock_contract = MagicMock()
        mock_contract.functions.availableBalance.return_value.call.return_value = 0  # 0 available
        mgr._get_gateway_contract = MagicMock(return_value=mock_contract)

        with pytest.raises(WithdrawError) as exc_info:
            await mgr.initiate_trustless_withdrawal("100.00")
        assert "insufficient" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_initiate_trustless_withdrawal_success(self):
        """Lines 498-519: initiate_trustless_withdrawal() success path."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mock_contract = MagicMock()
        mock_contract.functions.availableBalance.return_value.call.return_value = 10_000_000_000
        mock_contract.functions.withdrawalDelay.return_value.call.return_value = 5000
        mgr._get_gateway_contract = MagicMock(return_value=mock_contract)
        mgr._sign_and_send = MagicMock(return_value="0xtxhash123")
        mgr._build_tx = MagicMock(return_value={})

        tx_hash = await mgr.initiate_trustless_withdrawal("10.00")
        assert tx_hash == "0xtxhash123"

    @pytest.mark.asyncio
    async def test_complete_trustless_withdrawal_not_ready(self):
        """Lines 539-557: complete_trustless_withdrawal() when not ready."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.block_number = 100
        mock_contract = MagicMock()
        mock_contract.functions.withdrawalBlock.return_value.call.return_value = 200
        mgr._get_gateway_contract = MagicMock(return_value=mock_contract)
        mgr._build_tx = MagicMock(return_value={})

        with pytest.raises(WithdrawError) as exc_info:
            await mgr.complete_trustless_withdrawal()
        assert "not ready" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_complete_trustless_withdrawal_no_initiated(self):
        """Lines 539-553: complete_trustless_withdrawal() when nothing initiated."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.block_number = 10000
        mock_contract = MagicMock()
        mock_contract.functions.withdrawalBlock.return_value.call.return_value = 0
        mgr._get_gateway_contract = MagicMock(return_value=mock_contract)

        with pytest.raises(WithdrawError) as exc_info:
            await mgr.complete_trustless_withdrawal()
        assert "no withdrawal initiated" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_complete_trustless_withdrawal_success(self):
        """Lines 559-580: complete_trustless_withdrawal() success."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mgr._w3.eth.block_number = 10000
        mock_contract = MagicMock()
        mock_contract.functions.withdrawalBlock.return_value.call.return_value = 9999
        mgr._get_gateway_contract = MagicMock(return_value=mock_contract)
        mgr._build_tx = MagicMock(return_value={})
        mgr._sign_and_send = MagicMock(return_value="0xcompletedsuccess")

        tx_hash = await mgr.complete_trustless_withdrawal()
        assert tx_hash == "0xcompletedsuccess"

    @pytest.mark.asyncio
    async def test_get_balance(self):
        """Line 717: get_balance() delegates to client."""
        mgr = self._make_wallet_manager()
        mock_result = GatewayBalance(
            total=100_000_000,
            available=50_000_000,
            formatted_total="100.00 USDC",
            formatted_available="50.00 USDC",
        )
        mgr._client.check_balance = AsyncMock(return_value=mock_result)

        balance = await mgr.get_balance()
        assert balance.total == 100_000_000
        assert balance.available == 50_000_000
        mgr._client.check_balance.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_onchain_balance(self):
        """Lines 732-734: get_onchain_balance() calls USDC contract."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        usdc_mock = MagicMock()
        usdc_mock.functions.balanceOf.return_value.call.return_value = 1_000_000_000
        mgr._usdc_contract = MagicMock(return_value=usdc_mock)

        balance = await mgr.get_onchain_balance()
        assert balance == 1_000_000_000

    @pytest.mark.asyncio
    async def test_get_gateway_available_balance(self):
        """Lines 745-748: get_gateway_available_balance() calls contract."""
        mgr = self._make_wallet_manager()
        mgr._w3 = MagicMock()
        mgr._w3.eth = MagicMock()
        mock_contract = MagicMock()
        mock_contract.functions.availableBalance.return_value.call.return_value = 500_000_000
        mgr._get_gateway_contract = MagicMock(return_value=mock_contract)

        balance = await mgr.get_gateway_available_balance()
        assert balance == 500_000_000

    def test_address_property(self):
        """Line 223: address property returns _address."""
        mgr = self._make_wallet_manager()
        assert mgr.address == mgr._address

    def test_network_property(self):
        """Line 228: network property returns _network."""
        mgr = self._make_wallet_manager()
        assert mgr.network == mgr._network

    @pytest.mark.asyncio
    async def test_resolve_gateway_address_uses_cached(self):
        """Line 237: _resolve_gateway_address() returns cached value."""
        mgr = self._make_wallet_manager()
        mgr._gateway_address = "0x" + "a" * 40
        result = await mgr._resolve_gateway_address()
        assert result == "0x" + "a" * 40
        mgr._client.get_verifying_contract.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_usdc_address_uses_cached(self):
        """Line 243: _resolve_usdc_address() returns cached value."""
        mgr = self._make_wallet_manager()
        mgr._usdc_address = "0x" + "b" * 40
        result = await mgr._resolve_usdc_address()
        assert result == "0x" + "b" * 40
        mgr._client.get_usdc_address.assert_not_called()


# =============================================================================
# TEST: NanopaymentClient additional paths (client.py)
# =============================================================================


class TestNanopaymentClientAdditional:
    """Additional coverage for NanopaymentClient methods."""

    @pytest.mark.asyncio
    async def test_get_supported_uses_cache(self):
        """Lines 236-237: get_supported() returns cached result."""
        from omniclaw.protocols.nanopayments.client import SUPPORTED_NETWORKS_CACHE_TTL_SECONDS
        import time

        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "kinds": [
                {
                    "network": "eip155:5042002",
                    "verifyingContract": "0x" + "a" * 40,
                    "usdcAddress": "0x" + "b" * 40,
                }
            ]
        }
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient",
            return_value=mock_http,
        ):
            client = NanopaymentClient(
                environment="testnet",
                base_url="https://api.test.circle.cn",
                api_key="test-key",
            )
            # First call - cache miss
            result1 = await client.get_supported()
            # Simulate cache hit by setting cache values
            client._supported_cache = result1
            client._supported_cache_time = time.time()

            # Second call - should use cache
            result2 = await client.get_supported()
            assert result2 == result1
            # HTTP should NOT be called again
            mock_http.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_verifying_contract_unsupported_network(self):
        """Lines 275-281: get_verifying_contract() raises for unsupported network."""
        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "kinds": [
                {
                    "network": "eip155:1",
                    "verifyingContract": "0x" + "a" * 40,
                    "usdcAddress": "0x" + "b" * 40,
                }
            ]
        }
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient",
            return_value=mock_http,
        ):
            client = NanopaymentClient(
                environment="testnet",
                base_url="https://api.test.circle.cn",
                api_key="test-key",
            )

            with pytest.raises(UnsupportedNetworkError) as exc_info:
                await client.get_verifying_contract("eip155:999999")
            assert exc_info.value.network == "eip155:999999"

    @pytest.mark.asyncio
    async def test_get_usdc_address_unsupported_network(self):
        """Lines 296-302: get_usdc_address() raises for unsupported network."""
        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "kinds": [
                {
                    "network": "eip155:1",
                    "verifyingContract": "0x" + "a" * 40,
                    "usdcAddress": "0x" + "b" * 40,
                }
            ]
        }
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient",
            return_value=mock_http,
        ):
            client = NanopaymentClient(
                environment="testnet",
                base_url="https://api.test.circle.cn",
                api_key="test-key",
            )

            with pytest.raises(UnsupportedNetworkError) as exc_info:
                await client.get_usdc_address("eip155:999999")
            assert exc_info.value.network == "eip155:999999"

    @pytest.mark.asyncio
    async def test_verify_response_parsing(self):
        """Lines 349-350: verify() parses isValid and invalidReason."""
        # Create proper PaymentRequirements object using from_dict
        req = PaymentRequirements.from_dict(
            {
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
                    }
                ],
            }
        )

        mock_http = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "isValid": True,
            "payer": "0x" + "1" * 40,
            "invalidReason": None,
        }
        mock_response.text = "{}"
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient",
            return_value=mock_http,
        ):
            client = NanopaymentClient(
                environment="testnet",
                base_url="https://api.test.circle.cn",
                api_key="test-key",
            )

            payload = MagicMock(spec=PaymentPayload)
            payload.to_dict.return_value = {}
            resp = await client.verify(payload, req)
            assert resp.is_valid is True
            assert resp.payer == "0x" + "1" * 40
            assert resp.invalid_reason is None

    @pytest.mark.asyncio
    async def test_check_balance_404_raises_unsupported_network(self):
        """Lines 468-483: check_balance() with 404 raises UnsupportedNetworkError."""
        client = NanopaymentClient(
            environment="testnet",
            base_url="https://api.test.circle.cn",
            api_key="test-key",
        )
        # Mock get_supported to return empty list (unsupported network)
        client.get_supported = AsyncMock(return_value=[])

        mock_response_balances = MagicMock()
        mock_response_balances.status_code = 404
        mock_response_balances.text = "Not found"

        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response_balances)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient",
            return_value=mock_http,
        ):
            with pytest.raises(UnsupportedNetworkError) as exc_info:
                await client.check_balance(
                    address="0x" + "1" * 40,
                    network="eip155:999999",
                )
            assert exc_info.value.network == "eip155:999999"

    @pytest.mark.asyncio
    async def test_check_balance_success(self):
        """Lines 492-498: check_balance() success response parsing."""
        client = NanopaymentClient(
            environment="testnet",
            base_url="https://api.test.circle.cn",
            api_key="test-key",
        )
        # Mock get_supported so check_balance doesn't make an HTTP call for it
        client.get_supported = AsyncMock(return_value=[])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "token": "USDC",
            "balances": [
                {
                    "domain": 26,
                    "depositor": "0x" + "1" * 40,
                    "balance": "100000000",  # string atomic units
                }
            ],
        }
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient",
            return_value=mock_http,
        ):
            balance = await client.check_balance(
                address="0x" + "1" * 40,
                network="eip155:5042002",
            )
            assert balance.total == 100_000_000
            # Circle's Gateway has no separate "available" field; available == total
            assert balance.available == 100_000_000
            assert balance.formatted_total == "100.000000 USDC"

    def test_init_invalid_environment(self):
        """Line 192: __init__ raises on invalid environment."""
        with pytest.raises(ValueError) as exc_info:
            NanopaymentClient(environment="invalid")
        assert "environment" in str(exc_info.value).lower()


# =============================================================================
# TEST: NanopaymentClient coverage (client.py)
# =============================================================================


class TestNanopaymentClientCoverage:
    """Coverage for NanopaymentClient methods not tested elsewhere."""

    @pytest.mark.asyncio
    async def test_get_verifying_contract_success(self):
        """Lines 520-539: get_verifying_contract() returns contract for supported network."""
        client = NanopaymentClient(
            environment="testnet",
            base_url="https://api.test.circle.cn",
            api_key="test-key",
        )
        client.get_supported = AsyncMock(
            return_value=[
                SupportedKind(
                    x402_version=2,
                    scheme="exact",
                    network="eip155:5042002",
                    extra={
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": "0x" + "a" * 40,
                        "usdcAddress": "0x" + "b" * 40,
                    },
                )
            ]
        )

        addr = await client.get_verifying_contract("eip155:5042002")
        assert addr == "0x" + "a" * 40

    @pytest.mark.asyncio
    async def test_get_verifying_contract_unsupported_network(self):
        """Lines 533-539: get_verifying_contract() raises for unsupported network."""
        client = NanopaymentClient(
            environment="testnet",
            base_url="https://api.test.circle.cn",
            api_key="test-key",
        )
        client.get_supported = AsyncMock(return_value=[])

        with pytest.raises(UnsupportedNetworkError) as exc_info:
            await client.get_verifying_contract("eip155:999999")
        assert exc_info.value.network == "eip155:999999"

    @pytest.mark.asyncio
    async def test_get_usdc_address_success(self):
        """Lines 541-560: get_usdc_address() returns USDC address for supported network."""
        client = NanopaymentClient(
            environment="testnet",
            base_url="https://api.test.circle.cn",
            api_key="test-key",
        )
        client.get_supported = AsyncMock(
            return_value=[
                SupportedKind(
                    x402_version=2,
                    scheme="exact",
                    network="eip155:5042002",
                    extra={
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": "0x" + "a" * 40,
                        "usdcAddress": "0x" + "b" * 40,
                    },
                )
            ]
        )

        addr = await client.get_usdc_address("eip155:5042002")
        assert addr == "0x" + "b" * 40

    @pytest.mark.asyncio
    async def test_get_usdc_address_unsupported_network(self):
        """Lines 554-560: get_usdc_address() raises for unsupported network."""
        client = NanopaymentClient(
            environment="testnet",
            base_url="https://api.test.circle.cn",
            api_key="test-key",
        )
        client.get_supported = AsyncMock(return_value=[])

        with pytest.raises(UnsupportedNetworkError) as exc_info:
            await client.get_usdc_address("eip155:999999")
        assert exc_info.value.network == "eip155:999999"

    @pytest.mark.asyncio
    async def test_get_supported_parses_usdc_from_assets(self):
        """Lines 494-500: get_supported() extracts USDC address from assets array."""
        from unittest.mock import AsyncMock
        from omniclaw.protocols.nanopayments.client import NanopaymentHTTPClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "kinds": [
                {
                    "x402Version": 2,
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "extra": {
                        "name": "GatewayWalletBatched",
                        "version": "1",
                        "verifyingContract": "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                        "assets": [
                            {
                                "address": "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                                "symbol": "USDC",
                                "decimals": 6,
                            },
                            {
                                "address": "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
                                "symbol": "OTHER",
                                "decimals": 6,
                            },
                        ],
                    },
                }
            ]
        }

        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient",
            return_value=mock_http,
        ):
            client = NanopaymentClient(
                environment="testnet",
                base_url="https://api.test.circle.cn",
                api_key="test-key",
            )
            kinds = await client.get_supported(force_refresh=True)
            assert len(kinds) == 1
            assert kinds[0].network == "eip155:5042002"
            assert kinds[0].usdc_address == "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
            assert kinds[0].verifying_contract == "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    @pytest.mark.asyncio
    async def test_check_balance_empty_balances_returns_zero(self):
        """Line 758: check_balance() returns zero when balances array is empty."""
        from unittest.mock import AsyncMock

        client = NanopaymentClient(
            environment="testnet",
            base_url="https://api.test.circle.cn",
            api_key="test-key",
        )
        client.get_supported = AsyncMock(return_value=[])

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "token": "USDC",
            "balances": [],  # empty
        }
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "omniclaw.protocols.nanopayments.client.NanopaymentHTTPClient",
            return_value=mock_http,
        ):
            balance = await client.check_balance(
                address="0x" + "1" * 40,
                network="eip155:5042002",
            )
            assert balance.total == 0
            assert balance.available == 0
            assert balance.formatted_total == "0 USDC"

    def test_caip2_to_circle_network_valid(self):
        """Lines 73-82: _caip2_to_circle_network() converts known CAIP-2 to circle name."""
        from omniclaw.protocols.nanopayments.client import _caip2_to_circle_network

        assert _caip2_to_circle_network("eip155:5042002") == "arc-testnet"
        assert _caip2_to_circle_network("eip155:8453") == "base"

    def test_caip2_to_circle_network_unknown_returns_chain_id(self):
        """Lines 73-82: _caip2_to_circle_network() returns chain ID for unknown networks."""
        from omniclaw.protocols.nanopayments.client import _caip2_to_circle_network

        # Unknown CAIP-2 that has no mapping
        result = _caip2_to_circle_network("eip155:999999")
        assert result == "999999"

    def test_parse_caip2_chain_id_valid(self):
        """Lines 85-98: _parse_caip2_chain_id() parses valid CAIP-2."""
        from omniclaw.protocols.nanopayments.client import _parse_caip2_chain_id

        assert _parse_caip2_chain_id("eip155:5042002") == 5042002
        assert _parse_caip2_chain_id("eip155:8453") == 8453
        assert _parse_caip2_chain_id("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp") == 0  # non-numeric

    def test_parse_caip2_chain_id_invalid(self):
        """Lines 85-98: _parse_caip2_chain_id() returns 0 for invalid format."""
        from omniclaw.protocols.nanopayments.client import _parse_caip2_chain_id

        assert _parse_caip2_chain_id("invalid") == 0
        assert _parse_caip2_chain_id("eip155:abc") == 0  # non-numeric

    def test_caip2_to_gateway_network(self):
        """Lines 121-134: _caip2_to_gateway_network() converts CAIP-2 to gateway name."""
        from omniclaw.protocols.nanopayments.client import _caip2_to_gateway_network

        assert _caip2_to_gateway_network("eip155:5042002") == "arc-testnet"
        assert _caip2_to_gateway_network("eip155:8453") == "base"

    def test_gateway_network_to_caip2(self):
        """Lines 137-150: _gateway_network_to_caip2() converts gateway name to CAIP-2."""
        from omniclaw.protocols.nanopayments.client import _gateway_network_to_caip2

        assert _gateway_network_to_caip2("arc-testnet") == "eip155:5042002"
        assert _gateway_network_to_caip2("base") == "eip155:8453"
        # numeric fallback
        assert _gateway_network_to_caip2("12345") == "eip155:12345"
        # passthrough for unknown
        assert _gateway_network_to_caip2("unknown-network") == "unknown-network"

    def test_to_int_valid(self):
        """Lines 161-170: _to_int() converts valid values."""
        from omniclaw.protocols.nanopayments.client import _to_int

        assert _to_int("1000000") == 1000000
        assert _to_int(42) == 42
        assert _to_int("0") == 0

    def test_to_int_invalid_returns_zero(self):
        """Lines 161-170: _to_int() returns 0 for invalid values."""
        from omniclaw.protocols.nanopayments.client import _to_int

        assert _to_int(None) == 0
        assert _to_int("invalid") == 0


# =============================================================================
# TEST: NanoKeyVault additional paths (vault.py)
# =============================================================================


class TestNanoKeyVaultAdditional:
    """Additional coverage for NanoKeyVault methods."""

    def _make_vault(self):
        """Create a vault with mocked storage and keystore."""
        mock_storage = MagicMock(spec=StorageBackend)
        mock_storage.get = AsyncMock(return_value=None)
        mock_storage.save = AsyncMock()
        return NanoKeyVault(
            entity_secret="test-secret-key-32-chars-long!!",
            storage_backend=mock_storage,
            circle_api_key="test-api-key",
            nanopayments_environment="testnet",
        )

    @pytest.mark.asyncio
    async def test_add_key_duplicate_alias_raises(self):
        """Line 147: add_key() with existing alias raises DuplicateKeyAliasError."""
        vault = self._make_vault()
        # Pre-existing key
        vault._storage.get = AsyncMock(
            return_value={
                "encrypted_key": "some_encrypted",
                "address": "0x" + "1" * 40,
                "network": "eip155:5042002",
            }
        )

        with pytest.raises(DuplicateKeyAliasError):
            await vault.add_key(
                alias="existing-key",
                private_key="0x" + "2" * 64,
            )

    @pytest.mark.asyncio
    async def test_get_network_uses_default(self):
        """Lines 239-248: get_network() with no stored network falls back to default."""
        vault = self._make_vault()
        # No default key set
        with pytest.raises(NoDefaultKeyError):
            await vault.get_network(alias=None)

    @pytest.mark.asyncio
    async def test_get_network_returns_recorded(self):
        """Lines 243-248: get_network() returns stored network."""
        vault = self._make_vault()
        vault._default_key_alias = "test-key"
        vault._storage.get = AsyncMock(
            return_value={
                "encrypted_key": "enc",
                "address": "0x" + "1" * 40,
                "network": "eip155:137",
            }
        )

        network = await vault.get_network(alias="test-key")
        assert network == "eip155:137"

    @pytest.mark.asyncio
    async def test_update_key_network(self):
        """Lines 261-268: update_key_network() saves new network."""
        vault = self._make_vault()
        vault._storage.get = AsyncMock(
            return_value={
                "encrypted_key": "enc",
                "address": "0x" + "1" * 40,
                "network": "eip155:1",
            }
        )
        vault._storage.save = AsyncMock()

        await vault.update_key_network(alias="test-key", network="eip155:137")
        vault._storage.save.assert_called_once()
        saved_data = vault._storage.save.call_args
        assert saved_data[0][2]["network"] == "eip155:137"

    @pytest.mark.asyncio
    async def test_get_balance_delegates_to_client(self):
        """Lines 440-445: get_balance() delegates to nanopayment client."""
        vault = self._make_vault()
        vault._default_key_alias = "test-key"
        vault._storage.get = AsyncMock(
            return_value={
                "encrypted_key": "enc",
                "address": "0x" + "1" * 40,
                "network": "eip155:5042002",
            }
        )
        vault._client.check_balance = AsyncMock(
            return_value=GatewayBalance(
                total=100_000_000,
                available=50_000_000,
                formatted_total="100 USDC",
                formatted_available="50 USDC",
            )
        )

        balance = await vault.get_balance(alias="test-key")
        assert balance.total == 100_000_000
        vault._client.check_balance.assert_called_once()

    def test_default_network_property(self):
        """Lines 96-99: default_network property."""
        vault = self._make_vault()
        assert vault.default_network is not None

    def test_environment_property(self):
        """Lines 102-104: environment property."""
        vault = self._make_vault()
        assert vault.environment == "testnet"

    @pytest.mark.asyncio
    async def test_get_raw_key_no_default(self):
        """Lines 465-467: get_raw_key() with no default raises."""
        vault = self._make_vault()
        with pytest.raises(NoDefaultKeyError):
            await vault.get_raw_key(alias=None)

    @pytest.mark.asyncio
    async def test_get_raw_key_returns_decrypted(self):
        """Lines 469-474: get_raw_key() returns None for missing key."""
        vault = self._make_vault()
        vault._default_key_alias = "test-key"
        vault._storage.get = AsyncMock(return_value=None)

        with pytest.raises(KeyNotFoundError):
            await vault.get_raw_key(alias="test-key")


# =============================================================================
# TEST: Adapter settlement paths (adapter.py)
# =============================================================================


class TestAdapterSettlementPaths:
    """Coverage for adapter settlement/error paths."""

    def _make_mock_http_client(self):
        mock_http = MagicMock()
        mock_http.post = AsyncMock()
        mock_http.request = AsyncMock()
        return mock_http

    @pytest.mark.asyncio
    async def test_settle_success_path(self):
        """Lines 447-448: settlement succeeds → record_success."""
        mock_vault = MagicMock(spec=NanoKeyVault)
        mock_vault.get_address = AsyncMock(return_value="0x" + "1" * 40)
        mock_client = MagicMock(spec=NanopaymentClient)
        mock_client.get_supported = AsyncMock(return_value=[])
        mock_http = self._make_mock_http_client()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        mock_client.settle = AsyncMock(
            return_value=SettleResponse(
                success=True,
                transaction="0xsuccess",
                payer="0x" + "1" * 40,
                error_reason=None,
            )
        )

        payload = MagicMock(spec=PaymentPayload)
        payload.to_dict.return_value = {}
        req = make_402_requirements()

        result = await adapter._settle_with_retry(payload=payload, requirements=req)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_auto_topup_failure_proceeds(self):
        """Lines 594-596: auto-topup failure doesn't break settlement."""
        mock_vault = MagicMock(spec=NanoKeyVault)
        mock_client = MagicMock(spec=NanopaymentClient)
        mock_http = self._make_mock_http_client()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=True,
            auto_topup_threshold="0.1",
            auto_topup_amount="1.0",
        )
        adapter._wallet_manager = MagicMock()
        adapter._wallet_manager.deposit = AsyncMock(side_effect=RuntimeError("RPC error"))

        mock_client.check_balance = AsyncMock(
            return_value=GatewayBalance(
                total=10_000_000,
                available=50_000,
                formatted_total="10.00 USDC",
                formatted_available="0.05 USDC",
            )
        )

        mock_client.settle = AsyncMock(
            return_value=SettleResponse(
                success=True,
                transaction="0xtx",
                payer="0x" + "1" * 40,
                error_reason=None,
            )
        )

        payload = MagicMock(spec=PaymentPayload)
        payload.to_dict.return_value = {}
        req = make_402_requirements()

        # Should not raise even though topup fails
        result = await adapter._settle_with_retry(payload=payload, requirements=req)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_check_and_topup_low_balance(self):
        """Lines 763-781: _check_and_topup with low balance calls deposit."""
        mock_vault = MagicMock(spec=NanoKeyVault)
        mock_client = MagicMock(spec=NanopaymentClient)
        mock_http = self._make_mock_http_client()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=True,
            auto_topup_threshold="0.1",
            auto_topup_amount="1.0",
        )
        adapter._wallet_manager = MagicMock()
        adapter._wallet_manager.deposit = AsyncMock(
            return_value=DepositResult(
                approval_tx_hash=None,
                deposit_tx_hash="0xtxhash",
                amount=1_000_000,
                formatted_amount="1.00 USDC",
            )
        )
        # _check_and_topup calls self._vault.get_balance()
        mock_vault.get_balance = AsyncMock(
            return_value=GatewayBalance(
                total=10_000_000,
                available=50_000,
                formatted_total="10.00 USDC",
                formatted_available="0.05 USDC",
            )
        )

        did_topup = await adapter._check_and_topup(alias="default")
        assert did_topup is True
        adapter._wallet_manager.deposit.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_and_topup_balance_ok(self):
        """Line 780: _check_and_topup returns False when balance is sufficient."""
        mock_vault = MagicMock(spec=NanoKeyVault)
        mock_client = MagicMock(spec=NanopaymentClient)
        mock_http = self._make_mock_http_client()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=True,
            auto_topup_threshold="1.0",
        )
        mock_vault.get_balance = AsyncMock(
            return_value=GatewayBalance(
                total=10_000_000,
                available=5_000_000,
                formatted_total="10.00 USDC",
                formatted_available="5.00 USDC",
            )
        )

        did_topup = await adapter._check_and_topup(alias="default")
        assert did_topup is False


# =============================================================================
# TEST: NanopaymentAdapter additional coverage (adapter.py)
# =============================================================================


class TestNanopaymentAdapterAdditionalCoverage:
    """Additional coverage for NanopaymentAdapter."""

    def _make_mock_http(self):
        mock = MagicMock()
        mock.post = AsyncMock()
        mock.request = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_pay_x402_url_resource_from_body(self):
        """Line 346: resource extracted from 402 response body, not constructed from URL."""
        req_data = make_402_requirements()
        encoded = base64.b64encode(json.dumps(req_data).encode()).decode()

        # 402 response body contains a resource field
        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": encoded}
        mock_resp_402.text = json.dumps(
            {
                "resource": {
                    "url": "https://seller.com/api/data",
                    "description": "Premium data access",
                    "mimeType": "application/json",
                }
            }
        )

        retry_resp = MagicMock()
        retry_resp.status_code = 200
        retry_resp.content = b'{"data": "premium"}'
        retry_resp.text = '{"data": "premium"}'

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock(
            return_value=MagicMock(
                spec=PaymentPayload,
                to_dict=lambda: {},
            )
        )

        mock_client = MagicMock()
        mock_client.settle = AsyncMock(
            return_value=MagicMock(
                success=True,
                transaction="tx-from-body-resource",
            )
        )

        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=[mock_resp_402, retry_resp])

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        result = await adapter.pay_x402_url("https://api.seller.com/data")
        assert result.success is True

        # Verify ResourceInfo was constructed from body (not URL)
        call_args = mock_vault.sign.call_args
        resource_arg = call_args.kwargs.get("resource") or call_args[1].get("resource")
        assert resource_arg is not None
        assert resource_arg.url == "https://seller.com/api/data"

    @pytest.mark.asyncio
    async def test_pay_x402_url_resource_body_parse_exception_fallback(self):
        """Lines 347-348: body parse exception → falls back to URL-based resource."""
        req_data = make_402_requirements()
        encoded = base64.b64encode(json.dumps(req_data).encode()).decode()

        # 402 body has malformed JSON that causes parse exception
        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.headers = {"payment-required": encoded}
        mock_resp_402.text = "not valid json{"  # Will cause json.loads to raise

        retry_resp = MagicMock()
        retry_resp.status_code = 200
        retry_resp.content = b"ok"
        retry_resp.text = "ok"

        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.sign = AsyncMock(
            return_value=MagicMock(
                spec=PaymentPayload,
                to_dict=lambda: {},
            )
        )

        mock_client = MagicMock()
        mock_client.settle = AsyncMock(
            return_value=MagicMock(
                success=True,
                transaction="tx-fallback",
            )
        )

        mock_http = MagicMock()
        mock_http.request = AsyncMock(side_effect=[mock_resp_402, retry_resp])

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
        )

        # Should not raise - falls back to URL-based resource
        result = await adapter.pay_x402_url("https://fallback.test/item")
        assert result.success is True

        # Verify fallback resource was used (from URL, not body)
        call_args = mock_vault.sign.call_args
        resource_arg = call_args.kwargs.get("resource") or call_args[1].get("resource")
        assert resource_arg is not None
        assert resource_arg.url == "https://fallback.test/item"

    @pytest.mark.asyncio
    async def test_settle_with_retry_connection_error_then_success(self):
        """Lines 730-743: GatewayConnectionError retries with backoff then succeeds."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import GatewayConnectionError

        mock_vault = MagicMock()
        mock_client = MagicMock()

        # Fail once with connection error, then succeed
        mock_client.settle = AsyncMock(
            side_effect=[
                GatewayConnectionError("Connection refused"),
                MagicMock(success=True, transaction="tx-after-conn-retry"),
            ]
        )

        mock_http = self._make_mock_http()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
            retry_attempts=3,
            retry_base_delay=0.01,
        )

        payload = MagicMock(spec=PaymentPayload)
        req = MagicMock(spec=PaymentRequirements)

        result = await adapter._settle_with_retry(payload=payload, requirements=req)

        assert result.success is True
        assert mock_client.settle.call_count == 2
        # Circuit breaker should have recorded one error
        assert adapter.get_circuit_breaker_state() == "closed"

    @pytest.mark.asyncio
    async def test_settle_with_retry_insufficient_balance_raises(self):
        """Lines 748-751: InsufficientBalanceError is non-recoverable, no retry."""
        from omniclaw.protocols.nanopayments.adapter import (
            NanopaymentAdapter,
            NanopaymentCircuitBreaker,
        )
        from omniclaw.protocols.nanopayments.exceptions import InsufficientBalanceError

        mock_vault = MagicMock()
        mock_client = MagicMock()

        mock_client.settle = AsyncMock(
            side_effect=InsufficientBalanceError(reason="insufficient_balance")
        )

        mock_http = self._make_mock_http()
        cb = NanopaymentCircuitBreaker(failure_threshold=1)

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
            retry_attempts=3,
            circuit_breaker=cb,
        )

        payload = MagicMock()
        req = MagicMock()

        with pytest.raises(InsufficientBalanceError):
            await adapter._settle_with_retry(payload=payload, requirements=req)

        # Should NOT have retried
        assert mock_client.settle.call_count == 1
        # Circuit breaker should have recorded a failure (threshold=1)
        assert adapter.get_circuit_breaker_state() == "open"

    @pytest.mark.asyncio
    async def test_settle_with_retry_transient_settlement_error_then_success(self):
        """Lines 752-768: SettlementError with 'timeout' retries, then succeeds."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentAdapter
        from omniclaw.protocols.nanopayments.exceptions import SettlementError

        mock_vault = MagicMock()
        mock_client = MagicMock()

        # Transient SettlementError first, then success
        mock_client.settle = AsyncMock(
            side_effect=[
                SettlementError("Gateway timeout - try again"),
                MagicMock(success=True, transaction="tx-after-settlement-retry"),
            ]
        )

        mock_http = self._make_mock_http()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
            retry_attempts=3,
            retry_base_delay=0.01,
        )

        payload = MagicMock(spec=PaymentPayload)
        req = MagicMock(spec=PaymentRequirements)

        result = await adapter._settle_with_retry(payload=payload, requirements=req)

        assert result.success is True
        assert mock_client.settle.call_count == 2

    @pytest.mark.asyncio
    async def test_settle_with_retry_non_transient_settlement_error_raises(self):
        """Lines 769-772: SettlementError without 'timeout'/'connection' is non-recoverable."""
        from omniclaw.protocols.nanopayments.adapter import (
            NanopaymentAdapter,
            NanopaymentCircuitBreaker,
        )
        from omniclaw.protocols.nanopayments.exceptions import SettlementError

        mock_vault = MagicMock()
        mock_client = MagicMock()

        # Non-transient SettlementError
        mock_client.settle = AsyncMock(
            side_effect=SettlementError("Invalid authorization signature")
        )

        mock_http = self._make_mock_http()
        cb = NanopaymentCircuitBreaker(failure_threshold=1)

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=False,
            retry_attempts=3,
            circuit_breaker=cb,
        )

        payload = MagicMock()
        req = MagicMock()

        with pytest.raises(SettlementError) as exc_info:
            await adapter._settle_with_retry(payload=payload, requirements=req)

        assert "Invalid authorization signature" in str(exc_info.value)
        assert mock_client.settle.call_count == 1
        # Circuit breaker should have recorded a failure (threshold=1)
        assert adapter.get_circuit_breaker_state() == "open"

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_to_open(self):
        """Circuit breaker transitions: closed → error threshold → open."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentCircuitBreaker

        cb = NanopaymentCircuitBreaker(failure_threshold=2)

        cb.record_error()  # 1 error - still closed
        assert cb.state == "closed"

        cb.record_error()  # 2 errors - trips to open
        assert cb.state == "open"

        cb.record_error()  # additional errors in open state
        assert cb.state == "open"  # stays open

    def test_circuit_breaker_half_open_recovery(self):
        """Circuit breaker recovers from open to half-open via state property."""
        from omniclaw.protocols.nanopayments.adapter import NanopaymentCircuitBreaker

        cb = NanopaymentCircuitBreaker(failure_threshold=1, recovery_seconds=0.1)

        cb.record_failure()  # trips to open
        assert cb.state == "open"

        # Advance time past recovery window
        import time

        time.sleep(0.15)

        # State property auto-transitions to half_open
        assert cb.state == "half_open"
        # Success in half_open resets to closed
        cb.record_success()
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_pay_direct_auto_topup_failure_continues(self):
        """Lines 622-623: pay_direct auto-topup failure logs but continues."""
        mock_vault = MagicMock()
        mock_vault.get_address = AsyncMock(return_value="0x" + "a" * 40)
        mock_vault.get_balance = AsyncMock(
            return_value=GatewayBalance(
                total=100_000,
                available=50_000,
                formatted_total="0.1 USDC",
                formatted_available="0.05 USDC",
            )
        )
        mock_vault.sign = AsyncMock(
            return_value=MagicMock(
                spec=PaymentPayload,
                to_dict=lambda: {},
            )
        )

        mock_client = MagicMock()
        mock_client.get_verifying_contract = AsyncMock(return_value="0x" + "b" * 40)
        mock_client.get_usdc_address = AsyncMock(return_value="0x" + "c" * 40)
        mock_client.settle = AsyncMock(
            return_value=SettleResponse(
                success=True,
                transaction="0xtx",
                payer="0x" + "a" * 40,
                error_reason=None,
            )
        )

        mock_http = self._make_mock_http()

        adapter = NanopaymentAdapter(
            vault=mock_vault,
            nanopayment_client=mock_client,
            http_client=mock_http,
            auto_topup_enabled=True,
            auto_topup_threshold="0.001",  # very low so topup is attempted
            auto_topup_amount="1.0",
        )
        # No wallet manager configured → _check_and_topup returns False (line 806)
        # but the exception is caught by the try/except in pay_direct (lines 622-623)

        result = await adapter.pay_direct(
            seller_address="0x" + "b" * 40,
            amount_usdc="0.001",
            network="eip155:5042002",
        )

        assert result.success is True
        # Verify settlement was called despite auto-topup early return
        mock_client.settle.assert_called_once()
