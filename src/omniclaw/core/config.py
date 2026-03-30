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
    rpc_url: str | None = None

    # x402 facilitator (thirdweb)
    x402_facilitator_url: str = "https://x402.org/facilitator"

    # Gateway API for gasless transfers
    gateway_api_url: str = "https://gateway-api-testnet.circle.com/v1"

    # Timeouts (seconds)
    request_timeout: float = 60.0
    transaction_poll_interval: float = 2.0
    transaction_poll_timeout: float = 120.0

    # Environment & Logging
    # log_level is already defined below
    env: str = "development"

    # Wallet defaults
    default_wallet_id: str | None = None

    # Default Guard Configuration
    daily_budget: str | None = None
    hourly_budget: str | None = None
    tx_limit: str | None = None
    rate_limit_per_min: int | None = None
    whitelisted_recipients: list[str] | None = None
    confirm_always: bool = False
    confirm_threshold: str | None = None

    # =====================================================================
    # Nanopayments (EIP-3009 Circle Gateway batched settlement)
    # =====================================================================
    nanopayments_enabled: bool = True
    """Enable nanopayments (EIP-3009 batched USDC micro-payments)."""

    nanopayments_environment: str = "testnet"
    """Circle Gateway environment: 'testnet' or 'mainnet'."""

    nanopayments_auto_topup: bool = True
    """Automatically deposit to Gateway when balance is low."""

    nanopayments_topup_threshold: str = "1.00"
    """Auto-topup threshold in USDC decimal (e.g. '1.00')."""

    nanopayments_topup_amount: str = "10.00"
    """Amount deposited when auto-topup triggers."""

    nanopayments_micro_threshold: str = "1.00"
    """Amount below which nanopayments are used instead of standard transfer."""

    nanopayments_default_key_alias: str | None = None
    """Default NanoKeyVault key alias for agents."""

    nanopayments_default_network: str | None = None
    """Default CAIP-2 network for nanopayments (e.g., 'eip155:1' for mainnet, 'eip155:11155111' for Sepolia)."""

    payment_strict_settlement: bool = True
    """If true, success=True is emitted only for irreversible settlement."""

    auto_reconcile_pending_settlements: bool = False
    """If true, opportunistically reconcile pending settlements during payment operations."""

    def __post_init__(self) -> None:
        if not self.circle_api_key:
            raise ValueError("circle_api_key is required")
        if not self.entity_secret:
            raise ValueError("entity_secret is required")

    @classmethod
    def from_env(cls, **overrides: Any) -> Config:
        """Load configuration from environment variables."""

        def override_or_env(name: str, env_name: str, default: Any = None) -> Any:
            if name in overrides:
                return overrides[name]
            return _get_env_var(env_name, default=default)

        circle_api_key = override_or_env("circle_api_key", "CIRCLE_API_KEY") or _get_env_var(
            "CIRCLE_API_KEY", required=True
        )
        entity_secret = override_or_env("entity_secret", "ENTITY_SECRET") or _get_env_var(
            "ENTITY_SECRET", required=True
        )

        # Parse network from environment
        network_str = override_or_env("network", "OMNICLAW_NETWORK", "ARC-TESTNET")
        network = Network.from_string(network_str) if isinstance(network_str, str) else network_str

        default_wallet_id = override_or_env("default_wallet_id", "OMNICLAW_DEFAULT_WALLET")

        log_level = override_or_env("log_level", "OMNICLAW_LOG_LEVEL", "INFO")

        env = override_or_env("env", "OMNICLAW_ENV", "development")
        rpc_url = override_or_env("rpc_url", "OMNICLAW_RPC_URL")

        # Auto-detect nanopayments environment from OMNICLAW_ENV
        # production/prod/mainnet → mainnet, otherwise testnet
        is_production = env in {"prod", "production", "mainnet"}
        nanopayments_env = "mainnet" if is_production else "testnet"

        # Parse guard limits
        daily_budget = override_or_env("daily_budget", "OMNICLAW_DAILY_BUDGET")
        hourly_budget = override_or_env("hourly_budget", "OMNICLAW_HOURLY_BUDGET")
        tx_limit = override_or_env("tx_limit", "OMNICLAW_TX_LIMIT")
        rate_limit_env = _get_env_var("OMNICLAW_RATE_LIMIT_PER_MIN")
        rate_limit_per_min = (
            overrides["rate_limit_per_min"]
            if "rate_limit_per_min" in overrides
            else (int(rate_limit_env) if rate_limit_env else None)
        )

        whitelist_env = _get_env_var("OMNICLAW_WHITELISTED_RECIPIENTS")
        whitelisted_recipients = (
            overrides["whitelisted_recipients"]
            if "whitelisted_recipients" in overrides
            else (whitelist_env.split(",") if whitelist_env else None)
        )

        confirm_always = (
            overrides["confirm_always"]
            if "confirm_always" in overrides
            else (_get_env_var("OMNICLAW_CONFIRM_ALWAYS", "false").lower() == "true")
        )
        confirm_threshold = override_or_env("confirm_threshold", "OMNICLAW_CONFIRM_THRESHOLD")

        # Nanopayments configuration (always enabled, env auto-detected from OMNICLAW_ENV)
        nanopayments_enabled = True
        nanopayments_auto_topup = (
            overrides.get("nanopayments_auto_topup")
            if "nanopayments_auto_topup" in overrides
            else (_get_env_var("OMNICLAW_NANOPAYMENTS_AUTO_TOPUP", "true").lower() == "true")
        )
        nanopayments_topup_threshold = override_or_env(
            "nanopayments_topup_threshold", "OMNICLAW_NANOPAYMENTS_TOPUP_THRESHOLD", "1.00"
        )
        nanopayments_topup_amount = override_or_env(
            "nanopayments_topup_amount", "OMNICLAW_NANOPAYMENTS_TOPUP_AMOUNT", "10.00"
        )
        nanopayments_micro_threshold = override_or_env(
            "nanopayments_micro_threshold", "OMNICLAW_NANOPAYMENTS_MICRO_THRESHOLD", "1.00"
        )
        nanopayments_default_key_alias = override_or_env(
            "nanopayments_default_key_alias", "OMNICLAW_NANOPAYMENTS_DEFAULT_KEY"
        )
        nanopayments_default_network = override_or_env(
            "nanopayments_default_network", "OMNICLAW_NANOPAYMENTS_DEFAULT_NETWORK"
        )
        payment_strict_settlement = (
            overrides.get("payment_strict_settlement")
            if "payment_strict_settlement" in overrides
            else (_get_env_var("OMNICLAW_STRICT_SETTLEMENT", "true").lower() == "true")
        )
        auto_reconcile_pending_settlements = (
            overrides.get("auto_reconcile_pending_settlements")
            if "auto_reconcile_pending_settlements" in overrides
            else (
                _get_env_var("OMNICLAW_AUTO_RECONCILE_PENDING_SETTLEMENTS", "false").lower()
                == "true"
            )
        )

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
            rpc_url=rpc_url,
            daily_budget=daily_budget,
            hourly_budget=hourly_budget,
            tx_limit=tx_limit,
            rate_limit_per_min=rate_limit_per_min,
            whitelisted_recipients=whitelisted_recipients,
            confirm_always=confirm_always,
            confirm_threshold=confirm_threshold,
            nanopayments_enabled=nanopayments_enabled,
            nanopayments_environment=nanopayments_env,
            nanopayments_auto_topup=nanopayments_auto_topup,
            nanopayments_topup_threshold=nanopayments_topup_threshold,
            nanopayments_topup_amount=nanopayments_topup_amount,
            nanopayments_micro_threshold=nanopayments_micro_threshold,
            nanopayments_default_key_alias=nanopayments_default_key_alias,
            nanopayments_default_network=nanopayments_default_network,
            payment_strict_settlement=payment_strict_settlement,
            auto_reconcile_pending_settlements=auto_reconcile_pending_settlements,
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
            "rpc_url": self.rpc_url,
            "daily_budget": self.daily_budget,
            "hourly_budget": self.hourly_budget,
            "tx_limit": self.tx_limit,
            "rate_limit_per_min": self.rate_limit_per_min,
            "whitelisted_recipients": self.whitelisted_recipients,
            "confirm_always": self.confirm_always,
            "confirm_threshold": self.confirm_threshold,
            "nanopayments_enabled": self.nanopayments_enabled,
            "nanopayments_environment": self.nanopayments_environment,
            "nanopayments_auto_topup": self.nanopayments_auto_topup,
            "nanopayments_topup_threshold": self.nanopayments_topup_threshold,
            "nanopayments_topup_amount": self.nanopayments_topup_amount,
            "nanopayments_micro_threshold": self.nanopayments_micro_threshold,
            "nanopayments_default_key_alias": self.nanopayments_default_key_alias,
            "nanopayments_default_network": self.nanopayments_default_network,
            "payment_strict_settlement": self.payment_strict_settlement,
            "auto_reconcile_pending_settlements": self.auto_reconcile_pending_settlements,
        }
        current.update(updates)
        return Config(**current)

    def masked_api_key(self) -> str:
        """Return API key with most characters masked for safe logging."""
        if len(self.circle_api_key) <= 8:
            return "****"
        return self.circle_api_key[:4] + "..." + self.circle_api_key[-4:]
