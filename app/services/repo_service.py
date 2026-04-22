"""
Repository Service
Business logic for repository CRUD and state management.
"""

from datetime import datetime
from typing import Optional, List
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repo import Repo
from app.schemas.repo_schema import RepoCreate, RepoUpdate


async def create_repo(session: AsyncSession, data: RepoCreate) -> Repo:
    """Create a new repository record."""
    repo = Repo(
        name=data.name,
        platform=data.platform,
        description=data.description,
        language=data.language,
        default_branch=data.default_branch,
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


async def get_repos(
    session: AsyncSession,
    platform: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Repo]:
    """Fetch all repositories with optional platform filtering."""
    query = select(Repo)
    if platform:
        query = query.where(Repo.platform == platform)
    query = query.order_by(Repo.updated_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_repo_by_id(session: AsyncSession, repo_id: str) -> Optional[Repo]:
    """Fetch a single repository by ID."""
    return await session.get(Repo, repo_id)


async def update_repo(
    session: AsyncSession, repo_id: str, data: RepoUpdate
) -> Optional[Repo]:
    """Update repository fields."""
    repo = await session.get(Repo, repo_id)
    if not repo:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(repo, key, value)

    repo.updated_at = datetime.utcnow()
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


async def update_repo_state(
    session: AsyncSession,
    repo_id: str,
    **kwargs,
) -> Optional[Repo]:
    """Internal method: update repo state from automation actions."""
    repo = await session.get(Repo, repo_id)
    if not repo:
        return None

    for key, value in kwargs.items():
        if hasattr(repo, key):
            setattr(repo, key, value)

    repo.updated_at = datetime.utcnow()
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo
