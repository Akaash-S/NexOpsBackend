from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlmodel import Session, select
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

async def verify_signature(request: Request, x_hub_signature_256: str = Header(None)):
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
    x_github_event: str = Header(...),
    session: Session = Depends(get_session)
):
    """
    Real-time GitHub Webhook Handler.
    Receives events from GitHub, normalizes them, and triggers automation.
    """
    # Verify signature if secret is configured
    await verify_signature(request)

    payload = await request.json()
    logger.info(f"Received GitHub Webhook: {x_github_event}")

    # 1. Extract Repository Info
    repo_data = payload.get("repository", {})
    full_name = repo_data.get("full_name") # "owner/repo"
    
    if not full_name:
        return {"status": "ignored", "reason": "No repository info found in payload"}

    # 2. Find the repository in NexOps database
    result = await session.execute(
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
    await session.commit()
    await session.refresh(new_event)

    # 5. Trigger Automation Engine
    await process_event(session, new_event)

    return {"status": "processed", "event_id": new_event.id, "type": event_type}
