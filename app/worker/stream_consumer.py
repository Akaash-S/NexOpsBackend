"""
Redis Streams Consumer Worker
Consumes events from 'nexops:events' stream, processes them, and handles retries/dead-letter queue.
"""
import asyncio
import logging
import os
import socket
import sys
from sqlalchemy import text
from sqlmodel import select

# Set up logging before any app imports to capture early logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("nexops.worker")

# Ensure proper event loop policy on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.core.config import settings
from app.core.redis import redis_client, init_redis
from app.core.database import async_session, init_db
from app.models.event import Event
from app.services.automation_service import process_event

STREAM_NAME = "nexops:events"
GROUP_NAME = "nexops-workers"
DEAD_LETTER_STREAM = "nexops:events:dead"
CONSUMER_NAME = f"consumer-{socket.gethostname()}-{os.getpid()}"
MAX_RETRIES = 3

async def init_consumer_group():
    """Create consumer group if it doesn't already exist."""
    if not redis_client:
        logger.error("Redis client is not initialized.")
        return False
    try:
        # Create group, MKSTREAM creates the stream if it doesn't exist
        await redis_client.xgroup_create(STREAM_NAME, GROUP_NAME, id="0", mkstream=True)
        logger.info(f"Consumer group {GROUP_NAME} created for stream {STREAM_NAME}.")
    except Exception as e:
        # If it already exists, Redis raises an error which we can ignore
        if "BUSYGROUP" in str(e):
            logger.info(f"Consumer group {GROUP_NAME} already exists.")
        else:
            logger.error(f"Failed to create consumer group: {e}")
            return False
    return True

async def handle_message(msg_id: str, fields: dict):
    """Process a single stream message with retry logic and dead-letter queue."""
    event_id = fields.get("event_id")
    workspace_id = fields.get("workspace_id")
    retry_count = int(fields.get("retry_count", 0))

    if not event_id or not workspace_id:
        logger.warning(f"Malformed message {msg_id}: event_id/workspace_id missing. Acking and skipping.")
        await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    logger.info(f"Processing event {event_id} (workspace: {workspace_id}, attempt: {retry_count + 1})")

    try:
        async with async_session() as session:
            # 1. Set GUC to scope the DB session to this workspace
            await session.execute(
                text("SELECT set_config('nexops.current_workspace_id', :workspace_id, false)"),
                {"workspace_id": workspace_id}
            )

            # 2. Fetch the event
            result = await session.execute(select(Event).where(Event.id == event_id))
            event = result.scalars().first()

            if not event:
                logger.warning(f"Event {event_id} not found in DB. Acking and skipping.")
                await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
                return

            # Test Hook: Deliberately trigger processing error for validation
            if event.payload and event.payload.get("trigger_worker_error"):
                raise ValueError("Deliberate worker processing failure triggered for testing")

            # 3. Process the event via the intelligence engine
            await process_event(session, event)

        # 4. Success -> Ack message
        await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
        logger.info(f"Successfully processed and acked event {event_id}")

    except Exception as err:
        logger.error(f"Error processing event {event_id}: {err}", exc_info=True)
        
        # 5. Retry/Dead-letter logic
        next_retry = retry_count + 1
        if next_retry >= MAX_RETRIES:
            logger.error(f"Event {event_id} failed after {MAX_RETRIES} attempts. Moving to dead-letter queue.")
            try:
                # Add to dead-letter stream
                await redis_client.xadd(
                    DEAD_LETTER_STREAM,
                    {
                        "event_id": event_id,
                        "workspace_id": workspace_id,
                        "error": str(err),
                        "retry_count": str(next_retry),
                        "failed_at": str(asyncio.get_event_loop().time())
                    }
                )
                # Ack the original message so it doesn't block
                await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
                logger.info(f"Event {event_id} successfully dead-lettered.")
            except Exception as dl_err:
                logger.critical(f"Failed to dead-letter event {event_id}: {dl_err}")
        else:
            logger.info(f"Re-queueing event {event_id} for retry {next_retry}")
            try:
                # Re-queue event with incremented retry count
                await redis_client.xadd(
                    STREAM_NAME,
                    {
                        "event_id": event_id,
                        "workspace_id": workspace_id,
                        "retry_count": str(next_retry)
                    }
                )
                # Ack the current message since the new one is queued
                await redis_client.xack(STREAM_NAME, GROUP_NAME, msg_id)
            except Exception as rq_err:
                logger.critical(f"Failed to re-queue event {event_id}: {rq_err}")

async def run_consumer():
    """Main consumer loop."""
    logger.info("Initializing stream consumer...")
    await init_redis()
    
    if not redis_client:
        logger.critical("Failed to connect to Redis. Worker exiting.")
        return

    # Verify consumer group exists
    if not await init_consumer_group():
        logger.critical("Failed to initialize consumer group. Worker exiting.")
        return

    # Verify database is initialized
    await init_db()

    logger.info(f"Worker connected and listening on stream '{STREAM_NAME}' as consumer '{CONSUMER_NAME}'...")

    while True:
        try:
            # Read new messages from the stream
            # '>' reads messages that have never been delivered to other consumers
            response = await redis_client.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"},
                count=10,
                block=2000
            )

            if not response:
                continue

            for stream_name, messages in response:
                for msg_id, fields in messages:
                    await handle_message(msg_id, fields)

        except asyncio.CancelledError:
            logger.info("Worker consumer shutdown requested.")
            break
        except Exception as e:
            if "NOGROUP" in str(e):
                logger.warning("Consumer group missing (NOGROUP). Re-initializing consumer group...")
                await init_consumer_group()
            else:
                logger.error(f"Error in consumer loop: {e}")
            await asyncio.sleep(2)  # Cool down on unexpected errors

if __name__ == "__main__":
    try:
        asyncio.run(run_consumer())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
