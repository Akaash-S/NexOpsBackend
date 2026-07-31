from fastapi import APIRouter, Depends, HTTPException, Body, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import select, func
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.core.database import get_session
from app.core.security import get_current_user, get_uid, invalidate_user_cache
from app.services.vcs_service import vcs_service
from app.core.crypto import encrypt_secret
from app.core.rate_limit import limiter
from app.models.repo import Repo
from app.models.user import User
from app.models.event import Event
from app.models.workspace_acknowledgment import WorkspaceAcknowledgment
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import httpx
import logging
import hmac
import hashlib
import time
from app.core.config import settings

async def _is_terms_acknowledged(session: AsyncSession, workspace_id: str) -> bool:
    """Check if the workspace has recorded an acknowledgment of Terms of Service and Privacy Notice."""
    result = await session.execute(
        select(WorkspaceAcknowledgment).where(WorkspaceAcknowledgment.workspace_id == workspace_id)
    )
    return result.scalars().first() is not None


# ── OAuth State Token Helpers ────────────────────────────────────────────
# State is a signed token of the form "uid:expiry:hmac" where the HMAC is
# computed over "uid:expiry" using the ENCRYPTION_KEY as the signing secret.
# This lets us trust the uid on the callback without storing server-side state.
_STATE_TTL_SECONDS = 300  # 5-minute window for OAuth round-trip

def _make_oauth_state(uid: str) -> str:
    """Create a time-limited, HMAC-signed state token encoding the user's UID."""
    expiry = int(time.time()) + _STATE_TTL_SECONDS
    payload = f"{uid}:{expiry}"
    sig = hmac.new(
        settings.ENCRYPTION_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"{payload}:{sig}"

def _verify_oauth_state(state: str) -> str:
    """
    Validate a state token and return the embedded uid.
    Raises ValueError if the token is malformed, expired, or signature-invalid.
    """
    try:
        uid, expiry_str, received_sig = state.rsplit(":", 2)
    except ValueError:
        raise ValueError("Malformed state token.")

    payload = f"{uid}:{expiry_str}"
    expected_sig = hmac.new(
        settings.ENCRYPTION_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, received_sig):
        raise ValueError("State token signature invalid.")

    if int(time.time()) > int(expiry_str):
        raise ValueError("State token has expired.")

    return uid

# ── PagerDuty Webhook UID Token Helpers ──────────────────────────────────
# The PagerDuty webhook URL embeds a signed uid token of the form "uid.hmac".
# This prevents an attacker who discovers another user's raw UID from anchoring
# an incoming webhook to a workspace they don't own (security audit P2-F5).
_PD_UID_SCOPE = "nexops-pd-webhook-v1"

def _make_pd_uid_token(uid: str) -> str:
    """Create a permanently-valid HMAC-signed uid token for PagerDuty webhook URLs."""
    payload = f"{_PD_UID_SCOPE}:{uid}"
    sig = hmac.new(
        settings.ENCRYPTION_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:32]  # 128-bit hex prefix — sufficient for URL embeds
    return f"{uid}.{sig}"

def _verify_pd_uid_token(token: str) -> str:
    """
    Validate a signed PagerDuty webhook uid token and return the embedded uid.
    Raises ValueError if the token is malformed or signature-invalid.
    """
    try:
        uid, received_sig = token.rsplit(".", 1)
    except ValueError:
        raise ValueError("Malformed PagerDuty uid token.")

    payload = f"{_PD_UID_SCOPE}:{uid}"
    expected_sig = hmac.new(
        settings.ENCRYPTION_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:32]

    if not hmac.compare_digest(expected_sig, received_sig):
        raise ValueError("PagerDuty uid token signature invalid — possible SSRF or spoofing attempt.")

    return uid

router = APIRouter(tags=["Integrations"])
logger = logging.getLogger("nexops.integrations")

class SyncRequest(BaseModel):
    provider: str
    token: str
    workspace_id: str = Field(alias="workspaceId")

    class Config:
        validate_by_name = True

async def _perform_sync(request: SyncRequest, user: User, session: AsyncSession):
    try:
        # Verify workspace ownership first before any token processing or external API calls
        if not user.workspace_id or request.workspace_id != user.workspace_id:
            raise HTTPException(status_code=403, detail="Workspace access denied: user cannot sync to a mismatched workspace")

        token = request.token
        if (not token or token == "use_stored_token") and request.provider == "github":
            if user.github_access_token:
                from app.core.crypto import decrypt_secret
                token = decrypt_secret(user.github_access_token)
            else:
                raise HTTPException(status_code=400, detail="No stored GitHub access token found. Please connect GitHub first.")

        # 1. Fetch repos from provider
        new_repos = await vcs_service.sync_repositories(
            provider=request.provider,
            token=token,
            workspace_id=request.workspace_id
        )

        # 1.5 Update user github token if provider is github
        if request.provider == "github" and request.token != "use_stored_token":
            db_user = await session.get(User, user.id)
            if not db_user:
                raise HTTPException(status_code=404, detail="User not found")
            db_user.github_access_token = encrypt_secret(token)
            session.add(db_user)
            await session.flush()  # type: ignore
            await invalidate_user_cache(user.id)

        # 2. Persist repos and generate 'Synthetic History' for NEW ones
        synced_repos = []
        for repo_data in new_repos:
            # Associate repo with the syncing user
            repo_data.user_id = user.id

            # Check if repo already exists for this user
            existing_result = await session.execute(  # type: ignore
                select(Repo).where(
                    Repo.name == repo_data.name,
                    Repo.platform == repo_data.platform,
                    Repo.user_id == user.id
                )
            )
            repo = existing_result.scalar_one_or_none()
            
            is_new = False
            if repo:
                # Update existing repo — propagate all real GitHub fields
                repo.description = repo_data.description
                repo.language = repo_data.language
                repo.default_branch = repo_data.default_branch
                repo.owner = repo_data.owner
                repo.open_issues = repo_data.open_issues
                repo.stars = repo_data.stars
                repo.forks = repo_data.forks
                repo.last_commit_at = repo_data.last_commit_at
                repo.github_updated_at = repo_data.github_updated_at
                repo.activity = repo_data.activity
                repo.updated_at = datetime.utcnow()
            else:
                # Create new repo
                repo = repo_data
                is_new = True
            
            session.add(repo)
            await session.flush()  # type: ignore
            synced_repos.append(repo)

            if is_new:
                sync_event = Event(
                    workspace_id=repo.workspace_id,
                    repo_id=repo.id,
                    type="repo.synced",
                    source=request.provider,
                    message=f"Repository {repo.name} added to NexOps via {request.provider} sync",
                    severity="info",
                    created_at=datetime.utcnow()
                )
                session.add(sync_event)

        # 1.8 Detect and reconcile deleted/unlinked repositories (soft-disconnect, preserving historical records)
        # ONLY reconcile if new_repos was successfully fetched and non-empty to prevent accidental mass-disconnections on API failures
        if len(new_repos) > 0:
            active_repo_names = set()
            for r in new_repos:
                active_repo_names.add(r.name)
                if r.owner:
                    active_repo_names.add(f"{r.owner}/{r.name}")

            existing_db_repos_res = await session.execute(
                select(Repo).where(
                    (Repo.user_id == user.id) | (Repo.workspace_id == user.workspace_id),
                    Repo.platform == request.provider
                )
            )
            existing_db_repos = existing_db_repos_res.scalars().all()
            for db_repo in existing_db_repos:
                repo_identifiers = {db_repo.name}
                if db_repo.owner:
                    repo_identifiers.add(f"{db_repo.owner}/{db_repo.name}")
                
                if not repo_identifiers.intersection(active_repo_names):
                    if db_repo.status != "disconnected":
                        logger.info(f"Marking deleted/unlinked repository as disconnected in NexOps: {db_repo.name} (id: {db_repo.id})")
                        db_repo.status = "disconnected"
                        db_repo.updated_at = datetime.utcnow()
                        session.add(db_repo)
                        
                        disconnect_event = Event(
                            workspace_id=db_repo.workspace_id,
                            repo_id=db_repo.id,
                            type="repo.disconnected",
                            source=request.provider,
                            message=f"Repository {db_repo.name} was deleted or unlinked on {request.provider}. Marked as disconnected; historical data preserved.",
                            severity="warning",
                            created_at=datetime.utcnow()
                        )
                        session.add(disconnect_event)
        else:
            logger.warning("Skipping repository disconnection reconciliation: GitHub API returned 0 repositories or sync token failed.")
        await session.flush()  # type: ignore

        # 3. Fetch real CI status for active GitHub repos only and recalculate real health score
        if request.provider == "github":
            for repo in synced_repos:
                if getattr(repo, "status", "active") == "disconnected":
                    continue
                try:
                    ci_status = await vcs_service.fetch_github_ci_status(
                        token=token,
                        owner=repo.owner or "unknown",
                        repo=repo.name
                    )
                    repo.ci_status = ci_status
                    
                    # Recalculate health_score dynamically based on real CI status and issue counts
                    base_health = 100.0
                    if ci_status == "failing":
                        base_health -= 30.0
                    elif ci_status in ("no_runs", "unknown", "none"):
                        base_health -= 25.0  # Penalty for unverified CI pipeline status
                    if repo.open_issues > 0:
                        base_health -= min(repo.open_issues * 2.0, 30.0)
                    if getattr(repo, "vulnerabilities", 0) > 0:
                        base_health -= min(repo.vulnerabilities * 10.0, 40.0)
                    repo.health_score = round(max(10.0, base_health), 1)

                    session.add(repo)
                    logger.info(f"CI status for {repo.owner}/{repo.name}: {ci_status} | Health Score: {repo.health_score}% | Activity: {repo.activity}%")
                except Exception as ci_err:
                    logger.warning(f"Failed to fetch CI status for {repo.name}: {ci_err}")
            await session.flush()  # type: ignore
        
        # 4. Parse nexops.yaml for active repositories to build real Dependency rows
        if request.provider == "github":
            import yaml
            from app.models.dependency import Dependency
            for repo in synced_repos:
                if getattr(repo, "status", "active") == "disconnected":
                    continue
                try:
                    file_data = await vcs_service.fetch_github_file_content(
                        token=token,
                        owner=repo.owner or "unknown",
                        repo=repo.name,
                        path="nexops.yaml"
                    )
                    content = file_data.get("content", "")
                    if content and not content.startswith("//"):
                        config_data = yaml.safe_load(content)
                        if config_data and "dependencies" in config_data:
                            for dep_entry in config_data["dependencies"]:
                                # Support both dict format {repo: org/name, type: api}
                                # and bare string format (legacy)
                                if isinstance(dep_entry, dict):
                                    dep_full_name = dep_entry.get("repo", "")
                                    dep_type = dep_entry.get("type", "api")
                                    dep_label = dep_entry.get("label", dep_type)
                                else:
                                    dep_full_name = str(dep_entry)
                                    dep_type = "api"
                                    dep_label = "api"

                                # Match by the repo name component (last part of org/repo)
                                dep_repo_name = dep_full_name.split("/")[-1] if "/" in dep_full_name else dep_full_name

                                # Find target repo tracked in NexOps
                                target_result = await session.execute(  # type: ignore
                                    select(Repo).where(
                                        Repo.name == dep_repo_name
                                    )
                                )
                                target_repo = target_result.scalars().first()
                                if target_repo:
                                    # Create dependency edge if not already present
                                    existing_dep_result = await session.execute(  # type: ignore
                                        select(Dependency).where(
                                            Dependency.source_repo_id == repo.id,
                                            Dependency.target_repo_id == target_repo.id
                                        )
                                    )
                                    existing_dep = existing_dep_result.scalars().first()
                                    if not existing_dep:
                                        if not repo.workspace_id:
                                            raise ValueError(f"Repository {repo.name} lacks a valid workspace_id")
                                        dep = Dependency(
                                            workspace_id=repo.workspace_id,
                                            source_repo_id=repo.id,
                                            target_repo_id=target_repo.id,
                                            type=dep_type,
                                            label=dep_label
                                        )
                                        session.add(dep)
                                        logger.info(f"Dependency edge: {repo.name} -> {dep_repo_name} ({dep_type})")
                                else:
                                    logger.info(f"nexops.yaml: dependency '{dep_full_name}' declared but not yet tracked in NexOps — skipping edge creation")
                except Exception as yaml_err:
                    logger.warning(f"Failed to parse nexops.yaml for {repo.name}: {yaml_err}")
            await session.flush()  # type: ignore

        # 5. Fetch historical deployments & register webhooks for active GitHub repos
        if request.provider == "github":
            from app.models.deployment import Deployment
            from app.services.impact_service import calculate_deployment_risk
            
            # Base backend URL for webhook endpoint
            webhook_endpoint = "https://nexopsbackend.onrender.com/api/v1/webhooks/github"
            
            for repo in synced_repos:
                if getattr(repo, "status", "active") == "disconnected":
                    continue
                owner = repo.owner or "unknown"
                # Register webhook on GitHub repository
                await vcs_service.register_github_webhook(
                    token=token,
                    owner=owner,
                    repo=repo.name,
                    webhook_url=webhook_endpoint,
                    secret=settings.GITHUB_WEBHOOK_SECRET or ""
                )
                
                # Fetch recent deployments
                recent_deps = await vcs_service.fetch_github_deployments(
                    token=token,
                    owner=owner,
                    repo=repo.name
                )
                for dep_item in recent_deps:
                    commit_hash = dep_item.get("sha", "")
                    env = dep_item.get("environment", "production")
                    st = dep_item.get("state", "success")
                    
                    risk_calc = await calculate_deployment_risk(session, repo.id)
                    
                    now = datetime.utcnow()
                    gh_created_at = dep_item.get("created_at")
                    dep_timestamp = now
                    if gh_created_at:
                        try:
                            dep_timestamp = datetime.fromisoformat(gh_created_at.replace("Z", "+00:00")).replace(tzinfo=None)
                        except Exception:
                            dep_timestamp = now

                    dep_query = select(Deployment).where(
                        Deployment.repo_id == repo.id,
                        Deployment.commit_hash == commit_hash,
                        Deployment.environment == env,
                        Deployment.deployed_at == dep_timestamp
                    )
                    dep_res = await session.execute(dep_query)
                    existing_dep = dep_res.scalars().first()

                    if existing_dep:
                        existing_dep.deployed_at = dep_timestamp
                        existing_dep.finished_at = dep_timestamp
                        existing_dep.updated_at = now
                        session.add(existing_dep)
                        logger.info(f"Updated existing deployment timestamp for {repo.name}: {commit_hash[:7]} (dated {dep_timestamp})")
                    else:
                        new_dep = Deployment(
                            workspace_id=repo.workspace_id,
                            repo_id=repo.id,
                            commit_hash=commit_hash,
                            environment=env,
                            status=st if st != "success" else "success",
                            deployed_by=dep_item.get("creator", "unknown"),
                            changelog=dep_item.get("description", f"Deployment of commit {commit_hash[:7] if commit_hash else ''}"),
                            risk_score=risk_calc.get("risk_score", 0.0),
                            risk_basis=risk_calc.get("risk_basis", ""),
                            deployed_at=dep_timestamp,
                            finished_at=dep_timestamp,
                            created_at=now,
                            updated_at=now
                        )
                        session.add(new_dep)
                        logger.info(f"Populated new deployment during sync for {repo.name}: {commit_hash[:7]} (dated {dep_timestamp})")
            await session.flush()  # type: ignore

        # Stamp the successful sync time on the user record
        db_user = await session.get(User, user.id)
        if db_user:
            db_user.github_last_synced_at = datetime.utcnow()
            session.add(db_user)
            await invalidate_user_cache(user.id)

        await session.commit()  # type: ignore
        return {"status": "success", "synced": len(new_repos)}
        
    except HTTPException:
        await session.rollback()  # type: ignore
        raise
    except Exception as e:
        await session.rollback()  # type: ignore
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/integrations/sync-manual")
async def sync_vcs_repositories_manual(
    request: SyncRequest,
    user = Depends(get_current_user),
    session = Depends(get_session)
):
    """
    Sync repositories manually using a pasted token.
    """
    return await _perform_sync(request, user, session)

@router.post("/integrations/sync")
async def sync_vcs_repositories(
    request: SyncRequest,
    user = Depends(get_current_user),
    session = Depends(get_session)
):
    """
    Fallback alias for standard sync endpoint.
    """
    return await _perform_sync(request, user, session)

@router.get("/integrations/github/connect")
@limiter.limit("10/minute")
async def github_connect(
    request: Request,
    user: User = Depends(get_current_user),
):
    """
    Redirect to GitHub OAuth page.
    The user must be authenticated. A signed, time-limited state token is generated
    encoding the authenticated user's UID — their raw UID is never sent as the state.
    """
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub OAuth is not configured.")

    # Build the callback URL from the incoming request host so it works across environments
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/v1/integrations/github/callback"

    state = _make_oauth_state(user.id)

    github_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.GITHUB_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=repo,user"
        f"&state={state}"
    )
    return RedirectResponse(github_url)


@router.get("/integrations/github/callback")
@limiter.limit("10/minute")
async def github_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """
    OAuth Callback. Validates the signed state token, exchanges the code for an access
    token, encrypts it, and saves it to the correct user's record.
    """
    _frontend = settings.FRONTEND_URL.rstrip("/")

    if not code:
        return RedirectResponse(f"{_frontend}/onboarding?error=missing_code")

    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="GitHub Client configuration is missing")

    # Validate the signed state token — reject the callback if it's invalid or expired
    if not state:
        logger.warning("GitHub OAuth callback received with no state parameter.")
        return RedirectResponse(f"{_frontend}/onboarding?error=invalid_state")

    try:
        uid = _verify_oauth_state(state)
    except ValueError as state_err:
        logger.warning(f"GitHub OAuth callback state validation failed: {state_err}")
        return RedirectResponse(f"{_frontend}/onboarding?error=invalid_state")

    # Exchange code for access token
    try:
        base_url = str(request.base_url).rstrip("/")
        redirect_uri = f"{base_url}/api/v1/integrations/github/callback"

        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                timeout=10.0
            )
            res.raise_for_status()
            data = res.json()
            if "access_token" not in data:
                logger.error(f"GitHub OAuth token exchange failed: {data}")
                return RedirectResponse(f"{_frontend}/onboarding?error=oauth_failed")

            access_token = data["access_token"]
    except Exception as oauth_err:
        logger.error(f"GitHub OAuth code exchange failed: {oauth_err}")
        return RedirectResponse(f"{_frontend}/onboarding?error=oauth_failed")

    # Encrypt and save the token to the user identified by the validated state token
    encrypted_token = encrypt_secret(access_token)

    user_result = await session.execute(select(User).where(User.id == uid))  # type: ignore
    user = user_result.scalar_one_or_none()

    if not user:
        logger.error(f"GitHub OAuth callback: no user found for uid={uid} from validated state.")
        return RedirectResponse(f"{_frontend}/onboarding?error=user_not_found")

    user.github_access_token = encrypted_token
    session.add(user)
    await session.commit()  # type: ignore
    await invalidate_user_cache(user.id)
    logger.info(f"Successfully saved encrypted GitHub access token for user {user.id}")

    return RedirectResponse(f"{_frontend}/onboarding?success=github_connected")


@router.get("/integrations/status")
async def get_integration_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Return real connection status for all integration providers."""
    from app.core.crypto import decrypt_secret

    # GitHub: check whether the encrypted token exists AND can be decrypted
    github_connected = False
    if user.github_access_token:
        try:
            token = decrypt_secret(user.github_access_token)
            github_connected = bool(token)
        except Exception:
            github_connected = False

    # Count tracked repos (scoped to this user)
    count_result = await session.execute(
        select(func.count(Repo.id)).where(Repo.user_id == user.id)
    )
    synced_repos_count = count_result.scalar() or 0

    # PagerDuty: check whether the encrypted token exists AND can be decrypted
    pagerduty_connected = False
    if user.pagerduty_access_token:
        try:
            pd_token = decrypt_secret(user.pagerduty_access_token)
            pagerduty_connected = bool(pd_token)
        except Exception:
            pagerduty_connected = False

    # Terms Acknowledgment Gate check for status response
    terms_acknowledged = await _is_terms_acknowledged(session, user.workspace_id)

    return {
        "terms_acknowledged": terms_acknowledged,
        "github": {
            "connected": github_connected,
            "config": "OAuth Connected (read-only)" if github_connected else "Not configured",
            "synced_repos_count": synced_repos_count,
            "latest_sync_at": user.github_last_synced_at.isoformat() if user.github_last_synced_at else None,
        },
        "pagerduty": {
            "connected": pagerduty_connected,
            "config": "API Token Connected" if pagerduty_connected else "Not configured",
        },
    }


@router.post("/integrations/terms/acknowledge")
async def acknowledge_terms(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Record one-time per-workspace acknowledgment of Terms of Service and Privacy Notice."""
    existing = await session.execute(
        select(WorkspaceAcknowledgment).where(WorkspaceAcknowledgment.workspace_id == user.workspace_id)
    )
    ack = existing.scalars().first()
    if not ack:
        ack = WorkspaceAcknowledgment(
            workspace_id=user.workspace_id,
            user_id=user.id,
            terms_version="v1.0",
            acknowledged_at=datetime.utcnow()
        )
        session.add(ack)
        await session.commit()
        logger.info(f"Workspace {user.workspace_id} acknowledged Terms of Service v1.0 by user {user.id}")
    return {
        "status": "acknowledged",
        "workspace_id": user.workspace_id,
        "user_id": user.id,
        "terms_version": ack.terms_version,
        "acknowledged_at": ack.acknowledged_at.isoformat()
    }


@router.get("/integrations/github/oauth-url")
async def get_github_oauth_url(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return the GitHub OAuth URL as JSON so the frontend can redirect with auth."""
    # Gate check: require terms & privacy acknowledgment for workspace
    if not await _is_terms_acknowledged(session, user.workspace_id):
        raise HTTPException(
            status_code=403,
            detail="Terms of Service and Privacy Notice must be acknowledged before connecting integrations.",
            headers={"X-NexOps-Terms-Gate": "terms_not_acknowledged"}
        )

    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub OAuth is not configured.")

    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/v1/integrations/github/callback"
    state = _make_oauth_state(user.id)

    github_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.GITHUB_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=repo,user"
        f"&state={state}"
    )
    return {"url": github_url}


@router.post("/integrations/github/disconnect")
async def disconnect_github(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Clear the stored GitHub access token. Keeps existing synced repo data in place."""
    db_user = await session.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    db_user.github_access_token = None
    session.add(db_user)
    await session.commit()  # type: ignore
    await invalidate_user_cache(user.id)
    logger.info(f"GitHub disconnected for user {user.id} — existing repo data preserved")

    return {"status": "disconnected"}


class PagerDutyConnectRequest(BaseModel):
    token: str


@router.post("/integrations/pagerduty/connect")
@limiter.limit("10/minute")
async def connect_pagerduty(
    request: Request,
    response: Response,
    payload: PagerDutyConnectRequest = Body(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Validate API token, register a webhook subscription on PagerDuty, and store credentials."""
    # Gate check: require terms & privacy acknowledgment for workspace
    if not await _is_terms_acknowledged(session, user.workspace_id):
        raise HTTPException(
            status_code=403,
            detail="Terms of Service and Privacy Notice must be acknowledged before connecting integrations.",
            headers={"X-NexOps-Terms-Gate": "terms_not_acknowledged"}
        )

    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="PagerDuty API token cannot be empty.")


    from app.services.pagerduty_service import pagerduty_service
    from app.core.crypto import encrypt_secret

    # 1. Validate the token against PagerDuty API
    is_valid = await pagerduty_service.validate_token(token)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid PagerDuty API token. Validation call failed.")

    # 2. Register a webhook subscription on PagerDuty pointing to our webhook endpoint
    base_url = str(request.base_url).rstrip("/")
    # Security audit P2-F5: sign the uid so incoming webhooks can't be anchored to
    # an arbitrary user's workspace by an attacker who discovers a raw uid.
    signed_uid = _make_pd_uid_token(user.id)
    webhook_url = f"{base_url}/api/v1/webhooks/pagerduty?uid={signed_uid}"

    subscription_id = None
    webhook_secret = None

    # Check if the URL is local (localhost, 127.0.0.1, or private IP address) or not HTTPS
    from urllib.parse import urlparse
    parsed_url = urlparse(webhook_url)
    hostname = parsed_url.hostname or ""
    is_local = (
        hostname == "localhost"
        or hostname == "127.0.0.1"
        or hostname.startswith("192.168.")
        or hostname.startswith("172.")
        or hostname.startswith("10.")
        or not webhook_url.startswith("https://")
    )

    if is_local:
        logger.warning(f"Local development environment detected ({webhook_url}). Skipping PagerDuty webhook registration and using local dummy credentials.")
        subscription_id = "local-dev-dummy-id"
        webhook_secret = settings.PAGERDUTY_WEBHOOK_SECRET or "local-dev-dummy-secret"
    else:
        try:
            subscription = await pagerduty_service.create_webhook_subscription(token, webhook_url)
            subscription_id = subscription.get("id")
            webhook_secret = subscription.get("delivery_method", {}).get("secret")
        except Exception as e:
            error_msg = str(e)
            if "URL is not allowed" in error_msg:
                logger.warning(f"PagerDuty rejected local URL ({webhook_url}) during webhook registration. Falling back to local integration mode.")
                subscription_id = "local-dev-dummy-id"
                webhook_secret = settings.PAGERDUTY_WEBHOOK_SECRET or "local-dev-dummy-secret"
            else:
                logger.error(f"Failed to create PagerDuty webhook subscription: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Successfully validated token, but failed to register webhook subscription with PagerDuty: {str(e)}"
                )

    if not subscription_id or not webhook_secret:
        raise HTTPException(
            status_code=500,
            detail="PagerDuty webhook subscription response missing 'id' or 'secret'."
        )

    # 3. Store encrypted credentials in the database
    db_user = await session.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    db_user.pagerduty_access_token = encrypt_secret(token)
    db_user.pagerduty_webhook_secret = encrypt_secret(webhook_secret)
    db_user.pagerduty_webhook_subscription_id = subscription_id

    session.add(db_user)
    await session.commit()  # type: ignore
    await invalidate_user_cache(user.id)
    logger.info(f"PagerDuty connected successfully for user {user.id}")

    return {
        "status": "connected",
        "webhook_subscription_id": subscription_id
    }


@router.delete("/integrations/pagerduty/disconnect")
async def disconnect_pagerduty(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Remove the stored PagerDuty credential and attempt to clean up registered webhook subscription."""
    db_user = await session.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Decrypt token and attempt best-effort deletion of subscription
    if db_user.pagerduty_access_token and db_user.pagerduty_webhook_subscription_id:
        from app.core.crypto import decrypt_secret
        from app.services.pagerduty_service import pagerduty_service
        try:
            token = decrypt_secret(db_user.pagerduty_access_token)
            subscription_id = db_user.pagerduty_webhook_subscription_id
            await pagerduty_service.delete_webhook_subscription(token, subscription_id)
        except Exception as delete_err:
            logger.error(f"Best-effort PagerDuty webhook cleanup failed: {delete_err}")

    # Clear columns in user model
    db_user.pagerduty_access_token = None
    db_user.pagerduty_webhook_secret = None
    db_user.pagerduty_webhook_subscription_id = None

    session.add(db_user)
    await session.commit()  # type: ignore
    await invalidate_user_cache(user.id)
    logger.info(f"PagerDuty disconnected for user {user.id}")

    return {"status": "disconnected"}
