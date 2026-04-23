"""
Pipeline Routes
Endpoints for CI/CD history and stage details.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_session
from app.schemas.pipeline_schema import PipelineResponse
from app.services import pipeline_service

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


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
