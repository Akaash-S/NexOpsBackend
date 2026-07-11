"""
Alert Service
Business logic for alert creation, querying, and resolution.
"""

from datetime import datetime
from typing import Optional, List
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, case

from app.models.alert import Alert
from app.models.repo import Repo
from app.schemas.alert_schema import AlertCreate


async def create_alert(session: AsyncSession, data: AlertCreate, user_id: Optional[str] = None) -> Alert:
    """Create a new alert record, optionally verifying repository ownership."""
    repo = await session.get(Repo, data.repo_id)
    if not repo:
        raise ValueError("Repository not found")
    if user_id and repo.user_id != user_id:
        raise ValueError("Repository not found or access denied")

    alert = Alert(
        title=data.title,
        message=data.message,
        severity=data.severity,
        category=data.category,  # Direct field, no alias needed
        repo_id=data.repo_id,
        event_id=data.event_id,
        workspace_id=repo.workspace_id,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def create_alert_from_rule(
    session: AsyncSession,
    repo_id: str,
    event_id: str,
    severity: str,
    title: str,
    message: str,
    category: str = "system",
) -> Alert:
    """Create an alert directly from automation engine (no schema validation needed)."""
    repo = await session.get(Repo, repo_id)
    if not repo:
        raise ValueError(f"Repository {repo_id} not found")
    alert = Alert(
        title=title,
        message=message,
        severity=severity,
        category=category,
        repo_id=repo_id,
        event_id=event_id,
        workspace_id=repo.workspace_id,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def get_alerts(
    session: AsyncSession,
    workspace_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Alert]:
    """Fetch alerts with filtering, optionally scoped to a workspace."""
    query = select(Alert)
    if workspace_id:
        query = query.where(Alert.workspace_id == workspace_id)
    if repo_id:
        query = query.where(Alert.repo_id == repo_id)
    if severity:
        query = query.where(Alert.severity == severity)
    if resolved is not None:
        query = query.where(Alert.resolved == resolved)
    query = query.order_by(Alert.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def resolve_alert(session: AsyncSession, alert_id: str, workspace_id: Optional[str] = None) -> Optional[Alert]:
    """Mark an alert as resolved, optionally scoped to a workspace."""
    query = select(Alert).where(Alert.id == alert_id)
    if workspace_id:
        query = query.where(Alert.workspace_id == workspace_id)
    result = await session.execute(query)
    alert = result.scalar_one_or_none()
    if not alert:
        return None
    alert.resolved = True
    alert.resolved_at = datetime.utcnow()
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def acknowledge_alert(session: AsyncSession, alert_id: str, workspace_id: Optional[str] = None) -> Optional[Alert]:
    """Acknowledge an alert without resolving it, optionally scoped to a workspace."""
    query = select(Alert).where(Alert.id == alert_id)
    if workspace_id:
        query = query.where(Alert.workspace_id == workspace_id)
    result = await session.execute(query)
    alert = result.scalar_one_or_none()
    if not alert:
        return None
    alert.acknowledged = True
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def get_alert_counts(session: AsyncSession, workspace_id: Optional[str] = None, repo_id: Optional[str] = None) -> dict:
    """Get alert count breakdown by severity using a single optimized query, optionally scoped to a workspace."""
    from sqlalchemy import case
    
    query = select(
        func.count(Alert.id).label("total"),
        func.sum(case((Alert.severity == "critical", 1), else_=0)).label("critical"),
        func.sum(case((Alert.severity == "high", 1), else_=0)).label("high"),
        func.sum(case((Alert.severity == "medium", 1), else_=0)).label("medium"),
        func.sum(case((Alert.severity == "low", 1), else_=0)).label("low"),
    ).where(Alert.resolved == False)
    
    if workspace_id:
        query = query.where(Alert.workspace_id == workspace_id)
    if repo_id:
        query = query.where(Alert.repo_id == repo_id)
    
    result = await session.execute(query)
    row = result.first()
    
    return {
        "total": row.total or 0,
        "critical": row.critical or 0,
        "high": row.high or 0,
        "medium": row.medium or 0,
        "low": row.low or 0,
    }


async def get_noisy_rules(session: AsyncSession, repo_id: str) -> List[str]:
    """
    Determine which alert rules (grouped by alert title) are noisy for a given repo.
    A rule is noisy if:
    - It triggered at least 3 times in the last 30 days.
    - The alerts under this rule rarely correlate with a confirmed incident (correlation rate < 20%).
    """
    from datetime import timedelta
    from app.models.candidate_cause import CandidateCause
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # Fetch alerts for this repo in last 30 days
    alert_query = select(Alert).where(Alert.repo_id == repo_id, Alert.created_at >= thirty_days_ago)
    alert_result = await session.execute(alert_query)
    alerts = list(alert_result.scalars().all())
    
    if not alerts:
        return []
        
    # Fetch confirmed causes for this repo in last 30 days
    cause_query = select(CandidateCause).where(
        CandidateCause.repo_id == repo_id,
        CandidateCause.confirmed == True,
        CandidateCause.created_at >= thirty_days_ago
    )
    cause_result = await session.execute(cause_query)
    confirmed_causes = list(cause_result.scalars().all())
    
    # Group alerts by title (rule name)
    grouped_alerts = {}
    for a in alerts:
        grouped_alerts.setdefault(a.title, []).append(a)
        
    noisy_rules = []
    for title, group in grouped_alerts.items():
        if len(group) < 3:
            continue
            
        correlated_count = 0
        for alert in group:
            # Check if there is any confirmed cause within 4 hours of the alert
            correlated = False
            for cause in confirmed_causes:
                time_diff = abs((cause.created_at - alert.created_at).total_seconds())
                if time_diff <= 4 * 3600:
                    correlated = True
                    break
            if correlated:
                correlated_count += 1
                
        correlation_rate = correlated_count / len(group)
        if correlation_rate < 0.20:
            noisy_rules.append(title)
            
    return noisy_rules

