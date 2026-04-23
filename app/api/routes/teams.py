"""
Team Routes
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from sqlmodel import select

from app.core.database import get_session
from app.models.team import Team
from app.schemas.user_team_schema import TeamResponse

router = APIRouter(prefix="/teams", tags=["Teams"])


@router.get("", response_model=List[TeamResponse])
async def list_teams(session: AsyncSession = Depends(get_session)):
    """List all teams."""
    result = await session.execute(select(Team))
    return list(result.scalars().all())


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(team_id: str, session: AsyncSession = Depends(get_session)):
    """Get team details."""
    team = await session.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team
