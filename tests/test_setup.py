"""Unit tests for setup module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from omniagentpay.onboarding import (
    generate_entity_secret,
    create_env_file,
    verify_setup,
    SetupError,
)


class TestGenerateEntitySecret:
    """Tests for generate_entity_secret()."""
    
    def test_generates_64_char_hex(self) -> None:
        """Test secret is 64 hex characters."""
        secret = generate_entity_secret()
        
        assert len(secret) == 64
        # Verify it's valid hex
        int(secret, 16)
    
    def test_generates_unique_secrets(self) -> None:
        """Test each call generates a unique secret."""
        secrets = [generate_entity_secret() for _ in range(10)]
        
        assert len(set(secrets)) == 10  # All unique


class TestCreateEnvFile:
    """Tests for create_env_file()."""
    
    def test_creates_env_file(self) -> None:
        """Test .env file creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            
            result = create_env_file(
                api_key="TEST_API_KEY",
                entity_secret="a" * 64,
                env_path=env_path,
            )
            
            assert result.exists()
            content = result.read_text()
            assert "CIRCLE_API_KEY=TEST_API_KEY" in content
            assert f"ENTITY_SECRET={'a' * 64}" in content
    
    def test_raises_if_exists_no_overwrite(self) -> None:
        """Test error if file exists and overwrite=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("existing")
            
            with pytest.raises(SetupError, match="already exists"):
                create_env_file(
                    api_key="key",
                    entity_secret="a" * 64,
                    env_path=env_path,
                    overwrite=False,
                )
    
    def test_overwrites_if_flag_set(self) -> None:
        """Test overwrite works when flag is set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("old content")
            
            result = create_env_file(
                api_key="NEW_KEY",
                entity_secret="b" * 64,
                env_path=env_path,
                overwrite=True,
            )
            
            content = result.read_text()
            assert "CIRCLE_API_KEY=NEW_KEY" in content
    
    def test_includes_network_config(self) -> None:
        """Test network is included in .env."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            
            create_env_file(
                api_key="key",
                entity_secret="a" * 64,
                env_path=env_path,
                network="ARC",
            )
            
            content = env_path.read_text()
            assert "OMNIAGENTPAY_NETWORK=ARC" in content


class TestVerifySetup:
    """Tests for verify_setup()."""
    
    def test_returns_status_dict(self) -> None:
        """Test verify_setup returns expected keys."""
        result = verify_setup()
        
        assert "circle_sdk_installed" in result
        assert "api_key_set" in result
        assert "entity_secret_set" in result
        assert "ready" in result
    
    def test_detects_missing_env_vars(self) -> None:
        """Test detection when env vars not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = verify_setup()
            
            assert result["api_key_set"] is False
            assert result["entity_secret_set"] is False
            assert result["ready"] is False
    
    def test_detects_set_env_vars(self) -> None:
        """Test detection when env vars are set."""
        env = {
            "CIRCLE_API_KEY": "test_key",
            "ENTITY_SECRET": "test_secret",
        }
        
        with patch.dict(os.environ, env):
            result = verify_setup()
            
            assert result["api_key_set"] is True
            assert result["entity_secret_set"] is True
