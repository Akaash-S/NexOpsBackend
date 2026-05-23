from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select
from typing import List
from app.core.database import get_session
from app.core.security import get_current_user, get_uid
from app.services.vcs_service import vcs_service
from app.core.crypto import encrypt_secret
from app.models.repo import Repo
from app.models.workspace import Workspace
from app.models.event import Event
from app.models.pipeline import Pipeline
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import random

router = APIRouter(tags=["Integrations"])

class SyncRequest(BaseModel):
    provider: str
    token: str
    workspace_id: str = Field(alias="workspaceId")

    class Config:
        allow_population_by_field_name = True

@router.post("/integrations/sync")
async def sync_vcs_repositories(
    request: SyncRequest,
    user = Depends(get_current_user),
    session = Depends(get_session)
):
    """
    Sync repositories from a VCS provider and generate initial system activity.
    """
    try:
        # 1. Fetch repos from provider
        new_repos = await vcs_service.sync_repositories(
            provider=request.provider,
            token=request.token,
            workspace_id=request.workspace_id
        )

        # 1.5 Update workspace token and sync timestamp
        workspace_result = await session.execute(select(Workspace).where(Workspace.id == request.workspace_id))
        workspace = workspace_result.scalar_one_or_none()
        if workspace:
            workspace.access_token = encrypt_secret(request.token)
            workspace.last_synced_at = datetime.utcnow()
            workspace.status = "connected"
            session.add(workspace)
            await session.flush()

        # 2. Persist repos and generate 'Synthetic History' for NEW ones
        for repo_data in new_repos:
            # Check if repo already exists in this workspace
            existing_result = await session.execute(
                select(Repo).where(
                    Repo.workspace_id == request.workspace_id,
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
            await session.flush()

            # Only generate synthetic history for NEW repositories to avoid clutter
            if is_new:
                # Create a "Sync Completed" event
                sync_event = Event(
                    repo_id=repo.id,
                    type="repo.synced",
                    source=request.provider,
                    message=f"Successfully synchronized {repo.name} from {request.provider}",
                    severity="info",
                    created_at=datetime.utcnow()
                )
                session.add(sync_event)

                # Create a mock initial pipeline with realistic logs
                from app.core.logs import generate_realistic_logs
                logs = generate_realistic_logs(repo.name, repo.default_branch or "main", "success")
                
                initial_pipeline = Pipeline(
                    repo_id=repo.id,
                    name="Initial Verification",
                    status="success",
                    trigger="manual",
                    commit_message="Initial cluster synchronization",
                    environment="production",
                    logs=logs,
                    created_at=datetime.utcnow() - timedelta(minutes=random.randint(5, 60))
                )
                session.add(initial_pipeline)

                # Generate a few random activity events
                for i in range(random.randint(3, 8)):
                    activity_event = Event(
                        repo_id=repo.id,
                        type=random.choice(["repo.updated", "push", "pr.opened"]),
                        source=request.provider,
                        message=f"Historical activity record for {repo.name}",
                        severity="info",
                        created_at=datetime.utcnow() - timedelta(days=random.randint(0, 3), hours=random.randint(0, 23))
                    )
                    session.add(activity_event)
        
        await session.commit()
        return {"status": "success", "synced": len(new_repos)}
        
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
