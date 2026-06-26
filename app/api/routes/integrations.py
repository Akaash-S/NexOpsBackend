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
from datetime import datetime
import httpx
import logging
from app.core.config import settings

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
                # Update existing repo
                repo.description = repo_data.description
                repo.language = repo_data.language
                repo.default_branch = repo_data.default_branch
                repo.owner = repo_data.owner
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
        
        # 3. Parse nexops.yaml for all repositories to build real Dependency rows
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
    uid: Optional[str] = None
):
    """
    Redirect to GitHub OAuth page.
    """
    client_id = settings.GITHUB_CLIENT_ID or "dummy_github_client_id"
    # Match registration on GitHub
    redirect_uri = "http://localhost:8000/api/v1/integrations/github/callback"
    
    state = uid or "anonymous"
    
    github_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=repo,user"
        f"&state={state}"
    )
    return RedirectResponse(github_url)

@router.get("/integrations/github/callback")
async def github_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """
    OAuth Callback. Exchange code for token, encrypt, save to user, and redirect.
    """
    if not code:
        return RedirectResponse("http://localhost:3000/onboarding?error=missing_code")

    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="GitHub Client configuration is missing")

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": "http://localhost:8000/api/v1/integrations/github/callback"
                },
                timeout=10.0
            )
            res.raise_for_status()
            data = res.json()
            if "access_token" not in data:
                logger.error(f"GitHub OAuth token exchange failed: {data}")
                return RedirectResponse("http://localhost:3000/onboarding?error=oauth_failed")
            
            access_token = data["access_token"]
    except Exception as oauth_err:
        logger.error(f"GitHub OAuth code exchange failed: {oauth_err}")
        return RedirectResponse("http://localhost:3000/onboarding?error=oauth_failed")

    # Encrypt the token
    encrypted_token = encrypt_secret(access_token)

    # Save to user
    user = None
    if state and state != "anonymous":
        user_result = await session.execute(select(User).where(User.id == state))  # type: ignore
        user = user_result.scalar_one_or_none()

    if not user:
        # Fallback: get the first user in database
        user_result = await session.execute(select(User))  # type: ignore
        user = user_result.scalars().first()

    if user:
        user.github_access_token = encrypted_token
        session.add(user)
        await session.commit()  # type: ignore
        invalidate_user_cache(user.id)
        logger.info(f"Successfully saved encrypted access token for user {user.id}")
    else:
        logger.warning("No user found to save access token.")

    # Redirect to frontend onboarding page
    return RedirectResponse("http://localhost:3000/onboarding?success=github_connected")
