from fastapi import APIRouter, Request, Header, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
import hmac
import hashlib
import logging
from datetime import datetime
from typing import Optional

from app.core.database import get_session
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.event import Event
from app.models.repo import Repo
from app.models.incident import Incident
from app.services.automation_service import process_event

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger("nexops.webhooks")


async def verify_github_signature(request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    """
    Validate the GitHub webhook HMAC-SHA256 signature.
    If GITHUB_WEBHOOK_SECRET is not configured the endpoint rejects all requests — a
    missing secret is treated as a misconfiguration, not a reason to skip verification.
    """
    if not settings.GITHUB_WEBHOOK_SECRET:
        logger.error("GITHUB_WEBHOOK_SECRET is not configured — rejecting webhook request.")
        raise HTTPException(
            status_code=503,
            detail="Webhook endpoint not configured: server secret is missing."
        )

    if not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="X-Hub-Signature-256 header missing.")

    body = await request.body()
    expected = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(f"sha256={expected}", x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature.")


async def verify_pagerduty_signature(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """
    Validate the PagerDuty webhook HMAC-SHA256 signature.
    Supports multi-tenancy: looks up user's secret from the db using the 'uid' query parameter.
    Falls back to settings.PAGERDUTY_WEBHOOK_SECRET if 'uid' is not present or user has no secret.
    """
    uid = request.query_params.get("uid")
    webhook_secret = None

    if uid:
        from app.models.user import User
        from app.core.crypto import decrypt_secret
        try:
            result = await session.execute(select(User).where(User.id == uid))
            user = result.scalars().first()
            if user and user.pagerduty_webhook_secret:
                webhook_secret = decrypt_secret(user.pagerduty_webhook_secret)
                logger.info(f"Using per-user PagerDuty webhook secret for user {uid}")
        except Exception as db_err:
            logger.error(f"Error looking up PagerDuty secret for user {uid}: {db_err}")

    if not webhook_secret:
        webhook_secret = settings.PAGERDUTY_WEBHOOK_SECRET
        if webhook_secret:
            logger.info("Using global settings.PAGERDUTY_WEBHOOK_SECRET fallback")

    if not webhook_secret:
        logger.error("No PagerDuty webhook secret found (per-user or global) — rejecting webhook request.")
        raise HTTPException(
            status_code=503,
            detail="Webhook endpoint not configured: server secret is missing."
        )

    pd_signature = request.headers.get("X-PagerDuty-Signature")
    if not pd_signature:
        raise HTTPException(status_code=401, detail="X-PagerDuty-Signature header missing.")

    body = await request.body()

    # PagerDuty sends "v1=<hex>,v1=<hex>" — validate against any v1 hash present
    v1_hash = None
    for segment in pd_signature.split(","):
        segment = segment.strip()
        if segment.startswith("v1="):
            v1_hash = segment[3:]
            break

    if not v1_hash:
        raise HTTPException(status_code=401, detail="No v1 signature found in X-PagerDuty-Signature.")

    expected = hmac.new(
        webhook_secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, v1_hash):
        raise HTTPException(status_code=401, detail="Invalid PagerDuty signature.")


@router.post("/github")
@limiter.limit("60/minute")
async def github_webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(...),
    session: AsyncSession = Depends(get_session),
    _ = Depends(verify_github_signature)
):
    """
    Real-time GitHub Webhook Handler.
    Receives events from GitHub, normalizes them, and triggers automation.
    """

    payload = await request.json()
    logger.info(f"Received GitHub Webhook: {x_github_event}")

    # 1. Extract Repository Info
    repo_data = payload.get("repository", {})
    full_name = repo_data.get("full_name")  # "owner/repo"

    if not full_name:
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "No repository info found in payload"})

    # 2. Find the repository in NexOps database
    result = await session.execute(  # type: ignore
        select(Repo).where(Repo.owner == full_name.split("/")[0], Repo.name == full_name.split("/")[1])
    )
    repo = result.scalars().first()

    if not repo:
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": f"Repository {full_name} not tracked in NexOps"})

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
            return JSONResponse(status_code=200, content={"status": "ignored", "reason": f"PR action {action} not processed"})

    elif x_github_event == "issues":
        action = payload.get("action")
        if action == "opened":
            event_type = "issue.created"
            message = f"New Issue #{payload.get('issue', {}).get('number')} created"
            repo.open_issues += 1
            session.add(repo)
        else:
            return JSONResponse(status_code=200, content={"status": "ignored", "reason": f"Issue action {action} not processed"})

    if event_type == "unknown":
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": f"Event type {x_github_event} not mapped"})

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

    return JSONResponse(status_code=200, content={"status": "processed", "event_id": new_event.id, "type": event_type})


@router.post("/pagerduty")
@limiter.limit("60/minute")
async def pagerduty_webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    _ = Depends(verify_pagerduty_signature)
):
    """
    Ingest PagerDuty incident webhook events.

    Fix — Defect B (repo fallback):
      - Reads service.summary (correct field path; PagerDuty does NOT send service.name).
      - Removes the unscoped SELECT * FROM repos fallback that silently attached events
        to arbitrary repos. If no repo can be matched, rejects with a clear log entry.

    Fix — Defect A (idempotency):
      - Extracts the PagerDuty event.id and stores it as pd_event_id on the Event row.
      - If an Event with the same pd_event_id already exists, returns a duplicate
        response and skips processing — no new Event/Incident is created.

    Fix — Open Question 4 (event type routing):
      - incident.triggered  → creates a new NexOps Event + runs automation (as before).
      - incident.acknowledged / incident.resolved → finds the existing open NexOps
        incident for the PagerDuty incident ID and updates its status. Does NOT create
        a new Event or Incident row.
      - Other event types → ignored with a clear log entry.
    """
    payload = await request.json()

    # --- Extract event envelope ---
    event_data = payload.get("event", {})
    if not event_data:
        messages = payload.get("messages", [])
        if messages:
            event_data = messages[0]

    pd_event_id = event_data.get("id")           # PagerDuty's own unique event ID
    event_type = event_data.get("event_type") or event_data.get("event", "")
    incident_data = event_data.get("data", event_data.get("incident", {}))
    pd_incident_id = incident_data.get("id")      # PagerDuty incident ID (e.g. Q3OILL557B8681)
    title = incident_data.get("title", "PagerDuty Alert")

    # Fix B — use service.summary (correct field); PagerDuty sends summary, not name
    service_info = incident_data.get("service", {})
    pd_service_name = service_info.get("summary") or service_info.get("name", "")

    logger.info(f"PagerDuty webhook: event_type={event_type} pd_event_id={pd_event_id} "
                f"pd_incident_id={pd_incident_id} service={pd_service_name!r}")

    # Fix A — idempotency: reject duplicate deliveries with the same PagerDuty event ID
    if pd_event_id:
        existing_event_result = await session.execute(  # type: ignore
            select(Event).where(Event.pd_event_id == pd_event_id)
        )
        existing_event = existing_event_result.scalars().first()
        if existing_event:
            logger.warning(f"Duplicate PagerDuty event {pd_event_id} — already processed as "
                           f"NexOps event {existing_event.id}. Skipping.")
            return JSONResponse(status_code=200, content={
                "status": "duplicate",
                "pd_event_id": pd_event_id,
                "existing_event_id": existing_event.id
            })

    # Fix OQ4 — route acknowledged/resolved to status updates, NOT new incidents
    if event_type in ("incident.acknowledged", "incident.resolved"):
        if not pd_incident_id:
            logger.warning(f"PagerDuty {event_type} received but no incident ID in payload — ignoring.")
            return JSONResponse(status_code=200, content={"status": "ignored", "reason": "no pd_incident_id"})

        # Find the original event by pd_incident_id column (fast indexed lookup)
        orig_event_result = await session.execute(  # type: ignore
            select(Event).where(
                Event.source == "pagerduty",
                Event.pd_incident_id == pd_incident_id,
                Event.type == "pagerduty.incident"
            ).order_by(Event.created_at.desc()).limit(1)
        )
        orig_event = orig_event_result.scalars().first()

        # Find the open or investigating incident for the matched repository
        matched_incident = None
        if orig_event and orig_event.repo_id:
            inc_result = await session.execute(  # type: ignore
                select(Incident).where(
                    Incident.root_cause_repo_id == orig_event.repo_id,
                    Incident.status.in_(["open", "investigating"])
                ).order_by(Incident.created_at.desc()).limit(1)
            )
            matched_incident = inc_result.scalars().first()

        if matched_incident:
            new_status = "investigating" if event_type == "incident.acknowledged" else "resolved"
            matched_incident.status = new_status
            if new_status == "resolved":
                matched_incident.resolved_at = datetime.utcnow()
            session.add(matched_incident)
            await session.commit()  # type: ignore
            logger.info(f"Updated incident {matched_incident.id} status to {new_status} "
                        f"via PagerDuty {event_type}")
            return JSONResponse(status_code=200, content={
                "status": "updated",
                "incident_id": matched_incident.id,
                "new_status": new_status
            })
        else:
            logger.warning(f"PagerDuty {event_type} for PD incident {pd_incident_id} — "
                           f"no matching open/investigating NexOps incident found. Event arrived out of order.")
            return JSONResponse(status_code=200, content={
                "status": "unmatched",
                "reason": f"No open/investigating NexOps incident found for PagerDuty incident {pd_incident_id}"
            })

    # Only incident.triggered (and other unrecognised types) fall through to create an Event
    if event_type and event_type not in ("incident.triggered",) and event_type.startswith("incident."):
        logger.info(f"PagerDuty event type {event_type!r} is not incident.triggered — ignoring.")
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": f"event_type {event_type!r} not processed"})

    # Fix B — repo matching: use service.summary; no unscoped fallback
    repo = None
    if pd_service_name:
        result = await session.execute(  # type: ignore
            select(Repo).where(Repo.name.ilike(f"%{pd_service_name}%"))  # type: ignore
        )
        repo = result.scalars().first()

    if not repo:
        # Do NOT fall back to arbitrary first repo. Reject loudly.
        logger.warning(
            f"PagerDuty webhook: service {pd_service_name!r} does not match any tracked repo. "
            f"pd_event_id={pd_event_id}. Webhook ignored — manual triage required."
        )
        return JSONResponse(status_code=200, content={
            "status": "unmatched",
            "reason": f"PagerDuty service {pd_service_name!r} not matched to any tracked NexOps repository. "
                      "Add the repository or update the service name in PagerDuty."
        })

    # Create NexOps Event for incident.triggered
    new_event = Event(
        type="pagerduty.incident",
        repo_id=repo.id,
        source="pagerduty",
        payload=payload,
        pd_event_id=pd_event_id,
        pd_incident_id=pd_incident_id,
        message=f"PagerDuty incident: {title} (service: {pd_service_name})",
        severity="error"
    )
    session.add(new_event)
    await session.commit()  # type: ignore
    await session.refresh(new_event)  # type: ignore

    from app.api.routes.events import _run_automation
    background_tasks.add_task(_run_automation, new_event.id)

    logger.info(f"PagerDuty incident.triggered processed: NexOps event {new_event.id} "
                f"repo={repo.name} pd_event_id={pd_event_id} pd_incident_id={pd_incident_id!r}")
    return JSONResponse(status_code=200, content={
        "status": "processed",
        "event_id": new_event.id,
        "type": new_event.type,
        "pd_event_id": pd_event_id,
        "pd_incident_id": pd_incident_id
    })
