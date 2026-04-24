"""
Event Routes
Ingestion and query endpoints for system events.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.core.database import get_session
from app.schemas.event_schema import EventCreate, EventResponse
from app.services import event_service
from app.services.automation_service import process_event

router = APIRouter(prefix="/events", tags=["Events"])


async def _run_automation(event_id: str):
    """Background task to process events without blocking the ingestion response."""
    from app.core.database import async_session
    async with async_session() as session:
        event = await event_service.get_event_by_id(session, event_id)
        if event:
            await process_event(session, event)


@router.post("", response_model=EventResponse, status_code=201)
async def create_event(
    data: EventCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Ingest a new system event (webhook simulation).
    Triggers the automation engine in a background task.
    """
    try:
        event = await event_service.create_event(session, data)

        # Fire-and-forget: trigger automation engine in background
        background_tasks.add_task(_run_automation, event.id)

        return EventResponse.model_validate(event)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
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
    return [EventResponse.model_validate(e) for e in events]
