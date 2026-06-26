from fastapi import APIRouter, Request, Header, HTTPException, Depends, BackgroundTasks
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
import hmac
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from app.core.database import get_session
from app.core.config import settings
from app.models.event import Event
from app.models.repo import Repo
from app.services.automation_service import process_event

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger("nexops.webhooks")

async def verify_signature(request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    """
    Validate the GitHub webhook signature using HMAC-SHA256.
    """
    if not settings.GITHUB_WEBHOOK_SECRET:
        logger.warning("GITHUB_WEBHOOK_SECRET not set, skipping verification.")
        return

    if not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="X-Hub-Signature-256 header missing")

    body = await request.body()
    signature = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(f"sha256={signature}", x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

@router.post("/github")
async def github_webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(...),
    session: AsyncSession = Depends(get_session),
    _ = Depends(verify_signature)
):
    """
    Real-time GitHub Webhook Handler.
    Receives events from GitHub, normalizes them, and triggers automation.
    """

    payload = await request.json()
    logger.info(f"Received GitHub Webhook: {x_github_event}")

    # 1. Extract Repository Info
    repo_data = payload.get("repository", {})
    full_name = repo_data.get("full_name") # "owner/repo"
    
    if not full_name:
        return {"status": "ignored", "reason": "No repository info found in payload"}

    # 2. Find the repository in NexOps database
    result = await session.execute(  # type: ignore
        select(Repo).where(Repo.owner == full_name.split("/")[0], Repo.name == full_name.split("/")[1])
    )
    repo = result.scalars().first()

    if not repo:
        return {"status": "ignored", "reason": f"Repository {full_name} not tracked in NexOps"}

    # 3. Map GitHub Event -> NexOps Event Type
    event_type = "unknown"
    message = ""
    severity = "info"

    if x_github_event == "push":
        event_type = "repo.updated"
        ref = payload.get("ref", "")
        message = f"Push detected on {ref} by {payload.get('pusher', {}).get('name')}"
        
        # Update repo last commit
        repo.last_commit_at = datetime.utcnow()
        session.add(repo)

    elif x_github_event == "pull_request":
        action = payload.get("action")
        if action == "opened":
            event_type = "pr.opened"
            message = f"New Pull Request #{payload.get('number')} opened"
        elif action == "closed" and payload.get("pull_request", {}).get("merged"):
            event_type = "pr.merged"
            message = f"Pull Request #{payload.get('number')} merged"
        else:
            return {"status": "ignored", "reason": f"PR action {action} not processed"}

    elif x_github_event == "issues":
        action = payload.get("action")
        if action == "opened":
            event_type = "issue.created"
            message = f"New Issue #{payload.get('issue', {}).get('number')} created"
            repo.open_issues += 1
            session.add(repo)
        else:
            return {"status": "ignored", "reason": f"Issue action {action} not processed"}
    
    if event_type == "unknown":
        return {"status": "ignored", "reason": f"Event type {x_github_event} not mapped"}

    # 4. Create NexOps Event
    new_event = Event(
        type=event_type,
        repo_id=repo.id,
        source="github",
        payload=payload,
        message=message,
        severity=severity
    )
    session.add(new_event)
    await session.commit()  # type: ignore
    await session.refresh(new_event)  # type: ignore

    # 5. Trigger Automation Engine in background
    from app.api.routes.events import _run_automation
    background_tasks.add_task(_run_automation, new_event.id)

    return {"status": "processed", "event_id": new_event.id, "type": event_type}


@router.post("/pagerduty")
async def pagerduty_webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """
    Ingest PagerDuty incident webhook events.
    """
    pd_signature = request.headers.get("X-PagerDuty-Signature")
    pd_secret = settings.model_dump().get("PAGERDUTY_SIGNING_KEY") or settings.model_dump().get("PAGERDUTY_WEBHOOK_SECRET") or getattr(settings, "PAGERDUTY_WEBHOOK_SECRET", None)
    
    body = await request.body()
    if pd_secret and pd_signature:
        sig_hash = pd_signature.split(",")
        v1_hash = None
        for s in sig_hash:
            if s.startswith("v1="):
                v1_hash = s.split("=")[1]
                break
        if v1_hash:
            import hmac
            import hashlib
            expected = hmac.new(
                pd_secret.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, v1_hash):
                raise HTTPException(status_code=401, detail="Invalid PagerDuty signature")

    payload = await request.json()
    logger.info("Received PagerDuty Webhook payload")

    event_data = payload.get("event", {})
    if not event_data:
        messages = payload.get("messages", [])
        if messages:
            event_data = messages[0]

    event_type = event_data.get("event_type") or event_data.get("event", "incident.triggered")
    incident_data = event_data.get("data", event_data.get("incident", {}))
    title = incident_data.get("title", "PagerDuty Alert")
    service_info = incident_data.get("service", {})
    pd_service_name = service_info.get("name", "")

    # Find the repository in NexOps database
    repo = None
    if pd_service_name:
        result = await session.execute(  # type: ignore
            select(Repo).where(Repo.name.ilike(f"%{pd_service_name}%"))  # type: ignore
        )
        repo = result.scalars().first()

    if not repo:
        result = await session.execute(select(Repo))  # type: ignore
        repo = result.scalars().first()

    if not repo:
        return {"status": "ignored", "reason": "No repository tracked in NexOps database to link alert to"}

    new_event = Event(
        type="pagerduty.incident" if "incident" in event_type else "ci.failed",
        repo_id=repo.id,
        source="pagerduty",
        payload=payload,
        message=f"PagerDuty incident: {title} on service {pd_service_name}",
        severity="error" if "resolve" not in event_type else "info"
    )
    session.add(new_event)
    await session.commit()  # type: ignore
    await session.refresh(new_event)  # type: ignore

    from app.api.routes.events import _run_automation
    background_tasks.add_task(_run_automation, new_event.id)

    return {"status": "processed", "event_id": new_event.id, "type": new_event.type}
