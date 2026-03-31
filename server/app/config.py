"""Application configuration for the simulation backend."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = Field(default="Autonomous Village Server")
    app_env: str = Field(default="development")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    tick_interval_seconds: float = Field(default=1.0, gt=0.0)
    world_width: int = Field(default=16, ge=4)
    world_height: int = Field(default=12, ge=4)
    initial_agent_count: int = Field(default=3, ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for app startup and DI."""

    return Settings()
