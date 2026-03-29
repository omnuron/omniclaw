"""Policy loading, validation, and wallet management for agent server."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from omniclaw.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class WalletLimits:
    """Spending limits for a wallet."""

    daily_max: Decimal | None = None
    hourly_max: Decimal | None = None
    per_tx_max: Decimal | None = None
    per_tx_min: Decimal | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> WalletLimits:
        if not data:
            return cls()
        return cls(
            daily_max=Decimal(data.get("daily_max", "0")) if data.get("daily_max") else None,
            hourly_max=Decimal(data.get("hourly_max", "0")) if data.get("hourly_max") else None,
            per_tx_max=Decimal(data.get("per_tx_max", "0")) if data.get("per_tx_max") else None,
            per_tx_min=Decimal(data.get("per_tx_min", "0")) if data.get("per_tx_min") else None,
        )


@dataclass
class RateLimits:
    """Rate limits for a wallet."""

    per_minute: int | None = None
    per_hour: int | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> RateLimits:
        if not data:
            return cls()
        return cls(
            per_minute=data.get("per_minute"),
            per_hour=data.get("per_hour"),
        )


@dataclass
class RecipientConfig:
    """Recipient whitelist/blacklist configuration."""

    mode: str = "whitelist"  # "whitelist" or "blacklist"
    addresses: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> RecipientConfig:
        if not data:
            return cls()
        return cls(
            mode=data.get("mode", "whitelist"),
            addresses=data.get("addresses", []),
            domains=data.get("domains", []),
        )


@dataclass
class Policy:
    """Main policy configuration for the single agent wallet."""

    version: str = "2.0"
    limits: WalletLimits = field(default_factory=WalletLimits)
    rate_limits: RateLimits = field(default_factory=RateLimits)
    recipients: RecipientConfig = field(default_factory=RecipientConfig)
    confirm_threshold: Decimal | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> Policy:
        if not data:
            return cls()
        return cls(
            version=data.get("version", "2.0"),
            limits=WalletLimits.from_dict(data.get("limits")),
            rate_limits=RateLimits.from_dict(data.get("rate_limits")),
            recipients=RecipientConfig.from_dict(data.get("recipients")),
            confirm_threshold=Decimal(data.get("confirm_threshold", "0"))
            if data.get("confirm_threshold")
            else None,
        )


class PolicyManager:
    """Manages policy loading, validation, and wallet operations."""

    def __init__(self, policy_path: str | None = None):
        self._policy_path = policy_path or os.environ.get(
            "OMNICLAW_AGENT_POLICY_PATH", "/config/policy.json"
        )
        self._policy: Policy | None = None
        self._wallet_id: str | None = None
        self._logger = logger

    async def load(self) -> Policy:
        """Load policy from file."""
        path = Path(self._policy_path)
        if not path.exists():
            self._logger.warning(f"Policy file not found: {self._policy_path}, using empty policy")
            self._policy = Policy()
            return self._policy

        with open(path) as f:
            data = json.load(f)

        self._policy = Policy.from_dict(data)
        self._logger.info("Loaded agent policy configuration.")
        return self._policy

    def get_policy(self) -> Policy:
        """Get current policy."""
        if not self._policy:
            raise RuntimeError("Policy not loaded")
        return self._policy

    def get_wallet_id(self) -> str | None:
        return self._wallet_id

    def set_wallet_id(self, wallet_id: str) -> None:
        """Set wallet ID after creation."""
        self._wallet_id = wallet_id
        self._logger.info(f"Set primary agent wallet ID to '{wallet_id}'")

    def is_valid_recipient(self, recipient: str) -> bool:
        """Check if recipient is allowed for wallet."""
        if not self._policy:
            return True  # No policy means allow all

        recipients = self._policy.recipients
        if not recipients.addresses and not recipients.domains:
            return True  # No restrictions

        if recipient in recipients.addresses:
            return recipients.mode == "whitelist"

        if recipient.startswith("http"):
            for domain in recipients.domains:
                if domain in recipient:
                    return recipients.mode == "whitelist"

        return recipients.mode != "whitelist"

    def check_limits(self, amount: Decimal) -> tuple[bool, str | None]:
        """Check if amount is within limits."""
        if not self._policy:
            return True, None

        limits = self._policy.limits

        if limits.per_tx_max and amount > limits.per_tx_max:
            return False, f"Amount {amount} exceeds per_tx_max {limits.per_tx_max}"

        if limits.per_tx_min and amount < limits.per_tx_min:
            return False, f"Amount {amount} below per_tx_min {limits.per_tx_min}"

        return True, None

    def requires_confirmation(self, amount: Decimal) -> bool:
        """Check if payment requires confirmation."""
        if not self._policy:
            return False
        threshold = self._policy.confirm_threshold
        if not threshold:
            return False
        return amount >= threshold


class WalletManager:
    """Manages wallet creation based on policy."""

    def __init__(self, policy_manager: PolicyManager, omniclaw_client: Any):
        self._policy = policy_manager
        self._client = omniclaw_client
        self._logger = logger

    async def initialize_wallets(self) -> dict[str, str]:
        """Ensure the single agent wallet exists."""
        try:
            wallet_id = os.environ.get("OMNICLAW_AGENT_WALLET_ID")
            if wallet_id:
                wallet = await self._client.get_wallet(wallet_id)
            else:
                wallet_set, wallet = await self._client.create_agent_wallet(
                    agent_name="omniclaw-primary-agent",
                    apply_default_guards=False,
                )

            self._policy.set_wallet_id(wallet.id)
            self._logger.info(f"Wallet successfully initialized: {wallet.id}")
            return {"status": "success", "wallet_id": wallet.id}
        except Exception as e:
            self._logger.error(f"Failed to initialize agent wallet: {e}")
            return {"status": "error", "message": str(e)}

    async def get_wallet_address(self) -> str | None:
        """Get wallet address."""
        wallet_id = self._policy.get_wallet_id()
        if not wallet_id:
            return None
        wallet = await self._client.get_wallet(wallet_id)
        return wallet.address if wallet else None

    async def get_wallet_balance(self) -> Decimal | None:
        """Get wallet balance."""
        wallet_id = self._policy.get_wallet_id()
        if not wallet_id:
            return None
        return await self._client.get_balance(wallet_id)
