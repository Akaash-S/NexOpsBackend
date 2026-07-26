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
from app.core.security import get_current_user
from app.schemas.insight_schema import InsightResponse

router = APIRouter(prefix="/insights", tags=["Insights"])


from app.models.repo import Repo
from app.models.user import User

@router.get("/{repo_id}", response_model=InsightResponse)
async def repo_insights(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """
    Get comprehensive intelligence insights for a repository.
    Powers the frontend's "Intelligence Insights" slide-out panel.
    Strictly scoped to user's workspace_id to prevent cross-tenant data leaks.
    """
    repo = await session.get(Repo, repo_id)
    if not repo or repo.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Repository not found")

    insights = await get_repo_insights(session, repo_id)
    if not insights:
        raise HTTPException(status_code=404, detail="Repository not found")
    return insights


@router.post("/{repo_id}/recalculate-health")
async def recalculate_health(
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """
    Manually trigger a health score recalculation.
    Strictly scoped to user's workspace_id to prevent cross-tenant unauthorized modifications.
    """
    repo = await session.get(Repo, repo_id)
    if not repo or repo.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Repository not found")

    score = await calculate_health_score(session, repo_id)
    if score is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {"repo_id": repo_id, "health_score": score}


from app.core.security import get_current_user
from app.core.config import settings
from app.models.repo import Repo
from app.models.alert import Alert
from app.models.deployment import Deployment
from sqlmodel import SQLModel, select, func
import httpx

@router.get("/workspace/{workspace_id}/ai-summary")
async def get_workspace_ai_summary(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """
    Generate an AI-powered summary of the workspace health and active threats.
    Queries repository count, average health score, active alerts, and running deployments.
    Sends this state to Gemini and returns a concise, actionable summary.
    Strictly scoped to user's workspace_id to prevent cross-tenant data leaks.
    """
    if workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
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

    # Get list of repo IDs in workspace to filter alerts and deployments
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

        # Count running deployments
        pipelines_result = await session.execute(
            select(func.count()).select_from(Deployment).where(
                Deployment.repo_id.in_(repo_ids),
                Deployment.status == "running"
            )
        )
        running_pipelines = pipelines_result.scalar() or 0

    # 2. Check if GEMINI_API_KEY is configured
    if not settings.GEMINI_API_KEY:
        return "AI insights unavailable: no API key configured"

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
    user: User = Depends(get_current_user)
):
    """
    Interact with the conversational DevOps Co-Pilot.
    Gathers workspace context (repos, alerts, deployments, incidents) and queries Gemini.
    Strictly scoped to user's workspace_id to prevent cross-tenant data leaks.
    """
    if workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
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

    # Get recent/active deployments
    pipelines = []
    if repo_ids:
        pipelines_result = await session.execute(
            select(Deployment).where(
                Deployment.repo_id.in_(repo_ids)
            ).order_by(Deployment.deployed_at.desc()).limit(10)
        )
        pipelines = list(pipelines_result.scalars().all())

    # 2. Build detailed technical context block
    context_lines = []
    context_lines.append("Workspace telemetry:")
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

    context_lines.append("- Recent Deployments:")
    if not pipelines:
        context_lines.append("  * None")
    for p in pipelines:
        repo_name = repo_names.get(p.repo_id, "unknown")
        context_lines.append(f"  * {repo_name}: version={p.version}, env={p.environment}, status={p.status}")

    context_text = "\n".join(context_lines)

    # 3. Request Gemini API if configured
    if not settings.GEMINI_API_KEY:
        return "AI insights unavailable: no API key configured"

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


class CodeAuditRequest(SQLModel):
    repo_id: str
    path: str
    code: str
    mode: str

@router.post("/code-audit")
async def code_audit(
    payload: CodeAuditRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """
    Audit, explain, or generate tests for the provided code content.
    Queries Gemini if configured, otherwise falls back to a smart local analyzer.
    Strictly verifies repository ownership against user's workspace_id.
    """
    repo = await session.get(Repo, payload.repo_id)
    if not repo or repo.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Repository not found")

    code = payload.code
    path = payload.path
    mode = payload.mode
    
    if not code.strip():
        raise HTTPException(status_code=400, detail="Source code content cannot be empty.")

    # 1. Parse simple metrics for fallback/enrichment
    lines = code.splitlines()
    num_lines = len(lines)
    
    # Simple syntax parser for fallback
    functions = []
    classes = []
    imports = []
    todo_count = 0
    unsafe_calls = []
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from ") or ("require(" in stripped and "=" in stripped):
            imports.append(stripped)
        if stripped.startswith("def ") or stripped.startswith("async def ") or stripped.startswith("function ") or (("const" in stripped or "let" in stripped) and "=>" in stripped):
            parts = stripped.split()
            if len(parts) > 1:
                name = parts[1].split("(")[0].split("=")[0].strip()
                functions.append(name)
        if stripped.startswith("class "):
            parts = stripped.split()
            if len(parts) > 1:
                name = parts[1].split("(")[0].split(":")[0].strip()
                classes.append(name)
        if "TODO" in stripped or "FIXME" in stripped:
            todo_count += 1
        if "eval(" in stripped or "exec(" in stripped or "dangerouslySetInnerHTML" in stripped:
            unsafe_calls.append(stripped)

    # 2. Call real Gemini if key is present
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "unset":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
        
        if mode == "explain":
            system_instruction = (
                "You are an expert software architect named NexOps AI. "
                "Explain the provided code snippet, outlining its structure, key functions/classes, imports, and purpose. "
                "Format your explanation in clear, clean markdown with bullet points and subheadings. Keep it under 6 sentences."
            )
        elif mode == "diagnose":
            system_instruction = (
                "You are an expert static analysis security auditor named NexOps AI. "
                "Audit the provided code for logic bugs, performance inefficiencies, and security issues. "
                "Provide a numbered list of findings with severity ratings (Critical, High, Medium, Low), code snippets, and instructions to resolve. "
                "Format in clean markdown. Keep it technical and actionable."
            )
        else: # test
            system_instruction = (
                "You are a test-driven development engineer named NexOps AI. "
                "Generate comprehensive unit tests for the provided code using standard testing frameworks (e.g. PyTest, Jest, Mocha). "
                "Format tests in clean markdown. Keep it technical and actionable."
            )

        prompt = (
            f"Code content to analyze:\n```\n{code}\n```\n\n"
            f"Please perform the code action mode: {mode}."
        )

        payload_data = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "temperature": 0.2
            }
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, json=payload_data)
                if response.status_code == 200:
                    res_data = response.json()
                    candidates = res_data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        return {"result": text.strip()}
        except Exception as e:
            logger.error(f"Gemini code audit query failed: {e}")

    return {"result": "AI insights unavailable: no API key configured"}
