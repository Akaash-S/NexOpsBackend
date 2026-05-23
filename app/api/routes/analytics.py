"""
Analytics Routes
"""

import asyncio
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func
from sqlmodel import select
from typing import List

from datetime import datetime
from app.core.database import get_session
from app.core.security import get_current_user
from app.core.redis import get_cached_data, set_cached_data
from app.models.repo import Repo
from app.models.alert import Alert
from app.models.event import Event
from app.models.pipeline import Pipeline
from app.schemas.analytics_schema import DashboardStats, ActivityResponse, ActivityPoint, DashboardSummary

router = APIRouter(prefix="/analytics", tags=["Analytics"])

async def _calculate_dashboard_stats(session: AsyncSession) -> DashboardStats:
    """Calculate aggregated top-level metrics in a single database round-trip."""
    avg_health_sub = select(func.avg(Repo.health_score)).scalar_subquery()
    alerts_sub = select(func.count(Alert.id)).where(
        Alert.resolved == False,
        Alert.severity.in_(["critical", "high"])
    ).scalar_subquery()
    
    pipeline_success_sub = select(func.count(Pipeline.id)).where(
        Pipeline.status == "success"
    ).scalar_subquery()
    pipeline_total_sub = select(func.count(Pipeline.id)).where(
        Pipeline.status.in_(["success", "failed"])
    ).scalar_subquery()
    
    running_sub = select(func.count(Pipeline.id)).where(
        Pipeline.status == "running"
    ).scalar_subquery()

    query = select(
        avg_health_sub.label("avg_health"),
        alerts_sub.label("vulnerability_index"),
        pipeline_success_sub.label("pipeline_success"),
        pipeline_total_sub.label("pipeline_total"),
        running_sub.label("running_count")
    )
    result = await session.execute(query)
    row = result.first()
    
    avg_health = float(row.avg_health) if row and row.avg_health is not None else 100.0
    vulnerability_index = row.vulnerability_index if row and row.vulnerability_index is not None else 0
    p_success = row.pipeline_success or 0
    p_total = row.pipeline_total or 0
    running_count = row.running_count or 0
    
    success_rate = (p_success / p_total * 100) if p_total > 0 else 100.0
    infra_load = min((running_count / 20) * 100, 100.0)
    
    return DashboardStats(
        avg_health=round(avg_health, 1),
        success_rate=round(success_rate, 1),
        vulnerability_index=vulnerability_index,
        infrastructure_load=round(infra_load, 1)
    )

@router.get("/dashboard/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    workspace_id: str = Query(None),
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """
    Get all dashboard data in a single request, cached in Redis.
    Combines stats, repos, alerts, and clusters into one response.
    """
    workspace_key = workspace_id if workspace_id else "all"
    cache_key = f"cache:dashboard:summary:{workspace_key}"
    
    cached = await get_cached_data(cache_key)
    if cached:
        return DashboardSummary(**cached)

    from app.models.cluster import Cluster
    from app.services.repo_service import get_repos
    from app.services.alert_service import get_alerts
    from app.services.cluster_service import get_clusters
    
    # Execute database queries
    repos = await get_repos(session, workspace_id=workspace_id, limit=100)
    alerts = await get_alerts(session, resolved=False, limit=50)
    clusters = await get_clusters(session, workspace_id) if workspace_id else []
    
    # Calculate stats using consolidated database aggregates
    stats = await _calculate_dashboard_stats(session)
    
    summary = DashboardSummary(
        stats=stats,
        repos=repos,
        alerts=alerts,
        clusters=clusters
    )
    
    # Cache the result in Redis with 30s TTL
    await set_cached_data(cache_key, summary.model_dump(), ttl=30)
    return summary

@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Get aggregated top-level metrics for the dashboard, cached in Redis."""
    cache_key = "cache:dashboard:stats"
    cached = await get_cached_data(cache_key)
    if cached:
        return DashboardStats(**cached)

    stats = await _calculate_dashboard_stats(session)
    await set_cached_data(cache_key, stats.model_dump(), ttl=30)
    return stats

@router.get("/activity", response_model=ActivityResponse)
async def get_activity_data(
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Get real time-series data for velocity charts from the Events table, cached in Redis."""
    cache_key = "cache:dashboard:activity"
    cached = await get_cached_data(cache_key)
    if cached:
        return ActivityResponse(**cached)

    from datetime import timedelta
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=6) # 7 days including today

    # Fetch events from the last 7 days
    result = await session.execute(
        select(Event).where(Event.created_at >= seven_days_ago).order_by(Event.created_at.asc())
    )
    events = result.scalars().all()

    # Create an ordered list of the last 7 days
    day_labels = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
    last_7_days_labels = []
    activity_map: dict = {}

    for i in range(7):
        date = seven_days_ago + timedelta(days=i)
        day_name = day_labels[date.weekday()]
        full_label = f"{day_name} {date.strftime('%d/%m')}"
        last_7_days_labels.append(full_label)
        activity_map[full_label] = {"name": full_label, "commits": 0, "issues": 0, "deployed": 0, "_date": date.date()}

    for event in events:
        event_date = event.created_at.date()
        for label, data in activity_map.items():
            if data["_date"] == event_date:
                if "repo.updated" in event.type or "push" in event.type:
                    data["commits"] += 1
                elif "issue" in event.type or "pr.opened" in event.type:
                    data["issues"] += 1
                elif "deploy.success" in event.type or "ci.success" in event.type:
                    data["deployed"] += 1
                break

    ordered_points = [
        ActivityPoint(name=activity_map[label]["name"], commits=activity_map[label]["commits"],
                      issues=activity_map[label]["issues"], deployed=activity_map[label]["deployed"])
        for label in last_7_days_labels
    ]

    response_data = ActivityResponse(data=ordered_points)
    await set_cached_data(cache_key, response_data.model_dump(), ttl=30)
    return response_data
