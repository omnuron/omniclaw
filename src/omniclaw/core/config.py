"""
Configuration management for OmniClaw SDK.

Handles loading configuration from environment variables and validation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from omniclaw.core.types import Network


def _get_env_var(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Get environment variable with optional default."""
    value = os.environ.get(name, default)
    if required and not value:
        raise ValueError(f"Required environment variable {name} is not set")
    return value


@dataclass(frozen=True)
class Config:
    """SDK configuration."""

    circle_api_key: str
    entity_secret: str
    network: Network = Network.ETH
    storage_backend: str = "memory"
    redis_url: str | None = None
    log_level: str = "INFO"
    # Timeout configuration
    http_timeout: float = 30.0  # HTTP client timeout in seconds
    cctp_timeout: float = 300.0  # CCTP transfer timeout (5 minutes)
    # Rate limiting
    enable_rate_limiting: bool = True  # Enable Circle API rate limiting
    max_api_calls_per_second: int = 30  # Conservative limit (Circle allows 35) endpoints
    circle_api_base_url: str = "https://api.circle.com/v1/w3s"

    # x402 facilitator (thirdweb)
    x402_facilitator_url: str = "https://x402.org/facilitator"

    # Gateway API for gasless transfers
    gateway_api_url: str = "https://gateway-api-testnet.circle.com/v1"

    # Timeouts (seconds)
    request_timeout: float = 30.0
    transaction_poll_interval: float = 2.0
    transaction_poll_timeout: float = 120.0

    # Environment & Logging
    # log_level is already defined above
    env: str = "development"
    
    # Wallet defaults
    default_wallet_id: str | None = None

    def __post_init__(self) -> None:
        if not self.circle_api_key:
            raise ValueError("circle_api_key is required")
        if not self.entity_secret:
            raise ValueError("entity_secret is required")

    @classmethod
    def from_env(cls, **overrides: Any) -> Config:
        """Load configuration from environment variables."""
        circle_api_key = overrides.get("circle_api_key") or _get_env_var(
            "CIRCLE_API_KEY", required=True
        )
        entity_secret = overrides.get("entity_secret") or _get_env_var(
            "ENTITY_SECRET", required=True
        )

        # Parse network from environment
        network_str = overrides.get("network") or _get_env_var(
            "OMNICLAW_NETWORK", default="ARC-TESTNET"
        )
        network = Network.from_string(network_str) if isinstance(network_str, str) else network_str

        default_wallet_id = overrides.get("default_wallet_id") or _get_env_var(
            "OMNICLAW_DEFAULT_WALLET"
        )

        log_level = overrides.get("log_level") or _get_env_var(
            "OMNICLAW_LOG_LEVEL", default="INFO"
        )

        env = overrides.get("env") or _get_env_var("OMNICLAW_ENV", default="development")

        return cls(
            circle_api_key=circle_api_key,  # type: ignore
            entity_secret=entity_secret,  # type: ignore
            network=network,
            default_wallet_id=default_wallet_id,
            circle_api_base_url=overrides.get("circle_api_base_url", cls.circle_api_base_url),
            x402_facilitator_url=overrides.get("x402_facilitator_url", cls.x402_facilitator_url),
            gateway_api_url=overrides.get("gateway_api_url", cls.gateway_api_url),
            request_timeout=overrides.get("request_timeout", cls.request_timeout),
            transaction_poll_interval=overrides.get(
                "transaction_poll_interval", cls.transaction_poll_interval
            ),
            transaction_poll_timeout=overrides.get(
                "transaction_poll_timeout", cls.transaction_poll_timeout
            ),
            log_level=log_level,  # type: ignore
            env=env,  # type: ignore
        )

    def with_updates(self, **updates: Any) -> Config:
        """Create a new Config with updated values."""
        current = {
            "circle_api_key": self.circle_api_key,
            "entity_secret": self.entity_secret,
            "network": self.network,
            "default_wallet_id": self.default_wallet_id,
            "circle_api_base_url": self.circle_api_base_url,
            "x402_facilitator_url": self.x402_facilitator_url,
            "gateway_api_url": self.gateway_api_url,
            "request_timeout": self.request_timeout,
            "transaction_poll_interval": self.transaction_poll_interval,
            "transaction_poll_timeout": self.transaction_poll_timeout,
            "log_level": self.log_level,
            "env": self.env,
        }
        current.update(updates)
        return Config(**current)

    def masked_api_key(self) -> str:
        """Return API key with most characters masked for safe logging."""
        if len(self.circle_api_key) <= 8:
            return "****"
        return self.circle_api_key[:4] + "..." + self.circle_api_key[-4:]
