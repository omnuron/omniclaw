"""Policy loading, validation, and wallet management for agent server."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from omniclaw.agent.policy_schema import RecipientMode, validate_policy
from omniclaw.core.logging import get_logger
from omniclaw.core.types import normalize_network

logger = get_logger(__name__)


def _private_key_address(private_key: str | None) -> str | None:
    if not private_key:
        return None
    try:
        from eth_account import Account

        key = private_key if private_key.startswith("0x") else f"0x{private_key}"
        return Account.from_key(key).address
    except Exception:
        return None


def _client_signer_address(client: Any) -> str | None:
    if getattr(client, "_nano_adapter", None):
        return client._nano_adapter.address
    config = getattr(client, "config", None)
    private_key = getattr(config, "nanopayments_private_key", None) or os.environ.get(
        "OMNICLAW_PRIVATE_KEY"
    )
    return _private_key_address(private_key)


@dataclass
class TimeWindow:
    """Time window for allowed transactions."""

    start: str = "00:00"  # HH:MM format
    end: str = "23:59"

    @classmethod
    def from_dict(cls, data: dict | None) -> TimeWindow:
        if not data:
            return cls()
        return cls(start=data.get("start", "00:00"), end=data.get("end", "23:59"))

    def is_allowed(self) -> bool:
        """Check if current time is within window."""
        now = datetime.now().time()
        start = time.fromisoformat(self.start)
        end = time.fromisoformat(self.end)
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end


@dataclass
class TimeRestrictions:
    """Time-based restrictions for payments."""

    allowed_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])  # 0=Mon, 6=Sun
    allowed_hours: TimeWindow = field(default_factory=TimeWindow)
    timezone: str = "UTC"

    @classmethod
    def from_dict(cls, data: dict | None) -> TimeRestrictions:
        if not data:
            return cls()
        return cls(
            allowed_days=data.get("allowed_days", [0, 1, 2, 3, 4, 5, 6]),
            allowed_hours=TimeWindow.from_dict(data.get("allowed_hours")),
            timezone=data.get("timezone", "UTC"),
        )

    def is_allowed(self) -> tuple[bool, str]:
        """Check if current time is allowed."""
        import datetime

        now = datetime.datetime.now()
        weekday = now.weekday()

        if weekday not in self.allowed_days:
            return False, f"Payments not allowed on day {weekday}"

        if not self.allowed_hours.is_allowed():
            return (
                False,
                f"Payments only allowed between {self.allowed_hours.start} and {self.allowed_hours.end}",
            )

        return True, ""


@dataclass
class IPRestrictions:
    """IP-based restrictions for API access."""

    allowed_ips: list[str] = field(default_factory=list)
    blocked_ips: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> IPRestrictions:
        if not data:
            return cls()
        return cls(
            allowed_ips=data.get("allowed_ips", []),
            blocked_ips=data.get("blocked_ips", []),
        )

    def is_allowed(self, ip: str) -> tuple[bool, str]:
        """Check if IP is allowed."""
        if self.blocked_ips and ip in self.blocked_ips:
            return False, f"IP {ip} is blocked"

        if self.allowed_ips and ip not in self.allowed_ips:
            return False, f"IP {ip} is not in allowed list"

        return True, ""


@dataclass
class CategoryConfig:
    """Payment category restrictions."""

    allowed_categories: list[str] = field(default_factory=list)
    blocked_categories: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> CategoryConfig:
        if not data:
            return cls()
        return cls(
            allowed_categories=data.get("allowed_categories", []),
            blocked_categories=data.get("blocked_categories", []),
        )

    def is_allowed(self, category: str) -> tuple[bool, str]:
        """Check if category is allowed."""
        if self.blocked_categories and category in self.blocked_categories:
            return False, f"Category {category} is blocked"

        if self.allowed_categories and category not in self.allowed_categories:
            return False, f"Category {category} is not in allowed list"

        return True, ""


@dataclass
class NetworkConfig:
    """Network/chain restrictions."""

    allowed_networks: list[str] = field(default_factory=list)
    blocked_networks: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> NetworkConfig:
        if not data:
            return cls()
        return cls(
            allowed_networks=data.get("allowed_networks", []),
            blocked_networks=data.get("blocked_networks", []),
        )

    def is_allowed(self, network: str) -> tuple[bool, str]:
        """Check if network is allowed."""
        if self.blocked_networks and network in self.blocked_networks:
            return False, f"Network {network} is blocked"

        if self.allowed_networks and network not in self.allowed_networks:
            return False, f"Network {network} is not in allowed list"

        return True, ""


@dataclass
class PurposeConfig:
    """Payment purpose pattern matching."""

    pattern: str | None = None
    required_tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> PurposeConfig:
        if not data:
            return cls()
        return cls(
            pattern=data.get("pattern"),
            required_tags=data.get("required_tags", []),
        )

    def is_allowed(self, purpose: str | None, tags: list[str] | None = None) -> tuple[bool, str]:
        """Check if purpose/tags are allowed."""
        if self.pattern and purpose and not re.match(self.pattern, purpose):
            return False, f"Purpose '{purpose}' does not match pattern {self.pattern}"

        if self.required_tags:
            if not tags:
                return False, f"Tags required: {self.required_tags}"
            for required in self.required_tags:
                if required not in tags:
                    return False, f"Required tag '{required}' not found"

        return True, ""


@dataclass
class TrustConfig:
    """Trust score requirements."""

    min_trust_score: float | None = None
    require_trust_verified: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> TrustConfig:
        if not data:
            return cls()
        return cls(
            min_trust_score=data.get("min_trust_score"),
            require_trust_verified=data.get("require_trust_verified", False),
        )

    def is_allowed(self, trust_score: float | None, verified: bool) -> tuple[bool, str]:
        """Check if trust requirements are met."""
        if self.require_trust_verified and not verified:
            return False, "Recipient must be trust verified"

        if self.min_trust_score and (trust_score is None or trust_score < self.min_trust_score):
            return False, f"Trust score {trust_score} below minimum {self.min_trust_score}"

        return True, ""


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

    mode: str = "allow_all"  # "allow_all", "whitelist" or "blacklist"
    addresses: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> RecipientConfig:
        if not data:
            return cls()
        return cls(
            mode=data.get("mode", "allow_all"),
            addresses=data.get("addresses", []),
            domains=data.get("domains", []),
        )


@dataclass
class RailConfig:
    """Enabled buyer payment rails for a policy wallet/profile."""

    circle_transfer: bool = True
    x402_exact: bool = True
    gateway: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> RailConfig:
        if not data:
            return cls()
        return cls(
            circle_transfer=bool(data.get("circle_transfer", True)),
            x402_exact=bool(data.get("x402_exact", True)),
            gateway=bool(data.get("gateway", True)),
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "circle_transfer": self.circle_transfer,
            "x402_exact": self.x402_exact,
            "gateway": self.gateway,
        }


@dataclass
class Policy:
    """Main policy configuration for the agent economy."""

    version: str = "2.0"
    tokens: dict[str, dict[str, Any]] = field(default_factory=dict)
    wallets: dict[str, dict[str, Any]] = field(default_factory=dict)
    limits: WalletLimits = field(default_factory=WalletLimits)
    rate_limits: RateLimits = field(default_factory=RateLimits)
    recipients: RecipientConfig = field(default_factory=RecipientConfig)
    confirm_threshold: Decimal | None = None

    def to_dict(self) -> dict:
        """Convert policy to dict for saving."""
        result = {
            "version": self.version,
            "tokens": self.tokens,
            "wallets": self.wallets,
        }

        if self.limits and any(
            [
                self.limits.daily_max,
                self.limits.hourly_max,
                self.limits.per_tx_max,
                self.limits.per_tx_min,
            ]
        ):
            result["limits"] = {
                "daily_max": str(self.limits.daily_max) if self.limits.daily_max else None,
                "hourly_max": str(self.limits.hourly_max) if self.limits.hourly_max else None,
                "per_tx_max": str(self.limits.per_tx_max) if self.limits.per_tx_max else None,
                "per_tx_min": str(self.limits.per_tx_min) if self.limits.per_tx_min else None,
            }

        if self.rate_limits and any([self.rate_limits.per_minute, self.rate_limits.per_hour]):
            result["rate_limits"] = {
                "per_minute": self.rate_limits.per_minute,
                "per_hour": self.rate_limits.per_hour,
            }

        if self.recipients and (
            self.recipients.mode != "allow_all"
            or self.recipients.addresses
            or self.recipients.domains
        ):
            result["recipients"] = {
                "mode": self.recipients.mode,
                "addresses": self.recipients.addresses,
                "domains": self.recipients.domains,
            }

        if self.confirm_threshold:
            result["confirm_threshold"] = str(self.confirm_threshold)

        return result

    @classmethod
    def from_dict(cls, data: dict | None) -> Policy:
        if not data:
            return cls()
        return cls(
            version=data.get("version", "2.0"),
            tokens=data.get("tokens", {}),
            wallets=data.get("wallets", {}),
            limits=WalletLimits.from_dict(data.get("limits")),
            rate_limits=RateLimits.from_dict(data.get("rate_limits")),
            recipients=RecipientConfig.from_dict(data.get("recipients")),
            confirm_threshold=Decimal(data.get("confirm_threshold", "0"))
            if data.get("confirm_threshold")
            else None,
        )


class RuntimeWalletState:
    """Generated buyer wallet state kept separate from stable policy."""

    def __init__(self, path: str | None = None, policy_path: str | None = None):
        if path is None:
            path = os.environ.get("OMNICLAW_AGENT_STATE_PATH")
        if path is None and policy_path and str(policy_path).startswith("/config/"):
            path = "/data/omniclaw/wallet-state.json"
        if path is None and policy_path:
            policy_file = Path(policy_path)
            path = str(policy_file.with_name(f"{policy_file.stem}.state.json"))
        self._path = Path(path or ".omniclaw-agent-state.json")
        self._data: dict[str, Any] = {"version": "1.0", "wallets": {}}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        if self._path.exists():
            with open(self._path) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = loaded
        self._data.setdefault("version", "1.0")
        self._data.setdefault("wallets", {})
        self._loaded = True

    def get_wallet(self, alias: str) -> dict[str, Any]:
        self.load()
        wallets = self._data.setdefault("wallets", {})
        value = wallets.get(alias, {})
        return dict(value) if isinstance(value, dict) else {}

    def set_wallet(self, alias: str, updates: dict[str, Any]) -> bool:
        self.load()
        wallets = self._data.setdefault("wallets", {})
        current = dict(wallets.get(alias, {}))
        next_value = {**current, **updates}
        if current == next_value:
            return False
        wallets[alias] = next_value
        return True

    def save(self) -> None:
        self.load()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2, default=str)
            f.write("\n")


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
        self._last_mtime: float | None = None

    async def load(self) -> Policy:
        """Load policy from file."""
        path = Path(self._policy_path)
        if not path.exists():
            self._logger.warning(
                f"Policy file not found: {self._policy_path}, creating default policy"
            )
            env_token = os.environ.get("OMNICLAW_AGENT_TOKEN")
            if not env_token:
                raise ValueError(
                    "OMNICLAW_AGENT_TOKEN is required when creating a default policy. "
                    "Set it or provide OMNICLAW_AGENT_POLICY_PATH."
                )
            wallet_alias = os.environ.get("OMNICLAW_AGENT_WALLET", "primary")
            # Create default policy with default token and wallet
            self._policy = Policy(
                version="2.0",
                tokens={
                    env_token: {
                        "wallet_alias": wallet_alias,
                        "active": True,
                        "label": "Default Agent",
                    }
                },
                wallets={
                    wallet_alias: {
                        "name": "Primary Wallet",
                        "limits": {"daily_max": "100.00", "per_tx_max": "10.00"},
                        "recipients": {"mode": "allow_all"},
                        "rails": {
                            "circle_transfer": True,
                            "x402_exact": True,
                            "gateway": True,
                        },
                    }
                },
            )
            # Save default policy to file
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._write_policy_file()
                self._logger.info(f"Created default policy at {self._policy_path}")
            except Exception as e:
                raise PermissionError(
                    f"Policy file is not writable: {self._policy_path}. {e}"
                ) from e
            return self._policy

        try:
            with open(path) as f:
                data = json.load(f)
            # Strict schema validation
            validated = validate_policy(data)
            self._policy = Policy.from_dict(validated.model_dump())
            self._last_mtime = path.stat().st_mtime
            self._logger.info("Loaded agent economy policy configuration.")
        except Exception as e:
            self._logger.error(f"Failed to load policy: {e}")
            raise
        return self._policy

    def save(self) -> None:
        """Persist current policy to disk."""
        if not self._policy:
            return
        self._write_policy_file()

    def _write_policy_file(self) -> None:
        """Persist policy and refresh the watched mtime."""
        if not self._policy:
            return
        path = Path(self._policy_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._policy.to_dict(), indent=2, default=str)
            with open(path, "w") as f:
                f.write(payload)
                f.write("\n")
            try:
                self._last_mtime = path.stat().st_mtime
            except Exception:
                self._last_mtime = None
        except Exception as e:
            raise PermissionError(f"Policy file is not writable: {self._policy_path}. {e}") from e

    def get_token_map(self) -> dict[str, dict[str, Any]]:
        return self._policy.tokens if self._policy else {}

    @property
    def policy_path(self) -> str:
        return self._policy_path

    def get_wallet_map(self) -> dict[str, dict[str, Any]]:
        return self._policy.wallets if self._policy else {}

    def update_wallet_config(self, alias: str, updates: dict[str, Any]) -> None:
        """Update wallet config in policy for a given alias."""
        if not self._policy:
            self._policy = Policy()
        wallet_cfg = self._policy.wallets.get(alias, {})
        wallet_cfg.update(updates)
        self._policy.wallets[alias] = wallet_cfg

    def set_mapping(self, token: str, wallet_id: str, config: dict[str, Any]) -> None:
        self._token_to_wallet_id[token] = wallet_id
        self._wallet_id_to_config[wallet_id] = config

    def reset_mappings(self) -> None:
        self._token_to_wallet_id = {}
        self._wallet_id_to_config = {}

    def get_wallet_id_for_token(self, token: str) -> str | None:
        return self._token_to_wallet_id.get(token)

    def get_policy(self) -> Policy:
        return self._policy or Policy()

    def get_wallet_config(self, wallet_id: str | None) -> dict[str, Any]:
        """Get cached wallet config for a given wallet_id."""
        if not wallet_id:
            return {}
        return self._wallet_id_to_config.get(wallet_id, {})

    def _wallet_config(self, wallet_id: str | None) -> dict[str, Any]:
        if not wallet_id:
            return {}
        return self._wallet_id_to_config.get(wallet_id, {})

    def _recipient_config_for_wallet(self, wallet_id: str | None = None) -> RecipientConfig:
        if wallet_id is None:
            return self.get_policy().recipients
        config = self._wallet_config(wallet_id)
        if config.get("recipients") is not None:
            return RecipientConfig.from_dict(config.get("recipients"))
        return self.get_policy().recipients

    def _limits_for_wallet(self, wallet_id: str | None = None) -> WalletLimits:
        if wallet_id is None:
            return self.get_policy().limits
        config = self._wallet_config(wallet_id)
        wallet_limits = WalletLimits.from_dict(config.get("limits"))
        base_limits = self.get_policy().limits
        return WalletLimits(
            daily_max=wallet_limits.daily_max or base_limits.daily_max,
            hourly_max=wallet_limits.hourly_max or base_limits.hourly_max,
            per_tx_max=wallet_limits.per_tx_max or base_limits.per_tx_max,
            per_tx_min=wallet_limits.per_tx_min or base_limits.per_tx_min,
        )

    @staticmethod
    def _host_matches(hostname: str, allowed_domain: str) -> bool:
        host = hostname.strip(".").lower()
        domain = allowed_domain.strip(".").lower()
        return host == domain or host.endswith(f".{domain}")

    def has_changed(self) -> bool:
        path = Path(self._policy_path)
        if not path.exists():
            return False
        if self._last_mtime is None:
            return True
        try:
            return path.stat().st_mtime > self._last_mtime
        except Exception:
            return False

    async def reload(self) -> bool:
        """Reload policy if changed. Returns True on success."""
        if not self.has_changed():
            return False
        try:
            await self.load()
            self.reset_mappings()
            self._logger.info("Policy reloaded successfully.")
            return True
        except Exception as e:
            self._logger.error(f"Policy reload failed: {e}")
            return False

    def is_valid_recipient(self, recipient: str, wallet_id: str | None = None) -> bool:
        """Check if recipient is allowed."""
        recipient_cfg = self._recipient_config_for_wallet(wallet_id)

        if recipient_cfg.mode == RecipientMode.ALLOW_ALL.value:
            return True

        if not recipient_cfg.addresses and not recipient_cfg.domains:
            return recipient_cfg.mode != RecipientMode.WHITELIST.value

        if recipient in recipient_cfg.addresses:
            return recipient_cfg.mode == RecipientMode.WHITELIST.value

        if recipient.startswith("http"):
            hostname = urlparse(recipient).hostname or ""
            domain_match = any(
                self._host_matches(hostname, domain) for domain in recipient_cfg.domains
            )
            if domain_match:
                return recipient_cfg.mode == RecipientMode.WHITELIST.value

        return recipient_cfg.mode != RecipientMode.WHITELIST.value

    def check_limits(
        self, amount: Decimal, wallet_id: str | None = None
    ) -> tuple[bool, str | None]:
        limits = self._limits_for_wallet(wallet_id)

        if limits.per_tx_max and amount > limits.per_tx_max:
            return False, f"Amount {amount} exceeds per_tx_max {limits.per_tx_max}"
        if limits.per_tx_min and amount < limits.per_tx_min:
            return False, f"Amount {amount} is below per_tx_min {limits.per_tx_min}"

        return True, None

    def requires_confirmation(self, amount: Decimal, wallet_id: str | None = None) -> bool:
        if wallet_id is None:
            threshold = self.get_policy().confirm_threshold or Decimal("0")
        else:
            config = self._wallet_id_to_config.get(wallet_id, {})
            threshold = (
                Decimal(str(config.get("confirm_threshold")))
                if config.get("confirm_threshold") is not None
                else self.get_policy().confirm_threshold or Decimal("0")
            )
        return threshold > 0 and amount >= threshold

    def rail_config(self, wallet_id: str | None = None) -> RailConfig:
        config = self._wallet_config(wallet_id)
        return RailConfig.from_dict(config.get("rails"))

    def is_rail_enabled(self, rail: str, wallet_id: str | None = None) -> bool:
        rails = self.rail_config(wallet_id)
        if rail == "circle_transfer":
            return rails.circle_transfer
        if rail == "x402_exact":
            return rails.x402_exact
        if rail == "gateway":
            return rails.gateway
        return False


class WalletManager:
    """Manages wallet creation based on policy mapping."""

    def __init__(
        self,
        policy_manager: PolicyManager,
        omniclaw_client: Any,
        runtime_state: RuntimeWalletState | None = None,
    ):
        self._policy = policy_manager
        self._client = omniclaw_client
        self._state = runtime_state or RuntimeWalletState(policy_path=policy_manager.policy_path)
        self._logger = logger

    async def initialize_wallets(self) -> dict[str, str]:
        """Initialize all wallets defined in the policy mapping (Parallel)."""
        self._policy.reset_mappings()
        token_map = self._policy.get_token_map()
        wallet_map = self._policy.get_wallet_map()

        # If no tokens in policy, nothing to initialize
        if not token_map:
            self._logger.info("No tokens defined in policy, skipping initialization")
            return {}

        # Build alias -> tokens mapping
        alias_to_tokens: dict[str, list[str]] = {}
        for token, config in token_map.items():
            if config.get("active") is False:
                continue
            alias = config.get("wallet_alias", "primary")
            alias_to_tokens.setdefault(alias, []).append(token)

        # PHASE 1: Pre-populate token map with placeholder
        for alias, tokens in alias_to_tokens.items():
            for token in tokens:
                cfg = dict(wallet_map.get(alias, {}))
                cfg.setdefault("alias", alias)
                self._policy.set_mapping(token, f"pending-{alias}", cfg)

        changed = False
        results: dict[str, str] = {}
        target_network = normalize_network(
            getattr(getattr(self._client, "_config", None), "network", None)
        )

        # PHASE 2: Ensure each alias has a Circle wallet id + address
        async def init_alias(alias: str) -> tuple[str, str | None, str | None]:
            wallet_cfg = wallet_map.get(alias)
            if wallet_cfg is None:
                wallet_cfg = {}
                self._policy.update_wallet_config(alias, wallet_cfg)

            runtime_cfg = self._state.get_wallet(alias)
            wallet_id = wallet_cfg.get("wallet_id") or runtime_cfg.get("circle_wallet_id")
            wallet_address = wallet_cfg.get("address") or runtime_cfg.get("circle_wallet_address")
            gateway_address = runtime_cfg.get("gateway_eoa_address")
            signer_address = _client_signer_address(self._client)
            if signer_address:
                gateway_address = signer_address

            circle_enabled = bool(getattr(self._client.config, "enable_circle_transfer", True))
            if not circle_enabled:
                synthetic_prefix = (
                    "gateway" if getattr(self._client.config, "enable_gateway", False) else "eoa"
                )
                synthetic_id = (
                    wallet_id or runtime_cfg.get("wallet_id") or f"{synthetic_prefix}:{alias}"
                )
                return alias, synthetic_id, wallet_address or gateway_address

            # If wallet_id exists, verify and fill address if missing
            if wallet_id:
                try:
                    wallet = await self._client.get_wallet(wallet_id)
                    wallet_network = normalize_network(getattr(wallet, "blockchain", None))
                    if target_network and wallet_network and wallet_network != target_network:
                        self._logger.warning(
                            "Wallet '%s' for alias '%s' is on %s but current network is %s. "
                            "Creating a new wallet for the target network.",
                            wallet_id,
                            alias,
                            wallet_network.value,
                            target_network.value,
                        )
                        wallet_id = None
                        wallet_address = None
                    else:
                        if wallet and wallet.address and wallet.address != wallet_address:
                            wallet_address = wallet.address
                        return alias, wallet_id, wallet_address
                except Exception as exc:
                    raise RuntimeError(
                        f"Configured wallet '{wallet_id}' for alias '{alias}' could not be "
                        f"verified. Fix the policy or remove wallet_id to create a new wallet."
                    ) from exc

            # Create a new wallet for this alias
            res = await self._client.create_agent_wallet(
                agent_name=f"omniclaw-{alias}",
                apply_default_guards=False,
            )
            if isinstance(res, tuple | list):
                _, wallet = res
            else:
                wallet = res
            wallet_id = wallet.id
            wallet_address = wallet.address
            return alias, wallet_id, wallet_address

        # Run per-alias initialization in parallel
        tasks = [init_alias(alias) for alias in alias_to_tokens]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in batch_results:
            if isinstance(result, Exception):
                self._logger.error(f"Failed to initialize wallet: {result}")
                continue
            alias, wallet_id, wallet_address = result
            if not wallet_id:
                continue
            # Persist wallet_id/address into policy
            circle_enabled = bool(getattr(self._client.config, "enable_circle_transfer", True))
            gateway_address = _client_signer_address(self._client)
            state_updates = {
                "wallet_id": wallet_id,
                "circle_wallet_id": wallet_id if circle_enabled else None,
                "circle_wallet_address": wallet_address if circle_enabled else None,
                "gateway_eoa_address": gateway_address,
                "signer_address": gateway_address,
                "network": getattr(
                    self._client.config.network, "value", self._client.config.network
                ),
            }
            if self._state.set_wallet(alias, state_updates):
                changed = True
            # Map all tokens sharing this alias
            for token in alias_to_tokens.get(alias, []):
                cfg = dict(wallet_map.get(alias, {}))
                cfg.update(
                    {
                        "wallet_id": wallet_id,
                        "address": wallet_address,
                        "gateway_eoa_address": gateway_address,
                    }
                )
                cfg.setdefault("alias", alias)
                self._policy.set_mapping(token, wallet_id, cfg)
                results[token] = wallet_id
            self._logger.info(f"Initialized wallet '{wallet_id}' for alias '{alias}'")

            # Apply policy guards to this wallet
            try:
                await self._apply_policy_guards(wallet_id, wallet_map.get(alias, {}))
            except Exception as e:
                self._logger.error(f"Failed to apply policy guards for wallet '{wallet_id}': {e}")

        if changed:
            self._state.save()

        return results

    async def _apply_policy_guards(self, wallet_id: str, wallet_cfg: dict[str, Any]) -> None:
        """Apply policy.json guard configuration to a wallet."""
        policy = self._policy.get_policy()

        # Clear existing policy guards to avoid duplicates
        with contextlib.suppress(Exception):
            await self._client._guard_manager.clear_wallet_guards(wallet_id)

        # Resolve limits: wallet overrides policy defaults
        base_limits = policy.limits
        wallet_limits = WalletLimits.from_dict(wallet_cfg.get("limits"))
        daily_max = wallet_limits.daily_max or base_limits.daily_max
        hourly_max = wallet_limits.hourly_max or base_limits.hourly_max
        per_tx_max = wallet_limits.per_tx_max or base_limits.per_tx_max
        per_tx_min = wallet_limits.per_tx_min or base_limits.per_tx_min

        if daily_max or hourly_max:
            await self._client.add_budget_guard(
                wallet_id=wallet_id,
                daily_limit=str(daily_max) if daily_max else None,
                hourly_limit=str(hourly_max) if hourly_max else None,
                name="policy_budget",
            )

        if per_tx_max or per_tx_min:
            max_amount = per_tx_max if per_tx_max else Decimal("1e18")
            await self._client.add_single_tx_guard(
                wallet_id=wallet_id,
                max_amount=str(max_amount),
                min_amount=str(per_tx_min) if per_tx_min else None,
                name="policy_single_tx",
            )

        # Rate limits
        base_rate = policy.rate_limits
        wallet_rate = RateLimits.from_dict(wallet_cfg.get("rate_limits"))
        per_minute = wallet_rate.per_minute or base_rate.per_minute
        per_hour = wallet_rate.per_hour or base_rate.per_hour
        if per_minute or per_hour:
            await self._client.add_rate_limit_guard(
                wallet_id=wallet_id,
                max_per_minute=per_minute,
                max_per_hour=per_hour,
                name="policy_rate_limit",
            )

        # Recipients
        wallet_recipients = wallet_cfg.get("recipients")
        if wallet_recipients is not None:
            rcfg = RecipientConfig.from_dict(wallet_recipients)
        else:
            rcfg = policy.recipients

        if rcfg.mode != RecipientMode.ALLOW_ALL.value:
            await self._client.add_recipient_guard(
                wallet_id=wallet_id,
                mode=rcfg.mode,
                addresses=rcfg.addresses,
                domains=rcfg.domains,
                name="policy_recipient",
            )

        # Confirm threshold
        threshold = (
            Decimal(str(wallet_cfg.get("confirm_threshold")))
            if wallet_cfg.get("confirm_threshold") is not None
            else policy.confirm_threshold
        )
        if threshold and threshold > 0:
            await self._client.add_confirm_guard(
                wallet_id=wallet_id,
                threshold=str(threshold),
                always_confirm=False,
                name="policy_confirm",
            )

    async def get_wallet_address(self, wallet_id: str | None = None) -> str | None:
        """Get wallet address."""
        if not wallet_id:
            return None
        try:
            wallet = await self._client.get_wallet(wallet_id)
            return wallet.address if wallet else None
        except Exception:
            return None

    async def get_wallet_balance(self, wallet_id: str | None = None) -> Decimal | None:
        """Get wallet balance."""
        if not wallet_id:
            return None
        try:
            return await self._client.get_balance(wallet_id)
        except Exception:
            return None
