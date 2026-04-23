"""
Pipeline Service
Business logic for CI/CD pipeline history and details.
"""

from typing import List, Optional
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.pipeline import Pipeline


async def get_pipelines(
    session: AsyncSession,
    repo_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Pipeline]:
    """Fetch pipeline history with filtering."""
    query = select(Pipeline)
    if repo_id:
        query = query.where(Pipeline.repo_id == repo_id)
    if status:
        query = query.where(Pipeline.status == status)
    
    query = query.order_by(Pipeline.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_pipeline_by_id(session: AsyncSession, pipeline_id: str) -> Optional[Pipeline]:
    """Fetch a single pipeline detail."""
    return await session.get(Pipeline, pipeline_id)
