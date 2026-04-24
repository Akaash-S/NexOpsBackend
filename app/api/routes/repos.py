"""
Repository Routes
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.core.database import get_session
from app.schemas.repo_schema import RepoCreate, RepoUpdate, RepoResponse
from app.services import repo_service

router = APIRouter(prefix="/repos", tags=["Repositories"])


@router.get("", response_model=List[RepoResponse])
async def list_repos(
    platform: Optional[str] = Query(None, pattern="^(github|gitlab|bitbucket)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List all tracked repositories."""
    return await repo_service.get_repos(session, platform=platform, limit=limit, offset=offset)


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
    repo = await repo_service.update_repo(session, repo_id, data)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
from sqlmodel import select
from app.models.repo import Repo
from app.models.workspace import Workspace
from app.services.vcs_service import vcs_service


@router.get("/{repo_id}/tree")
async def get_repo_tree(
    repo_id: str,
    path: str = Query("", description="Folder path within the repository"),
    session: AsyncSession = Depends(get_session),
):
    """Fetch live directory structure from the VCS provider."""
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
            return await vcs_service.fetch_github_tree(
                token=workspace.access_token,
                owner=repo.owner or "unknown",
                repo=repo.name,
                path=path
            )
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
    """Fetch live file content from the VCS provider."""
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
            return await vcs_service.fetch_github_file_content(
                token=workspace.access_token,
                owner=repo.owner or "unknown",
                repo=repo.name,
                path=path
            )
        else:
            raise HTTPException(status_code=501, detail=f"File fetching not implemented for {repo.platform}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"VCS Error: {str(e)}")
