"""
Team Model
Represents groups of users and ownership of workspaces/repositories.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Team(SQLModel, table=True):
    __tablename__ = "teams"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    name: str = Field(index=True, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    
    # Simple metrics for the Teams UI
    member_count: int = Field(default=0)
    repo_count: int = Field(default=0)
    health_score: float = Field(default=100.0)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
