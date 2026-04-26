"""
Invitation Service
Handles the lifecycle of workspace invitations.
"""

import logging
from datetime import datetime
from typing import List, Optional
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.models.invitation import Invitation
from app.models.workspace_member import WorkspaceMember
from app.models.user import User

logger = logging.getLogger("nexops.invitations")

async def create_invitation(
    session: AsyncSession, 
    workspace_id: str, 
    email: str, 
    role: str, 
    invited_by_id: str
) -> Invitation:
    # Check if already a member
    user_query = select(User).where(User.email == email)
    user_result = await session.execute(user_query)
    user = user_result.scalar_one_or_none()
    
    if user:
        member_query = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id
        )
        member_result = await session.execute(member_query)
        if member_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="User is already a member of this workspace")

    # Check for existing pending invitation
    invite_query = select(Invitation).where(
        Invitation.workspace_id == workspace_id,
        Invitation.email == email,
        Invitation.status == "pending"
    )
    invite_result = await session.execute(invite_query)
    if invite_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A pending invitation already exists for this email")

    invitation = Invitation(
        workspace_id=workspace_id,
        email=email,
        role=role,
        invited_by_id=invited_by_id
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)
    
    logger.info(f"Invitation created for {email} to workspace {workspace_id}")
    return invitation

async def accept_invitation(session: AsyncSession, token: str, user_id: str) -> bool:
    query = select(Invitation).where(Invitation.token == token, Invitation.status == "pending")
    result = await session.execute(query)
    invitation = result.scalar_one_or_none()
    
    if not invitation:
        return False
    
    if invitation.expires_at < datetime.utcnow():
        invitation.status = "expired"
        session.add(invitation)
        await session.commit()
        return False

    # Create workspace member
    member = WorkspaceMember(
        workspace_id=invitation.workspace_id,
        user_id=user_id,
        role=invitation.role
    )
    session.add(member)
    
    # Update invitation status
    invitation.status = "accepted"
    invitation.accepted_at = datetime.utcnow()
    session.add(invitation)
    
    await session.commit()
    logger.info(f"User {user_id} accepted invitation to workspace {invitation.workspace_id}")
    return True

async def get_workspace_invitations(session: AsyncSession, workspace_id: str) -> List[Invitation]:
    query = select(Invitation).where(Invitation.workspace_id == workspace_id)
    result = await session.execute(query)
    return list(result.scalars().all())
