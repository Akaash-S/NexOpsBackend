"""
Queue Service
Enqueues events into the Redis Stream for asynchronous processing.
"""
import logging
from app.core.redis import redis_client
from app.core.config import settings

logger = logging.getLogger("nexops.queue")

STREAM_NAME = "nexops:events"

async def enqueue_event(event_id: str, workspace_id: str) -> bool:
    """
    Push event_id and workspace_id into Redis Stream.
    Falls back to synchronous background processing if Redis is unavailable.
    """
    if not redis_client:
        logger.warning("Redis client is not available. Queue fallback triggered.")
        return False

    try:
        # Push message to Redis Stream
        await redis_client.xadd(
            STREAM_NAME,
            {"event_id": event_id, "workspace_id": workspace_id, "retry_count": "0"}
        )
        logger.info(f"Successfully enqueued event {event_id} for workspace {workspace_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to enqueue event {event_id} to Redis Stream: {e}")
        return False
