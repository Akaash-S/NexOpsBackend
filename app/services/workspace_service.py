"""
Workspace Service
Handles organizational logic for repositories.
"""

from typing import List, Optional
from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workspace import Workspace
from app.models.repo import Repo
from app.schemas.workspace_schema import WorkspaceCreate


async def get_workspaces(session: AsyncSession) -> List[Workspace]:
    """List all workspaces."""
    result = await session.execute(select(Workspace).order_by(Workspace.name))
    return list(result.scalars().all())


async def get_workspace_by_id(session: AsyncSession, workspace_id: str) -> Optional[Workspace]:
    """Get a single workspace."""
    return await session.get(Workspace, workspace_id)


async def create_workspace(session: AsyncSession, data: WorkspaceCreate) -> Workspace:
    """Create a new workspace."""
    workspace = Workspace(**data.model_dump())
    session.add(workspace)
    await session.commit()
    await session.refresh(workspace)
    return workspace


async def get_workspace_stats(session: AsyncSession, workspace_id: str) -> dict:
    """Calculate stats for a workspace based on its repos."""
    # Count repos
    repo_count_query = select(func.count()).select_from(Repo).where(Repo.workspace_id == workspace_id)
    repo_count_result = await session.execute(repo_count_query)
    repo_count = repo_count_result.scalar() or 0

    # Calculate average health score
    health_query = select(func.avg(Repo.health_score)).where(Repo.workspace_id == workspace_id)
    health_result = await session.execute(health_query)
    avg_health = health_result.scalar() or 100.0

    return {
        "repo_count": repo_count,
        "health_score": round(float(avg_health), 1)
    }
