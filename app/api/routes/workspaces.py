"""
Workspace Routes
Organizational endpoints for grouping repositories.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_session
from app.schemas.workspace_schema import WorkspaceCreate, WorkspaceResponse
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(session: AsyncSession = Depends(get_session)):
    """List all organizational workspaces."""
    workspaces = await workspace_service.get_workspaces(session)
    
    results = []
    for ws in workspaces:
        stats = await workspace_service.get_workspace_stats(session, ws.id)
        results.append(
            WorkspaceResponse(
                **ws.model_dump(),
                repo_count=stats["repo_count"],
                health_score=stats["health_score"]
            )
        )
    return results


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    data: WorkspaceCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new workspace."""
    workspace = await workspace_service.create_workspace(session, data)
    return WorkspaceResponse(**workspace.model_dump(), repo_count=0, health_score=100.0)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str, session: AsyncSession = Depends(get_session)):
    """Get detailed workspace stats."""
    workspace = await workspace_service.get_workspace_by_id(session, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    stats = await workspace_service.get_workspace_stats(session, workspace.id)
    return WorkspaceResponse(
        **workspace.model_dump(),
        repo_count=stats["repo_count"],
        health_score=stats["health_score"]
    )
