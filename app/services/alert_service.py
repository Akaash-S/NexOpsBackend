"""
Alert Service
Business logic for alert creation, querying, and resolution.
"""

from datetime import datetime
from typing import Optional, List
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.schemas.alert_schema import AlertCreate


async def create_alert(session: AsyncSession, data: AlertCreate) -> Alert:
    """Create a new alert record."""
    alert = Alert(
        title=data.title,
        message=data.message,
        severity=data.severity,
        category=data.type,  # Mapped from 'type' in schema
        repo_id=data.repoId,  # Mapped from 'repoId' in schema
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
    repo_id: Optional[str] = None,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Alert]:
    """Fetch alerts with filtering."""
    query = select(Alert)
    if repo_id:
        query = query.where(Alert.repo_id == repo_id)
    if severity:
        query = query.where(Alert.severity == severity)
    if resolved is not None:
        query = query.where(Alert.resolved == resolved)
    query = query.order_by(Alert.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def resolve_alert(session: AsyncSession, alert_id: str) -> Optional[Alert]:
    """Mark an alert as resolved."""
    alert = await session.get(Alert, alert_id)
    if not alert:
        return None
    alert.resolved = True
    alert.resolved_at = datetime.utcnow()
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def acknowledge_alert(session: AsyncSession, alert_id: str) -> Optional[Alert]:
    """Acknowledge an alert without resolving it."""
    alert = await session.get(Alert, alert_id)
    if not alert:
        return None
    alert.acknowledged = True
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def get_alert_counts(session: AsyncSession, repo_id: Optional[str] = None) -> dict:
    """Get alert count breakdown by severity."""
    query = select(Alert).where(Alert.resolved == False)
    if repo_id:
        query = query.where(Alert.repo_id == repo_id)
    result = await session.execute(query)
    alerts = list(result.scalars().all())

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": len(alerts)}
    for alert in alerts:
        if alert.severity in counts:
            counts[alert.severity] += 1
    return counts
