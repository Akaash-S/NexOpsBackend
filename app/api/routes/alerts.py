"""
Alert Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.core.database import get_session
from app.schemas.alert_schema import AlertCreate, AlertUpdate, AlertResponse
from app.services import alert_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("/counts")
async def alert_counts(
    repo_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """Get alert counts grouped by severity."""
    return await alert_service.get_alert_counts(session, repo_id=repo_id)


@router.get("", response_model=List[AlertResponse])
async def list_alerts(
    repo_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None, pattern="^(low|medium|high|critical)$"),
    resolved: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List alerts with optional filtering."""
    return await alert_service.get_alerts(
        session,
        repo_id=repo_id,
        severity=severity,
        resolved=resolved,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=AlertResponse, status_code=201)
async def create_alert(
    data: AlertCreate,
    session: AsyncSession = Depends(get_session),
):
    """Manually create an alert (bypass automation engine)."""
    return await alert_service.create_alert(session, data)


@router.patch("/{alert_id}/resolve", response_model=AlertResponse)
async def resolve_alert(
    alert_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Resolve an alert."""
    alert = await alert_service.resolve_alert(session, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.patch("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Acknowledge an alert without resolving it."""
    alert = await alert_service.acknowledge_alert(session, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert
