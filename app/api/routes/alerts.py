"""
Alert Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.core.database import get_session
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.alert_schema import AlertCreate, AlertUpdate, AlertResponse
from app.services import alert_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("/counts")
async def alert_counts(
    repo_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Get alert counts grouped by severity, scoped to current user."""
    return await alert_service.get_alert_counts(session, user_id=user.id, repo_id=repo_id)


@router.get("", response_model=List[AlertResponse])
async def list_alerts(
    repo_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None, pattern="^(low|medium|high|critical)$"),
    resolved: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List alerts with optional filtering, scoped to current user."""
    return await alert_service.get_alerts(
        session,
        user_id=user.id,
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
    user: User = Depends(get_current_user),
):
    """Manually create an alert (bypass automation engine), scoped to current user."""
    try:
        return await alert_service.create_alert(session, data, user_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/{alert_id}/resolve", response_model=AlertResponse)
async def resolve_alert(
    alert_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Resolve an alert, scoped to current user."""
    alert = await alert_service.resolve_alert(session, alert_id, user_id=user.id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.patch("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Acknowledge an alert without resolving it, scoped to current user."""
    alert = await alert_service.acknowledge_alert(session, alert_id, user_id=user.id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert
