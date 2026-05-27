from typing import Literal

from pydantic import AliasChoices, AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "OmniClaw MCP Server"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: Literal["dev", "prod"] = "dev"

    # OmniClaw / Circle credentials
    CIRCLE_API_KEY: SecretStr | None = None
    ENTITY_SECRET: SecretStr | None = None
    OMNICLAW_KEY: SecretStr | None = None
    OMNICLAW_CLOUD_URL: str | None = None
    OMNICLAW_NETWORK: str = Field(
        default="ARC-TESTNET",
        validation_alias=AliasChoices("OMNICLAW_NETWORK", "OMNIAGENTPAY_NETWORK"),
    )

    # Guard policy defaults (new + backward compatible env names)
    OMNICLAW_DAILY_BUDGET: float = Field(
        default=1000.0,
        validation_alias=AliasChoices("OMNICLAW_DAILY_BUDGET", "OMNIAGENTPAY_DAILY_BUDGET"),
    )
    OMNICLAW_HOURLY_BUDGET: float = Field(
        default=200.0,
        validation_alias=AliasChoices("OMNICLAW_HOURLY_BUDGET", "OMNIAGENTPAY_HOURLY_BUDGET"),
    )
    OMNICLAW_TX_LIMIT: float = Field(
        default=500.0,
        validation_alias=AliasChoices("OMNICLAW_TX_LIMIT", "OMNIAGENTPAY_TX_LIMIT"),
    )
    OMNICLAW_RATE_LIMIT_PER_MIN: int = Field(
        default=5,
        validation_alias=AliasChoices(
            "OMNICLAW_RATE_LIMIT_PER_MIN",
            "OMNIAGENTPAY_RATE_LIMIT_PER_MIN",
        ),
    )
    OMNICLAW_WHITELISTED_RECIPIENTS: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "OMNICLAW_WHITELISTED_RECIPIENTS",
            "OMNIAGENTPAY_WHITELISTED_RECIPIENTS",
        ),
    )

    # Optional HITL policy
    OMNICLAW_CONFIRM_ALWAYS: bool = False
    OMNICLAW_CONFIRM_THRESHOLD: float | None = None

    # FastMCP Authentication
    MCP_AUTH_ENABLED: bool = True
    MCP_AUTH_TOKEN: SecretStr | None = None
    MCP_JWT_SECRET: SecretStr | None = None
    MCP_REQUIRE_AUTH: bool = True
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Webhook verification
    OMNICLAW_WEBHOOK_VERIFICATION_KEY: SecretStr | None = None

    # CORS
    BACKEND_CORS_ORIGINS: list[AnyHttpUrl] = []

    @field_validator("CIRCLE_API_KEY", "ENTITY_SECRET")
    @classmethod
    def validate_payment_secrets(cls, value: SecretStr | None, info: any) -> SecretStr | None:
        if info.data.get("ENVIRONMENT") == "prod" and not value:
            raise ValueError(f"Missing payment secret: {info.field_name}")
        return value

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        if (
            self.MCP_REQUIRE_AUTH
            and self.MCP_AUTH_ENABLED
            and not self.MCP_AUTH_TOKEN
            and not self.MCP_JWT_SECRET
        ):
            raise ValueError(
                "MCP authentication is enabled and required, but no MCP_AUTH_TOKEN or MCP_JWT_SECRET is configured."
            )
        return self

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
