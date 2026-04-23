"""
User & Team Schemas
"""

from typing import Optional
from datetime import datetime
from .base import BaseSchema


class UserResponse(BaseSchema):
    id: str
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    role: str
    created_at: datetime


class TeamResponse(BaseSchema):
    id: str
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    member_count: int
    repo_count: int
    health_score: float
    created_at: datetime
