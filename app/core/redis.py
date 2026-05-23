import json
import logging
from typing import Optional, Any
import redis.asyncio as redis
from app.core.config import settings

logger = logging.getLogger("nexops.redis")

# Initialize Redis client using from_url if REDIS_URL is configured
redis_client = None
if settings.REDIS_URL:
    try:
        redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0
        )
        logger.info("Redis client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Redis client: {e}")
        redis_client = None

async def get_cached_data(key: str) -> Optional[Any]:
    """Retrieve data from Redis cache."""
    if not redis_client:
        return None
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Redis cache read failed for key '{key}': {e}")
    return None

async def set_cached_data(key: str, data: Any, ttl: int = 30) -> None:
    """Store data in Redis cache with an optional TTL (in seconds)."""
    if not redis_client:
        return
    try:
        await redis_client.set(key, json.dumps(data), ex=ttl)
    except Exception as e:
        logger.warning(f"Redis cache write failed for key '{key}': {e}")

async def invalidate_cache_pattern(pattern: str) -> None:
    """Invalidate all cache keys matching the given pattern."""
    if not redis_client:
        return
    try:
        keys = await redis_client.keys(pattern)
        if keys:
            await redis_client.delete(*keys)
            logger.info(f"Invalidated {len(keys)} keys matching pattern: {pattern}")
    except Exception as e:
        logger.warning(f"Redis cache invalidation failed for pattern '{pattern}': {e}")
