"""
Repository Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from sqlmodel import select, or_

from app.core.database import get_session
from app.models.repo import Repo
from app.models.user import User
from app.schemas.repo_schema import RepoCreate, RepoUpdate, RepoResponse
from app.services import repo_service
from app.services.vcs_service import vcs_service
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.security import get_current_user

router = APIRouter(prefix="/repos", tags=["Repositories"])


@router.get("", response_model=List[RepoResponse])
async def list_repos(
    workspace_id: Optional[str] = Query(None),
    cluster_id: Optional[str] = Query(None),
    platform: Optional[str] = Query(None, pattern="^(github|gitlab|bitbucket)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List repositories, optionally filtered by workspace or cluster, scoped to the current user."""
    return await repo_service.get_repos(
        session,
        workspace_id=user.workspace_id,
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
    user: User = Depends(get_current_user),
):
    """Search repositories by name, description, or language, scoped to the current user."""
    search_term = f"%{q}%"
    query = select(Repo).where(
        Repo.workspace_id == user.workspace_id,
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
    user: User = Depends(get_current_user),
):
    """Get a single repository by ID, verifying user ownership."""
    repo = await repo_service.get_repo_by_id(session, repo_id)
    if not repo or repo.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.post("", response_model=RepoResponse, status_code=201)
async def create_repo(
    data: RepoCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Register a new repository to track, owned by the current user."""
    repo = Repo(
        name=data.name,
        platform=data.platform,
        description=data.description,
        language=data.language,
        default_branch=data.default_branch,
        user_id=user.id,
        workspace_id=user.workspace_id,
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


@router.patch("/{repo_id}", response_model=RepoResponse)
async def update_repo(
    repo_id: str,
    data: RepoUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Update repository details, verifying user ownership."""
    old_repo = await repo_service.get_repo_by_id(session, repo_id)
    if not old_repo or old_repo.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    repo = await repo_service.update_repo(session, repo_id, data)
    return repo


@router.get("/{repo_id}/blast-radius")
async def get_repo_blast_radius(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Calculate repository blast radius and risk score, verifying user ownership."""
    repo = await repo_service.get_repo_by_id(session, repo_id)
    if not repo or repo.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    from app.services.impact_service import calculate_blast_radius
    return await calculate_blast_radius(session, repo_id)


@router.get("/{repo_id}/tree")
async def get_repo_tree(
    repo_id: str,
    path: str = Query("", description="Folder path within the repository"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Fetch live directory structure from the VCS provider, verifying user ownership."""
    # Check cache first
    from app.core.redis import get_cached_data, set_cached_data
    cache_key = f"cache:repo:tree:{repo_id}:{path}"
    cached_tree = await get_cached_data(cache_key)
    if cached_tree is not None:
        return cached_tree

    # 1. Get Repo metadata and verify ownership
    result = await session.execute(select(Repo).where(Repo.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo or repo.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not user.github_access_token:
        raise HTTPException(
            status_code=401, 
            detail="VCS integration not authenticated. Please sync your account on the Integrations page to enable live code viewing."
        )

    # 3. Call VCS service
    try:
        if repo.platform == "github":
            tree_data = await vcs_service.fetch_github_tree(
                token=decrypt_secret(user.github_access_token),
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
    user: User = Depends(get_current_user),
):
    """Fetch live file content from the VCS provider, verifying user ownership."""
    # Check cache first
    from app.core.redis import get_cached_data, set_cached_data
    cache_key = f"cache:repo:file:{repo_id}:{path}"
    cached_file = await get_cached_data(cache_key)
    if cached_file is not None:
        return cached_file

    # 1. Get Repo metadata and verify ownership
    result = await session.execute(select(Repo).where(Repo.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo or repo.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if not user.github_access_token:
        raise HTTPException(
            status_code=401, 
            detail="VCS integration not authenticated. Please sync your account on the Integrations page to enable live code viewing."
        )

    # 3. Call VCS service
    try:
        if repo.platform == "github":
            file_data = await vcs_service.fetch_github_file_content(
                token=decrypt_secret(user.github_access_token),
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
