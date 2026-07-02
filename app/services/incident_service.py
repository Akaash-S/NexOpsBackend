"""
Incident Service
Handles incident lifecycle, alert grouping, and cause correlation.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlmodel import select
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.alert import Alert
from app.models.repo import Repo
from app.models.candidate_cause import CandidateCause
from app.models.event import Event
from app.models.dependency import Dependency

logger = logging.getLogger("nexops.incidents")

async def correlate_incident_causes(session: AsyncSession, incident: Incident):
    """
    Correlates past events/commits on the alerting repository and its dependencies
    within a 2-hour window. Saves the top 3 scored candidates in the candidate_causes table.
    """
    repo_id = incident.root_cause_repo_id
    if not repo_id:
        return
    
    # 1. Get dependency repository IDs (alerting repo depends on these)
    dep_query = select(Dependency).where(Dependency.source_repo_id == repo_id)
    dep_result = await session.execute(dep_query)
    dependencies = dep_result.scalars().all()
    dep_repo_ids = {dep.target_repo_id for dep in dependencies}
    
    candidate_repo_ids = {repo_id} | dep_repo_ids
    
    # 2. Query events in the 2-hour window before incident start
    two_hours_ago = incident.created_at - timedelta(hours=2)
    event_query = select(Event).where(
        Event.repo_id.in_(list(candidate_repo_ids)),
        Event.created_at >= two_hours_ago,
        Event.created_at <= incident.created_at
    )
    event_result = await session.execute(event_query)
    events = event_result.scalars().all()
    
    # 3. For each event, calculate point score
    scored_candidates = []
    ninety_days_ago = incident.created_at - timedelta(days=90)
    
    for event in events:
        score = 0.0
        reasons = []
        
        # Repository association
        if event.repo_id == repo_id:
            score += 35.0
            reasons.append("Same repository (+35)")
        elif event.repo_id in dep_repo_ids:
            score += 20.0
            reasons.append("Dependency repository (+20)")
            
        # Temporal proximity
        time_diff = (incident.created_at - event.created_at).total_seconds()
        if time_diff <= 900:  # 15 minutes
            score += 25.0
            reasons.append("Temporal proximity within 15 min (+25)")
        elif time_diff <= 3600:  # 60 minutes
            score += 15.0
            reasons.append("Temporal proximity within 15-60 min (+15)")
        elif time_diff <= 7200:  # 120 minutes
            score += 5.0
            reasons.append("Temporal proximity within 60-120 min (+5)")
            
        # Past confirmed cause within 90 days on this repository
        cc_query = select(CandidateCause).where(
            CandidateCause.repo_id == event.repo_id,
            CandidateCause.confirmed == True,
            CandidateCause.created_at >= ninety_days_ago
        )
        cc_result = await session.execute(cc_query)
        confirmed_past = cc_result.scalars().all()
        if confirmed_past:
            score += 15.0
            reasons.append("Past confirmed cause within 90 days (+15)")
            
        # Test score boost (for testing capping logic)
        if event.payload and "test_score_boost" in event.payload:
            score += float(event.payload["test_score_boost"])
            reasons.append(f"Test score boost (+{event.payload['test_score_boost']})")
            
        if score > 0:
            score = min(100.0, score)
            reason_str = ", ".join(reasons) + f". Total Score: {score}"
            scored_candidates.append({
                "event": event,
                "score": score,
                "reason": reason_str
            })
            
    # Deduplicate by repo_id keeping only the best score per repository
    best_per_repo: dict[str, dict] = {}
    for cand in scored_candidates:
        repo_id = cand["event"].repo_id
        if repo_id not in best_per_repo or cand["score"] > best_per_repo[repo_id]["score"]:
            best_per_repo[repo_id] = cand

    scored_candidates = list(best_per_repo.values())

    # Sort descending by score
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = scored_candidates[:3]
    
    # Save top candidates to database
    for cand in top_candidates:
        db_cand = CandidateCause(
            incident_id=incident.id,
            repo_id=cand["event"].repo_id,
            event_id=cand["event"].id,
            score=cand["score"],
            reason=cand["reason"],
            confirmed=None
        )
        session.add(db_cand)
        
    await session.flush()
    logger.info(f"Correlated {len(top_candidates)} candidate causes for incident {incident.id}")

async def get_or_create_incident(
    session: AsyncSession, 
    repo_id: str, 
    severity: str, 
    title: str,
    impacted_repos: List[str] = []
) -> Incident:
    """
    Find an existing open incident for the same repository within the last 30 mins, 
    or create a new one, protected by an advisory lock.
    """
    # Use repo_id hash as advisory lock key to prevent concurrent creation
    lock_key = abs(hash(repo_id)) % (2**31 - 1)
    await session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    # Check for existing open incident for this repository
    thirty_mins_ago = datetime.utcnow() - timedelta(minutes=30)
    query = select(Incident).where(
        Incident.root_cause_repo_id == repo_id,
        Incident.status == "open",
        Incident.created_at >= thirty_mins_ago
    )
    result = await session.execute(query)
    existing_incident = result.scalar_one_or_none()
    
    if existing_incident:
        logger.info(f"Grouping alert into existing incident: {existing_incident.id}")
        current_impacted = set(existing_incident.impacted_repos or [])
        current_impacted.update(impacted_repos)
        existing_incident.impacted_repos = list(current_impacted)
        session.add(existing_incident)
        await session.flush()
        return existing_incident

    # Create new incident
    new_incident = Incident(
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
    
    # Perform cause correlation scoring
    await correlate_incident_causes(session, new_incident)
    
    logger.info(f"Created new incident: {new_incident.id}")
    return new_incident

async def resolve_incident(session: AsyncSession, incident_id: str):
    """Mark an incident and its associated alerts as resolved."""
    incident = await session.get(Incident, incident_id)
    if not incident:
        return
    
    incident.status = "resolved"
    incident.resolved_at = datetime.utcnow()
    session.add(incident)
    
    await session.commit()
    return incident
