from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.core.database import get_session
from app.core.security import get_current_user
from app.models.incident import Incident
from app.models.repo import Repo
from app.models.candidate_cause import CandidateCause
from app.schemas.incident_schema import IncidentResponse, IncidentCreate

router = APIRouter(prefix="/incidents", tags=["Incidents"])

class FeedbackRequest(BaseModel):
    candidate_cause_id: str = Field(alias="candidateCauseId")
    confirmed: Optional[bool] = None

    class Config:
        validate_by_name = True


@router.get("", response_model=List[IncidentResponse])
async def list_incidents(
    status: Optional[str] = Query(None),
    cluster_id: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    query = select(Incident).where(Incident.workspace_id == user.workspace_id)
    if status:
        query = query.where(Incident.status == status)
    if cluster_id:
        query = query.where(Incident.cluster_id == cluster_id)
    query = query.order_by(Incident.created_at.desc())
    result = await session.execute(query)
    incidents = list(result.scalars().all())

    response_incidents = []
    if incidents:
        # Load all candidate causes for these incidents in one query
        incident_ids = [inc.id for inc in incidents]
        cc_result = await session.execute(
            select(CandidateCause).where(CandidateCause.incident_id.in_(incident_ids))
        )
        causes = list(cc_result.scalars().all())
        
        # Group by incident_id
        from collections import defaultdict
        causes_by_incident = defaultdict(list)
        for cause in causes:
            causes_by_incident[cause.incident_id].append(cause)
            
        for inc in incidents:
            inc_dict = inc.model_dump()
            inc_dict["candidate_causes"] = causes_by_incident[inc.id]
            response_incidents.append(inc_dict)
    else:
        for inc in incidents:
            response_incidents.append(inc.model_dump())

    return response_incidents


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: str,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    # Verify ownership
    incident_result = await session.execute(
        select(Incident)
        .where(Incident.id == incident_id, Incident.workspace_id == user.workspace_id)
    )
    incident = incident_result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    cc_result = await session.execute(
        select(CandidateCause).where(CandidateCause.incident_id == incident.id)
    )
    resp_data = incident.model_dump()
    resp_data["candidate_causes"] = list(cc_result.scalars().all())
    return resp_data


@router.patch("/{incident_id}/resolve", response_model=IncidentResponse)
async def resolve_incident(
    incident_id: str,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    # Verify ownership
    incident_result = await session.execute(
        select(Incident)
        .where(Incident.id == incident_id, Incident.workspace_id == user.workspace_id)
    )
    incident = incident_result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    from app.services.incident_service import resolve_incident as resolve_logic
    incident = await resolve_logic(session, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    cc_result = await session.execute(
        select(CandidateCause).where(CandidateCause.incident_id == incident.id)
    )
    resp_data = incident.model_dump()
    resp_data["candidate_causes"] = list(cc_result.scalars().all())
    return resp_data


@router.post("/{incident_id}/feedback", response_model=IncidentResponse)
@router.patch("/{incident_id}/feedback", response_model=IncidentResponse)
async def submit_feedback(
    incident_id: str,
    feedback: FeedbackRequest,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    # 1. Fetch incident and verify ownership
    incident_result = await session.execute(
        select(Incident)
        .where(Incident.id == incident_id, Incident.workspace_id == user.workspace_id)
    )
    incident = incident_result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
        
    # 2. Fetch candidate cause
    cc_result = await session.execute(
        select(CandidateCause).where(
            CandidateCause.id == feedback.candidate_cause_id,
            CandidateCause.incident_id == incident_id
        )
    )
    target_cause = cc_result.scalar_one_or_none()
    if not target_cause:
        raise HTTPException(status_code=404, detail="Candidate cause not found for this incident")
        
    # 3. Update confirmation state
    target_cause.confirmed = feedback.confirmed
    target_cause.confirmed_by = user.id
    target_cause.updated_at = datetime.utcnow()
    session.add(target_cause)
    
    # If confirmed is True, reject all other causes for this incident
    if feedback.confirmed is True:
        others_result = await session.execute(
            select(CandidateCause).where(
                CandidateCause.incident_id == incident_id,
                CandidateCause.id != feedback.candidate_cause_id
            )
        )
        for other in others_result.scalars().all():
            other.confirmed = False
            other.confirmed_by = user.id
            other.updated_at = datetime.utcnow()
            session.add(other)
            
        # Update incident root cause repo ID
        incident.root_cause_repo_id = target_cause.repo_id
        session.add(incident)
    elif feedback.confirmed is False:
        # If this was marked as confirmed root cause, clear it
        if incident.root_cause_repo_id == target_cause.repo_id:
            incident.root_cause_repo_id = None
            session.add(incident)
            
    await session.commit()
    await session.refresh(incident)
    
    # 4. Attach updated causes list
    cc_all = await session.execute(
        select(CandidateCause).where(CandidateCause.incident_id == incident_id)
    )
    
    # Invalidate cache
    from app.core.redis import invalidate_cache_pattern
    try:
        await invalidate_cache_pattern("cache:dashboard:*")
    except Exception as cache_err:
        pass
        
    resp_data = incident.model_dump()
    resp_data["candidate_causes"] = list(cc_all.scalars().all())
    return resp_data
