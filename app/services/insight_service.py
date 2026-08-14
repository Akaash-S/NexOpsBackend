"""
Insight Service
Intelligence layer that calculates health scores and provides analytical data.
"""

import logging
from typing import Optional
from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from app.models.repo import Repo
from app.models.alert import Alert
from app.models.deployment import Deployment
from app.models.event import Event

logger = logging.getLogger("nexops.insights")


async def calculate_health_score(session: AsyncSession, repo_id: str) -> Optional[float]:
    """
    Calculate a dynamic health score for a repository.
    
    Formula:
        health_score = (ci_success_rate * 0.4) + (commit_activity * 0.3) + (issue_health * 0.3)
    
    Penalties:
        - Critical alerts: -15 each
        - High alerts: -8 each
        - Medium alerts: -3 each
        - Low alerts: -1 each
    """
    repo = await session.get(Repo, repo_id)
    if not repo:
        return None

    # ── Factor 1: CI Success Rate (40% weight) ──────────────────────────
    pipeline_query = select(Deployment).where(
        Deployment.repo_id == repo_id,
        Deployment.status.in_(["success", "failed"]),
    ).order_by(Deployment.deployed_at.desc()).limit(20)
    pipeline_result = await session.execute(pipeline_query)
    recent_pipelines = list(pipeline_result.scalars().all())

    if recent_pipelines:
        success_count = sum(1 for p in recent_pipelines if p.status == "success")
        ci_success_rate = (success_count / len(recent_pipelines)) * 100
    else:
        if getattr(repo, 'ci_status', 'unknown') == 'failing':
            ci_success_rate = 0.0
        elif getattr(repo, 'ci_status', 'unknown') == 'passing':
            ci_success_rate = 100.0
        else:
            ci_success_rate = 50.0  # Unverified baseline neutral score (not silent 100%)

    # ── Factor 2: Commit Activity (30% weight) ──────────────────────────
    # Based on repo.activity (0-100 scale from external data)
    commit_activity = repo.activity

    # ── Factor 3: Issue Health (30% weight) ──────────────────────────────
    # Calculate based on active alert count and severity
    alert_query = select(Alert).where(
        Alert.repo_id == repo_id,
        Alert.resolved == False,
    )
    alert_result = await session.execute(alert_query)
    active_alerts = list(alert_result.scalars().all())

    alert_penalty = 0
    for alert in active_alerts:
        if alert.severity == "critical":
            alert_penalty += 15
        elif alert.severity == "high":
            alert_penalty += 8
        elif alert.severity == "medium":
            alert_penalty += 3
        else:
            alert_penalty += 1

    issue_health = max(0, 100 - alert_penalty)

    # ── Composite Score ──────────────────────────────────────────────────
    health_score = (
        (ci_success_rate * 0.4)
        + (commit_activity * 0.3)
        + (issue_health * 0.3)
    )
    health_score = round(max(0, min(100, health_score)), 1)

    # ── Factor 4: Active Incident Cap ─────────────────────────────────────
    from app.models.incident import Incident
    from app.models.candidate_cause import CandidateCause

    inc_query = select(Incident).where(
        Incident.status.in_(["open", "investigating"]),
        (Incident.workspace_id == repo.workspace_id) | (Incident.workspace_id == "default-workspace")
    )
    inc_result = await session.execute(inc_query)
    active_incidents = list(inc_result.scalars().all())

    has_active_incident = False
    for inc in active_incidents:
        if inc.root_cause_repo_id == repo_id or (inc.impacted_repos and repo_id in inc.impacted_repos):
            has_active_incident = True
            break

    if not has_active_incident and active_incidents:
        inc_ids = [inc.id for inc in active_incidents]
        cc_res = await session.execute(
            select(CandidateCause).where(
                CandidateCause.incident_id.in_(inc_ids),
                CandidateCause.repo_id == repo_id
            )
        )
        if cc_res.scalars().first():
            has_active_incident = True

    if has_active_incident:
        health_score = min(health_score, 45.0)
        repo.ci_status = "failing"

    # Update the repo record
    repo_name = repo.name
    repo.health_score = health_score
    repo.updated_at = datetime.utcnow()
    session.add(repo)
    await session.commit()

    logger.info(f"Health score for {repo_name}: {health_score} "
                f"(CI: {ci_success_rate:.0f}, Activity: {commit_activity:.0f}, Issues: {issue_health:.0f}, ActiveIncident: {has_active_incident})")
    return health_score


async def get_repo_insights(session: AsyncSession, repo_id: str) -> Optional[dict]:
    """
    Generate a comprehensive insight report for a repository.
    This powers the frontend's "Intelligence Insights" panel.
    """
    repo = await session.get(Repo, repo_id)
    if not repo:
        return None

    # Active alerts breakdown
    alert_query = select(Alert).where(Alert.repo_id == repo_id, Alert.resolved == False)
    alert_result = await session.execute(alert_query)
    active_alerts = list(alert_result.scalars().all())

    alert_breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for alert in active_alerts:
        if alert.severity in alert_breakdown:
            alert_breakdown[alert.severity] += 1

    # Recent pipeline stats using deployments
    pipeline_query = select(Deployment).where(
        Deployment.repo_id == repo_id
    ).order_by(Deployment.deployed_at.desc()).limit(10)
    pipeline_result = await session.execute(pipeline_query)
    recent_pipelines = list(pipeline_result.scalars().all())

    pipeline_stats = {
        "total": len(recent_pipelines),
        "success": sum(1 for p in recent_pipelines if p.status == "success"),
        "failed": sum(1 for p in recent_pipelines if p.status == "failed"),
        "running": sum(1 for p in recent_pipelines if p.status == "running"),
        "avg_duration": round(
            sum((p.finished_at - p.deployed_at).total_seconds() for p in recent_pipelines if p.finished_at)
            / max(sum(1 for p in recent_pipelines if p.finished_at), 1)
        ) if any(p.finished_at for p in recent_pipelines) else None,
    }

    # Recent event count (last 24h)
    day_ago = datetime.utcnow() - timedelta(hours=24)
    event_query = select(func.count()).select_from(Event).where(
        Event.repo_id == repo_id,
        Event.created_at >= day_ago,
    )
    event_result = await session.execute(event_query)
    recent_event_count = event_result.scalar()

    # Check if this repo is the root cause of an active incident
    from app.models.incident import Incident
    incident_query = select(Incident).where(
        Incident.root_cause_repo_id == repo_id,
        Incident.status == "open"
    ).order_by(Incident.created_at.desc()).limit(1)
    incident_result = await session.execute(incident_query)
    active_incident = incident_result.scalar_one_or_none()
    
    impact_info = None
    if active_incident:
        impact_info = {
            "incident_id": active_incident.id,
            "impacted_count": len(active_incident.impacted_repos or []),
            "severity": active_incident.severity
        }

    # Generate recommendation
    recommendation = _generate_recommendation(repo, active_alerts, pipeline_stats, impact_info)

    return {
        "repo_id": repo.id,
        "repo_name": repo.name,
        "health_score": repo.health_score,
        "ci_status": repo.ci_status,
        "activity": repo.activity,
        "vulnerabilities": repo.vulnerabilities,
        "alerts": {
            "active_count": len(active_alerts),
            "breakdown": alert_breakdown,
        },
        "pipelines": pipeline_stats,
        "events_24h": recent_event_count,
        "recommendation": recommendation,
        "factors": [
            {
                "label": "Security Posture",
                "value": f"{repo.vulnerabilities} findings" if repo.vulnerabilities else "Clean",
                "impact": "negative" if repo.vulnerabilities and repo.vulnerabilities > 0 else "positive",
            },
            {
                "label": "Operational Health",
                "value": f"{len(active_alerts)} active alerts",
                "impact": "negative" if len(active_alerts) > 3 else "neutral" if len(active_alerts) > 0 else "positive",
            },
            {
                "label": "CI/CD Stability",
                "value": repo.ci_status,
                "impact": "negative" if repo.ci_status == "failing" else "positive" if repo.ci_status == "passing" else "neutral",
            },
            {
                "label": "Development Velocity",
                "value": "High" if repo.activity > 70 else "Moderate" if repo.activity > 30 else "Stale",
                "impact": "negative" if repo.activity < 20 else "positive",
            },
        ],
    }


def _generate_recommendation(repo: Repo, alerts: list, pipeline_stats: dict, impact_info: Optional[dict] = None) -> dict:
    """Generate an actionable recommendation based on current state."""
    critical_count = sum(1 for a in alerts if a.severity == "critical")
    high_count = sum(1 for a in alerts if a.severity == "high")

    if impact_info and impact_info["severity"] in ["high", "critical"]:
        return {
            "urgency": "critical",
            "title": "Systemic Impact Detected",
            "message": f"This repository is the root cause of a cascading failure affecting {impact_info['impacted_count']} downstream services.",
            "action": "Initiate rollback of the latest deployment or configuration change immediately.",
        }
    
    if critical_count > 0:
        return {
            "urgency": "critical",
            "title": "Immediate Intervention Required",
            "message": f"{critical_count} critical alert(s) detected. Production stability may be at risk.",
            "action": "Triage critical alerts and initiate incident response.",
        }
    elif repo.ci_status == "failing":
        return {
            "urgency": "high",
            "title": "CI Pipeline Requires Attention",
            "message": "The latest CI pipeline has failed. Merges are blocked until resolved.",
            "action": "Review build logs and fix failing tests.",
        }
    elif high_count > 2:
        return {
            "urgency": "medium",
            "title": "Growing Alert Backlog",
            "message": f"{high_count} high-severity alerts are unresolved. Consider scheduling a triage session.",
            "action": "Prioritize and assign high-severity alerts.",
        }
    elif repo.activity < 20:
        return {
            "urgency": "low",
            "title": "Repository Appears Stale",
            "message": "Development activity has dropped significantly. Consider archiving or reassigning ownership.",
            "action": "Review repository ownership and roadmap.",
        }
    else:
        return {
            "urgency": "none",
            "title": "System Healthy",
            "message": "All metrics are within normal operating parameters.",
            "action": "Continue routine monitoring.",
        }
