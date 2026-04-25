"""
Automation Service — THE CORE ENGINE (Refactored for Multi-Action Support)
Processes incoming events, matches them against active rules,
and executes the corresponding actions.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.rule import Rule
from app.services.alert_service import create_alert_from_rule
from app.services.repo_service import update_repo_state
from app.services.insight_service import calculate_health_score

logger = logging.getLogger("nexops.automation")

# Default reactions mapping remains similar but uses the new execution flow
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
    """The main automation pipeline."""
    actions_taken = {
        "event_id": event.id,
        "event_type": event.type,
        "rules_matched": 0,
        "total_actions": 0,
    }

    logger.info(f"Processing event: {event.type} for repo {event.repo_id}")

    matched_rules = await _find_matching_rules(session, event)
    actions_taken["rules_matched"] = len(matched_rules)

    if matched_rules:
        for rule in matched_rules:
            # Execute all actions in the rule
            for action in (rule.action_config or []):
                await _execute_single_action(session, action, rule, event)
                actions_taken["total_actions"] += 1
            
            # Update rule execution metadata
            rule.execution_count += 1
            rule.last_triggered_at = datetime.utcnow()
            session.add(rule)
    else:
        # Fallback to default reactions
        reactions = DEFAULT_REACTIONS.get(event.type, [])
        for action in reactions:
            await _execute_single_action(session, action, None, event)
            actions_taken["total_actions"] += 1

    # Recalculate health score
    try:
        await calculate_health_score(session, event.repo_id)
        # Propagate health up to the cluster if repo belongs to one
        from app.models.repo import Repo as RepoModel
        repo_obj = await session.get(RepoModel, event.repo_id)
        if repo_obj and repo_obj.cluster_id:
            from app.services.cluster_service import recalculate_cluster_health
            await recalculate_cluster_health(session, repo_obj.cluster_id)
    except Exception as e:
        logger.error(f"Health score recalculation failed: {e}")

    # Mark event as processed
    event.processed = True
    session.add(event)
    await session.commit()

    # BROADCAST REAL-TIME UPDATE
    from app.core.websocket import manager
    try:
        await manager.broadcast({
            "type": "system.update",
            "source": "automation_engine",
            "payload": {
                "event_type": event.type,
                "repo_id": event.repo_id,
                "actions": actions_taken
            }
        })
    except Exception as e:
        logger.error(f"WebSocket broadcast failed: {e}")

    logger.info(f"Event processed: {actions_taken}")
    return actions_taken

async def _find_matching_rules(session: AsyncSession, event: Event) -> List[Rule]:
    """Find all active rules whose condition_type matches the event type."""
    query = select(Rule).where(
        Rule.is_active == True,
        Rule.condition_type == event.type,
    )
    result = await session.execute(query)
    rules = list(result.scalars().all())

    # Advanced filtering based on condition_config list
    filtered = []
    for rule in rules:
        if not rule.condition_config:
            filtered.append(rule)
            continue

        match = True
        for cond in rule.condition_config:
            field = cond.get("field")
            op = cond.get("operator")
            val = cond.get("value")

            # Check if field exists in event or payload
            actual_val = getattr(event, field, None)
            if actual_val is None and event.payload:
                actual_val = event.payload.get(field)

            if not _evaluate_condition(actual_val, op, val):
                match = False
                break
        
        if match:
            filtered.append(rule)

    return filtered

def _evaluate_condition(actual: Any, operator: str, expected: Any) -> bool:
    """Evaluate a single condition logic gate."""
    if actual is None:
        return False
    try:
        if operator == "equals": return str(actual) == str(expected)
        if operator == "contains": return str(expected) in str(actual)
        if operator == "greater_than": return float(actual) > float(expected)
        if operator == "less_than": return float(actual) < float(expected)
    except (ValueError, TypeError):
        return False
    return False

async def _execute_single_action(session: AsyncSession, action: Dict[str, Any], rule: Optional[Rule], event: Event):
    """Execute a single action from a rule or default reaction."""
    a_type = action.get("type")
    params = action.get("params", {})
    
    rule_name = rule.name if rule else "Default Reaction"
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
