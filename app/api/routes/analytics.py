"""
Analytics Routes
"""

import asyncio
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func
from sqlmodel import select
from typing import List

from datetime import datetime
from app.core.database import get_session
from app.core.security import get_current_user
from app.models.repo import Repo
from app.models.alert import Alert
from app.models.event import Event
from app.models.pipeline import Pipeline
from app.schemas.analytics_schema import DashboardStats, ActivityResponse, ActivityPoint

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Get aggregated top-level metrics for the dashboard using sequential execution."""
    # Run queries sequentially as AsyncSession is NOT thread-safe for concurrent calls
    # 1. Avg Health
    repos_result = await session.execute(select(Repo))
    repos = repos_result.scalars().all()
    avg_health = sum(r.health_score for r in repos) / len(repos) if repos else 100.0
    
    # 2. Vulnerability Index
    alerts_result = await session.execute(
        select(func.count(Alert.id)).where(
            Alert.resolved == False,
            Alert.severity.in_(["critical", "high"])
        )
    )
    vulnerability_index = alerts_result.scalar() or 0

    # 3. Success Rate
    pipeline_stats = await session.execute(
        select(
            func.count(Pipeline.id).label("total"),
            func.count().filter(Pipeline.status == "success").label("success")
        ).where(Pipeline.status.in_(["success", "failed"]))
    )
    p_stats = pipeline_stats.first()
    success_rate = (p_stats.success / p_stats.total * 100) if p_stats and p_stats.total > 0 else 100.0

    # 4. Infrastructure Load
    running_result = await session.execute(
        select(func.count(Pipeline.id)).where(Pipeline.status == "running")
    )
    running_count = running_result.scalar() or 0
    infra_load = min((running_count / 20) * 100, 100.0)
    
    return DashboardStats(
        avg_health=round(avg_health, 1),
        success_rate=round(success_rate, 1),
        vulnerability_index=vulnerability_index,
        infrastructure_load=round(infra_load, 1)
    )

@router.get("/activity", response_model=ActivityResponse)
async def get_activity_data(
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Get real time-series data for velocity charts from the Events table."""
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
    activity_map = {}
    
    for i in range(7):
        date = seven_days_ago + timedelta(days=i)
        day_name = day_labels[date.weekday()]
        # Format: "MON 24/04"
        full_label = f"{day_name} {date.strftime('%d/%m')}"
        last_7_days_labels.append(full_label)
        activity_map[full_label] = {"name": full_label, "commits": 0, "issues": 0, "deployed": 0, "raw_date": date.date()}

    for event in events:
        event_date = event.created_at.date()
        for label, data in activity_map.items():
            if data["raw_date"] == event_date:
                # Map event types to chart categories
                if "repo.updated" in event.type or "push" in event.type:
                    data["commits"] += 1
                elif "issue" in event.type or "pr.opened" in event.type:
                    data["issues"] += 1
                elif "deploy.success" in event.type or "ci.success" in event.type:
                    data["deployed"] += 1
                break

    # Return in the correct chronological order
    ordered_data = [activity_map[label] for label in last_7_days_labels]
    # Remove raw_date before returning
    for item in ordered_data:
        item.pop("raw_date", None)
    
    return ActivityResponse(data=ordered_data)
