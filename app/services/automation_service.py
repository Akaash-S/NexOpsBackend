"""
Automation Service — THE CORE ENGINE (Refactored for Multi-Action Support)
Processes incoming events and executes the corresponding actions.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.services.alert_service import create_alert_from_rule
from app.services.repo_service import update_repo_state
from app.services.insight_service import calculate_health_score

logger = logging.getLogger("nexops.automation")

# Default reactions mapping
DEFAULT_REACTIONS = {
    "ci.failed": [
        {"type": "create_alert", "params": {"severity": "high", "category": "ci", "title": "CI Pipeline Failed"}},
        {"type": "update_repo", "params": {"ci_status": "failing"}}
    ],
    "ci.success": [
        {"type": "update_repo", "params": {"ci_status": "passing"}}
    ],
    "deploy.failed": [
        {"type": "escalate", "params": {"title": "Deployment Failed"}},
        {"type": "update_repo", "params": {"ci_status": "failing"}}
    ],
}

async def process_event(session: AsyncSession, event: Event) -> dict:
    """The main automation pipeline (NexOps Intelligence Engine)."""
    from app.services.impact_service import propagate_impact, get_downstream_repos
    from app.services.incident_service import get_or_create_incident
    
    actions_taken = {
        "event_id": event.id,
        "event_type": event.type,
        "rules_matched": 0,
        "total_actions": 0,
        "impacted_repos": 0,
        "incident_id": None
    }

    logger.info(f"Intelligence Engine Processing: {event.type} for repo {event.repo_id}")

    # Evaluate default reactions directly
    reactions = DEFAULT_REACTIONS.get(event.type, [])
    for action in reactions:
        await _execute_single_action(session, action, event)
        actions_taken["total_actions"] += 1

    # 2. Impact Propagation
    # If the event is a failure (CI/Deploy), propagate impact
    if event.type in ["ci.failed", "deploy.failed"] or event.severity in ["error", "critical"]:
        # Traverse dependencies and update downstream health
        await propagate_impact(session, event.repo_id, event.severity)
        downstream = await get_downstream_repos(session, event.repo_id)
        actions_taken["impacted_repos"] = len(downstream)
        
        # Create or group into an Incident
        incident = await get_or_create_incident(
            session, 
            event.repo_id, 
            event.severity, 
            title=f"Systemic Failure: {event.message or event.type}",
            impacted_repos=downstream,
            pd_incident_id=event.pd_incident_id
        )
        actions_taken["incident_id"] = incident.id
        
        # Generate Intelligent Insight
        insight_msg = f"{event.type} in {event.repo_id} -> "
        if len(downstream) > 0:
            insight_msg += f"propagated to {len(downstream)} services -> impacting cluster health."
        else:
            insight_msg += "local failure detected."
        
        event.message = f"{event.message or ''} | Insight: {insight_msg}".strip(" | ")

    # 3. Recalculate health score for the source repo
    try:
        await calculate_health_score(session, event.repo_id)
    except Exception as e:
        logger.error(f"Health score recalculation failed: {e}")

    # Capture details for broadcast before commit (to avoid lazy loading issues)
    event_type = event.type
    repo_id = event.repo_id

    # Gather details for websocket broadcast before commit to avoid lazy loading issues
    incident_data = None
    candidate_causes_data = []
    if actions_taken.get("incident_id"):
        try:
            from app.models.incident import Incident
            from app.models.candidate_cause import CandidateCause
            # Fetch incident
            inc_res = await session.execute(
                select(Incident).where(Incident.id == actions_taken["incident_id"])
            )
            db_inc = inc_res.scalars().first()
            if db_inc:
                incident_data = db_inc.model_dump()
                for k, v in incident_data.items():
                    if hasattr(v, "isoformat"):
                        incident_data[k] = v.isoformat()

                # Fetch candidate causes
                cc_res = await session.execute(
                    select(CandidateCause).where(CandidateCause.incident_id == db_inc.id)
                )
                for cc in cc_res.scalars().all():
                    cc_dict = cc.model_dump()
                    for k, v in cc_dict.items():
                        if hasattr(v, "isoformat"):
                            cc_dict[k] = v.isoformat()
                    candidate_causes_data.append(cc_dict)
        except Exception as serial_err:
            logger.error(f"Failed to serialize incident/candidate causes: {serial_err}")

    # Mark event as processed
    event.processed = True
    session.add(event)
    await session.commit()

    # INVALIDATE CACHE IN REDIS
    from app.core.redis import invalidate_cache_pattern
    try:
        await invalidate_cache_pattern("cache:dashboard:*")
        # Invalidate repo code-viewer cache on commits/updates
        if event_type == "repo.updated" or event_type == "push":
            await invalidate_cache_pattern(f"cache:repo:*:{repo_id}:*")
    except Exception as cache_err:
        logger.error(f"Failed to invalidate cache: {cache_err}")

    # BROADCAST REAL-TIME UPDATE
    from app.core.websocket import manager
    try:
        await manager.broadcast({
            "type": "incident.created" if incident_data else "system.update",
            "source": "intelligence_engine",
            "payload": {
                "event_type": event_type,
                "repo_id": repo_id,
                "actions": actions_taken,
                "incident": incident_data,
                "candidate_causes": candidate_causes_data
            }
        })
    except Exception as e:
        logger.error(f"WebSocket broadcast failed: {e}")

    logger.info(f"Intelligence loop complete: {actions_taken}")
    return actions_taken

async def _execute_single_action(session: AsyncSession, action: Dict[str, Any], event: Event):
    """Execute a single action from a default reaction."""
    a_type = action.get("type")
    params = action.get("params", {})
    
    rule_name = "Default Reaction"
    logger.info(f"Executing action: {a_type} (from {rule_name})")

    if a_type == "create_alert":
        await create_alert_from_rule(
            session=session,
            repo_id=event.repo_id,
            event_id=event.id,
            severity=params.get("severity", "medium"),
            title=params.get("title", f"Rule Triggered: {rule_name}"),
            message=params.get("message", f"Triggered by event {event.type}."),
            category=params.get("category", "system"),
        )

    elif a_type == "update_repo":
        await update_repo_state(session, event.repo_id, **params)

    elif a_type == "escalate":
        await create_alert_from_rule(
            session=session,
            repo_id=event.repo_id,
            event_id=event.id,
            severity="critical",
            title=f"Escalation: {params.get('title', rule_name)}",
            message=params.get("message", "Immediate attention required."),
            category="system",
        )
