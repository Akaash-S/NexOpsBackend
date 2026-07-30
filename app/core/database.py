"""
NexOps Database Engine
Async PostgreSQL connection pool using SQLModel + SQLAlchemy async.
"""

from typing import AsyncGenerator
import logging
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

logger = logging.getLogger("nexops.database")

import ssl as ssl_module

# Build connect_args for asyncpg (SSL handled here, not in URL)
connect_args = {}
if settings.requires_ssl:
    connect_args["ssl"] = True

# Async engine for Neon serverless PostgreSQL with connection pooling
engine = create_async_engine(
    settings.async_database_url,
    echo=False,  # Set to False to keep terminal logs clean and short
    pool_pre_ping=True,
    connect_args=connect_args,
    pool_size=10,  # Maintain 10 connections
    max_overflow=20,  # Allow 20 additional connections under load
    pool_recycle=3600,  # Recycle connections after 1 hour
)

# Session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Create all tables and run DDL schema migrations on startup."""
    try:
        async with engine.begin() as conn:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE repos ADD COLUMN IF NOT EXISTS user_id VARCHAR;"))
            await conn.execute(text("ALTER TABLE repos ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'active';"))
            await conn.execute(text("UPDATE repos SET status = 'active' WHERE status IS NULL;"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS github_last_synced_at TIMESTAMP;"))
            await conn.run_sync(SQLModel.metadata.create_all)
    except Exception as e:
        logger.warning(f"init_db schema check warning: {e}")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection: yields an async DB session per request."""
    async with async_session() as session:
        try:
            yield session
        finally:
            try:
                from sqlalchemy import text
                await session.execute(text("RESET ALL;"))
            except Exception:
                pass
            await session.close()

