"""
Repository Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from sqlmodel import select, or_

from app.core.database import get_session
from app.models.repo import Repo
from app.models.workspace import Workspace
from app.schemas.repo_schema import RepoCreate, RepoUpdate, RepoResponse
from app.services import repo_service
from app.services.vcs_service import vcs_service

router = APIRouter(prefix="/repos", tags=["Repositories"])


@router.get("", response_model=List[RepoResponse])
async def list_repos(
    workspace_id: Optional[str] = Query(None),
    cluster_id: Optional[str] = Query(None),
    platform: Optional[str] = Query(None, pattern="^(github|gitlab|bitbucket)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List repositories, optionally filtered by workspace or cluster."""
    return await repo_service.get_repos(
        session,
        workspace_id=workspace_id,
        cluster_id=cluster_id,
        platform=platform,
        limit=limit,
        offset=offset,
    )


@router.get("/search", response_model=List[RepoResponse])
async def search_repos(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """Search repositories by name, description, or language."""
    search_term = f"%{q}%"
    query = select(Repo).where(
        or_(
            Repo.name.ilike(search_term),
            Repo.description.ilike(search_term),
            Repo.language.ilike(search_term),
            Repo.platform.ilike(search_term)
        )
    ).limit(limit)
    
    result = await session.execute(query)
    return list(result.scalars().all())


@router.get("/{repo_id}", response_model=RepoResponse)
async def get_repo(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a single repository by ID."""
    repo = await repo_service.get_repo_by_id(session, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.post("", response_model=RepoResponse, status_code=201)
async def create_repo(
    data: RepoCreate,
    session: AsyncSession = Depends(get_session),
):
    """Register a new repository to track."""
    return await repo_service.create_repo(session, data)


@router.patch("/{repo_id}", response_model=RepoResponse)
async def update_repo(
    repo_id: str,
    data: RepoUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update repository details."""
    # Get the old cluster_id before update
    old_repo = await repo_service.get_repo_by_id(session, repo_id)
    if not old_repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    old_cluster_id = old_repo.cluster_id
    
    # Update the repo
    repo = await repo_service.update_repo(session, repo_id, data)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # If cluster_id changed, recalculate health for both old and new clusters
    new_cluster_id = repo.cluster_id
    if old_cluster_id != new_cluster_id:
        from app.services import cluster_service
        
        # Recalculate old cluster health (if it had one)
        if old_cluster_id:
            await cluster_service.recalculate_cluster_health(session, old_cluster_id)
        
        # Recalculate new cluster health (if assigned to one)
        if new_cluster_id:
            await cluster_service.recalculate_cluster_health(session, new_cluster_id)
    
    return repo


@router.get("/{repo_id}/tree")
async def get_repo_tree(
    repo_id: str,
    path: str = Query("", description="Folder path within the repository"),
    session: AsyncSession = Depends(get_session),
):
    """Fetch live directory structure from the VCS provider, cached in Redis."""
    # Check cache first
    from app.core.redis import get_cached_data, set_cached_data
    cache_key = f"cache:repo:tree:{repo_id}:{path}"
    cached_tree = await get_cached_data(cache_key)
    if cached_tree is not None:
        return cached_tree

    # 1. Get Repo metadata
    result = await session.execute(select(Repo).where(Repo.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # 2. Get Workspace for token
    if not repo.workspace_id:
        raise HTTPException(status_code=400, detail="Repository is not linked to a workspace")
    
    ws_result = await session.execute(select(Workspace).where(Workspace.id == repo.workspace_id))
    workspace = ws_result.scalar_one_or_none()
    
    if not workspace or not workspace.access_token:
        # Fallback to mock if no token, but here we want to solve it properly
        raise HTTPException(
            status_code=401, 
            detail="VCS integration not authenticated. Please re-sync your workspace on the Integrations page to enable live code viewing."
        )

    # 3. Call VCS service
    try:
        if repo.platform == "github":
            tree_data = await vcs_service.fetch_github_tree(
                token=workspace.decrypted_access_token,
                owner=repo.owner or "unknown",
                repo=repo.name,
                path=path
            )
            # Cache directory tree for 10 minutes (600s)
            await set_cached_data(cache_key, tree_data, ttl=600)
            return tree_data
        else:
            raise HTTPException(status_code=501, detail=f"Tree fetching not implemented for {repo.platform}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"VCS Error: {str(e)}")


@router.get("/{repo_id}/files/{path:path}")
async def get_file_content(
    repo_id: str,
    path: str,
    session: AsyncSession = Depends(get_session),
):
    """Fetch live file content from the VCS provider, cached in Redis."""
    # Check cache first
    from app.core.redis import get_cached_data, set_cached_data
    cache_key = f"cache:repo:file:{repo_id}:{path}"
    cached_file = await get_cached_data(cache_key)
    if cached_file is not None:
        return cached_file

    # 1. Get Repo metadata
    result = await session.execute(select(Repo).where(Repo.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # 2. Get Workspace for token
    ws_result = await session.execute(select(Workspace).where(Workspace.id == repo.workspace_id))
    workspace = ws_result.scalar_one_or_none()
    
    if not workspace or not workspace.access_token:
        raise HTTPException(
            status_code=401, 
            detail="VCS integration not authenticated. Please re-sync your workspace on the Integrations page to enable live code viewing."
        )

    # 3. Call VCS service
    try:
        if repo.platform == "github":
            file_data = await vcs_service.fetch_github_file_content(
                token=workspace.decrypted_access_token,
                owner=repo.owner or "unknown",
                repo=repo.name,
                path=path
            )
            # Cache file content for 10 minutes (600s)
            await set_cached_data(cache_key, file_data, ttl=600)
            return file_data
        else:
            raise HTTPException(status_code=501, detail=f"File fetching not implemented for {repo.platform}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"VCS Error: {str(e)}")
