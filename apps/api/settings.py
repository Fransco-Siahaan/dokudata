"""API settings from environment variables (prefix ``DOKUDATA_``)."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOKUDATA_", env_file=ROOT / ".env", extra="ignore")

    env: Literal["development", "production", "test"] = "development"
    database_url: str = f"sqlite:///{(ROOT / 'var' / 'dokudata.db').as_posix()}"
    storage: Literal["local", "s3"] = "local"
    storage_dir: Path = ROOT / "var" / "storage"
    s3_endpoint: str | None = None
    s3_bucket: str = "dokudata"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    queue_mode: Literal["inline", "rq"] = "inline"
    redis_url: str = "redis://localhost:6379/0"
    inline_workers: int = 2

    # Signs short-lived download and event URLs. Set it in production; the random default resets on restart.
    secret_key: str = secrets.token_urlsafe(32)
    signed_url_ttl_s: int = 3600
    cors_origins: list[str] = ["http://localhost:5173"]

    max_upload_mb: int = 10
    max_files_per_request: int = 20
    max_pdf_pages: int = 10
    uploads_per_hour_per_ip: int = 120
    documents_per_day_per_session: int = 200
    llm_documents_per_day: int = 50
    retention_hours: int = 24

    default_extractor: Literal["rules", "llm_ocr", "llm_vision"] = "rules"
    allow_llm: bool = True
    # Methods B and C (Claude). The key can come from .env or the environment; without it the
    # SDK still finds an `ant auth login` profile.
    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("DOKUDATA_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    llm_model: str = "claude-opus-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    ocr_engine: str = "rapidocr"
    classifier: str = "tfidf"

    reports_dir: Path = ROOT / "reports"
    samples_dir: Path = ROOT / "apps" / "api" / "samples"

    @property
    def llm_configured(self) -> bool:
        """True when Claude credentials are available (API key, auth token or a saved `ant` profile)."""
        if (
            self.anthropic_api_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        ):
            return True
        config = Path(os.environ.get("ANTHROPIC_CONFIG_DIR", Path.home() / ".config" / "anthropic"))
        return config.is_dir() and any(config.rglob("*.json"))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
