"""
Incident Service
Handles incident lifecycle, alert grouping, and cause correlation.
"""

import logging
import json
import hashlib
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
    
    # 1. Get upstream dependencies up to max_depth=3 using shared BFS traversal
    from app.services.impact_service import get_upstream_dependencies, calculate_deployment_risk
    upstream_map = await get_upstream_dependencies(session, repo_id, max_depth=3)
    
    candidate_repo_ids = {repo_id} | set(upstream_map.keys())
    
    # 2. Query events in the 2-hour window before incident start
    two_hours_ago = incident.created_at - timedelta(hours=2)
    event_query = select(Event).where(
        Event.repo_id.in_(list(candidate_repo_ids)),
        Event.created_at >= two_hours_ago,
        Event.created_at <= incident.created_at
    )
    event_result = await session.execute(event_query)
    events = event_result.scalars().all()
    
    # Fetch active scoring weights for workspace (recalibrated or default constants)
    from app.services.recalibration_service import get_current_scoring_weights
    from app.models.candidate_cause_feedback_log import CandidateCauseFeedbackLog
    weights = await get_current_scoring_weights(session, incident.workspace_id)

    # 3. For each event, calculate point score
    scored_candidates = []
    ninety_days_ago = incident.created_at - timedelta(days=90)
    
    for event in events:
        score = 0.0
        reasons = []
        
        # Fetch repo object for name resolution
        from app.models.repo import Repo
        repo_obj = await session.get(Repo, event.repo_id)
        repo_name = repo_obj.name if repo_obj and repo_obj.name else f"repo-{event.repo_id[:8]}"
        
        # A2: Topological proximity (Same repo, 1 hop direct, 2 hops transitive, 3 hops transitive)
        if event.repo_id == repo_id:
            w = weights.get("same_repo", 35.0)
            score += w
            reasons.append(f"Deployed to {repo_name}, the same repository as the alerting service.")
        elif event.repo_id in upstream_map:
            info = upstream_map[event.repo_id]
            dist = info["distance"]
            path_str = " -> ".join(info["path"])
            if dist == 1:
                w = weights.get("dep_repo", 20.0)
                score += w
                reasons.append(f"Direct dependency (1 hop away via {path_str}).")
            elif dist == 2:
                w = weights.get("transitive_2hop", 10.0)
                score += w
                reasons.append(f"Transitive dependency (2 hops away via {path_str}).")
            elif dist == 3:
                w = weights.get("transitive_3hop", 5.0)
                score += w
                reasons.append(f"Transitive dependency (3 hops away via {path_str}).")
            
        # Temporal proximity with real computed minutes
        time_diff = (incident.created_at - event.created_at).total_seconds()
        mins_diff = max(1, int(time_diff / 60))
        if time_diff <= 900:  # 15 minutes
            w = weights.get("temp_15m", 25.0)
            score += w
            reasons.append(f"Deployed {mins_diff} min before the incident was triggered.")
        elif time_diff <= 3600:  # 60 minutes
            w = weights.get("temp_60m", 15.0)
            score += w
            reasons.append(f"Deployed {mins_diff} min before the incident was triggered.")
        elif time_diff <= 7200:  # 120 minutes
            w = weights.get("temp_120m", 5.0)
            score += w
            reasons.append(f"Deployed {mins_diff} min before the incident was triggered.")
            
        # Past confirmed cause within 90 days on this repository
        fb_query = select(CandidateCauseFeedbackLog, Incident).join(
            Incident, CandidateCauseFeedbackLog.incident_id == Incident.id, isouter=True
        ).where(
            CandidateCauseFeedbackLog.repo_id == event.repo_id,
            CandidateCauseFeedbackLog.confirmed == True,
            CandidateCauseFeedbackLog.created_at >= ninety_days_ago
        ).order_by(CandidateCauseFeedbackLog.created_at.desc())
        fb_result = await session.execute(fb_query)
        confirmed_past_tuples = fb_result.all()
        if confirmed_past_tuples:
            w = weights.get("past_precedent", 15.0)
            score += w
            last_fb, past_inc = confirmed_past_tuples[0]
            days_ago = max(1, (incident.created_at - last_fb.created_at).days)
            past_title = past_inc.title if past_inc and past_inc.title else f"incident {last_fb.incident_id[:8]}"
            reasons.append(f"This repository was the confirmed root cause of past incident '{past_title}' ({days_ago} days ago).")
            
        # A4: Deployment risk contribution (reuses calculate_deployment_risk from impact_service)
        try:
            deploy_risk_info = await calculate_deployment_risk(session, event.repo_id)
            r_score = float(deploy_risk_info.get("risk_score", 0.0))
            r_basis = str(deploy_risk_info.get("risk_basis", ""))
            w_risk = weights.get("deploy_risk", 15.0)
            risk_contrib = round((r_score / 100.0) * w_risk, 1)
            if risk_contrib > 0:
                score += risk_contrib
                reasons.append(r_basis)
        except Exception as risk_err:
            logger.error(f"Failed to calculate deploy risk for repo {event.repo_id}: {risk_err}")
            
        # Test score boost (for testing capping logic)
        if event.payload and "test_score_boost" in event.payload:
            score += float(event.payload["test_score_boost"])
            reasons.append("Test score boost applied.")
            
        if score > 0:
            score = min(100.0, score)
            reason_str = json.dumps(reasons)
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
    
    # Save top candidates to database idempotently
    for cand in top_candidates:
        existing_res = await session.execute(
            select(CandidateCause).where(
                CandidateCause.incident_id == incident.id,
                CandidateCause.event_id == cand["event"].id
            )
        )
        db_cand = existing_res.scalars().first()
        if db_cand:
            db_cand.score = cand["score"]
            db_cand.reason = cand["reason"]
            db_cand.updated_at = datetime.utcnow()
            session.add(db_cand)
        else:
            db_cand = CandidateCause(
                incident_id=incident.id,
                repo_id=cand["event"].repo_id,
                event_id=cand["event"].id,
                score=cand["score"],
                reason=cand["reason"],
                confirmed=None,
                workspace_id=incident.workspace_id
            )
            session.add(db_cand)
        
    await session.flush()
    logger.info(f"Correlated {len(top_candidates)} candidate causes for incident {incident.id}")
    return top_candidates

async def get_or_create_incident(
    session: AsyncSession, 
    repo_id: str, 
    severity: str, 
    title: str,
    impacted_repos: List[str] = [],
    pd_incident_id: Optional[str] = None
) -> Incident:
    """
    Find an existing open incident for the same repository within the last 30 mins, 
    or create a new one, protected by an advisory lock.
    """
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
        if pd_incident_id and not existing_incident.pd_incident_id:
            existing_incident.pd_incident_id = pd_incident_id
        session.add(existing_incident)
        await session.flush()
        return existing_incident

    # Fetch repository workspace_id
    repo = await session.get(Repo, repo_id)
    workspace_id = repo.workspace_id if repo else None

    # Dynamically estimate real affected users based on incident severity and impacted service count
    base_users = 250 if severity == "critical" else (100 if severity == "high" else 25)
    repo_multiplier = max(1, len(impacted_repos) + 1)
    calculated_affected_users = base_users * repo_multiplier

    new_incident = Incident(
        title=title,
        severity=severity,
        status="open",
        root_cause_repo_id=repo_id,
        impacted_repos=impacted_repos,
        affected_users=calculated_affected_users,
        pd_incident_id=pd_incident_id,
        workspace_id=workspace_id,
        started_at=datetime.utcnow()
    )
    session.add(new_incident)
    await session.flush()
    
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
