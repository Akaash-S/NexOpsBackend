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
    # Must be set to the deployed frontend origin in production (e.g. https://nexops.asolvitra.tech)
    FRONTEND_URL: str = "https://nexops.asolvitra.tech"

    # Gemini AI
    GEMINI_API_KEY: Optional[str] = None

    # Domain & Email Configuration (Loaded directly from environment variables / .env)
    EMAIL_DOMAIN: Optional[str] = None
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: Optional[str] = None

    # Email Sender Aliases per Channel (Loaded directly from environment variables / .env)
    EMAIL_AUTH_SENDER: Optional[str] = None
    EMAIL_ALERTS_SENDER: Optional[str] = None
    EMAIL_DEPLOYMENTS_SENDER: Optional[str] = None
    EMAIL_TEAM_SENDER: Optional[str] = None
    EMAIL_BILLING_SENDER: Optional[str] = None

    @property
    def domain(self) -> str:
        return self.EMAIL_DOMAIN or "asolvitra.tech"

    @property
    def resend_from_email(self) -> str:
        return self.RESEND_FROM_EMAIL or "NexOps <onboarding@resend.dev>"

    @property
    def auth_sender(self) -> str:
        return self.EMAIL_AUTH_SENDER or f"NexOps Auth <nexops-auth@{self.domain}>"

    @property
    def alerts_sender(self) -> str:
        return self.EMAIL_ALERTS_SENDER or f"NexOps Alerts <nexops-alerts@{self.domain}>"

    @property
    def deployments_sender(self) -> str:
        return self.EMAIL_DEPLOYMENTS_SENDER or f"NexOps Deployments <nexops-deployments@{self.domain}>"

    @property
    def team_sender(self) -> str:
        return self.EMAIL_TEAM_SENDER or f"NexOps Team <nexops-team@{self.domain}>"

    @property
    def billing_sender(self) -> str:
        return self.EMAIL_BILLING_SENDER or f"NexOps Billing <nexops-billing@{self.domain}>"

    # SMTP Email Configuration
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "noreply@asolvitra.tech"
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
