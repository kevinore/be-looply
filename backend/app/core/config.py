from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: Literal["development", "test", "production"] = "development"
    DATABASE_URL: str
    # Only migrations and scripts use it. Never set in Railway.
    MIGRATION_DATABASE_URL: str = ""
    PUBLIC_APP_URL: str = "http://localhost:5173"
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    COOKIE_SECURE: bool = False
    DEFAULT_BUSINESS_SLUG: str
    PRIVACY_POLICY_VERSION: str
    SENTRY_DSN: str = ""
    WEATHER_TIMEOUT_SECONDS: float = 2

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value


settings = Settings()
