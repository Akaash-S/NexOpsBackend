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
    user_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    cluster_id: Optional[str] = None,
    platform: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Repo]:
    """Fetch repositories, strictly requiring and filtering by workspace_id."""
    if not workspace_id:
        return []

    query = select(Repo).where(Repo.workspace_id == workspace_id)
    if user_id:
        query = query.where(Repo.user_id == user_id)
    if cluster_id:
        query = query.where(Repo.cluster_id == cluster_id)
    if platform:
        query = query.where(Repo.platform == platform)
    query = query.order_by(Repo.updated_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    repos = list(result.scalars().all())

    # Map active incidents to repos to ensure health score parity across /repos and /dependencies/topology
    from app.models.incident import Incident
    from app.models.candidate_cause import CandidateCause

    inc_res = await session.execute(
        select(Incident).where(
            Incident.status.in_(["open", "investigating"]),
            (Incident.workspace_id == workspace_id) | (Incident.workspace_id == "default-workspace")
        )
    )
    active_incidents = list(inc_res.scalars().all())
    active_inc_ids = [inc.id for inc in active_incidents]

    active_repo_ids = set()
    for inc in active_incidents:
        if inc.root_cause_repo_id:
            active_repo_ids.add(inc.root_cause_repo_id)
        for r_id in (inc.impacted_repos or []):
            active_repo_ids.add(r_id)

    if active_inc_ids:
        cc_res = await session.execute(
            select(CandidateCause).where(CandidateCause.incident_id.in_(active_inc_ids))
        )
        for cc in cc_res.scalars().all():
            if cc.repo_id:
                active_repo_ids.add(cc.repo_id)

    for r in repos:
        if r.id in active_repo_ids:
            r.health_score = min(r.health_score, 45.0)
            r.ci_status = "failing"

    return repos


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
