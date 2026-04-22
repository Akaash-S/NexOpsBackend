"""
NexOps Database Engine
Async PostgreSQL connection pool using SQLModel + SQLAlchemy async.
"""

from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

import ssl as ssl_module

# Build connect_args for asyncpg (SSL handled here, not in URL)
connect_args = {}
if settings.requires_ssl:
    connect_args["ssl"] = True

from sqlalchemy.pool import NullPool

# Async engine for Neon serverless PostgreSQL
engine = create_async_engine(
    settings.async_database_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    connect_args=connect_args,
    poolclass=NullPool,
)

# Session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncSession:
    """Dependency injection: yields an async DB session per request."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
