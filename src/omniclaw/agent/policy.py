"""Policy loading, validation, and wallet management for agent server."""

from __future__ import annotations

import asyncio
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
    """Main policy configuration for the agent economy."""
    version: str = "0.0.2"
    tokens: dict[str, dict[str, Any]] = field(default_factory=dict)
    wallets: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> Policy:
        if not data:
            return cls()
        return cls(
            version=data.get("version", "2.0"),
            tokens=data.get("tokens", {}),
            wallets=data.get("wallets", {}),
        )


class PolicyManager:
    """Manages policy loading, validation, and multi-agent token mapping."""
    def __init__(self, policy_path: str | None = None):
        self._policy_path = policy_path or os.environ.get(
            "OMNICLAW_AGENT_POLICY_PATH", "/config/policy.json"
        )
        self._policy: Policy | None = None
        self._token_to_wallet_id: dict[str, str] = {}
        self._wallet_id_to_config: dict[str, dict[str, Any]] = {}
        self._logger = logger

    async def load(self) -> Policy:
        """Load policy from file."""
        path = Path(self._policy_path)
        if not path.exists():
            self._logger.warning(f"Policy file not found: {self._policy_path}, using empty policy")
            self._policy = Policy()
            return self._policy

        with open(path, "r") as f:
            data = json.load(f)

        self._policy = Policy.from_dict(data)
        self._logger.info("Loaded agent economy policy configuration.")
        return self._policy

    def get_token_map(self) -> dict[str, dict[str, Any]]:
        return self._policy.tokens if self._policy else {}

    def get_wallet_map(self) -> dict[str, dict[str, Any]]:
        return self._policy.wallets if self._policy else {}

    def set_mapping(self, token: str, wallet_id: str, config: dict[str, Any]) -> None:
        self._token_to_wallet_id[token] = wallet_id
        self._wallet_id_to_config[wallet_id] = config

    def get_wallet_id_for_token(self, token: str) -> str | None:
        return self._token_to_wallet_id.get(token)

    def is_valid_recipient(self, recipient: str, wallet_id: str) -> bool:
        """Check if recipient is allowed for a specific wallet."""
        config = self._wallet_id_to_config.get(wallet_id, {})
        recipient_cfg = RecipientConfig.from_dict(config.get("recipients"))
        
        if not recipient_cfg.addresses and not recipient_cfg.domains:
            return True

        if recipient in recipient_cfg.addresses:
            return recipient_cfg.mode == "whitelist"

        if recipient.startswith("http"):
            for domain in recipient_cfg.domains:
                if domain in recipient:
                    return recipient_cfg.mode == "whitelist"

        return recipient_cfg.mode != "whitelist"

    def check_limits(self, amount: Decimal, wallet_id: str) -> tuple[bool, str | None]:
        config = self._wallet_id_to_config.get(wallet_id, {})
        limits = WalletLimits.from_dict(config.get("limits"))

        if limits.per_tx_max and amount > limits.per_tx_max:
            return False, f"Amount {amount} exceeds per_tx_max {limits.per_tx_max}"

        return True, None

    def requires_confirmation(self, amount: Decimal, wallet_id: str) -> bool:
        config = self._wallet_id_to_config.get(wallet_id, {})
        threshold = Decimal(config.get("confirm_threshold", "0"))
        return threshold > 0 and amount >= threshold


class WalletManager:
    """Manages secure wallet mapping from policy tokens."""
    def __init__(self, policy_manager: PolicyManager, omniclaw_client: Any):
        self._policy = policy_manager
        self._client = omniclaw_client
        self._logger = logger

    async def initialize_wallets(self) -> dict[str, str]:
        """Initialize all wallets defined in the policy mapping (Parallel)."""
        token_map = self._policy.get_token_map()
        wallet_map = self._policy.get_wallet_map()
        results = {}

        # PHASE 1: Pre-populate token map with alias so Auth works immediately (stateless)
        for token, config in token_map.items():
            alias = config.get("wallet_alias", "primary")
            # We don't have the real wallet_id yet, but we map it to a placeholder 
            # so the Agent isn't rejected with "Unauthorized"
            self._policy.set_mapping(token, f"pending-{alias}", wallet_map.get(alias, {}))

        # PHASE 2: Perform the intensive SDK/Network calls in PARALLEL
        async def init_one(token: str, config: dict[str, Any]):
            alias = config.get("wallet_alias", "primary")
            wallet_cfg = wallet_map.get(alias, {})
            try:
                # 10/10 RESILIENCE: Explicitly handle async/sync transitions to prevent unpacking errors
                coro = self._client.create_agent_wallet(
                    agent_name=f"omniclaw-{alias}",
                    apply_default_guards=False,
                )
                
                # Check for double-wrapping or mismatched SDK versions
                if asyncio.iscoroutine(coro):
                    res = await coro
                else:
                    res = coro  # Should not happen if SDK is correctly async 
                
                wallet_set, wallet = res
                # Success! Overwrite the placeholder with the real wallet ID
                self._policy.set_mapping(token, wallet.id, wallet_cfg)
                self._logger.info(f"Successfully initialized wallet '{wallet.id}' for agent '{alias}'")
                return token, wallet.id
            except Exception as e:
                self._logger.error(f"Failed to initialize wallet for '{alias}': {e}")
                return token, None

        # Gather all parallel tasks
        tasks = [init_one(token, config) for token, config in token_map.items()]
        batch_results = await asyncio.gather(*tasks)
        
        # Collect results
        for token, wallet_id in batch_results:
            if wallet_id:
                results[token] = wallet_id
        
        return results

    async def get_wallet_address(self, wallet_id: str) -> str | None:
        """Get wallet address."""
        try:
            wallet = await self._client.get_wallet(wallet_id)
            return wallet.address if wallet else None
        except Exception:
            return None

    async def get_wallet_balance(self, wallet_id: str) -> Decimal | None:
        """Get wallet balance."""
        try:
            return await self._client.get_balance(wallet_id)
        except Exception:
            return None
