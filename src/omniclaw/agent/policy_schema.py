"""Strict policy schema validation for agent policy.json."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class RecipientMode(str, Enum):
    ALLOW_ALL = "allow_all"
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"


class LimitsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_max: Decimal | None = None
    hourly_max: Decimal | None = None
    per_tx_max: Decimal | None = None
    per_tx_min: Decimal | None = None


class RateLimitsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_minute: int | None = None
    per_hour: int | None = None


class RecipientConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: RecipientMode = RecipientMode.ALLOW_ALL
    addresses: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class RailsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    circle_transfer: bool = True
    x402_exact: bool = True
    gateway: bool = True


class TokenConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wallet_alias: str
    active: bool = True
    label: str | None = None


class WalletConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    wallet_id: str | None = None
    address: str | None = None
    limits: LimitsModel | None = None
    rate_limits: RateLimitsModel | None = None
    recipients: RecipientConfigModel | None = None
    confirm_threshold: Decimal | None = None
    rails: RailsModel | None = None

    @field_validator("address")
    @classmethod
    def _validate_address(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.startswith("0x") or len(value) != 42:
            raise ValueError("wallet address must be a 0x-prefixed 40-hex string")
        return value


class PolicySchema(BaseModel):
    """Strict schema for policy.json."""

    model_config = ConfigDict(extra="forbid")

    version: str = "2.0"
    tokens: dict[str, TokenConfigModel]
    wallets: dict[str, WalletConfigModel]
    limits: LimitsModel | None = None
    rate_limits: RateLimitsModel | None = None
    recipients: RecipientConfigModel | None = None
    confirm_threshold: Decimal | None = None

    @model_validator(mode="after")
    def _validate_aliases(self) -> PolicySchema:
        if not self.tokens:
            raise ValueError("policy.tokens must not be empty")
        if not self.wallets:
            raise ValueError("policy.wallets must not be empty")
        for token, cfg in self.tokens.items():
            if cfg.wallet_alias not in self.wallets:
                raise ValueError(
                    f"token '{token}' references missing wallet_alias '{cfg.wallet_alias}'"
                )
        return self


def validate_policy(data: dict[str, Any]) -> PolicySchema:
    """Validate raw policy JSON and return normalized policy model."""
    try:
        return PolicySchema.model_validate(data)
    except ValidationError as exc:
        # Re-raise with a simpler message for operator logs
        raise ValueError(f"Invalid policy.json: {exc}") from exc
