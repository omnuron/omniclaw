"""Unit tests for config module."""

import os
from unittest.mock import patch

import pytest

from omniclaw.core.config import Config
from omniclaw.core.types import Network


class TestConfig:
    """Tests for Config class."""

    def test_create_config_directly(self) -> None:
        """Test creating config with direct values."""
        config = Config(
            circle_api_key="test_api_key_123",
            entity_secret="test_entity_secret_456",
        )

        assert config.circle_api_key == "test_api_key_123"
        assert config.entity_secret == "test_entity_secret_456"
        assert config.network == Network.ETH  # default
        assert config.payment_strict_settlement is False

    def test_create_config_with_all_options(self) -> None:
        """Test creating config with all options."""
        config = Config(
            circle_api_key="test_key",
            entity_secret="test_secret",
            network=Network.ETH,
            default_wallet_id="wallet-123",
            request_timeout=60.0,
        )

        assert config.network == Network.ETH
        assert config.default_wallet_id == "wallet-123"
        assert config.request_timeout == 60.0

    def test_config_is_immutable(self) -> None:
        """Test that config is frozen (immutable)."""
        config = Config(
            circle_api_key="test_key",
            entity_secret="test_secret",
        )

        with pytest.raises(AttributeError):
            config.circle_api_key = "new_key"  # type: ignore

    def test_missing_api_key_raises(self) -> None:
        """Test missing API key raises ValueError."""
        with pytest.raises(ValueError, match="CIRCLE_API_KEY"):
            Config(
                circle_api_key="",
                entity_secret="test_secret",
                buyer_mode="circle",
                enable_circle_transfer=True,
            )

    def test_missing_entity_secret_warns(self) -> None:
        """Test missing entity secret logs warning (no longer required)."""
        # entity_secret is now optional — Config should NOT raise
        config = Config(
            circle_api_key="test_key",
            entity_secret="",
            buyer_mode="x402",
            enable_circle_transfer=False,
            enable_gateway=False,
            enable_x402_exact=True,
            nanopayments_private_key="0x" + "1" * 64,
        )
        assert config.entity_secret == ""

    def test_from_env(self) -> None:
        """Test loading config from environment variables."""
        env_vars = {
            "CIRCLE_API_KEY": "env_api_key",
            "ENTITY_SECRET": "env_entity_secret",
            "OMNICLAW_NETWORK": "ARC-TESTNET",
            "OMNICLAW_DEFAULT_WALLET": "wallet-xyz",
            "OMNICLAW_STRICT_SETTLEMENT": "true",
            "OMNICLAW_AUTO_RECONCILE_PENDING_SETTLEMENTS": "true",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = Config.from_env()

        assert config.circle_api_key == "env_api_key"
        assert config.entity_secret == "env_entity_secret"
        assert config.network == Network.ARC_TESTNET
        assert config.default_wallet_id == "wallet-xyz"
        assert config.payment_strict_settlement is True
        assert config.auto_reconcile_pending_settlements is True

    def test_strict_settlement_defaults_to_false_for_non_production(self) -> None:
        env_vars = {
            "CIRCLE_API_KEY": "env_api_key",
            "ENTITY_SECRET": "env_entity_secret",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.from_env()

        assert config.payment_strict_settlement is False

    def test_from_env_missing_api_key_raises(self) -> None:
        """Test from_env raises when API key not set."""
        env_vars = {
            "ENTITY_SECRET": "test_secret",
        }

        with (
            patch.dict(os.environ, env_vars, clear=True),
            pytest.raises(ValueError, match="CIRCLE_API_KEY"),
        ):
            Config.from_env()

    def test_from_env_missing_entity_secret_warns(self) -> None:
        """x402 mode with Gateway support needs Circle API, not Circle entity secret."""
        env_vars = {
            "CIRCLE_API_KEY": "test_key",
            "OMNICLAW_BUYER_MODE": "x402",
            "OMNICLAW_PRIVATE_KEY": "0x" + "1" * 64,
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.from_env()
        assert config.entity_secret == ""
        assert config.circle_api_key == "test_key"
        assert config.enable_circle_transfer is False
        assert config.enable_gateway is True
        assert config.enable_x402 is True

    def test_x402_mode_does_not_require_circle_credentials(self) -> None:
        """x402 exact-only mode uses the EOA signer and no Circle wallet secret."""
        env_vars = {
            "OMNICLAW_BUYER_MODE": "x402",
            "OMNICLAW_PRIVATE_KEY": "0x" + "1" * 64,
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.from_env()

        assert config.circle_api_key == ""
        assert config.entity_secret == ""
        assert config.enable_circle_transfer is False
        assert config.enable_gateway is False
        assert config.enable_x402_exact is True

    def test_gateway_mode_does_not_require_entity_secret(self) -> None:
        """Legacy gateway mode remains accepted for existing deployments."""
        env_vars = {
            "OMNICLAW_BUYER_MODE": "gateway",
            "CIRCLE_API_KEY": "test_key",
            "OMNICLAW_PRIVATE_KEY": "0x" + "1" * 64,
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.from_env()

        assert config.entity_secret == ""
        assert config.enable_circle_transfer is False
        assert config.enable_gateway is True
        assert config.enable_x402_exact is True
        assert config.enable_x402 is True

    def test_x402_public_flag_disables_internal_x402_paths(self) -> None:
        env_vars = {
            "OMNICLAW_BUYER_MODE": "hybrid",
            "CIRCLE_API_KEY": "test_key",
            "ENTITY_SECRET": "test_secret",
            "OMNICLAW_ENABLE_X402": "false",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.from_env()

        assert config.enable_circle_transfer is True
        assert config.enable_gateway is False
        assert config.enable_x402_exact is False
        assert config.enable_x402 is False

    def test_x402_public_flag_enables_standard_x402_without_circle_credentials(self) -> None:
        env_vars = {
            "OMNICLAW_BUYER_MODE": "circle",
            "OMNICLAW_ENABLE_CIRCLE_TRANSFER": "false",
            "OMNICLAW_ENABLE_X402": "true",
            "OMNICLAW_PRIVATE_KEY": "0x" + "1" * 64,
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.from_env()

        assert config.enable_circle_transfer is False
        assert config.enable_gateway is False
        assert config.enable_x402_exact is True
        assert config.enable_x402 is True

    def test_x402_public_flag_enables_gateway_only_with_circle_api_key(self) -> None:
        env_vars = {
            "OMNICLAW_BUYER_MODE": "circle",
            "OMNICLAW_ENABLE_CIRCLE_TRANSFER": "false",
            "OMNICLAW_ENABLE_X402": "true",
            "CIRCLE_API_KEY": "test_key",
            "OMNICLAW_PRIVATE_KEY": "0x" + "1" * 64,
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.from_env()

        assert config.enable_circle_transfer is False
        assert config.enable_gateway is True
        assert config.enable_x402_exact is True
        assert config.enable_x402 is True

    def test_string_override_false_disables_public_x402(self) -> None:
        config = Config.from_env(
            buyer_mode="hybrid ",
            circle_api_key="test_key",
            entity_secret="test_secret",
            nanopayments_private_key="0x" + "1" * 64,
            enable_x402="false",
        )

        assert config.buyer_mode == "hybrid"
        assert config.enable_circle_transfer is True
        assert config.enable_gateway is False
        assert config.enable_x402_exact is False
        assert config.enable_x402 is False

    def test_hybrid_mode_requires_entity_secret_and_private_key(self) -> None:
        """Hybrid buyer mode requires both Circle transfer and EOA credentials."""
        with (
            patch.dict(
                os.environ,
                {
                    "OMNICLAW_BUYER_MODE": "hybrid",
                    "CIRCLE_API_KEY": "test_key",
                },
                clear=True,
            ),
            pytest.raises(ValueError, match="ENTITY_SECRET"),
        ):
            Config.from_env()

        with (
            patch.dict(
                os.environ,
                {
                    "OMNICLAW_BUYER_MODE": "hybrid",
                    "CIRCLE_API_KEY": "test_key",
                    "ENTITY_SECRET": "test_secret",
                },
                clear=True,
            ),
            pytest.raises(ValueError, match="OMNICLAW_PRIVATE_KEY"),
        ):
            Config.from_env()

    def test_from_env_with_overrides(self) -> None:
        """Test from_env with override values."""
        env_vars = {
            "CIRCLE_API_KEY": "env_key",
            "ENTITY_SECRET": "env_secret",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = Config.from_env(
                circle_api_key="override_key",
                network=Network.ETH,
            )

        assert config.circle_api_key == "override_key"
        assert config.entity_secret == "env_secret"
        assert config.network == Network.ETH

    def test_with_updates(self) -> None:
        """Test creating new config with updates."""
        original = Config(
            circle_api_key="test_key",
            entity_secret="test_secret",
            network=Network.ARC_TESTNET,
        )

        updated = original.with_updates(
            network=Network.ETH,
            default_wallet_id="new-wallet",
        )

        # Original unchanged
        assert original.network == Network.ARC_TESTNET
        assert original.default_wallet_id is None

        # Updated has new values
        assert updated.network == Network.ETH
        assert updated.default_wallet_id == "new-wallet"
        assert updated.circle_api_key == "test_key"  # preserved

    def test_masked_api_key(self) -> None:
        """Test API key masking for safe logging."""
        config = Config(
            circle_api_key="sk_test_1234567890abcdef",
            entity_secret="test_secret",
        )

        masked = config.masked_api_key()

        assert "sk_t" in masked  # first 4 chars
        assert "cdef" in masked  # last 4 chars
        assert "1234567890ab" not in masked  # middle hidden
        assert "..." in masked

    def test_masked_api_key_short(self) -> None:
        """Test masking short API key."""
        config = Config(
            circle_api_key="short",
            entity_secret="test_secret",
        )

        masked = config.masked_api_key()

        assert masked == "****"

    def test_default_urls(self) -> None:
        """Test default API URLs are set."""
        config = Config(
            circle_api_key="test_key",
            entity_secret="test_secret",
        )

        assert "circle.com" in config.circle_api_base_url
        assert config.x402_facilitator_url == "https://x402.org/facilitator"

    def test_default_timeouts(self) -> None:
        """Test default timeout values."""
        config = Config(
            circle_api_key="test_key",
            entity_secret="test_secret",
        )

        assert config.request_timeout == 60.0
        assert config.transaction_poll_interval == 2.0
        assert config.transaction_poll_timeout == 120.0
