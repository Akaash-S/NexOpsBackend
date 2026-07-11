from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import List, Optional
from datetime import datetime

from app.core.database import get_session
from app.core.security import get_current_user
from app.models.deployment import Deployment
from app.schemas.deployment_schema import DeploymentResponse, DeploymentCreate
from app.schemas.event_schema import EventCreate
from app.services.event_service import create_event

router = APIRouter(prefix="/deployments", tags=["Deployments"])

@router.get("", response_model=List[DeploymentResponse])
async def list_deployments(
    repo_id: Optional[str] = Query(None),
    environment: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    query = select(Deployment).where(Deployment.workspace_id == user.workspace_id)
    if repo_id:
        query = query.where(Deployment.repo_id == repo_id)
    if environment:
        query = query.where(Deployment.environment == environment)
    query = query.order_by(Deployment.deployed_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())

@router.post("", response_model=DeploymentResponse, status_code=201)
async def trigger_deployment(
    data: DeploymentCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """
    Simulate a deployment trigger. 
    Creates a deployment record and an associated event.
    """
    from app.models.repo import Repo
    repo = await session.get(Repo, data.repo_id)
    if not repo or repo.workspace_id != user.workspace_id:
        raise HTTPException(status_code=403, detail="Repository not found or access denied")

    # Calculate risk score
    from app.services.impact_service import calculate_deployment_risk
    risk_calc = await calculate_deployment_risk(session, data.repo_id)
    risk_score = risk_calc.get("risk_score", 0.0)
    risk_basis = risk_calc.get("risk_basis", "")

    deployment = Deployment(
        repo_id=data.repo_id,
        environment=data.environment,
        status=data.status,
        deployed_by=data.deployed_by or user.email,
        commit_hash=data.commit_hash,
        changelog=data.changelog,
        risk_score=risk_score,
        risk_basis=risk_basis,
        workspace_id=user.workspace_id,
        deployed_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    session.add(deployment)
    await session.flush()
    await session.refresh(deployment)
    
    # Create a 'deploy.started' event
    event_data = EventCreate(
        type="deploy.started",
        repo_id=data.repo_id,
        source="system",
        payload={
            "deployment_id": deployment.id,
            "environment": data.environment,
            "risk_score": risk_score,
            "risk_basis": risk_basis
        }
    )
    
    # Trigger automation in background
    from app.api.routes.events import _run_automation
    event = await create_event(session, event_data)
    background_tasks.add_task(_run_automation, event.id)
    
    await session.commit()
    return deployment
