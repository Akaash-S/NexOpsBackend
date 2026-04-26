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
    query = select(Deployment)
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
    deployment = Deployment(**data.model_dump())
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
            "version": data.version,
            "environment": data.environment,
            "provider_id": data.provider_id
        }
    )
    
    # NEW: Create a Pipeline record so it's visible in the CICD Command Center
    from app.models.pipeline import Pipeline
    from app.core.logs import generate_realistic_logs
    
    pipeline = Pipeline(
        repo_id=data.repo_id,
        name=f"Manual Deploy: {data.version}",
        status="running",
        trigger="manual",
        environment=data.environment,
        commit_hash=data.commit_hash,
        logs=generate_realistic_logs("Deployment", "HEAD", "success"),
        metadata={"provider_id": data.provider_id} # Store provider info in pipeline metadata
    )
    session.add(pipeline)
    await session.flush()

    # Trigger automation in background
    from app.api.routes.events import _run_automation
    event = await create_event(session, event_data)
    background_tasks.add_task(_run_automation, event.id)
    
    await session.commit()
    return deployment
