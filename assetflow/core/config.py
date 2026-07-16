from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASSETFLOW_", env_file=".env", extra="ignore", populate_by_name=True
    )

    app_name: str = "AssetFlow AI"
    environment: str = "development"
    debug: bool = False
    database_url: str = Field(
        default="sqlite:///./assetflow.db",
        validation_alias=AliasChoices("database_url", "DATABASE_URL", "ASSETFLOW_DATABASE_URL"),
    )
    secret_key: str = "development-only-change-me"
    allowed_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1", "testserver"]
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60
    upload_dir: Path = Path("var/uploads")
    max_upload_bytes: int = 10 * 1024 * 1024
    approved_preview_retention_days: int = 10
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "ASSETFLOW_OPENAI_API_KEY"),
    )
    openai_model: str = "gpt-4o-mini"
    ai_hourly_request_limit: int = 5
    ai_cooldown_seconds: int = 30

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def split_hosts(cls, value):
        return [host.strip() for host in value.split(",") if host.strip()] if isinstance(value, str) else value

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.jwt_algorithm != "HS256":
            raise ValueError("AssetFlow supports only HS256 JWT signing")
        if self.environment == "production":
            if (
                self.secret_key in {"development-only-change-me", "replace-me"}
                or self.secret_key.startswith("local-development-only")
                or len(self.secret_key) < 32
            ):
                raise ValueError("Production requires a secret key of at least 32 characters")
            if self.debug:
                raise ValueError("Debug must be disabled in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("Production requires PostgreSQL; SQLite is for development only")
            if any(host in {"*", "localhost", "127.0.0.1", "testserver"} for host in self.allowed_hosts):
                raise ValueError("Production allowed hosts must contain only deployed hostnames")
        if self.max_upload_bytes < 1024 or self.max_upload_bytes > 50 * 1024 * 1024:
            raise ValueError("Upload limit must be between 1 KB and 50 MB")
        if not 1 <= self.approved_preview_retention_days <= 30:
            raise ValueError("Preview retention must be between 1 and 30 days")
        if not 1 <= self.ai_hourly_request_limit <= 20:
            raise ValueError("AI hourly request limit must be between 1 and 20")
        if not 5 <= self.ai_cooldown_seconds <= 300:
            raise ValueError("AI cooldown must be between 5 and 300 seconds")
        try:
            self.upload_dir.resolve().relative_to(Path("static").resolve())
        except ValueError:
            pass
        else:
            raise ValueError("Managed uploads cannot be stored inside the public static directory")
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
