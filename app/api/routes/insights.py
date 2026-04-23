"""
Insights Routes
Intelligence & analytics endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.insight_service import get_repo_insights, calculate_health_score
from app.schemas.insight_schema import InsightResponse

router = APIRouter(prefix="/repos", tags=["Insights"])


@router.get("/{repo_id}/insights", response_model=InsightResponse)
async def repo_insights(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Get comprehensive intelligence insights for a repository.
    Powers the frontend's "Intelligence Insights" slide-out panel.
    
    Returns health score, contributing factors, alert breakdown,
    pipeline stats, and actionable recommendations.
    """
    insights = await get_repo_insights(session, repo_id)
    if not insights:
        raise HTTPException(status_code=404, detail="Repository not found")
    return insights


@router.post("/{repo_id}/recalculate-health")
async def recalculate_health(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Manually trigger a health score recalculation."""
    score = await calculate_health_score(session, repo_id)
    if score is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {"repo_id": repo_id, "health_score": score}
