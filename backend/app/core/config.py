"""Application settings, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration lives here. Nothing sensitive is hard-coded."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+psycopg://docint:docint@localhost:5432/docint"
    redis_url: str = "redis://localhost:6379/0"
    celery_eager: bool = False  # run tasks inline (tests / no-Redis demos)
    stalled_after_minutes: float = 15.0  # documents with no progress for this long are re-queued
    requeue_interval_seconds: int = 300  # how often the reaper runs (Celery beat)

    # --- storage and upload limits ---
    storage_dir: Path = Path("./storage")
    max_upload_mb: int = 200
    max_files_per_request: int = 20
    max_pages_per_document: int = 3000
    max_image_pixels: int = 60_000_000
    max_sheet_rows: int = 200_000
    max_zip_uncompressed_mb: int = 600

    # --- auth ---
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    admin_email: str | None = None
    admin_password: str | None = None
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- rate limiting ---
    rate_limit_per_minute: int = 240
    login_rate_limit_per_minute: int = 10

    # --- OCR ---
    ocr_engine: Literal["tesseract"] = "tesseract"
    ocr_lang: str = "eng"
    ocr_dpi: int = 200
    ocr_deskew: bool = True
    ocr_denoise: bool = False
    ocr_binarize: bool = False
    scanned_text_threshold: int = 25  # fewer chars than this => page treated as scanned

    # --- AI ---
    llm_provider: Literal["heuristic", "gemini"] = "heuristic"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"  # verify current free-tier model names in AI Studio
    llm_timeout_seconds: float = 60.0
    llm_requests_per_minute: int = 10
    llm_pages_per_call: int = 6
    prompt_version: str = "v1"
    embedder: Literal["hashing", "sentence-transformers"] = "hashing"
    embedding_dim: int = 384
    review_confidence_threshold: float = 0.75

    # --- validation tolerances ---
    amount_tolerance: str = "0.01"

    @model_validator(mode="after")
    def _check_secrets(self) -> Settings:
        if not self.jwt_secret:
            if self.app_env == "production":
                raise ValueError("JWT_SECRET must be set in production")
            # Development/test: a random per-process secret (tokens die on restart).
            self.jwt_secret = secrets.token_urlsafe(48)
        elif self.app_env == "production" and len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters in production")
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
