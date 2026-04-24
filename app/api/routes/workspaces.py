"""
Workspace Routes
Organizational endpoints for grouping repositories.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_session
from app.core.security import get_current_user
from app.schemas.workspace_schema import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])
# ... (list_workspaces and create_workspace)

@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    data: WorkspaceUpdate,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Update workspace details."""
    workspace = await workspace_service.update_workspace(session, workspace_id, data)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    stats = await workspace_service.get_workspace_stats(session, workspace.id)
    return WorkspaceResponse(
        **workspace.model_dump(),
        repo_count=stats["repo_count"],
        health_score=stats["health_score"]
    )


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
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
    user = Depends(get_current_user)
):
    """Create a new workspace."""
    workspace = await workspace_service.create_workspace(session, data)
    return WorkspaceResponse(**workspace.model_dump(), repo_count=0, health_score=100.0)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str, 
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
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

@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str, 
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Delete a workspace and its associated data."""
    success = await workspace_service.delete_workspace(session, workspace_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return None
