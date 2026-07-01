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


async def create_event(session: AsyncSession, data: EventCreate, user_id: Optional[str] = None) -> Event:
    """
    Create and store a new event.
    NOTE: This does NOT trigger automation — that is handled in the route layer
    via BackgroundTasks so the API response is instant.
    """
    if not data.repo_id:
        raise ValueError("repo_id is required to create an event")
        
    if user_id:
        from app.models.repo import Repo
        repo = await session.get(Repo, data.repo_id)
        if not repo or repo.user_id != user_id:
            raise ValueError("Repository not found or access denied")

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
    user_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    event_type: Optional[str] = None,
    processed: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Event]:
    """Fetch events with optional filtering, optionally scoped to a user's repositories."""
    query = select(Event)
    if user_id:
        from app.models.repo import Repo
        query = query.join(Repo, Event.repo_id == Repo.id).where(Repo.user_id == user_id)
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
