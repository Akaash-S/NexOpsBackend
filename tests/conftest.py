"""
Pytest global configuration and fixtures.
Ensures session/test event loop safety and connection pool cleanup across async tests.
"""

import asyncio
import pytest
from app.core.database import engine
from app.core import redis as app_redis


@pytest.fixture(autouse=True)
async def dispose_connection_pools():
    """Dispose SQLAlchemy engine and Redis connection pools after every test to prevent loop leaks."""
    yield
    await engine.dispose()
    if app_redis.redis_client:
        try:
            await app_redis.redis_client.aclose()
        except Exception:
            pass
