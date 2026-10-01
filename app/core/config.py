"""Centralised configuration. Everything comes from environment variables / .env."""

from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Shared secret used to verify HMAC signatures on incoming payment webhooks.
    webhook_secret: SecretStr

    # Probability (0..1) that the *simulated* payment endpoint reports SUCCESS.
    payment_success_rate: float = 0.8

    log_level: str = "INFO"

    # Only used by `python -m app.scripts.seed` to bootstrap an admin account.
    admin_email: str | None = None
    admin_password: SecretStr | None = None

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_long_enough(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @field_validator("webhook_secret")
    @classmethod
    def _webhook_secret_long_enough(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 16:
            raise ValueError("WEBHOOK_SECRET must be at least 16 characters")
        return v

    @field_validator("payment_success_rate")
    @classmethod
    def _rate_is_probability(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("PAYMENT_SUCCESS_RATE must be between 0 and 1")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment


settings = get_settings()
