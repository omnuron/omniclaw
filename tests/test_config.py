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
        with pytest.raises(ValueError, match="circle_api_key is required"):
            Config(
                circle_api_key="",
                entity_secret="test_secret",
            )

    def test_missing_entity_secret_raises(self) -> None:
        """Test missing entity secret raises ValueError."""
        with pytest.raises(ValueError, match="entity_secret is required"):
            Config(
                circle_api_key="test_key",
                entity_secret="",
            )

    def test_from_env(self) -> None:
        """Test loading config from environment variables."""
        env_vars = {
            "CIRCLE_API_KEY": "env_api_key",
            "ENTITY_SECRET": "env_entity_secret",
            "OMNICLAW_NETWORK": "ARC-TESTNET",
            "OMNICLAW_DEFAULT_WALLET": "wallet-xyz",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = Config.from_env()

        assert config.circle_api_key == "env_api_key"
        assert config.entity_secret == "env_entity_secret"
        assert config.network == Network.ARC_TESTNET
        assert config.default_wallet_id == "wallet-xyz"

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

    def test_from_env_missing_entity_secret_raises(self) -> None:
        """Test from_env raises when entity secret not set."""
        env_vars = {
            "CIRCLE_API_KEY": "test_key",
        }

        with (
            patch.dict(os.environ, env_vars, clear=True),
            pytest.raises(ValueError, match="ENTITY_SECRET"),
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

        assert config.request_timeout == 30.0
        assert config.transaction_poll_interval == 2.0
        assert config.transaction_poll_timeout == 120.0
