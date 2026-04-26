"""
Member Service
Manages workspace membership and roles.
"""

from typing import List, Optional
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.workspace_member import WorkspaceMember
from app.models.user import User

async def get_workspace_members(session: AsyncSession, workspace_id: str):
    """Return all members of a workspace with their user details."""
    query = (
        select(User, WorkspaceMember.role, WorkspaceMember.joined_at)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    result = await session.execute(query)
    
    members = []
    for user, role, joined_at in result.all():
        members.append({
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "role": role,
            "joined_at": joined_at
        })
    return members

async def update_member_role(session: AsyncSession, workspace_id: str, user_id: str, new_role: str):
    query = select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id
    )
    result = await session.execute(query)
    member = result.scalar_one_or_none()
    
    if not member:
        return False
    
    member.role = new_role
    session.add(member)
    await session.commit()
    return True

async def remove_member(session: AsyncSession, workspace_id: str, user_id: str):
    query = select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id
    )
    result = await session.execute(query)
    member = result.scalar_one_or_none()
    
    if not member:
        return False
    
    await session.delete(member)
    await session.commit()
    return True
