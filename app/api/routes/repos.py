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
