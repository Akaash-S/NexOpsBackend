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
from sqlmodel import select
from app.models.workspace_member import WorkspaceMember

router = APIRouter(tags=["Team Management"])

async def verify_workspace_member(session: AsyncSession, workspace_id: str, user_id: str) -> WorkspaceMember:
    """Helper to verify a user belongs to a workspace and return their membership."""
    query = select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id
    )
    result = await session.execute(query)
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You do not belong to this workspace."
        )
    return member

async def verify_workspace_admin(session: AsyncSession, workspace_id: str, user_id: str) -> WorkspaceMember:
    """Helper to verify a user is an admin or lead in a workspace."""
    member = await verify_workspace_member(session, workspace_id, user_id)
    if member.role not in ["admin", "lead"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only workspace admins or leads can perform this action."
        )
    return member

@router.get("/workspaces/{workspace_id}/members")
async def list_workspace_members(
    workspace_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """List all members of a workspace."""
    await verify_workspace_member(session, workspace_id, user.id)
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
    await verify_workspace_admin(session, workspace_id, user.id)
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
    await verify_workspace_member(session, workspace_id, user.id)
    return await invitation_service.get_workspace_invitations(session, workspace_id)

@router.delete("/workspaces/{workspace_id}/members/{user_id}")
async def revoke_member_access(
    workspace_id: str,
    user_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Revoke a user's access to the workspace."""
    await verify_workspace_admin(session, workspace_id, user.id)
    # Prevent self-revocation (optional, depends on policy)
    if user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot revoke your own access. Transfer ownership or contact another admin."
        )
    
    success = await member_service.remove_member(session, workspace_id, user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this workspace"
        )
    return {"message": "Access revoked successfully"}

@router.delete("/workspaces/{workspace_id}/invitations/{invitation_id}")
async def cancel_invitation(
    workspace_id: str,
    invitation_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Cancel a pending invitation."""
    await verify_workspace_admin(session, workspace_id, user.id)
    success = await invitation_service.cancel_invitation(session, workspace_id, invitation_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )
    return {"message": "Invitation cancelled successfully"}
