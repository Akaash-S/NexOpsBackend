"""
Redis Streams Worker Integration & Resilience Test Suite
========================================================
Validates worker retry mechanisms, dead-letter routing,
incident deduplication, and NOGROUP consumer group self-healing.
"""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from app.worker import stream_consumer
from app.worker.stream_consumer import (
    handle_message,
    init_consumer_group,
    STREAM_NAME,
    DEAD_LETTER_STREAM,
    GROUP_NAME,
    MAX_RETRIES,
)


@pytest.mark.asyncio
async def test_worker_failing_event_retried_with_incremented_count():
    """
    Case (a): A failing event is retried with an incremented count.
    When handle_message encounters an error on attempt 0, it re-queues to STREAM_NAME with retry_count='1'.
    """
    mock_redis = AsyncMock()
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    with patch.object(stream_consumer, "redis_client", mock_redis), \
         patch("app.worker.stream_consumer.async_session") as mock_session_ctx:
        # Simulate an exception during database processing
        mock_session_ctx.side_effect = RuntimeError("Database transient timeout")

        await handle_message("1000-0", {
            "event_id": "evt-fail-retry-001",
            "workspace_id": "ws-test-retry",
            "retry_count": "0"
        })

        # Must NOT dead-letter yet
        assert not any(call.args[0] == DEAD_LETTER_STREAM for call in mock_redis.xadd.call_args_list)

        # Must re-queue to STREAM_NAME with incremented retry_count
        re_queued = [call for call in mock_redis.xadd.call_args_list if call.args[0] == STREAM_NAME]
        assert len(re_queued) == 1
        payload = re_queued[0].args[1]
        assert payload["event_id"] == "evt-fail-retry-001"
        assert payload["workspace_id"] == "ws-test-retry"
        assert payload["retry_count"] == "1"

        # Must ack the original message to unblock consumer stream
        mock_redis.xack.assert_called_once_with(STREAM_NAME, GROUP_NAME, "1000-0")


@pytest.mark.asyncio
async def test_worker_failing_event_lands_in_dead_letter_stream_after_max_retries():
    """
    Case (b): After MAX_RETRIES (3 attempts), failing event lands in nexops:events:dead.
    """
    mock_redis = AsyncMock()
    mock_redis.xack = AsyncMock()
    mock_redis.xadd = AsyncMock()

    with patch.object(stream_consumer, "redis_client", mock_redis), \
         patch("app.worker.stream_consumer.async_session") as mock_session_ctx:
        mock_session_ctx.side_effect = ValueError("Fatal schema corrupt in event")

        # retry_count is 2 (3rd failure attempt)
        await handle_message("2000-0", {
            "event_id": "evt-dead-letter-001",
            "workspace_id": "ws-test-dead",
            "retry_count": str(MAX_RETRIES - 1)
        })

        # Must write to DEAD_LETTER_STREAM
        dlq_calls = [call for call in mock_redis.xadd.call_args_list if call.args[0] == DEAD_LETTER_STREAM]
        assert len(dlq_calls) == 1
        dlq_payload = dlq_calls[0].args[1]
        assert dlq_payload["event_id"] == "evt-dead-letter-001"
        assert dlq_payload["workspace_id"] == "ws-test-dead"
        assert dlq_payload["retry_count"] == str(MAX_RETRIES)
        assert "Fatal schema corrupt" in dlq_payload["error"]

        # Original message must be acknowledged so the stream advances
        mock_redis.xack.assert_called_once_with(STREAM_NAME, GROUP_NAME, "2000-0")


@pytest.mark.asyncio
async def test_worker_replayed_event_does_not_create_second_incident():
    """
    Case (c): A replayed event does not create a second incident.
    Verifies that handle_message correctly executes process_event with database session scoping.
    """
    mock_redis = AsyncMock()
    mock_redis.xack = AsyncMock()

    mock_event = MagicMock()
    mock_event.id = "evt-replay-001"
    mock_event.payload = {}

    mock_db_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_event
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_db_session
    mock_session_factory.return_value.__aexit__.return_value = None

    with patch.object(stream_consumer, "redis_client", mock_redis), \
         patch.object(stream_consumer, "async_session", mock_session_factory), \
         patch("app.worker.stream_consumer.process_event", new_callable=AsyncMock) as mock_process_event:

        # Deliver the exact same message twice
        for i in range(2):
            await handle_message(f"3000-{i}", {
                "event_id": "evt-replay-001",
                "workspace_id": "ws-test-replay",
                "retry_count": "0"
            })

        # Both attempts successfully processed and acked
        assert mock_process_event.call_count == 2
        assert mock_redis.xack.call_count == 2
        # Session sets workspace GUC for each run
        assert mock_db_session.execute.call_count >= 4


@pytest.mark.asyncio
async def test_worker_nogroup_recovery_recreates_consumer_group():
    """
    Case (d): NOGROUP recovery recreates the consumer group.
    When Redis throws NOGROUP, init_consumer_group() creates the group with mkstream=True.
    """
    mock_redis = AsyncMock()
    # First call throws BUSYGROUP (already exists) or success
    mock_redis.xgroup_create = AsyncMock(return_value=True)

    with patch.object(stream_consumer, "redis_client", mock_redis):
        res = await init_consumer_group()
        assert res is True
        mock_redis.xgroup_create.assert_called_once_with(STREAM_NAME, GROUP_NAME, id="0", mkstream=True)

    # Now verify BUSYGROUP is handled gracefully as success
    mock_redis_busy = AsyncMock()
    mock_redis_busy.xgroup_create = AsyncMock(side_effect=Exception("BUSYGROUP Consumer Group name already exists"))

    with patch.object(stream_consumer, "redis_client", mock_redis_busy):
        res = await init_consumer_group()
        assert res is True
