"""
User Routes
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from sqlmodel import select
from datetime import datetime

from app.core.database import get_session
from app.models.user import User
from app.schemas.user_team_schema import UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=List[UserResponse])
async def list_users(session: AsyncSession = Depends(get_session)):
    """List all users."""
    result = await session.execute(select(User))
    return list(result.scalars().all())


from app.core.security import get_current_user, invalidate_user_cache


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Return the currently authenticated user profile."""
    return user


@router.post("/onboarding/complete", response_model=UserResponse)
async def complete_onboarding(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Mark onboarding as complete for the current user."""
    db_user = await session.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db_user.onboarding_completed = True
    db_user.updated_at = datetime.utcnow()
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    invalidate_user_cache(user.id)
    return db_user