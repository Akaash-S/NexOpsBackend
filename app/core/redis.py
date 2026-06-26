import json
import logging
import asyncio
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
            socket_timeout=0.5,
            socket_connect_timeout=0.5
        )
        logger.info("Redis client initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Redis client: {e}")
        redis_client = None

_in_memory_cache = {}
_use_in_memory = False

async def init_redis() -> None:
    """Verify Redis connection at startup to failover immediately if down."""
    global _use_in_memory
    if not redis_client:
        _use_in_memory = True
        return
    try:
        await asyncio.wait_for(redis_client.ping(), timeout=0.5)
        logger.info("Redis connection verified successfully.")
    except Exception as e:
        logger.warning(f"Redis ping failed at startup ({e}). Switching to in-memory fallback cache.")
        _use_in_memory = True

async def get_cached_data(key: str) -> Optional[Any]:
    """Retrieve data from Redis cache, falling back to in-memory if Redis is down."""
    global _use_in_memory
    if _use_in_memory or not redis_client:
        return _in_memory_cache.get(key)
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Redis cache read failed for key '{key}' (switching to in-memory): {e}")
        _use_in_memory = True
        return _in_memory_cache.get(key)
    return None

async def set_cached_data(key: str, data: Any, ttl: int = 30) -> None:
    """Store data in Redis cache with an optional TTL, falling back to in-memory if Redis is down."""
    global _use_in_memory
    if _use_in_memory or not redis_client:
        _in_memory_cache[key] = data
        return
    try:
        await redis_client.set(key, json.dumps(data), ex=ttl)
    except Exception as e:
        logger.warning(f"Redis cache write failed for key '{key}' (switching to in-memory): {e}")
        _use_in_memory = True
        _in_memory_cache[key] = data

async def invalidate_cache_pattern(pattern: str) -> None:
    """Invalidate all cache keys matching the given pattern."""
    global _use_in_memory
    
    # Invalidate in-memory cache keys matching the pattern
    import fnmatch
    keys_to_del = [k for k in _in_memory_cache if fnmatch.fnmatch(k, pattern)]
    for k in keys_to_del:
        try:
            del _in_memory_cache[k]
        except KeyError:
            pass

    if _use_in_memory or not redis_client:
        return
    try:
        keys = await redis_client.keys(pattern)
        if keys:
            await redis_client.delete(*keys)
            logger.info(f"Invalidated {len(keys)} keys matching pattern: {pattern}")
    except Exception as e:
        logger.warning(f"Redis cache invalidation failed for pattern '{pattern}' (switching to in-memory): {e}")
        _use_in_memory = True
