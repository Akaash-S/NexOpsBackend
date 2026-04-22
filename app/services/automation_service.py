"""
Automation Service — THE CORE ENGINE
Processes incoming events, matches them against active rules,
and executes the corresponding actions (alert creation, repo state updates).
This is what makes NexOps a reactive system, not just a CRUD app.
"""

import logging
from datetime import datetime
from typing import List
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.rule import Rule
from app.services.alert_service import create_alert_from_rule
from app.services.repo_service import update_repo_state
from app.services.insight_service import calculate_health_score

logger = logging.getLogger("nexops.automation")


# ─── Event Type → Default Alert Mapping ─────────────────────────────────
# These are the built-in reactions when no custom rules exist.
# Status values ('passing', 'failing') align with frontend 'status' type.
DEFAULT_REACTIONS = {
    "ci.failed": {
        "severity": "high",
        "category": "ci",
        "title": "CI Pipeline Failed",
        "message": "A CI pipeline has failed for this repository. Investigate build logs immediately.",
        "repo_update": {"ci_status": "failing"},
    },
    "ci.success": {
        "severity": None,  # No alert, just update state
        "repo_update": {"ci_status": "passing"},
    },
    "deploy.failed": {
        "severity": "critical",
        "category": "system",
        "title": "Deployment Failed",
        "message": "A deployment has failed. Production may be affected.",
        "repo_update": {"ci_status": "failing"},
    },
    "deploy.started": {
        "severity": None,
        "repo_update": {"ci_status": "running"},
    },
    "issue.created": {
        "severity": "low",
        "category": "repository",
        "title": "New Issue Opened",
        "message": "A new issue has been opened on this repository.",
        "repo_update_fn": lambda repo, meta: {"open_issues": repo.open_issues + 1},
    },
    "pr.opened": {
        "severity": None,
        "category": "repository",
        "repo_update_fn": lambda repo, meta: {"open_prs": repo.open_prs + 1},
    },
    "pr.merged": {
        "severity": None,
        "category": "repository",
        "repo_update_fn": lambda repo, meta: {
            "open_prs": max(0, repo.open_prs - 1),
            "last_commit_at": datetime.utcnow(),
        },
    },
    "repo.updated": {
        "severity": None,
        "category": "repository",
        "repo_update": None,
    },
}


async def process_event(session: AsyncSession, event: Event) -> dict:
    """
    The main automation pipeline.
    
    Flow:
    1. Match event against active rules
    2. Execute rule actions (or fallback to defaults)
    3. Update repository state
    4. Recalculate health score
    5. Mark event as processed
    
    Returns a summary of actions taken.
    """
    actions_taken = {
        "event_id": event.id,
        "event_type": event.type,
        "rules_matched": 0,
        "alerts_created": 0,
        "repo_updated": False,
        "health_recalculated": False,
    }

    logger.info(f"⚡ Processing event: {event.type} for repo {event.repo_id}")

    # ── Step 1: Find matching rules ──────────────────────────────────────
    matched_rules = await _find_matching_rules(session, event)
    actions_taken["rules_matched"] = len(matched_rules)

    # ── Step 2: Execute matched rules ────────────────────────────────────
    if matched_rules:
        for rule in matched_rules:
            await _execute_rule(session, rule, event)
            actions_taken["alerts_created"] += 1 if rule.action_type == "create_alert" else 0
            actions_taken["repo_updated"] = actions_taken["repo_updated"] or rule.action_type == "update_repo"
    else:
        # ── Step 2b: Fallback to default reactions ───────────────────────
        result = await _execute_default_reaction(session, event)
        actions_taken["alerts_created"] += result.get("alerts_created", 0)
        actions_taken["repo_updated"] = result.get("repo_updated", False)

    # ── Step 3: Recalculate health score ─────────────────────────────────
    try:
        await calculate_health_score(session, event.repo_id)
        actions_taken["health_recalculated"] = True
    except Exception as e:
        logger.error(f"Health score recalculation failed: {e}")

    # ── Step 4: Mark event as processed ──────────────────────────────────
    event.processed = True
    session.add(event)
    await session.commit()

    logger.info(f"✅ Event processed: {actions_taken}")
    return actions_taken


async def _find_matching_rules(session: AsyncSession, event: Event) -> List[Rule]:
    """Find all active rules whose condition_type matches the event type."""
    query = select(Rule).where(
        Rule.is_active == True,
        Rule.condition_type == event.type,
    )
    result = await session.execute(query)
    rules = list(result.scalars().all())

    # Filter by condition_config if present (e.g., specific repo_id)
    filtered = []
    for rule in rules:
        if rule.condition_config:
            # Check if all config conditions match the event payload
            config_match = True
            for key, value in rule.condition_config.items():
                if key == "repo_id" and value != event.repo_id:
                    config_match = False
                    break
                if event.payload and key in event.payload and event.payload[key] != value:
                    config_match = False
                    break
            if config_match:
                filtered.append(rule)
        else:
            filtered.append(rule)

    return filtered


async def _execute_rule(session: AsyncSession, rule: Rule, event: Event):
    """Execute a single matched rule's action."""
    logger.info(f"  🔗 Executing rule: {rule.name} (action: {rule.action_type})")

    if rule.action_type == "create_alert":
        config = rule.action_config or {}
        await create_alert_from_rule(
            session=session,
            repo_id=event.repo_id,
            event_id=event.id,
            severity=config.get("severity", "medium"),
            title=config.get("title", f"Rule Triggered: {rule.name}"),
            message=config.get("message", f"Automation rule '{rule.name}' was triggered by event {event.type}."),
            category=config.get("category", "system"),
        )

    elif rule.action_type == "update_repo":
        config = rule.action_config or {}
        if config:
            await update_repo_state(session, event.repo_id, **config)

    elif rule.action_type == "notify":
        # Placeholder for future notification channels (Slack, email, etc.)
        logger.info(f"  📢 Notification action triggered (not yet implemented)")

    elif rule.action_type == "escalate":
        # Escalate: create a critical alert
        await create_alert_from_rule(
            session=session,
            repo_id=event.repo_id,
            event_id=event.id,
            severity="critical",
            title=f"⚠️ Escalation: {rule.name}",
            message=f"This event has been escalated by rule '{rule.name}'. Immediate attention required.",
            category="system",
        )

    # Update rule execution metadata
    rule.execution_count += 1
    rule.last_triggered_at = datetime.utcnow()
    session.add(rule)
    await session.commit()


async def _execute_default_reaction(session: AsyncSession, event: Event) -> dict:
    """
    Execute built-in default reactions for known event types.
    This ensures the system always reacts, even without custom rules.
    """
    result = {"alerts_created": 0, "repo_updated": False}
    reaction = DEFAULT_REACTIONS.get(event.type)

    if not reaction:
        logger.info(f"  ℹ️ No default reaction for event type: {event.type}")
        return result

    # Create alert if severity is defined
    if reaction.get("severity"):
        await create_alert_from_rule(
            session=session,
            repo_id=event.repo_id,
            event_id=event.id,
            severity=reaction["severity"],
            title=reaction.get("title", f"Alert: {event.type}"),
            message=reaction.get("message", f"Default alert for event {event.type}"),
            category=reaction.get("category", "system"),
        )
        result["alerts_created"] = 1

    # Update repo state (static updates)
    if reaction.get("repo_update"):
        await update_repo_state(session, event.repo_id, **reaction["repo_update"])
        result["repo_updated"] = True

    # Update repo state (dynamic updates requiring current repo state)
    if reaction.get("repo_update_fn"):
        from app.services.repo_service import get_repo_by_id
        repo = await get_repo_by_id(session, event.repo_id)
        if repo:
            updates = reaction["repo_update_fn"](repo, event.payload)
            await update_repo_state(session, event.repo_id, **updates)
            result["repo_updated"] = True

    return result
