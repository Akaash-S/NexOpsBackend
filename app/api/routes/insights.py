"""
Insights Routes
Intelligence & analytics endpoints.
"""

import logging

logger = logging.getLogger("nexops")

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
from sqlmodel import SQLModel, select, func
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


class AIQueryRequest(SQLModel):
    question: str


from app.models.incident import Incident


@router.post("/workspace/{workspace_id}/ai-query")
async def query_workspace_ai(
    workspace_id: str,
    payload: AIQueryRequest,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """
    Interact with the conversational DevOps Co-Pilot.
    Gathers workspace context (repos, alerts, pipelines, incidents) and queries Gemini.
    """
    # 1. Gather context
    # Get repos in workspace
    repos_result = await session.execute(
        select(Repo).where(Repo.workspace_id == workspace_id)
    )
    repos = list(repos_result.scalars().all())
    repo_ids = [r.id for r in repos]
    repo_names = {r.id: r.name for r in repos}

    # Get active incidents
    incidents = []
    if repo_ids:
        incidents_result = await session.execute(
            select(Incident).where(
                Incident.root_cause_repo_id.in_(repo_ids),
                Incident.status != "resolved"
            )
        )
        incidents = list(incidents_result.scalars().all())

    # Get unresolved alerts
    alerts = []
    if repo_ids:
        alerts_result = await session.execute(
            select(Alert).where(
                Alert.repo_id.in_(repo_ids),
                Alert.resolved == False
            )
        )
        alerts = list(alerts_result.scalars().all())

    # Get recent/active pipelines
    pipelines = []
    if repo_ids:
        pipelines_result = await session.execute(
            select(Pipeline).where(
                Pipeline.repo_id.in_(repo_ids)
            ).order_by(Pipeline.created_at.desc()).limit(10)
        )
        pipelines = list(pipelines_result.scalars().all())

    # 2. Build detailed technical context block
    context_lines = []
    context_lines.append("Workspace metrics:")
    context_lines.append(f"- Total tracked repositories: {len(repos)}")
    for r in repos:
        context_lines.append(f"  * {r.name}: status={r.ci_status}, healthScore={r.health_score}%")

    context_lines.append("- Active Incidents:")
    if not incidents:
        context_lines.append("  * None")
    for inc in incidents:
        context_lines.append(f"  * {inc.title}: severity={inc.severity}, status={inc.status}, impact={inc.impact_summary}")

    context_lines.append("- Active Unresolved Alerts:")
    if not alerts:
        context_lines.append("  * None")
    for a in alerts:
        repo_name = repo_names.get(a.repo_id, "unknown")
        context_lines.append(f"  * {repo_name}: {a.message} (severity={a.severity}, category={a.category})")

    context_lines.append("- Recent Pipelines:")
    if not pipelines:
        context_lines.append("  * None")
    for p in pipelines:
        repo_name = repo_names.get(p.repo_id, "unknown")
        context_lines.append(f"  * {repo_name}: pipeline={p.name}, branch={p.branch}, status={p.status}")

    context_text = "\n".join(context_lines)

    # 3. Request Gemini API if configured
    if not settings.GEMINI_API_KEY:
        # Fallback local smart response matching keywords
        q = payload.question.lower()
        if "repo" in q or "repository" in q or "failing" in q:
            failing_repos = [r.name for r in repos if r.ci_status != "passing"]
            if failing_repos:
                return f"Currently, the repository {', '.join(failing_repos)} is failing or requires attention. System health stands at {repos[0].health_score}%."
            return "All repositories in the workspace are currently in a healthy, passing status."
        elif "alert" in q or "threat" in q or "security" in q:
            if alerts:
                alert_list = [f"'{a.message}' in {repo_names.get(a.repo_id)}" for a in alerts]
                return f"There are {len(alerts)} unresolved alerts in the workspace: {', '.join(alert_list)}."
            return "No unresolved alerts detected in this workspace. The security perimeter is secure."
        elif "pipeline" in q or "velocity" in q or "deploy" in q:
            running = [p.name for p in pipelines if p.status == "running"]
            failed = [p.name for p in pipelines if p.status == "failed"]
            resp = "Recent deployments show normal activity. "
            if running:
                resp += f"Pipelines currently running: {', '.join(running)}. "
            if failed:
                resp += f"Recent failures: {', '.join(failed)}. "
            return resp
        elif "incident" in q or "break" in q:
            if incidents:
                inc_list = [f"'{i.title}' (Severity: {i.severity})" for i in incidents]
                return f"Active incidents under investigation: {', '.join(inc_list)}."
            return "No active incidents are open. All services are running optimally."
        
        # General response
        avg_health = sum(r.health_score for r in repos)/len(repos) if repos else 100.0
        return (
            f"Workspace '{workspace_id}' is operating at an average health of "
            f"{avg_health:.1f}%. Active concerns: {len(alerts)} alerts and {len(incidents)} open incidents. "
            "Please configure GEMINI_API_KEY to enable full conversational DevOps insights."
        )

    # Call real Gemini
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
    system_instruction = (
        "You are an expert DevOps Intelligence Co-Pilot named NexOps AI. "
        "Your task is to answer the developer's question based strictly on the provided workspace telemetry context. "
        "Be extremely technical, clear, and actionable. Keep your answer under 4 sentences. "
        "Do not use bold markdown formatting."
    )
    prompt = (
        f"Workspace Context:\n{context_text}\n\n"
        f"Developer Question: {payload.question}"
    )
    payload_data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "systemInstruction": {
            "parts": [{"text": system_instruction}]
        },
        "generationConfig": {
            "temperature": 0.5
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload_data)
            response.raise_for_status()
            res_data = response.json()
            candidates = res_data.get("candidates", [])
            if candidates:
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if text:
                    return text.strip()
            return "No response could be generated from the AI model."
    except Exception as e:
        logger.error(f"Gemini API query error: {e}")
        return f"Co-Pilot encountered an interface connection issue while generating response: {str(e)}"


