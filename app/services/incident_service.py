"""
Incident Service
Handles incident lifecycle and alert grouping.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.alert import Alert
from app.models.repo import Repo

logger = logging.getLogger("nexops.incidents")

async def get_or_create_incident(
    session: AsyncSession, 
    repo_id: str, 
    severity: str, 
    title: str,
    impacted_repos: List[str] = []
) -> Incident:
    """
    Find an existing open incident in the same cluster within the last 30 mins, 
    or create a new one.
    """
    repo = await session.get(Repo, repo_id)
    cluster_id = repo.cluster_id if repo else None
    
    if cluster_id:
        # Check for existing open incident in the same cluster
        thirty_mins_ago = datetime.utcnow() - timedelta(minutes=30)
        query = select(Incident).where(
            Incident.cluster_id == cluster_id,
            Incident.status == "open",
            Incident.created_at >= thirty_mins_ago
        )
        result = await session.execute(query)
        existing_incident = result.scalar_one_or_none()
        
        if existing_incident:
            logger.info(f"Grouping alert into existing incident: {existing_incident.id}")
            # Add new impacted repos to existing list
            current_impacted = set(existing_incident.impacted_repos or [])
            current_impacted.update(impacted_repos)
            existing_incident.impacted_repos = list(current_impacted)
            session.add(existing_incident)
            return existing_incident

    # Create new incident
    new_incident = Incident(
        cluster_id=cluster_id,
        title=title,
        severity=severity,
        status="open",
        root_cause_repo_id=repo_id,
        impacted_repos=impacted_repos,
        started_at=datetime.utcnow()
    )
    session.add(new_incident)
    await session.flush()
    await session.refresh(new_incident)
    
    logger.info(f"Created new incident: {new_incident.id} (Cluster: {cluster_id})")
    return new_incident

async def resolve_incident(session: AsyncSession, incident_id: str):
    """Mark an incident and its associated alerts as resolved."""
    incident = await session.get(Incident, incident_id)
    if not incident:
        return
    
    incident.status = "resolved"
    incident.resolved_at = datetime.utcnow()
    session.add(incident)
    
    # Resolve alerts? (Optional, maybe alerts should be resolved individually)
    # For now, let's just mark the incident.
    
    await session.commit()
    return incident
