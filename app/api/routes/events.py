"""
Event Routes — The Core Ingestion API
POST /events is the primary entry point for all system state changes.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.core.database import get_session, async_session
from app.schemas.event_schema import EventCreate, EventResponse
from app.services import event_service
from app.services.automation_service import process_event

router = APIRouter(prefix="/events", tags=["Events"])


async def _run_automation(event_id: str):
    """
    Background task: runs the automation engine in a separate DB session.
    This ensures the API response (201) is instant while processing happens async.
    """
    async with async_session() as session:
        event = await event_service.get_event_by_id(session, event_id)
        if event and not event.processed:
            await process_event(session, event)


@router.post("", response_model=EventResponse, status_code=201)
async def create_event(
    data: EventCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Ingest a new event into the system.
    
    The event is stored immediately and the automation engine is triggered
    as a background task. The API returns the event instantly.
    
    Example body:
    ```json
    {
        "type": "ci.failed",
        "repo_id": "uuid-here",
        "metadata": { "branch": "main", "commit": "abc123" }
    }
    ```
    """
    try:
        # Verify repo exists
        from app.services.repo_service import get_repo_by_id
        repo = await get_repo_by_id(session, data.repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail=f"Repository '{data.repo_id}' not found")

        event = await event_service.create_event(session, data)

        # Fire-and-forget: trigger automation engine in background
        background_tasks.add_task(_run_automation, event.id)

        # Manual mapping to avoid SQLAlchemy .metadata collision
        return EventResponse(
            id=event.id,
            type=event.type,
            repo_id=event.repo_id,
            source=event.source,
            event_data=event.payload,
            processed=event.processed,
            created_at=event.created_at,
        )
    except Exception as e:
        import logging
        logging.getLogger("nexops.api").error(f"Error creating event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[EventResponse])
async def list_events(
    repo_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    processed: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List events with optional filtering."""
    events = await event_service.get_events(
        session,
        repo_id=repo_id,
        event_type=type,
        processed=processed,
        limit=limit,
        offset=offset,
    )
    return [
        EventResponse(
            id=e.id,
            type=e.type,
            repo_id=e.repo_id,
            source=e.source,
            event_data=e.payload,
            processed=e.processed,
            created_at=e.created_at,
        )
        for e in events
    ]
