"""
Event Service
Handles event ingestion and triggers the automation engine.
"""

import logging
from typing import Optional, List
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.schemas.event_schema import EventCreate

logger = logging.getLogger("nexops.events")


async def create_event(session: AsyncSession, data: EventCreate) -> Event:
    """
    Create and store a new event.
    NOTE: This does NOT trigger automation — that is handled in the route layer
    via BackgroundTasks so the API response is instant.
    """
    event = Event(
        type=data.type,
        repo_id=data.repo_id,
        source=data.source,
        payload=data.payload,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    logger.info(f"Event created: {event.type} (repo: {event.repo_id})")
    return event


async def get_events(
    session: AsyncSession,
    repo_id: Optional[str] = None,
    event_type: Optional[str] = None,
    processed: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Event]:
    """Fetch events with optional filtering."""
    query = select(Event)
    if repo_id:
        query = query.where(Event.repo_id == repo_id)
    if event_type:
        query = query.where(Event.type == event_type)
    if processed is not None:
        query = query.where(Event.processed == processed)
    query = query.order_by(Event.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_event_by_id(session: AsyncSession, event_id: str) -> Optional[Event]:
    """Fetch a single event by ID."""
    return await session.get(Event, event_id)
