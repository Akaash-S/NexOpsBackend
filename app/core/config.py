"""
NexOps Core Configuration
Centralized settings using pydantic-settings for type-safe environment variable loading.
"""

from pydantic_settings import BaseSettings
from typing import List, Optional
import json


class Settings(BaseSettings):
    # App
    APP_NAME: str
    APP_ENV: str
    DEBUG: bool
    API_PREFIX: str

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str

    # CORS
    CORS_ORIGINS: str

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS regardless of format — JSON array or comma-separated."""
        v = self.CORS_ORIGINS.strip()
        if v.startswith("["):
            return json.loads(v)
        return [o.strip() for o in v.split(",") if o.strip()]

    # Firebase
    FIREBASE_SERVICE_ACCOUNT_PATH: str

    # Encryption (Fernet)
    ENCRYPTION_KEY: str

    # GitHub Webhook
    GITHUB_WEBHOOK_SECRET: str

    # GitHub OAuth
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None

    # Gemini AI
    GEMINI_API_KEY: Optional[str] = None

    @property
    def async_database_url(self) -> str:
        """Convert standard postgresql:// URL to asyncpg driver URL.
        Strips query params (sslmode, channel_binding, etc.) that asyncpg
        doesn't accept as URL parameters — SSL is handled via connect_args.
        """
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        # Strip all query parameters — asyncpg chokes on libpq-specific ones
        url = url.split("?")[0]
        return url

    @property
    def requires_ssl(self) -> bool:
        """Check if the original DATABASE_URL requests SSL."""
        return "sslmode=" in self.DATABASE_URL or "ssl=" in self.DATABASE_URL

    @property
    def sync_database_url(self) -> str:
        """Ensure standard postgresql:// prefix for sync operations."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql://", 1)
        return url

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
