"""
NexOps Core Configuration
Centralized settings using pydantic-settings for type-safe environment variable loading.
"""

from pydantic_settings import BaseSettings
from typing import List, Optional
import json


class Settings(BaseSettings):
    # App
    APP_NAME: str = "NexOps"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    # Database — single Neon PostgreSQL URL
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/nexops"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # CORS — stored as plain string, parsed in the property below
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS regardless of format — JSON array or comma-separated."""
        v = self.CORS_ORIGINS.strip()
        if v.startswith("["):
            return json.loads(v)
        return [o.strip() for o in v.split(",") if o.strip()]

    # Firebase
    FIREBASE_SERVICE_ACCOUNT_PATH: str = "service-account.json"

    # Encryption (Fernet)
    ENCRYPTION_KEY: str = "_quTgtR0C6NufNi80kDfQ75-k_N1_1LzwScpDSdSRcM="

    # GitHub Webhook
    GITHUB_WEBHOOK_SECRET: Optional[str] = None

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
