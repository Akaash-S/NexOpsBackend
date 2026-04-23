"""
User Routes
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from sqlmodel import select

from app.core.database import get_session
from app.models.user import User
from app.schemas.user_team_schema import UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=List[UserResponse])
async def list_users(session: AsyncSession = Depends(get_session)):
    """List all users."""
    result = await session.execute(select(User))
    return list(result.scalars().all())


@router.get("/me", response_model=UserResponse)
async def get_current_user(session: AsyncSession = Depends(get_session)):
    """Mock endpoint for the current logged-in user."""
    # Return the first user as a mock for 'me'
    result = await session.execute(select(User).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="No users found")
    return user
