"""
Cluster Routes
Domain-level intelligence layer between Workspace and Repository.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime

from app.core.database import get_session
from app.core.security import get_current_user
from app.schemas.cluster_schema import (
    ClusterCreate, ClusterUpdate, ClusterResponse, ClusterAlertSummary
)
from app.schemas.repo_schema import RepoResponse
from app.services import cluster_service

router = APIRouter(prefix="/clusters", tags=["Clusters"])


@router.get("", response_model=List[ClusterResponse])
async def list_clusters(
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """List all clusters in a workspace."""
    return await cluster_service.get_clusters(session, workspace_id)


@router.post("", response_model=ClusterResponse, status_code=201)
async def create_cluster(
    data: ClusterCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Create a new cluster."""
    return await cluster_service.create_cluster(session, data)


@router.get("/alert-summary", response_model=List[ClusterAlertSummary])
async def alert_summary(
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Alert breakdown grouped by cluster — powers the security page."""
    return await cluster_service.get_alert_summary_by_cluster(session, workspace_id)


@router.get("/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(
    cluster_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    cluster = await cluster_service.get_cluster_by_id(session, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


@router.patch("/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    data: ClusterUpdate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    cluster = await cluster_service.update_cluster(session, cluster_id, data)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


@router.delete("/{cluster_id}", status_code=204)
async def delete_cluster(
    cluster_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    success = await cluster_service.delete_cluster(session, cluster_id)
    if not success:
        raise HTTPException(status_code=404, detail="Cluster not found")


@router.get("/{cluster_id}/repos", response_model=List[RepoResponse])
async def get_cluster_repos(
    cluster_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """List all repos belonging to a cluster."""
    return await cluster_service.get_cluster_repos(session, cluster_id)


@router.post("/{cluster_id}/recalculate", response_model=ClusterResponse)
async def recalculate_health(
    cluster_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Manually trigger health recalculation for a cluster."""
    cluster = await cluster_service.recalculate_cluster_health(session, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


@router.post("/{cluster_id}/assign-repo", response_model=ClusterResponse)
async def assign_repo_to_cluster(
    cluster_id: str,
    repo_id: str = Query(..., description="Repository ID to assign"),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Assign a repository to this cluster and recalculate health."""
    from app.models.repo import Repo
    
    # Verify cluster exists
    cluster = await cluster_service.get_cluster_by_id(session, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Get the repo
    repo = await session.get(Repo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # Store old cluster_id
    old_cluster_id = repo.cluster_id
    
    # Assign repo to cluster
    repo.cluster_id = cluster_id
    repo.updated_at = datetime.utcnow()
    session.add(repo)
    await session.commit()
    
    # Recalculate health for old cluster (if it had one)
    if old_cluster_id and old_cluster_id != cluster_id:
        await cluster_service.recalculate_cluster_health(session, old_cluster_id)
    
    # Recalculate health for new cluster
    updated_cluster = await cluster_service.recalculate_cluster_health(session, cluster_id)
    
    return updated_cluster


@router.delete("/{cluster_id}/repos/{repo_id}", response_model=ClusterResponse)
async def remove_repo_from_cluster(
    cluster_id: str,
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Remove a repository from this cluster and recalculate health."""
    from app.models.repo import Repo
    
    # Verify cluster exists
    cluster = await cluster_service.get_cluster_by_id(session, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Get the repo
    repo = await session.get(Repo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # Verify repo belongs to this cluster
    if repo.cluster_id != cluster_id:
        raise HTTPException(status_code=400, detail="Repository does not belong to this cluster")
    
    # Remove repo from cluster
    repo.cluster_id = None
    repo.updated_at = datetime.utcnow()
    session.add(repo)
    await session.commit()
    
    # Recalculate cluster health
    updated_cluster = await cluster_service.recalculate_cluster_health(session, cluster_id)
    
    return updated_cluster
