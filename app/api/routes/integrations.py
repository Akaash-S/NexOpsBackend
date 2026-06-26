from fastapi import APIRouter, Depends, HTTPException, Body, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.core.database import get_session
from app.core.security import get_current_user, get_uid, invalidate_user_cache
from app.services.vcs_service import vcs_service
from app.core.crypto import encrypt_secret
from app.models.repo import Repo
from app.models.user import User
from app.models.event import Event
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import httpx
import logging
import hmac
import hashlib
import time
from app.core.config import settings

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
            invalidate_user_cache(user.id)

        # 2. Persist repos and generate 'Synthetic History' for NEW ones
        synced_repos = []
        for repo_data in new_repos:
            # Check if repo already exists
            existing_result = await session.execute(  # type: ignore
                select(Repo).where(
                    Repo.name == repo_data.name,
                    Repo.platform == repo_data.platform
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
                repo.updated_at = datetime.utcnow()
            else:
                # Create new repo
                repo = repo_data
                is_new = True
            
            session.add(repo)
            await session.flush()  # type: ignore
            synced_repos.append(repo)

            # Record a real sync event for newly-tracked repos only.
            # No synthetic deployments or fake activity events — real data only.
            if is_new:
                sync_event = Event(
                    repo_id=repo.id,
                    type="repo.synced",
                    source=request.provider,
                    message=f"Repository {repo.name} added to NexOps via {request.provider} sync",
                    severity="info",
                    created_at=datetime.utcnow()
                )
                session.add(sync_event)
        
        # 3. Fetch real CI status for all GitHub repos
        if request.provider == "github":
            for repo in synced_repos:
                ci_status = await vcs_service.fetch_github_ci_status(
                    token=token,
                    owner=repo.owner or "unknown",
                    repo=repo.name
                )
                repo.ci_status = ci_status
                session.add(repo)
                logger.info(f"CI status for {repo.owner}/{repo.name}: {ci_status}")
            await session.flush()  # type: ignore
        
        # 4. Parse nexops.yaml for all repositories to build real Dependency rows
        if request.provider == "github":
            import yaml
            from app.models.dependency import Dependency
            for repo in synced_repos:
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
                                        dep = Dependency(
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
                    logger.error(f"Failed to parse nexops.yaml for {repo.name}: {yaml_err}")
            await session.flush()  # type: ignore
        
        await session.commit()  # type: ignore
        return {"status": "success", "synced": len(new_repos)}
        
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
    if not code:
        return RedirectResponse("/onboarding?error=missing_code")

    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="GitHub Client configuration is missing")

    # Validate the signed state token — reject the callback if it's invalid or expired
    if not state:
        logger.warning("GitHub OAuth callback received with no state parameter.")
        return RedirectResponse("/onboarding?error=invalid_state")

    try:
        uid = _verify_oauth_state(state)
    except ValueError as state_err:
        logger.warning(f"GitHub OAuth callback state validation failed: {state_err}")
        return RedirectResponse("/onboarding?error=invalid_state")

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
                return RedirectResponse("/onboarding?error=oauth_failed")

            access_token = data["access_token"]
    except Exception as oauth_err:
        logger.error(f"GitHub OAuth code exchange failed: {oauth_err}")
        return RedirectResponse("/onboarding?error=oauth_failed")

    # Encrypt and save the token to the user identified by the validated state token
    encrypted_token = encrypt_secret(access_token)

    user_result = await session.execute(select(User).where(User.id == uid))  # type: ignore
    user = user_result.scalar_one_or_none()

    if not user:
        logger.error(f"GitHub OAuth callback: no user found for uid={uid} from validated state.")
        return RedirectResponse("/onboarding?error=user_not_found")

    user.github_access_token = encrypted_token
    session.add(user)
    await session.commit()  # type: ignore
    invalidate_user_cache(user.id)
    logger.info(f"Successfully saved encrypted GitHub access token for user {user.id}")

    return RedirectResponse("/onboarding?success=github_connected")
