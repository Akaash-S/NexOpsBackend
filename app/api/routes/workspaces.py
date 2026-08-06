"""
Workspace Routes
Provides management of tenant workspace configuration and feature flags.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from datetime import datetime

from app.core.database import get_session
from app.core.security import get_current_user
from app.models.workspace import Workspace
from app.schemas.workspace_schema import WorkspaceResponse, WorkspaceUpdate

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


@router.get("/current", response_model=WorkspaceResponse)
async def get_current_workspace(
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Fetch active workspace configuration for the authenticated user."""
    try:
        user_ws_id = user.workspace_id or f"ws-{user.id[:12]}"
        result = await session.execute(select(Workspace).where(Workspace.id == user_ws_id))
        workspace = result.scalars().first()
        if not workspace:
            workspace = Workspace(
                id=user_ws_id, 
                name=f"{user.full_name or 'User'}'s Workspace", 
                show_extended_navigation=True
            )
            session.add(workspace)
            await session.commit()
            await session.refresh(workspace)

        if user.workspace_id != workspace.id:
            user.workspace_id = workspace.id
            session.add(user)
            await session.commit()

        return workspace
    except Exception as e:
        import logging
        logging.getLogger("nexops").error(f"Error fetching current workspace for user {user.id}: {e}", exc_info=True)
        fallback_id = user.workspace_id or f"ws-{user.id[:12]}"
        return Workspace(id=fallback_id, name="Personal Workspace", show_extended_navigation=True)


@router.patch("/current", response_model=WorkspaceResponse)
async def update_current_workspace(
    body: WorkspaceUpdate,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """Update active workspace configuration (e.g. show_extended_navigation feature flag)."""
    if not user.workspace_id:
        raise HTTPException(status_code=404, detail="No active workspace found for user.")
    result = await session.execute(select(Workspace).where(Workspace.id == user.workspace_id))
    workspace = result.scalars().first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(workspace, field, value)
    workspace.updated_at = datetime.utcnow()

    session.add(workspace)
    await session.commit()
    await session.refresh(workspace)
    return workspace
