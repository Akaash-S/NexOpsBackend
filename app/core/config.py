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
    MIGRATION_DATABASE_URL: Optional[str] = None
    STAGING_DATABASE_URL: Optional[str] = None

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

    # PagerDuty Webhook
    # Required for production: if unset, the PagerDuty webhook endpoint rejects all requests.
    PAGERDUTY_WEBHOOK_SECRET: Optional[str] = None

    # GitHub OAuth
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None

    # Frontend URL (for OAuth callbacks and redirects)
    # Must be set to the deployed frontend origin in production (e.g. https://nexops-frontend.vercel.app)
    FRONTEND_URL: str = "http://localhost:3000"

    # Gemini AI
    GEMINI_API_KEY: Optional[str] = None

    # SMTP Email Configuration
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "noreply@nexops.dev"
    SMTP_TLS: bool = True

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

    def to_direct_async_url(self, url: str) -> str:
        """Get direct (non-pooled) async database URL by removing '-pooler' and using asyncpg driver."""
        if "-pooler" in url:
            url = url.replace("-pooler", "", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        url = url.split("?")[0]
        return url

    @property
    def direct_database_url(self) -> str:
        """Get the direct (non-pooled) Neon database URL by removing '-pooler' from the host."""
        url = self.DATABASE_URL
        if "-pooler" in url:
            url = url.replace("-pooler", "", 1)
        return url

    @property
    def direct_async_database_url(self) -> str:
        """Get direct (non-pooled) async database URL for production by removing '-pooler'."""
        return self.to_direct_async_url(self.DATABASE_URL)

    @property
    def direct_async_migration_database_url(self) -> str:
        """Get direct (non-pooled) async database URL for migration branch."""
        if not self.MIGRATION_DATABASE_URL:
            raise ValueError("MIGRATION_DATABASE_URL is not set in environment or .env file")
        return self.to_direct_async_url(self.MIGRATION_DATABASE_URL)

    @property
    def direct_async_staging_database_url(self) -> str:
        """Get direct (non-pooled) async database URL for staging branch."""
        if not self.STAGING_DATABASE_URL:
            raise ValueError("STAGING_DATABASE_URL is not set in environment or .env file")
        return self.to_direct_async_url(self.STAGING_DATABASE_URL)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
