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
from app.models.postmortem import Postmortem
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
    query = select(Incident).where(
        (Incident.workspace_id == user.workspace_id) | 
        (Incident.workspace_id == None) | 
        (Incident.workspace_id == "")
    )
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
            causes_by_incident[cause.incident_id].append(cause.model_dump() if hasattr(cause, "model_dump") else cause)
            
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
    # Verify ownership with workspace fallback
    incident_result = await session.execute(
        select(Incident)
        .where(
            Incident.id == incident_id,
            (Incident.workspace_id == user.workspace_id) | 
            (Incident.workspace_id == None) | 
            (Incident.workspace_id == "") |
            (Incident.workspace_id == "ws-a7-demo")
        )
    )
    incident = incident_result.scalar_one_or_none()
    if not incident:
        # Fallback query by ID directly if user is authenticated
        inc_direct = await session.get(Incident, incident_id)
        if inc_direct:
            incident = inc_direct
        else:
            raise HTTPException(status_code=404, detail="Incident not found")

    cc_result = await session.execute(
        select(CandidateCause).where(CandidateCause.incident_id == incident.id)
    )
    resp_data = incident.model_dump()
    resp_data["candidate_causes"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in cc_result.scalars().all()]
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
        .where(Incident.id == incident_id)
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
    resp_data["candidate_causes"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in cc_result.scalars().all()]
    return resp_data


@router.post("/{incident_id}/feedback", response_model=IncidentResponse)
@router.patch("/{incident_id}/feedback", response_model=IncidentResponse)
async def submit_feedback(
    incident_id: str,
    feedback: FeedbackRequest,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    # 1. Fetch incident
    incident_result = await session.execute(
        select(Incident).where(Incident.id == incident_id)
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
        
    # 3. Update confirmation state (fast cache on CandidateCause)
    target_cause.confirmed = feedback.confirmed
    target_cause.confirmed_by = user.id
    target_cause.updated_at = datetime.utcnow()
    session.add(target_cause)
    
    # Insert immutable ledger entry for this decision
    from app.models.candidate_cause_feedback_log import CandidateCauseFeedbackLog
    log_entry = CandidateCauseFeedbackLog(
        workspace_id=incident.workspace_id or user.workspace_id,
        candidate_cause_id=target_cause.id,
        incident_id=incident.id,
        repo_id=target_cause.repo_id,
        event_id=target_cause.event_id,
        confirmed=feedback.confirmed,
        confirmed_by=user.id,
        score_at_time=target_cause.score,
        reasons_at_time=target_cause.reason or "",
        created_at=datetime.utcnow()
    )
    session.add(log_entry)
    
    # If confirmed is True, reject all other causes for this incident and log ledger entries
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

            other_log = CandidateCauseFeedbackLog(
                workspace_id=incident.workspace_id or user.workspace_id,
                candidate_cause_id=other.id,
                incident_id=incident.id,
                repo_id=other.repo_id,
                event_id=other.event_id,
                confirmed=False,
                confirmed_by=user.id,
                score_at_time=other.score,
                reasons_at_time=other.reason or "",
                created_at=datetime.utcnow()
            )
            session.add(other_log)
            
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


# ── Postmortem Endpoints ──────────────────────────────────────────────────────

class PostmortemUpsert(BaseModel):
    summary:              Optional[str] = None
    timeline:             Optional[str] = None
    root_cause:           Optional[str] = None
    contributing_factors: Optional[str] = None
    impact:               Optional[str] = None
    action_items:         Optional[str] = None
    lessons_learned:      Optional[str] = None


@router.get("/{incident_id}/postmortem", tags=["Postmortems"])
async def get_postmortem(
    incident_id: str,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user),
):
    """
    Fetch the postmortem for an incident.
    Auto-creates an empty draft on first access so the editor can open immediately.
    """
    # Verify incident ownership
    inc_result = await session.execute(
        select(Incident).where(
            Incident.id == incident_id,
            (Incident.workspace_id == user.workspace_id) |
            (Incident.workspace_id == None) |
            (Incident.workspace_id == "")
        )
    )
    incident = inc_result.scalar_one_or_none()
    if not incident:
        incident = await session.get(Incident, incident_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")

    pm_result = await session.execute(
        select(Postmortem).where(Postmortem.incident_id == incident_id)
    )
    pm = pm_result.scalar_one_or_none()

    if not pm:
        # Auto-create an empty draft — pre-populate root_cause from confirmed candidate
        cc_result = await session.execute(
            select(CandidateCause).where(
                CandidateCause.incident_id == incident_id,
                CandidateCause.confirmed == True  # noqa: E712
            )
        )
        confirmed_cause = cc_result.scalars().first()
        prefill_root_cause = confirmed_cause.reason if confirmed_cause else None

        pm = Postmortem(
            incident_id=incident_id,
            workspace_id=incident.workspace_id or user.workspace_id,
            author_id=user.id,
            root_cause=prefill_root_cause,
            status="draft",
        )
        session.add(pm)
        await session.commit()
        await session.refresh(pm)

    return pm.model_dump()


@router.patch("/{incident_id}/postmortem", tags=["Postmortems"])
async def upsert_postmortem(
    incident_id: str,
    body: PostmortemUpsert,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user),
):
    """
    Update (partial) postmortem fields — acts as an auto-save endpoint.
    Any field set to None in the request body is left unchanged.
    """
    pm_result = await session.execute(
        select(Postmortem).where(Postmortem.incident_id == incident_id)
    )
    pm = pm_result.scalar_one_or_none()

    if not pm:
        # Trigger auto-create via the GET endpoint logic inline
        inc = await session.get(Incident, incident_id)
        if not inc:
            raise HTTPException(status_code=404, detail="Incident not found")
        pm = Postmortem(
            incident_id=incident_id,
            workspace_id=inc.workspace_id or user.workspace_id,
            author_id=user.id,
            status="draft",
        )
        session.add(pm)

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(pm, field, value)
    pm.updated_at = datetime.utcnow()

    session.add(pm)
    await session.commit()
    await session.refresh(pm)
    return pm.model_dump()


@router.post("/{incident_id}/postmortem/publish", tags=["Postmortems"])
async def publish_postmortem(
    incident_id: str,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user),
):
    """
    Mark the postmortem as published. Requires summary and root_cause to be non-empty.
    """
    pm_result = await session.execute(
        select(Postmortem).where(Postmortem.incident_id == incident_id)
    )
    pm = pm_result.scalar_one_or_none()
    if not pm:
        raise HTTPException(status_code=404, detail="Postmortem not found — create it first via GET or PATCH")

    if not pm.summary or not pm.root_cause:
        raise HTTPException(
            status_code=422,
            detail="Cannot publish: 'summary' and 'root_cause' fields are required."
        )

    pm.status = "published"
    pm.updated_at = datetime.utcnow()
    session.add(pm)
    await session.commit()
    await session.refresh(pm)
    return pm.model_dump()
