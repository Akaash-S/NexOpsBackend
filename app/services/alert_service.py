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
    if user_id:
        repo = await session.get(Repo, data.repo_id)
        if not repo or repo.user_id != user_id:
            raise ValueError("Repository not found or access denied")

    alert = Alert(
        title=data.title,
        message=data.message,
        severity=data.severity,
        category=data.category,  # Direct field, no alias needed
        repo_id=data.repo_id,
        event_id=data.event_id,
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
    alert = Alert(
        title=title,
        message=message,
        severity=severity,
        category=category,
        repo_id=repo_id,
        event_id=event_id,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def get_alerts(
    session: AsyncSession,
    user_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Alert]:
    """Fetch alerts with filtering, optionally scoped to a user."""
    query = select(Alert)
    if user_id:
        query = query.join(Repo, Alert.repo_id == Repo.id).where(Repo.user_id == user_id)
    if repo_id:
        query = query.where(Alert.repo_id == repo_id)
    if severity:
        query = query.where(Alert.severity == severity)
    if resolved is not None:
        query = query.where(Alert.resolved == resolved)
    query = query.order_by(Alert.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def resolve_alert(session: AsyncSession, alert_id: str, user_id: Optional[str] = None) -> Optional[Alert]:
    """Mark an alert as resolved, optionally scoped to a user's repositories."""
    query = select(Alert).where(Alert.id == alert_id)
    if user_id:
        query = query.join(Repo, Alert.repo_id == Repo.id).where(Repo.user_id == user_id)
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


async def acknowledge_alert(session: AsyncSession, alert_id: str, user_id: Optional[str] = None) -> Optional[Alert]:
    """Acknowledge an alert without resolving it, optionally scoped to a user's repositories."""
    query = select(Alert).where(Alert.id == alert_id)
    if user_id:
        query = query.join(Repo, Alert.repo_id == Repo.id).where(Repo.user_id == user_id)
    result = await session.execute(query)
    alert = result.scalar_one_or_none()
    if not alert:
        return None
    alert.acknowledged = True
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def get_alert_counts(session: AsyncSession, user_id: Optional[str] = None, repo_id: Optional[str] = None) -> dict:
    """Get alert count breakdown by severity using a single optimized query, optionally scoped to a user."""
    from sqlalchemy import case
    
    query = select(
        func.count(Alert.id).label("total"),
        func.sum(case((Alert.severity == "critical", 1), else_=0)).label("critical"),
        func.sum(case((Alert.severity == "high", 1), else_=0)).label("high"),
        func.sum(case((Alert.severity == "medium", 1), else_=0)).label("medium"),
        func.sum(case((Alert.severity == "low", 1), else_=0)).label("low"),
    ).where(Alert.resolved == False)
    
    if user_id:
        query = query.join(Repo, Alert.repo_id == Repo.id).where(Repo.user_id == user_id)
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
