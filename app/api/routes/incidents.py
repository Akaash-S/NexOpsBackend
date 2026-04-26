from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import List, Optional

from app.core.database import get_session
from app.core.security import get_current_user
from app.models.incident import Incident
from app.schemas.incident_schema import IncidentResponse, IncidentCreate

router = APIRouter(prefix="/incidents", tags=["Incidents"])

@router.get("", response_model=List[IncidentResponse])
async def list_incidents(
    status: Optional[str] = Query(None),
    cluster_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    query = select(Incident)
    if status:
        query = query.where(Incident.status == status)
    if cluster_id:
        query = query.where(Incident.cluster_id == cluster_id)
    query = query.order_by(Incident.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())

@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: str,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    incident = await session.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident

@router.patch("/{incident_id}/resolve", response_model=IncidentResponse)
async def resolve_incident(
    incident_id: str,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    from app.services.incident_service import resolve_incident as resolve_logic
    incident = await resolve_logic(session, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident
