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


from app.core.security import get_current_user


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Return the currently authenticated user profile."""
    return user
