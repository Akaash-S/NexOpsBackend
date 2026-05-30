"""
Pipeline Routes
Endpoints for CI/CD history and stage details.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import asyncio
import random
import uuid
from datetime import datetime
from pydantic import BaseModel
from sqlmodel import select

from app.core.database import get_session, async_session
from app.schemas.pipeline_schema import PipelineResponse
from app.services import pipeline_service
from app.models.pipeline import Pipeline
from app.models.repo import Repo

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


async def simulate_pipeline_run(pipeline_id: str):
    """Simulates a pipeline execution in background stages."""
    stages_list = [
        {"name": "lint_code", "status": "pending", "duration": 0.0},
        {"name": "security_scan", "status": "pending", "duration": 0.0},
        {"name": "execute_tests", "status": "pending", "duration": 0.0},
        {"name": "deploy_infra", "status": "pending", "duration": 0.0}
    ]
    logs_output = (
        "[system] Workflow initialized.\n"
        "[system] Locating target runner node...\n"
        "[system] Runner active. Initializing environment configuration...\n"
    )
    
    # 1. Update pipeline to running
    await asyncio.sleep(2)
    async with async_session() as session:
        pipeline = await session.get(Pipeline, pipeline_id)
        if not pipeline or pipeline.status == "cancelled":
            return
        
        repo = await session.get(Repo, pipeline.repo_id)
        repo_name = repo.name if repo else "unknown"
        
        pipeline.status = "running"
        pipeline.stages = stages_list
        pipeline.logs = logs_output + f"[system] Running task sequences for {repo_name} on branch {pipeline.branch}...\n"
        session.add(pipeline)
        await session.commit()

    # 2. Iterate through stages
    total_duration = 0.0
    failed_stage = None
    
    # Simple logic: 10% chance to fail tests, 5% chance to fail deploy
    will_fail = random.random() < 0.15
    fail_at_stage = random.choice([2, 3]) if will_fail else -1

    for idx, stage in enumerate(stages_list):
        # Check if pipeline was cancelled in the meantime
        async with async_session() as session:
            pipeline = await session.get(Pipeline, pipeline_id)
            if not pipeline or pipeline.status == "cancelled":
                return
        
        # Start stage
        stage["status"] = "running"
        async with async_session() as session:
            pipeline = await session.get(Pipeline, pipeline_id)
            pipeline.stages = list(stages_list)
            pipeline.logs += f"[step] Starting stage '{stage['name']}'...\n"
            session.add(pipeline)
            await session.commit()
            
        # Simulate work
        stage_dur = round(random.uniform(2.0, 5.0), 1)
        await asyncio.sleep(stage_dur)
        total_duration += stage_dur
        stage["duration"] = stage_dur
        
        # Check if this stage fails
        if idx == fail_at_stage:
            stage["status"] = "failed"
            failed_stage = stage["name"]
            break
        else:
            stage["status"] = "success"
            
        async with async_session() as session:
            pipeline = await session.get(Pipeline, pipeline_id)
            if pipeline.status == "cancelled":
                return
            pipeline.stages = list(stages_list)
            pipeline.logs += f"[step] Stage '{stage['name']}' completed successfully in {stage_dur}s.\n"
            session.add(pipeline)
            await session.commit()

    # 3. Finalize run
    async with async_session() as session:
        pipeline = await session.get(Pipeline, pipeline_id)
        if not pipeline or pipeline.status == "cancelled":
            return
            
        pipeline.duration = round(total_duration, 1)
        pipeline.updated_at = datetime.utcnow()
        
        if failed_stage:
            pipeline.status = "failed"
            pipeline.logs += f"\n[system] Build pipeline failed at stage '{failed_stage}'!\n[system] Final elapsed duration: {pipeline.duration}s."
        else:
            pipeline.status = "success"
            pipeline.logs += f"\n[system] Build pipeline completed successfully!\n[system] Final elapsed duration: {pipeline.duration}s."
            
        # Also update the repo.ci_status
        repo = await session.get(Repo, pipeline.repo_id)
        if repo:
            repo.ci_status = "passing" if not failed_stage else "failing"
            session.add(repo)
            
        session.add(pipeline)
        await session.commit()


class TriggerRequest(BaseModel):
    repo_id: str
    branch: str = "main"
    environment: str = "staging"


@router.get("", response_model=List[PipelineResponse])
async def list_pipelines(
    repo_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List all pipeline executions with optional filtering."""
    pipelines = await pipeline_service.get_pipelines(
        session, repo_id=repo_id, status=status, limit=limit, offset=offset
    )
    return pipelines


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(pipeline_id: str, session: AsyncSession = Depends(get_session)):
    """Get detailed stages and metrics for a specific pipeline."""
    pipeline = await pipeline_service.get_pipeline_by_id(session, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline


@router.post("/trigger", response_model=PipelineResponse)
async def trigger_pipeline(
    payload: TriggerRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """Manually trigger a pipeline run."""
    pipeline = Pipeline(
        repo_id=payload.repo_id,
        name="manual-workflow",
        branch=payload.branch,
        status="pending",
        trigger="manual",
        triggered_by="developer",
        commit_hash=uuid.uuid4().hex[:10].upper(),
        commit_message="Manual execution run triggered from web dashboard",
        environment=payload.environment,
        stages=[
            {"name": "lint_code", "status": "pending", "duration": 0.0},
            {"name": "security_scan", "status": "pending", "duration": 0.0},
            {"name": "execute_tests", "status": "pending", "duration": 0.0},
            {"name": "deploy_infra", "status": "pending", "duration": 0.0}
        ],
        logs="[system] Queued. Waiting for available runner node...\n"
    )
    session.add(pipeline)
    await session.commit()
    await session.refresh(pipeline)
    
    background_tasks.add_task(simulate_pipeline_run, pipeline.id)
    return pipeline


@router.post("/{pipeline_id}/cancel", response_model=PipelineResponse)
async def cancel_pipeline(pipeline_id: str, session: AsyncSession = Depends(get_session)):
    """Cancel a running or pending pipeline."""
    pipeline = await session.get(Pipeline, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    
    if pipeline.status in ["success", "failed", "cancelled"]:
        raise HTTPException(status_code=400, detail="Cannot cancel completed pipeline")
        
    pipeline.status = "cancelled"
    pipeline.logs = (pipeline.logs or "") + "\n[system] Workflow cancellation requested by developer.\n[system] Build pipeline cancelled."
    pipeline.updated_at = datetime.utcnow()
    session.add(pipeline)
    await session.commit()
    await session.refresh(pipeline)
    return pipeline


@router.post("/{pipeline_id}/retry", response_model=PipelineResponse)
async def retry_pipeline(
    pipeline_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """Retry a failed or completed pipeline by cloning it as a new run."""
    old_pipeline = await session.get(Pipeline, pipeline_id)
    if not old_pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
        
    new_pipeline = Pipeline(
        repo_id=old_pipeline.repo_id,
        name=old_pipeline.name,
        branch=old_pipeline.branch,
        status="pending",
        trigger="manual",
        triggered_by="developer",
        commit_hash=uuid.uuid4().hex[:10].upper(),
        commit_message=f"Retry of pipeline run {old_pipeline.id[:8]}",
        environment=old_pipeline.environment,
        stages=[
            {"name": "lint_code", "status": "pending", "duration": 0.0},
            {"name": "security_scan", "status": "pending", "duration": 0.0},
            {"name": "execute_tests", "status": "pending", "duration": 0.0},
            {"name": "deploy_infra", "status": "pending", "duration": 0.0}
        ],
        logs="[system] Retrying workflow. Waiting for available runner node...\n"
    )
    session.add(new_pipeline)
    await session.commit()
    await session.refresh(new_pipeline)
    
    background_tasks.add_task(simulate_pipeline_run, new_pipeline.id)
    return new_pipeline

