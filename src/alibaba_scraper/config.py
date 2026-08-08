# src/alibaba_scraper/config.py
"""Application configuration."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_prefix="ALIBABA_SCRAPER_",
        env_file=".env",
        extra="ignore",
    )

    timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    requests_per_second: float = Field(default=0.5, gt=0.0, le=10.0)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    database_path: Path = Path("data/alibaba.sqlite3")
    user_agent: str = "AlibabaScraper/0.2 (+public-data-research)"
