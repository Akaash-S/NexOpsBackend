from fastapi import APIRouter, Request, Header, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlmodel import select
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import hmac
import hashlib
import logging
from datetime import datetime
from typing import Optional

from app.core.database import get_session
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.rls import rls_bypass  # Security audit P1-B4/B5: guaranteed-safe RLS bypass
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
    secret_source = "none"
    if uid:
        from app.models.user import User
        from app.core.crypto import decrypt_secret
        from app.api.routes.integrations import _verify_pd_uid_token
        try:
            # Security audit P2-F5: verify the HMAC-signed uid token before trusting it.
            # Rejects forged/guessed uids from external callers — only tokens produced by
            # _make_pd_uid_token (signed with ENCRYPTION_KEY) are accepted.
            raw_uid = _verify_pd_uid_token(uid)
        except ValueError as token_err:
            logger.warning(f"PagerDuty webhook received invalid uid token: {token_err}")
            raw_uid = None  # fall through to global secret fallback

        if raw_uid:
            try:
                # rls_bypass context manager guarantees bypass is reset even on exception or early return
                async with rls_bypass(session):
                    result = await session.execute(select(User).where(User.id == raw_uid))
                    user = result.scalars().first()
                    if user:
                        # Set workspace and user context for the session (bypass already being reset by CM)
                        await session.execute(
                            text("SELECT set_config('nexops.current_workspace_id', :workspace_id, false), set_config('nexops.current_user_id', :user_id, false)"),
                            {"workspace_id": user.workspace_id, "user_id": user.id}
                        )
                    if user and user.pagerduty_webhook_secret:
                        webhook_secret = decrypt_secret(user.pagerduty_webhook_secret)
                        secret_source = f"user:{raw_uid}"
                        logger.info(f"Using per-user PagerDuty webhook secret for user {raw_uid}")
            except Exception as db_err:
                logger.error(f"Error looking up PagerDuty secret for user {raw_uid}: {db_err}")

    if not webhook_secret:
        webhook_secret = settings.PAGERDUTY_WEBHOOK_SECRET
        if webhook_secret:
            secret_source = "global_env"
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
        secret_fp = hashlib.sha256(webhook_secret.encode()).hexdigest()[:8]
        logger.warning(
            f"PagerDuty HMAC signature verification failed (source={secret_source}, "
            f"secret_len={len(webhook_secret)}, secret_fp={secret_fp}). "
            f"Expected {expected[:8]}... received {v1_hash[:8]}..."
        )
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
    # rls_bypass guarantees nexops.bypass_rls is reset to false on exit
    repo = None
    async with rls_bypass(session):
        result = await session.execute(  # type: ignore
            select(Repo).where(Repo.owner == full_name.split("/")[0], Repo.name == full_name.split("/")[1])
        )
        repo = result.scalars().first()
        if repo:
            # Set workspace context (bypass resets to false when CM exits)
            await session.execute(
                text("SELECT set_config('nexops.current_workspace_id', :workspace_id, false)"),
                {"workspace_id": repo.workspace_id}
            )

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

    elif x_github_event == "repository":
        action = payload.get("action")
        if action == "deleted":
            if repo:
                logger.info(f"GitHub repository deleted event received for {full_name} — marking repo as disconnected and preserving historical records")
                repo.status = "disconnected"
                repo.updated_at = datetime.utcnow()
                session.add(repo)

                disconnect_event = Event(
                    workspace_id=repo.workspace_id,
                    repo_id=repo.id,
                    type="repo.disconnected",
                    source="github",
                    message=f"Repository {full_name} was deleted on GitHub. Marked as disconnected; historical data preserved.",
                    severity="warning"
                )
                session.add(disconnect_event)
                await session.commit()
            return JSONResponse(status_code=200, content={"status": "success", "message": f"Repository {full_name} marked as disconnected in NexOps"})
        elif action in ("created", "renamed", "privatized", "publicized"):
            from app.models.user import User
            from app.api.routes.integrations import _perform_sync, SyncRequest
            if repo and repo.user_id:
                user = await session.get(User, repo.user_id)
                if user:
                    req = SyncRequest(provider="github", token="use_stored_token", workspaceId=user.workspace_id)
                    background_tasks.add_task(_perform_sync, req, user, session)
            return JSONResponse(status_code=200, content={"status": "success", "message": f"Triggered sync for repository event {action}"})

    elif x_github_event == "issues":
        action = payload.get("action")
        if action == "opened":
            event_type = "issue.created"
            message = f"New Issue #{payload.get('issue', {}).get('number')} created"
            repo.open_issues += 1
            session.add(repo)
        else:
            return JSONResponse(status_code=200, content={"status": "ignored", "reason": f"Issue action {action} not processed"})

    elif x_github_event == "deployment_status":
        event_type = "deployment.status"
        deployment_data = payload.get("deployment", {})
        status_data = payload.get("deployment_status", {})
        
        commit_hash = deployment_data.get("sha", "")
        environment = deployment_data.get("environment", "staging")
        gh_state = status_data.get("state", "pending")
        deployed_by = payload.get("sender", {}).get("login", "unknown")
        changelog = deployment_data.get("description") or status_data.get("description") or f"Deployment of commit {commit_hash[:7] if commit_hash else ''}"
        
        if gh_state in ("failure", "error"):
            status = "failed"
            severity = "warning"
        elif gh_state == "success":
            status = "success"
            severity = "info"
        elif gh_state == "in_progress":
            status = "running"
            severity = "info"
        else:
            status = gh_state
            severity = "info"
            
        # Calculate risk score
        from app.services.impact_service import calculate_deployment_risk
        risk_calc = await calculate_deployment_risk(session, repo.id)
        risk_score = risk_calc.get("risk_score", 0.0)
        risk_basis = risk_calc.get("risk_basis", "")
        
        # Save or update Deployment row
        from app.models.deployment import Deployment
        deploy_query = select(Deployment).where(
            Deployment.repo_id == repo.id,
            Deployment.commit_hash == commit_hash,
            Deployment.environment == environment
        )
        deploy_result = await session.execute(deploy_query)
        db_deployment = deploy_result.scalars().first()
        
        now = datetime.utcnow()
        if db_deployment:
            db_deployment.status = status
            db_deployment.finished_at = now if status in ("success", "failed") else None
            db_deployment.risk_score = risk_score
            db_deployment.risk_basis = risk_basis
            db_deployment.deployed_by = deployed_by
            db_deployment.changelog = changelog
            db_deployment.updated_at = now
            session.add(db_deployment)
            logger.info(f"Updated deployment {db_deployment.id} for repo {repo.name} to status {status}")
        else:
            db_deployment = Deployment(
                workspace_id=repo.workspace_id,
                repo_id=repo.id,
                commit_hash=commit_hash,
                environment=environment,
                status=status,
                deployed_by=deployed_by,
                changelog=changelog,
                risk_score=risk_score,
                risk_basis=risk_basis,
                deployed_at=now,
                finished_at=now if status in ("success", "failed") else None,
                created_at=now,
                updated_at=now
            )
            session.add(db_deployment)
            logger.info(f"Created new deployment for repo {repo.name} with status {status}")
            
        message = f"Deployment status for {repo.name} in {environment} updated to {status}."

    if event_type == "unknown":
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": f"Event type {x_github_event} not mapped"})

    # 4. Create NexOps Event
    new_event = Event(
        type=event_type,
        repo_id=repo.id,
        source="github",
        payload=payload,
        message=message,
        severity=severity,
        workspace_id=repo.workspace_id
    )
    session.add(new_event)
    await session.commit()  # type: ignore
    await session.refresh(new_event)  # type: ignore

    # 5. Trigger Automation Engine (async via Redis Stream, fallback to background tasks if Redis down)
    from app.services.queue_service import enqueue_event
    enqueued = await enqueue_event(new_event.id, repo.workspace_id)
    if not enqueued:
        logger.warning(f"Redis queue unavailable. Falling back to background task for event {new_event.id}")
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

    # --- Extract user & workspace context early ---
    uid = request.query_params.get("uid")
    target_user = None
    target_workspace_id = None
    if uid:
        from app.api.routes.integrations import _verify_pd_uid_token
        from app.models.user import User
        try:
            raw_uid = _verify_pd_uid_token(uid)
        except ValueError:
            raw_uid = uid.split('.')[0]
        async with rls_bypass(session):
            res_user = await session.execute(select(User).where(User.id == raw_uid))
            target_user = res_user.scalars().first()
            if target_user:
                target_workspace_id = target_user.workspace_id

    # Security & Isolation Hardening: Reject requests where target workspace identity cannot be resolved.
    # Prevents silent fallback to unscoped cross-workspace operations.
    if not target_workspace_id:
        logger.warning(f"PagerDuty webhook rejected — target workspace identity could not be resolved from uid={uid!r}.")
        return JSONResponse(
            status_code=400,
            content={"status": "rejected", "reason": "Target workspace identity could not be resolved from uid parameter."}
        )

    # Set session RLS workspace context unconditionally
    await session.execute(
        text("SELECT set_config('nexops.current_workspace_id', :workspace_id, false)"),
        {"workspace_id": target_workspace_id}
    )

    # Hardened workspace-scoped idempotency check: unconditionally filtered by target_workspace_id
    if pd_event_id:
        idempotency_query = select(Event).where(
            Event.workspace_id == target_workspace_id,
            Event.pd_event_id == pd_event_id
        )
        existing_event_result = await session.execute(idempotency_query)  # type: ignore
        existing_event = existing_event_result.scalars().first()
        if existing_event:
            logger.warning(f"Duplicate PagerDuty event {pd_event_id} — already processed as "
                           f"NexOps event {existing_event.id} for workspace {existing_event.workspace_id}. Skipping.")
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

        # Find original event by pd_incident_id, unconditionally scoped to target_workspace_id
        orig_query = select(Event).where(
            Event.workspace_id == target_workspace_id,
            Event.source == "pagerduty",
            Event.pd_incident_id == pd_incident_id,
            Event.type == "pagerduty.incident"
        )
        orig_event_result = await session.execute(  # type: ignore
            orig_query.order_by(Event.created_at.desc()).limit(1)
        )
        orig_event = orig_event_result.scalars().first()

        # Find open or investigating incident by pd_incident_id, unconditionally scoped to target_workspace_id
        matched_incident = None
        if orig_event and orig_event.pd_incident_id:
            inc_query = select(Incident).where(
                Incident.workspace_id == target_workspace_id,
                Incident.pd_incident_id == orig_event.pd_incident_id,
                Incident.status.in_(["open", "investigating"])
            )
            inc_result = await session.execute(inc_query.limit(1))  # type: ignore
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
                           f"no matching open/investigating NexOps incident found in workspace {target_workspace_id}.")
            return JSONResponse(status_code=200, content={
                "status": "unmatched",
                "reason": f"No open/investigating NexOps incident found for PagerDuty incident {pd_incident_id}"
            })

    # Only incident.triggered (and other unrecognised types) fall through to create an Event
    if event_type and event_type not in ("incident.triggered",) and event_type.startswith("incident."):
        logger.info(f"PagerDuty event type {event_type!r} is not incident.triggered — ignoring.")
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": f"event_type {event_type!r} not processed"})

    # Repo matching: unconditionally scoped to target_workspace_id
    repo = None
    if pd_service_name:
        async with rls_bypass(session):
            res_repo = await session.execute(
                select(Repo).where(
                    Repo.workspace_id == target_workspace_id,
                    Repo.name.ilike(f"%{pd_service_name}%")
                )
            )
            repo = res_repo.scalars().first()

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
        severity="error",
        workspace_id=repo.workspace_id
    )
    session.add(new_event)
    await session.commit()  # type: ignore
    await session.refresh(new_event)  # type: ignore

    # Trigger Automation Engine (run background task for immediate process execution)
    from app.services.queue_service import enqueue_event
    await enqueue_event(new_event.id, repo.workspace_id)
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
