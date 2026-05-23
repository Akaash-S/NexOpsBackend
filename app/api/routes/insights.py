"""
Insights Routes
Intelligence & analytics endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.insight_service import get_repo_insights, calculate_health_score
from app.schemas.insight_schema import InsightResponse

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/{repo_id}", response_model=InsightResponse)
async def repo_insights(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Get comprehensive intelligence insights for a repository.
    Powers the frontend's "Intelligence Insights" slide-out panel.
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


from app.core.security import get_current_user
from app.core.config import settings
from app.models.repo import Repo
from app.models.alert import Alert
from app.models.pipeline import Pipeline
from sqlmodel import select, func
import httpx

@router.get("/workspace/{workspace_id}/ai-summary")
async def get_workspace_ai_summary(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """
    Generate an AI-powered summary of the workspace health and active threats.
    Queries repository count, average health score, active alerts, and running pipelines.
    Sends this state to Gemini and returns a concise, actionable summary.
    """
    # 1. Gather real metrics for the workspace
    # Count repos in workspace
    repo_count_result = await session.execute(
        select(func.count()).select_from(Repo).where(Repo.workspace_id == workspace_id)
    )
    total_repos = repo_count_result.scalar() or 0

    # Calculate average health score
    health_result = await session.execute(
        select(func.avg(Repo.health_score)).where(Repo.workspace_id == workspace_id)
    )
    avg_health = health_result.scalar()
    avg_health_rounded = round(float(avg_health), 1) if avg_health is not None else 100.0

    # Get list of repo IDs in workspace to filter alerts and pipelines
    repos_in_ws_result = await session.execute(
        select(Repo.id).where(Repo.workspace_id == workspace_id)
    )
    repo_ids = [r for r in repos_in_ws_result.scalars().all()]

    active_alerts = 0
    running_pipelines = 0

    if repo_ids:
        # Count open alerts
        alerts_result = await session.execute(
            select(func.count()).select_from(Alert).where(
                Alert.repo_id.in_(repo_ids),
                Alert.resolved == False
            )
        )
        active_alerts = alerts_result.scalar() or 0

        # Count running pipelines
        pipelines_result = await session.execute(
            select(func.count()).select_from(Pipeline).where(
                Pipeline.repo_id.in_(repo_ids),
                Pipeline.status == "running"
            )
        )
        running_pipelines = pipelines_result.scalar() or 0

    # 2. Check if GEMINI_API_KEY is configured
    if not settings.GEMINI_API_KEY:
        # Fallback to local mock summary if API key is not set
        return (
            f"Based on {total_repos} tracked clusters, the system health is {avg_health_rounded}%. "
            f"Resolve {active_alerts} pending alerts to optimize performance."
        )

    # 3. Request Gemini API securely
    prompt = (
        f"Analyze the following DevOps metrics and provide a 2-sentence actionable insight: "
        f"Repos: {total_repos}, Avg Health: {avg_health_rounded}%, "
        f"Active Alerts: {active_alerts}, Running Pipelines: {running_pipelines}."
    )
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "systemInstruction": {
            "parts": [{"text": "You are a DevOps Intelligence Expert. Provide very concise, technical, and actionable insights. Do not use bold markdown."}]
        },
        "generationConfig": {
            "temperature": 0.7
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            res_data = response.json()
            # Extract text safely
            candidates = res_data.get("candidates", [])
            if candidates:
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if text:
                    return text.strip()
            return "Failed to generate AI insights."
    except Exception as e:
        # Graceful fallback on HTTP errors / API key failures
        return (
            f"Security protocol suggests optimizing pipeline concurrency to reduce the "
            f"{100.0 - avg_health_rounded:.1f}% health gap in the workspace."
        )

