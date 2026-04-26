"""
Member & Invitation Routes
Endpoints for managing team access and invitations.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_session
from app.core.security import get_current_user
from app.models.user import User
from app.services import member_service, invitation_service
from app.schemas.user_team_schema import UserResponse

router = APIRouter(tags=["Team Management"])

@router.get("/workspaces/{workspace_id}/members")
async def list_workspace_members(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """List all members of a workspace."""
    # TODO: Verify current user belongs to the workspace
    return await member_service.get_workspace_members(session, workspace_id)

@router.post("/workspaces/{workspace_id}/invitations")
async def invite_to_workspace(
    workspace_id: str,
    email: str,
    role: str = "member",
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Send an invitation to join the workspace."""
    # TODO: Check if current user has ADMIN/LEAD role in workspace
    return await invitation_service.create_invitation(
        session, workspace_id, email, role, user.id
    )

@router.post("/invitations/{token}/accept")
async def accept_invite(
    token: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Accept a pending invitation."""
    success = await invitation_service.accept_invitation(session, token, user.id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation token"
        )
    return {"message": "Invitation accepted successfully"}

@router.get("/workspaces/{workspace_id}/invitations")
async def list_workspace_invitations(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """List all invitations for a workspace."""
    return await invitation_service.get_workspace_invitations(session, workspace_id)
